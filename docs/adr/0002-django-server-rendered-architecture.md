# ADR 0002 — Django 5.2 LTS with server-rendered templates

Status: accepted
Date: 2026-08-27

## Context

One developer must ship a credible, auditable demo and maintain it. The product is
form- and table-heavy: an exception inbox, case detail, import preview, an
identity-resolution queue, and a finance ledger. There is no real-time UI
requirement — the data source is a daily CSV.

V1's Flask monolith demonstrated the cost of hand-rolling auth, sessions, CSRF,
schema management, and admin tooling.

## Decision

Use Django 5.2 LTS with server-rendered templates, accessible HTML, custom CSS,
and minimal vanilla JavaScript. Structure the code as `apps/` with application
services for commands and selectors for reads; views validate input and
authorization, call a service, and render.

Do not add Django REST Framework, React, Next.js, Tailwind, or a second API
service.

## Alternatives considered

- **Flask + SQLAlchemy.** Rejected: V1 proved the maintenance cost of assembling
  auth/migrations/admin by hand for a solo developer.
- **Django + DRF + React SPA.** Rejected: two build systems, two deployment
  artifacts, and a client-side authorization surface for zero demo benefit.
- **FastAPI + HTMX.** Rejected: no built-in auth/sessions/CSRF/migrations/admin;
  more assembly for the same server-rendered result.
- **Django 6.1 (current release).** Rejected for now: 5.2 is the LTS with security
  support to April 2028. Noted that 5.2 left mainstream support on 2025-12-03 and
  receives security and data-loss fixes only.

## Consequences

- Built-in auth, sessions, CSRF, forms, ORM, and migrations remove a large amount
  of security-sensitive custom code.
- Django 5.2 gets no non-security bug fixes; the upgrade target is 6.2 LTS
  (April 2027). Python 3.13 and PostgreSQL 18 already satisfy the 6.x floors, so
  the path stays open.
- Pin `django>=5.2.17,<5.3`: 5.2.17 fixed four CVEs, and 5.2.x ships monthly
  security releases that must be tracked.

## Security/privacy impact

Positive: Django's secure defaults (CSRF on state-changing routes, password
hashing, session handling, clickjacking protection) replace bespoke code. Django
5.2's `STORAGES` setting is not merged with defaults, so both `default` and
`staticfiles` keys are declared explicitly.

## Migration/rollback impact

None yet. Framework replacement after Phase 2 would be a rewrite; this is the
decision point.

## Validation evidence

- Resolved and installed: Django 5.2.17 on Python 3.13.15.
- `tests/test_project_boundaries.py::test_storages_defines_both_required_keys`.
- `tests/test_project_boundaries.py::test_whitenoise_follows_security_middleware`.
