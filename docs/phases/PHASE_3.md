# Phase 3 — CSV import, preview, commit, and source history

**Approval:** `Approve Phase 3`  **Status:** complete, pending review

## What the owner can now do

Upload one of four synthetic CSVs, declare what it covers, see a preview that **changes
nothing**, and explicitly commit. After commit, normalized records exist, source history
is appended, rows whose references do not resolve sit quarantined in an identity queue,
and a reconciliation run becomes `ready` exactly once. Replaying the identical file does
no semantic work.

## What was built

| Area | Contents |
|---|---|
| Models | `ImportBatch`, `ImportCoverage`, `ImportRow`, `SourceRecordVersion`, `ReconciliationRun`, `ReconciliationRunInput` |
| Errors | All 29 codes from section 28.8, each with safe guidance |
| Parsing | Streaming CSV reader: strict UTF-8, size and row limits, conservative header normalization, formula neutralization |
| Contracts | Four declarative column specifications with typed coercion |
| Services | coverage, identity, imports (upload/preview/commit), normalizers, reconciliation |
| Screens | imports list, upload, preview, results, identity queue, reconciliation queue |
| Fixtures | A generator producing the Atlas dataset, blank templates, and five invalid examples |

## The three rules that shape the design

1. **Preview writes nothing.** Asserted directly: counts of every operational model are
   captured before and after a preview call and compared.
2. **Commit is all-or-nothing.** Under the demo row limit the whole validated file
   promotes in one transaction. A forced failure mid-commit leaves nothing visible.
3. **Exact replay does no semantic work.** The same bytes, mapping version, source-as-of
   time and coverage manifest return the *same batch* — no second batch, no new source
   version, no duplicate records.

That third rule is why the `ImportBatch` uniqueness constraint spans seven columns rather
than just the content hash. Including `source_as_of_at` and `coverage_manifest_sha256` is
deliberate: **the same empty accounting export at a later legitimate as-of time is a new
observation**, while an exact replay of the same bytes and declarations is not.

## Coverage: how absence is proven

Negative evidence — "there is no invoice for this work" — is only safe when coverage is
explicit. `ImportCoverage.proves_absence` is true only when **all four** hold:

- completeness is `complete`,
- the source is authoritative,
- the batch actually committed,
- the observation mode is a snapshot, not a delta.

Anything less can supply positive facts but can never prove absence. Completeness is
never inferred from the filename, the row count, or how recent the file is — the user
declares it on the form, and only an authoritative source may claim it.

Query semantics come from a fixed allowlist; arbitrary user text can never define what a
coverage declaration means.

## Identity: how references resolve

A reference resolves **only** through a confirmed mapping. There is no name matching, no
similarity, no "probably the same". The three failure modes are distinguished so the
queue can explain what a human must decide: unresolved, ambiguous, and conflicting.

An unresolved reference **quarantines the row**. It never becomes a guessed canonical id,
and it blocks reconciliation readiness until an owner confirms the mapping.

This is demonstrated rather than asserted. The `ar_ledger` crosswalk row for the Potomac
site is deliberately absent, and invoice `80000944-1753000000` references that site. On
import the row is rejected, the invoice does not appear, an identity issue opens, and the
reconciliation run stays `waiting_inputs`. After the owner confirms the mapping, the run
becomes `ready` — exactly once.

## Where Phase 3 deliberately stops

A reconciliation run may become `ready`. **No `DetectorDispatchIntent` is created and
nothing is published.** Detector handlers do not exist yet, so creating an intent would
publish work nothing can consume.

The seam is empty on purpose, and tested as such: a test asserts the model does not exist
and that no `detector` or `dispatch` table is present in the database. Verified: **0
tables**.

The other three CSV kinds are unimplemented. `get_contract("scheduled_shifts")` **raises**
rather than returning an empty contract, because a missing importer must never resemble a
successful no-op import.

## The unused-column decision

`sites_contracts.csv` carries sixteen attendance- and quality-only columns — grace
periods, deficiency SLAs, weekly-hours thresholds, workweek boundaries, availability
policy, the qualification triple. Their target models are deliberately not built.

The columns are **declared and validated but persisted nowhere**, marked
`unused_in_route_b`, and asserted as such by test. The schema is the schema, and a
partner's export will contain them.

## Evidence

| Command | Result |
|---|---|
| `manage.py migrate` (fresh database) | all migrations apply cleanly |
| `ruff` / `mypy` | clean, 67 files |
| `pytest` | **612 passed** |
| `coverage --fail-under=85` | **88%** |
| `pip-audit` | no known vulnerabilities |

Live: all four screens returned 200; upload → preview (stating "Nothing has been imported
yet") → commit → results showing created = 3; replaying the identical file redirected to
the **same batch** with still only one batch in the database; source freshness showed one
fresh and three unknown — never assumed fresh.

The full four-file load produces 3 obligations, 17 crosswalk mappings, 4 work orders, and
**2 canonical invoices from 3 rows** with 2 payments — the invoice amount is stored once,
never counted per payment row.

## Three defects found and fixed

1. **The work-order validator was deleting the evidence the demo needs.** It rejected any
   row where authorization was required but absent. The specification requires the
   reference only when authorization is required *and obtained* — a work order that
   needed authorization and never received it is a real source state, and it is precisely
   the negative control Journey B depends on. Authorization is a **detector** rule, not
   an import rule. The row now imports and reports `has_required_authorization == False`.
2. **Duplicate detection fingerprinted the whole row**, so two legitimate payment rows for
   one invoice looked like conflicting duplicates. Repeats are now compared on
   invoice-scoped columns only.
3. **The quarantine fixture never fired** — no invoice referenced the site whose crosswalk
   had been omitted. The control was decorative until an invoice row was added for it.

## Known limitations

1. Coverage is declared at **organization scope** in the form; customer, site and
   work-order scopes exist in the model and validate, but have no form control yet.
2. `ReconciliationRun` creation is a service call, not yet scheduled — Phase 4 owns the
   cadence lease.
3. Precedence rules are enforced as blocking issues, but no automatic conflict **scanner**
   runs; issues are opened by services.
4. No CSV download of rejected rows yet — they are shown on screen.
5. Uploads are parsed from memory under the 5 MB demo limit rather than streamed to a
   temporary directory. Real-data retention rules are a Phase 10 requirement.
