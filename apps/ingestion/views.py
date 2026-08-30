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
from apps.ingestion.models import (
    FINANCIAL_FIELD_GROUPS,
    OPERATIONAL_FIELD_GROUPS,
    IdentityResolutionIssue,
    ImportBatch,
    ReconciliationIssue,
)
from apps.ingestion.services import coverage as coverage_service
from apps.ingestion.services import identity as identity_service
from apps.ingestion.services import imports as import_service
from apps.ingestion.services import reconciliation as reconciliation_service
from apps.organizations.models import Membership
from apps.organizations.policy import Denied, require
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
            # The badge and the queue must show the same set. A count the reader cannot
            # then open is how they learn something exists that is not theirs to see.
            "open_reconciliation_issues": selectors.open_reconciliation_issues_for(
                membership
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
            "issues": selectors.open_reconciliation_issues_for(membership),
            "runs": reconciliation_service.runs_for_organization(membership.organization_id)[:10],
            "can_resolve_operational": _can(membership, Action.RESOLVE_OPERATIONAL_RECONCILIATION),
            "can_resolve_financial": _can(membership, Action.RESOLVE_FINANCIAL_RECONCILIATION),
        },
    )


def _action_for(field_group: str) -> str:
    """Which action resolving this conflict requires."""
    if field_group in FINANCIAL_FIELD_GROUPS:
        return Action.RESOLVE_FINANCIAL_RECONCILIATION
    return Action.RESOLVE_OPERATIONAL_RECONCILIATION


def _resolvable_field_groups(membership: Membership) -> frozenset[str]:
    """The reconciliation domains this member may resolve, as field-group values.

    Empty means no resolution authority of any kind, which is decided before any object
    is looked up.
    """
    groups: set[str] = set()
    if _can(membership, Action.RESOLVE_OPERATIONAL_RECONCILIATION):
        groups |= OPERATIONAL_FIELD_GROUPS
    if _can(membership, Action.RESOLVE_FINANCIAL_RECONCILIATION):
        groups |= FINANCIAL_FIELD_GROUPS
    return frozenset(groups)


@login_required
@require_POST
def reconciliation_resolve(request: HttpRequest, issue_id: uuid.UUID) -> HttpResponse:
    """Resolve one reconciliation issue.

    The ordering here is the security property, not an implementation detail.

    1. **Authority is decided before any lookup.** A member with no resolution authority
       is refused without the database being asked whether the id exists, so a 403 can
       never double as confirmation that an issue is there.
    2. **The lookup is confined to the domains this member may resolve.** An operations
       manager asking for an invoice-status issue gets exactly what they get for a UUID
       that was never issued: 404. The two are indistinguishable, so the pair cannot be
       used to enumerate finance conflicts.
    3. **The action check still runs before the mutation.** Steps 1 and 2 narrow what can
       be reached; only this decides what may be done, and it is the one the service
       relies on.
    """
    membership = _require_membership(request)

    authorized_groups = _resolvable_field_groups(membership)
    if not authorized_groups:
        # Before the lookup, deliberately. Nothing here reveals whether issue_id exists.
        raise Denied("This role may not resolve reconciliation issues.")

    issue = ReconciliationIssue.objects.filter(
        organization_id=membership.organization_id,
        id=issue_id,
        field_group__in=authorized_groups,
    ).first()
    if issue is None:
        # Unknown id, another tenant's id, or an id in a domain this member may not
        # resolve. All three answer identically (section 17, rule 8).
        raise Http404

    require(membership, _action_for(issue.field_group))

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
