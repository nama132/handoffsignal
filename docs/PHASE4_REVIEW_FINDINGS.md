# Phase 4 — adversarial review findings

Source: 10-agent design+verify pass run in parallel with the build, 2026-08-27. The
verifiers reviewed both the design proposal and the code on disk. Findings that targeted
only the design agent's own proposal (a separate `apps/detection` app, a `requeue`
command that never existed) are omitted; these are the ones that applied to **shipped
code** or to correctness.

## Resolved

| # | Severity | Finding | Resolution |
|---|---|---|---|
| 1 | BLOCKING — false positive | Service date derived from the completion instant. Fixtures run 18:00–02:00, so a job finished at 01:30 dated to D+1, missed the ledger's D invoice, and would have flagged billed work. | Occurrence date = site-local `scheduled_at` date (else completion date); invoice search and coverage check use **both** candidate dates. ADR 0007 §3. Tested on both dates. |
| 2 | BLOCKING — false positive | Coverage row proved absence while its batch still held a quarantined row (the Potomac invoice was never imported, yet the batch claimed complete). | A batch with post-commit invalid rows cannot prove absence; resolving an identity now reprocesses the rows it blocked. ADR 0007 §6. |
| 3 | BLOCKING — duplicate case | Fingerprint included `rule_version`, so a version bump would open a second case for the same occurrence, violating condition 8. | `service_date` on the case + `uniq_case_per_work_order_occurrence`; re-evaluation refreshes rather than duplicates; terminal cases are never reopened. ADR 0007 §5. |
| 4 | BLOCKING — stale evidence | Open cases whose work order stopped matching (invoice arrived, authorization withdrawn) were never touched — `persist()` iterated matches only. Line 1401 requires the case be flagged for finance review without changing state. | `_flag_cases_that_stopped_matching`: appends a `contradicted` timeline event with the skip reason, links the invoice as contradicting evidence, retargets the next action. State untouched. |
| 5 | IMPORTANT — recovery | A `FAILED` DetectorRun could never be retried: the claim treated any terminal row as done. Line 711 requires a visible failed-job recovery path. | `claim()` reclaims a FAILED run at any time, resetting it to RUNNING with an incremented attempt; only SUCCEEDED short-circuits. |
| 6 | IMPORTANT — false positive | Authorization checked only the work-order flag; the contract's own `extra_work_requires_authorization` policy was ignored. | Required if either says so. ADR 0007 §4. Also exposed a fixture flaw: every obligation had been generated as `authorized_extra`; Capital Retail's quarterly burnish is now `periodic` contract scope. |
| 7 | found by test — stale evidence | Detector read freshness from the mutable `DataSource` row, not the manifest batch, so a later import changed what an earlier evaluation "saw". | Reads `ImportBatch.source_as_of_at` from the manifest. ADR 0007 §7. |
| 8 | found by test — reliability | `publish_intent` wrapped claim and publish in one transaction, so a broker failure rolled the claim back and erased the lease and attempt count the sweeper needs. | Claim commits first; publish runs outside the transaction; only the claim owner may mark published. The crash-boundary test now genuinely exercises the boundary. |

## Open

| # | Severity | Finding |
|---|---|---|
| 9 | IMPORTANT | An invoice matching customer/site/service-date that could *also* belong to a second completed work order on the same day is currently treated as billing for both. The design recommends opening a blocking `ReconciliationIssue` for the ambiguity instead. Not exercised by any fixture. |
| 10 | NOTE | `case_number` is derived from a count and retried on collision; a sequence would be cleaner under high concurrency. |
| 11 | NOTE | The 30-day deadline grace and $1,000 severity threshold (ADR 0007 §1–2) are placeholders awaiting partner input. |

## Confirmed sound by the verifiers

- The eight-condition ordering — positive facts first, the negative-evidence claim last and only after coverage is proven.
- Unknown money is `NULL`, never zero; `manual_amount_required` basis cannot carry a value (database check).
- `ExceptionCase.state` is unreachable except through the transition service (`save()` guard), and the guard is tested.
- Exactly-one-actor check constraints on both event models; append-only `save()`/`delete()` refusals, tested.
