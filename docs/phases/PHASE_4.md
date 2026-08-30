# Phase 4 — Exception engine, state machine, audit, and inbox

**Approval:** `Approve Phase 4`  **Status:** complete, pending review

## What the owner can now do

Load the four Atlas files, resolve the one deliberate identity quarantine, and a
reconciliation run becomes `ready` — which now also inserts a durable dispatch intent. A
Celery worker (or the manual command) claims a leased `DetectorRun` and evaluates
`REVENUE_COMPLETED_UNBILLED_V1`. The inbox shows **exactly one** case: the $480 star work
order, labelled *candidate value*. The other three work orders produce no case, each with
a recorded skip reason. A finance reviewer acknowledges, assigns, resolves, or dismisses
it; every step is version-checked and audited.

## What was built

9 models across two new apps (`exceptions`, `audit`), one detector, four services, three
screens, one management command, and three Celery tasks.

| Area | Contents |
|---|---|
| Dispatch | `DetectorDispatchIntent`, on-commit nudge, recoverable sweeper |
| Runs | `DetectorRun` (leased, reclaimable), `DetectorScheduleLease` |
| Cases | `ExceptionCase`, `ExceptionSourceLink`, `ExceptionEvent` |
| Money | `FinancialImpactSnapshot`, `FinancialRecoveryItem` (candidate stage only) |
| Audit | `AuditEvent` — append-only, allowlisted metadata |
| Screens | Cockpit (`/app/`), inbox, case detail |

**Not built** (Route B): the attendance and quality detectors, and no placeholder for
them. Phase 5 is skipped entirely — no `RecommendationSet`, `Approval`, or
`ProposedAction`. Invoice-ready approval and export belong to Phase 6. Tests assert each
absence.

## The three things that carry the correctness

### 1. A negative claim is gated, not assumed

The detector evaluates its eight conditions in a deliberate order: cheap positive facts
first, the negative-evidence check **last** and only after coverage is proven. A missing
invoice row is never a fact on its own. The coverage row must be complete, from an
authoritative source, on a committed snapshot batch, under the exact
`ACCOUNTING_SERVICE_DATE_LEDGER_V1` contract, scoped to this organization/customer/site,
with every candidate service date inside its half-open interval — **and** the batch must
hold no quarantined rows. Anything less yields `insufficient_coverage` and a visible skip
count.

### 2. State changes have exactly one door

`ExceptionCase.save()` refuses a changed state unless the transition service authorized
it. Every transition locks the row, re-checks the role, requires the caller's expected
version, validates the edge and its required data, and writes the timeline event and
audit event **in the same transaction**. Two threads racing the same transition produce
one winner and one `StaleVersion` — tested with real threads on real connections.

### 3. Money is never guessed

Unknown is `NULL`, never zero — enforced by a database check that a `manual_amount_required`
basis cannot carry a value. Arithmetic is `Decimal` at four places; cents appear only at
display. The four financial stages are shown separately and never summed; three of them
read *"not available in this phase"* rather than a misleading `$0`.

## Evidence

| Command | Result |
|---|---|
| `migrate` (fresh database) | 26 migrations apply cleanly |
| `manage.py check` / `makemigrations --check` | no issues / no changes |
| `ruff format --check` / `ruff check` / `mypy` | clean, 87 files |
| `pytest` | **746 passed** |
| `coverage --fail-under=85` | **88%** |
| `pip-audit` | no known vulnerabilities |

**Live, end to end, no mocks:** after four files the run reported
`waiting_inputs / ['unresolved_identity']`; resolving the identity made it `ready` and
produced **1 dispatch intent, published**. The manual command reported
`scanned 4, created 1, skipped 3 {invoice_present, authorization_missing, not_completed}`.
The cockpit showed the `$480.00` candidate tile and three *"not available in this phase"*
tiles; the case detail offered Acknowledge, which moved the case to Acknowledged and grew
the timeline from 1 event to 2; replaying the same POST with the stale version left the
state unchanged.

## Eight defects found by adversarial review, and fixed

A design-and-verify pass ran in parallel with the build. Full detail in
`docs/PHASE4_REVIEW_FINDINGS.md`; the decisions are recorded in ADR 0007.

Three were **false-positive paths** — the failure mode section 8.3 names as a kill
criterion:

1. **Overnight service dates.** Every fixture window runs 18:00–02:00, so a job finished
   at 01:30 dated to the *next* day, missed the ledger's invoice for the actual service
   day, and would have accused a customer of unbilled work that was billed.
2. **Coverage proved absence while its own batch held a quarantined row** — the Potomac
   invoice was never imported, yet the batch claimed complete coverage.
3. **Authorization checked only the work-order flag**, ignoring the contract's own
   `extra_work_requires_authorization` policy. This also exposed a fixture flaw: every
   obligation had been generated as `authorized_extra`.

The rest: a rule-version bump would have opened a **second case** for one occurrence
(condition 8); open cases that stopped matching were never flagged for finance (line
1401); a `FAILED` run could never be retried (line 711); freshness was read from the
mutable source row instead of the immutable manifest; and `publish_intent` wrapped claim
and publish in one transaction, so a broker failure rolled back the lease the sweeper
needs.

Two more were found by the tests themselves rather than by review — the freshness bug
surfaced when a stale test reported `operations_stale` where `accounting_stale` was
expected, and the crash-boundary test failed until the claim was committed separately.

## Known limitations

1. **Open finding**: an invoice matching customer/site/service-date that could belong to a
   *second* completed work order on the same day is treated as billing for both. The
   design recommends a blocking reconciliation issue instead. No fixture exercises it.
2. `waiting_external` is encoded in the state machine but has no Phase 4 trigger — it
   needs an approved handoff (Phase 5/6).
3. The deadline grace (30 days) and severity threshold ($1,000) are placeholders awaiting
   partner input (ADR 0007 §1–2).
4. `case_number` is derived from a count with retry-on-collision; a sequence would be
   cleaner under high concurrency.
5. `make test-worker-integration` still exits cleanly without running a real worker — the
   tasks exist now, so this is the phase where that target should grow teeth.
6. Three Phase 2 findings remain open in `docs/PHASE2_REVIEW_FINDINGS.md`.

## Where this leaves Route B

Phase 4 was the last full phase before the revenue slice. Journey B is now detectable end
to end: import → reconcile → detect → triage. Phase 6 adds the finance evidence
checklist, the invoice-ready snapshot, the CSV export, and the Playwright controls — and
then the **mandatory evidence stop** described in `PHASE_0A.md`.
