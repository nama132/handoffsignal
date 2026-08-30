"""Invoice-ready export, download protection, and accounting-stage derivation."""

from __future__ import annotations

import datetime as dt
import uuid
from decimal import Decimal

import pytest
from django.urls import reverse

from apps.exceptions.models import FinancialRecoveryItem
from apps.operations.models import AccountingInvoice, AccountingPayment
from apps.organizations.models import Membership, User
from apps.organizations.policy import Denied
from apps.recovery.models import AppendOnlyError, Approval, FinanceExport, FinancialStageEvent
from apps.recovery.services import accounting, approvals, exports
from tests.phase6_helpers import loaded_atlas

pytestmark = pytest.mark.django_db


@pytest.fixture
def atlas(settings):  # type: ignore[no-untyped-def]
    settings.APP_ENV = "local"
    data = loaded_atlas()
    approvals.approve_invoice_ready(
        membership=data.finance,
        req=approvals.ApprovalRequest(item_id=data.item.id, expected_version=data.item.version),
    )
    data.item.refresh_from_db()
    return data


class TestExportGeneration:
    def test_export_contains_one_row_with_full_provenance(self, atlas) -> None:  # type: ignore[no-untyped-def]
        export, created = exports.export_invoice_ready(membership=atlas.finance)
        assert created and export.row_count == 1
        header, row = export.content.splitlines()[:2]
        for column in (
            "case_number",
            "work_order_external_id",
            "invoice_ready_value",
            "approved_by",
            "approved_at",
            "accounting_coverage_basis",
        ):
            assert column in header
        assert "REV-00001" in row
        assert "00518774" in row  # the operations source identifier
        assert "480.0000" in row
        assert "finance@atlas.example" in row

    def test_export_total_is_invoice_ready_only(self, atlas) -> None:  # type: ignore[no-untyped-def]
        """Never a cross-stage total (section 26)."""
        export, _ = exports.export_invoice_ready(membership=atlas.finance)
        assert export.total_invoice_ready_value == Decimal("480.0000")

    def test_export_moves_the_item_and_records_an_approval(self, atlas) -> None:  # type: ignore[no-untyped-def]
        exports.export_invoice_ready(membership=atlas.finance)
        atlas.item.refresh_from_db()
        assert atlas.item.workflow_state == FinancialRecoveryItem.WorkflowState.EXPORTED
        assert atlas.item.export_reference
        assert Approval.objects.filter(
            financial_recovery_item=atlas.item, approval_type=Approval.ApprovalType.FINANCE_EXPORT
        ).exists()
        assert atlas.item.stage_events.filter(reason_code="finance_export").exists()

    def test_nothing_to_export_raises(self, atlas) -> None:  # type: ignore[no-untyped-def]
        exports.export_invoice_ready(membership=atlas.finance)
        with pytest.raises(exports.ExportError):
            exports.export_invoice_ready(membership=atlas.finance)

    def test_export_content_is_immutable(self, atlas) -> None:  # type: ignore[no-untyped-def]
        export, _ = exports.export_invoice_ready(membership=atlas.finance)
        export.content = "tampered"
        export.content_sha256 = "0" * 64
        with pytest.raises(AppendOnlyError):
            export.save()

    def test_export_cannot_be_deleted(self, atlas) -> None:  # type: ignore[no-untyped-def]
        export, _ = exports.export_invoice_ready(membership=atlas.finance)
        with pytest.raises(AppendOnlyError):
            export.delete()

    def test_an_exported_item_cannot_be_rolled_back(self, atlas) -> None:  # type: ignore[no-untyped-def]
        """Section 23.1 line 1391: a source correction after export opens a dispute,
        it never rolls the item backward."""
        exports.export_invoice_ready(membership=atlas.finance)
        atlas.item.refresh_from_db()
        with pytest.raises(approvals.ApprovalError, match="exported"):
            approvals.revoke_invoice_ready(
                membership=atlas.finance,
                item_id=atlas.item.id,
                expected_version=atlas.item.version,
                reason="changed",
            )


class TestExportIdempotency:
    def test_a_resubmitted_request_returns_the_first_export(self, atlas) -> None:  # type: ignore[no-untyped-def]
        """A double submit must not mint a second reference for the same handoff."""
        ids = [atlas.item.id]
        first, created_first = exports.export_invoice_ready(membership=atlas.finance, item_ids=ids)
        second, created_second = exports.export_invoice_ready(
            membership=atlas.finance, item_ids=ids
        )
        assert created_first is True
        assert created_second is False
        assert first.id == second.id
        assert FinanceExport.objects.count() == 1

    def test_a_resubmit_is_not_a_second_workflow_transition(self, atlas) -> None:  # type: ignore[no-untyped-def]
        ids = [atlas.item.id]
        exports.export_invoice_ready(membership=atlas.finance, item_ids=ids)
        exports.export_invoice_ready(membership=atlas.finance, item_ids=ids)
        atlas.item.refresh_from_db()
        assert atlas.item.stage_events.filter(reason_code="finance_export").count() == 1
        assert (
            Approval.objects.filter(
                financial_recovery_item=atlas.item,
                approval_type=Approval.ApprovalType.FINANCE_EXPORT,
            ).count()
            == 1
        )

    def test_a_different_item_set_is_a_different_export(self, atlas) -> None:  # type: ignore[no-untyped-def]
        """Replay must key on the set, never on "this tenant exported recently"."""
        exports.export_invoice_ready(membership=atlas.finance, item_ids=[atlas.item.id])
        with pytest.raises(exports.ExportError):
            exports.export_invoice_ready(membership=atlas.finance, item_ids=[uuid.uuid4()])

    def test_the_form_posts_the_ids_it_displayed(self, atlas, client) -> None:  # type: ignore[no-untyped-def]
        """The idempotent path is only reachable if the view actually names the set."""
        client.force_login(User.objects.get(email="finance@atlas.example"))
        page = client.get(reverse("recovery:ledger"))
        assert f'name="item_id" value="{atlas.item.id}"' in page.content.decode()

    def test_a_malformed_item_id_is_rejected(self, atlas, client) -> None:  # type: ignore[no-untyped-def]
        client.force_login(User.objects.get(email="finance@atlas.example"))
        response = client.post(reverse("recovery:export"), {"item_id": "not-a-uuid"})
        assert response.status_code == 400


class TestFormulaNeutralization:
    def test_a_formula_in_source_data_is_neutralized_in_the_export(self, atlas) -> None:  # type: ignore[no-untyped-def]
        """A hostile customer name must not become a live spreadsheet formula."""
        customer = atlas.item.work_order.customer
        customer.name = "=cmd|'/c calc'!A1"
        customer.save()
        export, _ = exports.export_invoice_ready(membership=atlas.finance)
        assert "'=cmd" in export.content
        for line in export.content.splitlines()[1:]:
            for cell in line.split(","):
                assert not cell.startswith(("=", "+", "@")), cell

    def test_download_is_utf8_with_bom_for_spreadsheets(self, atlas, client) -> None:  # type: ignore[no-untyped-def]
        export, _ = exports.export_invoice_ready(membership=atlas.finance)
        client.force_login(User.objects.get(email="finance@atlas.example"))
        response = client.get(reverse("recovery:export-download", kwargs={"export_id": export.id}))
        assert response.status_code == 200
        assert response.content.startswith(b"\xef\xbb\xbf")
        assert response["Content-Type"].startswith("text/csv")
        assert "attachment" in response["Content-Disposition"]
        assert response["X-Content-Type-Options"] == "nosniff"


class TestDownloadProtection:
    def _export(self, atlas):  # type: ignore[no-untyped-def]
        export, _ = exports.export_invoice_ready(membership=atlas.finance)
        return export

    @pytest.mark.parametrize("email", ["finance@atlas.example", "owner@atlas.example"])
    def test_permitted_roles_can_download(self, atlas, client, email) -> None:  # type: ignore[no-untyped-def]
        export = self._export(atlas)
        client.force_login(User.objects.get(email=email))
        assert (
            client.get(
                reverse("recovery:export-download", kwargs={"export_id": export.id})
            ).status_code
            == 200
        )

    @pytest.mark.parametrize(
        "email", ["ops@atlas.example", "supervisor@atlas.example", "auditor@atlas.example"]
    )
    def test_denied_roles_get_403(self, atlas, client, email) -> None:  # type: ignore[no-untyped-def]
        export = self._export(atlas)
        client.force_login(User.objects.get(email=email))
        assert (
            client.get(
                reverse("recovery:export-download", kwargs={"export_id": export.id})
            ).status_code
            == 403
        )

    def test_another_tenant_gets_404_not_403(self, atlas, client) -> None:  # type: ignore[no-untyped-def]
        """The export's existence is the secret; the role denial is not."""
        from apps.organizations.models import MembershipRoleGrant
        from apps.organizations.roles import Role

        export = self._export(atlas)
        beacon = Membership.objects.get(user__email="owner@beacon.example")
        MembershipRoleGrant.objects.get_or_create(
            membership=beacon, role=Role.FINANCE_REVIEWER, revoked_at=None
        )
        client.force_login(User.objects.get(email="owner@beacon.example"))
        assert (
            client.get(
                reverse("recovery:export-download", kwargs={"export_id": export.id})
            ).status_code
            == 404
        )

    def test_anonymous_is_redirected_to_login(self, atlas, client) -> None:  # type: ignore[no-untyped-def]
        export = self._export(atlas)
        response = client.get(reverse("recovery:export-download", kwargs={"export_id": export.id}))
        assert response.status_code == 302
        assert reverse("login") in response.url

    def test_denied_role_cannot_trigger_an_export(self, atlas) -> None:  # type: ignore[no-untyped-def]
        with pytest.raises(Denied):
            exports.export_invoice_ready(membership=atlas.ops)


class TestAccountingStageDerivation:
    """Section 23.1 rules 1-5. The distinct-invoice rule is the one that matters."""

    def _invoice(self, atlas, amount="480.00", status="posted", **kw):  # type: ignore[no-untyped-def]
        work_order = atlas.item.work_order
        return AccountingInvoice.objects.create(
            organization=atlas.organization,
            customer=kw.pop("customer", work_order.customer),
            site=kw.pop("site", work_order.site),
            service_date=kw.pop("service_date", atlas.case.service_date),
            invoice_reference=kw.pop("reference", "INV-1"),
            invoice_amount=Decimal(amount),
            invoiced_at=dt.datetime(2026, 8, 1, tzinfo=dt.UTC),
            currency="USD",
            source_status=status,
            source_as_of_at=dt.datetime(2026, 8, 1, tzinfo=dt.UTC),
            **kw,
        )

    def _payment(self, atlas, invoice, amount, status="posted", reference="P-1"):  # type: ignore[no-untyped-def]
        return AccountingPayment.objects.create(
            organization=atlas.organization,
            accounting_invoice=invoice,
            payment_reference=reference,
            collected_amount=Decimal(amount),
            collected_at=dt.datetime(2026, 8, 5, tzinfo=dt.UTC),
            currency="USD",
            source_status=status,
            source_as_of_at=dt.datetime(2026, 8, 5, tzinfo=dt.UTC),
        )

    def test_no_invoice_yields_no_invoice_stage(self, atlas) -> None:  # type: ignore[no-untyped-def]
        result = accounting.derive(atlas.item)
        assert result.stage == FinancialRecoveryItem.AccountingStage.NO_INVOICE
        assert result.invoiced is None and result.collected is None

    def test_one_invoice_no_payment_is_invoiced(self, atlas) -> None:  # type: ignore[no-untyped-def]
        self._invoice(atlas)
        result = accounting.derive(atlas.item)
        assert result.stage == FinancialRecoveryItem.AccountingStage.INVOICED
        assert result.invoiced == Decimal("480.00")
        assert result.collected == Decimal("0")

    def test_ONE_INVOICE_ACROSS_TWO_PAYMENTS_IS_NOT_DOUBLE_COUNTED(self, atlas) -> None:  # type: ignore[no-untyped-def]
        """Section 23.1 rule 3: "Never sum the invoice amount once per payment row."

        A join over invoice x payment would report $960 invoiced for one $480 invoice
        with two payments. This test fails loudly if anyone reintroduces that join.
        """
        invoice = self._invoice(atlas, "480.00")
        self._payment(atlas, invoice, "300.00", reference="P-1")
        self._payment(atlas, invoice, "180.00", reference="P-2")
        result = accounting.derive(atlas.item)
        assert result.invoiced == Decimal("480.00"), "the invoice was counted once per payment row"
        assert result.collected == Decimal("480.00")
        assert result.stage == FinancialRecoveryItem.AccountingStage.COLLECTED

    def test_three_payments_still_count_the_invoice_once(self, atlas) -> None:  # type: ignore[no-untyped-def]
        """Section 33.4 line 2099 asks for exactly this shape."""
        invoice = self._invoice(atlas, "600.00")
        for index, amount in enumerate(["100.00", "200.00", "150.00"]):
            self._payment(atlas, invoice, amount, reference=f"P-{index}")
        result = accounting.derive(atlas.item)
        assert result.invoiced == Decimal("600.00")
        assert result.collected == Decimal("450.00")
        assert result.stage == FinancialRecoveryItem.AccountingStage.PARTIALLY_COLLECTED

    def test_partial_collection(self, atlas) -> None:  # type: ignore[no-untyped-def]
        invoice = self._invoice(atlas, "480.00")
        self._payment(atlas, invoice, "200.00")
        assert (
            accounting.derive(atlas.item).stage
            == FinancialRecoveryItem.AccountingStage.PARTIALLY_COLLECTED
        )

    def test_void_invoice_is_not_counted(self, atlas) -> None:  # type: ignore[no-untyped-def]
        self._invoice(atlas, "480.00", status="void")
        assert (
            accounting.derive(atlas.item).stage == FinancialRecoveryItem.AccountingStage.NO_INVOICE
        )

    def test_reversed_payment_is_not_collected(self, atlas) -> None:  # type: ignore[no-untyped-def]
        invoice = self._invoice(atlas, "480.00")
        self._payment(atlas, invoice, "480.00", status="reversed")
        result = accounting.derive(atlas.item)
        assert result.collected == Decimal("0")
        assert result.stage == FinancialRecoveryItem.AccountingStage.INVOICED

    def test_over_collection_opens_a_dispute(self, atlas) -> None:  # type: ignore[no-untyped-def]
        invoice = self._invoice(atlas, "480.00")
        self._payment(atlas, invoice, "500.00")
        assert accounting.derive(atlas.item).dispute == accounting.DisputeReason.OVER_COLLECTION

    def test_two_invoices_for_one_work_order_open_a_dispute_not_a_sum(self, atlas) -> None:  # type: ignore[no-untyped-def]
        self._invoice(atlas, "300.00", reference="A")
        self._invoice(atlas, "200.00", reference="B")
        result = accounting.derive(atlas.item)
        assert result.dispute == accounting.DisputeReason.AMBIGUOUS_MAPPING
        assert result.invoiced is None, "an ambiguous mapping must never be summed"

    def test_currency_mismatch_opens_a_dispute_not_a_conversion(self, atlas) -> None:  # type: ignore[no-untyped-def]
        invoice = self._invoice(atlas, "480.00")
        AccountingInvoice.objects.filter(pk=invoice.pk).update(currency="EUR")
        result = accounting.derive(atlas.item)
        assert result.dispute == accounting.DisputeReason.CURRENCY_MISMATCH
        assert result.invoiced is None

    def test_refresh_is_replay_safe(self, atlas) -> None:  # type: ignore[no-untyped-def]
        """Section 33.4 line 2098: one stage event and one actual amount."""
        invoice = self._invoice(atlas, "480.00")
        self._payment(atlas, invoice, "480.00")
        accounting.refresh(atlas.item.id)
        accounting.refresh(atlas.item.id)
        accounting.refresh(atlas.item.id)
        atlas.item.refresh_from_db()
        assert atlas.item.actual_invoiced_amount == Decimal("480.00")
        assert atlas.item.stage_events.filter(kind=FinancialStageEvent.Kind.ACCOUNTING).count() == 1

    def test_refresh_never_changes_case_state(self, atlas) -> None:  # type: ignore[no-untyped-def]
        """Section 23.1 line 1401: it "does NOT change ExceptionCase.state"."""
        before = atlas.case.state
        self._invoice(atlas, "480.00")
        accounting.refresh(atlas.item.id)
        atlas.case.refresh_from_db()
        assert atlas.case.state == before

    def test_stage_events_are_append_only(self, atlas) -> None:  # type: ignore[no-untyped-def]
        self._invoice(atlas, "480.00")
        accounting.refresh(atlas.item.id)
        event = atlas.item.stage_events.filter(kind=FinancialStageEvent.Kind.ACCOUNTING).first()
        event.note = "tampered"
        with pytest.raises(AppendOnlyError):
            event.save()
        with pytest.raises(AppendOnlyError):
            event.delete()
