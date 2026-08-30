"""Celery tasks. Every task is idempotent: delivery can occur more than once.

Retry backoffs stay well under the Redis visibility timeout (3600s in settings), so a
retrying task cannot be redelivered mid-retry and evaluated twice in a loop.
"""

from __future__ import annotations

import logging
import uuid

from celery import shared_task
from django.db import OperationalError

from apps.exceptions.models import DetectorDispatchIntent
from apps.exceptions.services import dispatch, runs

logger = logging.getLogger(__name__)

TRANSIENT = (OperationalError, ConnectionError, TimeoutError)


@shared_task(
    bind=True,
    autoretry_for=TRANSIENT,
    retry_backoff=5,
    retry_backoff_max=300,
    retry_jitter=True,
    max_retries=5,
    acks_late=True,
)
def run_detector(self, intent_id: str) -> str:
    """Evaluate the detector named by a dispatch intent.

    Idempotent through the unique DetectorRun evaluation key: a duplicate delivery
    finds the finished run and returns without re-evaluating. Transient errors retry
    with bounded backoff; anything else is terminal and recorded on the run.
    """
    intent = (
        DetectorDispatchIntent.objects.select_related("reconciliation_run")
        .filter(id=uuid.UUID(intent_id))
        .first()
    )
    if intent is None:
        logger.warning("run_detector: intent not found", extra={"intent_id": intent_id})
        return "missing_intent"

    detector_run = runs.evaluate_and_persist(
        run=intent.reconciliation_run,
        detector_code=intent.detector_code,
        as_of=intent.reconciliation_run.as_of,
    )
    if detector_run is None:
        return "lease_held_elsewhere"
    return detector_run.status


@shared_task
def sweep_dispatch_intents() -> int:
    """Periodic recovery: publish anything pending or stale. Correctness lives here."""
    return dispatch.sweep()


@shared_task
def schedule_detectors() -> int:
    """Periodic cadence: open a run per organization and dispatch it once per window.

    Route B: the cadence opens a reconciliation run keyed by window and lets readiness
    decide whether inputs exist. The schedule lease prevents two beats from doing this
    for the same window; the DetectorRun key prevents double evaluation regardless.
    """
    from django.utils import timezone

    from apps.ingestion.services import reconciliation
    from apps.organizations.models import Organization

    dispatched = 0
    now = timezone.now()
    for organization in Organization.objects.filter(status=Organization.Status.ACTIVE):
        for code, version in dispatch.ENABLED_DETECTORS:
            window = dispatch.run_window(organization=organization, cadence_minutes=1440, at=now)
            lease = dispatch.claim_schedule_lease(
                organization=organization, detector_code=code, rule_version=version, window=window
            )
            if lease is None:
                continue
            run = reconciliation.open_run(
                organization=organization,
                run_key=f"cadence:{code}:{window[0].isoformat()}",
                as_of=now,
            )
            lease.reconciliation_run = run
            lease.save(update_fields=["reconciliation_run", "updated_at"])
            reconciliation.evaluate_readiness(run)
            dispatched += 1
    return dispatched
