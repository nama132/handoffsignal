"""Accounting-stage derivation (master prompt section 23.1, lines 1393-1401).

The five rules, and the one that matters most:

    "actual_invoiced_amount is the sum of distinct active mapped invoice amounts in the
     item's currency. actual_collected_amount is the sum of distinct `posted` payments
     attached to those invoices. **Never sum the invoice amount once per payment row.**"

The shipped `invoice_status.csv` has one $1,200 invoice across two payment rows. A naive
join over invoice x payment would report $2,400 invoiced. Derivation therefore aggregates
over the DISTINCT invoice set first, and only then sums payments attached to it.

Nothing here changes `ExceptionCase.state`. Section 23.1 line 1401: an invoice arriving
through another process "does **not** change ExceptionCase.state" — a finance reviewer
must use the transition service to resolve or dismiss.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass, field
from decimal import Decimal

from django.db import transaction

from apps.audit import models as audit
from apps.exceptions.models import FinancialRecoveryItem
from apps.operations.models import AccountingInvoice, AccountingPayment
from apps.recovery.models import FinancialStageEvent

ZERO = Decimal("0")


class DisputeReason:
    OVER_COLLECTION = "over_collection"
    CURRENCY_MISMATCH = "currency_mismatch"
    VOID_AFTER_STAGE = "void_after_prior_stage"
    AMOUNT_CHANGED = "invoice_amount_changed"
    AMBIGUOUS_MAPPING = "ambiguous_invoice_mapping"
    REVERSED_PAYMENT = "payment_reversed_after_collection"
    DISPUTED_INVOICE = "invoice_disputed_at_source"
    DISPUTED_PAYMENT = "payment_disputed_at_source"


@dataclass
class Derivation:
    stage: str
    invoiced: Decimal | None
    collected: Decimal | None
    dispute: str = ""
    invoice_ids: list[uuid.UUID] = field(default_factory=list)


def _invoices_matching(
    item: FinancialRecoveryItem, *, statuses: tuple[str, ...]
) -> list[AccountingInvoice]:
    """Invoices in the given source states that this item's work order matches.

    Matching runs on the work-order link when the accounting source supplies one, else
    on the confirmed customer/site crosswalk plus service date. Deduplication is by
    canonical identity (the row), never by display reference.

    The status filter is a parameter because the same matching has to answer two
    different questions: which invoices count as billed, and whether an invoice the
    source is contesting exists at all.
    """
    work_order = item.work_order
    service_date = item.exception_case.service_date
    candidates = AccountingInvoice.objects.filter(
        organization_id=item.organization_id, source_status__in=statuses
    )
    direct = list(candidates.filter(work_order=work_order))
    if direct:
        return direct
    if service_date is None:
        return []
    return list(
        candidates.filter(
            customer_id=work_order.customer_id,
            site_id=work_order.site_id,
            service_date=service_date,
        )
    )


def _mapped_invoices(item: FinancialRecoveryItem) -> list[AccountingInvoice]:
    """Active invoices mapped to this item's work order.

    Rule 1: map each non-void, NON-DISPUTED canonical invoice to at most one active
    recovery item. A disputed invoice is a claim the customer is contesting; treating
    it as billed would both hide a real recovery candidate and report money as invoiced
    that the source itself does not stand behind.
    """
    return _invoices_matching(item, statuses=(AccountingInvoice.SourceStatus.POSTED,))


def derive(item: FinancialRecoveryItem) -> Derivation:
    """Compute the accounting stage and actual amounts. Pure: performs no writes."""
    invoices = _mapped_invoices(item)

    if not invoices:
        # Rule 4: no active mapped invoice.
        void_exists = bool(
            _invoices_matching(item, statuses=(AccountingInvoice.SourceStatus.VOID,))
        )
        disputed_exists = bool(
            _invoices_matching(item, statuses=(AccountingInvoice.SourceStatus.DISPUTED,))
        )
        if disputed_exists:
            # The source is contesting its own invoice. That is a fact for a human,
            # never a silent return to "nobody has billed this".
            return Derivation(
                FinancialRecoveryItem.AccountingStage.NO_INVOICE,
                None,
                None,
                DisputeReason.DISPUTED_INVOICE,
            )
        dispute = (
            DisputeReason.VOID_AFTER_STAGE
            if (
                void_exists
                and item.accounting_stage != FinancialRecoveryItem.AccountingStage.NO_INVOICE
            )
            else ""
        )
        return Derivation(FinancialRecoveryItem.AccountingStage.NO_INVOICE, None, None, dispute)

    currencies = {invoice.currency for invoice in invoices}
    reference_snapshot = item.current_invoice_ready_snapshot or item.current_candidate_snapshot
    item_currency = reference_snapshot.currency if reference_snapshot is not None else "USD"
    if len(currencies) > 1 or currencies != {item_currency}:
        # Rule 5: currency mismatch is a dispute, never a conversion.
        return Derivation(
            item.accounting_stage,
            None,
            None,
            DisputeReason.CURRENCY_MISMATCH,
            [i.id for i in invoices],
        )

    if len(invoices) > 1:
        # A work order billed by several invoices is unsupported in the demo
        # (section 22.4): it opens a dispute rather than being summed and guessed.
        return Derivation(
            item.accounting_stage,
            None,
            None,
            DisputeReason.AMBIGUOUS_MAPPING,
            [i.id for i in invoices],
        )

    # ---- the distinct-invoice rule ------------------------------------------------
    # Sum over the DISTINCT invoice set, then over payments attached to it. Summing a
    # joined invoice x payment rowset would count a $1,200 invoice twice when it has
    # two payments.
    invoiced = sum((invoice.invoice_amount for invoice in invoices), ZERO)

    payments = AccountingPayment.objects.filter(
        organization_id=item.organization_id, accounting_invoice__in=invoices
    )
    posted = [p for p in payments if p.source_status == AccountingPayment.SourceStatus.POSTED]
    reversed_exists = any(
        p.source_status == AccountingPayment.SourceStatus.REVERSED for p in payments
    )
    disputed_payment = any(
        p.source_status == AccountingPayment.SourceStatus.DISPUTED for p in payments
    )
    collected = sum((p.collected_amount for p in posted), ZERO)

    dispute = ""
    if disputed_payment:
        dispute = DisputeReason.DISPUTED_PAYMENT
    elif collected > invoiced:
        dispute = DisputeReason.OVER_COLLECTION
    elif reversed_exists and item.accounting_stage in (
        FinancialRecoveryItem.AccountingStage.COLLECTED,
        FinancialRecoveryItem.AccountingStage.PARTIALLY_COLLECTED,
    ):
        dispute = DisputeReason.REVERSED_PAYMENT

    # Rule 4: the stage as a pure function of the two amounts.
    if collected <= ZERO:
        stage = FinancialRecoveryItem.AccountingStage.INVOICED
    elif collected < invoiced:
        stage = FinancialRecoveryItem.AccountingStage.PARTIALLY_COLLECTED
    else:
        stage = FinancialRecoveryItem.AccountingStage.COLLECTED

    return Derivation(stage, invoiced, collected, dispute, [i.id for i in invoices])


@transaction.atomic
def refresh(
    item_id: uuid.UUID, *, actor_rule: str = "ACCOUNTING_DERIVATION_V1"
) -> FinancialRecoveryItem:
    """Recompute one item's accounting stage, appending an event only on a real change.

    Replay-safe: re-observing the same accounting rows produces the same derivation and
    appends nothing (section 33.4 line 2098, "Replay an accounting invoice/payment
    observation: one financial stage event and actual amount").
    """
    item = FinancialRecoveryItem.objects.select_for_update(of=("self",)).get(pk=item_id)
    result = derive(item)

    stage_changed = item.accounting_stage != result.stage
    amounts_changed = (
        item.actual_invoiced_amount != result.invoiced
        or item.actual_collected_amount != result.collected
    )
    dispute_changed = (
        bool(result.dispute) and item.dispute_status != FinancialRecoveryItem.DisputeStatus.OPEN
    )

    if not (stage_changed or amounts_changed or dispute_changed):
        return item

    previous_stage = item.accounting_stage
    item.accounting_stage = result.stage
    item.actual_invoiced_amount = result.invoiced
    item.actual_collected_amount = result.collected
    if result.dispute:
        item.dispute_status = FinancialRecoveryItem.DisputeStatus.OPEN
        item.dispute_reason = result.dispute
    item.save()

    if stage_changed:
        FinancialStageEvent.objects.create(
            organization=item.organization,
            financial_recovery_item=item,
            kind=FinancialStageEvent.Kind.ACCOUNTING,
            from_value=previous_stage,
            to_value=result.stage,
            reason_code="derived_from_accounting_source",
            actor_rule=actor_rule,
            source_invoice_id=result.invoice_ids[0] if result.invoice_ids else None,
        )
    if result.dispute and dispute_changed:
        FinancialStageEvent.objects.create(
            organization=item.organization,
            financial_recovery_item=item,
            kind=FinancialStageEvent.Kind.DISPUTE,
            to_value=FinancialRecoveryItem.DisputeStatus.OPEN,
            reason_code=result.dispute,
            actor_rule=actor_rule,
            note="Excluded from actual-value totals until a finance reviewer resolves it.",
        )
        audit.record(
            organization=item.organization,
            action="recovery.dispute.opened",
            object_type="exceptions.FinancialRecoveryItem",
            object_id=item.id,
            actor_rule=actor_rule,
            metadata={"reason_code": result.dispute},
        )
    return item


def refresh_organization(organization_id: uuid.UUID) -> int:
    """Recompute every item in one organization. Returns how many changed."""
    changed = 0
    for item_id in FinancialRecoveryItem.objects.filter(
        organization_id=organization_id
    ).values_list("id", flat=True):
        before = FinancialRecoveryItem.objects.values_list("accounting_stage", flat=True).get(
            pk=item_id
        )
        after = refresh(item_id)
        if after.accounting_stage != before:
            changed += 1
    return changed


@transaction.atomic
def resolve_dispute(*, membership, item_id: uuid.UUID, note: str) -> FinancialRecoveryItem:
    """Resolve a dispute and recompute. Prior events are never rewritten (line 1399)."""
    from apps.organizations.policy import require
    from apps.organizations.roles import Action

    require(membership, Action.RESOLVE_FINANCIAL_RECONCILIATION)
    item = (
        FinancialRecoveryItem.objects.select_for_update(of=("self",))
        .filter(organization_id=membership.organization_id, id=item_id)
        .first()
    )
    if item is None:
        raise FinancialRecoveryItem.DoesNotExist
    if item.dispute_status != FinancialRecoveryItem.DisputeStatus.OPEN:
        raise ValueError("Only an open dispute can be resolved.")
    if not note.strip():
        raise ValueError("Resolving a dispute requires a reason.")

    item.dispute_status = FinancialRecoveryItem.DisputeStatus.RESOLVED
    item.save(update_fields=["dispute_status", "updated_at"])
    FinancialStageEvent.objects.create(
        organization=item.organization,
        financial_recovery_item=item,
        kind=FinancialStageEvent.Kind.DISPUTE,
        from_value=FinancialRecoveryItem.DisputeStatus.OPEN,
        to_value=FinancialRecoveryItem.DisputeStatus.RESOLVED,
        actor_membership=membership,
        note=note[:500],
    )
    return refresh(item.id)
