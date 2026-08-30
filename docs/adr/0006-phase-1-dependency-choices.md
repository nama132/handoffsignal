# ADR 0006 — Phase 1 dependency choices: URL parsing, type stubs, scheduler

Status: accepted
Date: 2026-08-27

## Context

Three Phase 1 decisions are not settled by the master prompt and would otherwise be
made silently at implementation time. Section 47 requires that a package be added
only when the standard library or Django does not solve the need clearly.

## Decision

**1. Parse `DATABASE_URL` with the standard library, not `dj-database-url`.**
Section 20.1 requires custom validation regardless — SQLite must be rejected with an
explicit error, and failures must name variables without printing values. That logic
is not provided by any library, so adopting one would add a dependency and still
require the custom layer. `config/env.py` uses `urllib.parse` (about 40 lines) and
handles percent-encoded credentials, invalid ports, and query-string options.

**2. Use `django-stubs[compatible-mypy]` 6.1 with mypy 2.3, accepting "partial"
Django 5.2 support.** The alternative, `django-stubs` 5.2.9, is the only line with
*full* Django 5.2 support but caps mypy below 1.20 and is a dead end. The
`compatible-mypy` extra pins the mypy range so a future release cannot silently
break the plugin.

**3. Use Celery's built-in scheduler, not `django-celery-beat`.** The master prompt
requires a database `DetectorScheduleLease` for duplicate-run prevention (section
19), which is the actual correctness mechanism. `django-celery-beat` would add an
app, migrations, and a `Django<6.1` pin without replacing that lease. Revisit only
if runtime-editable schedules become a requirement.

## Alternatives considered

- `dj-database-url ~=3.1`: well-tested and Jazzband-maintained, but redundant given
  the mandatory custom validation layer.
- `django-environ`: broader scope than needed; slower release cadence.
- `django-stubs` 5.2.9 + mypy <1.20: fully accurate for Django 5.2 but blocks mypy
  upgrades permanently.
- `django-celery-beat`: warranted only if schedules must be editable at runtime.

## Consequences

- URL parsing is our code, so it is our bug surface — mitigated by 10 unit tests
  including percent-encoding, invalid port, and value-disclosure cases.
- Some Django 5.2-specific type inference may be imperfect under django-stubs 6.1.
  Type checking is a guardrail here, not a correctness proof.
- Detector schedules are defined in code and require a deploy to change. Acceptable
  for a demo; revisit before a pilot.

## Security/privacy impact

Positive on (1): the custom parser guarantees SQLite rejection and value-free error
messages, both of which are explicit section 20.1 requirements. Neutral on (2) and (3).

## Migration/rollback impact

All three are reversible. Adopting `dj-database-url` later is a contained change to
`config/env.py`; adopting `django-celery-beat` later is an added app plus migrations.

## Validation evidence

- `tests/test_settings_guards.py::TestDatabaseUrl` — 8 cases including SQLite
  rejection and `test_error_message_never_contains_the_value`.
- `tests/test_production_settings.py` — 17 rejection cases exercised in subprocesses.
- `tests/test_project_boundaries.py::test_celery_registers_no_business_task`.
