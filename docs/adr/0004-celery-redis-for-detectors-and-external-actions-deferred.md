# ADR 0004 — Celery 5.6 + Redis for durable work; external actions deferred

Status: accepted
Date: 2026-08-27

## Context

Detectors must run on a schedule, retry safely, survive a crash, and never run
twice for the same evaluation. V1 used in-process APScheduler and daemon threads,
which cannot survive a restart, cannot be leased across replicas, and hold
process-local state that breaks with more than one worker.

Separately, the demo must be incapable of an external side effect: no SMS, email,
webhook, model API, or source-system write.

## Decision

Use Celery 5.6.3+ with Redis as broker for background work. Wire the Celery
application in Phase 1 but register **no business task** — detector and import
tasks arrive in Phases 3 and 4.

Defer every external-action mechanism (provider adapters, outbox, webhook
envelopes, consent records, delivery attempts) to Phase 11. Do not create
placeholder demo versions of them.

Configure for at-least-once delivery explicitly: `task_acks_late=True`,
`task_reject_on_worker_lost=True`, `worker_prefetch_multiplier=1`, and a stated
`visibility_timeout` of 3600s.

## Alternatives considered

- **Django-Q / Huey / RQ.** Rejected: less mature scheduling, leasing, and retry
  semantics for the reliability guarantees this product claims.
- **APScheduler in-process (V1's approach).** Rejected outright: named as an
  inherited risk; cannot survive restarts or coordinate across replicas.
- **`django-celery-beat` DatabaseScheduler.** Deferred. The built-in scheduler plus
  the `DetectorScheduleLease` database lease (Phase 4) covers the requirement
  without an extra app and migrations. Also noted: `django-celery-beat` 2.9.0 pins
  `Django<6.1`, which would constrain a later upgrade.
- **PostgreSQL-backed queue (no Redis).** Rejected: Redis is already required for
  caching/locking and Railway provides it as a first-class service.

## Consequences

- Tasks may be redelivered, so **every** task must be idempotent. This is a
  standing requirement, not a per-task consideration.
- `redis-py` is deliberately NOT a direct dependency. `kombu` 5.6.2 constrains it
  to `<6.5`, so `celery[redis]` resolves `redis-py` 6.4.0. Adding an explicit
  `redis>=7` or `>=8` pin makes the resolution unsolvable. This is recorded so a
  future contributor does not "helpfully" upgrade it.
- Redis must run with `maxmemory-policy noeviction`; evicted Kombu binding keys
  cause `InconsistencyError`. The Compose file sets this explicitly.
- Retry backoffs must stay well below the visibility timeout or tasks are
  redelivered in a loop.
- Exactly one Celery Beat scheduler may ever run.

## Security/privacy impact

Strongly positive. `EXTERNAL_ACTIONS_ENABLED` is validated to be false at startup
in every environment and the settings module hard-codes the resolved value to
`False`; there is no adapter for it to enable. `EVIDENCE_MODE` is constrained to
`metadata_only`. Missing configuration fails closed.

## Migration/rollback impact

No queue state exists in Phase 1, so there is nothing to drain. Rollback is
removing the Celery configuration.

## Validation evidence

- `tests/test_project_boundaries.py::test_celery_registers_no_business_task`.
- `tests/test_project_boundaries.py::test_celery_is_configured_for_redelivery_safety`.
- `tests/test_project_boundaries.py::test_external_actions_are_disabled`.
- `tests/test_settings_guards.py::TestPhaseBoundaries`.
- Resolved: celery 5.6.3, kombu 5.6.2, redis-py 6.4.0.
