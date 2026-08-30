# Atlas Facility Services — synthetic fixtures

Every value here is fictional. No real customer, site, worker, amount, or address
appears in any of these files.

## Load order

Section 27 requires `sites_contracts`, then `entity_crosswalk`, then the fact files.
A fact that arrives before its canonical entity stays quarantined rather than being
guessed.

1. `sites_contracts.csv` — establishes canonical customers, sites, contracts, obligations
2. `entity_crosswalk.csv` — maps the two alias dialects onto those canonical records
3. `work_orders_service_events.csv` — operations facts
4. `invoice_status.csv` — accounting facts

## Three identifier dialects

| Source | Shape | Example |
|---|---|---|
| `contract_register` | UPPER-HYPHEN-TOKENS | `MBC-NOVA-01` |
| `opsplatform_workorders` | zero-padded integer | `00093011` |
| `ar_ledger` | accounting list id | `80000107-1739216455` |

The accounting export carries **no work-order identifier** on any row. Reconciliation
therefore has to run on the confirmed customer/site crosswalk plus service date — which
is the point. If the invoice carried the operations key, the demo would be a join on a
shared column and would prove nothing.

## Deliberate controls

| Fixture | Purpose |
|---|---|
| Work order `00518774` | Completed, authorized, billable, $480, no matching invoice |
| Work order `00518801` | Already invoiced — must never become a candidate |
| Work order `00518830` | Authorization required but absent — must not be billable |
| Work order `00518902` | Still open — nothing owed yet |
| Missing `ar_ledger` crosswalk for `PDA-MDMONT-01` | Invoice `80000944-1753000000` references it, so that row quarantines into the identity queue |
| `invalid/` | One file per representative error code |

The `$480.00` figure is a narrative placeholder. It is not an estimate of anything and
must never be cited as one.
