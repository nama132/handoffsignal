# Phase 0A — Customer/data evidence gate and route selection

**Date:** 2026-08-27  **Write permission:** analysis only; no application code.
**Owner instruction:** *"Proceed with Phase0A as we need a demo to get an interview."*

This is the most important document in this directory. It records **why the product is
scoped the way it is** and, just as importantly, **what this build cannot prove**.

## The decision

**Route B — capped synthetic concept, one thin vertical slice: Journey B, "completed but
not invoiced."**

The owner's stated reason is the specification's own Route B trigger, near-verbatim:
*"The owner may explicitly choose a concept-first route when a demo is needed to obtain
interviews."*

Route B **does not validate the market.** It authorizes a synthetic proof intended to
enable interviews, nothing more.

## Evidence available at the time of the decision

| Route A precondition | Held? |
|---|---|
| Five serious workflow interviews (owner / operations / finance) | **0** |
| At least one current-state workflow walkthrough | **0** |
| Sanitized column lists or sample exports | **0** |
| Documented per-system identifiers and how staff reconcile them today | **none** |
| A named queue owner and one repeated target exception | **none** |
| A design partner willing to define a pilot metric | **none** |

Route A's preconditions were not met. That absence is exactly what Route B exists for —
and exactly what caps it. **Every field, enum, threshold and CSV column in this build is
provisional until interviews validate it.**

## Why Journey B rather than A or C

| Slice | Gets a call | Build cost vs the 8–12 day cap | Wedge demonstrated | Verdict |
|---|---|---|---|---|
| **B — completed but unbilled** | Moderate | **8–12 days** | **Highest** — cross-system reconciliation is the actual wedge | **Chosen** |
| A — late/no-show + replacement | Highest | **15–20 days** — needs all the omitted worker/shift/time models *plus* all of Phase 5 | Low–moderate: schedule and time usually live in one system | Rejected on cost |
| C — failed inspection | Low | 7–9 days | Low — episodic, already owned by the incumbent's inspection app | Rejected on value |

Journey B tests the cross-system revenue hypothesis without building dispatch, messaging,
worker eligibility, or the decision-scope locking machinery.

## What is deliberately not built

Journeys A and C are **unbuilt, with no placeholder behaviour**. The specification is
explicit that a read-only stub would itself be a violation.

| Not built | Belongs to |
|---|---|
| `Worker`, `Shift`, `TimeEntry`, `WorkerAvailabilityWindow` | Journey A |
| `QualificationType`, `SiteRequirement`, `WorkerQualification`, `WorkerSiteAuthorization` | Journey A |
| `QualityEvent`, corrective actions, client-notification state | Journey C |
| `SiteOperationalRule` | Both — every field is an attendance or quality input |
| `workers_eligibility`, `scheduled_shifts`, `time_entries` importers | Journeys A and C |
| Phase 5 (recommendation and handoff) | Journey A |
| Phase 7 polish, Phase 8 Railway hosting | Blocked until evidence expansion |

Asking for an unimplemented importer raises `ContractNotImplemented` rather than
returning an empty result, so a missing feature can never resemble a successful no-op.

## The provisional source and crosswalk design

Four data sources. Sources 2 and 3 are deliberately the *same* fictional vendor emitting
two feeds under distinct keys, exercising the rule that `system_key` must disambiguate
them.

| `system_key` | Domain | Authoritative for |
|---|---|---|
| `contract_register` | contracts | contract status/dates, obligation identity, billing basis, `uninvoiced_delay_days` |
| `opsplatform_workorders` | service events | work-order status, completion, billable flag, authorization, approved amount |
| `opsplatform_idmap` | identity crosswalk | alias→canonical mapping proposals only |
| `ar_ledger` | invoice status | invoice/payment identity, amounts, dates, posted/void/disputed |

Three structurally different identifier dialects — differing by prefix alone would prove
nothing:

| Canonical object | `contract_register` | `opsplatform_workorders` | `ar_ledger` |
|---|---|---|---|
| Meridian Property Group | `MERIDIAN-PG` | `00084120` | `80000042-1739216455` |
| Meridian Business Center | `MBC-NOVA-01` | `00093011` | `80000107-1739216455` |
| The $480 work order | *(none)* | `00518774` | **deliberately absent** |

Two absences carry the demonstrative weight:

1. **The accounting ledger carries no work-order identifier on any row.** Reconciliation
   must therefore run on confirmed customer/site crosswalks plus service date. If the
   invoice carried the operations key, the demo would be a join on a shared column and
   would prove nothing.
2. **One crosswalk row is omitted on purpose** — the Potomac site in the accounting
   dialect — so a dependent invoice row quarantines and blocks reconciliation readiness.

## Highest-risk assumptions

Ranked by probability-wrong × cost-if-wrong. **A1, A2 and the two cheapest kill criteria
cost roughly nothing to test and should run alongside the build, not after it.**

| # | Assumption | Kill signal | Cost to test |
|---|---|---|---|
| **A1** | **A working demo is what unblocks interviews** | 30–40 no-demo outreach attempts yield ≥2 serious calls → the bottleneck was never the artifact | **0 build days** |
| **A2** | Operations and accounting are genuinely separate systems for the buyer | Interviewees say completion auto-generates the invoice | one question per call |
| **A3** | Completed-but-unbilled is *material and repeated*, not occasional | Owners cannot recall an instance, or recall one a year | free |
| **A4** | **Someone will declare bounded, complete coverage on every import** | An operations manager, shown the real import form, cannot say which sites and dates the file completely covers | show them the form |
| **A5** | The four exports can be produced repeatably without high manual effort | Nobody can produce `sites_contracts`-equivalent data at all | ask for a sample |
| **A6** | Cross-system identity is a felt pain, not our design artifact | "We match on customer name and it works" | free |

**A4 is the most invisible risk in the build.** The synthetic fixtures ship a pre-checked
coverage manifest, so the hardest real-world step is already done and a prospect never
sees it. Put the *real* import form in front of at least two interviewees.

## Two findings that must not be buried

1. **A1 is unmeasured.** The specification only says a thin concept *"may support
   interviews"* — permissive, never causal. Zero interviews today is equally consistent
   with no prospect list or the wrong outreach channel.
2. **Route B contains an ordering defect.** It forbids Railway deployment and skips the
   polish phase, so the deliverable is an unpolished localhost application with no demo
   runbook. It cannot be emailed, linked, or self-served — it can only be shown *after*
   a call already exists. **The artifact built to get interviews requires an interview to
   show it.**

Neither changes the route. They change what should run alongside it:

- Run 30–40 no-demo outreach attempts during the build, to test A1 for free.
- Read the incumbent API terms — free, about a day, zero code.
- Pre-write the sanitized-export ask; it is the highest-value conversion available in any
  call, and the one most likely to be forgotten when a call goes well.

## What this demo can and cannot test

Of the nine kill criteria in the specification:

- **Genuinely testable: 2** — whether the incumbent already resolves this in one system,
  and whether detected items can be supported by contract and authorization evidence.
  The invoice-ready evidence checklist doubles as a discovery script.
- **Partially testable: 3** — queue ownership, whether operators review before acting,
  and whether a buyer will commit. All testable by *asking*, not by showing.
- **Structurally untestable: 4** — including the two cheapest: whether the required
  exports can actually be produced, and whether incumbent API terms permit the use.
  Both are answerable **without writing any code**.

A synthetic demo's false-positive rate is zero by construction. **A clean demo is not
evidence of precision.**

## Things that must be said out loud to every prospect

Volunteer these before the walkthrough, not defensively when cornered:

1. This is synthetic — every company, site and dollar figure is invented.
2. This is a concept, not a validated product: zero customers, zero pilots, no design partner.
3. It reads a daily CSV export. It is not real-time and will not be called that.
4. It does not connect to QuickBooks or any system you use, and no vendor integration
   will be claimed until an authenticated, permitted one has been tested.
5. It never writes to your systems, never sends a message, never creates an invoice.
6. One journey is built. Late/no-show and failed-inspection are deliberately unbuilt.

And whenever a number appears: **"That $480 is a candidate value — contract-supported
work that may be billable. It is not recovered revenue, not invoiced, and not
collected."** The four financial stages never add up. The amount came from the customer's
own work order; what the product produced is the *gap*.

The honest closing line, and the most useful one: *"If your work orders and your
invoicing live in the same system, don't buy this."* Their answer is the most valuable
data in the call.

## Scope-creep traps refused during the build

| Trap | Why it was refused |
|---|---|
| Seeding the full synthetic dataset from section 31 | It was written for the three-journey demo and contradicts the Route B omissions |
| Handling quality `record_type` values "since the parser needs the columns anyway" | Only work-order rows are authorized; quality types are rejected with a row error |
| Deploying to Railway "so I can send a link" | Explicitly forbidden, and the most seductive trap because it appears to serve the goal |
| Polishing to prospect-facing quality | Phase 7 is skipped and cannot be entered from a one-journey concept |
| Building a QuickBooks-shaped CSV mapper "so it feels real" | Edges toward an integration claim the specification forbids |

## The mandatory stop after Phase 6

The moment the Route B revenue subset passes its gate, everything stops. Forbidden at
that point: any second journey, Phase 5, Phase 7 polish, Phase 8 hosting, and any change
to a CSV contract.

The owner must obtain **five or more serious workflow interviews** across owner,
operations and **finance** roles — finance is non-optional, because that is the only role
that can run the evidence checklist — plus **one sanitized source walkthrough**.

A disconfirmation report then recommends keep / change / kill / pivot. Only then does
`Approve evidence expansion plan` authorize a **read-only** plan, with E1–E4 each
separately approved.

**Route B is structured so that a kill decision costs roughly twelve days, not six
months. That is the point of it.**
