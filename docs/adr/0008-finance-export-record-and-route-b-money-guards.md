# ADR 0008 — The finance export record, and the money guards Route B needs

Status: accepted
Date: 2026-08-28

## Context

Four separate places in the specification assume a finance export exists:

* line 692 — the export must be idempotent;
* line 1386 — `invoice_ready -> exported` is a real financial workflow transition;
* line 1883 — there is a tenant- and role-scoped export **download** route;
* line 2700 — the Route B deliverable is an invoice-ready export a bookkeeper can use.

Section 22 nevertheless defines **no export model**: no table, no fields, no lifecycle.
Section 22.5 line 1238 gives `FinancialRecoveryItem` an "optional export reference" and
stops there. Something has to exist for those four rules to be about, so this ADR records
what was built and why, and the money guards that adversarial review showed were needed
around it.

None of the decisions below is a specification requirement. Each is versioned here so a
later change is a new decision rather than a silent edit.

## Decisions

### 1. `recovery.FinanceExport` is a first-class immutable record

Fields: `idempotency_key`, `content` (the CSV verbatim), `content_sha256`, `row_count`,
`total_invoice_ready_value`, `currency`, `created_by`, `superseded_note`, and a
many-to-many to the exported items.

Content is frozen after creation (`save()` and `delete()` raise `AppendOnlyError`). A
source correction that arrives after an export opens a dispute and, if needed, sets
`superseded_note` — it never rewrites or erases what was handed to a person, per line
1389 and 1391. `FinancialRecoveryItem.export_reference` stays the `CharField` the spec
named; the authoritative link is the many-to-many.

### 2. The idempotency key is the item set at its approved snapshots

`sha256("|".join(sorted(f"{item.id}:{item.current_invoice_ready_snapshot_id}")))`.

The obvious alternative — including `item.version` — cannot work: the export transaction
bumps `version` itself, so a resubmitted request would compute a different key and mint a
second reference for the same handoff. Keying on the snapshot also gets the re-approval
case right: a source correction produces a **new** snapshot, so a corrected export is
genuinely a different export.

The export form posts the item ids it displayed, so a resubmit names the same set and
`_replay()` resolves it to the export that already handled it.

### 3. The export re-proves "still unbilled" under its own lock

This is the guard that matters most, and it was missing in the first implementation.

Approval proves the work was unbilled *at approval time*. An `invoice_status` import can
land between approval and export, and the exported file is an instruction to raise an
invoice. So inside the same `select_for_update` transaction the export re-evaluates
checklist items 8 and 9 against current data, and refuses the **whole** request — zero
writes — if the item is now invoiced, disputed, or already exported.

Without this, the product's own kill criterion (§8.3: a false positive that tells an
operator to bill work that was already billed) is reachable through the normal path.

### 4. One export carries one currency

`stage_totals` withholds every total when the visible items span more than one currency,
and the export refuses a mixed set outright. Adding USD to EUR produces a number that
means nothing; §23.1 rule 5 already treats a currency mismatch as a dispute rather than a
conversion, and an aggregate cannot be looser than the rule it aggregates.

### 5. An accounting commit is what advances the accounting stage

`apps.recovery.services.accounting.refresh_organization` is called from
`imports.commit()` when the committed batch belongs to a source in the `invoice_status`
domain. Nothing else in Route B can move an item from "nobody has billed this" to
invoiced or collected; before this wiring the derivation service had no caller at all and
the ledger's confirmed columns would have stayed empty forever.

### 6. The approval also refuses a disputed item

Section 21.2 line 966 — "A blocking conflict prevents dependent detector/financial
approval until resolved" — is enforced in `approve_invoice_ready` as an explicit gate, not
as UI copy.

## Consequences

* An export is auditable without the product: content plus hash plus approver plus the
  evidence snapshot the approver saw.
* A repeat submit is safe and says so.
* Two currencies in one organization degrade to per-item figures rather than to a wrong
  headline number.
* `FinanceExport` and `Approval` are the only Phase 5/6 tables that exist; the phase
  boundary tests were updated to allow exactly those and still forbid recommendations,
  proposed actions, evidence artifacts, and draft handoffs.
