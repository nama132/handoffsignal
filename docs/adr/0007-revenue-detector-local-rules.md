# ADR 0007 — Local rules the revenue detector needs that the specification leaves open

Status: accepted
Date: 2026-08-27

## Context

Section 24.2 defines the eight conditions for `REVENUE_COMPLETED_UNBILLED_V1` and the
candidate-value arithmetic, but — unlike 24.1 and 24.3 — it defines **no deadline and no
severity rule**, while `ExceptionCase` requires both and the inbox sorts by them (section
30.2). Three further points were found by adversarial review to be underspecified in a
way that produced false-positive paths in the first implementation. Section 12 principle
4 forbids unversioned rules invented at implementation time, so each is recorded here.

**None of these is a specification requirement.** They are local decisions, versioned so
a later change is a new rule rather than a silent edit.

## Decisions

### 1. `REVENUE_DEADLINE_V1`
`deadline_at = completed_at + uninvoiced_delay_days + 30 days`. The 30-day grace is a
demo placeholder for "how long finance has before this is overdue" and is expected to be
replaced by a partner-supplied value.

### 2. `REVENUE_SEVERITY_V1`
| Condition | Severity |
|---|---|
| ≥ 60 days past the uninvoiced delay | high |
| ≥ 30 days past, OR candidate value ≥ $1,000 | medium |
| otherwise | low |

`critical` is never assigned by this rule. Severity never drives a message or an external
action.

### 3. Service occurrence date (condition 4's "service-date identity")
Service windows cross midnight — every fixture obligation runs 18:00–02:00 — and the
accounting ledger's `service_date` is a plain date the source chose, normally the day the
job started. Deriving the occurrence from the completion instant alone would date a job
finished at 01:30 to D+1, miss the ledger's D invoice, and raise a **false positive**.

Therefore: **primary service date = site-local date of `scheduled_at` when present,
otherwise of `completed_at`.** The invoice search and the coverage-interval check use
**both** candidate dates (scheduled-date and completion-date). Searching both is
deliberately conservative: a missed invoice is a false positive, which section 8.3 names
as a kill criterion, while an over-suppressed case is merely a missed candidate.

The primary date is the case's occurrence identity (`ExceptionCase.service_date`).

### 4. Authorization is required if the work order OR the contract policy says so
Condition 5 says "if authorization is required". A work-order flag alone can be wrong at
source. Authorization is therefore required when `WorkOrder.authorization_required` is
true **or** the obligation is `authorized_extra` scope with
`extra_work_requires_authorization`. The contract's declared policy is an independent
check on the operations source.

### 5. One case per occurrence, across rule versions
Condition 8 forbids a second case for the same tenant, work order and occurrence. The
fingerprint (section 18) includes `rule_version`, so a version bump would otherwise open a
second case beside the first. `uniq_case_per_work_order_occurrence` on
`(organization, exception_type, work_order, service_date)` makes the occurrence the
identity; a re-evaluation under a new rule version **refreshes** the open case and
records the new version. A resolved or dismissed case for that occurrence stands and is
never reopened.

### 6. Coverage cannot prove absence while its batch holds quarantined rows
A committed batch whose rows were quarantined on identity errors is not a complete
observation of its own file — something in it was never imported. Its coverage row
cannot prove absence for anyone until those rows are re-resolved and promoted. Resolving
an identity now reprocesses the rows it was blocking (`imports.reprocess_quarantined`).

### 7. Freshness is judged from the manifest, not the mutable source row
`DataSource.last_source_as_of_at` changes with every import. The detector reads the
`source_as_of_at` of the `ImportBatch` on the run's immutable manifest, so a later import
cannot retroactively change what an evaluation saw (section 16.2).

## Alternatives considered

- Completion-date-only service date: rejected — demonstrated false positive on overnight
  windows.
- Fingerprint as the sole case identity: rejected — violates condition 8 on a rule bump.
- Trusting `DataSource` freshness: rejected — mutable state under an immutable manifest.
- Assigning `critical` severity: rejected — nothing in a revenue case is time-critical in
  the sense the attendance rule uses it.

## Consequences

- A partner interview must confirm what their ledger's `service_date` actually means;
  decision 3 is the most likely to change.
- The 30-day deadline grace and the $1,000 severity threshold are placeholders and are
  labelled as such in the UI.

## Security/privacy impact

Positive: decisions 3, 4 and 6 each close a path by which a customer could be accused of
unbilled work that was in fact billed, not billable, or not observable.

## Migration/rollback impact

Decision 5 added `ExceptionCase.service_date` and a partial unique constraint
(`exceptions/0002`, `0003`). All synthetic; reversible by dropping the two migrations.

## Validation evidence

- `tests/test_detector_revenue.py::TestTimezone::test_overnight_completion_belongs_to_the_start_date`
- `…::test_overnight_job_is_suppressed_by_an_invoice_on_either_date` (parametrized over both dates)
- `…::TestQuarantineAwareCoverage` (two tests)
- `…::test_freshness_comes_from_the_manifest_not_the_mutable_source_row`
- `tests/test_case_lifecycle.py::TestIdempotency::test_a_new_manifest_refreshes_the_case_rather_than_duplicating_it`
