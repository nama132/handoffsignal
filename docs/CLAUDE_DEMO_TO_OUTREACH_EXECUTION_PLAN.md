# HandoffSignal V2 — Claude Demo-to-Outreach Execution Plan

Status: execution plan only; no phase in this document is approved merely because this
file exists.

Repository:

    /Users/amanabbas/Desktop/Project AI/V2/ops-recovery-v2

Primary evidence:

- docs/PHASE_0_TO_6_BUILD_HANDOFF.md
- docs/BUILD_STATUS.md
- docs/phases/PHASE_0A.md
- docs/PHASE2_REVIEW_FINDINGS.md
- docs/PHASE4_REVIEW_FINDINGS.md
- docs/PHASE6_REVIEW_FINDINGS.md
- docs/adr/0005-railway-separate-project-and-service-layout.md
- CLAUDE_V2_COMMERCIAL_CLEANING_MASTER_PROMPT.md
- ../ops-recovery-go-to-market/OUTREACH_MARKETING_PROGRAM.md
- ../ops-recovery-go-to-market/FIELD_ASSETS.md
- ../ops-recovery-go-to-market/DMV_PROSPECT_RESEARCH.md
- ../ops-recovery-go-to-market/outputs/2026-08-27/DMV_PROSPECT_DATABASE.xlsx

## 1. Purpose

This document tells Claude Code how to move the verified Route B implementation from its
current Phase 6 state to:

1. a recoverable, version-controlled repository;
2. a correctly scoped and truthful cockpit;
3. a reliable synthetic demonstration;
4. a complete presenter package and fallback;
5. an evidence-based Railway decision; and
6. a controlled founder-led interview outreach program.

The order is deliberate. Do not market or host a demo that has a known tenant-scope
failure. Do not begin a real-data pilot from this plan. Do not expand into Journey A,
Journey C, Phase 5, new CSV contracts, vendor integrations, source-system write-back,
messaging, or automated invoicing.

Scope clarification relative to docs/phases/PHASE_0A.md:

- Phase 0A originally blocked Phase 7 polish and Phase 8 hosting until five interviews
  plus a sanitized source walkthrough. It also records that this ordering leaves a local
  artifact that is difficult to present before an interview exists.
- The owner's later instruction deliberately permits a narrow presenter package and local
  rehearsal before outreach to repair that ordering problem. It does not authorize a new
  product journey, customer data, or public hosting.
- The original evidence gate still controls actual Railway deployment. Phase 8A is a
  decision document; the default outcome before Phase 9 evidence is no-go.
- Claude must record this owner-directed scope clarification in the execution ledger and
  must not rewrite the historical Phase 0A record as though it never existed.

## 2. Verified starting point

Treat the following as the baseline to re-check, not assumptions to repeat:

- Branch: v2-commercial-cleaning.
- The repository currently has no commits, no tracked files, and no configured remote.
- The current inventory contains 229 files; Claude must re-count immediately before the
  baseline because this is a point-in-time observation.
- The Route B recovery ledger is implemented through Phase 6.
- The automated suite was reported as 839 non-browser tests plus 20 real-browser tests.
- The first post-login cockpit has a confirmed site-scope defect:
  - a supervisor with zero site grants sees Open cases: 0;
  - the same screen exposes the organization-wide 480-dollar candidate amount;
  - the same screen exposes an organization-wide Medium: 1 severity count.
- The cockpit still displays three Phase 4 messages saying financial stages are not
  available, even though Phase 6 implements those stages.
- The demo loader defaults to a fixed 2026-08-20 as-of time, so freshness becomes stale
  as wall-clock time advances.
- seed_demo contains a shared password in source and can run when APP_ENV is demo.
- No worker_integration test is registered.
- No Railway resource has been provisioned for V2.
- All existing data is synthetic.
- The owner-selected outward product name is HandoffSignal. OpsRecovery V2 remains the
  internal codename until a deliberate presentation-layer rename is approved.

## 3. Non-negotiable product truths

Claude must preserve these invariants in every phase:

1. The product is a read-only overlay toward customer source systems.
2. It never creates, posts, sends, or modifies an invoice.
3. It never writes back to an operations or accounting system.
4. Candidate, invoice-ready, confirmed invoiced, and confirmed collected are four
   independent facts. They are never added together.
5. A candidate amount is not recovered revenue.
6. Finance approval is required before an invoice-ready export.
7. Invoice absence is evaluated only after completion, authorization, rate basis,
   identity, coverage, freshness, and duplicate controls.
8. Empty site scope means no sites. It must never be treated as tenant-wide scope.
9. A foreign tenant identifier must not become an existence oracle.
10. Every demo company, site, person, identifier, and amount is fictional.
11. Journey A, Journey C, and Phase 5 remain unbuilt.
12. EXTERNAL_ACTIONS_ENABLED remains false.

## 4. Execution contract for Claude

### 4.1 Sequential, approval-gated operation

Claude must execute only one numbered phase at a time.

For every phase:

1. Read this entire plan and the phase-specific evidence before editing.
2. Inspect the current repository state; do not rely on an earlier status report.
3. State the files expected to change.
4. Implement only the approved phase.
5. Run the phase-specific tests and the proportional regression suite.
6. Review the final diff for scope, security, tenant isolation, financial language, and
   accidental secrets.
7. Update the phase ledger described below.
8. Report results, unresolved findings, and exact Git status.
9. Stop. Do not begin the next phase without the owner’s explicit approval.

Keep each completed implementation phase in its own focused local commit after the owner
reviews the phase result. Never combine Steps 2–7 into one large commit, amend the Phase 1
baseline, or push a phase merely because it was committed. A push remains a separate
external-action confirmation.

Use these approval phrases:

- Approve Phase 1 — Repository Protection
- Approve Phase 2 — Cockpit Site Scope
- Approve Phase 3 — Four-Stage Cockpit
- Approve Phase 4 — Relative Demo Clock
- Approve Phase 5 — Secure Demo Accounts
- Approve Phase 6 — Presenter Package
- Approve Phase 7 — Local Rehearsal
- Approve Phase 8A — Railway Decision
- Authorize Railway Phase 8B — Synthetic Demo Deployment
- Approve Phase 9 — Interview Outreach Preparation

Approval of Phase 8A is not authorization to mutate Railway. Approval of Phase 9 is not
authorization to send email, call, message, publish, register for an event, or upload
prospect data.

### 4.2 Destructive and external actions

Claude must obtain action-time confirmation before:

- creating or deleting a remote repository;
- adding or changing a Git remote;
- pushing;
- rewriting history;
- rotating or entering a credential;
- provisioning, modifying, or deleting Railway resources;
- changing Namecheap or other DNS records;
- adding a public domain;
- sending an email or message;
- publishing a landing page, screenshot, video, result, logo, or customer claim;
- registering or paying for an event.

Never use force push, destructive reset, broad recursive deletion, or volume deletion.
Never run docker compose down -v.

### 4.3 File and data safety

- Do not read or print .env, credentials, keys, database dumps, or secret values.
- Environment-variable names may be documented; values may not.
- Do not upload or ingest real customer or prospect data.
- Do not place passwords in source, documentation, shell history, fixtures, screenshots,
  videos, logs, or commits.
- Do not use a purchased list or scrape personal contact information.
- Preserve unrelated owner changes.

### 4.4 Required execution ledger

Create docs/demo/DEMO_EXECUTION_STATUS.md in the first code-changing phase. Maintain:

| Phase | Status | Approval wording | Files changed | Tests | Result | Commit |
| --- | --- | --- | --- | --- | --- | --- |

Allowed status values:

- not_started
- in_progress
- complete_pending_owner_review
- owner_approved
- blocked

Claude may mark complete_pending_owner_review. Only the owner’s subsequent wording may
be recorded as owner_approved.

## 5. Global verification commands

Use the project’s locked environment and documented commands. Do not upgrade packages as
part of these phases.

Minimum engineering gate:

~~~bash
uv run python manage.py check
uv run python manage.py makemigrations --check --dry-run
uv run ruff format --check .
uv run ruff check .
uv run mypy apps config
uv run pytest -q -m "not worker_integration and not browser"
uv run pytest -q -m browser
uv run coverage run -m pytest -m "not worker_integration"
uv run coverage report --fail-under=85
~~~

Run pip-audit when dependency files change or before a hosted-deployment decision.

The worker target currently collects no tests. Do not present its successful exit as
worker validation:

~~~bash
make test-worker-integration
~~~

## 6. Phase 1 — Protect the repository

### 6.1 Objective

Create a recoverable Phase 6 baseline without capturing credentials, build artifacts,
databases, virtual environments, generated caches, or unrelated repositories.

### 6.2 Why this phase comes first

Seven completed build phases currently exist as untracked files on one machine. Any
subsequent fix is unsafe until the baseline can be recovered and compared.

### 6.3 Phase 1A — Read-only preflight

Tasks:

1. Confirm the repository top-level path is exactly ops-recovery-v2.
2. Record the current branch, status, remotes, ignored files, and file counts.
3. Confirm there is still no HEAD commit.
4. Confirm V1 and the two backup repositories are outside this Git top level.
5. Check for nested Git repositories and symlinks that resolve outside the V2 repository.
6. Inspect .gitignore and .dockerignore without opening secret-bearing files.
7. Enumerate the intended first-commit files.
8. Identify oversized, generated, binary, or otherwise unexpected files.
9. Confirm .venv, caches, coverage files, local databases, environment files, credentials,
   keys, recordings, and temporary exports will not be staged.
10. If a secret-scanning tool is already installed, run it in no-write mode. If none is
   available, record the missing reproducible control; do not install one without
   approval.
11. Scan candidate paths for credential-shaped content without printing matched values.
    Treat the known fictional demo password as a code-security defect that Phase 5 must
    remove, not as authority to ignore any other finding.
12. Run the minimum engineering gate before staging.

Required report:

- proposed repository display name;
- proposed private remote provider;
- exact proposed remote URL, if already supplied by the owner;
- proposed Git commit-author name and email;
- explicit first-commit manifest;
- excluded-file summary;
- tests and failures;
- any credential-shaped or oversized-file concern, reported without printing a value.

Stop gate:

Do not stage, commit, create a remote, or push during Phase 1A.

### 6.4 Phase 1B — Initial local commit

This phase requires explicit owner approval after Phase 1A.

Tasks:

1. Stage only the explicit reviewed manifest. Do not use a blind broad add operation.
2. Inspect staged names and the staged diff.
3. Fail the phase if any of the following is staged:
   - .env other than .env.example;
   - credentials or private keys;
   - database files;
   - .venv or caches;
   - coverage artifacts;
   - generated browser binaries;
   - real prospect/customer data;
   - files outside ops-recovery-v2.
4. Confirm .env.example contains names and safe comments only.
5. Run the minimum engineering gate from the staged state.
   - A plausible live secret, private key, real customer data, or unexplained credential
     blocks the commit.
   - A reproducible pre-existing non-security failure must be documented and shown to the
     owner. It does not silently disappear and does not automatically justify leaving the
     only copy unprotected; the owner decides whether to preserve the known baseline or
     require repair first.
6. Create one baseline commit with a neutral message such as:

       chore: establish V2 Phase 6 baseline

7. Record the commit identifier in docs/demo/DEMO_EXECUTION_STATUS.md.
8. Do not amend or rewrite the baseline after reporting it.

Acceptance criteria:

- git log contains exactly the intended new baseline.
- git status is clean except for explicitly documented owner work.
- No ignored or secret-bearing file is tracked.
- Full engineering gate passes, or the owner has explicitly approved preserving a
  reproducible pre-existing non-security failure in the baseline.
- Any approved pre-existing failure is recorded in the execution ledger with a
  remediation item; no new failure was introduced.

Rollback:

- Before commit: unstage only the reviewed staged paths.
- After commit: do not reset or amend automatically. Report the issue and ask the owner.

### 6.5 Phase 1C — Private remote

This phase requires the owner to provide or approve:

- the provider;
- exact private repository name;
- exact remote URL or permission to create that named private repository;
- confirmation of the account/organization that should own it;
- confirmation of the commit-author identity and whether the branch remains
  v2-commercial-cleaning or is deliberately renamed.

Recommended default: a dedicated private GitHub repository for V2. This is a
recommendation, not an assumption.

Tasks after authorization:

1. Verify the remote repository is private.
2. Add it as origin only if no origin exists.
3. Display the remote URL without credentials embedded in it.
4. Push v2-commercial-cleaning with upstream tracking.
5. Do not push V1, another branch, tags, or history from any other repository.
6. Verify the remote branch resolves to the same commit.
7. Do not enable deployment hooks or Railway autodeploy.
8. If supported, prevent force pushes and branch deletion. Do not require nonexistent CI
   checks before CI exists.

Acceptance criteria:

- A fresh clone can reproduce the file tree.
- The private remote contains the approved baseline commit.
- No secret or generated local artifact is present.
- V1 remains untouched.

Phase 1 completion evidence:

- local commit identifier;
- remote branch identifier;
- clean status;
- test results;
- secret-control limitation, if a scanner is still not configured.

## 7. Phase 2 — Correct cockpit site scoping

### 7.1 Objective

Ensure every number on the first post-login screen is constrained to the viewer’s
effective site scope, including the empty-set case.

### 7.2 Confirmed defect

apps/exceptions/views.py currently scopes open_cases but calls organization-wide
open_case_counts and the Phase 4 organization-wide financial stage selector. This creates
contradictory and unauthorized aggregates for a supervisor with zero site grants.

### 7.3 Expected implementation surface

Likely files:

- apps/exceptions/selectors.py
- apps/exceptions/views.py
- apps/recovery/selectors.py only if a reusable shape is missing
- tests/test_case_views.py
- tests/test_recovery_ledger.py
- one browser or view-level tenancy test
- docs/demo/DEMO_EXECUTION_STATUS.md

Do not broaden the change into a permission-system rewrite.

### 7.4 Tasks

1. Add an optional limit_to_site_ids parameter to open_case_counts.
2. Apply the filter whenever the parameter is not None.
3. Preserve the three-valued scope contract:
   - None means tenant-wide;
   - a non-empty set means those sites;
   - an empty set means no sites.
4. In cockpit, calculate site_scope once with effective_site_scope.
5. Pass site_scope to:
   - cases_for_organization;
   - open_case_counts;
   - the Phase 6 recovery-stage totals.
6. Replace the cockpit’s call to apps.exceptions.services.financial.stage_totals with the
   site-scoped Phase 6 selector in apps.recovery.selectors.
7. Keep the existing financial presentation helper where case_detail still relies on it;
   do not break an unrelated money path while changing the cockpit import.
8. Quantize displayed Decimal values at the presentation boundary only.
9. Do not change detector, approval, export, or accounting rules.
10. Audit all money-rendering views and severity/count surfaces for the same defect class.
    Organization-level source-health, identity-issue, and detector-run widgets are not
    directly site-addressable; do not silently redesign them. If supervisors should not
    see tenant-health metadata, stop for an explicit product decision.
11. Add a regression test that would fail if any first-screen case count or money total
    widens an empty site scope.

### 7.5 Required tests

At minimum:

1. Owner sees the one Atlas case and its candidate value.
2. Finance reviewer sees the one Atlas case and its candidate value.
3. Supervisor with zero grants sees:
   - Open cases: 0;
   - every severity count as zero;
   - no 480-dollar amount;
   - no candidate, invoice-ready, invoiced, or collected amount from an ungranted site.
4. Supervisor granted the Meridian site sees only Meridian data.
5. Supervisor granted a different site sees no Meridian money or count.
6. Empty set never behaves like None.
7. Beacon user cannot infer Atlas counts or money.
8. Ledger scoping remains unchanged and passing.
9. Tenant-wide roles remain tenant-wide even if they happen to have site grants.

Run:

~~~bash
uv run pytest -q tests/test_case_views.py tests/test_recovery_ledger.py tests/test_permissions.py
uv run pytest -q tests/test_tenancy.py
uv run pytest -q -m browser
~~~

Then run the global engineering gate.

### 7.6 Acceptance criteria

- Open-case headline, severity tiles, recent cases, and financial stages agree for every
  role and site scope.
- No unauthorized amount or count appears in HTML.
- A direct selector test covers empty, limited, and tenant-wide scopes.
- A rendered-view test covers the known supervisor-zero-grants reproduction.
- No authorization was weakened.

Stop conditions:

- Any foreign-tenant information becomes distinguishable.
- A test is weakened or removed to make the fix pass.
- The fix requires changing the meaning of None or the empty set.
- Financial totals diverge from the recovery ledger for the same scope.

## 8. Phase 3 — Replace obsolete cockpit financial stages

### 8.1 Objective

Make the first screen accurately present Phase 6’s four independent financial facts.

### 8.2 Expected implementation surface

- apps/exceptions/views.py
- templates/exceptions/cockpit.html
- possibly a small shared presentation helper
- tests/test_case_views.py
- browser tests covering pre- and post-approval state
- docs/demo/DEMO_EXECUTION_STATUS.md

### 8.3 Presentation requirements

The cockpit must display:

1. Candidate value — may be billable; not recovered revenue.
2. Invoice-ready value — reviewed and approved for handoff.
3. Confirmed invoiced — accounting source only.
4. Confirmed collected — accounting source only.

Rules:

- Use none when a stage has no evidence; do not imply a verified zero.
- Never add the four numbers.
- Withhold totals when visible rows span multiple currencies.
- Explain when disputes exclude items from confirmed stages.
- Do not hard-code the statement that Phase 6 is unavailable.
- Keep financial language consistent with templates/recovery/ledger.html.
- Do not claim AI, automation, real-time operation, integrations, or recovered revenue.

### 8.4 Tasks

1. Reuse the Phase 6 selector rather than duplicating financial calculations in a view or
   template.
2. Convert display values to cents only after calculation.
3. Render all four stages from the passed values.
4. Add mixed-currency and dispute explanations when applicable.
5. Update the test that currently asserts three obsolete messages.
6. Add a pre-approval view test:
   - candidate is 480;
   - other stages are none.
7. Add a post-approval view test:
   - candidate remains 480;
   - invoice-ready becomes 480;
   - confirmed stages remain none.
8. Add accounting-confirmation tests only by using existing supported services; do not
   invent a shortcut in test setup.
9. Check the page at 375 pixels and with a keyboard-only path.
10. Update the README’s current-state summary from Phase 1 to Phase 6, without rewriting
    the architecture or expanding scope.

Technical note:

- apps.recovery.selectors.stage_totals returns four-decimal Decimals. The cockpit must
  format them to two decimals just as the ledger does, or the same value will appear with
  contradictory precision.
- The Phase 6 selector includes recovery items beyond only open exception cases. This is
  the intended handoff recommendation, but Claude must state and test the semantic change
  rather than treating it as a cosmetic template edit.

### 8.5 Acceptance criteria

- A first-time viewer can correctly explain all four stages from the cockpit.
- Cockpit and recovery ledger show the same stage values for the same actor and scope.
- The phrase not available in this phase no longer appears for built Phase 6 stages.
- No single recovered-revenue total exists.
- A posted invoice and payment, when created through existing accounting derivation,
  populate confirmed invoiced and confirmed collected independently; neither is copied
  from candidate or approval data.
- Existing browser and financial-safety tests pass.

## 9. Phase 4 — Make the demo clock relative and truthful

### 9.1 Objective

After a deliberate demo reset, the synthetic sources should display a coherent, fresh
observation time without weakening real freshness checks.

### 9.2 Constraint

Do not change production freshness thresholds merely to make a fixture look fresh. Change
the demo observation clock, not the business rule.

### 9.3 Expected implementation surface

- apps/recovery/management/commands/demo_load.py
- tests for demo_load and freshness rendering
- possibly config environment parsing already used for DEMO_AS_OF
- README or docs/runbooks/demo.md
- docs/demo/DEMO_EXECUTION_STATUS.md

Avoid rewriting the four CSV contracts in this phase.

### 9.4 Tasks

1. Change demo_load so an explicit --as-of remains deterministic and authoritative.
2. When --as-of is omitted:
   - prefer an approved DEMO_AS_OF configuration when present;
   - otherwise use timezone-aware current time in local/demo only;
   - remove microseconds for readable output.
3. Continue rejecting a naive datetime.
4. Continue rejecting demo clock controls in pilot/production settings.
5. Pass the resolved as-of value into ImportBatch observations and the reconciliation run.
6. Rewrite each imported CSV row's source_as_of_at field in memory where that field
   exists, so row provenance agrees with the batch observation. Never rewrite the
   committed fixture files on disk.
7. Do not mutate the detector’s source-freshness rule.
8. Ensure coverage declarations remain coherent for the fixture’s service dates and the
   resolved observation time.
9. Document that make demo-reset must run before a presentation.
10. Record the resolved synthetic as-of time in command output without exposing secrets.
11. Hash every committed fixture before and after demo_load in a test; every hash must be
    byte-identical.
12. Add a regression test using a frozen or injected clock; do not make a wall-clock
    assertion that flakes around midnight.

### 9.5 Required scenarios

- Explicit --as-of reproduces the same deterministic case and amount.
- Omitted --as-of yields fresh operations and accounting sources immediately after reset.
- A deliberately old explicit --as-of still shows stale when compared with a later
  injected now; the freshness control must remain real.
- A naive --as-of is rejected.
- Pilot settings reject demo-only clock behavior.
- Three consecutive demo resets produce one case and the same narrative amount.
- DataSource, ImportBatch, and row-level source_as_of_at values agree for sources that
  carry the field.

### 9.6 Acceptance criteria

- Immediately after make demo-reset, no source is stale. Decision-dependent operations
  and accounting feeds are fresh; a source whose maximum age is intentionally undefined,
  such as the identity map, remains unknown rather than being falsely labeled fresh.
- The detector still creates exactly one case and skips the same three negative controls.
- The 480-dollar amount and identity-control story do not change.
- Real freshness semantics remain untouched.
- Historical service, authorization, invoice, payment, and contract dates remain fixed.
  If this eventually changes the case's severity band, do not silently shift every
  business date; stop and design a separate coherent story-date transformation.

## 10. Phase 5 — Secure demo account creation

### 10.1 Objective

Remove credentials from source and ensure synthetic accounts cannot become publicly
reachable with a known default.

### 10.2 Security posture

Local convenience is not a reason to ship a password. Hosted synthetic data is still an
internet-facing authentication surface.

### 10.3 Expected implementation surface

- apps/organizations/management/commands/seed_demo.py
- apps/organizations/management/commands/_guards.py
- apps/organizations/management/commands/create_owner.py
- apps/recovery/management/commands/demo_load.py
- apps/ingestion/management/commands/generate_sample_data.py
- config/env.py and settings only if a new variable name is necessary
- .env.example for names and safe comments only
- tests for command guards and credential handling
- Makefile and local/demo runbook
- docs/demo/DEMO_EXECUTION_STATUS.md

### 10.4 Required design

Claude must propose the final account design before implementing it. The preferred
minimal design is:

1. Remove the module-level shared password.
2. Create demo users with unusable passwords by default.
3. Make the destructive synthetic-data commands seed_demo, demo_load, and
   generate_sample_data require both APP_ENV=local and DEMO_MODE=true. They must refuse
   test, demo, staging, pilot, and production even if DEMO_MODE is true.
4. Give create_owner a separate non-destructive bootstrap guard; preserve its default of
   creating an unusable password.
5. For local role-switch rehearsal only, support an explicit non-echoing interactive
   prompt, validate and confirm the password, and never accept it through a command-line
   argument, source file, or printed output.
6. On every seed/reset, actively invalidate the six existing synthetic users before an
   optional local interactive credential is applied. seed_demo --reset deletes
   memberships and organizations but not User rows; removing the constant alone would
   leave hashes made from the legacy known password usable.
7. Defer hosted-account provisioning to a separately designed Railway security phase.
   A deployed environment must never run these destructive local seed/reset commands.
8. Do not print or log any credential.

If the preferred design conflicts with current configuration rules, write a short ADR
before changing the security boundary.

### 10.5 Tasks

1. Remove DEMO_PASSWORD from source.
2. Split the command guards as described above. Do not let APP_ENV=test define a
   production boundary or regain permission merely to simplify tests.
3. Preserve isolated, idempotent synthetic tenant creation.
4. Add tests for:
   - refusal in production;
   - refusal in pilot;
   - refusal in test, demo, and staging;
   - refusal in local when DEMO_MODE is false;
   - success only in local when DEMO_MODE is true;
   - unusable password by default;
   - invalidation of a pre-existing usable synthetic-user password;
   - weak password and prompt mismatch failing without partial writes;
   - valid prompted password authenticating locally;
   - no credential in stdout or logs;
   - reset limited to the two named synthetic tenants.
5. Remove browser tests' dependency on the application password constant. Test fixtures
   may create a test-only password after seeding without weakening runtime guards.
6. Search documentation, fixtures, and tests for credential copies.
7. Update make demo-reset or add a clearly named local setup target so role-switching
   remains usable without checking a password into the repository.
8. Do not expose seed/reset through HTTP or build public signup, password reset, email
   invitation, or user self-service.

### 10.6 Acceptance criteria

- No reusable demo password exists in tracked text.
- seed_demo and other destructive fixture commands refuse every environment except local
  plus DEMO_MODE=true.
- Existing hashes created from the old shared value do not survive the next seed/reset.
- Default seeding creates unusable credentials; a local operator can deliberately create
  validated credentials through a non-echoing prompt.
- Logs and command output contain no credential.
- Local demo reset remains documented and repeatable.
- Full authentication, authorization, and browser suites pass.

Stop conditions:

- A proposed solution stores a password in Git, docs, logs, screenshots, or shell
  history.
- The guard becomes a single easily forgotten flag.
- Production or pilot can invoke reset.
- APP_ENV=test or APP_ENV=demo can invoke reset.
- Rate limiting is deferred while a public URL is authorized.

## 11. Phase 6 — Build the presenter package

### 11.1 Objective

Make the synthetic demo understandable and recoverable when presented by someone who did
not build the software.

### 11.2 Owner branding decision

Use HandoffSignal as the outward presentation name if the owner confirms it for this
phase. Preserve OpsRecovery V2 as the internal package/repository codename unless a
separate rename is approved. Do not perform a broad code rename as demo polish.

Before public promotion, record that owning handoffsignal.com is not trademark clearance.

### 11.3 Required deliverables

Create:

- docs/runbooks/demo.md
- docs/demo/DEMO_TALK_TRACK.md
- docs/demo/DEMO_REHEARSAL_CHECKLIST.md
- docs/demo/DEMO_LEAVE_BEHIND.md
- docs/demo/DEMO_LEAVE_BEHIND.pdf, rendered from the reviewed source and visually
  verified as exactly one page
- docs/demo/DEMO_MEDIA_MANIFEST.md
- docs/demo/DEMO_EXECUTION_STATUS.md
- ignored local assets under docs/media/YYYY-MM-DD/ with approved synthetic screenshots,
  a 1080p recorded walkthrough, and a text transcript

Do not place a large video in Git unless the owner approves the storage approach. A
private, access-controlled location may be preferable; record the pointer, not a public
link, until publication is authorized.

The media manifest must record the source commit, reset state, capture date, resolution,
filenames, SHA-256 checksums, storage location, and exact recapture instructions. Recapture
all affected assets after any user-facing, fixture, detector, authorization, or financial-
language change.

### 11.4 Demo structure

Target duration: 7–10 minutes.

Opening disclosure, before showing the product:

1. Everything is synthetic.
2. This is a concept with no customers or pilots yet.
3. It reads bounded CSV exports and is not real-time.
4. It connects to no prospect system today.
5. It writes nothing back, sends nothing, and creates no invoice.
6. One workflow is built; attendance and inspection workflows are deliberately absent.

Golden-path narrative:

1. Show four source types and explain the identifier mismatch.
2. Explain the omitted Potomac crosswalk and why guessing is forbidden.
3. Show the one created exception and three negative controls.
4. Open REV-00001 and explain completion, authorization, rate, coverage, freshness, and
   invoice-absence evidence.
5. Show the four financial facts on the recovery ledger.
6. Approve invoice-ready as finance.
7. Export the bookkeeper handoff and state that no invoice was created.
8. Resubmit to demonstrate export idempotency.
9. Switch to operations, auditor, and foreign-tenant roles to demonstrate denied actions.
10. Close with the qualification question:

       If your work orders and invoicing live in the same system and your native control
       already closes the loop, you should not buy this.

Required money sentence:

    That 480 dollars is a synthetic candidate value: contract-supported work that may be
    billable. It is not recovered revenue, not invoiced, and not collected.

The runbook must also include:

- T-24-hour, T-60-minute, and T-10-minute checks;
- an account/role matrix with no passwords;
- exact safe reset/start commands and expected outputs;
- the click path and recovery action for every golden-path step;
- a never-say list covering recovered revenue, proven precision or ROI, authenticated
  integrations, real-time monitoring, and customer validation;
- discovery questions at the point where each source or control appears;
- post-demo cleanup that removes the downloaded synthetic CSV, logs out, preserves
  volumes, and resets before the next session;
- fallback order: live app, then recording, then screenshots plus narration.

### 11.5 Screenshot set

Capture only synthetic data:

1. Corrected cockpit.
2. Imports/source freshness.
3. Identity-resolution explanation.
4. Exception inbox.
5. Case-detail evidence and timeline.
6. Recovery ledger before approval.
7. Recovery ledger after approval.
8. Export history.
9. Wrong-role denial.
10. Cross-tenant 404 with no Atlas identifiers.

Before saving each screenshot:

- inspect browser tabs, notifications, bookmarks, profile menus, desktop, and terminal for
  personal or secret information;
- crop to the product surface;
- confirm no password, email inbox, domain-control panel, token, or unrelated customer
  information is visible.
- capture only the product viewport, keep the synthetic-data banner visible, and verify
  that every visible email address uses the fictional .example domain;
- capture candidate state before approval/export state and never weaken authorization to
  manufacture a cleaner denial screenshot.

### 11.6 Leave-behind

DEMO_LEAVE_BEHIND.md must include:

- the problem hypothesis;
- the read-only four-source flow;
- what the product does and does not do;
- the four financial stages;
- the 25-minute workflow-interview ask;
- a request for column headers and a few de-identified rows, not full files;
- screen-share or a column-list walkthrough as the preferred first step;
- explicit instruction not to email sensitive exports;
- a prohibition on customer names, street addresses, worker details, credentials,
  access/alarm codes, bank, tax, or payroll data, and system secrets;
- acceptable sanitization such as stable substituted identifiers, shifted dates, altered
  amounts, preserved status labels, and a few rows;
- the minimum source list;
- a valid negative outcome;
- no synthetic performance or ROI claim.

### 11.7 Acceptance criteria

- A second person can run the demo from docs/runbooks/demo.md.
- The presenter completes the primary story in 10 minutes.
- Every screen and phrase is consistent with Route B.
- The fallback can support the conversation with Docker stopped.
- The recording contains all six disclosures, the required 480-dollar sentence, and the
  honest negative qualification line.
- The PDF leave-behind is exactly one page and has been visually inspected after render.
- No captured asset contains sensitive or non-synthetic data.
- The leave-behind asks for a sanitized source walkthrough rather than a sale.

## 12. Phase 7 — Rehearse locally and prove recovery

### 12.1 Objective

Prove that the demo is repeatable under normal and failure conditions before involving a
prospect.

### 12.2 Rehearsal protocol

Run three clean rehearsals on the intended presentation hardware.

For each run record:

- start and end time;
- reset duration;
- application start duration;
- presenter duration;
- expected case and skipped-control counts;
- approval/export behavior;
- role-denial results;
- failure or confusing language;
- recovery action;
- screenshots/video version used.

Create these rehearsal supports:

- apps/recovery/management/commands/demo_preflight.py;
- tests/test_demo_preflight.py;
- a demo-preflight Make target;
- a demo-rehearse Make target that performs the documented reset and read-only preflight,
  never hidden destructive recovery;
- docs/demo/DEMO_FAILURE_CARD.md;
- docs/demo/DEMO_REHEARSAL_TEMPLATE.md;
- docs/demo/DEMO_REHEARSAL_REPORT.md.

demo_preflight must be read-only. It exits nonzero, names the failed invariant without
connection details, and tells the presenter to use the fallback. It must never repair,
delete, reseed, grant a role, or change a password automatically.

### 12.3 Required preflight

1. Confirm the intended branch and commit.
2. Confirm PostgreSQL and Redis are healthy.
3. Run migrations.
4. Run make demo-reset.
5. Confirm:
   - reconciliation run ready;
   - one case;
   - candidate 480.0000;
   - one invoice-present skip;
   - one authorization-missing skip;
   - one not-completed skip.
6. Start the server.
7. Open only the tabs required for the demo.
8. Disable personal notifications.
9. Confirm the fallback assets are available offline.

The read-only preflight must additionally verify:

- APP_ENV is local and DEMO_MODE is true;
- the presentation database contains only the two expected synthetic organizations;
- Atlas and Beacon are marked as demo organizations;
- expected users and grants exist without printing credentials;
- no decision-dependent source is stale and the deliberately policy-free identity source
  is reported honestly;
- the latest detector run scanned four records, created one, and skipped exactly one each
  for invoice_present, authorization_missing, and not_completed;
- the identity queue is empty after demo_load;
- REV-00001 is the only candidate, for work order 00518774 at Meridian Business Center,
  with candidate value 480.0000 and no pre-walkthrough approval/export;
- the zero-grant supervisor sees no case-derived count or money;
- Beacon cannot resolve Atlas objects;
- Journey A and Journey C remain absent;
- the synthetic banner and safe financial language render.

### 12.4 Failure matrix

Rehearse:

| Failure | Expected behavior | Maximum recovery |
| --- | --- | --- |
| PostgreSQL stopped | readiness 503; no false success | 60 seconds |
| Redis stopped | liveness remains 200; readiness 503 | 60 seconds |
| Server stopped | fallback assets available | immediate |
| Stale expected version | friendly refusal; no write | explain in 30 seconds |
| Invoice arrives before export | export refuses as a safety control | explain in 30 seconds |
| Wrong role posts approval | 403; no write | immediate |
| Auditor downloads export | 403 | immediate |
| Foreign tenant requests Atlas case/export | 404; no identifiers | immediate |
| Export is submitted twice | same export record | immediate |
| Live demo becomes unstable | switch to recording/screenshots | 30 seconds |

Do not deliberately corrupt or delete the database to demonstrate failure.

Also perform and record:

1. A cold start beginning with docker compose down, never down -v.
2. A warm reset after approval/export, returning to one untouched candidate and zero
   exports.
3. A second-person run using only the runbook and no database-shell edits.
4. A complete fallback narration with Docker stopped and no internet dependency.

Classify failures:

- presentation or infrastructure failure: switch to fallback, then repair after the call;
- expected safety refusal: explain it, never bypass it, and reset only afterward;
- correctness or isolation failure: stop immediately and return to engineering. Duplicate
  exports, unauthorized success, tenant leakage, or combined financial stages are hard
  stops, not presentation inconveniences.

### 12.5 Acceptance criteria

- Three consecutive golden paths produce identical business outcomes.
- No unauthorized action succeeds.
- Every known failure has a rehearsed response.
- The presenter can switch to fallback within 30 seconds.
- The complete story remains under 10 minutes.
- A non-builder can execute the runbook without undocumented help.
- Full engineering gate passes after rehearsal fixes.
- No recovery uses direct database editing, weakened permissions, public reset, or
  docker compose down -v.

### 12.6 Rehearsal report

Create docs/demo/DEMO_REHEARSAL_REPORT.md with:

- environment and commit;
- three-run timing table;
- failures encountered;
- fixes made;
- open demo risks;
- go/no-go recommendation;
- explicit statement that only synthetic data was used.

## 13. Phase 8 — Decide on Railway; deploy only if evidence justifies it

### 13.1 Phase 8A objective

Make a documented no-deploy, deploy-guided-demo, or deploy-self-serve-demo decision. This
phase is analysis only.

### 13.2 Default recommendation

Default to no deployment until a real outreach or scheduled-call constraint shows that a
remote link is needed. A local guided demo plus recorded fallback is sufficient to begin
interviews. Hosting adds an internet-facing authentication surface before customer
evidence exists.

The current evidence-based decision is no-go for provisioning. Phase 0A's mandatory
evidence stop requires at least five serious interviews across owner, operations, and
finance, plus one sanitized source walkthrough, before hosting. Finish Phase 8A, proceed
to Phase 9 with the local/recorded demo, and revisit Phase 8B only after that checkpoint.
An earlier exception requires the owner to explicitly supersede the evidence gate and
cite a qualified-prospect constraint; convenience or polish is not sufficient.

### 13.3 Decision matrix

| Signal | Decision |
| --- | --- |
| Scheduled interviews accept a live screen share | Defer Railway |
| Recording and screenshots answer asynchronous follow-up | Defer Railway |
| Prospects repeatedly require a link before scheduling | Consider hosted demo |
| A serious prospect needs a time-boxed self-serve evaluation | Consider hosted demo with controlled credentials |
| Only vanity, convenience, or “it looks more real” supports hosting | Do not deploy |
| Public URL controls remain incomplete | Do not deploy |
| V1 credential rotation/history cleanup is unconfirmed | Do not deploy |

### 13.4 Phase 8A deliverable

Create docs/demo/RAILWAY_DEMO_DECISION.md containing:

- evidence for and against hosting;
- intended audience and access model;
- expected duration;
- cost and maintenance owner;
- exact services required;
- whether background worker/beat are actually needed for the synthetic path;
- required ADR change if the topology differs from ADR 0005;
- domain proposal, preferably demo.handoffsignal.com;
- all security gates;
- no-deploy fallback;
- recommendation and confidence.

Also create docs/demo/RAILWAY_PREFLIGHT_CHECKLIST.md. If current platform facts supersede
ADR 0005, create a new ADR and mark ADR 0005 superseded; do not silently rewrite a
historical decision.

Stop after the decision document. Do not inspect or mutate Railway in Phase 8A.

### 13.5 Current Railway facts to revalidate

Railway behavior is time-sensitive. Claude must re-check current official documentation
at execution time and record the verification date. As of 2026-08-29:

- [Railway Config as Code](https://docs.railway.com/config-as-code) says
  railway.toml/railway.json are deprecated, existing legacy services have a 2026-12-01
  cutoff, and new services cannot opt in. The current replacement is Infrastructure as
  Code using .railway/railway.ts and the railway config workflow documented by the
  [Railway CLI](https://docs.railway.com/cli). ADR 0005 is therefore consistent with the
  current deprecation fact, but its decision to keep IaC out of scope must be deliberately
  re-evaluated—not assumed eternal.
- [Railway healthchecks](https://docs.railway.com/deployments/healthchecks) use Host:
  healthcheck.railway.app and run during deployment rather than as continuous monitoring.
  Django allowed hosts must include both the application hostname and
  healthcheck.railway.app; CSRF trusted origins must contain only actual HTTPS application
  origins.
- [Railway pre-deploy commands](https://docs.railway.com/deployments/pre-deploy-command)
  run in a separate container without mounted volumes and do not persist filesystem
  changes. Keep collectstatic in the image build and run migrations from web only.
- Verify the exact PostgreSQL image/version and volume mount at provisioning time; never
  trust a latest tag. Confirm the running version with SHOW server_version before calling
  the datastore compatible with local PostgreSQL 18.

### 13.6 Mandatory gates before Phase 8B

All must be true:

- Phase 1 baseline is committed and privately backed up.
- Phases 2–5 pass their acceptance criteria.
- Phase 7 recommends go.
- Login rate limiting exists and is tested.
- No shared or source-code demo password exists.
- V1 credential rotation and Git-history cleanup are owner-confirmed.
- The owner authorizes a new, separate V2 Railway project.
- The owner selects the access model and duration.
- No real data will be used.
- A teardown owner and date are defined.
- The Phase 9 evidence stop has five serious interviews covering owner, operations, and
  finance, at least one finance reviewer, and one sanitized source walkthrough, unless the
  owner has explicitly superseded that gate with a documented qualified-prospect need.
- At least two qualified prospects request a link or an otherwise credible scheduling or
  evaluation constraint shows that local screen share is blocking progress.
- A separately reviewed hosted synthetic-data bootstrap and credential procedure exists;
  the local-only destructive fixture commands remain unusable on Railway.

### 13.7 Phase 8B constraints if separately authorized

Follow ADR 0005 unless a new ADR explicitly changes it:

- new V2-only Railway project;
- dedicated demo environment;
- default production environment left empty;
- V1 project, services, datastores, variables, domains, and triggers untouched;
- US East/Virginia;
- PostgreSQL major version aligned with local version;
- Redis noeviction;
- only the web service public;
- explicit allowed hosts and CSRF origins;
- HTTPS verified before HSTS;
- autodeploy disabled for the first release;
- migrations run from web only;
- exactly one beat replica if beat is deployed;
- synthetic-only banner visible;
- no admin, signup, public reset, or demo-reset route;
- protected secret entry performed by the owner;
- service settings mirrored without values in docs/RAILWAY_CONFIG.md.

ADR 0005 plans five services, but the guided Route B path runs synchronously. Before
provisioning, choose one of two explicit paths:

1. Retain web, worker, beat, PostgreSQL, and Redis, and add at least one real
   worker_integration test covering publish, consume, and idempotent redelivery.
2. Write and approve a superseding ADR for a smaller authenticated synthetic-demo
   topology. Do not silently omit worker/beat or present an untested background path.

Only the web service may be public. PostgreSQL, Redis, worker, and beat use private
networking. Redis must use noeviction. Web must bind Railway's injected PORT. First use
the generated Railway domain; demo.handoffsignal.com and any Namecheap change require a
later, separate DNS authorization that leaves MX, SPF, DKIM, and DMARC untouched.

A public URL remains authenticated. Prefer presenter-controlled guided access. A shared
self-serve finance credential is not acceptable because one visitor can approve or export
the only case and change state for another. Self-service requires separately scoped,
time-limited state isolation; never solve this with a public reset route or a password in
source.

Claude must request confirmation immediately before each remote mutation. It must never
read, paste, or print a secret.

### 13.8 Hosted-demo verification

- Health live and ready endpoints behave correctly.
- The Railway deployment healthcheck succeeds with Host healthcheck.railway.app, while
  arbitrary unapproved hosts remain rejected.
- Dependency failure changes readiness to 503 without leaking connection details.
- Cross-tenant and wrong-role browser controls pass against the deployed URL.
- Demo accounts are rotated and access is time-bounded.
- Logs contain no passwords, raw rows, tokens, or sensitive error text.
- The site is usable at 375 pixels.
- The owner can disable public access promptly.
- A complete teardown/reseed procedure is tested.
- Railway's default production environment remains empty and a V2 push cannot trigger a
  V1 deployment.
- Running PostgreSQL version, Redis eviction policy, private networking, cost alert, and
  hard limit match the redacted configuration ledger.

## 14. Phase 9 — Founder-led interview outreach

### 14.1 Objective

Use the credible synthetic demo to test the market hypothesis and obtain the mandatory
evidence checkpoint:

- at least five serious workflow interviews;
- at least one interview with the finance reviewer who validates invoice absence;
- at least one sanitized source walkthrough;
- a disconfirmation report recommending keep, change, kill, or pivot.

This phase is not a broad product launch and not a bulk-email campaign.

Operating ownership:

| Subphase | Primary actor | Claude's permitted role |
| --- | --- | --- |
| Safety, segmentation, and drafts | Claude plus founder review | Build templates, reverify organization facts when instructed, draft one-to-one messages, and stop for approval |
| Direct and adviser outreach | Founder | Prepare the next reviewed batch and tracking structure; never send, call, message, or submit a form |
| Interviews and source walkthroughs | Founder | Prepare guides and convert owner-approved, de-identified notes into evidence maps |
| Evidence decision | Claude plus founder | Calculate the bounded experiment results and draft the Keep/Change/Kill/Pivot report; founder approves the decision |

The approval phrase for Phase 9 authorizes preparation only. The founder's later manual
outreach is an operational experiment, not autonomous Claude execution.

### 14.2 Commercial anchor

Offer context:

- Product: HandoffSignal, internally OpsRecovery V2.
- Audience: DMV commercial-cleaning building-service contractors, with Virginia focused
  on Northern Virginia.
- Workflow: completed and authorized work that may not have reached invoice review.
- Motion: founder-led discovery, then a bounded 45-day read-only design-partner pilot
  only after data feasibility.
- Current stage: pre-customer evidence; no active opportunity or committed buyer may be
  implied.

### 14.3 Prerequisites

Before any first contact:

1. The repository has a committed, recoverable private remote and Phases 2–5 pass.
2. Phase 7 has a go recommendation and a second person can deliver the demo from the
   repository in ten minutes.
3. The owner confirms the HandoffSignal sender identity.
4. handoffsignal.com passes SPF, DKIM, and DMARC.
5. aman@handoffsignal.com can send and receive.
6. A valid business postal address is available for commercial-email compliance.
7. A plain-text signature and immediate opt-out process exist.
8. A suppression list exists, is tested, and is checked before every touch.
9. The DMV prospect database is reviewed for freshness and disqualifiers.
10. No message claims customer results, integrations, recovered revenue, or AI autonomy.
11. The interview note template, claims ledger, and leakage-audit worksheet are ready.
12. No real or sanitized prospect data is stored in the product.

Claude may prepare drafts and trackers. It may not send or publish without separate
authorization.

Keep live suppression data, personal contact data, confidential notes, recordings, and
customer files outside Git. Repository templates may contain invented placeholders only.

### 14.4 Target segmentation

Prioritize candidates that:

- operate multi-site commercial cleaning in the DMV;
- perform periodic, project, extra, turnover, change-order, or emergency work;
- appear to use separate operations and accounting workflows;
- have a plausible owner/operations sponsor and finance reviewer;
- can likely export stable customer, site, work, authorization/rate, and invoice fields;
- are small enough for a founder-led pilot and large enough to have repeated exceptions.

Deprioritize or disqualify:

- very small operators with few variable-billing events;
- mature WinTeam or Aspire workflows that already close the gap;
- federal, airport, school, healthcare, corrections, union-heavy, or highly regulated
  environments as the first pilot;
- enterprise procurement before references and security evidence;
- no authoritative invoice ledger;
- no stable identifier/crosswalk path;
- no weekly review owner;
- requests for automatic invoicing, source write-back, payroll, messaging, or broad
  integrations.

Use the existing 50-company research universe only as a dated seed. Reverify every
selected organization from current official sources immediately before use. Select
exactly 36 organizations:

| Segment | Count | Purpose |
| --- | ---: | --- |
| Core fit | 24 | Test the primary independent/mid-market recurring-service ICP |
| Exploratory fit | 8 | Test smaller, mixed-service, or incompletely evidenced profiles |
| Contrast/disconfirmation | 4 | Test whether mature-system or larger operators already solve the gap |

Directional geography target: 16–20 Northern Virginia, 10–14 Maryland, and 4–6
Washington, DC. Fit outranks quota; do not include a weak company merely to satisfy a
geography cell. Exclude deep southern Virginia.

### 14.5 Buying-role map

| Role | Discovery responsibility | Evidence needed |
| --- | --- | --- |
| Owner, president, GM, CFO | Economic relevance and permission | Repeated material workflow and willingness to test |
| COO, operations leader, branch manager | Operational champion | Completion and authorization handoff |
| Controller, finance manager, billing owner, bookkeeper | Required validator | Authoritative invoice absence, duplicate controls, review effort |
| Systems or operations analyst | Data validator | Exportability, identifiers, coverage, preparation effort |

Do not infer a person’s role, software, pain, or authority from a title alone. Verify in
conversation.

Choose one verified professional role for the initial touch at each organization. Do not
contact several employees at once. Include at least eight finance/billing initial roles
when they can be verified. If the first role does not respond after the close-the-loop
touch, wait at least seven days before approaching a second verified role.

### 14.6 Phase 9A — Thirty-six-sequence A1 experiment

Purpose:

Test whether a demo is what unblocks interviews. The first contact should ask for a
workflow conversation, not require viewing the product.

One experiment unit is one unique organization entering a founder-reviewed no-demo
sequence. Follow-ups do not count as additional attempts. A sequence counts as delivered
only when the first email does not hard-bounce, an official form confirms submission, or
a live call/voicemail reaches an official business route.

Run six batches of six:

- Batches 1–4: the 24 core-fit organizations, beginning with the strongest six.
- Batch 5: six exploratory organizations.
- Batch 6: two exploratory plus four contrast/disconfirmation organizations.

Pause after each batch for evidence and deliverability review. Initiate no more than six
new organizations in a day and no more than ten total outbound emails in a day while the
domain is new. Complete the final sequence window before judging the experiment.

Run ten adviser-introduction requests in parallel, but keep them as a separate warm
channel. Never combine warm-introduction conversion with the 36 direct sequences.

For each account record:

- official company source;
- DMV service footprint;
- verified reason it fits;
- disqualifier check;
- target owner/operations/finance role;
- public business contact source;
- personalization fact with source and date;
- touch history;
- opt-out/suppression state;
- evidence stage.

Do not guess direct email addresses. Do not use personal emails.

### 14.7 Mailbox ramp and sending discipline

Use manual, consistent, low-volume sending:

- first three sending days: 3–5 highly personalized new-account messages per day;
- later batches: no more than six new-account messages per day and ten total emails per
  day while authentication, replies, and delivery remain normal;
- do not burst-send or use automated warm-up networks.

Planning volumes are not guarantees. Slow down immediately on bounces, spam placement,
negative feedback, or weak personalization.

Each commercial email must have:

- accurate sender and reply information;
- an honest subject;
- the real business identity;
- a valid postal address;
- a clear, easy opt-out;
- no attachment on first contact;
- no fake Re:, fake referral, urgency, or fabricated familiarity.

Honor opt-outs immediately in the internal suppression list.

Pause immediately for any spam complaint, an authentication failure, two hard bounces in
one six-account batch, a missing postal address/opt-out, or repeated feedback that the
message implies known invoice loss. These are conservative internal controls, not market
benchmarks.

### 14.8 Manual five-touch sequence

| Timing | Channel | Purpose |
| --- | --- | --- |
| Day 1 | Personalized email or official contact route | Ask for a 25-minute workflow interview; do not require a demo |
| Day 4 | Short email reply | Ask whether the current control is an integration, report, or manual check |
| Day 7 | Live founder call or voicemail to official business number | Clarify this is workflow research, not system replacement |
| Day 11 | Email | Offer the one-page leakage audit; do not attach unless requested |
| Day 16 | Close-the-loop email | End follow-up unless the recipient responds |

Rules:

- no prerecorded calls, autodialer, ringless voicemail, cold SMS, or number spoofing;
- no scraped LinkedIn activity or automated invitations;
- no more touches after an opt-out;
- one company may have multiple relevant roles, but do not create a coordinated swarm.
- stop the sequence immediately on reply, opt-out, disqualification, complaint, or
  confirmed delivery failure.

### 14.9 Message posture

Lead with:

    How do you prove that every approved extra service completed in operations actually
    reached the accounting invoice ledger?

Position the conversation as research:

- not a scheduler replacement;
- not an AI pitch;
- not a claim that the organization is losing revenue;
- not a request for full data;
- not a demo requirement.

The initial ask:

    A 25-minute walkthrough of the last real extra service from authorization through
    completion and invoice confirmation.

The next-step ask after a qualified conversation:

    Sanitized column headers or a few de-identified rows from the relevant sources, shared
    through an agreed non-email transfer path.

### 14.10 Discovery evidence

An interview counts as serious only when a relevant owner, operations, or finance
participant either discusses a recent actual example or clearly states that none exists,
maps authorization through invoice confirmation, identifies the authoritative invoice
ledger, explains ownership and cadence, addresses recurrence and materiality, and names
the source records involved. An interesting-idea conversation does not count.

Use a 25-minute structure:

1. Opening and note-taking permission — 2 minutes.
2. Company and workflow context — 5 minutes.
3. Last real example from request through invoice/collection — 10 minutes.
4. Frequency, consequence, ownership, and current control — 5 minutes.
5. Commitment and source-walkthrough test — 3 minutes.

Do not lead with the demo. Offer it only after the participant establishes a repeated
workflow or asks to see the hypothesis represented. Before every walkthrough, repeat the
six synthetic/pre-customer disclosures and the candidate-value language.

Every serious interview must document:

- the last real example;
- who requested and authorized the work;
- where rate or contract basis lives;
- how completion is proven;
- which identifiers connect the sources;
- how finance determines invoice readiness;
- which ledger is authoritative;
- how voids, credits, bundles, and reissues appear;
- who owns the exception;
- review frequency, item count, touches, and time;
- whether a native control already solves the workflow;
- willingness to provide sanitized headers/rows;
- the named finance validator.

Show the real import coverage form to at least two operations interviewees and ask which
sites, dates, statuses, and records their exports completely cover.

Strong evidence:

- a recent example;
- source names and column headers;
- repeated manual behavior;
- named owner and reviewer;
- willingness to run a bounded test.

Weak evidence:

- that sounds useful;
- generic lost-revenue estimates;
- AI curiosity;
- feature requests without an example;
- demo interest without a data path.

Sanitized-source progression:

1. Ask for column names and source descriptions first.
2. Prefer a prospect-controlled screen share of the actual export structure, with no file
   retention.
3. Record schema-level notes only: stable IDs, coverage dates, included/excluded statuses,
   update timestamps, authorization/rate basis, invoice/credit/void/reissue behavior, and
   bundled-invoice behavior.
4. Do not download, email, upload, retain, or ingest any file until a written sanitization
   standard, approved non-email transfer path, retention/deletion procedure, and named
   access owner exist.
5. Never load prospect data into the synthetic demo.

A sanitized source walkthrough counts only when actual source structures cover customer/
site master, completion, authorization/rate, and the authoritative invoice ledger. The
participant may substitute stable tokens. At least one walkthrough must include a finance
or billing validator.

### 14.11 Funnel definitions

| Stage | Required evidence |
| --- | --- |
| Researched | Official source and fit rationale |
| Contacted | One compliant manual touch |
| Replied | Human response |
| Discovery scheduled | Named person and date |
| Discovery complete | Recent workflow example documented |
| Data-fit pending | Agreement to sanitized field review |
| Data-fit | Identifiers, coverage, and four-source path appear feasible |
| Demo-qualified | Repeated problem, sponsor, finance reviewer, and data path |
| Pilot proposed | Written scope, price hypothesis, roles, metrics, dates, and stop conditions |
| Disqualified | Reason code recorded |

Do not use open rate as the primary measure. Google does not verify third-party open-rate
accuracy, and tracking pixels add little value at this stage.

Required experiment metrics:

- organizations researched, reverified, and delivered;
- hard bounces, opt-outs, complaints, and suppressions;
- human replies separated into positive, negative, referral, and disqualification;
- meetings scheduled, held, and no-showed;
- serious interviews and owner/operations/finance role coverage;
- complete workflow maps, source-field maps, and sanitized source walkthroughs;
- demo-qualified accounts and conditional paid-pilot interest;
- research, outreach, interview, and data-preparation time;
- repeated-exception frequency, touches, minutes, source completeness, native-system
  resolution, false-positive concerns, and disqualification reasons.

Calculate delivery, human-reply, serious-interview, show, finance-coverage,
source-walkthrough, and demo-qualified conversion rates. Treat them only as results of
this bounded experiment, never as market benchmarks.

### 14.12 Phase 9 success gates

Immediate A1 experiment:

- exactly 36 qualified organizations researched and reverified;
- 36 delivered organization-level sequences completed through their final windows;
- at least two serious workflow calls means the demo was not required to create initial
  access; record A1 as disconfirmed without treating that as product validation;
- after 12 delivered sequences with no human reply, inspect authentication, contact
  accuracy, and clarity and change only one variable;
- after 24 delivered sequences with no serious interview, stop new direct sends and use
  the separate adviser track to diagnose audience, role, message, and channel before more
  product work.

Mandatory evidence checkpoint:

- five serious completed workflow interviews collectively covering owner, operations,
  and finance;
- at least one finance reviewer;
- one sanitized source walkthrough;
- the real import form shown to at least two interviewees to test bounded coverage;
- every interview scored keep, investigate, or disqualify;
- no new journey authorized solely by positive reactions.

Planning targets—not promises or market benchmarks—are 8–12 serious interviews, five
complete workflow maps, three source-field maps, and two demo-qualified accounts.

### 14.13 Stop and kill criteria

Stop or reassess the wedge when:

- operations completion already creates the invoice reliably;
- interviewees cannot recall a repeated material example;
- no one can produce contract/rate or invoice-source equivalents;
- no one can declare which sites, statuses, and dates an export completely covers;
- identifiers cannot be mapped reliably;
- weekly preparation effort destroys the economics;
- a native report/process improvement solves the issue more simply;
- no finance reviewer will validate absence;
- interest exists only for automatic invoicing or unrelated workflows;
- the first five serious interviews consistently disconfirm the problem.

A negative result is success for the experiment. Do not redefine it as market traction.

Final recommendation rules:

- Keep Journey B only when five serious interviews cover owner, operations, and finance;
  at least three independent accounts confirm a repeated exception; an operations/
  finance pair agrees on the workflow; a feasible source path exists; and one sanitized
  source walkthrough is complete.
- Change the segment, wording, or workflow when pain exists but concentrates in another
  profile, another exception is materially stronger, source structures differ from the
  provisional four-file model, or identity matching is not the real difficulty.
- Kill or pivot the current wedge when five or more serious interviews consistently show
  completion already creates the invoice, cases are isolated, native controls close the
  gap, authorization/invoice evidence cannot be established, exports are not practical,
  or operations cannot declare bounded source coverage.
- Do not authorize product expansion while fewer than five serious interviews exist,
  finance is absent, or no sanitized source walkthrough is complete. Compliments, demo
  requests, and feature ideas are not substitutes.

### 14.14 Phase 9 deliverables

Claude may create or update, without sending:

- docs/go_to_market/STEP_9_OUTREACH_PROGRAM.md;
- docs/go_to_market/CLAIMS_LEDGER.md;
- docs/go_to_market/ICP_AND_SEGMENTATION.md;
- docs/go_to_market/FOUNDER_OUTREACH_SEQUENCE.md;
- docs/go_to_market/DISCOVERY_GUIDE.md;
- docs/go_to_market/SOURCE_WALKTHROUGH_GUIDE.md;
- docs/go_to_market/templates/OUTREACH_TRACKER_TEMPLATE.csv;
- docs/go_to_market/templates/INTERVIEW_NOTES_TEMPLATE.md;
- docs/go_to_market/templates/WORKFLOW_MAP_TEMPLATE.md;
- docs/go_to_market/templates/SOURCE_MAP_TEMPLATE.md;
- docs/go_to_market/templates/DISCONFIRMATION_REPORT_TEMPLATE.md;
- docs/go_to_market/templates/CONDITIONAL_PILOT_READINESS_MEMO.md;
- a reviewed 36-account cohort in the existing prospect workbook outside this Git
  repository, with account-specific draft emails and call notes for owner review;
- a one-page Completed Work-to-Invoice Leakage Audit and weekly evidence dashboard.

The final disconfirmation report must recommend exactly one of Keep, Change, Kill, or
Pivot and cite interviews, negative evidence, source findings, and remaining uncertainty.

Claude must not:

- send any message;
- call or text anyone;
- create calendar invitations;
- publish customer facts;
- upload customer data to the synthetic demo;
- mark a company data-fit without source evidence;
- create an opportunity or commitment that does not exist.
- place a live suppression list, private email address, personal phone number,
  confidential prospect note, interview recording, credential, or customer data in Git.

### 14.15 Phase 9 review cadence

Daily during active outreach:

- check suppression before sending;
- review delivery failures and negative replies;
- prepare the next small batch;
- log evidence, not impressions.

Twice weekly:

- compare owner versus finance response;
- review which personalization facts led to real workflow discussion;
- remove weak-fit or regulated-first-pilot accounts;
- refine one message variable at a time.

Weekly:

- count completed workflow maps;
- count finance participation;
- count sanitized-source commitments;
- record disqualifications and why;
- decide continue, change, or stop.

## 15. End-to-end release gates

### Gate A — Safe internal demo

- Baseline committed and recoverable.
- Site-scope defect fixed.
- Four-stage cockpit truthful.
- Freshness coherent after reset.
- No tracked password.
- Global engineering gate green.

### Gate B — Prospect-facing local demo

- Gate A.
- Presenter runbook complete.
- Three rehearsals pass.
- Backup recording/screenshots available.
- Branding and disclosures approved.
- No real data.

### Gate C — Hosted synthetic demo, post-evidence by default

- Gate B.
- Railway decision says deploy.
- Five serious interviews, finance participation, and one sanitized walkthrough are
  complete unless the owner explicitly supersedes the original evidence gate for a
  documented qualified-prospect constraint.
- Rate limiting and controlled credentials.
- Owner authorizes each remote resource and DNS change.
- V1 security gate confirmed.
- Synthetic banner and teardown procedure.

### Gate D — Evidence expansion

- Five interviews.
- Finance participation.
- One sanitized walkthrough.
- Disconfirmation report.
- Owner says Approve evidence expansion plan.

This file does not authorize a real-data pilot. Real-data controls remain a later,
separately approved plan.

## 16. Required final report from Claude after each phase

Use this format:

### Phase result

- Phase:
- Approval wording:
- Objective achieved:
- Files changed:
- Migrations:
- Commands run:
- Test counts:
- Coverage:
- Security/tenant review:
- Financial-language review:
- Demo impact:
- Remaining findings:
- Git status:
- Commit:
- Rollback notes:
- Recommended next phase:

Then stop.

## 17. Initial instruction to give Claude

Use this after placing Claude at the ops-recovery-v2 repository root:

    Read docs/CLAUDE_DEMO_TO_OUTREACH_EXECUTION_PLAN.md and
    docs/PHASE_0_TO_6_BUILD_HANDOFF.md in full. Begin Phase 1A read-only preflight only.
    Do not stage, commit, create a remote, push, deploy, change DNS, or contact anyone.
    Return the Phase 1A report and wait for my approval.
