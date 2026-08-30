"""Import, identity-resolution, and reconciliation screens.

Every view resolves its organization from the authenticated membership, checks the
section 9.3 action before doing anything, and returns 404 (not 403) for an object in
another tenant so existence is not disclosed.
"""

from __future__ import annotations

import uuid
from typing import Any

from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.http import Http404, HttpRequest, HttpResponse
from django.shortcuts import redirect, render
from django.views.decorators.http import require_GET, require_POST

from apps.ingestion import selectors
from apps.ingestion.forms import ImportUploadForm
from apps.ingestion.models import IdentityResolutionIssue, ImportBatch, ReconciliationIssue
from apps.ingestion.services import coverage as coverage_service
from apps.ingestion.services import identity as identity_service
from apps.ingestion.services import imports as import_service
from apps.ingestion.services import reconciliation as reconciliation_service
from apps.organizations.models import Membership
from apps.organizations.policy import require
from apps.organizations.roles import Action

#: Which action each file type's commit requires (section 9.3, rows 3-5).
COMMIT_ACTION_FOR_KIND = {
    "sites_contracts": Action.COMMIT_FINANCIAL_IMPORT,
    "invoice_status": Action.COMMIT_FINANCIAL_IMPORT,
    "work_orders_service_events": Action.COMMIT_OPERATIONAL_IMPORT,
    "entity_crosswalk": Action.COMMIT_CROSSWALK_IMPORT,
}


def _membership_or_redirect(request: HttpRequest) -> Membership | None:
    return getattr(request, "membership", None)


def _require_membership(request: HttpRequest) -> Membership:
    """Return the active membership or fail closed with 404.

    Views reached without a resolved tenant have no organization to scope to. Raising
    404 rather than proceeding means a middleware misconfiguration can never become an
    unscoped query.
    """
    membership = getattr(request, "membership", None)
    if membership is None:
        raise Http404
    return membership


@login_required
@require_GET
def import_list(request: HttpRequest) -> HttpResponse:
    membership = _membership_or_redirect(request)
    if membership is None:
        return redirect("organizations:select-organization")
    require(membership, Action.VIEW_ORGANIZATION)

    organization_id = membership.organization_id
    return render(
        request,
        "ingestion/import_list.html",
        {
            "batches": selectors.batches_for_organization(organization_id)[:50],
            "freshness": selectors.source_freshness(organization_id),
            "open_identity_issues": selectors.open_identity_issues(organization_id).count(),
            "open_reconciliation_issues": selectors.open_reconciliation_issues(
                organization_id
            ).count(),
        },
    )


@login_required
def import_new(request: HttpRequest) -> HttpResponse:
    membership = _membership_or_redirect(request)
    if membership is None:
        return redirect("organizations:select-organization")
    require(membership, Action.UPLOAD_PREVIEW_FILES)

    organization = membership.organization
    form = ImportUploadForm(request.POST or None, request.FILES or None, organization=organization)

    if request.method == "POST" and form.is_valid():
        kind = form.cleaned_data["kind"]
        # Uploading is not committing: the commit action is checked again at commit time,
        # but refusing here avoids parsing a file the caller could never promote.
        require(membership, COMMIT_ACTION_FOR_KIND[kind])

        declaration = coverage_service.CoverageDeclaration(
            record_family=form.record_family,
            scope_type="organization",
            coverage_start_at=form.cleaned_data["coverage_start_at"],
            coverage_end_at=form.cleaned_data["coverage_end_at"],
            query_contract_code=form.cleaned_data.get("query_contract_code") or "",
            query_contract_version=1,
            completeness=form.cleaned_data["completeness"],
            declaration_basis=form.cleaned_data["declaration_basis"],
        )
        result = import_service.upload(
            organization=organization,
            source=form.cleaned_data["source"],
            kind=kind,
            filename=form.cleaned_data["upload"].name,
            payload=form.cleaned_data["upload"].read(),
            observation_mode=form.cleaned_data["observation_mode"],
            source_as_of_at=form.cleaned_data["source_as_of_at"],
            declarations=[declaration],
            actor=request.user,
        )
        if result.batch is None:
            for error in result.file_errors:
                form.add_error(None, f"{error.code}: {error.guidance}")
        else:
            if result.duplicate_of is not None:
                messages.info(
                    request,
                    "This exact file and observation was already imported. Nothing changed.",
                )
            return redirect("ingestion:import-preview", batch_id=result.batch.id)

    return render(request, "ingestion/import_new.html", {"form": form})


def _batch_or_404(request: HttpRequest, batch_id: uuid.UUID) -> ImportBatch:
    membership = _require_membership(request)
    batch = selectors.get_batch_or_none(membership.organization_id, batch_id)
    if batch is None:
        # 404, never 403: a batch in another tenant must not be revealed to exist.
        raise Http404
    return batch


@login_required
@require_GET
def import_preview(request: HttpRequest, batch_id: uuid.UUID) -> HttpResponse:
    membership = _require_membership(request)
    require(membership, Action.UPLOAD_PREVIEW_FILES)
    batch = _batch_or_404(request, batch_id)
    context = import_service.preview(batch)
    context["commit_action"] = COMMIT_ACTION_FOR_KIND[batch.kind]
    return render(request, "ingestion/import_preview.html", context)


@login_required
@require_POST
def import_commit(request: HttpRequest, batch_id: uuid.UUID) -> HttpResponse:
    membership = _require_membership(request)
    batch = _batch_or_404(request, batch_id)
    # The commit permission depends on the file type, not on being able to see it.
    require(membership, COMMIT_ACTION_FOR_KIND[batch.kind])

    try:
        import_service.commit(batch, request.user)
    except import_service.CommitRefused as exc:
        messages.error(request, str(exc))
        return redirect("ingestion:import-preview", batch_id=batch.id)

    messages.success(request, "Import committed.")
    return redirect("ingestion:import-results", batch_id=batch.id)


@login_required
@require_GET
def import_results(request: HttpRequest, batch_id: uuid.UUID) -> HttpResponse:
    membership = _require_membership(request)
    require(membership, Action.VIEW_ORGANIZATION)
    batch = _batch_or_404(request, batch_id)
    return render(
        request,
        "ingestion/import_results.html",
        {
            "batch": batch,
            "coverage": list(batch.coverage_declarations.all()),
            "quarantined": batch.rows.filter(status="invalid").order_by("row_number")[:100],
        },
    )


@login_required
@require_GET
def identity_queue(request: HttpRequest) -> HttpResponse:
    membership = _membership_or_redirect(request)
    if membership is None:
        return redirect("organizations:select-organization")
    require(membership, Action.VIEW_ORGANIZATION)
    return render(
        request,
        "ingestion/identity_queue.html",
        {
            "issues": selectors.open_identity_issues(membership.organization_id),
            # Confirming an identity crosses the operational/financial boundary and is
            # owner-only (section 9.3, line 372).
            "can_resolve": _can(membership, Action.RESOLVE_IDENTITY),
        },
    )


def _can(membership: Membership, action: str) -> bool:
    from apps.organizations.policy import allows

    return allows(membership, action)


@login_required
@require_POST
def identity_resolve(request: HttpRequest, issue_id: uuid.UUID) -> HttpResponse:
    membership = _require_membership(request)
    require(membership, Action.RESOLVE_IDENTITY)

    issue = IdentityResolutionIssue.objects.filter(
        organization_id=membership.organization_id, id=issue_id
    ).first()
    if issue is None:
        raise Http404

    target_id = request.POST.get("target_id", "")
    from apps.ingestion.services.normalizers import CustomerAccount, Site

    model: Any = {"customer": CustomerAccount, "site": Site}.get(issue.entity_type)
    if model is None:
        messages.error(request, "This entity type cannot be resolved in this phase.")
        return redirect("ingestion:identity-queue")

    target = model.objects.filter(organization_id=membership.organization_id, id=target_id).first()
    if target is None:
        messages.error(request, "Choose a record in this organization.")
        return redirect("ingestion:identity-queue")

    identity_service.resolve_issue_manually(
        issue=issue,
        target=target,
        resolved_by=request.user,
        note=request.POST.get("note", "")[:500],
    )
    messages.success(request, "Identity confirmed.")
    return redirect("ingestion:identity-queue")


@login_required
@require_GET
def reconciliation_queue(request: HttpRequest) -> HttpResponse:
    membership = _membership_or_redirect(request)
    if membership is None:
        return redirect("organizations:select-organization")
    require(membership, Action.VIEW_ORGANIZATION)
    return render(
        request,
        "ingestion/reconciliation_queue.html",
        {
            "issues": selectors.open_reconciliation_issues(membership.organization_id),
            "runs": reconciliation_service.runs_for_organization(membership.organization_id)[:10],
            "can_resolve_operational": _can(membership, Action.RESOLVE_OPERATIONAL_RECONCILIATION),
            "can_resolve_financial": _can(membership, Action.RESOLVE_FINANCIAL_RECONCILIATION),
        },
    )


#: Field groups whose resolution crosses into finance and needs the finance role.
FINANCIAL_FIELD_GROUPS = {"contract_rate", "invoice_status"}


@login_required
@require_POST
def reconciliation_resolve(request: HttpRequest, issue_id: uuid.UUID) -> HttpResponse:
    membership = _require_membership(request)
    issue = ReconciliationIssue.objects.filter(
        organization_id=membership.organization_id, id=issue_id
    ).first()
    if issue is None:
        raise Http404

    action = (
        Action.RESOLVE_FINANCIAL_RECONCILIATION
        if issue.field_group in FINANCIAL_FIELD_GROUPS
        else Action.RESOLVE_OPERATIONAL_RECONCILIATION
    )
    require(membership, action)

    reconciliation_service.resolve_issue(
        issue=issue,
        chosen_source=None,
        resolved_by=request.user,
        note=request.POST.get("note", "")[:500],
    )
    messages.success(request, "Reconciliation issue resolved.")
    return redirect("ingestion:reconciliation-queue")


__all__ = [
    "identity_queue",
    "identity_resolve",
    "import_commit",
    "import_list",
    "import_new",
    "import_preview",
    "import_results",
    "reconciliation_queue",
    "reconciliation_resolve",
]
