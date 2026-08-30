# Phase 2 — Tenant identity, RBAC, and operational primitives

**Approval:** `Approve Phase 2`  **Status:** complete, pending review

## What the owner can now do

Two synthetic organizations exist with full tenant isolation. A user signed into one sees
only their own organization's data; a direct URL carrying the other's **real** UUID
returns 404 and leaks nothing. All five roles are enforced server-side and deny-by-default,
and a site supervisor sees only the sites explicitly granted to them.

## What was built

19 models across three applications, plus a `dashboard` application with no models.

| Application | Models |
|---|---|
| `organizations` | `User`, `Organization`, `Membership`, `MembershipRoleGrant`, `MembershipSiteGrant` |
| `operations` | `CustomerAccount`, `Site`, `Contract`, `ContractSite`, `ServiceObligation`, `WorkOrder`, `AccountingInvoice`, `AccountingPayment` |
| `ingestion` | `DataSource`, `ExternalEntityReference`, `IdentityResolutionIssue`, `SourcePrecedenceRule`, `SourcePrecedenceEntry`, `ReconciliationIssue` |

Also: a declarative permission matrix, a policy service, tenant middleware, scoped
selectors, organization selection, a tenant shell, and two guarded management commands.

## How authorization works

The section 9.3 table is transcribed into `apps/organizations/roles.py` as **data**, not
logic. `policy.py` interprets it. A permission question is answered by reading one table
rather than tracing conditionals through views.

Two rules are structural:

- **Deny by default.** `check()` starts from denial; only an explicit matrix entry moves
  it. There is no branch returning "allowed" for an unknown action, role, or grant.
- **Visibility is not authority.** An identity or reconciliation decision crossing the
  operational/financial boundary requires the owner. Broader power is never inferred
  from being able to see a record.

Site scoping deserves care. `effective_site_scope()` returns:

- `None` — tenant-wide; apply no site filter.
- a non-empty set — exactly those sites.
- an **empty set** — no sites at all.

The empty set must never collapse to `None`. Returning `None` for a supervisor with no
grants would silently widen access to the whole tenant — which is precisely the bug this
function exists to prevent, and precisely the bug that was found in review (below).

There is deliberately **no wildcard site-grant field**. A test asserts no such field
exists, because adding one would make the deny-by-default guarantee unprovable.

## Deliberate omissions

Beyond the Journey A and C models, `SiteOperationalRule` is **not built** even though the
Phase 2 deliverable list names it. Every one of its fields — grace periods, deficiency
SLAs, weekly-hours thresholds, workweek boundaries, availability policy — is an
attendance or quality input. Journey B's delay comes from
`ServiceObligation.uninvoiced_delay_days` instead.

Two sequencing items were resolved rather than papered over: `IdentityResolutionIssue`
and `ReconciliationIssue` are Phase 2 deliverables but reference `SourceRecordVersion`, a
Phase 3 model. They shipped without that link; Phase 3 added it.

## Database invariants

Constraints carry the weight, because a service can be bypassed and a constraint cannot:

- Organization-scoped uniqueness everywhere — **never global**. Two tenants may both have
  a customer named "Meridian Property Group".
- `ExternalEntityReference` conditional typed-target check: `confirmed` has exactly one
  target, `unresolved`/`rejected` have zero, `superseded` has zero or one.
- Partial unique index on non-superseded identity rows, so history accumulates while only
  one mapping is ever current.
- Partial unique on active role grants, so a revoked grant can coexist with a re-grant.
- Non-overlapping effective periods on `ContractSite` (service-level; see limitations).
- `Decimal` money with check constraints forbidding negatives. **Unknown is NULL, never
  zero.**
- A completed work order cannot exist without a completion timestamp.

`match_method` has no fuzzy or AI value, so auto-confirmation by similarity is
structurally impossible.

## Evidence

| Command | Result |
|---|---|
| `manage.py migrate` (fresh database) | 21 migrations applied |
| `ruff` / `mypy` | clean |
| `pytest` | **488 passed** |
| `coverage --fail-under=85` | **96%** |
| `pip-audit` | no known vulnerabilities |

Live verification: Atlas and Beacon owners each saw only their own organization; the
Atlas owner posting Beacon's **real** organization UUID received **404**, indistinguishable
from a nonexistent UUID; a POST with no CSRF token received 403 and wrote nothing; a
supervisor granted one of three sites saw only that one, while an operations manager with
zero grants correctly saw all three.

## Three blocking defects found by adversarial review, and fixed

A design-and-verify pass over the *shipped* code found three real defects. Full detail in
`docs/PHASE2_REVIEW_FINDINGS.md`.

1. **Cross-tenant hole.** `SourcePrecedenceEntry` was a plain `models.Model` with no
   organization column. Nothing stopped a join row linking a precedence rule in one
   tenant to a data source in another. Now tenant-scoped and same-tenant validated, with
   the database enforcing `NOT NULL`. A **generic guard test** now fails for any
   tenant-owned model lacking a non-null organization, so this class of bug cannot recur
   silently.
2. **Tenancy hole.** The shell scoped only by organization, so a supervisor with **zero
   site grants saw every site and customer in the tenant.** Site scope is now resolved by
   the policy layer and threaded through six selectors.
3. **Vacuous test.** `test_supervisor_with_no_grants_shows_zero_sites` asserted that an
   explanatory *sentence* appeared, not that site names were absent. It passed *because*
   of defect 2. Rewritten to assert rendered identifiers, and **proven non-vacuous**:
   reverting the fix makes two of the new tests fail.

A fourth issue was found in the fixtures themselves: `ContractSiteFactory` generated
cross-tenant object graphs, because its contract and site each created their own
customer and therefore their own organization. Any isolation test built on it was
operating on data that was never in one tenant to begin with. Fixed, with meta-tests
asserting every factory produces a coherent single-tenant graph.

## Known limitations

1. Three review findings remain open in `docs/PHASE2_REVIEW_FINDINGS.md`: the seed guard
   permits `APP_ENV=test` where the specification names local/demo; role-matrix tests
   should parametrize from the shipped `Action` enum; the stale-session-hint auto-select
   should be documented rather than silent.
2. No database **exclusion constraint** for overlapping effective periods. Overlap is
   rejected in `clean()` and tested; a PostgreSQL exclusion constraint needs the
   `btree_gist` extension and a generated range column.
3. Same-tenant foreign keys are enforced in `clean()` and by tests, not by a database
   constraint — Django 5.2 cannot express a cross-row tenant predicate. This is what the
   specification permits.
4. No login rate limiting, no MFA.
