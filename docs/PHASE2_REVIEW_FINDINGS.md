# Phase 2 — adversarial review findings

Source: 10-agent design+verify pass, 2026-08-27. These are defects found in **shipped
Phase 2 code**, not in the design proposal.

## Resolved

| # | Severity | Finding | Resolution |
|---|---|---|---|
| 1 | BLOCKING | `SourcePrecedenceEntry` was a plain `models.Model`: no `organization`, no same-tenant validation. Nothing stopped an entry joining a rule in org A to a `DataSource` in org B — a cross-tenant edge through a join table. | Now a `TenantScopedModel` with `assert_same_organization(self, "rule", "source")`. The database enforces `organization_id NOT NULL`. Covered by `TestSourcePrecedenceEntryIsolation` plus a generic guard, `TestEveryTenantOwnedModelIsScoped`, that fails for **any** tenant-owned model lacking a non-null organization — so this class of bug cannot recur silently. |
| 2 | BLOCKING | Tenancy hole: the dashboard scoped only by organization, so a supervisor with zero site grants saw every site and customer in the tenant. | Added `policy.effective_site_scope()`, which returns `None` for tenant-wide roles and an **empty set** — never `None` — for a supervisor with no grants. Threaded through six selectors; the view passes it verbatim. Verified live: a supervisor granted 1 of Atlas's 3 sites sees only that one, while an operations manager with zero grants still sees all three. |
| 3 | BLOCKING | Vacuous test: `test_supervisor_with_no_grants_shows_zero_sites` asserted only that an explanatory sentence appeared. It passed while the page listed every site. | Replaced with four tests asserting rendered identifiers (granted site present, ungranted site and its customer absent), plus positive controls for tenant-wide roles and role union. **Proven non-vacuous:** reverting the fix makes 2 of them fail; restoring it makes them pass. |

## Still open

| # | Severity | Finding |
|---|---|---|
| 4 | BLOCKING | `_guards.py` `LOCAL_ENVIRONMENTS` permits `test`, which §31 (line 1978) does not sanction — it names local/demo. Also missing a `DEMO_MODE` gate. Note: the test suite currently relies on `test` being permitted, so narrowing this requires the command tests to set `APP_ENV=local` first. |
| 5 | IMPORTANT | Role-matrix tests should be parametrized from the shipped 16-code `Action` enum with each code citing the §9.3 row it decomposes, rather than from the 11 spec rows. |
| 7 | NOTE | `resolve_active_membership` pops a stale session hint then auto-selects the sole membership. Benign for a single-membership user, but should be documented rather than silent. |
| 8 | NOTE | Money constants confirmed consistent (`MONEY_*` 14,4 / `RATE_*` 12,4). `approved_hours` is Decimal(8,2) — a quantity, not money. No change needed; recorded for the record. |

Finding 6 (site scope missing from four selectors) was resolved as part of finding 2.

## Confirmed sound by the verifiers

- `apps/organizations/policy.py::check` implements the correct union/site-narrowing
  reading of §9.3 line 382 (`tenant_wide = granting - {SUPERVISOR}`).
- `common.TenantScopedModel` and `common.assert_same_organization` are the right single
  idioms; the design's proposed duplicate base class was rejected in their favour.
