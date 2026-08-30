"""The ten-item evidence checklist and the approval it gates (section 6, lines 2707-2718).

Every item gets a test that breaks exactly that item and asserts approval is blocked
with THAT code — so a checklist that always fails, or one that fails for the wrong
reason, cannot pass this suite.
"""

from __future__ import annotations

import datetime as dt
from decimal import Decimal

import pytest

from apps.exceptions.models import FinancialImpactSnapshot, FinancialRecoveryItem
from apps.ingestion.models import ExternalEntityReference
from apps.operations.models import AccountingInvoice
from apps.organizations.policy import Denied
from apps.recovery.models import Approval, FinancialStageEvent
from apps.recovery.services import approvals
from apps.recovery.services.checklist import ITEM_CODES
from tests.phase6_helpers import loaded_atlas

pytestmark = pytest.mark.django_db


@pytest.fixture
def atlas(settings):  # type: ignore[no-untyped-def]
    settings.APP_ENV = "local"
    return loaded_atlas()


def approve(atlas, membership=None):  # type: ignore[no-untyped-def]
    atlas.item.refresh_from_db()
    return approvals.approve_invoice_ready(
        membership=membership or atlas.finance,
        req=approvals.ApprovalRequest(item_id=atlas.item.id, expected_version=atlas.item.version),
    )


class TestChecklistPassesWhenEvidenceIsComplete:
    def test_all_ten_items_present_for_the_star_case(self, atlas) -> None:  # type: ignore[no-untyped-def]
        checklist = approvals.build_checklist(atlas.item, membership=atlas.finance)
        assert len(checklist.items) == 10
        assert [i.code for i in checklist.items] == list(ITEM_CODES)
        assert checklist.is_complete, checklist.missing_codes

    def test_approval_succeeds_and_records_the_evidence_it_saw(self, atlas) -> None:  # type: ignore[no-untyped-def]
        approval = approve(atlas)
        assert approval.decision == Approval.Decision.APPROVED
        assert approval.approval_type == Approval.ApprovalType.INVOICE_READY
        assert approval.evidence_snapshot["complete"] is True
        assert len(approval.evidence_snapshot["items"]) == 10

    def test_approval_moves_the_item_and_writes_a_stage_event(self, atlas) -> None:  # type: ignore[no-untyped-def]
        approve(atlas)
        atlas.item.refresh_from_db()
        assert atlas.item.workflow_state == FinancialRecoveryItem.WorkflowState.INVOICE_READY
        event = atlas.item.stage_events.get(kind=FinancialStageEvent.Kind.WORKFLOW)
        assert (event.from_value, event.to_value) == ("candidate", "invoice_ready")
        assert event.actor_membership_id == atlas.finance.id

    def test_invoice_ready_value_is_a_new_immutable_snapshot(self, atlas) -> None:  # type: ignore[no-untyped-def]
        approve(atlas)
        snapshots = list(atlas.case.financial_snapshots.order_by("snapshot_version"))
        assert [s.snapshot_version for s in snapshots] == [1, 2]
        assert snapshots[0].invoice_ready_value is None  # candidate stage only
        assert snapshots[1].invoice_ready_value == Decimal("480.0000")
        assert snapshots[1].candidate_value == Decimal("480.0000")
        assert snapshots[1].approved_by_id == atlas.finance.id


class TestEachChecklistItemBlocksIndependently:
    """Break one item, assert approval fails naming THAT item."""

    def _assert_blocked(self, atlas, code: str) -> None:  # type: ignore[no-untyped-def]
        with pytest.raises(approvals.EvidenceIncomplete) as exc:
            approve(atlas)
        assert code in exc.value.checklist.missing_codes, exc.value.checklist.missing_codes

    def test_missing_source_identity(self, atlas) -> None:  # type: ignore[no-untyped-def]
        ExternalEntityReference.objects.filter(
            organization=atlas.organization, entity_type="work_order"
        ).update(mapping_status=ExternalEntityReference.MappingStatus.SUPERSEDED)
        self._assert_blocked(atlas, ITEM_CODES[0])

    def test_not_completed(self, atlas) -> None:  # type: ignore[no-untyped-def]
        work_order = atlas.item.work_order
        work_order.status = work_order.Status.IN_PROGRESS
        work_order.save()
        self._assert_blocked(atlas, ITEM_CODES[1])

    def test_contract_not_active_on_the_service_date(self, atlas) -> None:  # type: ignore[no-untyped-def]
        contract = atlas.item.work_order.contract
        contract.status = contract.Status.ENDED
        contract.save()
        self._assert_blocked(atlas, ITEM_CODES[2])

    def test_unconfirmed_crosswalk(self, atlas) -> None:  # type: ignore[no-untyped-def]
        ExternalEntityReference.objects.filter(
            organization=atlas.organization, entity_type="site"
        ).update(mapping_status=ExternalEntityReference.MappingStatus.UNRESOLVED, site=None)
        self._assert_blocked(atlas, ITEM_CODES[3])

    def test_not_billable(self, atlas) -> None:  # type: ignore[no-untyped-def]
        work_order = atlas.item.work_order
        work_order.billable = False
        work_order.save()
        self._assert_blocked(atlas, ITEM_CODES[4])

    def test_authorization_required_but_absent(self, atlas) -> None:  # type: ignore[no-untyped-def]
        work_order = atlas.item.work_order
        work_order.authorization_reference = ""
        work_order.authorized_at = None
        work_order.save()
        self._assert_blocked(atlas, ITEM_CODES[5])

    def test_manual_amount_required_blocks_approval(self, atlas) -> None:  # type: ignore[no-untyped-def]
        """The single most important money test.

        A candidate whose amount could not be computed must NEVER be approvable. If the
        checklist treated a null value as zero — or as merely 'no objection' — this
        would approve a $0 invoice-ready item and the export would hand a bookkeeper a
        zero-value line. Section 22.5: unknown is NULL, not zero.
        """
        snapshot = atlas.item.current_candidate_snapshot
        blank = FinancialImpactSnapshot.objects.create(
            organization=atlas.organization,
            exception_case=atlas.case,
            snapshot_version=snapshot.snapshot_version + 1,
            calculation_code=snapshot.calculation_code,
            calculation_version=snapshot.calculation_version,
            currency="USD",
            candidate_value=None,
            basis=FinancialImpactSnapshot.Basis.MANUAL_AMOUNT_REQUIRED,
            assumptions={"missing": "approved_fixed_amount"},
            calculated_by_rule="test",
        )
        atlas.item.current_candidate_snapshot = blank
        atlas.item.save()
        self._assert_blocked(atlas, ITEM_CODES[6])

    def test_an_invoice_arriving_after_detection_blocks_approval(self, atlas) -> None:  # type: ignore[no-untyped-def]
        """Section 23.1 line 1401 contemplates exactly this. Approving on a stale
        absence would be the false positive the product exists to avoid."""
        work_order = atlas.item.work_order
        AccountingInvoice.objects.create(
            organization=atlas.organization,
            customer=work_order.customer,
            site=work_order.site,
            service_date=atlas.case.service_date,
            invoice_reference="LATE-1",
            invoice_amount=Decimal("480.00"),
            invoiced_at=dt.datetime(2026, 8, 19, tzinfo=dt.UTC),
            currency="USD",
            source_status=AccountingInvoice.SourceStatus.POSTED,
            source_as_of_at=dt.datetime(2026, 8, 19, tzinfo=dt.UTC),
        )
        self._assert_blocked(atlas, ITEM_CODES[7])

    def test_already_exported_blocks_a_second_approval(self, atlas) -> None:  # type: ignore[no-untyped-def]
        atlas.item.workflow_state = FinancialRecoveryItem.WorkflowState.EXPORTED
        atlas.item.save()
        with pytest.raises(approvals.ApprovalError):
            approve(atlas)

    def test_non_finance_role_fails_item_ten(self, atlas) -> None:  # type: ignore[no-untyped-def]
        checklist = approvals.build_checklist(atlas.item, membership=atlas.ops)
        assert checklist.missing_codes == [ITEM_CODES[9]]


class TestNoBypassExists:
    def test_the_service_builds_its_own_checklist(self) -> None:
        """A caller cannot hand in a passing checklist: the signature has no slot for one."""
        import inspect

        parameters = set(inspect.signature(approvals.approve_invoice_ready).parameters)
        assert parameters == {"membership", "req"}
        request_fields = set(approvals.ApprovalRequest.__dataclass_fields__)
        assert request_fields == {"item_id", "expected_version", "reason", "request_id"}
        for forbidden in ("force", "skip_checklist", "override", "bypass", "ignore_evidence"):
            assert forbidden not in request_fields

    def test_no_bypass_flag_appears_anywhere_in_the_recovery_app(self) -> None:
        """Section 6 line 2718: "Do not provide a bypass checkbox"."""
        from pathlib import Path

        from django.conf import settings

        for path in (Path(settings.BASE_DIR) / "apps" / "recovery").rglob("*.py"):
            text = path.read_text().lower()
            for forbidden in ("skip_checklist", "force_approve", "ignore_evidence", "bypass="):
                assert forbidden not in text, f"{path.name} contains {forbidden}"


class TestApprovalAuthorityAndConcurrency:
    @pytest.mark.parametrize("role_attr", ["ops", "supervisor", "auditor"])
    def test_denied_roles_cannot_approve(self, atlas, role_attr) -> None:  # type: ignore[no-untyped-def]
        with pytest.raises(Denied):
            approve(atlas, membership=getattr(atlas, role_attr))

    @pytest.mark.parametrize("role_attr", ["finance", "owner"])
    def test_permitted_roles_can_approve(self, atlas, role_attr) -> None:  # type: ignore[no-untyped-def]
        approval = approve(atlas, membership=getattr(atlas, role_attr))
        assert approval.decision == Approval.Decision.APPROVED

    def test_stale_version_is_refused(self, atlas) -> None:  # type: ignore[no-untyped-def]
        approve(atlas)
        with pytest.raises(approvals.StaleSubject):
            approvals.approve_invoice_ready(
                membership=atlas.finance,
                req=approvals.ApprovalRequest(item_id=atlas.item.id, expected_version=1),
            )

    def test_a_second_approval_of_the_same_item_is_refused(self, atlas) -> None:  # type: ignore[no-untyped-def]
        approve(atlas)
        atlas.item.refresh_from_db()
        with pytest.raises(approvals.ApprovalError):
            approve(atlas)
        assert (
            Approval.objects.filter(
                financial_recovery_item=atlas.item,
                approval_type=Approval.ApprovalType.INVOICE_READY,
            ).count()
            == 1
        )

    def test_cross_tenant_item_is_not_found(self, atlas) -> None:  # type: ignore[no-untyped-def]
        from apps.organizations.models import Membership

        beacon = Membership.objects.get(user__email="owner@beacon.example")
        with pytest.raises(FinancialRecoveryItem.DoesNotExist):
            approvals.approve_invoice_ready(
                membership=beacon,
                req=approvals.ApprovalRequest(item_id=atlas.item.id, expected_version=1),
            )


class TestRevocation:
    def test_revoking_returns_the_item_to_candidate(self, atlas) -> None:  # type: ignore[no-untyped-def]
        approve(atlas)
        atlas.item.refresh_from_db()
        item = approvals.revoke_invoice_ready(
            membership=atlas.finance,
            item_id=atlas.item.id,
            expected_version=atlas.item.version,
            reason="Source revision invalidated the amount.",
        )
        assert item.workflow_state == FinancialRecoveryItem.WorkflowState.CANDIDATE
        assert item.current_invoice_ready_snapshot is None
        live = Approval.objects.filter(
            financial_recovery_item=item,
            approval_type=Approval.ApprovalType.INVOICE_READY,
            revoked_at__isnull=True,
        )
        assert not live.exists()

    def test_revocation_requires_a_reason(self, atlas) -> None:  # type: ignore[no-untyped-def]
        approve(atlas)
        atlas.item.refresh_from_db()
        with pytest.raises(approvals.ApprovalError):
            approvals.revoke_invoice_ready(
                membership=atlas.finance,
                item_id=atlas.item.id,
                expected_version=atlas.item.version,
                reason="   ",
            )

    def test_history_is_preserved_after_revocation(self, atlas) -> None:  # type: ignore[no-untyped-def]
        approve(atlas)
        atlas.item.refresh_from_db()
        approvals.revoke_invoice_ready(
            membership=atlas.finance,
            item_id=atlas.item.id,
            expected_version=atlas.item.version,
            reason="corrected",
        )
        # Both snapshots survive; nothing is rewritten.
        assert atlas.case.financial_snapshots.count() == 2
        assert Approval.objects.filter(financial_recovery_item=atlas.item).count() == 1
        assert atlas.item.stage_events.count() == 2
