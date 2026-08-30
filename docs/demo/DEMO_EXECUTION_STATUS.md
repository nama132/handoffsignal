# Demo-to-Outreach execution ledger

Governing document: `docs/CLAUDE_DEMO_TO_OUTREACH_EXECUTION_PLAN.md`.

Claude may set a phase to `complete_pending_owner_review`. **Only the owner's own
subsequent wording may be recorded as `owner_approved`** (plan §4.4). Allowed values:
`not_started` · `in_progress` · `complete_pending_owner_review` · `owner_approved` ·
`blocked`.

## Phase status

| Phase | Status | Approval wording | Files changed | Tests | Result | Commit |
| --- | --- | --- | --- | --- | --- | --- |
| 1A — Read-only preflight | complete_pending_owner_review | (§17 authorises 1A directly) | none — read-only | 859 pass / 0 fail, 88% | Manifest, exclusions and boundary verified. No stage, commit, remote or push. | — |
| 1B — Initial local commit | complete_pending_owner_review | "Go ahead, I Approve Phase 1B - Initiial local commit" | 230 staged and committed | 859 pass / 0 fail, 88%, run **from the staged state** | Baseline created. Local only; no remote exists. | `416a727` |
| 1B.1 — Ignore the excluded specification | complete_pending_owner_review | "Add .gitignore" | 1 (`.gitignore`) | n/a — ignore rule only | The governing specification can no longer be swept in by a blind `git add .`. It remains on disk and untracked. | `9dbfc2b` |
| 1C — Private remote | complete_pending_owner_review | "I also approve phase 1c - private remote" | none — remote configuration only | verified remote tree = 231 files, identical to local | Private repo `nama132/handoffsignal` created and verified private BEFORE the push. Branch `v2-commercial-cleaning` pushed with upstream tracking; remote SHA matches local. No tags, no other branch, no webhook, no deploy key, no environment, no autodeploy. Branch protection **unavailable** — GitHub Pro is required for rulesets on a private repository, and the repository was deliberately NOT made public to obtain it. | `37947a1` |
| 2 — Cockpit site scope | complete_pending_owner_review | "I Approve Phase 2 - Cockpit Site Scope" | 4 changed, 2 test modules added | 863 non-browser + 20 browser pass, 88% | F-N1 closed. Every number on `/app/` is now scoped by the same `effective_site_scope`. Proven non-vacuous: reverting the fix fails 5 tests. A four-lens audit of the whole defect class found no other live leak. A structural guard now classifies every selector. | `e16253f` |
| 2.1 — Authorization hardening | complete_pending_owner_review | "Open a narrowly scoped Phase 2.1 authorization-hardening correction" | 5 production files, 3 test modules | 898 non-browser + 20 browser pass | Reconciliation read scoped for supervisors; resolution authority reordered so it cannot confirm an id exists; `effective_site_scope` fails closed; the inert site-scoped entry retired; the brittle Phase 2 money assertions repaired. **Not pushed** pending owner review. | `cb5e2bd` |
| 2.2 — Service-obligation site resolution | complete_pending_owner_review | "Implement the service-obligation correction" | 1 production, 1 test module, ledger | 911 non-browser + 20 browser pass, 88% | Corrects a wrong claim in Phase 2.1: a service obligation reaches exactly one site through `contract_site`, so it IS site-addressable and was being hidden from supervisors who were entitled to it. All seven subject types are now represented in the fixture. **Not pushed** pending owner review. | `05390aa` |
| 3 — Four-stage cockpit | not_started | — | — | — | F-N2 reproduced during 1A. | — |
| 4 — Relative demo clock | not_started | — | — | — | F-N6 outstanding. | — |
| 5 — Secure demo accounts | not_started | — | — | — | F-N3 outstanding. **Hard gate before any hosting.** | — |
| 6 — Presenter package | not_started | — | — | — | — | — |
| 7 — Local rehearsal | not_started | — | — | — | — | — |
| 8A — Railway decision | not_started | — | — | — | Analysis only. Default outcome before Phase 9 evidence is **no-go**. | — |
| 8B — Synthetic demo deployment | not_started | — | — | — | Requires a separate authorisation phrase. | — |
| 9 — Interview outreach preparation | not_started | — | — | — | Preparation only; authorises no message to anyone. | — |

## Owner decisions recorded

| Date | Decision | Effect |
| --- | --- | --- |
| 2026-08-29 | Commit author is `Aman Abbas <amanabbas267@gmail.com>`, set with `git config --local` | Applies to this repository only; the global Git identity remains unset. |
| 2026-08-29 | Outward product and repository name is **HandoffSignal** | Plan §11.2 preserves `OpsRecovery V2` as the internal package/module/codename. **No broad code rename was performed**, and none is authorised as demo polish. |
| 2026-08-29 | Branch stays `v2-commercial-cleaning`, and the work stays **local** | No remote was created, added, or contacted in Phase 1B. |
| 2026-08-29 | `CLAUDE_V2_COMMERCIAL_CLEANING_MASTER_PROMPT.md` is **excluded** from the commit | The file remains untracked in the working tree. Consequence recorded below. |
| 2026-08-29 | The `.env.example` credential deviation is deferred to Phase 5 | See "Known deviations". |
| 2026-08-30 | Add a `.gitignore` rule for the excluded specification | Durable enforcement of the 2026-08-29 exclusion decision. Committed as `9dbfc2b`. |
| 2026-08-30 | **Create the private remote and push the branch** | Supersedes the earlier "keep it local" instruction. Phase 1C executed: `https://github.com/nama132/handoffsignal` (private). |
| 2026-08-30 | Approve Phase 2 — Cockpit Site Scope | Authorised immediately after Phase 1C. |

## Owner-directed scope clarification (plan §1)

The plan deliberately permits a narrow presenter package and local rehearsal **before**
outreach, to repair the Route B ordering defect that `docs/phases/PHASE_0A.md` identified —
an artifact that requires an interview to show. This clarification:

- does **not** authorise a new product journey, customer data, or public hosting;
- does **not** replace the original evidence gate, which still controls actual Railway
  deployment. Phase 8A is a decision document and its default outcome remains no-go.

The historical Phase 0A record stands unaltered and must not be rewritten as though this
clarification had always applied.

## Findings closed by Phase 2.1

| Finding | How it was closed |
| --- | --- |
| `open_reconciliation_issues` unscoped and site-addressable | The selector takes `limit_to_site_ids` and `include_financial`. A supervisor reads only non-financial issues whose subject resolves unambiguously to a granted site: **`site`**, **`work_order`** (single FK), and **`service_obligation`** (via `contract_site`, a single FK naming one site). `customer` and `contract` reach their sites through multi-valued relations and may cover several, so they stay hidden rather than being attributed by guess. Corrected in Phase 2.2 — the Phase 2.1 implementation and its ledger entry wrongly described obligations as ambiguous and hid them from every supervisor. |
| The badge count and the queue could disagree | Both surfaces now call one function, `open_reconciliation_issues_for(membership)`. A count the reader cannot open is itself a disclosure. |
| `reconciliation_resolve` was an existence oracle | Authority is decided **before** any lookup, the lookup is confined to the domains the member may resolve, and the final action check still runs before mutation. An unauthorized-domain id, another tenant's id, and an invented id now return byte-identical 404s. |
| `effective_site_scope` failed open | Tenant-wide is now an allowlist intersection over `TENANT_WIDE_ROLES`. Supervisor-only, supervisor-plus-unknown, and unknown-only memberships all narrow to explicit grants. |
| `SITE_SCOPED_ACTIONS` claimed an enforcement that did not exist | `RESOLVE_OPERATIONAL_RECONCILIATION` removed — `ACTION_ROLES` never granted it to a supervisor, so the site branch was unreachable and the entry was a lie in the matrix. No new mutation authority was granted to supervisors. `ACT_ON_CASE` stays, documented as the contract for the unbuilt operational journeys. |
| The Phase 2 money assertions were brittle | They searched the whole page for the digits `480`, which the freshness panel's elapsed age (now past 14808) contains. Every money assertion now parses a **named stage** out of the financial section and compares the exact token `$480.00`. A decoy test proves the old check would have been fooled and the new one is not. |

## Settled product-policy boundaries

Decided by the owner. These are **not** open questions, and they are not deferred work.
Recording them here so a later reviewer does not reopen a decision that has already been
made.

| Boundary | The decision |
| --- | --- |
| Accounting-record subjects are finance-only | `accounting_invoice` and `accounting_payment` reconciliation issues are never visible to a supervisor, at any site scope. Both subjects do have unambiguous site paths, so this is a policy boundary rather than a schema limit — and it holds **regardless of an operational-looking `field_group`**. An accounting record is finance-domain by virtue of what it is; a conflict on an invoice does not become operational because its field group reads `identity`. No selector branch is to be added for either. `TestAccountingSubjectsRemainHidden` asserts both that the paths would resolve and that a granted supervisor still does not see them, so the boundary cannot erode by accident. |

## Explicitly deferred, not closed

| Finding | Why it is deferred |
| --- | --- |
| `ACT_ON_CASE` site scoping is declared but unenforced | No call site passes `site_id`, and `transitions._roles_for` never returns SUPERVISOR for a revenue case. It is the contract for Journeys A and C, which are unbuilt. Enforcing it now would be writing authorization for a journey that does not exist. |
| Tenant-health visibility for a site-scoped reader | Source freshness, import batch history, identity-issue counts and detector-run status remain organization-wide for every role. Whether a supervisor should see tenant pipeline metadata at all is a product question, deliberately left open. |
| The member roster on case detail | `apps/exceptions/views.py` supplies the full organization membership list to the assign-owner control. It is people, not site business data. Untouched. |
| F-P6-12, F-P6-13, F-P6-14, F-N2, F-N4, F-N5, F-N6, F-N7, F-N9, F-N16 | Carried from earlier reviews; each belongs to a later numbered phase. |

## Known deviations carried past the baseline

1. **`.env.example` is not "names and safe comments only"** (plan §6.4 acceptance 4).
   Seven variables carry values; `DATABASE_URL` embeds a working local credential. It is
   loopback-only (`127.0.0.1:5433`) and byte-identical to the one `compose.yaml` already
   declares in the clear, so scrubbing one file without the others achieves nothing.
   Owner decision: fix all sites together in **Phase 5**, alongside F-N3.
2. **The master prompt is referenced but no longer present.** Three committed documents
   present it as the governing specification and source comments cite its line numbers. A
   fresh clone cannot resolve those references. No action taken; recorded so the choice
   stays deliberate.
3. **No `LICENSE` file, and `pyproject.toml` declares no `license` or `authors`** while
   configuring a distributable wheel. Inbound licensing is clean (every dependency resolves
   from PyPI with hashes; no vendored source). Outbound paperwork only.
4. **Three committed documents state as present-tense fact that the repository has no
   commits.** This commit falsifies them. To be corrected when those documents are next
   touched.
5. **The baseline branch has no force-push or deletion protection.** GitHub requires a Pro
   plan for rulesets on a private repository, and making the repository public to obtain
   protection would be a worse trade. Until the plan changes, the branch's integrity rests
   on discipline: never force push, never rewrite history (plan section 4.2).

## Verification evidence for the baseline

Run immediately before the commit, from the staged state:

| Command | Result |
| --- | --- |
| `manage.py check` | no issues (0 silenced) |
| `makemigrations --check --dry-run` | no changes |
| `ruff format --check .` / `ruff check .` | 165 formatted / all passed |
| `mypy apps config` | no issues, 100 files |
| `pytest -m "not worker_integration and not browser"` | **839 passed** |
| `pytest -m browser` | **20 passed** (real Chromium) |
| `coverage report --fail-under=85` | **88%** |

`make test-worker-integration` exits 0 but collects **no tests** (F-N7). Its success is
not worker validation and must never be reported as such.

A pre-commit audit ran five independent lenses over the 230 staged files — secrets beyond
regex, real-person/prospect data, financial-language honesty, tenant-isolation invariants,
and files that do not belong in permanent history — each adversarially re-verified, plus a
completeness critic. **34 findings confirmed, 0 commit blockers.** No live credential, no
real customer or prospect data, and no reachable cross-tenant leak to an unauthorised
reader was found. Findings are recorded in the Phase 1B report and remain open for their
assigned phases.

## Boundary statement

V1 at `shiftcare-prod` is `main` @ `a6cc7d5` with **0 dirty entries**, unchanged throughout.
No denylisted file was opened. No live service was contacted. No message was sent. No
Railway resource was inspected or provisioned. All data is synthetic.
