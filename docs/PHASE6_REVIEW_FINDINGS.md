# Phase 6 — adversarial review findings

Sources: a 10-agent design+verify pass run in parallel with the build (2026-08-28), plus a
direct re-read of the shipped code. As in Phase 4, findings that targeted only the design
agent's own proposal are omitted — the design pass was written as if Phase 6 were
greenfield and repeatedly proposed things the shipped `apps/recovery/` already does
correctly (the idempotency key, the URL namespace, the export loop's typed errors). What
follows applied to **code on disk**.

Two things are worth saying plainly. Six of the nine resolved findings are defects the
build shipped and the review caught. Three of them could have put a wrong number, or a
second invoice, in front of a real customer.

## Resolved

| # | Severity | Finding | Resolution |
|---|---|---|---|
| 1 | BLOCKING — double invoice | The export never re-checked that the item was still unbilled. Its gates were workflow state, dispute status, snapshot presence and currency — never `accounting_stage`, and it never re-ran checklist item 8. An `invoice_status` import landing between approval and export produced a file telling a bookkeeper to invoice work that had just been invoiced: the exact false positive §8.3 names as a kill criterion. | The export re-evaluates checklist items 8 and 9 under its own `select_for_update`, and refuses the whole request — zero writes — naming the case and the reason. ADR 0008 §3. Proven end to end: committing an accounting CSV through the real import service is enough to stop the export. |
| 2 | BLOCKING — dead feature | `accounting.refresh` / `refresh_organization` had **no caller anywhere in `apps/`**. The derivation service, its stage machine and its dispute reasons were all reachable only from tests, so the ledger's "Confirmed invoiced" and "Confirmed collected" columns could never have filled in. | `imports.commit()` calls `refresh_organization` when the committed batch belongs to an `invoice_status` source. ADR 0008 §5. The test asserts the stage advances **without the test calling refresh**. |
| 3 | BLOCKING — wrong money | Cross-currency summation. `stage_totals` added every item's Decimal regardless of currency, and the export summed a mixed set and labelled the file with `items[0]`'s currency. §23.1 rule 5 already forbids converting; an aggregate cannot be looser than the rule it aggregates. | Totals are withheld entirely for a mixed set, with an on-screen explanation; the export refuses a mixed set. ADR 0008 §4. |
| 4 | BLOCKING — tenancy | `stage_totals` took only an organization, while the rows beside it were site-scoped. A supervisor granted one site (or none) saw zero rows and the organization-wide money. Same class as the Phase 2 dashboard hole. | Totals take `limit_to_site_ids` and the view passes `effective_site_scope(membership)`. Tested both ways: the ungranted reader sees nothing, the granted reader sees the figure. |
| 5 | BLOCKING — wrong money | `_mapped_invoices` excluded only `void`, though §23.1 rule 1 says "non-void, **non-disputed**". A disputed invoice was summed into `actual_invoiced_amount`, and a disputed payment counted as collected. | Matching is now status-parameterised: posted invoices are billed, disputed ones open `invoice_disputed_at_source`, and a disputed payment opens `payment_disputed_at_source` instead of being collected. |
| 6 | BLOCKING — evidence integrity | `FinancialImpactSnapshot.save()` compared only `candidate_value`, `basis` and `assumptions`. `invoice_ready_value`, `currency`, `calculation_code`, `calculation_version` and `snapshot_version` could all be overwritten in place on an approved snapshot with no error. | `IMMUTABLE_FIELDS` covers every value field, and the error names what was refused. Parametrised test over all seven. |
| 7 | BLOCKING — evidence integrity | `ck_snapshot_manual_basis_has_no_value` covered `candidate_value` only, so a `manual_amount_required` snapshot could carry an approved `invoice_ready_value` — a number nothing in the source supports, in the exported file. | Second check constraint `ck_snapshot_manual_basis_has_no_ready_value` (migration `exceptions.0004`). Tested at the database level. |
| 8 | IMPORTANT — crash | `_service_dates` asserted `completed_at is not None`, an invariant that held for the detector but not for the checklist, which the ledger runs for every row. An incomplete work order in the ledger crashed the page — and `assert` is stripped under `-O`. | Returns the scheduled date when there is no completion time; raises typed `NoServiceDate` only when a work order has neither. |
| 9 | IMPORTANT — wrong identifier | `_row` picked the work order's external reference with an unordered `.first()`. With confirmed references in two source systems the exported identifier — the one the bookkeeper keys their invoice from — could differ between runs. | Ordered by `(source__system_key, external_id)`; the row already names the system the id belongs to. |
| 10 | IMPORTANT — UI | The 375px control found the exceptions inbox overflowing the viewport by 229px. Every table except the ledger's was unwrapped. | All eleven tables wrapped in `.table-scroll`; the 52rem floor now applies only to `.table--dense`, so narrow tables size themselves. Five pages plus the case detail are asserted overflow-free at 375px. |
| 11 | NOTE — vacuity | Browser tests asserting the *absence* of a control would have passed on a blank page. | Every absence assertion now carries a positive precondition, plus a paired test proving finance sees the control on the same data. |

## Open

| # | Severity | Finding |
|---|---|---|
| 12 | IMPORTANT | Carried from Phase 4 (finding 9): an invoice matching customer/site/service-date that could belong to either of two completed work orders on the same day is attributed to both. Finding 1's export-time re-proof reduces the blast radius but does not resolve the ambiguity. No fixture exercises it. |
| 13 | IMPORTANT | The export's provenance columns are read live rather than from the approved snapshot's `assumptions`, so a later edit to a work order's rate could make an exported row's inputs disagree with the amount that was approved. The amount itself comes from the immutable snapshot, so the number is right; only the surrounding explanation could drift. |
| 14 | NOTE | The demo fixture's `source_as_of_at` is a fixed 2026-08-20. Freshness is not re-judged at approval time today; if it ever is, the fixture becomes unapprovable 48 hours after import and must be generated relative to `now`. |
| 15 | NOTE | Carried from Phase 2: the seed guard permits `APP_ENV=test`; role-matrix tests should parametrise from the shipped `Action` enum; the stale-session-hint auto-select is undocumented. |

## Confirmed sound by the verifiers

- The approval service builds its own checklist. There is no parameter, flag, or code path
  that can substitute one — asserted structurally, by signature inspection and by grepping
  `apps/recovery` for bypass spellings.
- The distinct-invoice rule: summing over invoices then over their payments, never over a
  join. Proven non-vacuous by reintroducing the join, which reports $960 for one $480
  invoice with two payments.
- Formula neutralisation reaches every exported cell. Proven non-vacuous by removing it.
- `FinanceExport` content and `FinancialStageEvent` rows are append-only, with `delete()`
  refusing as well as `save()`.
- 404-not-403 for another tenant's export, and an unknown UUID renders identically to a
  foreign one — so the pair cannot be used as an existence oracle.
