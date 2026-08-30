"""Cockpit, inbox, and case detail (master prompt sections 29 and 30).

Views validate input and authorization, call a service, and render. No transition or
financial logic lives here. Cross-tenant lookups return 404 (section 17, rule 8).
"""

from __future__ import annotations

import uuid

from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.http import Http404, HttpRequest, HttpResponse
from django.shortcuts import redirect, render
from django.views.decorators.http import require_GET, require_POST

from apps.exceptions import selectors
from apps.exceptions.models import (
    REVENUE_DISMISSAL_CODES,
    REVENUE_RESOLUTION_CODES,
    CaseState,
    Severity,
)
from apps.exceptions.services import financial, transitions
from apps.exceptions.services.transitions import ALLOWED_EDGES, TransitionRequest
from apps.ingestion import selectors as ingestion_selectors
from apps.organizations.models import Membership
from apps.organizations.policy import Denied, allows, effective_site_scope, require
from apps.organizations.roles import Action, Role


def _require_membership(request: HttpRequest) -> Membership:
    membership = getattr(request, "membership", None)
    if membership is None:
        raise Http404
    return membership


def _can_transition(membership: Membership, case, to_state: str) -> bool:
    """Mirror of the transition service's role rule, for rendering buttons only.

    Server-side enforcement happens in the service regardless (section 30.3).
    """
    if (case.state, to_state) not in ALLOWED_EDGES:
        return False
    roles = transitions._roles_for(case, to_state)
    return bool(membership.active_roles & roles)


@login_required
@require_GET
def cockpit(request: HttpRequest) -> HttpResponse:
    membership = getattr(request, "membership", None)
    if membership is None:
        return redirect("organizations:select-organization")
    require(membership, Action.VIEW_ORGANIZATION)
    organization_id = membership.organization_id
    site_scope = effective_site_scope(membership)

    open_cases = selectors.cases_for_organization(
        organization_id, limit_to_site_ids=site_scope
    ).filter(state__in=selectors.OPEN_STATES)
    return render(
        request,
        "exceptions/cockpit.html",
        {
            "counts_by_severity": selectors.open_case_counts(organization_id),
            "open_case_count": open_cases.count(),
            "stages": financial.stage_totals(organization_id),
            "freshness": ingestion_selectors.source_freshness(organization_id),
            "unresolved_identities": ingestion_selectors.open_identity_issues(
                organization_id
            ).count(),
            "failed_runs": selectors.failed_runs(organization_id).count(),
            "recent_runs": selectors.recent_runs(organization_id, limit=5),
            "recent_cases": open_cases[:5],
        },
    )


@login_required
@require_GET
def inbox(request: HttpRequest) -> HttpResponse:
    membership = getattr(request, "membership", None)
    if membership is None:
        return redirect("organizations:select-organization")
    require(membership, Action.VIEW_ORGANIZATION)

    state = request.GET.get("state", "")
    severity = request.GET.get("severity", "")
    owner = request.GET.get("owner", "")
    cases = selectors.cases_for_organization(
        membership.organization_id,
        limit_to_site_ids=effective_site_scope(membership),
        state=state if state in CaseState.values else "",
        severity=severity if severity in Severity.values else "",
        owner_id=uuid.UUID(owner) if _is_uuid(owner) else None,
    )
    return render(
        request,
        "exceptions/inbox.html",
        {
            "cases": cases[:200],
            "states": CaseState.choices,
            "severities": Severity.choices,
            "filters": {"state": state, "severity": severity, "owner": owner},
        },
    )


def _is_uuid(value: str) -> bool:
    try:
        uuid.UUID(value)
        return True
    except (ValueError, TypeError):
        return False


def _case_or_404(request: HttpRequest, case_id: uuid.UUID):
    membership = _require_membership(request)
    case = selectors.get_case_or_none(
        membership.organization_id, case_id, limit_to_site_ids=effective_site_scope(membership)
    )
    if case is None:
        raise Http404
    return membership, case


@login_required
@require_GET
def case_detail(request: HttpRequest, case_id: uuid.UUID) -> HttpResponse:
    membership, case = _case_or_404(request, case_id)
    require(membership, Action.VIEW_ORGANIZATION)

    snapshots = list(case.financial_snapshots.order_by("snapshot_version"))
    current = snapshots[-1] if snapshots else None
    allowed_targets = [s for s in CaseState.values if _can_transition(membership, case, s)]
    members = (
        Membership.objects.filter(organization_id=membership.organization_id, is_active=True)
        .select_related("user")
        .order_by("user__email")
    )

    return render(
        request,
        "exceptions/case_detail.html",
        {
            "case": case,
            "work_order": case.work_order,
            "snapshot": current,
            "candidate_cents": financial.to_cents(current.candidate_value) if current else None,
            "snapshots": snapshots,
            "recovery_item": getattr(case, "recovery_item", None),
            "events": case.events.select_related("actor_membership__user").order_by("occurred_at"),
            "source_links": case.source_links.select_related("source_record_version__source"),
            "allowed_targets": allowed_targets,
            "can_assign": (not case.is_terminal)
            and bool(
                membership.active_roles
                & {Role.OWNER, Role.FINANCE_REVIEWER, Role.OPERATIONS_MANAGER}
            ),
            "resolution_codes": sorted(REVENUE_RESOLUTION_CODES),
            "dismissal_codes": sorted(REVENUE_DISMISSAL_CODES),
            "members": members,
        },
    )


@login_required
@require_POST
def acknowledge(request: HttpRequest, case_id: uuid.UUID) -> HttpResponse:
    return _do_transition(request, case_id, CaseState.ACKNOWLEDGED)


@login_required
@require_POST
def transition(request: HttpRequest, case_id: uuid.UUID) -> HttpResponse:
    to_state = request.POST.get("to_state", "")
    if to_state not in CaseState.values:
        messages.error(request, "Unknown target state.")
        return redirect("exceptions:case-detail", case_id=case_id)
    return _do_transition(request, case_id, to_state)


def _do_transition(request: HttpRequest, case_id: uuid.UUID, to_state: str) -> HttpResponse:
    membership, case = _case_or_404(request, case_id)
    try:
        expected_version = int(request.POST.get("version", ""))
    except ValueError:
        messages.error(request, "The form is missing its version; reload and try again.")
        return redirect("exceptions:case-detail", case_id=case.id)

    owner_raw = request.POST.get("owner_membership_id", "")
    req = TransitionRequest(
        case_id=case.id,
        expected_version=expected_version,
        to_state=to_state,
        reason_code=request.POST.get("reason_code", "")[:40],
        note=request.POST.get("note", "")[:1000],
        owner_membership_id=uuid.UUID(owner_raw) if _is_uuid(owner_raw) else None,
        request_id=getattr(request, "request_id", ""),
    )
    try:
        transitions.transition(membership=membership, req=req)
    except transitions.StaleVersion:
        messages.error(request, "Someone else changed this case first. Review and try again.")
    except transitions.TransitionError as exc:
        messages.error(request, str(exc))
    except Denied:
        return HttpResponse(status=403)
    else:
        messages.success(request, f"Case moved to {to_state.replace('_', ' ')}.")
    return redirect("exceptions:case-detail", case_id=case.id)


@login_required
@require_POST
def assign_owner(request: HttpRequest, case_id: uuid.UUID) -> HttpResponse:
    membership, case = _case_or_404(request, case_id)
    owner_raw = request.POST.get("owner_membership_id", "")
    if not _is_uuid(owner_raw):
        messages.error(request, "Choose a member.")
        return redirect("exceptions:case-detail", case_id=case.id)
    try:
        transitions.assign_owner(
            membership=membership,
            case_id=case.id,
            expected_version=int(request.POST.get("version", "0")),
            owner_membership_id=uuid.UUID(owner_raw),
            request_id=getattr(request, "request_id", ""),
        )
    except transitions.StaleVersion:
        messages.error(request, "Someone else changed this case first. Review and try again.")
    except transitions.TransitionError as exc:
        messages.error(request, str(exc))
    except Denied:
        return HttpResponse(status=403)
    else:
        messages.success(request, "Owner updated.")
    return redirect("exceptions:case-detail", case_id=case.id)


__all__ = ["acknowledge", "allows", "assign_owner", "case_detail", "cockpit", "inbox", "transition"]
