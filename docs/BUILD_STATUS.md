# Build status — OpsRecovery V2

Status ledger: what exists, what was verified, and what is approved. It is intentionally
terse. For the narrative record of each phase — what was decided, what was rejected, and
what the evidence was — see `docs/phases/`.
Updated at the end of every phase. A phase is never marked `approved` by Claude;
approval is recorded only after the owner gives it.

| Field | Value |
|---|---|
| Route | **B — capped synthetic concept** (Journey B, "completed but not invoiced") |
| Current phase | Phase 6 — Route B revenue slice: evidence, approval, export, ledger |
| Status | `complete_pending_review` |
| Branch | `v2-commercial-cleaning` |
| Commits | **none** — no commit has been made or requested |

## Approval log

| Date | Phase | Wording received | Recorded |
|---|---|---|---|
| 2026-08-27 | Phase 0 | (preflight requested; report delivered) | complete |
| 2026-08-27 | Phase 0A | "Proceed with Phase0A as we need a demo to get an interview" | complete |
| 2026-08-27 | Phase 1 | "Apporve synthetic-concept Phase 1" — read as `Approve synthetic-concept Phase 1` | complete, pending review |
| 2026-08-27 | Phase 2 | "Approve Phase 2" | complete, pending review |
| 2026-08-27 | Phase 3 | "Approve Phase 3" | complete, pending review |
| 2026-08-27 | Phase 4 | "Approve Phase 4" | complete, pending review |
| 2026-08-28 | Phase 6 | "Approve Route B Revenue Slice" | complete, pending review |

Phase 5 was **skipped entirely** under the Route B scope override (line 2690).

Route B consequence: Journeys A (late/no-show) and C (failed inspection) are
deliberately **unbuilt**, with no placeholder behaviour, until the post-slice
evidence checkpoint and an explicit `Approve evidence expansion plan`.

## Phase 1 deliverables

| Deliverable | State |
|---|---|
| Workspace structure for `common` and `organizations` | done |
| `pyproject.toml`, pinned direct dependencies, `uv.lock` | done |
| `.python-version` pinned to 3.13.15 | done |
| Custom user model in the initial migration | done |
| Split settings base/local/test/production | done |
| Docker Compose PostgreSQL + Redis, non-default ports | done |
| Celery wired, no business task | done |
| WhiteNoise + Gunicorn configuration | done |
| `/health/live/` and `/health/ready/` | done |
| Root redirect + authenticated foundation-status page | done |
| `.env.example` — names and safe comments only | done |
| `.gitignore`, `.dockerignore` | done |
| README, this file, ADRs, threat-model outline | done |
| pytest / Ruff / mypy / coverage / pip-audit configuration | done |
| Network-blocking test setup and test database guard | done |

## Migrations added

| App | Migration | Contents |
|---|---|---|
| `organizations` | `0001_initial` | `User` — UUID pk, unique email, display_name, is_active, is_staff, date_joined |

`apps.common` contributes abstract bases only and has no migration by design.

## Environment verified

| Component | Version |
|---|---|
| Python | 3.13.15 (uv-managed) |
| Django | 5.2.17 |
| Celery / kombu / redis-py | 5.6.3 / 5.6.2 / 6.4.0 |
| psycopg | 3.3.4 (binary) |
| PostgreSQL | 18.6 (`postgres:18.6-trixie`) |
| Redis | 8.10.1 (`redis:8.10-alpine`), `maxmemory-policy noeviction` |
| gunicorn / whitenoise | 26.2.0 / 6.12.0 |
| uv | 0.12.6 |

## Commands run and results

| Command | Result |
|---|---|
| `uv sync --frozen --all-groups` | 70 packages |
| `uv run python manage.py migrate` | 16 migrations applied to a fresh PostgreSQL 18.6 database |
| `uv run python manage.py check` | no issues (0 silenced) |
| `uv run python manage.py makemigrations --check --dry-run` | no changes detected |
| `uv run ruff format --check .` | 47 files already formatted |
| `uv run ruff check .` | all checks passed |
| `uv run mypy apps config` | success, no issues in 25 source files |
| `uv run pytest -q -m "not worker_integration"` | **165 passed** |
| `uv run coverage report --fail-under=85` | **97%** total (449 stmts, 94 branches) — exit 0 |
| `uv run pip-audit -r <exported lock>` | no known vulnerabilities |
| `make test-worker-integration` | exits 0 with "no worker_integration tests registered yet" |
| `manage.py check --deploy --settings=config.settings.production` | 1 warning: `security.W021` HSTS preload — intentional, see below |

### Manual verification

| Flow | Result |
|---|---|
| `/health/live/` with both dependencies up | HTTP 200 `{"status": "ok"}` |
| `/health/ready/` with both up | HTTP 200 `{"database": true, "redis": true}` |
| `/health/live/` with Redis stopped | HTTP 200 — liveness performs no dependency I/O |
| `/health/ready/` with Redis stopped | HTTP 503 `{"database": true, "redis": false}` |
| `/health/live/` with Redis **and** PostgreSQL stopped | HTTP 200 |
| `/health/ready/` with both stopped | HTTP 503 `{"database": false, "redis": false}` |
| Readiness payload after restoring services | HTTP 200 `ready` |
| `GET /` anonymous | 302 → `/app/` |
| `GET /app/` anonymous | 302 → `/accounts/login/?next=/app/` |

Readiness responses contain per-dependency booleans only — no host, port, driver, or
error text. Asserted by `test_readiness_response_reveals_no_connection_details`.

### Defects found and fixed during this phase

| # | Defect | Fix |
|---|---|---|
| 1 | `get_str`/`get_bool` treated `required=True` as overriding a supplied default, so startup failed on `EVIDENCE_MODE` even with a valid default | A default now satisfies a requirement; `required` raises only when no default exists |
| 2 | Login was not actually case-insensitive: the model lowercases email on save, but `ModelBackend` looks up `USERNAME_FIELD` exactly | Added `apps/organizations/auth_backends.EmailBackend`, which normalizes before lookup |
| 3 | `NetworkAccessBlocked` was defined in `conftest.py`; pytest imports that file under a synthetic module name, so `from tests.conftest import ...` created a second class and `pytest.raises` never matched — the blocker's own tests were passing vacuously | Moved the guard to `tests/network_guard.py` so the class has one identity |
| 4 | The V1-import detector matched substrings and flagged `from config.celery import app as celery_app` | Replaced with a top-level-import regex plus a self-test proving the detector is not vacuous |
| 5 | `pytest 9` native TOML requires `addopts` as a list, not a string | Corrected in `pyproject.toml` |

## Known limitations

1. No tenant model, RBAC, or site scoping — Phase 2.
2. No rate limiting on login — required before pilot.
3. No MFA — required at Phase 10.
4. Django admin is not enabled; access restriction is a Phase 8 deployment concern.
5. Django 5.2 is in security-only support; upgrade target is 6.2 LTS (April 2027).
6. Django 5.2's CI does not cover PostgreSQL 18 — mitigated by running the full
   suite against 18 locally on every phase.
7. `factory_boy` 3.3.3 has no released Django 5.2 classifier. It is installed but
   not yet exercised; Phase 2 factories will confirm it.
8. `make test-worker-integration` exits cleanly with a message because no Celery
   business task exists yet. It becomes meaningful in Phase 4.
9. `manage.py check --deploy` reports `security.W021` (HSTS preload not enabled).
   Intentional: `SECURE_HSTS_SECONDS` defaults to 0 and preload is not set, so a
   broken certificate cannot be pinned into browsers before HTTPS is verified on a
   real domain. Revisit in Phase 8.
10. Coverage is 97% overall, but that measures the foundation only. The 90% branch
   target for detector, transition, eligibility, financial-calculation,
   import-commit, and authorization services applies from Phase 3 onward.

## Security and data boundary

- V1 changed: **No.** Baseline `main` @ `a6cc7d5`, 0 dirty entries, verified before
  and after Phase 1.
- Denylisted files opened: **None.**
- Live services contacted: **None.** Package downloads and documentation lookups only.
- Real data used: **No.**
- External actions: disabled structurally; no adapter exists.

## Next gate

Phase 2 — Tenant identity, RBAC, and operational primitives, reduced to the Route B
subset (omit worker/shift/time/quality models). Requires `Approve Phase 2`.

---

# Phase 2 — Tenant identity, RBAC, and operational primitives

Status: `complete_pending_review`

## Deliverables

| Deliverable | State |
|---|---|
| `Organization`, `Membership`, `MembershipRoleGrant`, deny-by-default `MembershipSiteGrant` | done |
| Customer, Site, Contract, ContractSite, ServiceObligation | done |
| WorkOrder, AccountingInvoice, AccountingPayment | done |
| `DataSource`, `ExternalEntityReference`, `IdentityResolutionIssue`, `SourcePrecedenceRule` (+ ordered `SourcePrecedenceEntry`), `ReconciliationIssue` | done |
| Tenant middleware/context and explicit scoped selectors | done |
| Role policy service implementing the section 9.3 matrix | done |
| Login, logout, organization selection, minimal authenticated shell | done |
| Admin-only local management commands (`create_owner`, `seed_demo`) | done |
| Data dictionary and ER diagram | done — `docs/DATA_DICTIONARY.md` |
| Worker/shift/time/quality models | **deliberately absent** (Route B, line 2296) |
| `SiteOperationalRule` | **deliberately absent** — every field is an attendance or quality input |

## Migrations added

| App | Migration | Contents |
|---|---|---|
| `operations` | `0001_initial`, `0002_initial` | 8 models, 16 constraints |
| `organizations` | `0002_...` | Organization, Membership, MembershipRoleGrant, MembershipSiteGrant |
| `ingestion` | `0001_initial`, `0002_initial` | 6 models, 11 constraints |

The Phase 2 migrations were regenerated once, mid-phase, when `SourcePrecedenceEntry`
gained its `organization` column. They had never been committed, released, or applied
outside the local disposable database, and all data is synthetic — so regeneration was
preferred over stacking a patch migration (section 46).

## Commands run and results

| Command | Result |
|---|---|
| `manage.py migrate` (fresh database) | 21 migrations applied |
| `manage.py check` | no issues |
| `makemigrations --check --dry-run` | no changes detected |
| `ruff format --check .` / `ruff check .` | 79 formatted / all passed |
| `mypy apps config` | no issues, 46 files |
| `pytest -m "not worker_integration"` | **488 passed** |
| `coverage report --fail-under=85` | **96%** — exit 0 |
| `pip-audit` | no known vulnerabilities |

## Manual verification

| Flow | Result |
|---|---|
| Atlas owner signs in | sees Atlas only; zero occurrences of Beacon's customer |
| Beacon owner signs in | sees Beacon only; zero occurrences of Atlas's customers |
| Atlas owner POSTs Beacon's **real** organization UUID | HTTP 404, no name leaked |
| Same POST with a nonexistent UUID | HTTP 404 — indistinguishable |
| POST with no CSRF token | HTTP 403, no write |
| Supervisor granted 1 of 3 sites | sees that site only; other two absent |
| Operations manager, zero site grants | sees all three sites (tenant-wide, correctly not narrowed) |
| Auditor | every management permission renders "Not permitted" |

## Defects found by adversarial review and fixed in this phase

Three blocking defects were found in shipped Phase 2 code by a 10-agent design+verify
pass and fixed before this report. Full detail in `docs/PHASE2_REVIEW_FINDINGS.md`.

1. **Cross-tenant hole** — `SourcePrecedenceEntry` was a plain `models.Model` with no
   organization column, so a join row could link a rule in one tenant to a data source
   in another. Now tenant-scoped and same-tenant validated, with a generic guard test
   covering every tenant-owned model.
2. **Tenancy hole** — the shell scoped only by organization, so a supervisor with zero
   site grants saw every site and customer. Site scope is now resolved by the policy
   layer and threaded through six selectors; an empty grant set is passed through
   verbatim and never widened.
3. **Vacuous test** — the supervisor test asserted an explanatory sentence rather than
   the absence of site names, and passed while the page leaked everything. Rewritten to
   assert rendered identifiers and proven to fail when the fix is reverted.

## Known limitations

1. Three review findings remain open, tracked in `docs/PHASE2_REVIEW_FINDINGS.md`:
   the seed guard permits `APP_ENV=test` (§31 names local/demo) and lacks a `DEMO_MODE`
   gate; role-matrix tests should parametrize from the shipped `Action` enum; and the
   stale-session-hint auto-select should be documented rather than silent.
2. No overlap **exclusion constraint** in the database for effective periods. Overlap is
   rejected in `clean()` and tested; a PostgreSQL exclusion constraint needs the
   `btree_gist` extension and a generated range column, deferred to a dedicated ADR.
3. Same-tenant foreign keys are enforced in model `clean()` and by tests, not by a
   database constraint — Django 5.2 cannot express a cross-row tenant predicate. This is
   what section 22.1 line 796 permits.
4. `IdentityResolutionIssue` and `ReconciliationIssue` record the supplied source and
   external identifier but not a `SourceRecordVersion`, which is a Phase 3 model.
5. No login rate limiting and no MFA — both required before pilot.
6. Django admin remains unenabled; platform-superuser restriction is a Phase 8 concern.

## Security and data boundary

- V1 changed: **No.** `main` @ `a6cc7d5`, 0 dirty entries — identical to the Phase 0 baseline.
- Denylisted files opened: **None.**
- Live services contacted: **None.**
- Real data used: **No.** All synthetic; two fictional tenants.
- Cross-tenant/role tests: **passing**, including the three fixed defects above.
- Secret scan over all changed V2 files: **0 hits**. The only credential-shaped strings
  are documented local development values that production validation actively rejects.
- Commits: **none**.

## Next gate

Phase 3 — CSV import, preview, commit, and source history, limited by the Route B matrix
to four contracts: `sites_contracts`, `entity_crosswalk`, the work-order record family of
`work_orders_service_events`, and `invoice_status`. Requires `Approve Phase 3`.


---

# Phase 3 — CSV import, preview, commit, and source history

Status: `complete_pending_review`

## Deliverables

| Deliverable | State |
|---|---|
| ImportBatch, ImportCoverage, ImportRow, SourceRecordVersion, ReconciliationRun + input manifest | done |
| Four Route B schema validators (`sites_contracts`, `entity_crosswalk`, work-order rows, `invoice_status`) | done |
| Upload, preview, commit, history, and results screens | done |
| Identity crosswalk import and unresolved-reference resolution queue | done |
| Reconciliation/conflict queue driven by explicit source-precedence rules | done |
| Idempotent normalization/upsert to the Phase 2 models | done |
| Row-level safe error reporting (all 29 codes from section 28.8) | done |
| Source freshness fields and UI | done |
| Synthetic valid, boundary, duplicate, and invalid CSV fixtures | done |
| Management command generating templates and the Atlas dataset | done |
| Reconciliation manifest with atomic waiting→ready, **no dispatch intent** | done |
| The other three CSV kinds | **deliberately unimplemented** — `get_contract` raises |

## Migrations added

| App | Migration | Contents |
|---|---|---|
| `ingestion` | `0003_...` | 6 models, 8 constraints, 2 indexes; adds the `SourceRecordVersion` links Phase 2 deferred on both issue models |

## Commands run and results

| Command | Result |
|---|---|
| `manage.py migrate` (fresh database) | all migrations apply cleanly |
| `manage.py check` / `makemigrations --check` | no issues / no changes |
| `ruff format --check` / `ruff check` | 104 formatted / all passed |
| `mypy apps config` | no issues, 67 files |
| `pytest -m "not worker_integration"` | **612 passed** |
| `coverage report --fail-under=85` | **88%** — exit 0 |
| `pip-audit` | no known vulnerabilities |

## Manual verification

| Flow | Result |
|---|---|
| `/app/imports/`, `/new/`, `/identity-resolution/`, `/reconciliation-issues/` | HTTP 200 |
| Upload → preview | preview states "Nothing has been imported yet" and offers commit |
| Commit | HTTP 302; results page shows created = 3 |
| Replay the identical file | redirects to the **same** batch; database still holds 1 batch |
| Source freshness | 1 fresh, 3 unknown (never imported) — never assumed fresh |
| Four-file load in order | 3 + 17 + 4 + 4 records; 2 canonical invoices from 3 rows, 2 payments |
| Quarantine control | the invoice referencing the unmapped Potomac site is rejected, opens an identity issue, and **blocks** reconciliation readiness |
| Owner resolves the identity | run then becomes `ready` exactly once |
| Detector/dispatch tables | 0 — Phase 3 stops at readiness |

## Defects found and fixed during this phase

| # | Defect | Fix |
|---|---|---|
| 1 | The work-order validator rejected any row whose authorization was required but absent, deleting the very negative control the demo needs. Section 28.6 requires the reference only when authorization is required **and obtained**. | Removed; section 24.2 condition 5 is a detector rule. The unauthorized work order now imports and reports `has_required_authorization == False`. |
| 2 | Duplicate detection fingerprinted the whole row, so two legitimate payment rows for one invoice looked like conflicting duplicates. | For `invoice_status`, repeats are compared on invoice-scoped columns only (section 28.7). |
| 3 | The quarantine fixture never fired: no invoice referenced the site whose crosswalk was deliberately omitted. | Added invoice `80000944-1753000000` for the Potomac site, so the control is real. |

## Known limitations

1. Coverage is declared at organization scope in the UI form; customer/site/work-order
   scopes exist in the model and are validated but have no form control yet.
2. `ReconciliationRun` creation is a service call, not yet wired to a schedule — Phase 4
   owns the cadence lease.
3. Precedence rules are modelled and enforced as blocking issues, but no automatic
   conflict **detection** runs yet; issues are opened by services, not by a scanner.
4. The downloadable invalid-row report is available as on-screen rows; a CSV download of
   rejected rows is not yet implemented.
5. Uploads are parsed from memory under the 5 MB demo limit rather than streamed to a
   temporary directory. Real-data retention rules are a Phase 10 requirement.
6. Three review findings from Phase 2 remain open in `docs/PHASE2_REVIEW_FINDINGS.md`.

## Security and data boundary

- V1 changed: **No.** `main` @ `a6cc7d5`, 0 dirty entries.
- Denylisted files opened: **None.** Live services contacted: **None.** Real data: **No.**
- Secret scan across 157 changed files: **0 hits**.
- Fixtures contain no email addresses, street addresses, or postcodes.
- Raw rows never enter logs: `ImportRow.raw_data` is excluded from logging and error text.
- Commits: **none**.

## Next gate

Phase 4 — Exception engine, state machine, audit, and inbox. Route B implements **one**
detector (`REVENUE_COMPLETED_UNBILLED_V1`), not three. Requires `Approve Phase 4`.


---

# Phase 4 — Exception engine, state machine, audit, and inbox

Status: `complete_pending_review`

## Deliverables

| Deliverable | State |
|---|---|
| DetectorRun, DetectorScheduleLease, durable DetectorDispatchIntent + dispatcher/sweeper | done |
| ExceptionCase, ExceptionSourceLink, ExceptionEvent, FinancialImpactSnapshot, FinancialRecoveryItem, AuditEvent | done |
| Versioned deterministic detector `REVENUE_COMPLETED_UNBILLED_V1` | done |
| Stable fingerprints, occurrence-based case deduplication | done |
| Explicit transition command service (the only path to `state`) | done |
| Deadline/severity calculation | done — local rules, ADR 0007 |
| Source-freshness suppression | done (read from the immutable manifest) |
| Cross-source identity/reconciliation blocking with visible reasons | done |
| Exception inbox, filters, case detail, rule/source explanation, timeline | done |
| Manual detector management command and Celery task | done |
| Periodic detector schedule with a database lease | done |
| Candidate value snapshot from separate operations/contract/accounting sources | done |
| Attendance and quality detectors | **deliberately absent**, no placeholder |
| Recommendation, approval, handoff, export | **not built** — Phase 5 skipped, Phase 6 pending |

## Migrations added

| App | Migration | Contents |
|---|---|---|
| `audit` | `0001_initial` | AuditEvent + exactly-one-actor check |
| `exceptions` | `0001_initial` | 8 models, 15 constraints |
| `exceptions` | `0002`, `0003` | `ExceptionCase.service_date` + occurrence uniqueness (ADR 0007 §5) |

## Commands run and results

| Command | Result |
|---|---|
| `manage.py migrate` (fresh database) | 26 migrations applied |
| `manage.py check` / `makemigrations --check` | no issues / no changes |
| `ruff format --check` / `ruff check` | 134 formatted / all passed |
| `mypy apps config` | no issues, 87 files |
| `pytest -m "not worker_integration"` | **746 passed** |
| `coverage report --fail-under=85` | **88%** — exit 0 |
| `pip-audit` | no known vulnerabilities |

## Manual verification

| Flow | Result |
|---|---|
| Four files loaded, identity unresolved | run `waiting_inputs`, blocker `unresolved_identity` |
| Identity resolved | run `ready`; **1 dispatch intent, published** |
| `manage.py run_detectors` | scanned 4, created 1, skipped 3 with named reasons |
| Star case | `REV-00001`, severity medium, service_date 2026-07-06, candidate $480.00 |
| Stage totals | candidate $480.00; invoice_ready / invoiced / collected all `None` |
| Cockpit | `$480.00` tile + 3 × "not available in this phase" |
| Inbox / case detail | 1 case listed; Acknowledge offered to finance reviewer |
| Acknowledge | 302; state → Acknowledged; timeline 1 → 2 events |
| Replay with stale version | refused; state unchanged |

## Defects found and fixed

Eight, six by an adversarial design+verify pass and two by the tests themselves. Three
were false-positive paths (overnight service dates, coverage proving absence while its
batch held a quarantined row, authorization ignoring contract policy). Full detail in
`docs/PHASE4_REVIEW_FINDINGS.md`; decisions in ADR 0007.

## Known limitations

1. Ambiguous invoice match across two same-day work orders is not yet routed to a
   blocking reconciliation issue (open finding 9).
2. `waiting_external` has no Phase 4 trigger.
3. Deadline grace and severity thresholds are placeholders (ADR 0007 §1–2).
4. `case_number` uses count-plus-retry rather than a sequence.
5. `make test-worker-integration` still runs no real worker.
6. Three Phase 2 findings remain open.

## Security and data boundary

- V1 changed: **No.** `main` @ `a6cc7d5`, 0 dirty entries.
- Denylisted files opened: **None.** Live services contacted: **None.** Real data: **No.**
- Secret scan across 199 changed files: **0 hits**.
- Detector and services contain **no network calls** (asserted by test).
- `EXTERNAL_ACTIONS_ENABLED` remains hard-coded `False`; creating a case sends nothing.
- Audit metadata is allowlisted; raw rows cannot be written through it.
- Commits: **none**.

## Next gate

Phase 6, Route B revenue subset only. Requires the exact approval
`Approve Route B Revenue Slice`. **Phase 5 is skipped.** After Phase 6 comes the mandatory
evidence checkpoint — no second journey, no polish, no hosting until then.

# Phase 6 — Route B revenue slice

## Deliverables

| Deliverable | State |
|---|---|
| Ten-item invoice-ready evidence checklist (lines 2707–2717) | done |
| Approval service with no bypass, structurally asserted | done |
| Immutable invoice-ready snapshot (v2 of the candidate) | done |
| Invoice-ready CSV export, idempotent, formula-safe, immutable | done |
| Tenant- and role-scoped export download (line 1883) | done |
| Accounting stage derivation, five rules of §23.1, six dispute reasons | done |
| Recovery ledger: four separate facts, never one total | done |
| Route B Playwright controls (journey, wrong-role, cross-tenant, insufficient coverage, already-invoiced, replay, 375px) | done |
| `make demo` / `make demo-reset` rehearsal path | done |
| Journey A, Journey C, evidence artifacts, external actions | **not built**, asserted absent |

## Migrations added

| App | Migration | Contents |
|---|---|---|
| `recovery` | `0001_initial` | `Approval`, `FinanceExport`, `FinancialStageEvent` + constraints |
| `exceptions` | `0004` | `ck_snapshot_manual_basis_has_no_ready_value` |

## Commands run and results

| Command | Result |
|---|---|
| `manage.py check` / `makemigrations --check` | no issues / no changes |
| `ruff format --check` / `ruff check` | 163 formatted / all passed |
| `mypy apps config` | no issues, 100 files |
| `pytest -m "not worker_integration and not browser"` | **839 passed** |
| `pytest -m browser` | **20 passed** (real Chromium, real server) |
| `coverage report --fail-under=85` | **87%** — exit 0 |
| `pip-audit` | no known vulnerabilities |
| `make demo-reset` | 4 files, 1 identity resolved, run ready, 1 case, candidate $480.0000 |

## Manual verification (against the reset demo database)

| Flow | Result |
|---|---|
| Operations manager POSTs the approval URL directly | **403**; item unchanged |
| Finance reviewer loads the ledger | approve control present, evidence complete |
| Finance reviewer approves | 302; `invoice_ready`; snapshot v2 = $480.0000 |
| Finance reviewer exports | 302; 1 row, $480.0000 USD; item → `exported` |
| Same export resubmitted | 302; still **1** export record |
| Download | 200, `text/csv`, 694 bytes, BOM, `attachment`, `nosniff` |
| First data row | `REV-00001,Meridian Property Group,…,00518774,CT-2026-MERIDIAN-01,…` |
| Auditor downloads | **403** |
| Beacon owner downloads Atlas's export | **404** (not 403 — existence is the secret) |
| Supervisor with no site grants | sees no rows **and no money** |

## Defects found and fixed

Eleven against shipped code — six of them defects that could have shown a wrong number or
caused a second invoice. The worst three: the export never re-checked that the work was
still unbilled; `accounting.refresh` had no caller anywhere, so the confirmed columns
could never have filled; and stage totals ignored site scope. Full detail in
`docs/PHASE6_REVIEW_FINDINGS.md`; decisions in ADR 0008.

## Known limitations

1. Ambiguous invoice match across two same-day work orders (carried from Phase 4).
2. Export provenance columns are read live rather than from the approved snapshot's
   `assumptions`; the amount is from the snapshot, only its explanation could drift.
3. Freshness is not re-judged at approval time.
4. `make test-worker-integration` still runs no real worker.
5. Three Phase 2 findings remain open.

## Security and data boundary

- V1 changed: **No.** `main` @ `a6cc7d5`, 0 dirty entries.
- Denylisted files opened: **None.** Live services contacted: **None.** Real data: **No.**
- Secret scan across 228 changed V2 files: **0 hits** (denylisted paths and repository
  history excluded by design).
- `EXTERNAL_ACTIONS_ENABLED` remains `False`; `EVIDENCE_MODE` remains `metadata_only`.
  Approving and exporting create no invoice and send nothing.
- Commits: **none**.

## Next gate

**Not another phase.** The mandatory evidence checkpoint from `PHASE_0A.md`: five or more
operator interviews, at least one with a finance reviewer, plus one sanitized walkthrough
of a real source export. Only then does `Approve evidence expansion plan` become
meaningful.
