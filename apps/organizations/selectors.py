"""Read paths for tenant identity.

Section 17, rule 5: "Every selector requires an explicit organization argument."
Selectors here take either a user (for membership discovery, which is inherently
cross-organization) or an explicit organization, never an implicit ambient tenant.
"""

from __future__ import annotations

import uuid

from django.db.models import QuerySet

from apps.organizations.models import Membership, Organization, User


def active_memberships_for(user: User) -> QuerySet[Membership]:
    """Every usable membership for a user.

    Filters on both the membership and the organization: a membership of a suspended
    or archived organization is not selectable, so it can never become the active
    tenant.
    """
    return (
        Membership.objects.filter(
            user=user,
            is_active=True,
            organization__status=Organization.Status.ACTIVE,
        )
        .select_related("organization")
        .prefetch_related("role_grants")
        .order_by("organization__display_name")
    )


def membership_for(user: User, organization_id: uuid.UUID) -> Membership | None:
    """The user's active membership of one organization, or None.

    Returning None rather than raising lets the caller choose 404 (do not reveal that
    the organization exists) over 403.
    """
    return active_memberships_for(user).filter(organization_id=organization_id).first()
