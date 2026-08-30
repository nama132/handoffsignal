"""Cross-source identity resolution.

Section 12, principle 15: "Different source systems are not assumed to share customer,
site, worker, contract, work-order, or invoice IDs; unresolved mappings stay visible and
block dependent decisions."

Two rules shape everything here:

* A reference resolves only through a **confirmed** ExternalEntityReference. There is no
  name matching, no similarity, no "probably the same".
* An unresolved reference quarantines the row. It never becomes a guessed canonical id.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass

from django.db import transaction

from apps.ingestion.errors import ErrorCode, RowError
from apps.ingestion.models import (
    DataSource,
    ExternalEntityReference,
    IdentityResolutionIssue,
    ImportBatch,
)


@dataclass(frozen=True)
class Reference:
    """A pointer to a canonical entity as written in a source file."""

    entity_type: str
    source_system: str
    external_id: str
    column: str


class Unresolved(Exception):
    """Raised when a reference cannot be resolved to exactly one canonical entity."""

    def __init__(self, error: RowError) -> None:
        super().__init__(error.code)
        self.error = error


def resolve(organization_id: uuid.UUID, reference: Reference) -> uuid.UUID:
    """Return the canonical id for a reference, or raise :class:`Unresolved`.

    Never falls back to a heuristic. The three failure modes are distinguished so the
    identity queue can explain what a human needs to decide.
    """
    if not reference.source_system:
        raise Unresolved(
            RowError(ErrorCode.MISSING_REFERENCE_SOURCE_SYSTEM, column=reference.column)
        )

    source = DataSource.objects.filter(
        organization_id=organization_id, system_key=reference.source_system
    ).first()
    if source is None:
        raise Unresolved(RowError(ErrorCode.SOURCE_NAMESPACE_UNKNOWN, column=reference.column))

    matches = list(
        ExternalEntityReference.objects.filter(
            organization_id=organization_id,
            source=source,
            entity_type=reference.entity_type,
            external_id=reference.external_id,
            mapping_status=ExternalEntityReference.MappingStatus.CONFIRMED,
        )[:2]
    )
    if not matches:
        raise Unresolved(RowError(ErrorCode.UNRESOLVED_IDENTITY, column=reference.column))
    if len(matches) > 1:  # pragma: no cover - the partial unique index prevents this
        raise Unresolved(RowError(ErrorCode.AMBIGUOUS_IDENTITY, column=reference.column))

    target_id = getattr(matches[0], f"{reference.entity_type}_id", None)
    if target_id is None:
        raise Unresolved(RowError(ErrorCode.UNRESOLVED_IDENTITY, column=reference.column))
    return target_id


def confirm(
    *,
    organization,
    source: DataSource,
    entity_type: str,
    external_id: str,
    target,
    match_method: str,
    provenance: str,
    confirmed_by=None,
) -> ExternalEntityReference:
    """Create or update a confirmed mapping.

    Re-confirming the identical mapping is a no-op, which is what makes an exact file
    replay produce no new identity work.
    """
    from django.utils import timezone

    existing = (
        ExternalEntityReference.objects.filter(
            organization=organization,
            source=source,
            entity_type=entity_type,
            external_id=external_id,
        )
        .exclude(mapping_status=ExternalEntityReference.MappingStatus.SUPERSEDED)
        .first()
    )

    if existing is not None:
        current_target = getattr(existing, f"{entity_type}_id", None)
        if (
            existing.mapping_status == ExternalEntityReference.MappingStatus.CONFIRMED
            and current_target == target.id
        ):
            return existing  # identical: nothing to do
        if (
            existing.mapping_status == ExternalEntityReference.MappingStatus.CONFIRMED
            and current_target != target.id
        ):
            # A different canonical target for the same source identity is a conflict a
            # human must adjudicate; it is never silently remapped.
            raise Unresolved(
                RowError(ErrorCode.CONFLICTING_CROSSWALK, column="canonical_external_id")
            )
        existing.mapping_status = ExternalEntityReference.MappingStatus.CONFIRMED
        existing.match_method = match_method
        existing.mapping_provenance = provenance
        existing.confirmed_by = confirmed_by
        existing.confirmed_at = timezone.now()
        setattr(existing, entity_type, target)
        existing.save()
        return existing

    return ExternalEntityReference.objects.create(
        organization=organization,
        source=source,
        entity_type=entity_type,
        external_id=external_id,
        mapping_status=ExternalEntityReference.MappingStatus.CONFIRMED,
        match_method=match_method,
        mapping_provenance=provenance,
        confirmed_by=confirmed_by,
        confirmed_at=timezone.now(),
        **{entity_type: target},
    )


def record_issue(
    *,
    batch: ImportBatch,
    entity_type: str,
    source_system: str,
    external_id: str,
    reason_code: str,
    explanation: str = "",
) -> IdentityResolutionIssue | None:
    """Open (or reuse) an unresolved-identity issue so a human can see it.

    Returns None when the source namespace itself is unknown: there is no DataSource to
    attach the issue to, and that condition is reported as a row error instead.
    """
    source = DataSource.objects.filter(
        organization=batch.organization, system_key=source_system
    ).first()
    if source is None:
        return None

    issue, _ = IdentityResolutionIssue.objects.get_or_create(
        organization=batch.organization,
        supplied_source=source,
        entity_type=entity_type,
        supplied_external_id=external_id,
        status=IdentityResolutionIssue.Status.UNRESOLVED,
        defaults={
            "reason_code": reason_code,
            "explanation": explanation,
            "import_batch": batch,
        },
    )
    return issue


@transaction.atomic
def resolve_issue_manually(
    *,
    issue: IdentityResolutionIssue,
    target,
    resolved_by,
    note: str = "",
) -> ExternalEntityReference:
    """Owner-only manual confirmation (section 9.3: crossing the identity boundary).

    Authorization is enforced by the caller through the policy service; this function
    performs the write and records provenance.
    """
    from django.utils import timezone

    reference = confirm(
        organization=issue.organization,
        source=issue.supplied_source,
        entity_type=issue.entity_type,
        external_id=issue.supplied_external_id,
        target=target,
        match_method=ExternalEntityReference.MatchMethod.MANUAL,
        provenance=f"manual:{resolved_by.email}",
        confirmed_by=resolved_by,
    )
    issue.status = IdentityResolutionIssue.Status.RESOLVED
    issue.resolved_reference = reference
    issue.resolved_by = resolved_by
    issue.resolved_at = timezone.now()
    issue.resolution_note = note
    issue.save()

    # Re-resolve the rows this identity was blocking, so the batch becomes a complete
    # observation of its own file again (and its coverage can prove absence).
    batch = issue.import_batch
    if batch is not None:
        from apps.ingestion.services.imports import reprocess_quarantined

        reprocess_quarantined(batch, resolved_by)
    return reference


def has_blocking_issues(organization_id: uuid.UUID) -> bool:
    """Whether any unresolved identity blocks dependent detection (section 22.3)."""
    return IdentityResolutionIssue.objects.filter(
        organization_id=organization_id, status=IdentityResolutionIssue.Status.UNRESOLVED
    ).exists()
