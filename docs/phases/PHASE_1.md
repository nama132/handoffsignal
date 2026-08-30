# Phase 1 — Isolated V2 foundation

**Approval:** `Approve synthetic-concept Phase 1`  **Status:** complete, pending review

## What the owner can now do

Run the foundation end to end from a clean checkout with documented commands. It boots
on Python 3.13.15 / Django 5.2.17 against PostgreSQL 18.6 and Redis 8.10.1, authenticates
a user, reports dependency health honestly, and **cannot** reach V1, the network, SQLite,
or any live service. The landing page states plainly that no business workflow exists.

```bash
uv sync --frozen --all-groups && docker compose up -d db redis
uv run python manage.py migrate && uv run python manage.py runserver
```

## What was built

63 files: 28 source files, 12 test files, 9 documents.

| Area | Contents |
|---|---|
| Configuration | `config/env.py` (parsing and startup validation), `dbguard.py`, `logging_utils.py`, split settings base/local/test/production, URLs, WSGI/ASGI, Celery app |
| Applications | `apps/common` (UUID/timestamp/version bases, request-ID middleware, health), `apps/organizations` (custom `User` + email auth backend) |
| Migration | `organizations/0001_initial` — the custom user model only |
| Infrastructure | `compose.yaml`, `Dockerfile`, `Makefile`, `.env.example`, ignore files |

## Decisions worth knowing

Three implementation choices are recorded in full in `docs/adr/0006`:

1. **Standard-library URL parsing rather than `dj-database-url`.** The configuration
   contract requires custom SQLite-rejection logic and value-free error messages
   regardless, so a library would add a dependency and still need the custom layer.
2. **`django-stubs` 6.1 with mypy 2.3** (Django 5.2 in "partial support") over
   `django-stubs` 5.2.9, which is fully accurate for 5.2 but caps mypy below 1.20 and is
   a dead end.
3. **Celery's built-in scheduler** rather than `django-celery-beat`. The database
   schedule lease is the actual correctness mechanism; the package would add an app,
   migrations and a `Django<6.1` pin without replacing it.

Dependency pins that matter, and why:

| Pin | Reason |
|---|---|
| `django>=5.2.17,<5.3` | 5.2.17 fixed four CVEs; the series is security-only |
| `psycopg[binary]>=3.3,<3.4` | PostgreSQL 18 libpq support began in 3.2.8; `[c]` is sdist-only and does not build against Cython 3.3 |
| `celery[redis]>=5.6.3,<5.7` | 5.6.3 fixed Redis-failover reconnection |
| **`redis-py` — not pinned at all** | `kombu` caps it below 6.5; a direct pin makes resolution unsolvable |

Local services run on **non-default ports** (PostgreSQL 5433, Redis 6380) so they cannot
collide with anything else, and the PostgreSQL volume is mounted at
`/var/lib/postgresql` — the PG18 path. The pre-18 convention silently loses data.

## Safety properties, each enforced by a test

| Property | Mechanism |
|---|---|
| No external side effects | No adapter exists; `EXTERNAL_ACTIONS_ENABLED` must be false at startup and is hard-coded `False` in settings |
| No arbitrary upload | `EVIDENCE_MODE` constrained to `metadata_only` |
| PostgreSQL only | SQLite rejected at configuration parse time in every environment |
| No outbound network in tests | Non-loopback connections raise |
| No test against a real database | Name and host must match an allowlisted test pattern |
| V1 untouched | No module imported; a regex detector plus a self-test proving the detector is not vacuous |
| No secret in the repository | `.env.example` holds names only, asserted by test |

Production settings refuse debug mode, wildcard hosts, SQLite, and known development
secrets — proven by 17 subprocess tests that load the real settings module.

## Evidence

| Command | Result |
|---|---|
| `manage.py migrate` (fresh PostgreSQL 18.6) | 16 migrations applied |
| `ruff format --check` / `ruff check` / `mypy` | clean |
| `pytest` | **165 passed** |
| `coverage --fail-under=85` | **97%** |
| `pip-audit` | no known vulnerabilities |

Health endpoints were verified live: liveness held HTTP 200 with Redis stopped *and*
with both dependencies stopped, proving it performs no dependency I/O; readiness returned
503 with per-dependency booleans and recovered to 200. Payloads carry booleans only — no
host, port, driver, or error text.

## Five defects found and fixed during the phase

Three were real bugs, not test noise:

1. **`required=True` overrode a supplied default** in the environment helpers, so startup
   failed on `EVIDENCE_MODE` despite a valid default. Caught by the application refusing
   to boot.
2. **Login was not actually case-insensitive.** The model lowercases email on save, but
   Django's `ModelBackend` matches the username field exactly, so correct credentials
   typed with different capitalisation would fail. Fixed with a normalizing backend.
3. **The network blocker's own tests were passing vacuously.** `NetworkAccessBlocked`
   lived in `conftest.py`; pytest imports that file under a synthetic module name, so
   `from tests.conftest import ...` built a *second* class and `pytest.raises` could
   never match. Moved to `tests/network_guard.py`.
4. The V1-import detector matched substrings and flagged `from config.celery import app`.
   Replaced with a real regex **plus a self-test proving the detector is not vacuous**.
5. pytest 9's native TOML table requires `addopts` as a list, not a string.

## Known limitations carried forward

- No tenancy or RBAC — Phase 2.
- **No login rate limiting and no MFA** — both required before a pilot.
- `security.W021` (HSTS preload off) is deliberate: `SECURE_HSTS_SECONDS` defaults to 0
  so a broken certificate cannot be pinned into browsers before HTTPS is verified.
- Django 5.2 is security-only until April 2028; the upgrade target is 6.2 LTS.
- 97% coverage measures the foundation only.
