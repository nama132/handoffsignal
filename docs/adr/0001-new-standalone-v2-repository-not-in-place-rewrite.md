# ADR 0001 — New standalone V2 workspace, not an in-place V1 rewrite

Status: accepted
Date: 2026-08-27

## Context

V1 is a single-agency Flask prototype for home-care shift coverage: `app.py` is
~82 KB and `db.py` ~82 KB of raw SQL helpers, schema is created ad hoc including
DDL at import time, there is no tenancy (`agency_name` is descriptive only), and
`CREDENTIALS.md` is tracked in Git and documented as containing live secrets. Its
`main` branch is connected to a live Railway deployment.

V2 is a different product for a different industry: a commercial-cleaning
exception and revenue-recovery overlay. It shares no data model, no tenant model,
and no compliance posture with V1.

An in-place rewrite would mean editing a repository whose history contains
secrets, whose branch deploys to production, and whose schema is mutated at
runtime — while simultaneously changing the domain.

## Decision

Build V2 as a new, isolated workspace at
`/Users/amanabbas/Desktop/Project AI/V2/ops-recovery-v2`, with its own Git
repository and branch `v2-commercial-cleaning`. V1 remains an external, read-only
reference at `/Users/amanabbas/Desktop/Project AI/A.I. Product/shiftcare-prod`.

No V1 module is imported, no symlink crosses the boundary, no credential or
database file is copied, and neither application is configured to read the
other's files. Concepts reused from V1 (candidate explanation, phone
normalization, deterministic parsing vocabulary) are reimplemented with tests.

## Alternatives considered

- **In-place rewrite of V1.** Rejected: couples a domain change to a live
  deployment and a compromised Git history, with no rollback boundary.
- **Fork of the V1 repository.** Rejected: inherits the secret-bearing history and
  the Railway deployment trigger.
- **Shared monorepo with V1.** Rejected: Railway watch paths and deployment
  triggers would couple the two products.

## Consequences

- V1 continues running untouched; its baseline (`main` @ `a6cc7d5`, clean tree)
  is recorded and re-verified at every phase boundary.
- No code reuse by copy — anything wanted from V1 is rebuilt with tests, which
  costs time but removes unsafe semantics (see the 20 inherited risks in the
  master prompt section 5).
- Two codebases exist during the demo period. Acceptable: V1 is frozen.

## Security/privacy impact

Strongly positive. The V2 workspace has no credential file, no tracked secret, and
no live provider configuration. The V1 secret-remediation problem stays contained
in V1 and is a hard gate before any remote V2 deployment.

## Migration/rollback impact

No data migration from V1 is planned or authorized. Rollback of V2 at this stage
is deleting the uncommitted V2 workspace contents; V1 is never touched.

## Validation evidence

- V1 baseline recorded before and after Phase 1: `main` @ `a6cc7d5`, 0 dirty entries.
- `tests/test_project_boundaries.py::test_no_source_file_imports_a_v1_module`.
- `tests/test_project_boundaries.py::test_no_dotenv_loader_is_used`.
