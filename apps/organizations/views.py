"""Organization selection.

Section 17, rule 4: the active organization is derived from an authenticated
membership. The POST here accepts an organization id, but it is only ever a *candidate*
— it is resolved through the user's own active memberships, so submitting another
tenant's id cannot select it.
"""

from __future__ import annotations

import uuid

from django.contrib.auth.decorators import login_required
from django.http import HttpRequest, HttpResponse
from django.shortcuts import redirect, render
from django.views.decorators.http import require_http_methods

from apps.organizations.context import authenticated_user, set_active_organization
from apps.organizations.selectors import active_memberships_for, membership_for


@login_required
@require_http_methods(["GET", "POST"])
def select_organization(request: HttpRequest) -> HttpResponse:
    user = authenticated_user(request)
    memberships = list(active_memberships_for(user))

    if request.method == "POST":
        raw = request.POST.get("organization_id", "")
        try:
            organization_id = uuid.UUID(raw)
        except (ValueError, TypeError):
            return render(
                request,
                "organizations/select_organization.html",
                {"memberships": memberships, "error": "Choose an organization to continue."},
                status=400,
            )

        # Resolved through the caller's own memberships. A valid id belonging to
        # another tenant simply does not resolve, and is reported the same way as an
        # unknown one so membership elsewhere is not disclosed.
        membership = membership_for(user, organization_id)
        if membership is None:
            return render(
                request,
                "organizations/select_organization.html",
                {"memberships": memberships, "error": "That organization is not available to you."},
                status=404,
            )

        set_active_organization(request, membership)
        return redirect("app:home")

    return render(request, "organizations/select_organization.html", {"memberships": memberships})
