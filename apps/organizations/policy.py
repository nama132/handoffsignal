"""Permission decisions.

One function answers every authorization question: :func:`check`. Views and services
call :func:`require` which raises, or :func:`allows` which returns a boolean for
template rendering. Both consult the same matrix, so a hidden button and a rejected
POST can never disagree (section 30.3: "The UI must not expose buttons the current role
cannot use. Server-side authorization remains mandatory even when the button is hidden").

Deny by default is structural: :func:`check` starts from denial and only an explicit
matrix entry can move it. There is no branch that returns "allowed" for an unknown
action, an unknown role, or a missing grant.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass

from django.core.exceptions import PermissionDenied

from apps.organizations.models import Membership
from apps.organizations.roles import ACTION_ROLES, SITE_SCOPED_ACTIONS, Role


class Denied(PermissionDenied):
    """Raised when an authenticated principal may not perform an action.

    Subclasses PermissionDenied so Django renders 403. Cross-tenant object lookups
    must instead return 404 and are handled by the selectors, not here (section 17,
    rule 8: return 404 where revealing existence is unnecessary; 403 where the object
    is known but the role cannot act on it).
    """


@dataclass(frozen=True)
class Decision:
    allowed: bool
    reason_code: str
    #: Roles that actually granted the action, for audit and debugging.
    granting_roles: frozenset[str] = frozenset()

    def __bool__(self) -> bool:
        return self.allowed


# Reason codes are stable identifiers, safe to log and to show in an audit trail.
REASON_OK = "permitted"
REASON_NO_MEMBERSHIP = "no_membership"
REASON_MEMBERSHIP_INACTIVE = "membership_inactive"
REASON_ORGANIZATION_NOT_ACTIVE = "organization_not_active"
REASON_UNKNOWN_ACTION = "unknown_action"
REASON_ROLE_NOT_PERMITTED = "role_not_permitted"
REASON_SITE_NOT_GRANTED = "site_not_granted"
REASON_SITE_REQUIRED = "site_required"


def check(
    membership: Membership | None,
    action: str,
    *,
    site_id: uuid.UUID | None = None,
) -> Decision:
    """Decide whether `membership` may perform `action`, optionally against a site.

    Every early return is a denial. The single ``allowed=True`` path at the end is
    reachable only after the organization, the membership, the action, the role union,
    and (where applicable) the site grant have all been checked.
    """
    if membership is None:
        return Decision(False, REASON_NO_MEMBERSHIP)

    # An inactive membership loses access immediately, on the next request
    # (section 33.3, line 2085).
    if not membership.is_active:
        return Decision(False, REASON_MEMBERSHIP_INACTIVE)

    # A suspended or archived organization permits nothing at all, including read.
    if not membership.organization.is_operational:
        return Decision(False, REASON_ORGANIZATION_NOT_ACTIVE)

    permitted_roles = ACTION_ROLES.get(action)
    if permitted_roles is None:
        # Unknown action: deny. A typo in a call site must never open a hole.
        return Decision(False, REASON_UNKNOWN_ACTION)

    held = membership.active_roles
    granting = frozenset(held & permitted_roles)
    if not granting:
        return Decision(False, REASON_ROLE_NOT_PERMITTED)

    if action in SITE_SCOPED_ACTIONS:
        # A tenant-wide role (anything other than supervisor) is not narrowed by site
        # grants. A principal qualifying ONLY as supervisor must hold a grant for the
        # exact site, and an empty grant set therefore reaches no site at all.
        tenant_wide = granting - {Role.SUPERVISOR}
        if not tenant_wide:
            if site_id is None:
                return Decision(False, REASON_SITE_REQUIRED)
            if not _has_site_grant(membership, site_id):
                return Decision(False, REASON_SITE_NOT_GRANTED)

    return Decision(True, REASON_OK, granting)


def _has_site_grant(membership: Membership, site_id: uuid.UUID) -> bool:
    """True only when an explicit grant exists for that exact site.

    There is no wildcard and no "all sites" flag to consult; absence is denial.
    """
    return membership.site_grants.filter(site_id=site_id).exists()


def allows(membership: Membership | None, action: str, *, site_id: uuid.UUID | None = None) -> bool:
    """Boolean form, for deciding whether to render a control."""
    return bool(check(membership, action, site_id=site_id))


def require(
    membership: Membership | None, action: str, *, site_id: uuid.UUID | None = None
) -> Decision:
    """Assert permission or raise :class:`Denied`.

    Every command service calls this before mutating anything.
    """
    decision = check(membership, action, site_id=site_id)
    if not decision.allowed:
        raise Denied(f"Action {action!r} denied: {decision.reason_code}")
    return decision


def granted_site_ids(membership: Membership) -> set[uuid.UUID]:
    """The exact sites a membership may reach through site grants.

    Used to narrow supervisor queries. Callers holding a tenant-wide role must not use
    this to widen access; it answers only "which sites were explicitly granted".
    """
    return set(membership.site_grants.values_list("site_id", flat=True))


def effective_site_scope(membership: Membership) -> set[uuid.UUID] | None:
    """The sites this membership may see, or None for tenant-wide visibility.

    Section 9.3 gives owner, operations manager, finance reviewer, and auditor
    tenant-wide visibility; a site supervisor sees only the sites explicitly granted to
    them. Section 22.2 line 841 makes the empty case decisive: "absence of a grant means
    no site access... Do not use a wildcard or interpret an empty grant set as
    tenant-wide access."

    So the return values are deliberately three-valued in effect:

    * ``None``          — tenant-wide; the caller applies no site filter.
    * a non-empty set   — exactly these sites.
    * an **empty set**  — no sites at all. Callers must pass this through verbatim and
      must never fall back to "unfiltered" when the set is empty.

    Returning None for a supervisor with no grants would silently widen access to the
    whole tenant, which is precisely the failure this function exists to prevent.
    """
    tenant_wide = membership.active_roles - {Role.SUPERVISOR}
    if tenant_wide:
        return None
    return granted_site_ids(membership)
