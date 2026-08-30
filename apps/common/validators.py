"""Shared validation helpers.

Same-tenant enforcement (section 22.1): "Each tenant-owned foreign-key assignment must
be within the same organization. Enforce this in service validation and tests; use
database constraints where Django/PostgreSQL can express them safely."

Django cannot express a cross-table same-tenant predicate as a CheckConstraint, so this
is enforced at the model layer via clean() and asserted by tests. Models that can carry
it structurally do so through organization-scoped unique constraints.
"""

from __future__ import annotations

import zoneinfo
from typing import TYPE_CHECKING

from django.core.exceptions import ValidationError

if TYPE_CHECKING:  # pragma: no cover
    from django.db import models


def validate_iana_timezone(value: str) -> None:
    """Reject anything that is not a valid IANA timezone identifier (section 18)."""
    if not value:
        raise ValidationError("A timezone is required.")
    try:
        zoneinfo.ZoneInfo(value)
    except (zoneinfo.ZoneInfoNotFoundError, ValueError, KeyError) as exc:
        raise ValidationError(f"{value!r} is not a valid IANA timezone identifier.") from exc


def assert_same_organization(instance: models.Model, *field_names: str) -> None:
    """Raise ValidationError if any named foreign key belongs to another organization.

    Called from Model.clean(). Reading the related object is acceptable here because
    this runs on the write path, not in a list query.
    """
    own_org_id = getattr(instance, "organization_id", None)
    if own_org_id is None:
        return

    errors: dict[str, str] = {}
    for field_name in field_names:
        related = getattr(instance, field_name, None)
        if related is None:
            continue
        related_org_id = getattr(related, "organization_id", None)
        if related_org_id is not None and related_org_id != own_org_id:
            # The message names the field, never the other organization's identifiers.
            errors[field_name] = "This reference belongs to a different organization."
    if errors:
        raise ValidationError(errors)
