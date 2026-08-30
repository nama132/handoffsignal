"""Invoice-ready approval (master prompt sections 22.6, 23.1).

The transition `candidate -> invoice_ready` requires "finance reviewer/owner approval;
current immutable calculation snapshot and complete evidence checklist" (line 1386).

This service is the only way to make that transition. It:

  * locks the recovery item and re-checks the caller's role under that organization,
  * requires the caller's expected version (a stale approval is refused),
  * **builds the checklist itself** — it never accepts one from a caller, so there is no
    bypass to pass in,
  * refuses on any missing item and reports exactly which,
  * writes the approval, the stage event, and the audit event in one transaction.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass

from django.db import transaction
from django.utils import timezone

from apps.audit import models as audit
from apps.exceptions.models import FinancialImpactSnapshot, FinancialRecoveryItem
from apps.ingestion.models import ReconciliationRun
from apps.organizations.models import Membership
from apps.organizations.policy import Denied, require
from apps.organizations.roles import Action, Role
from apps.recovery.models import Approval, FinancialStageEvent
from apps.recovery.services import checklist as checklist_service


class ApprovalError(Exception):
    """An approval the lifecycle, the checklist, or versioning refuses."""


class StaleSubject(ApprovalError):
    """The item changed since the caller loaded it."""


class EvidenceIncomplete(ApprovalError):
    """One or more checklist items are missing. Carries the exact codes."""

    def __init__(self, checklist: checklist_service.Checklist) -> None:
        codes = ", ".join(checklist.missing_codes)
        super().__init__(f"Missing evidence: {codes}")
        self.checklist = checklist


@dataclass(frozen=True)
class ApprovalRequest:
    item_id: uuid.UUID
    expected_version: int
    reason: str = ""
    request_id: str = ""


def _require_finance(membership: Membership) -> None:
    """Section 9.3: only owner and finance reviewer may approve invoice-ready value."""
    require(membership, Action.APPROVE_INVOICE_READY)
    if not (membership.active_roles & {Role.OWNER, Role.FINANCE_REVIEWER}):  # pragma: no cover
        raise Denied("Only an owner or finance reviewer may approve invoice-ready value.")


def build_checklist(
    item: FinancialRecoveryItem, *, membership: Membership | None = None
) -> checklist_service.Checklist:
    """Checklist for display. Item 10 reflects the viewer's own authority."""
    is_finance = bool(
        membership and (membership.active_roles & {Role.OWNER, Role.FINANCE_REVIEWER})
    )
    return checklist_service.evaluate(
        item, run=_latest_ready_run(item.organization_id), approver_is_finance=is_finance
    )


def _latest_ready_run(organization_id: uuid.UUID) -> ReconciliationRun | None:
    """The most recent ready manifest, used to re-check accounting coverage."""
    return (
        ReconciliationRun.objects.filter(
            organization_id=organization_id, status=ReconciliationRun.Status.READY
        )
        .order_by("-as_of", "-created_at")
        .first()
    )


@transaction.atomic
def approve_invoice_ready(*, membership: Membership, req: ApprovalRequest) -> Approval:
    """Approve one candidate as invoice-ready. Raises rather than partially applying."""
    # `of=("self",)` locks only this row. Combining select_for_update() with
    # select_related() across a NULLABLE foreign key produces a LEFT OUTER JOIN, and
    # PostgreSQL refuses FOR UPDATE on the nullable side of one.
    item = (
        FinancialRecoveryItem.objects.select_for_update(of=("self",))
        .filter(organization_id=membership.organization_id, id=req.item_id)
        .select_related("exception_case", "work_order", "current_candidate_snapshot")
        .first()
    )
    if item is None:
        # Cross-tenant or unknown: indistinguishable (section 17 rule 8).
        raise FinancialRecoveryItem.DoesNotExist

    _require_finance(membership)

    if item.version != req.expected_version:
        raise StaleSubject(
            f"Item is at version {item.version}; you acted on {req.expected_version}."
        )
    if item.workflow_state != FinancialRecoveryItem.WorkflowState.CANDIDATE:
        raise ApprovalError(
            f"Only a candidate may be approved invoice-ready; this item is {item.workflow_state}."
        )

    if item.dispute_status == FinancialRecoveryItem.DisputeStatus.OPEN:
        # Section 21.2 line 966: "A blocking conflict prevents dependent
        # detector/financial approval until resolved."
        raise ApprovalError(
            f"An open dispute ({item.dispute_reason}) blocks approval. "
            "Resolve the conflict in the accounting source first."
        )

    # The checklist is built HERE, from current data, using this caller's own authority.
    # No argument can substitute for it.
    result = checklist_service.evaluate(
        item,
        run=_latest_ready_run(item.organization_id),
        approver_is_finance=True,  # _require_finance already proved this
    )
    if not result.is_complete:
        raise EvidenceIncomplete(result)

    snapshot = item.current_candidate_snapshot
    if snapshot is None:  # pragma: no cover - checklist item 7 already required it
        raise ApprovalError("No candidate calculation exists to approve.")
    previous_state = item.workflow_state

    approval = Approval.objects.create(
        organization=item.organization,
        exception_case=item.exception_case,
        approval_type=Approval.ApprovalType.INVOICE_READY,
        decision=Approval.Decision.APPROVED,
        financial_recovery_item=item,
        subject_version=item.version,
        financial_snapshot=snapshot,
        evidence_snapshot=result.as_dict(),
        decided_by=membership,
        reason=req.reason[:1000],
    )

    # The invoice-ready value is the approved candidate amount, recorded as its own
    # immutable snapshot version so the two stages stay distinguishable (section 26).
    ready_snapshot = FinancialImpactSnapshot.objects.create(
        organization=item.organization,
        exception_case=item.exception_case,
        snapshot_version=snapshot.snapshot_version + 1,
        calculation_code=snapshot.calculation_code,
        calculation_version=snapshot.calculation_version,
        currency=snapshot.currency,
        candidate_value=snapshot.candidate_value,
        invoice_ready_value=snapshot.candidate_value,
        basis=snapshot.basis,
        assumptions={**snapshot.assumptions, "approved_from_snapshot": snapshot.snapshot_version},
        calculated_by_rule=f"invoice_ready_approval:{membership.user.email}",
        approved_at=timezone.now(),
        approved_by=membership,
    )
    approval.financial_snapshot = ready_snapshot
    approval.save(update_fields=["financial_snapshot"])

    item.workflow_state = FinancialRecoveryItem.WorkflowState.INVOICE_READY
    item.current_invoice_ready_snapshot = ready_snapshot
    item.version += 1
    item.save()

    FinancialStageEvent.objects.create(
        organization=item.organization,
        financial_recovery_item=item,
        kind=FinancialStageEvent.Kind.WORKFLOW,
        from_value=previous_state,
        to_value=item.workflow_state,
        reason_code="invoice_ready_approved",
        actor_membership=membership,
        note=req.reason[:500],
    )
    audit.record(
        organization=item.organization,
        action="recovery.invoice_ready.approved",
        object_type="exceptions.FinancialRecoveryItem",
        object_id=item.id,
        actor_membership=membership,
        request_id=req.request_id,
        metadata={
            "case_number": item.exception_case.case_number,
            "snapshot_version": ready_snapshot.snapshot_version,
            "object_version": item.version,
        },
    )
    return approval


@transaction.atomic
def revoke_invoice_ready(
    *, membership: Membership, item_id: uuid.UUID, expected_version: int, reason: str
) -> FinancialRecoveryItem:
    """Return an item to candidate. Only `source_revision_invalidated`, only before export.

    Section 23.1: "`invoice_ready` -> `candidate`: only `source_revision_invalidated`
    before any export; revoke the old approval, append an event, and require a new
    snapshot/review."
    """
    item = (
        FinancialRecoveryItem.objects.select_for_update(of=("self",))
        .filter(organization_id=membership.organization_id, id=item_id)
        .first()
    )
    if item is None:
        raise FinancialRecoveryItem.DoesNotExist
    _require_finance(membership)

    if item.version != expected_version:
        raise StaleSubject("The item changed since you loaded it.")
    if item.workflow_state == FinancialRecoveryItem.WorkflowState.EXPORTED or item.exports.exists():
        raise ApprovalError(
            "This item has been exported. A source correction after export opens a dispute; "
            "it never rolls the item backward."
        )
    if item.workflow_state != FinancialRecoveryItem.WorkflowState.INVOICE_READY:
        raise ApprovalError("Only an invoice-ready item may be returned to candidate.")
    if not reason.strip():
        raise ApprovalError("A revocation requires a reason.")

    live = item.approvals.filter(
        approval_type=Approval.ApprovalType.INVOICE_READY,
        decision=Approval.Decision.APPROVED,
        revoked_at__isnull=True,
    ).first()
    if live is not None:
        live.revoked_at = timezone.now()
        live.revoked_by = membership
        live.save(update_fields=["revoked_at", "revoked_by"])

    item.workflow_state = FinancialRecoveryItem.WorkflowState.CANDIDATE
    item.current_invoice_ready_snapshot = None
    item.version += 1
    item.save()

    FinancialStageEvent.objects.create(
        organization=item.organization,
        financial_recovery_item=item,
        kind=FinancialStageEvent.Kind.WORKFLOW,
        from_value=FinancialRecoveryItem.WorkflowState.INVOICE_READY,
        to_value=FinancialRecoveryItem.WorkflowState.CANDIDATE,
        reason_code="source_revision_invalidated",
        actor_membership=membership,
        note=reason[:500],
    )
    audit.record(
        organization=item.organization,
        action="recovery.invoice_ready.revoked",
        object_type="exceptions.FinancialRecoveryItem",
        object_id=item.id,
        actor_membership=membership,
        metadata={"reason_code": "source_revision_invalidated", "object_version": item.version},
    )
    return item
