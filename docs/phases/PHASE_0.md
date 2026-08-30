# Phase 0 — Read-only preflight

**Date:** 2026-08-27  **Write permission:** none. No file, branch, environment, or
install was created. **Exit:** owner proceeded to Phase 0A.

## Purpose

Confirm scope, repository safety, tool availability, and technical assumptions without
changing anything — so that the first line of code is written against a verified
environment rather than an assumed one.

## What was checked, and what was found

### Workspace and repository boundary

| Check | Result |
|---|---|
| Working directory | `/Users/amanabbas/Desktop/Project AI/V2/ops-recovery-v2` — matches the specification exactly |
| Contents before Phase 1 | The master prompt only |
| Git | **Not initialized.** The parent directory is not a repository either, so there was no risk of adopting a parent repo |
| Other instruction files | None — no `AGENTS.md`, `CLAUDE.md`, `.claude/`, `.cursorrules`, `.github/` |
| Parent folder | Contains only an unrelated Demosmith file, as the specification warned |

### V1 reference (read-only)

The external V1 repository exists at
`/Users/amanabbas/Desktop/Project AI/A.I. Product/shiftcare-prod`.

**Baseline recorded for later proof of non-modification: `main` @ `a6cc7d5`, working
tree clean (0 dirty or untracked entries).** This baseline is re-verified at the end of
every phase.

Top-level names were inventoried **by name only**. Three denylisted files are present
and were never opened: `.env`, `CREDENTIALS.md`, `shiftcare.db`. A legacy
`railway.json` also exists there and stays untouched.

### Toolchain

Machine: macOS 15.6, arm64.

| Tool | Required | Found at preflight |
|---|---|---|
| Python 3.13 | yes | **missing** — only system Python 3.9.6 |
| `uv` | yes | **missing** |
| Docker + Compose | yes | 29.2.1 / v5.1.0, daemon running |
| Git | yes | 2.50.1 |
| Homebrew | — | 6.0.16 |
| Railway CLI | Phase 8 only | missing (not needed yet) |

Ports 5432/5433, 6379/6380, 8000/8001 and 8080 were all free.

The missing Python and `uv` were reported as a blocker requiring owner approval rather
than silently installed. They were installed at the start of Phase 1 with that approval.

## Stack verification

Every version claim in the specification was re-checked against primary documentation
rather than accepted from memory, then **independently re-verified by a second pass**
that tried to refute each claim. 214 claims were checked: 213 confirmed, 1 partially
refuted (a minor attribution error about which gunicorn release dropped the eventlet
worker — irrelevant here).

The conclusion was that **no incompatibility requires changing the specified stack**,
but four findings changed how it had to be assembled:

| Finding | Consequence |
|---|---|
| `kombu` 5.6.2 constrains `redis-py` to `<6.5` | **Never pin `redis-py` directly.** `celery[redis]` resolves 6.4.0; an explicit `redis>=7` pin makes `uv lock` unsolvable |
| The `postgres:18` image moved `PGDATA` to `/var/lib/postgresql/18/docker` and its `VOLUME` to `/var/lib/postgresql` | A Compose file using the pre-18 `/var/lib/postgresql/data` mount silently fails to persist the cluster |
| PostgreSQL 18 libpq support landed in psycopg 3.2.8 | Pin `psycopg[binary]>=3.3` — above Django 5.2's own floor of 3.1.8 |
| Railway's PostgreSQL template defaults to **PG 16** | Phase 8 must pin the `:18` tag or local and remote majors diverge |

Also recorded: Django 5.2 left mainstream support on 2025-12-03 and now receives
security and data-loss fixes only, until April 2028. Python 3.13 was chosen over 3.14
because Celery, kombu, billiard and gunicorn all lack 3.14 classifiers.

## Top five risks identified

1. **Toolchain absent** — mitigated by an owner-approved, isolated `uv`-managed install.
2. **The kombu / redis-py version ceiling** — mitigated by never pinning `redis-py`.
3. **PostgreSQL 18 edge cases** — Django 5.2's CI tests 16 and 17, not 18. Mitigated by
   running the full suite against 18 and applying migrations to a fresh database every
   phase.
4. **Django 5.2 is security-only** — pinned `>=5.2.17,<5.3`; upgrade target is 6.2 LTS.
5. **Specification breadth versus solo capacity** — the largest risk. Mitigated by the
   Phase 0A route decision, which is what capped the build.

## What Phase 0 deliberately did not do

No branch, no directory, no environment, no install, no Railway authentication, no
reading of any denylisted file, and no execution of anything in V1.
