"""Owner assignment and the stopped-matching contradiction path (sections 23, 23.1 line 1401)."""

from __future__ import annotations

import pytest

from apps.exceptions.detectors import revenue_unbilled as det
from apps.exceptions.models import CaseState, ExceptionCase, ExceptionSourceLink
from apps.exceptions.services import runs, transitions
from apps.exceptions.services.transitions import StaleVersion, TransitionError, TransitionRequest
from apps.ingestion.models import ReconciliationRun
from apps.organizations.models import Membership
from apps.organizations.policy import Denied
from tests.phase4_helpers import AS_OF, invoice_csv_with_star_invoice, load_atlas, seed_atlas

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


def clone_run(atlas, key, manifest_char):  # type: ignore[no-untyped-def]
    run = ReconciliationRun.objects.create(
        organization=atlas.organization,
        run_key=key,
        as_of=AS_OF,
        status="ready",
        became_ready_at=AS_OF,
        input_manifest_sha256=manifest_char * 64,
    )
    for run_input in atlas.run.inputs.all():
        clone = run.inputs.create(
            organization=atlas.organization,
            domain=run_input.domain,
            import_batch=run_input.import_batch,
        )
        clone.coverage_declarations.set(run_input.coverage_declarations.all())
    return run


class TestAssignOwner:
    def test_finance_reviewer_assigns_an_owner(self, atlas) -> None:  # type: ignore[no-untyped-def]
        finance = member(atlas.organization, "finance@atlas.example")
        ops = member(atlas.organization, "ops@atlas.example")
        case = transitions.assign_owner(
            membership=finance,
            case_id=atlas.case.id,
            expected_version=atlas.case.version,
            owner_membership_id=ops.id,
        )
        assert case.owner_membership_id == ops.id
        assert case.version == 2
        assert case.state == CaseState.NEW  # ownership is not a transition
        assert case.events.filter(event_type="owner_assigned").count() == 1

    def test_stale_version_is_refused(self, atlas) -> None:  # type: ignore[no-untyped-def]
        finance = member(atlas.organization, "finance@atlas.example")
        with pytest.raises(StaleVersion):
            transitions.assign_owner(
                membership=finance,
                case_id=atlas.case.id,
                expected_version=99,
                owner_membership_id=finance.id,
            )

    @pytest.mark.parametrize("email", ["auditor@atlas.example", "supervisor@atlas.example"])
    def test_denied_roles_cannot_assign(self, atlas, email) -> None:  # type: ignore[no-untyped-def]
        actor = member(atlas.organization, email)
        with pytest.raises(Denied):
            transitions.assign_owner(
                membership=actor,
                case_id=atlas.case.id,
                expected_version=atlas.case.version,
                owner_membership_id=actor.id,
            )

    def test_cannot_assign_a_member_of_another_tenant(self, atlas) -> None:  # type: ignore[no-untyped-def]
        finance = member(atlas.organization, "finance@atlas.example")
        foreign = Membership.objects.get(user__email="owner@beacon.example")
        with pytest.raises(TransitionError):
            transitions.assign_owner(
                membership=finance,
                case_id=atlas.case.id,
                expected_version=atlas.case.version,
                owner_membership_id=foreign.id,
            )

    def test_cannot_reassign_a_terminal_case(self, atlas) -> None:  # type: ignore[no-untyped-def]
        finance = member(atlas.organization, "finance@atlas.example")
        case = transitions.transition(
            membership=finance,
            req=TransitionRequest(
                case_id=atlas.case.id,
                expected_version=atlas.case.version,
                to_state=CaseState.DISMISSED,
                reason_code="false_positive",
                note="x",
            ),
        )
        with pytest.raises(TransitionError):
            transitions.assign_owner(
                membership=finance,
                case_id=case.id,
                expected_version=case.version,
                owner_membership_id=finance.id,
            )

    def test_cross_tenant_case_id_raises_does_not_exist(self, atlas) -> None:  # type: ignore[no-untyped-def]
        foreign = Membership.objects.get(user__email="owner@beacon.example")
        with pytest.raises(ExceptionCase.DoesNotExist):
            transitions.assign_owner(
                membership=foreign,
                case_id=atlas.case.id,
                expected_version=1,
                owner_membership_id=foreign.id,
            )


class TestContradictionPath:
    """Line 1401: a later invoice flags the open case for finance review; state is untouched."""

    def _later_invoice_run(self, atlas):  # type: ignore[no-untyped-def]
        """Re-import accounting WITH an invoice for the star case, attach to a new run."""
        import datetime as dt

        from apps.ingestion.models import DataSource
        from apps.ingestion.services import coverage as coverage_service
        from apps.ingestion.services import imports as import_service

        source = DataSource.objects.get(organization=atlas.organization, system_key="ar_ledger")
        result = import_service.upload(
            organization=atlas.organization,
            source=source,
            kind="invoice_status",
            filename="invoice_status.csv",
            payload=invoice_csv_with_star_invoice(status="posted"),
            observation_mode="full_snapshot",
            source_as_of_at=AS_OF + dt.timedelta(days=1),
            declarations=[
                coverage_service.CoverageDeclaration(
                    record_family="accounting_invoice",
                    scope_type="organization",
                    coverage_start_at=dt.datetime(2026, 1, 1, tzinfo=dt.UTC),
                    coverage_end_at=dt.datetime(2027, 1, 1, tzinfo=dt.UTC),
                    query_contract_code="ACCOUNTING_SERVICE_DATE_LEDGER_V1",
                    query_contract_version=1,
                    completeness="complete",
                    declaration_basis="synthetic_fixture",
                )
            ],
            actor=atlas.actor,
        )
        batch = import_service.commit(result.batch, atlas.actor)
        run = clone_run(atlas, "later-invoice", "f")
        acct = run.inputs.get(domain="invoice_status")
        acct.import_batch = batch
        acct.save()
        acct.coverage_declarations.set(batch.coverage_declarations.all())
        return run

    def test_a_later_invoice_flags_the_open_case_without_changing_state(self, atlas) -> None:  # type: ignore[no-untyped-def]
        assert atlas.case.state == CaseState.NEW
        run = self._later_invoice_run(atlas)
        detector_run = runs.evaluate_and_persist(run=run, detector_code=det.RULE_CODE, as_of=AS_OF)

        atlas.case.refresh_from_db()
        assert atlas.case.state == CaseState.NEW, "the detector must never change state"
        assert atlas.case.recommended_next_action == "finance_review_contradiction"
        assert "invoice_present" in atlas.case.recommended_next_action_explanation
        assert atlas.case.last_refreshed_by_run_id == detector_run.id
        assert detector_run.updated_count == 1 and detector_run.created_count == 0

    def test_contradiction_writes_a_timeline_event_with_the_reason(self, atlas) -> None:  # type: ignore[no-untyped-def]
        run = self._later_invoice_run(atlas)
        runs.evaluate_and_persist(run=run, detector_code=det.RULE_CODE, as_of=AS_OF)
        event = atlas.case.events.get(event_type="contradicted")
        assert event.reason_code == "invoice_present"
        assert event.actor_kind == "detector"
        assert event.metadata["skip_reason"] == "invoice_present"

    def test_contradiction_links_the_invoice_as_contradicting_evidence(self, atlas) -> None:  # type: ignore[no-untyped-def]
        run = self._later_invoice_run(atlas)
        runs.evaluate_and_persist(run=run, detector_code=det.RULE_CODE, as_of=AS_OF)
        links = atlas.case.source_links.filter(
            relationship=ExceptionSourceLink.Relationship.CONTRADICTING
        )
        assert links.count() >= 1
        assert all(link.source_record_version.record_type == "accounting_invoice" for link in links)

    def test_contradiction_is_recorded_once_per_run_not_per_replay(self, atlas) -> None:  # type: ignore[no-untyped-def]
        run = self._later_invoice_run(atlas)
        runs.evaluate_and_persist(run=run, detector_code=det.RULE_CODE, as_of=AS_OF)
        runs.evaluate_and_persist(
            run=run, detector_code=det.RULE_CODE, as_of=AS_OF
        )  # duplicate delivery
        assert atlas.case.events.filter(event_type="contradicted").count() == 1

    def test_finance_then_resolves_it_through_the_transition_service(self, atlas) -> None:  # type: ignore[no-untyped-def]
        run = self._later_invoice_run(atlas)
        runs.evaluate_and_persist(run=run, detector_code=det.RULE_CODE, as_of=AS_OF)
        finance = member(atlas.organization, "finance@atlas.example")
        atlas.case.refresh_from_db()
        case = transitions.transition(
            membership=finance,
            req=TransitionRequest(
                case_id=atlas.case.id,
                expected_version=atlas.case.version,
                to_state=CaseState.DISMISSED,
                reason_code="already_invoiced",
                note="Invoice 3450 found in the ledger.",
            ),
        )
        assert case.state == CaseState.DISMISSED
        assert case.dismissal_code == "already_invoiced"

    def test_a_terminal_case_is_not_contradicted(self, atlas) -> None:  # type: ignore[no-untyped-def]
        finance = member(atlas.organization, "finance@atlas.example")
        transitions.transition(
            membership=finance,
            req=TransitionRequest(
                case_id=atlas.case.id,
                expected_version=atlas.case.version,
                to_state=CaseState.DISMISSED,
                reason_code="false_positive",
                note="x",
            ),
        )
        run = self._later_invoice_run(atlas)
        runs.evaluate_and_persist(run=run, detector_code=det.RULE_CODE, as_of=AS_OF)
        assert atlas.case.events.filter(event_type="contradicted").count() == 0


class TestFreshnessRollup:
    @pytest.mark.parametrize(
        "freshness,expected",
        [
            ({"a": "fresh", "b": "fresh"}, "fresh"),
            ({"a": "fresh", "b": "aging"}, "aging"),
            ({"a": "stale", "b": "fresh"}, "stale"),
            ({"a": "unknown", "b": "fresh"}, "unknown"),
            ({"a": "stale", "b": "unknown"}, "stale"),
        ],
    )
    def test_worst_level_wins(self, freshness, expected) -> None:  # type: ignore[no-untyped-def]
        assert runs._overall(freshness) == expected
