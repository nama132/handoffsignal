"""Accounting facts arriving AFTER approval, and the guards that stop a second invoice.

Route B's whole claim is that work was completed and never billed. The dangerous window
is between the reviewer's approval and the bookkeeper receiving the file: an accounting
export committed in that window can turn a true statement into a false one. Every test
here is about that window.
"""

from __future__ import annotations

import datetime as dt
from decimal import Decimal

import pytest
from django.db import IntegrityError, transaction

from apps.exceptions.models import (
    AppendOnlyError,
    FinancialImpactSnapshot,
    FinancialRecoveryItem,
)
from apps.ingestion.models import DataSource
from apps.ingestion.services import coverage as coverage_service
from apps.ingestion.services import imports as import_service
from apps.operations.models import AccountingInvoice, AccountingPayment
from apps.organizations.models import User
from apps.recovery.services import accounting, approvals, exports
from tests.phase6_helpers import loaded_atlas

pytestmark = pytest.mark.django_db

AS_OF = dt.datetime(2026, 8, 20, 10, tzinfo=dt.UTC)

HEADER = (
    "source_system,invoice_external_id,work_order_source_system,work_order_external_id,"
    "customer_source_system,customer_external_id,site_source_system,site_external_id,"
    "service_date,invoice_reference,invoice_amount,invoiced_at,invoice_status,"
    "payment_external_id,payment_reference,collected_amount,collected_at,payment_status,"
    "currency,source_updated_at,source_as_of_at"
)


def _late_invoice_csv(*, status: str = "posted", amount: str = "480.00") -> bytes:
    """An accounting export that now shows the star work order as invoiced."""
    # MERIDIAN-PG / MBC-NOVA-01 in the ar_ledger dialect: the star case's own
    # customer and site, on its own service date.
    row = (
        f"ar_ledger,80000999-1756000000,,,ar_ledger,80000042-1739216455,"
        f"ar_ledger,80000107-1739216455,2026-07-06,4001,{amount},"
        f"2026-07-20T09:00:00-04:00,{status},,,,,,USD,,2026-08-20T06:00:00-04:00"
    )
    return f"{HEADER}\n{row}\n".encode()


def _commit_invoice_status(organization, actor, payload: bytes):  # type: ignore[no-untyped-def]
    """Push an accounting file through the real upload and commit services."""
    source = DataSource.objects.get(organization=organization, system_key="ar_ledger")
    declaration = coverage_service.CoverageDeclaration(
        record_family="accounting_invoice",
        scope_type="organization",
        coverage_start_at=dt.datetime(2026, 1, 1, tzinfo=dt.UTC),
        coverage_end_at=dt.datetime(2027, 1, 1, tzinfo=dt.UTC),
        query_contract_code="ACCOUNTING_SERVICE_DATE_LEDGER_V1",
        query_contract_version=1,
        completeness="complete",
        declaration_basis="synthetic_fixture",
    )
    result = import_service.upload(
        organization=organization,
        source=source,
        kind="invoice_status",
        filename="invoice_status_late.csv",
        payload=payload,
        observation_mode="full_snapshot",
        source_as_of_at=AS_OF,
        declarations=[declaration],
        actor=actor,
    )
    assert result.batch is not None, [e.code for e in result.file_errors]
    return import_service.commit(result.batch, actor)


@pytest.fixture
def atlas(settings):  # type: ignore[no-untyped-def]
    settings.APP_ENV = "local"
    return loaded_atlas()


@pytest.fixture
def approved(atlas):  # type: ignore[no-untyped-def]
    approvals.approve_invoice_ready(
        membership=atlas.finance,
        req=approvals.ApprovalRequest(item_id=atlas.item.id, expected_version=atlas.item.version),
    )
    atlas.item.refresh_from_db()
    return atlas


class TestTheExportRefusesWorkThatIsNowBilled:
    """The single most dangerous failure: telling a bookkeeper to invoice twice."""

    def test_an_invoice_committed_after_approval_stops_the_export(self, approved) -> None:  # type: ignore[no-untyped-def]
        AccountingInvoice.objects.create(
            organization=approved.organization,
            customer=approved.item.work_order.customer,
            site=approved.item.work_order.site,
            service_date=approved.case.service_date,
            invoice_reference="LATE-1",
            invoice_amount=Decimal("480.00"),
            invoiced_at=dt.datetime(2026, 7, 20, tzinfo=dt.UTC),
            currency="USD",
            source_status=AccountingInvoice.SourceStatus.POSTED,
            source_as_of_at=AS_OF,
        )
        with pytest.raises(exports.ExportError, match="no longer unbilled|recorded as"):
            exports.export_invoice_ready(membership=approved.finance, item_ids=[approved.item.id])
        approved.item.refresh_from_db()
        assert approved.item.workflow_state == FinancialRecoveryItem.WorkflowState.INVOICE_READY
        assert approved.item.exports.count() == 0

    def test_without_that_invoice_the_same_export_succeeds(self, approved) -> None:  # type: ignore[no-untyped-def]
        """The refusal above must not be vacuous."""
        export, created = exports.export_invoice_ready(
            membership=approved.finance, item_ids=[approved.item.id]
        )
        assert created and export.row_count == 1

    def test_an_open_dispute_after_approval_stops_the_export(self, approved) -> None:  # type: ignore[no-untyped-def]
        FinancialRecoveryItem.objects.filter(pk=approved.item.pk).update(
            dispute_status=FinancialRecoveryItem.DisputeStatus.OPEN,
            dispute_reason=accounting.DisputeReason.AMBIGUOUS_MAPPING,
        )
        with pytest.raises(exports.ExportError):
            exports.export_invoice_ready(membership=approved.finance, item_ids=[approved.item.id])


class TestApprovalRefusesADisputedItem:
    def test_an_open_dispute_blocks_approval(self, atlas) -> None:  # type: ignore[no-untyped-def]
        """Section 21.2 line 966: a blocking conflict prevents financial approval."""
        FinancialRecoveryItem.objects.filter(pk=atlas.item.pk).update(
            dispute_status=FinancialRecoveryItem.DisputeStatus.OPEN,
            dispute_reason=accounting.DisputeReason.OVER_COLLECTION,
        )
        atlas.item.refresh_from_db()
        with pytest.raises(approvals.ApprovalError, match="dispute"):
            approvals.approve_invoice_ready(
                membership=atlas.finance,
                req=approvals.ApprovalRequest(
                    item_id=atlas.item.id, expected_version=atlas.item.version
                ),
            )


class TestCommittingAnAccountingFileAdvancesTheStage:
    """Nothing else in the product can move an item to `invoiced`."""

    def test_the_import_itself_advances_the_stage(self, approved) -> None:  # type: ignore[no-untyped-def]
        """No test-side call to refresh(): the commit path must do it."""
        actor = User.objects.get(email="owner@atlas.example")
        assert approved.item.accounting_stage == FinancialRecoveryItem.AccountingStage.NO_INVOICE

        _commit_invoice_status(approved.organization, actor, _late_invoice_csv())

        approved.item.refresh_from_db()
        assert approved.item.accounting_stage == FinancialRecoveryItem.AccountingStage.INVOICED
        assert approved.item.actual_invoiced_amount == Decimal("480.0000")
        assert approved.item.stage_events.filter(kind="accounting").exists()

    def test_and_the_export_then_refuses(self, approved) -> None:  # type: ignore[no-untyped-def]
        """End to end: the accounting file alone stops the double invoice."""
        actor = User.objects.get(email="owner@atlas.example")
        _commit_invoice_status(approved.organization, actor, _late_invoice_csv())
        with pytest.raises(exports.ExportError):
            exports.export_invoice_ready(membership=approved.finance, item_ids=[approved.item.id])


class TestDisputedSourceRows:
    def _invoice(self, atlas, status):  # type: ignore[no-untyped-def]
        return AccountingInvoice.objects.create(
            organization=atlas.organization,
            customer=atlas.item.work_order.customer,
            site=atlas.item.work_order.site,
            service_date=atlas.case.service_date,
            invoice_reference="D-1",
            invoice_amount=Decimal("480.00"),
            invoiced_at=dt.datetime(2026, 7, 20, tzinfo=dt.UTC),
            currency="USD",
            source_status=status,
            source_as_of_at=AS_OF,
        )

    def test_a_disputed_invoice_is_never_counted_as_invoiced(self, atlas) -> None:  # type: ignore[no-untyped-def]
        """Rule 1 maps "non-void, NON-DISPUTED" invoices only."""
        self._invoice(atlas, AccountingInvoice.SourceStatus.DISPUTED)
        result = accounting.derive(atlas.item)
        assert result.invoiced is None
        assert result.stage == FinancialRecoveryItem.AccountingStage.NO_INVOICE
        assert result.dispute == accounting.DisputeReason.DISPUTED_INVOICE

    def test_a_posted_invoice_of_the_same_shape_is_counted(self, atlas) -> None:  # type: ignore[no-untyped-def]
        """Non-vacuity control for the test above."""
        self._invoice(atlas, AccountingInvoice.SourceStatus.POSTED)
        result = accounting.derive(atlas.item)
        assert result.invoiced == Decimal("480.00")
        assert result.dispute == ""

    def test_a_disputed_payment_opens_a_dispute_and_is_not_collected(self, atlas) -> None:  # type: ignore[no-untyped-def]
        invoice = self._invoice(atlas, AccountingInvoice.SourceStatus.POSTED)
        AccountingPayment.objects.create(
            organization=atlas.organization,
            accounting_invoice=invoice,
            payment_reference="P-D",
            collected_amount=Decimal("480.00"),
            collected_at=dt.datetime(2026, 8, 5, tzinfo=dt.UTC),
            currency="USD",
            source_status=AccountingPayment.SourceStatus.DISPUTED,
            source_as_of_at=AS_OF,
        )
        result = accounting.derive(atlas.item)
        assert result.collected == Decimal("0")
        assert result.dispute == accounting.DisputeReason.DISPUTED_PAYMENT


class TestSnapshotImmutability:
    """An approved amount that can be edited in place is not evidence of anything."""

    @pytest.mark.parametrize(
        ("field", "value"),
        [
            ("invoice_ready_value", Decimal("99999.0000")),
            ("candidate_value", Decimal("99999.0000")),
            ("currency", "EUR"),
            ("calculation_code", "TAMPERED"),
            ("calculation_version", 99),
            ("snapshot_version", 99),
            ("basis", FinancialImpactSnapshot.Basis.MANUAL_AMOUNT_REQUIRED),
        ],
    )
    def test_every_value_field_is_frozen(self, approved, field, value) -> None:  # type: ignore[no-untyped-def]
        snapshot = approved.item.current_invoice_ready_snapshot
        setattr(snapshot, field, value)
        with pytest.raises(AppendOnlyError, match=field):
            snapshot.save()

    def test_approval_metadata_may_still_be_written(self, approved) -> None:  # type: ignore[no-untyped-def]
        """The guard must not be so broad that the approval service cannot record itself."""
        snapshot = approved.item.current_invoice_ready_snapshot
        assert snapshot.approved_at is not None
        snapshot.approved_at = dt.datetime(2026, 8, 21, tzinfo=dt.UTC)
        snapshot.save()  # does not raise

    def test_a_manual_amount_basis_cannot_carry_an_approved_value(self, approved) -> None:  # type: ignore[no-untyped-def]
        """The database refuses it even if every service layer is bypassed."""
        source = approved.item.current_invoice_ready_snapshot
        fields = {
            f.name: getattr(source, f.name)
            for f in FinancialImpactSnapshot._meta.concrete_fields
            if f.name not in {"id", "created_at", "updated_at", "calculated_at"}
        }
        fields.update(
            snapshot_version=source.snapshot_version + 1,
            basis=FinancialImpactSnapshot.Basis.MANUAL_AMOUNT_REQUIRED,
            candidate_value=None,
            invoice_ready_value=Decimal("480.0000"),
        )
        with pytest.raises(IntegrityError, match="manual_basis_has_no_ready_value"):
            with transaction.atomic():
                FinancialImpactSnapshot.objects.create(**fields)
