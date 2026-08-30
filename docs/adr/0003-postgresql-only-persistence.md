# ADR 0003 — PostgreSQL 18 only, no SQLite anywhere

Status: accepted
Date: 2026-08-27

## Context

V1 used SQLite for development and PostgreSQL when `DATABASE_URL` was present.
That split hides behaviour differences precisely where V2 depends on them:
partial unique indexes, check constraints, exclusion constraints for
non-overlapping effective date ranges, `SELECT ... FOR UPDATE` row locking,
`numeric` money arithmetic, timezone-aware timestamps, and (later) row-level
security.

V2's correctness argument rests on database-enforced invariants, not application
convention.

## Decision

PostgreSQL 18 in every environment: local Docker Compose, tests, and any future
deployment. SQLite is rejected at configuration parse time in all environments,
with an explicit error rather than a silent fallback.

Local and test databases run in Docker Compose on non-default ports (5433) so they
cannot collide with any other local PostgreSQL. `psycopg[binary]>=3.3` is the
driver.

## Alternatives considered

- **SQLite for local/test, PostgreSQL for deploy.** Rejected: the constraints V2
  relies on either do not exist or behave differently in SQLite; tests would prove
  less than they appear to.
- **PostgreSQL 17.** Viable and is the highest version Django 5.2 actually tests in
  CI. Rejected because 18 is GA and supported to November 2030, Django's stated
  support is "PostgreSQL 14 and higher" with no upper bound, and no PG18
  compatibility defects are recorded in Django's tracker.
- **`psycopg[c]`.** Rejected: `psycopg-c` 3.3.4 ships as an sdist only and does not
  build against Cython 3.3; `[binary]` provides prebuilt wheels with a bundled
  libpq for both macOS arm64 and Linux.

## Consequences

- Docker is required for local development. Accepted.
- Django 5.2's own CI matrix tests PostgreSQL 16 and 17, not 18. Mitigated by
  applying migrations to a fresh PostgreSQL 18 database on every phase and by
  running the whole suite against 18.
- `psycopg>=3.3` is required — above Django 5.2's floor of 3.1.8 — because
  PostgreSQL 18 libpq support first appeared in psycopg 3.2.8.
- The `postgres:18` image moved `PGDATA` to `/var/lib/postgresql/18/docker` and its
  `VOLUME` to `/var/lib/postgresql`. The Compose file mounts the new path; the
  pre-18 convention would silently fail to persist data.

## Security/privacy impact

Neutral-positive: one database engine means one set of security semantics to
reason about. Connection failures are logged without the exception message, which
can contain host and credential detail.

## Migration/rollback impact

Synthetic data only, so the local database can be dropped and recreated from
migrations. Never write a down-data transformation for synthetic data.

## Validation evidence

- `tests/test_settings_guards.py::TestDatabaseUrl` — SQLite, file, and MySQL URLs rejected.
- `tests/test_migrations.py::test_database_is_postgresql`.
- `tests/test_migrations.py::test_schema_applies_to_a_fresh_database`.
