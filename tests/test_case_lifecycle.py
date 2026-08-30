"""State machine, transition service, audit, idempotency, and concurrency (sections 23, 33.4)."""

from __future__ import annotations

import threading

import pytest
from django.db import connection

from apps.audit.models import AppendOnlyError as AuditAppendOnly
from apps.audit.models import AuditEvent
from apps.exceptions.detectors import revenue_unbilled as det
from apps.exceptions.models import (
    AppendOnlyError,
    CaseState,
    DirectStateChangeError,
    ExceptionCase,
    ExceptionEvent,
    FinancialImpactSnapshot,
    FinancialRecoveryItem,
)
from apps.exceptions.services import runs, transitions
from apps.exceptions.services.transitions import StaleVersion, TransitionError, TransitionRequest
from apps.organizations.models import Membership
from apps.organizations.policy import Denied
from tests.phase4_helpers import AS_OF, load_atlas, seed_atlas

pytestmark = pytest.mark.django_db


@pytest.fixture
def atlas(settings):  # type: ignore[no-untyped-def]
    settings.APP_ENV = "local"
    organization, actor = seed_atlas()
    loaded = load_atlas(organization, actor)
    loaded.detector_run = runs.evaluate_and_persist(
        run=loaded.run, detector_code=det.RULE_CODE, as_of=AS_OF
    )
    loaded.case = ExceptionCase.objects.get(organization=organization)
    return loaded


def member(organization, email):  # type: ignore[no-untyped-def]
    return Membership.objects.get(organization=organization, user__email=email)


def req(case, to_state, **kw):  # type: ignore[no-untyped-def]
    return TransitionRequest(
        case_id=case.id, expected_version=case.version, to_state=to_state, **kw
    )


class TestPersistence:
    def test_one_case_one_snapshot_one_recovery_item(self, atlas) -> None:  # type: ignore[no-untyped-def]
        assert ExceptionCase.objects.count() == 1
        assert FinancialImpactSnapshot.objects.count() == 1
        assert FinancialRecoveryItem.objects.count() == 1
        assert atlas.case.state == CaseState.NEW
        assert atlas.case.case_number == "REV-00001"

    def test_detection_writes_one_timeline_event_and_one_audit_event(self, atlas) -> None:  # type: ignore[no-untyped-def]
        assert atlas.case.events.filter(event_type="detected").count() == 1
        assert AuditEvent.objects.filter(action="case.detected").count() == 1
        event = atlas.case.events.get()
        assert event.actor_kind == "detector"
        assert event.actor_rule == f"{det.RULE_CODE}:v{det.RULE_VERSION}"

    def test_recovery_item_is_candidate_stage_only(self, atlas) -> None:  # type: ignore[no-untyped-def]
        item = atlas.case.recovery_item
        assert item.workflow_state == FinancialRecoveryItem.WorkflowState.CANDIDATE
        assert item.current_invoice_ready_snapshot is None
        assert item.actual_invoiced_amount is None
        assert item.export_reference == ""


class TestIdempotency:
    def test_rerunning_the_detector_creates_nothing_new(self, atlas) -> None:  # type: ignore[no-untyped-def]
        second = runs.evaluate_and_persist(run=atlas.run, detector_code=det.RULE_CODE, as_of=AS_OF)
        assert second.id == atlas.detector_run.id
        assert ExceptionCase.objects.count() == 1
        assert FinancialImpactSnapshot.objects.count() == 1
        assert ExceptionEvent.objects.filter(event_type="detected").count() == 1

    def test_a_new_manifest_refreshes_the_case_rather_than_duplicating_it(self, atlas) -> None:  # type: ignore[no-untyped-def]
        """A corrected manifest is a NEW evaluation but the SAME case (same fingerprint)."""
        from apps.ingestion.models import ReconciliationRun

        run2 = ReconciliationRun.objects.create(
            organization=atlas.organization,
            run_key="second",
            as_of=AS_OF,
            status="ready",
            became_ready_at=AS_OF,
            input_manifest_sha256="b" * 64,
        )
        for run_input in atlas.run.inputs.all():
            clone = run2.inputs.create(
                organization=atlas.organization,
                domain=run_input.domain,
                import_batch=run_input.import_batch,
            )
            clone.coverage_declarations.set(run_input.coverage_declarations.all())
        second = runs.evaluate_and_persist(run=run2, detector_code=det.RULE_CODE, as_of=AS_OF)
        assert second.id != atlas.detector_run.id
        assert second.updated_count == 1 and second.created_count == 0
        assert ExceptionCase.objects.count() == 1
        assert ExceptionCase.objects.get().last_refreshed_by_run_id == second.id

    def test_unchanged_value_appends_no_snapshot(self, atlas) -> None:  # type: ignore[no-untyped-def]
        runs.evaluate_and_persist(run=atlas.run, detector_code=det.RULE_CODE, as_of=AS_OF)
        assert atlas.case.financial_snapshots.count() == 1

    def test_a_terminal_case_is_not_reopened_by_the_detector(self, atlas) -> None:  # type: ignore[no-untyped-def]
        finance = member(atlas.organization, "finance@atlas.example")
        transitions.transition(membership=finance, req=req(atlas.case, CaseState.ACKNOWLEDGED))
        atlas.case.refresh_from_db()
        transitions.transition(
            membership=finance,
            req=req(atlas.case, CaseState.DISMISSED, reason_code="false_positive", note="reviewed"),
        )
        from apps.ingestion.models import ReconciliationRun

        run2 = ReconciliationRun.objects.create(
            organization=atlas.organization,
            run_key="after",
            as_of=AS_OF,
            status="ready",
            became_ready_at=AS_OF,
            input_manifest_sha256="c" * 64,
        )
        for run_input in atlas.run.inputs.all():
            clone = run2.inputs.create(
                organization=atlas.organization,
                domain=run_input.domain,
                import_batch=run_input.import_batch,
            )
            clone.coverage_declarations.set(run_input.coverage_declarations.all())
        runs.evaluate_and_persist(run=run2, detector_code=det.RULE_CODE, as_of=AS_OF)
        atlas.case.refresh_from_db()
        assert atlas.case.state == CaseState.DISMISSED
        assert ExceptionCase.objects.count() == 1


class TestStateMachine:
    def test_finance_reviewer_can_acknowledge_a_revenue_case(self, atlas) -> None:  # type: ignore[no-untyped-def]
        finance = member(atlas.organization, "finance@atlas.example")
        case = transitions.transition(
            membership=finance, req=req(atlas.case, CaseState.ACKNOWLEDGED)
        )
        assert case.state == CaseState.ACKNOWLEDGED
        assert case.version == 2
        assert case.first_acknowledged_at is not None
        assert case.owner_membership_id == finance.id  # explicit self-assignment

    def test_operations_manager_can_acknowledge_but_not_resolve(self, atlas) -> None:  # type: ignore[no-untyped-def]
        ops = member(atlas.organization, "ops@atlas.example")
        case = transitions.transition(membership=ops, req=req(atlas.case, CaseState.ACKNOWLEDGED))
        with pytest.raises(Denied):
            transitions.transition(
                membership=ops,
                req=req(case, CaseState.RESOLVED, reason_code="source_corrected", note="x"),
            )

    @pytest.mark.parametrize("email", ["supervisor@atlas.example", "auditor@atlas.example"])
    def test_supervisor_and_auditor_cannot_act_on_a_revenue_case(self, atlas, email) -> None:  # type: ignore[no-untyped-def]
        with pytest.raises(Denied):
            transitions.transition(
                membership=member(atlas.organization, email),
                req=req(atlas.case, CaseState.ACKNOWLEDGED),
            )

    def test_finance_reviewer_can_resolve_with_a_valid_code(self, atlas) -> None:  # type: ignore[no-untyped-def]
        finance = member(atlas.organization, "finance@atlas.example")
        case = transitions.transition(
            membership=finance, req=req(atlas.case, CaseState.ACKNOWLEDGED)
        )
        case = transitions.transition(
            membership=finance,
            req=req(
                case,
                CaseState.RESOLVED,
                reason_code="source_corrected",
                note="Invoice found in the ledger.",
            ),
        )
        assert case.state == CaseState.RESOLVED
        assert case.resolved_at is not None
        assert case.resolution_code == "source_corrected"

    def test_resolution_requires_a_revenue_appropriate_code(self, atlas) -> None:  # type: ignore[no-untyped-def]
        finance = member(atlas.organization, "finance@atlas.example")
        case = transitions.transition(
            membership=finance, req=req(atlas.case, CaseState.ACKNOWLEDGED)
        )
        with pytest.raises(TransitionError):
            transitions.transition(
                membership=finance,
                req=req(case, CaseState.RESOLVED, reason_code="replacement_confirmed", note="x"),
            )  # Journey A code

    def test_resolution_requires_a_note(self, atlas) -> None:  # type: ignore[no-untyped-def]
        finance = member(atlas.organization, "finance@atlas.example")
        case = transitions.transition(
            membership=finance, req=req(atlas.case, CaseState.ACKNOWLEDGED)
        )
        with pytest.raises(TransitionError):
            transitions.transition(
                membership=finance,
                req=req(case, CaseState.RESOLVED, reason_code="source_corrected", note="  "),
            )

    def test_dismissal_from_new_with_already_invoiced(self, atlas) -> None:  # type: ignore[no-untyped-def]
        finance = member(atlas.organization, "finance@atlas.example")
        case = transitions.transition(
            membership=finance,
            req=req(
                atlas.case,
                CaseState.DISMISSED,
                reason_code="already_invoiced",
                note="Found invoice 3450.",
            ),
        )
        assert case.state == CaseState.DISMISSED
        assert case.dismissal_code == "already_invoiced"

    def test_illegal_edge_is_refused(self, atlas) -> None:  # type: ignore[no-untyped-def]
        owner = member(atlas.organization, "owner@atlas.example")
        with pytest.raises(TransitionError):
            transitions.transition(
                membership=owner, req=req(atlas.case, CaseState.WAITING_EXTERNAL)
            )

    def test_terminal_state_has_no_exit(self, atlas) -> None:  # type: ignore[no-untyped-def]
        owner = member(atlas.organization, "owner@atlas.example")
        case = transitions.transition(
            membership=owner,
            req=req(atlas.case, CaseState.DISMISSED, reason_code="false_positive", note="x"),
        )
        with pytest.raises(TransitionError):
            transitions.transition(membership=owner, req=req(case, CaseState.ACKNOWLEDGED))

    def test_escalation_requires_a_target_owner(self, atlas) -> None:  # type: ignore[no-untyped-def]
        owner = member(atlas.organization, "owner@atlas.example")
        case = transitions.transition(membership=owner, req=req(atlas.case, CaseState.ACKNOWLEDGED))
        with pytest.raises(TransitionError):
            transitions.transition(
                membership=owner, req=req(case, CaseState.ESCALATED, note="urgent")
            )

    def test_owner_cannot_be_assigned_from_another_tenant(self, atlas) -> None:  # type: ignore[no-untyped-def]
        owner = member(atlas.organization, "owner@atlas.example")
        foreign = Membership.objects.get(user__email="owner@beacon.example")
        case = transitions.transition(membership=owner, req=req(atlas.case, CaseState.ACKNOWLEDGED))
        with pytest.raises(TransitionError):
            transitions.transition(
                membership=owner,
                req=req(case, CaseState.ESCALATED, note="x", owner_membership_id=foreign.id),
            )


class TestDirectStateChangeIsImpossible:
    def test_setting_state_on_the_model_raises(self, atlas) -> None:  # type: ignore[no-untyped-def]
        atlas.case.state = CaseState.RESOLVED
        with pytest.raises(DirectStateChangeError):
            atlas.case.save()

    def test_queryset_update_is_the_only_bypass_and_is_greppable(self) -> None:
        """QuerySet.update() skips save(). Assert no application code uses it on state."""
        import re
        from pathlib import Path

        from django.conf import settings

        offenders = []
        for path in (Path(settings.BASE_DIR) / "apps").rglob("*.py"):
            text = path.read_text()
            if re.search(r"ExceptionCase\.objects[^\n]*\.update\([^)]*state=", text):
                offenders.append(str(path))
        assert not offenders, offenders


class TestOptimisticConcurrency:
    def test_stale_version_is_rejected(self, atlas) -> None:  # type: ignore[no-untyped-def]
        finance = member(atlas.organization, "finance@atlas.example")
        stale = req(atlas.case, CaseState.ACKNOWLEDGED)  # captures version 1
        transitions.transition(membership=finance, req=stale)
        with pytest.raises(StaleVersion):
            transitions.transition(membership=finance, req=stale)  # version is now 2

    @pytest.mark.django_db(transaction=True)
    def test_two_concurrent_transitions_only_one_wins(self, atlas) -> None:  # type: ignore[no-untyped-def]
        """Real threads, real connections: select_for_update + version predicate.

        Marked transaction=True so fixture rows are COMMITTED and visible to the
        worker threads' own connections; inside the default per-test transaction the
        threads would see an empty table and the test would prove nothing.
        """
        finance = member(atlas.organization, "finance@atlas.example")
        owner = member(atlas.organization, "owner@atlas.example")
        request = req(atlas.case, CaseState.ACKNOWLEDGED)
        outcomes: list[str] = []
        barrier = threading.Barrier(2)

        def attempt(membership):  # type: ignore[no-untyped-def]
            try:
                barrier.wait(timeout=5)
                transitions.transition(membership=membership, req=request)
                outcomes.append("won")
            except StaleVersion:
                outcomes.append("stale")
            finally:
                connection.close()

        threads = [threading.Thread(target=attempt, args=(m,)) for m in (finance, owner)]
        for t in threads:
            t.start()
        for t in threads:
            t.join(timeout=15)
        assert sorted(outcomes) == ["stale", "won"], outcomes
        atlas.case.refresh_from_db()
        assert atlas.case.version == 2
        assert atlas.case.events.filter(event_type="transition").count() == 1


class TestAuditAndTimeline:
    def test_transition_writes_timeline_and_audit_in_one_transaction(self, atlas) -> None:  # type: ignore[no-untyped-def]
        finance = member(atlas.organization, "finance@atlas.example")
        transitions.transition(membership=finance, req=req(atlas.case, CaseState.ACKNOWLEDGED))
        event = atlas.case.events.get(event_type="transition")
        assert (event.from_state, event.to_state) == (CaseState.NEW, CaseState.ACKNOWLEDGED)
        assert event.actor_membership_id == finance.id
        assert event.case_version == 2
        audit = AuditEvent.objects.get(action="case.transition.acknowledged")
        assert audit.metadata["from_state"] == "new"

    def test_a_failed_transition_writes_no_event(self, atlas) -> None:  # type: ignore[no-untyped-def]
        finance = member(atlas.organization, "finance@atlas.example")
        before = (ExceptionEvent.objects.count(), AuditEvent.objects.count())
        with pytest.raises(TransitionError):
            transitions.transition(
                membership=finance, req=req(atlas.case, CaseState.WAITING_EXTERNAL)
            )
        assert (ExceptionEvent.objects.count(), AuditEvent.objects.count()) == before

    def test_timeline_events_cannot_be_updated_or_deleted(self, atlas) -> None:  # type: ignore[no-untyped-def]
        event = atlas.case.events.get()
        event.note = "tampered"
        with pytest.raises(AppendOnlyError):
            event.save()
        with pytest.raises(AppendOnlyError):
            event.delete()

    def test_audit_events_cannot_be_updated_or_deleted(self, atlas) -> None:  # type: ignore[no-untyped-def]
        audit = AuditEvent.objects.first()
        audit.action = "tampered"
        with pytest.raises(AuditAppendOnly):
            audit.save()
        with pytest.raises(AuditAppendOnly):
            audit.delete()

    def test_audit_metadata_rejects_non_allowlisted_keys(self, atlas) -> None:  # type: ignore[no-untyped-def]
        from django.core.exceptions import ValidationError

        from apps.audit.models import record

        with pytest.raises(ValidationError):
            record(
                organization=atlas.organization,
                action="x",
                object_type="y",
                object_id=atlas.case.id,
                actor_rule="SYSTEM:test",
                metadata={"raw_row": {"ssn": "123-45-6789"}},
            )

    def test_exactly_one_actor_is_enforced_by_the_database(self, atlas) -> None:  # type: ignore[no-untyped-def]
        from django.db import IntegrityError, transaction

        finance = member(atlas.organization, "finance@atlas.example")
        with pytest.raises(IntegrityError), transaction.atomic():
            ExceptionEvent.objects.create(
                organization=atlas.organization,
                exception_case=atlas.case,
                event_type="bad",
                actor_kind="detector",
                actor_membership=finance,
                actor_rule="R",
                case_version=1,
            )


class TestSnapshotImmutability:
    def test_snapshot_values_cannot_be_edited(self, atlas) -> None:  # type: ignore[no-untyped-def]
        from decimal import Decimal

        snapshot = atlas.case.financial_snapshots.get()
        snapshot.candidate_value = Decimal("999")
        with pytest.raises(AppendOnlyError):
            snapshot.save()

    def test_a_changed_amount_appends_version_two(self, atlas) -> None:  # type: ignore[no-untyped-def]
        from decimal import Decimal

        from apps.ingestion.models import ReconciliationRun

        wo = atlas.case.work_order
        wo.approved_fixed_amount = Decimal("525.00")
        wo.save()
        run2 = ReconciliationRun.objects.create(
            organization=atlas.organization,
            run_key="v2",
            as_of=AS_OF,
            status="ready",
            became_ready_at=AS_OF,
            input_manifest_sha256="d" * 64,
        )
        for run_input in atlas.run.inputs.all():
            clone = run2.inputs.create(
                organization=atlas.organization,
                domain=run_input.domain,
                import_batch=run_input.import_batch,
            )
            clone.coverage_declarations.set(run_input.coverage_declarations.all())
        runs.evaluate_and_persist(run=run2, detector_code=det.RULE_CODE, as_of=AS_OF)
        versions = list(atlas.case.financial_snapshots.order_by("snapshot_version"))
        assert [v.snapshot_version for v in versions] == [1, 2]
        assert versions[0].candidate_value == Decimal("480.0000")  # history preserved
        assert versions[1].candidate_value == Decimal("525.0000")
        assert atlas.case.recovery_item.current_candidate_snapshot_id == versions[1].id
