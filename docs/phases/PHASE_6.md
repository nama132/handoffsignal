# Phase 6 — The Route B revenue slice: evidence, approval, export, and the ledger

**Approval:** `Approve Route B Revenue Slice`  **Status:** complete, pending review

## What the owner can now do

`make demo` loads the Atlas story and leaves one case: the $480 post-construction detail
clean at Meridian Property Group's NoVA site, completed 2026-07-06 and never invoiced.

Signed in as the finance reviewer, the recovery ledger shows that case with **four
separate money columns** and a ten-item evidence checklist. Every item is satisfied, so
**Approve invoice-ready** is offered. Approving writes an immutable invoice-ready
snapshot and records the exact evidence the reviewer saw. **Export** then hands over a
20-column CSV a bookkeeper can raise the invoice from in their own accounting system.

No invoice is created. Nothing is sent. `EXTERNAL_ACTIONS_ENABLED` is still false.

Signed in as the operations manager, supervisor, or auditor, neither button exists — and
posting directly to either URL returns 403.

## What was built

One new app (`apps/recovery`), 3 models, 4 services, 2 screens, 1 command, 5 test modules.

| Area | Contents |
|---|---|
| Evidence | `services/checklist.py` — the ten items of lines 2707–2717, each with its own code and the exact missing-evidence wording |
| Approval | `services/approvals.py` — `approve_invoice_ready`, `revoke_invoice_ready`; `Approval` model with a live-approval uniqueness constraint |
| Export | `services/exports.py` — 20 columns, idempotency key, formula neutralisation; `FinanceExport`, immutable and undeletable |
| Accounting | `services/accounting.py` — the five rules of §23.1, invoiced/collected derivation, six dispute reasons |
| Lifecycle | `FinancialStageEvent` — append-only, exactly-one-actor |
| Screens | Recovery ledger (`/app/recovery-ledger/`), protected export download |
| Rehearsal | `demo_load` command, `make demo-reset`, `make demo` |

**Not built:** Journey A and Journey C, arbitrary evidence handling, quality and
client-notification behaviour, and any external action. Tests assert each absence.

## The four things that carry the correctness

### 1. The approval cannot be talked into skipping evidence

`approve_invoice_ready` takes a membership and an item id. It builds the checklist itself,
from current data, using the caller's own proven authority — there is no parameter a
caller could pass to substitute or skip one. That is asserted structurally: a test
inspects the service signature for a checklist slot and greps the whole app for
`skip_checklist`, `force_approve`, `ignore_evidence`, and `bypass=`. Each of the ten items
is then shown to block approval on its own, with its own code.

The most important of those is item 7. If the contract supports no rate basis, the
candidate value is `NULL` and the basis is `manual_amount_required` — and two database
check constraints now refuse to let such a snapshot carry either a candidate or an
approved value. Nothing is assumed, at any layer.

### 2. The export re-proves the claim before it hands over a file

Approval proves the work was unbilled *then*. The exported file is an instruction to
invoice, and an accounting export can land in between. So the export re-evaluates the
accounting-coverage and duplicate items under its own row lock and refuses the entire
request — writing nothing — if the item is now invoiced, disputed, or already exported.

This was missing in the first implementation and is the single most consequential fix in
the phase; the review that caught it is in `docs/PHASE6_REVIEW_FINDINGS.md`, finding 1.
It is tested end to end: committing an accounting CSV through the real import service is
by itself enough to stop the export.

### 3. Four facts, never one number

Candidate, invoice-ready, invoiced and collected are computed independently and never
added. Invoiced and collected come only from the accounting source. A stage with no data
reads *none*, never `$0`. The distinct-invoice rule — sum over invoices, then over the
payments attached to them, never over a join — is guarded by a test that fails loudly if
anyone reintroduces the join, which would report $960 for one $480 invoice paid twice.

Totals are also site-scoped and single-currency: a reader who cannot see a site does not
see its money, and a mixed-currency set reports no total at all rather than adding USD to
EUR.

### 4. The browser controls are real controls

Twenty Playwright tests drive a real Chromium against a real server: the finance journey
through to a downloaded, formula-safe CSV; the wrong-role buttons absent **and** direct
POSTs rejected; another tenant's case and export both 404, rendering identically to an
unknown UUID; an already-invoiced work order never surfaced; insufficient coverage
removing the control and rejecting a direct POST; a resubmitted export resolving to the
first one; and six pages asserted overflow-free at 375px.

## What the review caught

Eleven findings against shipped code, six of them defects that could have shown a wrong
number or caused a second invoice. Full detail in `docs/PHASE6_REVIEW_FINDINGS.md`. The
three worst: the export never re-checked that the work was still unbilled; the accounting
derivation service had no caller at all, so the confirmed columns could never have
filled; and stage totals ignored site scope, showing a supervisor with zero site grants
the organization-wide figure.

The 375px control earned its place by failing on first run — the exceptions inbox
overflowed by 229px.

## Known limitations

1. **Open finding**: an invoice that could belong to either of two completed work orders
   on the same day is attributed to both (carried from Phase 4).
2. The export's provenance columns are read live rather than from the approved snapshot's
   `assumptions`, so the explanation around an amount could drift even though the amount
   itself comes from the immutable snapshot.
3. Freshness is not re-judged at approval time. If it ever is, the fixture's fixed
   `source_as_of_at` must be generated relative to `now`.
4. `make test-worker-integration` still exits cleanly without a real worker.
5. Three Phase 2 findings remain open.

## Where this leaves the product

Route B is complete: the cross-system revenue hypothesis is demonstrable end to end on
synthetic data, and the product refuses to state anything it cannot evidence.

**Nothing further should be built yet.** The next gate is the mandatory evidence stop from
`PHASE_0A.md`: five or more operator interviews, at least one with a finance reviewer,
plus one sanitized walkthrough of a real source export — before `Approve evidence
expansion plan`. The demo exists to earn those conversations, not to substitute for them.
