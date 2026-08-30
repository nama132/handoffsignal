"""Invoice-ready CSV export (master prompt sections 23.1, 29, 30.5).

The export is the product's actual deliverable: a file a bookkeeper can raise the
invoice from **in their own system**, without this product. It therefore carries the
source identifiers, the contract basis, the approval provenance, and the evidence
references — not just an amount.

Three rules shape it:

  * **Idempotent.** The same approved item set exports to the same record; a second
    request returns the existing export rather than minting a duplicate reference.
  * **Immutable.** Content is hashed and frozen. A source correction after export opens
    a dispute; it never rewrites or erases what was handed off (line 1389, 1391).
  * **Formula-safe.** Every cell is neutralized before it reaches the file.

No invoice is created and nothing is sent. `EXTERNAL_ACTIONS_ENABLED` remains false.
"""

from __future__ import annotations

import decimal
import hashlib
import uuid

from django.db import transaction

from apps.audit import models as audit
from apps.exceptions.models import FinancialRecoveryItem
from apps.ingestion.models import ExternalEntityReference
from apps.ingestion.parsing import write_csv
from apps.organizations.models import Membership
from apps.organizations.policy import Denied, require
from apps.organizations.roles import Action, Role
from apps.recovery.models import Approval, FinanceExport, FinancialStageEvent
from apps.recovery.services.checklist import ITEM_CODES

#: Columns a bookkeeper needs to raise the invoice elsewhere, plus the provenance that
#: makes the amount auditable. Order is deliberate: identity, then scope, then money,
#: then who approved it and on what evidence.
COLUMNS = [
    "case_number",
    "customer_name",
    "site_name",
    "service_date",
    "work_order_source_system",
    "work_order_external_id",
    "contract_reference",
    "service_obligation_code",
    "billing_basis",
    "invoice_ready_value",
    "currency",
    "authorization_reference",
    "authorized_at",
    "calculation_code",
    "calculation_version",
    "snapshot_version",
    "approved_by",
    "approved_at",
    "evidence_complete",
    "accounting_coverage_basis",
]


class ExportError(Exception):
    pass


#: Re-proved at export time. These are the items whose truth can change between the
#: approval and the handoff, because they read the accounting source rather than the
#: contract. The rest were fixed when the reviewer approved.
_EXPORT_TIME_ITEMS = frozenset({ITEM_CODES[7], ITEM_CODES[8]})


def _require_finance(membership: Membership) -> None:
    """Section 9.3: export and download are owner/finance only."""
    require(membership, Action.EXPORT_FINANCE_CSV)
    if not (membership.active_roles & {Role.OWNER, Role.FINANCE_REVIEWER}):  # pragma: no cover
        raise Denied("Only an owner or finance reviewer may export finance data.")


def exportable_items(organization_id: uuid.UUID):
    """Approved, not-yet-exported, undisputed items."""
    return (
        FinancialRecoveryItem.objects.filter(
            organization_id=organization_id,
            workflow_state=FinancialRecoveryItem.WorkflowState.INVOICE_READY,
        )
        .exclude(dispute_status=FinancialRecoveryItem.DisputeStatus.OPEN)
        .select_related(
            "exception_case",
            "work_order__customer",
            "work_order__site",
            "work_order__contract",
            "work_order__service_obligation",
            "current_invoice_ready_snapshot",
        )
        .order_by("exception_case__case_number")
    )


def _idempotency_key(items) -> str:
    """Stable across requests for the same item set at the same approved snapshots.

    Keyed on the snapshot rather than the item version so that a resubmitted request
    returns the export that already exists. A re-approval after a source correction
    mints a new snapshot, so that is a genuinely different export -- never a silent
    reuse of the old one.
    """
    parts = sorted(f"{item.id}:{item.current_invoice_ready_snapshot_id}" for item in items)
    return hashlib.sha256("|".join(parts).encode("utf-8")).hexdigest()


def _replay(organization_id: uuid.UUID, item_ids: list[uuid.UUID]) -> FinanceExport | None:
    """Resolve a resubmitted export request to the export that already handled it.

    A double submit is the ordinary case: the first request exports the items and the
    second finds nothing left in `invoice_ready`. Answering "nothing to export" there
    would be true but useless, and re-running would mint a second reference for work
    that was already handed off. Instead we rebuild the key from the same items at
    their current snapshots; if it matches, the caller gets the original export back.
    """
    items = list(
        FinancialRecoveryItem.objects.filter(
            organization_id=organization_id,
            id__in=item_ids,
            workflow_state=FinancialRecoveryItem.WorkflowState.EXPORTED,
        )
    )
    if len(items) != len(set(item_ids)):
        return None
    return FinanceExport.objects.filter(
        organization_id=organization_id, idempotency_key=_idempotency_key(items)
    ).first()


def _row(item: FinancialRecoveryItem) -> dict[str, object]:
    case = item.exception_case
    work_order = item.work_order
    snapshot = item.current_invoice_ready_snapshot
    approval = (
        item.approvals.filter(
            approval_type=Approval.ApprovalType.INVOICE_READY,
            decision=Approval.Decision.APPROVED,
            revoked_at__isnull=True,
        )
        .select_related("decided_by__user")
        .first()
    )
    # A work order can carry a confirmed reference in more than one source system.
    # Order explicitly: an unordered .first() would put a different identifier in the
    # file on different runs, and the bookkeeper keys their invoice off this column.
    reference = (
        ExternalEntityReference.objects.filter(
            organization_id=item.organization_id,
            entity_type="work_order",
            work_order=work_order,
            mapping_status=ExternalEntityReference.MappingStatus.CONFIRMED,
        )
        .select_related("source")
        .order_by("source__system_key", "external_id")
        .first()
    )
    evidence = (approval.evidence_snapshot if approval else {}) or {}
    coverage_item: dict[str, object] = next(
        (i for i in evidence.get("items", []) if i.get("code") == ITEM_CODES[7]), {}
    )
    return {
        "case_number": case.case_number,
        "customer_name": work_order.customer.name,
        "site_name": work_order.site.name,
        "service_date": case.service_date.isoformat() if case.service_date else "",
        "work_order_source_system": reference.source.system_key if reference else "",
        "work_order_external_id": reference.external_id if reference else "",
        "contract_reference": work_order.contract.contract_reference,
        "service_obligation_code": work_order.service_obligation.code
        if work_order.service_obligation
        else "",
        "billing_basis": snapshot.basis if snapshot else "",
        "invoice_ready_value": snapshot.invoice_ready_value if snapshot else "",
        "currency": snapshot.currency if snapshot else "",
        "authorization_reference": work_order.authorization_reference,
        "authorized_at": work_order.authorized_at.isoformat() if work_order.authorized_at else "",
        "calculation_code": snapshot.calculation_code if snapshot else "",
        "calculation_version": snapshot.calculation_version if snapshot else "",
        "snapshot_version": snapshot.snapshot_version if snapshot else "",
        "approved_by": approval.decided_by.user.email if approval else "",
        "approved_at": approval.decided_at.isoformat() if approval else "",
        "evidence_complete": "yes" if evidence.get("complete") else "no",
        "accounting_coverage_basis": coverage_item.get("detail", ""),
    }


@transaction.atomic
def export_invoice_ready(
    *, membership: Membership, item_ids: list[uuid.UUID] | None = None, request_id: str = ""
) -> tuple[FinanceExport, bool]:
    """Generate (or return) the export for the approved item set.

    Returns (export, created). A second call for the same set returns the existing
    record — one idempotent export reference, per section 23.1 line 1386.
    """
    _require_finance(membership)

    queryset = exportable_items(membership.organization_id)
    if item_ids is not None:
        queryset = queryset.filter(id__in=item_ids)
    items = list(queryset.select_for_update(of=("self",)))
    if not items:
        replayed = _replay(membership.organization_id, item_ids) if item_ids else None
        if replayed is not None:
            return replayed, False
        raise ExportError("There is nothing approved and undisputed to export.")

    key = _idempotency_key(items)
    existing = FinanceExport.objects.filter(
        organization_id=membership.organization_id, idempotency_key=key
    ).first()
    if existing is not None:
        return existing, False

    # Approval proved the work was unbilled *then*. An `invoice_status` import can
    # arrive between approval and export, and the file we hand a bookkeeper is an
    # instruction to raise an invoice. Re-prove it now, under the same lock, or hand
    # over nothing: a second invoice to a real client is the false positive section
    # 8.3 names as a kill criterion.
    from apps.recovery.services import approvals as approvals_service

    for item in items:
        recheck = approvals_service.build_checklist(item)
        blocking = [i for i in recheck.items if i.code in _EXPORT_TIME_ITEMS and not i.satisfied]
        if blocking:
            raise ExportError(
                f"{item.exception_case.case_number} can no longer be exported: "
                + " ".join(i.detail for i in blocking)
            )
        if item.accounting_stage != FinancialRecoveryItem.AccountingStage.NO_INVOICE:
            raise ExportError(
                f"{item.exception_case.case_number} is now recorded as "
                f"{item.get_accounting_stage_display().lower()} in the accounting source. "
                "It was not exported."
            )
        if item.dispute_status == FinancialRecoveryItem.DisputeStatus.OPEN:
            raise ExportError(
                f"{item.exception_case.case_number} has an open dispute "
                f"({item.dispute_reason}). It was not exported."
            )

    currencies = {
        item.current_invoice_ready_snapshot.currency
        for item in items
        if item.current_invoice_ready_snapshot is not None
    }
    if len(currencies) > 1:
        # One file carries one total. Mixing currencies would either sum them, which
        # is meaningless, or label the file with one of them, which is worse.
        raise ExportError(
            "This set spans more than one currency ("
            + ", ".join(sorted(currencies))
            + "). Export one currency at a time."
        )

    rows = [_row(item) for item in items]
    content = write_csv(rows, COLUMNS)
    total = sum(
        (
            item.current_invoice_ready_snapshot.invoice_ready_value
            for item in items
            if item.current_invoice_ready_snapshot
            and item.current_invoice_ready_snapshot.invoice_ready_value is not None
        ),
        decimal.Decimal("0"),
    )

    export = FinanceExport.objects.create(
        organization=membership.organization,
        idempotency_key=key,
        content_sha256=hashlib.sha256(content.encode("utf-8")).hexdigest(),
        content=content,
        row_count=len(rows),
        total_invoice_ready_value=total,
        currency=next(iter(currencies), "USD"),
        created_by=membership,
    )
    export.items.set(items)

    for item in items:
        previous = item.workflow_state
        item.workflow_state = FinancialRecoveryItem.WorkflowState.EXPORTED
        item.export_reference = str(export.id)
        item.version += 1
        item.save()
        FinancialStageEvent.objects.create(
            organization=item.organization,
            financial_recovery_item=item,
            kind=FinancialStageEvent.Kind.WORKFLOW,
            from_value=previous,
            to_value=item.workflow_state,
            reason_code="finance_export",
            actor_membership=membership,
            note=f"Export {export.id}",
        )
        Approval.objects.create(
            organization=item.organization,
            exception_case=item.exception_case,
            approval_type=Approval.ApprovalType.FINANCE_EXPORT,
            decision=Approval.Decision.APPROVED,
            financial_recovery_item=item,
            subject_version=item.version,
            decided_by=membership,
            reason=f"Exported in {export.id}",
        )

    audit.record(
        organization=membership.organization,
        action="recovery.export.created",
        object_type="recovery.FinanceExport",
        object_id=export.id,
        actor_membership=membership,
        request_id=request_id,
        metadata={"count": len(rows)},
    )
    return export, True


def get_export_for_download(
    *, membership: Membership, export_id: uuid.UUID
) -> FinanceExport | None:
    """Fetch an export for download, or None.

    Returns None for another tenant's export so the caller can answer 404 without
    revealing that it exists. The role check is the caller's responsibility and is
    performed before this is called.
    """
    return FinanceExport.objects.filter(
        organization_id=membership.organization_id, id=export_id
    ).first()


def mark_superseded(export: FinanceExport, note: str) -> FinanceExport:
    """Record that a source correction arrived after this export.

    Section 23.1 line 1389: "an exported item is retained and marked for external
    correction, never erased."
    """
    export.superseded_note = note[:500]
    export.save(update_fields=["superseded_note", "updated_at"])
    return export
