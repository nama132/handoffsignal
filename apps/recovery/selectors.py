"""Read paths for the recovery ledger. Every function takes an explicit organization."""

from __future__ import annotations

import uuid
from decimal import Decimal

from django.db.models import QuerySet

from apps.exceptions.models import FinancialRecoveryItem
from apps.recovery.models import FinanceExport


def ledger_items(
    organization_id: uuid.UUID, *, limit_to_site_ids: set[uuid.UUID] | None = None
) -> QuerySet[FinancialRecoveryItem]:
    queryset = FinancialRecoveryItem.objects.filter(organization_id=organization_id).select_related(
        "exception_case",
        "work_order__customer",
        "work_order__site",
        "current_candidate_snapshot",
        "current_invoice_ready_snapshot",
    )
    if limit_to_site_ids is not None:
        queryset = queryset.filter(work_order__site_id__in=limit_to_site_ids)
    return queryset.order_by("exception_case__case_number")


def _currencies(items: list[FinancialRecoveryItem]) -> set[str]:
    """Every currency represented in a set of items, from their own snapshots."""
    found = set()
    for item in items:
        snapshot = item.current_invoice_ready_snapshot or item.current_candidate_snapshot
        if snapshot is not None and snapshot.currency:
            found.add(snapshot.currency)
    return found


def stage_totals(
    organization_id: uuid.UUID, *, limit_to_site_ids: set[uuid.UUID] | None = None
) -> dict[str, object]:
    """The four stages, computed independently and never summed (section 26).

    A disputed item is excluded from the ACTUAL columns (invoiced/collected) per
    section 23.1 rule 5, but its candidate and invoice-ready values remain visible —
    the dispute is about what the accounting source says, not about what was claimed.

    A stage with no data returns None, not zero, so the UI can say "none" rather than
    imply a real zero.
    """
    items = list(ledger_items(organization_id, limit_to_site_ids=limit_to_site_ids))

    # A reader who cannot see a site must not see its money either. The rows are
    # already scoped; totals computed over the whole organization would hand a
    # site-scoped supervisor the organization-wide figure by subtraction.
    currencies = _currencies(items)
    mixed = len(currencies) > 1

    def total(values: list[Decimal]) -> Decimal | None:
        # Adding USD to EUR produces a number that means nothing. Section 23.1 rule 5
        # treats a currency mismatch as a dispute, never a conversion; the same rule
        # has to hold for an aggregate, so a mixed set reports no total at all.
        if mixed or not values:
            return None
        return sum(values, Decimal("0"))

    candidate = [
        i.current_candidate_snapshot.candidate_value
        for i in items
        if i.current_candidate_snapshot and i.current_candidate_snapshot.candidate_value is not None
    ]
    ready = [
        i.current_invoice_ready_snapshot.invoice_ready_value
        for i in items
        if i.current_invoice_ready_snapshot
        and i.current_invoice_ready_snapshot.invoice_ready_value is not None
    ]
    undisputed = [i for i in items if i.dispute_status != FinancialRecoveryItem.DisputeStatus.OPEN]
    invoiced = [
        i.actual_invoiced_amount for i in undisputed if i.actual_invoiced_amount is not None
    ]
    collected = [
        i.actual_collected_amount for i in undisputed if i.actual_collected_amount is not None
    ]

    return {
        "candidate": total(candidate),
        "invoice_ready": total(ready),
        "invoiced": total(invoiced),
        "collected": total(collected),
        "disputed_excluded": sum(
            1 for i in items if i.dispute_status == FinancialRecoveryItem.DisputeStatus.OPEN
        ),
        "currency": next(iter(currencies)) if len(currencies) == 1 else "",
        "mixed_currency": mixed,
    }


def exports_for_organization(organization_id: uuid.UUID) -> QuerySet[FinanceExport]:
    return FinanceExport.objects.filter(organization_id=organization_id).select_related(
        "created_by__user"
    )
