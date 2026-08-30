# Phase records

One document per executed phase. These explain **what was done and why**; they are not
the status ledger and not the specification.

| Document | Purpose |
|---|---|
| `docs/phases/PHASE_*.md` | Narrative record: what was built, what was decided, what was rejected, what evidence exists |
| `docs/BUILD_STATUS.md` | Terse ledger: current phase, approvals, migrations, commands run, next gate (master prompt section 42) |
| `docs/adr/` | One decision per file, with alternatives and consequences (section 43) |
| `CLAUDE_V2_COMMERCIAL_CLEANING_MASTER_PROMPT.md` | The governing specification. Where it and these records disagree, the spec wins |

## Index

| Phase | Document | Status |
|---|---|---|
| 0 — Read-only preflight | [PHASE_0.md](PHASE_0.md) | Complete |
| 0A — Evidence gate and route selection | [PHASE_0A.md](PHASE_0A.md) | Complete — **Route B chosen** |
| 1 — Isolated V2 foundation | [PHASE_1.md](PHASE_1.md) | Complete, pending review |
| 2 — Tenant identity, RBAC, operational primitives | [PHASE_2.md](PHASE_2.md) | Complete, pending review |
| 3 — CSV import, preview, commit, source history | [PHASE_3.md](PHASE_3.md) | Complete, pending review |
| 4 — Exception engine, state machine, inbox | [PHASE_4.md](PHASE_4.md) | Complete, pending review |
| 5 — Recommendations and handoffs | — | **Skipped** by the Route B scope override (line 2690) |
| 6 — Route B revenue slice: evidence, approval, export, ledger | [PHASE_6.md](PHASE_6.md) | Complete, pending review |
| 5 — Replacement recommendation | **skipped under Route B** | Journey A is unbuilt |
| 6 — Revenue slice only | not started | Requires `Approve Route B Revenue Slice` |
| 7, 8 — Polish, Railway hosting | **blocked** | Cannot be entered from a one-journey concept |

After Phase 6 there is a **mandatory evidence stop**. See [PHASE_0A.md](PHASE_0A.md).

## Reading order for someone new

1. `PHASE_0A.md` — why the product is scoped the way it is, and what it cannot prove
2. `PHASE_0.md` — the environment and the stack, and why those versions
3. `PHASE_1.md` → `PHASE_3.md` — how the system was built up
4. `docs/DATA_DICTIONARY.md` — what the data means
