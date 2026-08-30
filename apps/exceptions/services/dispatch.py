"""Durable dispatch: intents, the on-commit nudge, the sweeper, and schedule leases.

Section 22.3: correctness "comes from a recoverable dispatcher/sweeper that claims
unsent/stale intents and publishes/reclaims idempotently after crashes." The on_commit
nudge exists only for latency. If the process dies between the readiness commit and the
broker publish, the sweeper finds the intent still `pending` and publishes it; if the
broker delivers twice, the unique DetectorRun key makes the second delivery a no-op.
"""

from __future__ import annotations

import datetime as dt
import uuid
import zoneinfo

from django.db import IntegrityError, transaction
from django.utils import timezone

from apps.exceptions.detectors import revenue_unbilled
from apps.exceptions.models import DetectorDispatchIntent, DetectorScheduleLease
from apps.ingestion.models import ReconciliationRun

PUBLISH_LEASE_SECONDS = 120
SCHEDULE_LEASE_SECONDS = 600

#: Route B has one detector.
ENABLED_DETECTORS: tuple[tuple[str, int], ...] = (
    (revenue_unbilled.RULE_CODE, revenue_unbilled.RULE_VERSION),
)


def _owner() -> str:
    import os
    import socket

    return f"{socket.gethostname()}:{os.getpid()}:{uuid.uuid4().hex[:8]}"


def create_intents(run: ReconciliationRun) -> list[DetectorDispatchIntent]:
    """Insert one intent per enabled detector. Called INSIDE the readiness transaction.

    Idempotent through the unique evaluation key: a repeated readiness transaction for
    the same manifest finds its intents already present.
    """
    created: list[DetectorDispatchIntent] = []
    for code, version in ENABLED_DETECTORS:
        intent, _ = DetectorDispatchIntent.objects.get_or_create(
            organization=run.organization,
            reconciliation_run=run,
            detector_code=code,
            rule_version=version,
            input_manifest_sha256=run.input_manifest_sha256,
        )
        created.append(intent)
    return created


def _publish(intent: DetectorDispatchIntent) -> str:
    """Hand the intent to the broker. Returns the broker task id."""
    from apps.exceptions.tasks import run_detector

    async_result = run_detector.delay(str(intent.id))
    return str(async_result.id)


def publish_intent(intent_id: uuid.UUID) -> DetectorDispatchIntent | None:
    """Claim and publish one intent. Safe to call any number of times.

    Deliberately NOT one transaction. The claim (an UPDATE guarded by "pending OR
    expired publishing") commits on its own, so a crash or broker failure during the
    publish leaves a durable `publishing` row with a lease and an incremented attempt
    count. The sweeper reclaims it only after the lease expires - no hot loop, and no
    lost attempt history. Wrapping both in one transaction would roll the claim back
    on failure and erase exactly the evidence the sweeper needs.
    """
    now = timezone.now()
    owner = _owner()
    claimed = (
        DetectorDispatchIntent.objects.filter(id=intent_id)
        .filter(
            models_Q(status=DetectorDispatchIntent.Status.PENDING)
            | models_Q(status=DetectorDispatchIntent.Status.PUBLISHING, leased_until__lt=now)
        )
        .update(
            status=DetectorDispatchIntent.Status.PUBLISHING,
            claim_owner_id=owner,
            leased_until=now + dt.timedelta(seconds=PUBLISH_LEASE_SECONDS),
            attempts=models_F("attempts") + 1,
        )
    )
    if claimed != 1:
        return None

    intent = DetectorDispatchIntent.objects.get(id=intent_id)
    try:
        task_id = _publish(intent)
    except Exception as exc:  # noqa: BLE001
        DetectorDispatchIntent.objects.filter(id=intent_id, claim_owner_id=owner).update(
            error_code=type(exc).__name__[:64]
        )
        raise

    # Only the claim owner may mark it published; a reclaimer after expiry would have a
    # different owner id and this update would touch zero rows.
    DetectorDispatchIntent.objects.filter(id=intent_id, claim_owner_id=owner).update(
        status=DetectorDispatchIntent.Status.PUBLISHED,
        broker_task_id=task_id[:128],
        published_at=timezone.now(),
        error_code="",
    )
    intent.refresh_from_db()
    return intent


def models_Q(**kwargs):
    from django.db.models import Q

    return Q(**kwargs)


def models_F(name: str):
    from django.db.models import F

    return F(name)


def nudge(run: ReconciliationRun) -> None:
    """Latency-only: after the readiness transaction commits, try to publish now.

    Failure here is harmless; the sweeper is the correctness path.
    """

    def _try() -> None:
        for intent in run.dispatch_intents.filter(status=DetectorDispatchIntent.Status.PENDING):
            try:
                publish_intent(intent.id)
            except Exception:  # noqa: BLE001, S110 - the sweeper will retry
                pass

    transaction.on_commit(_try)


def sweep(*, limit: int = 100) -> int:
    """Publish every pending or stale-publishing intent. Returns the count published."""
    now = timezone.now()
    candidates = DetectorDispatchIntent.objects.filter(
        models_Q(status=DetectorDispatchIntent.Status.PENDING)
        | models_Q(status=DetectorDispatchIntent.Status.PUBLISHING, leased_until__lt=now)
    ).order_by("created_at")[:limit]
    published = 0
    for intent in candidates:
        try:
            if publish_intent(intent.id) is not None:
                published += 1
        except Exception:  # noqa: BLE001, S112 - continue sweeping; the row keeps its lease
            continue
    return published


# ------------------------------------------------------------------ schedule leases


def run_window(
    *, organization, cadence_minutes: int, at: dt.datetime
) -> tuple[dt.datetime, dt.datetime]:
    """Derive a deterministic cadence window in organization time (section 22.5)."""
    tz = zoneinfo.ZoneInfo(organization.default_timezone)
    local = at.astimezone(tz)
    day_start = local.replace(hour=0, minute=0, second=0, microsecond=0)
    minutes_into_day = int((local - day_start).total_seconds() // 60)
    slot = minutes_into_day // cadence_minutes
    start = day_start + dt.timedelta(minutes=slot * cadence_minutes)
    end = start + dt.timedelta(minutes=cadence_minutes)
    return start.astimezone(dt.UTC), end.astimezone(dt.UTC)


@transaction.atomic
def claim_schedule_lease(
    *, organization, detector_code: str, rule_version: int, window: tuple[dt.datetime, dt.datetime]
) -> DetectorScheduleLease | None:
    """Claim the cadence window, or None if another scheduler already holds it.

    This prevents duplicate cadence scheduling only; it never substitutes for
    DetectorRun evaluation uniqueness (section 22.5).
    """
    now = timezone.now()
    owner = _owner()
    start, end = window
    try:
        with transaction.atomic():
            return DetectorScheduleLease.objects.create(
                organization=organization,
                detector_code=detector_code,
                rule_version=rule_version,
                run_window_start=start,
                run_window_end=end,
                lease_owner_id=owner,
                leased_until=now + dt.timedelta(seconds=SCHEDULE_LEASE_SECONDS),
                heartbeat_at=now,
            )
    except IntegrityError:
        pass
    updated = DetectorScheduleLease.objects.filter(
        organization=organization,
        detector_code=detector_code,
        rule_version=rule_version,
        run_window_start=start,
        run_window_end=end,
        leased_until__lt=now,
    ).update(
        lease_owner_id=owner,
        leased_until=now + dt.timedelta(seconds=SCHEDULE_LEASE_SECONDS),
        heartbeat_at=now,
    )
    if updated == 1:
        return DetectorScheduleLease.objects.get(
            organization=organization,
            detector_code=detector_code,
            rule_version=rule_version,
            run_window_start=start,
            run_window_end=end,
        )
    return None
