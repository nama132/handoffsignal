"""Tenant-scoped shell.

Every query here passes an explicit organization (section 17, rule 5). The page states
truthfully what does and does not exist at this phase, so a viewer cannot mistake the
foundation for a working exception inbox.
"""

from __future__ import annotations

from django.contrib.auth.decorators import login_required
from django.http import HttpRequest, HttpResponse
from django.shortcuts import redirect, render

from apps.operations.selectors import (
    customers_for_organization,
    sites_for_organization,
)
from apps.organizations.policy import allows, effective_site_scope
from apps.organizations.roles import Action


@login_required
def home(request: HttpRequest) -> HttpResponse:
    membership = getattr(request, "membership", None)
    if membership is None:
        # No organization resolved: either none, or several and none chosen yet.
        return redirect("organizations:select-organization")

    if not allows(membership, Action.VIEW_ORGANIZATION):
        # A membership of a suspended organization, or with no role grant at all.
        return render(request, "dashboard/no_access.html", status=403)

    organization = membership.organization

    # Site scope, not just organization scope. A supervisor with no site grants must
    # reach no site data at all; an empty set here is passed through verbatim and is
    # never downgraded to "unfiltered" (section 22.2, line 841).
    site_scope = effective_site_scope(membership)
    customers = customers_for_organization(organization.id, limit_to_site_ids=site_scope)
    sites = sites_for_organization(organization.id, limit_to_site_ids=site_scope)

    return render(
        request,
        "dashboard/home.html",
        {
            "organization": organization,
            "membership": membership,
            "active_roles": sorted(membership.active_roles),
            "customers": customers,
            "sites": sites,
            "site_scope_is_limited": site_scope is not None,
            "granted_site_count": membership.site_grants.count(),
            "can_manage_memberships": allows(membership, Action.MANAGE_MEMBERSHIPS),
            "can_manage_sources": allows(membership, Action.MANAGE_DATA_SOURCES),
            "can_resolve_identity": allows(membership, Action.RESOLVE_IDENTITY),
        },
    )
