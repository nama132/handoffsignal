"""Append-only audit events (master prompt section 22.6).

Section 14: the audit app owns "append-only audit events and safe diff metadata" and
must not own "raw secret/PII logging". Two properties are structural:

* **Exactly one actor.** A database check constraint requires precisely the actor
  column appropriate to `actor_kind`; detector and system actors carry a rule/job
  identity instead of a person.
* **No update or delete path.** `save()` refuses to update an existing row and
  `delete()` refuses outright. Tests exercise both.
"""

from __future__ import annotations

from typing import Any

from django.core.exceptions import ValidationError
from django.db import models
from django.db.models import Q

from apps.common.models import TenantScopedModel

#: Keys permitted in `metadata`. Anything else is rejected before save, so a raw row,
#: secret, or whole source record can never be written through this model.
ALLOWED_METADATA_KEYS: frozenset[str] = frozenset(
    {
        "from_state",
        "to_state",
        "reason_code",
        "case_number",
        "detector_code",
        "rule_version",
        "snapshot_version",
        "changed_fields",
        "object_version",
        "run_key",
        "attempt",
        "skip_reason",
        "count",
    }
)
MAX_METADATA_BYTES = 2_048


class AppendOnlyError(RuntimeError):
    """Raised when code attempts to update or delete an append-only row."""


class ActorKind(models.TextChoices):
    MEMBERSHIP = "membership", "Member"
    WORKER = "worker", "Worker"
    DETECTOR = "detector", "Detector"
    SYSTEM = "system", "System"


class AuditEvent(TenantScopedModel):
    action = models.CharField(max_length=64, db_index=True)
    object_type = models.CharField(max_length=64)
    object_id = models.UUIDField()
    request_id = models.CharField(max_length=64, blank=True)
    occurred_at = models.DateTimeField(auto_now_add=True, db_index=True)

    actor_kind = models.CharField(max_length=16, choices=ActorKind)
    actor_membership = models.ForeignKey(
        "organizations.Membership",
        on_delete=models.PROTECT,
        null=True,
        blank=True,
        related_name="audit_events",
    )
    # Route B has no Worker model; the column is kept so the exactly-one-actor rule
    # stays faithful to section 22.6, and it is simply never populated in this phase.
    actor_worker_id = models.UUIDField(null=True, blank=True)
    actor_rule = models.CharField(
        max_length=96, blank=True, help_text="Detector/job identity for non-human actors."
    )

    metadata = models.JSONField(default=dict, blank=True)

    class Meta:
        db_table = "audit_event"
        constraints = [
            models.CheckConstraint(
                condition=(
                    (
                        Q(actor_kind="membership")
                        & Q(actor_membership__isnull=False)
                        & Q(actor_worker_id__isnull=True)
                    )
                    | (
                        Q(actor_kind="worker")
                        & Q(actor_worker_id__isnull=False)
                        & Q(actor_membership__isnull=True)
                    )
                    | (
                        Q(actor_kind__in=["detector", "system"])
                        & Q(actor_membership__isnull=True)
                        & Q(actor_worker_id__isnull=True)
                        & ~Q(actor_rule="")
                    )
                ),
                name="ck_audit_exactly_one_actor",
            )
        ]
        ordering = ["-occurred_at"]
        indexes = [
            models.Index(
                fields=["organization", "object_type", "object_id"], name="idx_audit_object"
            ),
            models.Index(fields=["organization", "actor_membership"], name="idx_audit_actor"),
        ]

    def __str__(self) -> str:
        return f"{self.action} on {self.object_type}"

    def clean(self) -> None:
        super().clean()
        validate_metadata(self.metadata)

    def save(self, *args: Any, **kwargs: Any) -> None:
        if not self._state.adding:
            raise AppendOnlyError("AuditEvent rows are append-only and cannot be updated.")
        validate_metadata(self.metadata)
        super().save(*args, **kwargs)

    def delete(self, *args: Any, **kwargs: Any):
        raise AppendOnlyError("AuditEvent rows are append-only and cannot be deleted.")


def validate_metadata(metadata: object) -> None:
    """Reject anything outside the allowlist, or too large to be safe metadata."""
    import json

    if not isinstance(metadata, dict):
        raise ValidationError({"metadata": "Metadata must be an object."})
    unknown = set(metadata) - ALLOWED_METADATA_KEYS
    if unknown:
        raise ValidationError({"metadata": f"Keys not on the audit allowlist: {sorted(unknown)}"})
    if len(json.dumps(metadata, default=str)) > MAX_METADATA_BYTES:
        raise ValidationError({"metadata": "Metadata exceeds the size limit."})


def record(
    *,
    organization,
    action: str,
    object_type: str,
    object_id,
    actor_membership=None,
    actor_rule: str = "",
    request_id: str = "",
    metadata: dict[str, object] | None = None,
) -> AuditEvent:
    """Write one audit event. The actor kind is derived, never trusted from the caller."""
    if actor_membership is not None:
        kind = ActorKind.MEMBERSHIP
    elif actor_rule:
        kind = (
            ActorKind.DETECTOR
            if actor_rule.upper().startswith(("REVENUE_", "ATTENDANCE_", "QUALITY_"))
            else ActorKind.SYSTEM
        )
    else:
        raise ValidationError("An audit event needs a membership actor or a rule/job identity.")

    return AuditEvent.objects.create(
        organization=organization,
        action=action,
        object_type=object_type,
        object_id=object_id,
        request_id=request_id[:64],
        actor_kind=kind,
        actor_membership=actor_membership,
        actor_rule=actor_rule[:96],
        metadata=metadata or {},
    )
