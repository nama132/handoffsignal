"""The invoice-ready evidence checklist (master prompt section 6, lines 2707-2718).

Ten items. Every one must pass before a candidate may become invoice-ready:

    "If any required item is missing, block approval and show the exact missing
     evidence. Do not provide a bypass checkbox."

The absence of a bypass is **structural**, not a UI choice. `evaluate()` is the only
producer of a checklist, `approve_invoice_ready()` calls it itself rather than trusting
anything a caller passes, and there is no argument, flag, or setting that skips an item.
A view cannot construct a passing checklist it did not earn.

Item 8 is deliberately re-evaluated against **current** data rather than trusting the
detection-time finding, because section 23.1 line 1401 explicitly contemplates an invoice
arriving between detection and approval. Approving on a stale absence would be the exact
false positive the product exists to avoid.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from apps.exceptions.detectors import revenue_unbilled as detector
from apps.exceptions.models import ExceptionCase, FinancialImpactSnapshot, FinancialRecoveryItem
from apps.ingestion.models import ExternalEntityReference, ReconciliationRun


@dataclass(frozen=True)
class ChecklistItem:
    code: str
    label: str
    satisfied: bool
    detail: str = ""

    @property
    def status(self) -> str:
        return "present" if self.satisfied else "missing"


@dataclass
class Checklist:
    items: list[ChecklistItem] = field(default_factory=list)

    @property
    def is_complete(self) -> bool:
        return all(item.satisfied for item in self.items)

    @property
    def missing(self) -> list[ChecklistItem]:
        return [item for item in self.items if not item.satisfied]

    @property
    def missing_codes(self) -> list[str]:
        return [item.code for item in self.missing]

    def as_dict(self) -> dict[str, object]:
        return {
            "complete": self.is_complete,
            "items": [
                {"code": i.code, "label": i.label, "satisfied": i.satisfied, "detail": i.detail}
                for i in self.items
            ],
        }


#: Codes in checklist order, so the UI and the tests share one vocabulary.
ITEM_CODES = (
    "work_order_source_id_and_service_date",
    "completed_state_and_time",
    "active_applicable_contract",
    "confirmed_obligation_and_crosswalks",
    "billable_flag",
    "authorization_reference_when_required",
    "supported_rate_basis_and_amount",
    "accounting_coverage_and_no_existing_invoice",
    "duplicate_case_or_export_check",
    "finance_reviewer_approval",
)


def evaluate(
    item: FinancialRecoveryItem,
    *,
    run: ReconciliationRun | None = None,
    approver_is_finance: bool = False,
) -> Checklist:
    """Build the checklist for one recovery item.

    `approver_is_finance` supplies item 10 — the caller's own authority — because the
    checklist itself cannot know who is asking. The approval service passes the result of
    its own role check, so item 10 can never be satisfied by an unauthorised caller.
    """
    checklist = Checklist()
    case: ExceptionCase = item.exception_case
    work_order = item.work_order

    # ---- 1. work-order source id and service date -----------------------------------
    source_reference = (
        ExternalEntityReference.objects.filter(
            organization_id=item.organization_id,
            entity_type="work_order",
            work_order=work_order,
            mapping_status=ExternalEntityReference.MappingStatus.CONFIRMED,
        )
        .order_by("external_id")
        .first()
    )
    has_identity = source_reference is not None and case.service_date is not None
    identity_detail = (
        f"{source_reference.source.system_key}:{source_reference.external_id} "
        f"on {case.service_date.isoformat()}"
        if source_reference is not None and case.service_date is not None
        else "No confirmed source identifier, or no service occurrence date."
    )
    checklist.items.append(
        ChecklistItem(
            ITEM_CODES[0], "Work-order source ID and service date", has_identity, identity_detail
        )
    )

    # ---- 2. completed state and time -------------------------------------------------
    completed = (
        work_order.status == work_order.Status.COMPLETED and work_order.completed_at is not None
    )
    checklist.items.append(
        ChecklistItem(
            ITEM_CODES[1],
            "Completed state and time",
            completed,
            f"Completed {work_order.completed_at:%Y-%m-%d %H:%M} UTC"
            if completed
            else f"Source status is {work_order.get_status_display()}.",
        )
    )

    # ---- 3. active applicable contract ----------------------------------------------
    contract_active = bool(
        case.service_date and work_order.contract.is_active_on(case.service_date)
    )
    checklist.items.append(
        ChecklistItem(
            ITEM_CODES[2],
            "Active applicable contract",
            contract_active,
            f"{work_order.contract.contract_reference} active on {case.service_date}"
            if contract_active
            else "The contract is not active for this service date.",
        )
    )

    # ---- 4. confirmed obligation and identity crosswalks ----------------------------
    obligation = work_order.service_obligation
    required = {
        "customer": work_order.customer_id,
        "site": work_order.site_id,
        "contract": work_order.contract_id,
    }
    if obligation is not None:
        required["service_obligation"] = obligation.id
    unconfirmed = [
        entity
        for entity, target_id in required.items()
        if target_id
        and not ExternalEntityReference.objects.filter(
            organization_id=item.organization_id,
            entity_type=entity,
            mapping_status=ExternalEntityReference.MappingStatus.CONFIRMED,
            **{f"{entity}_id": target_id},
        ).exists()
    ]
    crosswalks_ok = obligation is not None and not unconfirmed
    if obligation is None:
        crosswalk_detail = "No service obligation is linked."
    elif unconfirmed:
        crosswalk_detail = f"Unconfirmed references: {', '.join(unconfirmed)}."
    else:
        crosswalk_detail = f"Obligation {obligation.code}; all references confirmed"
    checklist.items.append(
        ChecklistItem(
            ITEM_CODES[3],
            "Confirmed service obligation and identity crosswalks",
            crosswalks_ok,
            crosswalk_detail,
        )
    )

    # ---- 5. billable flag ------------------------------------------------------------
    checklist.items.append(
        ChecklistItem(
            ITEM_CODES[4],
            "Billable flag",
            bool(work_order.billable),
            "Marked billable at source"
            if work_order.billable
            else "Not marked billable at source.",
        )
    )

    # ---- 6. authorization reference when required -----------------------------------
    authorized = obligation is not None and detector._has_authorization(work_order, obligation)
    if obligation is None:
        detail = "No obligation, so the authorization policy cannot be determined."
    elif not detector._authorization_required(work_order, obligation):
        detail = "Authorization is not required for this scope."
    elif authorized:
        detail = (
            f"Reference {work_order.authorization_reference} on {work_order.authorized_at:%Y-%m-%d}"
        )
    else:
        detail = "Authorization is required but no reference and date are recorded."
    checklist.items.append(
        ChecklistItem(ITEM_CODES[5], "Authorization reference when required", authorized, detail)
    )

    # ---- 7. supported rate basis and amount inputs ----------------------------------
    snapshot: FinancialImpactSnapshot | None = item.current_candidate_snapshot
    basis_ok = (
        snapshot is not None
        and snapshot.basis != FinancialImpactSnapshot.Basis.MANUAL_AMOUNT_REQUIRED
        and snapshot.candidate_value is not None
    )
    if snapshot is None:
        detail = "No candidate calculation exists."
    elif snapshot.basis == FinancialImpactSnapshot.Basis.MANUAL_AMOUNT_REQUIRED:
        missing_input = snapshot.assumptions.get("missing", "an amount input")
        detail = f"Manual amount required: {missing_input} is not supplied by the source."
    elif snapshot.candidate_value is None:
        detail = "The calculation produced no amount."
    else:
        detail = f"{snapshot.get_basis_display()}: {snapshot.candidate_value}"
    checklist.items.append(
        ChecklistItem(ITEM_CODES[6], "Supported rate basis and amount inputs", basis_ok, detail)
    )

    # ---- 8. accounting coverage and no existing invoice ------------------------------
    # Re-evaluated against CURRENT data. An invoice may have arrived since detection
    # (section 23.1 line 1401); approving on a stale absence would be a false positive.
    coverage_ok = False
    invoice_absent = False
    coverage_detail = "No reconciliation run supplies an accounting coverage declaration."
    if run is not None and case.service_date is not None:
        _, service_dates = detector._service_dates(work_order)
        coverage_ok = detector._accounting_coverage_proves_absence(run, work_order, service_dates)
        invoice_absent = not detector._confirmed_invoice_exists(work_order, service_dates)
        if not coverage_ok:
            coverage_detail = (
                "The accounting snapshot does not declare complete, authoritative coverage "
                "of this customer and site for the service date."
            )
        elif not invoice_absent:
            coverage_detail = (
                "An invoice matching this customer, site and service date now exists in the "
                "accounting source. This candidate is no longer unbilled."
            )
        else:
            coverage_detail = "Complete authoritative coverage; no matching invoice found."
    checklist.items.append(
        ChecklistItem(
            ITEM_CODES[7],
            "Fresh authoritative accounting coverage with no existing invoice",
            coverage_ok and invoice_absent,
            coverage_detail,
        )
    )

    # ---- 9. duplicate case or export check -------------------------------------------
    already_exported = (
        item.workflow_state in (FinancialRecoveryItem.WorkflowState.EXPORTED,)
        or item.exports.exists()
    )
    other_active = (
        FinancialRecoveryItem.objects.filter(
            organization_id=item.organization_id, work_order=work_order
        )
        .exclude(pk=item.pk)
        .exclude(workflow_state=FinancialRecoveryItem.WorkflowState.VOID)
        .exists()
    )
    no_duplicate = not already_exported and not other_active
    checklist.items.append(
        ChecklistItem(
            ITEM_CODES[8],
            "Duplicate case or export check",
            no_duplicate,
            "No prior export or competing recovery item"
            if no_duplicate
            else (
                "This work order has already been exported."
                if already_exported
                else "Another active recovery item exists for this work order."
            ),
        )
    )

    # ---- 10. finance reviewer approval ------------------------------------------------
    checklist.items.append(
        ChecklistItem(
            ITEM_CODES[9],
            "Finance reviewer approval",
            approver_is_finance,
            "Reviewer holds the finance or owner role"
            if approver_is_finance
            else "Only an organization owner or finance reviewer may approve invoice-ready value.",
        )
    )

    return checklist
