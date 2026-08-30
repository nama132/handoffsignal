"""Candidate-value snapshots (master prompt sections 22.5, 23.1, 26).

Phase 4 owns the CANDIDATE stage only. Every snapshot is immutable; a changed input or
rule appends a new version. Money is Decimal at four places; display quantizes to cents.
"""

from __future__ import annotations

from decimal import ROUND_HALF_UP, Decimal

from django.db import transaction

from apps.exceptions.detectors.base import FinancialInputs
from apps.exceptions.models import ExceptionCase, FinancialImpactSnapshot, FinancialRecoveryItem

CENTS = Decimal("0.01")


def to_cents(value: Decimal | None) -> Decimal | None:
    """Display quantization only. Never applied before arithmetic."""
    if value is None:
        return None
    return value.quantize(CENTS, rounding=ROUND_HALF_UP)


@transaction.atomic
def record_candidate(
    *,
    case: ExceptionCase,
    financial: FinancialInputs,
    calculation_code: str,
    calculation_version: int,
    rule_identity: str,
) -> tuple[FinancialImpactSnapshot, bool]:
    """Append a candidate snapshot if the inputs changed; otherwise return the current one.

    Returns (snapshot, appended). An identical recalculation appends nothing, which is
    what keeps detector replay from minting duplicate value (section 33.4).
    """
    latest = (
        FinancialImpactSnapshot.objects.filter(exception_case=case)
        .order_by("-snapshot_version")
        .first()
    )
    if (
        latest is not None
        and latest.basis == financial.basis
        and latest.candidate_value == financial.candidate_value
        and latest.assumptions == financial.assumptions
        and latest.calculation_version == calculation_version
    ):
        return latest, False

    snapshot = FinancialImpactSnapshot.objects.create(
        organization=case.organization,
        exception_case=case,
        snapshot_version=(latest.snapshot_version + 1) if latest else 1,
        calculation_code=calculation_code,
        calculation_version=calculation_version,
        currency=case.work_order.contract.currency if case.work_order else "USD",
        candidate_value=financial.candidate_value,
        basis=financial.basis,
        assumptions=financial.assumptions,
        calculated_by_rule=rule_identity,
    )

    if case.work_order is None:
        # ck_revenue_case_has_work_order makes this unreachable for a revenue case.
        raise ValueError("A financial snapshot requires a case with a work order.")
    item, _ = FinancialRecoveryItem.objects.get_or_create(
        organization=case.organization,
        exception_case=case,
        defaults={"work_order": case.work_order},
    )
    item.current_candidate_snapshot = snapshot
    item.save(update_fields=["current_candidate_snapshot", "updated_at"])
    return snapshot, True


def stage_totals(organization_id) -> dict[str, Decimal | None]:
    """RETIRED. Superseded by `apps.recovery.selectors.stage_totals`.

    This is the Phase 4 selector. It has **no site-scope parameter**, so wiring it to any
    reader-facing view reintroduces the leak that Phase 2 of the demo-to-outreach plan
    closed: it aggregates every recovery item in the organization regardless of who is
    asking. It also reports only `candidate`, because the other three stages did not
    exist when it was written.

    It is kept for one reason: `tests/test_cockpit_scope.py` uses it to demonstrate the
    behavioural difference against its replacement, which counts items whose exception
    case is no longer open. **Do not call it from application code.** The supported
    selector takes `limit_to_site_ids` and returns all four stages.

    Phase 4 can populate `candidate` only, from each open case's CURRENT candidate
    snapshot. The other three are returned as None - meaning "no data", not zero.
    """
    open_states = ["new", "acknowledged", "action_pending", "waiting_external", "escalated"]
    items = FinancialRecoveryItem.objects.filter(
        organization_id=organization_id,
        exception_case__state__in=open_states,
        current_candidate_snapshot__isnull=False,
    ).select_related("current_candidate_snapshot")

    values = [
        item.current_candidate_snapshot.candidate_value
        for item in items
        if item.current_candidate_snapshot
        and item.current_candidate_snapshot.candidate_value is not None
    ]
    candidate = sum(values, Decimal("0")) if values else None
    return {
        "candidate": to_cents(candidate),
        "invoice_ready": None,
        "invoiced": None,
        "collected": None,
    }
