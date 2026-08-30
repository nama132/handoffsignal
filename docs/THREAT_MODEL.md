# Threat model — OpsRecovery V2

Status: **outline (Phase 1)**. Expanded at each phase; a full review is required
before any deployment and before every live integration.

Scope of this revision: the Phase 1 foundation only — configuration, authentication,
health endpoints, and the custom user model. There is no tenant model, no import
path, no detector, and no export yet, so the corresponding threats are listed as
*deferred* rather than *mitigated*.

## Assets

| Asset | Sensitivity in the demo | Later |
|---|---|---|
| Login credentials | Real (owner's own accounts) | Real |
| Session cookies | Real | Real |
| Synthetic operational data | None — fictional | Becomes real partner data at Phase 10 |
| Financial candidate/invoice values | Synthetic | Real revenue data at Phase 10 |
| Source exports (CSV) | Synthetic | Real customer data at Phase 10 |
| Audit trail | Integrity-critical from Phase 4 | Evidentiary |
| V1 credentials and database | **Out of scope — never accessed** | Owner-controlled remediation |

## Trust boundaries (Phase 1)

1. Browser → Django (authenticated session, CSRF-protected state changes).
2. Django → PostgreSQL (private, loopback-bound in local development).
3. Django → Redis (private, loopback-bound in local development).
4. **No outbound boundary exists.** There is no provider adapter, no webhook, no
   model API, and no source-system connection.

## Phase 1 threats and current status

| # | Threat | Status | Control |
|---|---|---|---|
| T1 | Secret committed to the repository | **Mitigated** | `.gitignore` denies `.env`, `CREDENTIALS.*`, `*.db`; `.env.example` holds names only, asserted by test |
| T2 | Development secret reaches a deployed environment | **Mitigated** | `validate_deployment_secret_key` rejects known defaults, the `django-insecure-` prefix, and keys under 50 chars; proven in subprocess tests |
| T3 | Wildcard host / origin in a deployed environment | **Mitigated** | `require_no_wildcard` + `validate_https_origin`; startup fails |
| T4 | Accidental external side effect | **Mitigated (structurally)** | No adapter exists; `EXTERNAL_ACTIONS_ENABLED` must be false at startup and is hard-coded `False` in settings |
| T5 | Test run against a real database | **Mitigated** | `config/dbguard.py` refuses non-allowlisted names/hosts before connecting |
| T6 | Test making a real outbound call | **Mitigated** | `tests/network_guard.py` blocks non-loopback `connect`/`create_connection`; proven by test |
| T7 | Secret or connection detail leaked in logs/errors | **Mitigated** | Allowlist JSON log formatter; readiness returns booleans only; `ConfigurationError` messages name variables, never values (asserted) |
| T8 | SQLite used by accident | **Mitigated** | Rejected at parse time in every environment |
| T9 | Runtime schema mutation (a V1 failure mode) | **Mitigated** | Django migrations only; drift test in CI-equivalent suite |
| T10 | Public signup or seed endpoint | **Mitigated** | No such route; asserted by test |
| T11 | Session fixation / weak password | **Partially mitigated** | Django session cycling on login; 12-char minimum + validators. MFA is a Phase 10 requirement |
| T12 | Brute-force login | **NOT mitigated** | No rate limiting yet. Required before pilot (section 20) |
| T13 | Cross-tenant data access | **Deferred** | No tenant model until Phase 2. The single largest threat class for this product |
| T14 | Privilege escalation across roles | **Deferred** | RBAC lands in Phase 2 |
| T15 | Malicious CSV (formula injection, zip bomb, huge row) | **Deferred** | Import lands in Phase 3 |
| T16 | Detector acting on stale/incomplete data | **Deferred** | Coverage contract lands in Phases 3–4 |
| T17 | Duplicate financial value from replay | **Deferred** | Idempotency lands in Phases 3–4 |
| T18 | Arbitrary file upload | **Mitigated (structurally)** | `EVIDENCE_MODE` is constrained to `metadata_only`; no upload path exists |

## Known gaps carried into later phases

- **No rate limiting** on login or sensitive actions (T12). Required before a pilot.
- **No MFA.** Required for owner, finance, and platform-admin access at Phase 10.
- **No tenant isolation yet** (T13/T14) — Phase 2 must land with negative tests.
- **Platform superuser** access via Django admin is not yet restricted; the admin is
  not enabled in Phase 1 and must be disabled or tightly restricted before deployment.
- **`SECURE_HSTS_SECONDS` defaults to 0.** HSTS is enabled only after HTTPS is
  verified on the real domain, to avoid pinning a broken certificate.

## Explicitly out of scope

V1's tracked credentials and its Git history. Remediation is an owner-controlled
security operation and a hard gate before any remote V2 deployment. This project
never opens those files.
