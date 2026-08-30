# OpsRecovery V2

A human-controlled, read-only overlay that combines exported schedule, attendance,
quality, contract, and billable-work data into one operational exception inbox for
commercial-cleaning operators.

`OpsRecovery V2` is an internal working codename, not a cleared public brand.

> **Status: Phase 1 — foundation only.** There is no tenant model, no CSV import, no
> detector, and no exception inbox yet. The application boots, authenticates, and
> reports its health. Nothing else.

## What this is (and is not)

It is an **overlay**. Source systems stay authoritative; V2 writes only its own
cases, decisions, evidence, and exports. It never assigns a worker, edits payroll,
creates an invoice, or messages anyone. Every recommendation is deterministic and
explains itself, and every consequential action requires a human approval.

It is **not** a scheduler, time clock, inspection app, work-order suite, payroll
system, invoice generator, or AI dispatcher. Those markets are well served; see
`docs/adr/` for the reasoning.

### Route B is in effect

The build is following the capped synthetic-concept route: **one** journey —
*completed but not invoiced* — is being built to support customer interviews. The
late/no-show and failed-inspection journeys are deliberately **unbuilt**, with no
placeholder behaviour, until interview evidence justifies them.

This validates nothing about the market. It is an interview aid.

## Requirements

- macOS or Linux
- Docker with Compose (local PostgreSQL 18 and Redis 8)
- [uv](https://docs.astral.sh/uv/) 0.12.3 or newer

Python is managed by uv; no system Python is used or modified.

## Quick start

```bash
uv python install 3.13          # once — installs a managed CPython 3.13.15
uv sync --frozen --all-groups   # create .venv from the lock file
docker compose up -d db redis   # PostgreSQL on 5433, Redis on 6380
uv run python manage.py migrate
uv run python manage.py createsuperuser
uv run python manage.py runserver
```

Then open <http://127.0.0.1:8000/>. `make help` lists every convenience target.

Stop the local services with `docker compose down`. **Never** add `-v` to that
command in a routine script: it deletes the local V2 volume.

## Verify the installation

```bash
make qa        # django checks, migration drift, ruff, mypy, pytest
make coverage  # coverage with the 85% floor
make audit     # pip-audit against an exported lock
```

## Layout

```
config/          settings (base/local/test/production), URLs, WSGI/ASGI, Celery
  env.py         environment parsing and startup validation
  dbguard.py     refuses a non-test database during test runs
apps/common/     abstract base models, request IDs, health endpoints
apps/organizations/  custom User model (Organization arrives in Phase 2)
templates/       server-rendered, accessible HTML
tests/           unit, integration, and boundary tests
docs/            build status, threat model, ADRs, runbooks
```

## Safety boundaries

These are enforced by tests, not convention:

- **No external side effects.** `EXTERNAL_ACTIONS_ENABLED` must be false; no
  messaging, model-API, or source-system adapter exists to enable.
- **No arbitrary upload.** `EVIDENCE_MODE` is constrained to `metadata_only`.
- **PostgreSQL only.** SQLite is rejected at configuration parse time everywhere.
- **No outbound network in tests.** Non-loopback connections raise.
- **No test against a real database.** The name and host must match a test pattern.
- **V1 is untouched.** The separate Flask prototype is read-only reference material;
  no module of it is imported and no credential or database file is read.
- **No secret in the repository.** `.env.example` contains variable names only.

## Documentation

| Document | Purpose |
|---|---|
| `docs/phases/` | Per-phase narrative records: what was built, decided, rejected, and proven |
| `docs/BUILD_STATUS.md` | What exists, what was verified, what is approved |
| `docs/THREAT_MODEL.md` | Assets, trust boundaries, mitigated and deferred threats |
| `docs/adr/` | Architecture decision records |
| `docs/runbooks/local-development.md` | Day-to-day commands and troubleshooting |
| `CLAUDE_V2_COMMERCIAL_CLEANING_MASTER_PROMPT.md` | The governing specification |

The master prompt governs. Where this README and the master prompt disagree, the
master prompt wins and the README is wrong.
