"""Recovery ledger, approval, export, and protected download (sections 29, 30.5)."""

from __future__ import annotations

import uuid
from decimal import Decimal

from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.http import Http404, HttpRequest, HttpResponse, HttpResponseBadRequest
from django.shortcuts import redirect, render
from django.views.decorators.http import require_GET, require_POST

from apps.exceptions.models import FinancialRecoveryItem
from apps.exceptions.services.financial import to_cents
from apps.organizations.models import Membership
from apps.organizations.policy import Denied, allows, effective_site_scope, require
from apps.organizations.roles import Action, Role
from apps.recovery import selectors
from apps.recovery.services import approvals, exports


def _membership(request: HttpRequest) -> Membership:
    membership = getattr(request, "membership", None)
    if membership is None:
        raise Http404
    return membership


@login_required
@require_GET
def ledger(request: HttpRequest) -> HttpResponse:
    membership = getattr(request, "membership", None)
    if membership is None:
        return redirect("organizations:select-organization")
    require(membership, Action.VIEW_ORGANIZATION)

    organization_id = membership.organization_id
    site_scope = effective_site_scope(membership)
    items = selectors.ledger_items(organization_id, limit_to_site_ids=site_scope)
    rows = []
    for item in items:
        candidate = item.current_candidate_snapshot
        ready = item.current_invoice_ready_snapshot
        checklist = approvals.build_checklist(item, membership=membership)
        rows.append(
            {
                "item": item,
                "case": item.exception_case,
                "candidate": to_cents(candidate.candidate_value) if candidate else None,
                "basis": candidate.get_basis_display() if candidate else "",
                "invoice_ready": to_cents(ready.invoice_ready_value) if ready else None,
                "invoiced": to_cents(item.actual_invoiced_amount),
                "collected": to_cents(item.actual_collected_amount),
                "missing_count": len(checklist.missing),
                "missing_labels": [i.label for i in checklist.missing],
                "can_approve": checklist.is_complete
                and item.workflow_state == FinancialRecoveryItem.WorkflowState.CANDIDATE,
            }
        )

    raw_totals = selectors.stage_totals(organization_id, limit_to_site_ids=site_scope)
    totals = {
        key: to_cents(value) if isinstance(value, Decimal) else value
        for key, value in raw_totals.items()
    }
    return render(
        request,
        "recovery/ledger.html",
        {
            "rows": rows,
            "totals": totals,
            "exports": selectors.exports_for_organization(organization_id)[:10],
            "can_approve": allows(membership, Action.APPROVE_INVOICE_READY),
            "can_export": allows(membership, Action.EXPORT_FINANCE_CSV),
            "exportable": [
                {"id": item.id, "case_number": item.exception_case.case_number}
                for item in exports.exportable_items(organization_id)
            ],
        },
    )


@login_required
@require_POST
def approve_invoice_ready(request: HttpRequest, item_id: uuid.UUID) -> HttpResponse:
    membership = _membership(request)
    try:
        approvals.approve_invoice_ready(
            membership=membership,
            req=approvals.ApprovalRequest(
                item_id=item_id,
                expected_version=int(request.POST.get("version", "-1")),
                reason=request.POST.get("reason", "")[:1000],
                request_id=getattr(request, "request_id", ""),
            ),
        )
    except Denied:
        return HttpResponse(status=403)
    except FinancialRecoveryItem.DoesNotExist:
        raise Http404 from None
    except approvals.EvidenceIncomplete as exc:
        messages.error(
            request,
            "Cannot approve: "
            + "; ".join(i.label for i in exc.checklist.missing)
            + ". Correct the source data and re-import.",
        )
    except approvals.StaleSubject:
        messages.error(request, "Someone changed this item first. Review it and try again.")
    except (approvals.ApprovalError, ValueError) as exc:
        messages.error(request, str(exc))
    else:
        messages.success(request, "Approved as invoice-ready. No invoice was created.")
    return redirect("recovery:ledger")


@login_required
@require_POST
def export_csv(request: HttpRequest) -> HttpResponse:
    membership = _membership(request)
    # The form posts the ids it displayed. A resubmit therefore names the same set and
    # resolves to the export that already handled it, instead of reporting an empty one.
    try:
        item_ids = [uuid.UUID(value) for value in request.POST.getlist("item_id")] or None
    except ValueError:
        return HttpResponseBadRequest("Malformed item id.")
    try:
        export, created = exports.export_invoice_ready(
            membership=membership,
            item_ids=item_ids,
            request_id=getattr(request, "request_id", ""),
        )
    except Denied:
        return HttpResponse(status=403)
    except exports.ExportError as exc:
        messages.error(request, str(exc))
        return redirect("recovery:ledger")
    messages.success(
        request,
        f"Export {'created' if created else 'already existed'}: {export.row_count} row(s). "
        "No invoice was created and nothing was sent.",
    )
    return redirect("recovery:export-download", export_id=export.id)


@login_required
@require_GET
def export_download(request: HttpRequest, export_id: uuid.UUID) -> HttpResponse:
    """Tenant- and role-scoped download (section 29, line 1884).

    A denied role gets 403 because the object's existence is not the secret; another
    tenant's export gets 404 because its existence is (section 17, rule 8).
    """
    membership = _membership(request)
    if not (membership.active_roles & {Role.OWNER, Role.FINANCE_REVIEWER}):
        return HttpResponse(status=403)
    require(membership, Action.EXPORT_FINANCE_CSV)

    export = exports.get_export_for_download(membership=membership, export_id=export_id)
    if export is None:
        raise Http404

    # UTF-8 with BOM so spreadsheets open it correctly; the leading apostrophe applied
    # by neutralize_formula is preserved either way.
    response = HttpResponse(
        export.content.encode("utf-8-sig"), content_type="text/csv; charset=utf-8"
    )
    response["Content-Disposition"] = f'attachment; filename="{export.filename}"'
    response["X-Content-Type-Options"] = "nosniff"
    return response
