"""Active-organization resolution.

Section 17, rule 4: "Derive active organization from an authenticated membership,
never from an untrusted form field alone."

The session holds only a candidate organization id. It is re-validated against an
active membership on **every** request, so revoking a membership takes effect on the
next request rather than at the next login (section 33.3, line 2085).
"""

from __future__ import annotations

import uuid
from collections.abc import Callable
from typing import cast

from django.core.exceptions import PermissionDenied
from django.http import HttpRequest, HttpResponse

from apps.organizations.models import Membership, User
from apps.organizations.selectors import active_memberships_for, membership_for

SESSION_ORGANIZATION_KEY = "active_organization_id"


def authenticated_user(request: HttpRequest) -> User:
    """Narrow `request.user` to the concrete model behind a @login_required view.

    Django types `request.user` as `User | AnonymousUser`. Inside a @login_required
    view the anonymous case is unreachable, but the check is kept rather than casting
    blindly so a decorator removed by mistake fails closed instead of proceeding with
    an anonymous principal.
    """
    user = request.user
    if not user.is_authenticated:  # pragma: no cover - @login_required guarantees this
        raise PermissionDenied("Authentication is required.")
    return user


def resolve_active_membership(request: HttpRequest) -> Membership | None:
    """Return the caller's active membership, or None.

    The session value is a *candidate*, never an authorization. If it does not resolve
    to a currently active membership of an active organization, it is discarded.
    """
    raw_user = getattr(request, "user", None)
    if raw_user is None or not raw_user.is_authenticated:
        return None
    user = cast(User, raw_user)

    candidate = request.session.get(SESSION_ORGANIZATION_KEY)
    if candidate:
        try:
            organization_id = uuid.UUID(str(candidate))
        except (ValueError, TypeError):
            request.session.pop(SESSION_ORGANIZATION_KEY, None)
        else:
            membership = membership_for(user, organization_id)
            if membership is not None:
                return membership
            # Stale or revoked: drop it rather than carrying it forward.
            request.session.pop(SESSION_ORGANIZATION_KEY, None)

    # With exactly one membership there is nothing to choose, so select it implicitly.
    memberships = list(active_memberships_for(user)[:2])
    if len(memberships) == 1:
        set_active_organization(request, memberships[0])
        return memberships[0]
    return None


def set_active_organization(request: HttpRequest, membership: Membership) -> None:
    """Record the chosen organization after it has been validated."""
    request.session[SESSION_ORGANIZATION_KEY] = str(membership.organization_id)


def clear_active_organization(request: HttpRequest) -> None:
    request.session.pop(SESSION_ORGANIZATION_KEY, None)


class ActiveOrganizationMiddleware:
    """Attaches the resolved membership to the request.

    It deliberately does **not** store the organization in a thread-local or any
    process-global. Ambient tenant state is unsafe under Celery workers, where a task
    is not tied to a request; every background code path must therefore receive its
    organization explicitly as an argument (section 17, rule 5).

    Attaching None is normal: the view layer decides whether that means "choose an
    organization" or "deny".
    """

    def __init__(self, get_response: Callable[[HttpRequest], HttpResponse]) -> None:
        self.get_response = get_response

    def __call__(self, request: HttpRequest) -> HttpResponse:
        membership = resolve_active_membership(request)
        # Attached dynamically: Django's HttpRequest has no slot for these. Views read
        # them via getattr so a missing middleware surfaces as None, never as a crash
        # that could be mistaken for "no tenant".
        request.membership = membership  # type: ignore[attr-defined]
        request.organization = membership.organization if membership else None  # type: ignore[attr-defined]
        return self.get_response(request)
