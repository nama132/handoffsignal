# ADR 0005 — Railway as the only cloud target, in a separate V2 project

Status: accepted (planning only — nothing is provisioned)
Date: 2026-08-27

## Context

V1 is deployed on Railway and its `main` branch is connected to a live deployment.
The owner already has a Railway account, so reusing the platform avoids learning a
second one. The danger is the opposite of convenience: a shared project,
environment, datastore, variable set, domain, or deploy trigger would let a V2
change affect V1 production.

**No Railway resource has been created, inspected, or modified. This ADR records the
intended layout so Phase 8A can verify it, nothing more.**

## Decision

Railway is the only cloud platform for V2. Do not evaluate Render, Fly.io, Heroku,
AWS, GCP, Azure, or Vercel unless the owner changes this decision.

Planned layout, subject to the Phase 8A preflight and explicit per-resource
authorization:

- One **new** Railway project (working name `OpsRecovery V2`), separate from V1.
- A dedicated `demo` environment. Railway's default `production` environment stays
  empty — no deployment, datastore, domain, secret, or autodeploy.
- Five services: `v2-web`, `v2-worker`, `v2-beat`, `v2-postgres`, `v2-redis`.
- Only `v2-web` gets a public domain. Worker, beat, PostgreSQL, and Redis stay
  private with no TCP proxy; connections use Railway private networking and
  reference variables.
- Root Directory `/`, empty Watch Paths (the repository is V2-only), branch
  `v2-commercial-cleaning`.
- GitHub autodeploy **disabled** on web, worker, and beat for the first hosted demo:
  a push would otherwise start three independent deployments with no ordering
  guarantee.
- Only `v2-web` runs the pre-deploy migration command; worker and beat never migrate.
- Region US East (Virginia) — the first market is the DMV — with all services
  co-located.

No `railway.toml` or `railway.json` is created: Railway deprecated Config as Code
and new services cannot opt in. Railway IaC (`.railway/railway.ts`) is out of scope
because applying it mutates remote infrastructure; proposing it later requires a
separate infrastructure-management ADR.

## Alternatives considered

- **Reuse the existing V1 Railway project.** Rejected outright: shared datastores,
  variables, domains, and deploy triggers put V1 production at risk.
- **A second cloud provider.** Rejected: no requirement justifies the learning and
  operational cost.
- **Config as Code.** Not available — deprecated for new services.
- **Railway IaC.** Rejected for now: applying it mutates remote infrastructure,
  which conflicts with the owner-reviewed, per-resource authorization model.

## Consequences

- Docker, standard PostgreSQL, standard Redis, and environment-based configuration
  keep local and Railway behaviour reproducible. Portability is a side benefit, not
  a commitment to a second cloud.
- Service settings live in the Railway UI/API, so they must be mirrored into a
  redacted `docs/RAILWAY_CONFIG.md` ledger (Phase 8) or they are undocumented.
- Manual, ordered releases: migrate and verify web, then worker, then the single
  beat replica.
- **Verified risk for Phase 8A:** Railway's PostgreSQL template currently defaults to
  PostgreSQL 16, not 18. The image tag must be pinned to `:18` or the local/remote
  major versions diverge. Railway's PG18 service also inherits the image's
  `VOLUME=/var/lib/postgresql`, so the mount path must be checked before relying on
  persistence.

## Security/privacy impact

The isolation requirements are the security control. Secrets are entered by the
owner through Railway's protected Variables UI and sealed where supported; Claude
never reads or enters a secret value. Deployment is additionally gated on evidence
that V1's tracked credentials were rotated and purged under a separate,
owner-controlled security plan.

## Migration/rollback impact

Nothing is provisioned. Rollback at this stage is deleting this ADR. Post-deploy
rollback (expand-only migrations, ordered service rollback, one beat writer) is
specified in the master prompt's Phase 8 and belongs to `docs/runbooks/rollback.md`,
which is created in Phase 8 and not before.

## Validation evidence

None yet, and none is possible before Phase 8A. Phase 1 produced no Railway
artifact; `railway.toml`/`railway.json` are deliberately absent from this repository.
