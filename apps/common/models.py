"""Abstract base models shared by every V2 app.

Section 22.1 defines the common field conventions. These bases carry no table of
their own; tenant ownership arrives in Phase 2 with the Organization model.
"""

from __future__ import annotations

import uuid

from django.db import models


class UUIDPrimaryKeyModel(models.Model):
    """UUID primary keys for V2 domain entities (section 17, rule 1)."""

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)

    class Meta:
        abstract = True


class TimestampedModel(models.Model):
    """Timezone-aware creation and modification timestamps (section 22.1)."""

    created_at = models.DateTimeField(auto_now_add=True, db_index=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        abstract = True


class VersionedModel(models.Model):
    """Optimistic-concurrency counter for records subject to concurrent human action.

    Section 19 requires a version or current-state predicate on human transitions so a
    stale form cannot act twice. Consumers arrive in Phase 4.
    """

    version = models.PositiveIntegerField(default=1)

    class Meta:
        abstract = True


class TenantScopedModel(UUIDPrimaryKeyModel, TimestampedModel):
    """Base for every tenant-owned model.

    Section 17 rule 2: "Every tenant-owned model has a non-null `organization_id`."
    Section 22.1: tenant-owned models carry a UUID id, a non-null organization foreign
    key, and timezone-aware created/updated timestamps.

    `on_delete=PROTECT` is deliberate: an organization must never be deletable while it
    still owns operational rows, because that would silently destroy audit history.
    """

    organization = models.ForeignKey(
        "organizations.Organization",
        on_delete=models.PROTECT,
        related_name="%(app_label)s_%(class)s_set",
        db_index=True,
    )

    class Meta:
        abstract = True


class Provenance(models.TextChoices):
    """How a displayed fact came to exist (section 22.1).

    "Every material displayed fact must expose provenance as `source_imported`,
    `locally_asserted`, or `derived`, with its source version or actor/rule."
    """

    SOURCE_IMPORTED = "source_imported", "Imported from a source system"
    LOCALLY_ASSERTED = "locally_asserted", "Asserted locally by a named user"
    DERIVED = "derived", "Derived by a versioned rule"


# Money: section 18 requires Decimal and PostgreSQL numeric, never binary floating point.
# 14 total digits with 4 decimal places keeps rate arithmetic exact before display
# quantization to cents. Unknown is always NULL, never zero.
MONEY_MAX_DIGITS = 14
MONEY_DECIMAL_PLACES = 4
RATE_MAX_DIGITS = 12
RATE_DECIMAL_PLACES = 4
