"""Reconciliation runs: the immutable manifest a detector will one day evaluate.

Section 22.3: "The transition to `ready` occurs atomically only when all required
batches are committed, their identities are resolved, blocking reconciliation issues are
absent, and required positive/negative-evidence coverage is present."

Phase 3 stopped at readiness. Phase 4 fills the seam: the readiness transaction now
inserts one durable DetectorDispatchIntent per enabled detector (section 22.3), and an
on-commit nudge attempts publication for latency while a periodic sweeper guarantees it.
Committing an individual file still never publishes anything directly.
"""

from __future__ import annotations

import hashlib
import json
import uuid

from django.db import transaction
from django.utils import timezone

from apps.ingestion.models import (
    DataSource,
    ImportBatch,
    ReconciliationIssue,
    ReconciliationRun,
    ReconciliationRunInput,
)
from apps.ingestion.services import identity

#: Domains Journey B needs before a run can be evaluated.
JOURNEY_B_REQUIRED_DOMAINS: tuple[str, ...] = (
    DataSource.Domain.CONTRACTS,
    DataSource.Domain.SERVICE_EVENTS,
    DataSource.Domain.INVOICE_STATUS,
)


def _manifest_hash(inputs: list[ReconciliationRunInput]) -> str:
    entries = [
        {
            "domain": item.domain,
            "batch": str(item.import_batch_id),
            "watermark": item.accepted_watermark,
            "coverage": sorted(str(c.id) for c in item.coverage_declarations.all()),
        }
        for item in inputs
    ]
    payload = json.dumps(
        sorted(entries, key=lambda entry: entry["domain"]),
        sort_keys=True,
        separators=(",", ":"),
    )
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


@transaction.atomic
def open_run(
    *, organization, run_key: str, as_of, domains=JOURNEY_B_REQUIRED_DOMAINS
) -> ReconciliationRun:
    """Create a run waiting on its required domains, or return the existing one."""
    run, created = ReconciliationRun.objects.get_or_create(
        organization=organization,
        run_key=run_key,
        defaults={"as_of": as_of, "status": ReconciliationRun.Status.WAITING_INPUTS},
    )
    if created:
        for domain in domains:
            ReconciliationRunInput.objects.create(
                organization=organization, reconciliation_run=run, domain=domain
            )
    return run


@transaction.atomic
def attach_batch(run: ReconciliationRun, batch: ImportBatch) -> ReconciliationRunInput | None:
    """Record a committed batch against the run input for its domain.

    Only a committed batch may be attached: an uncommitted file has no visible records,
    so treating it as a satisfied input would let a detector read nothing and call it
    absence.
    """
    if not batch.is_committed:
        return None

    locked = ReconciliationRun.objects.select_for_update().get(pk=run.pk)
    run_input = locked.inputs.filter(domain=batch.source.domain).first()
    if run_input is None:
        return None

    run_input.import_batch = batch
    run_input.accepted_watermark = batch.source_watermark
    run_input.save()
    run_input.coverage_declarations.set(batch.coverage_declarations.all())
    return run_input


def readiness_blockers(run: ReconciliationRun) -> list[str]:
    """Every reason this run may not become ready. Empty means it may."""
    blockers: list[str] = []

    for run_input in run.inputs.all():
        if not run_input.is_satisfied:
            blockers.append(f"waiting_for_{run_input.domain}")

    if identity.has_blocking_issues(run.organization_id):
        blockers.append("unresolved_identity")

    if ReconciliationIssue.objects.filter(
        organization_id=run.organization_id,
        status=ReconciliationIssue.Status.OPEN,
        is_blocking=True,
    ).exists():
        blockers.append("blocking_reconciliation_issue")

    for run_input in run.inputs.all():
        if run_input.is_satisfied and not run_input.coverage_declarations.exists():
            blockers.append(f"missing_coverage_{run_input.domain}")

    return blockers


@transaction.atomic
def evaluate_readiness(run: ReconciliationRun) -> ReconciliationRun:
    """Move a run to `ready` exactly once, atomically.

    Re-running this against an already-ready run is a no-op: the status guard plus the
    row lock make readiness idempotent, so replaying an import cannot produce a second
    readiness transition.
    """
    locked = ReconciliationRun.objects.select_for_update().get(pk=run.pk)

    if locked.status != ReconciliationRun.Status.WAITING_INPUTS:
        return locked  # already ready, or past readiness

    if readiness_blockers(locked):
        return locked

    locked.input_manifest_sha256 = _manifest_hash(list(locked.inputs.all()))
    locked.status = ReconciliationRun.Status.READY
    locked.became_ready_at = timezone.now()
    locked.save()

    # Phase 4: one durable DetectorDispatchIntent per enabled detector, inserted in
    # THIS transaction so readiness and the promise to evaluate commit or roll back
    # together. The on_commit nudge is latency only; the sweeper is correctness.
    from apps.exceptions.services import dispatch

    dispatch.create_intents(locked)
    dispatch.nudge(locked)
    return locked


def open_blocking_issue(
    *, organization, entity_type: str, field_group: str, explanation: str, subject
) -> ReconciliationIssue:
    """Record that two sources disagree, blocking dependent evaluation."""
    return ReconciliationIssue.objects.create(
        organization=organization,
        entity_type=entity_type,
        field_group=field_group,
        explanation=explanation,
        is_blocking=True,
        **{entity_type: subject},
    )


@transaction.atomic
def resolve_issue(
    *, issue: ReconciliationIssue, chosen_source: DataSource | None, resolved_by, note: str = ""
) -> ReconciliationIssue:
    """Resolve a conflict with explicit provenance (section 22.3)."""
    locked = ReconciliationIssue.objects.select_for_update().get(pk=issue.pk)
    locked.status = ReconciliationIssue.Status.RESOLVED
    locked.chosen_source = chosen_source
    locked.resolved_by = resolved_by
    locked.resolved_at = timezone.now()
    if note:
        locked.explanation = f"{locked.explanation}\nResolution: {note}"
    locked.save()
    return locked


def runs_for_organization(organization_id: uuid.UUID):
    return ReconciliationRun.objects.filter(organization_id=organization_id).prefetch_related(
        "inputs"
    )
