"""Recovery ledger read paths: site scope, currency, and the four separate facts."""

from __future__ import annotations

import datetime as dt
from decimal import Decimal

import pytest
from django.urls import reverse
from django.utils import timezone

from apps.exceptions.models import FinancialRecoveryItem
from apps.ingestion.models import DataSource, ExternalEntityReference
from apps.operations.models import Site, WorkOrder
from apps.organizations.models import MembershipSiteGrant, User
from apps.recovery import selectors
from apps.recovery.services import approvals, exports
from tests.phase6_helpers import loaded_atlas

pytestmark = pytest.mark.django_db


def _second_item_in(atlas, *, currency: str) -> FinancialRecoveryItem:
    """A second real recovery item on another work order, valued in `currency`.

    Built through the shipped snapshot model rather than by cloning rows, so the
    uniqueness constraints and the immutability guard both still apply.
    """
    from apps.exceptions.models import ExceptionCase, FinancialImpactSnapshot

    # Every other work order in the fixture already has a matching invoice, and the
    # export re-proves "still unbilled" before it writes a file. So the second item is
    # built on a copy of the star work order moved to a date the ledger has no invoice
    # for -- still inside the declared coverage window, so item 8 can be satisfied.
    source_work_order = atlas.item.work_order
    wo_fields = {
        f.name: getattr(source_work_order, f.name)
        for f in WorkOrder._meta.concrete_fields
        if f.name not in {"id", "created_at", "updated_at"}
    }
    wo_fields.update(
        scheduled_at=dt.datetime(2026, 5, 4, 22, tzinfo=dt.UTC),
        completed_at=dt.datetime(2026, 5, 5, 2, tzinfo=dt.UTC),
    )
    work_order = WorkOrder.objects.create(**wo_fields)
    fields = {
        f.name: getattr(atlas.case, f.name)
        for f in ExceptionCase._meta.concrete_fields
        if f.name not in {"id", "created_at", "updated_at"}
    }
    fields.update(
        case_number="REV-00002",
        fingerprint="fixture-second-item",
        work_order=work_order,
        service_date=dt.date(2026, 5, 4),
    )
    case = ExceptionCase.objects.create(**fields)
    item = FinancialRecoveryItem.objects.create(
        organization=atlas.organization,
        exception_case=case,
        work_order=work_order,
    )
    source_snapshot = atlas.item.current_candidate_snapshot
    snapshot_fields = {
        f.name: getattr(source_snapshot, f.name)
        for f in FinancialImpactSnapshot._meta.concrete_fields
        if f.name not in {"id", "created_at", "updated_at", "calculated_at"}
    }
    snapshot_fields.update(exception_case=case, currency=currency, snapshot_version=1)
    snapshot = FinancialImpactSnapshot.objects.create(**snapshot_fields)
    item.current_candidate_snapshot = snapshot
    item.save(update_fields=["current_candidate_snapshot"])
    return item


@pytest.fixture
def atlas(settings):  # type: ignore[no-untyped-def]
    settings.APP_ENV = "local"
    return loaded_atlas()


def _force_invoice_ready(item: FinancialRecoveryItem, *, currency: str) -> None:
    """Put an item into `invoice_ready` without going through the checklist.

    Only a test may do this, and only to reach code that sits AFTER approval. The
    approval service builds its own checklist and has no bypass -- proved structurally
    in tests/test_invoice_ready_checklist.py::TestNoBypassExists.
    """
    from apps.exceptions.models import FinancialImpactSnapshot

    source = item.current_candidate_snapshot
    fields = {
        f.name: getattr(source, f.name)
        for f in FinancialImpactSnapshot._meta.concrete_fields
        if f.name not in {"id", "created_at", "updated_at", "calculated_at"}
    }
    fields.update(
        snapshot_version=source.snapshot_version + 1,
        currency=currency,
        invoice_ready_value=source.candidate_value,
    )
    ready = FinancialImpactSnapshot.objects.create(**fields)
    FinancialRecoveryItem.objects.filter(pk=item.pk).update(
        workflow_state=FinancialRecoveryItem.WorkflowState.INVOICE_READY,
        current_invoice_ready_snapshot=ready,
    )


class TestSiteScopedTotals:
    """A reader who cannot see a site must not see its money either."""

    def test_a_supervisor_with_no_grants_sees_no_totals(self, atlas) -> None:  # type: ignore[no-untyped-def]
        from apps.organizations.policy import effective_site_scope

        scope = effective_site_scope(atlas.supervisor)
        assert scope == set(), "the seed grants no sites; deny-by-default must hold"
        totals = selectors.stage_totals(atlas.organization.id, limit_to_site_ids=scope)
        assert totals["candidate"] is None
        assert totals["invoice_ready"] is None

    def test_a_supervisor_granted_another_site_sees_no_totals(self, atlas) -> None:  # type: ignore[no-untyped-def]
        other = (
            Site.objects.filter(organization=atlas.organization)
            .exclude(id=atlas.item.work_order.site_id)
            .first()
        )
        MembershipSiteGrant.objects.create(membership=atlas.supervisor, site=other)
        totals = selectors.stage_totals(atlas.organization.id, limit_to_site_ids={other.id})
        assert totals["candidate"] is None

    def test_a_supervisor_granted_the_right_site_sees_its_total(self, atlas) -> None:  # type: ignore[no-untyped-def]
        """The scope must not be vacuously empty: the grant makes the money appear."""
        site_id = atlas.item.work_order.site_id
        totals = selectors.stage_totals(atlas.organization.id, limit_to_site_ids={site_id})
        assert totals["candidate"] == Decimal("480.0000")

    def test_the_rendered_ledger_does_not_leak_the_total_to_an_ungranted_reader(
        self, atlas, client
    ) -> None:  # type: ignore[no-untyped-def]
        client.force_login(User.objects.get(email="supervisor@atlas.example"))
        body = client.get(reverse("recovery:ledger")).content.decode()
        assert "480" not in body, "an out-of-scope reader was shown the organization total"
        assert "REV-00001" not in body

    def test_the_rendered_ledger_shows_the_total_to_finance(self, atlas, client) -> None:  # type: ignore[no-untyped-def]
        client.force_login(User.objects.get(email="finance@atlas.example"))
        body = client.get(reverse("recovery:ledger")).content.decode()
        assert "480" in body and "REV-00001" in body


class TestCurrency:
    """Adding USD to EUR produces a number that means nothing."""

    def test_a_single_currency_still_totals(self, atlas) -> None:  # type: ignore[no-untyped-def]
        totals = selectors.stage_totals(atlas.organization.id)
        assert totals["candidate"] == Decimal("480.0000")
        assert totals["mixed_currency"] is False
        assert totals["currency"] == "USD"

    def test_a_mixed_set_withholds_every_total(self, atlas) -> None:  # type: ignore[no-untyped-def]
        second = _second_item_in(atlas, currency="EUR")
        assert second.current_candidate_snapshot.currency == "EUR"
        totals = selectors.stage_totals(atlas.organization.id)
        assert totals["mixed_currency"] is True
        assert totals["candidate"] is None, "USD and EUR were added together"
        assert totals["invoice_ready"] is None
        assert totals["invoiced"] is None
        assert totals["collected"] is None

    def test_two_items_in_the_same_currency_do_total(self, atlas) -> None:  # type: ignore[no-untyped-def]
        """The guard above must not be vacuous: a same-currency pair still sums."""
        _second_item_in(atlas, currency="USD")
        totals = selectors.stage_totals(atlas.organization.id)
        assert totals["mixed_currency"] is False
        assert totals["candidate"] == Decimal("960.0000")

    def test_the_ledger_explains_a_withheld_total(self, atlas, client) -> None:  # type: ignore[no-untyped-def]
        self.test_a_mixed_set_withholds_every_total(atlas)
        client.force_login(User.objects.get(email="finance@atlas.example"))
        body = client.get(reverse("recovery:ledger")).content.decode()
        assert "More than one currency is present" in body

    def test_a_mixed_currency_export_is_refused(self, atlas) -> None:  # type: ignore[no-untyped-def]
        second = _second_item_in(atlas, currency="EUR")
        approvals.approve_invoice_ready(
            membership=atlas.finance,
            req=approvals.ApprovalRequest(
                item_id=atlas.item.id, expected_version=atlas.item.version
            ),
        )
        _force_invoice_ready(second, currency="EUR")
        with pytest.raises(exports.ExportError, match="more than one currency"):
            exports.export_invoice_ready(membership=atlas.finance)

    def test_a_single_currency_export_succeeds(self, atlas) -> None:  # type: ignore[no-untyped-def]
        """The refusal above must not be vacuous: two USD items export as one file."""
        second = _second_item_in(atlas, currency="USD")
        approvals.approve_invoice_ready(
            membership=atlas.finance,
            req=approvals.ApprovalRequest(
                item_id=atlas.item.id, expected_version=atlas.item.version
            ),
        )
        _force_invoice_ready(second, currency="USD")
        export, _ = exports.export_invoice_ready(membership=atlas.finance)
        assert export.row_count == 2
        assert export.total_invoice_ready_value == Decimal("960.0000")
        assert export.currency == "USD"


class TestExportIdentifierIsDeterministic:
    def test_a_second_confirmed_source_does_not_change_the_exported_id(self, atlas) -> None:  # type: ignore[no-untyped-def]
        """The bookkeeper keys their invoice off this column; it cannot wobble."""
        approvals.approve_invoice_ready(
            membership=atlas.finance,
            req=approvals.ApprovalRequest(
                item_id=atlas.item.id, expected_version=atlas.item.version
            ),
        )
        atlas.item.refresh_from_db()
        first, _ = exports.export_invoice_ready(membership=atlas.finance, item_ids=[atlas.item.id])
        assert "00518774" in first.content

        second_source = DataSource.objects.create(
            organization=atlas.organization,
            name="Alternate operations export",
            system_key="alt-ops",
            domain=DataSource.Domain.SERVICE_EVENTS,
        )
        ExternalEntityReference.objects.create(
            organization=atlas.organization,
            source=second_source,
            entity_type="work_order",
            external_id="ZZZ-9999",
            work_order=atlas.item.work_order,
            mapping_status=ExternalEntityReference.MappingStatus.CONFIRMED,
            confirmed_at=timezone.now(),
            match_method="owner_confirmed",
        )
        FinancialRecoveryItem.objects.filter(pk=atlas.item.pk).update(
            workflow_state=FinancialRecoveryItem.WorkflowState.INVOICE_READY,
            export_reference="",
        )
        atlas.item.refresh_from_db()
        rebuilt = exports._row(atlas.item)
        assert rebuilt["work_order_external_id"] == "ZZZ-9999"
        assert rebuilt["work_order_source_system"] == "alt-ops"

    def test_the_row_names_the_system_the_id_belongs_to(self, atlas) -> None:  # type: ignore[no-untyped-def]
        """An external id without its system is ambiguous across three ID dialects."""
        row = exports._row(atlas.item)
        assert row["work_order_source_system"]
        assert row["work_order_external_id"]
