# API design and review map

**Review status: proposed architecture for owner review.** Confirmed product
decisions remain approved; new paths, payloads, permission boundaries and
recommendations below are proposals until accepted. This document does not mark
issues Ready, assign work or approve a migration.

**Implemented baseline:** main `a4cafb8` has the FastAPI application, shared JSON
errors/headers, `GET /health/live`, shared telemetry helpers, and database
revisions `0001_database_foundation` and `0002_master_records`. Readiness,
lookups, authenticated exercise/workout APIs and the #30 follow-up migration
are not implemented on that baseline. Closed, unmerged PR #33 is not accepted
implementation and is not the basis of this design-only revision.

## Canonical design homes

| Document | Owns |
|---|---|
| [Foundation](foundation.md) | Common HTTP/access rules, readiness, lookup reads, deadline/connection ownership and safe telemetry |
| [Exercises](exercises.md) | Stored/live search, provider selection and retention gates, private custom creation |
| [Workouts](workouts.md) | Template Save, start, completion, Finish choice, cancellation, history and previous performance |
| [Database design](../database/design.md) | Physical representation, invariants, migration/rollback, privileged discard boundary and compatibility |
| [Observability](../architecture/observability.md) | Approved SDK → Alloy → Loki/Mimir/Tempo route, privacy, retention and delivery evidence |

Designs describe user actions, not a CRUD endpoint for every table. Database
reads/writes do not by themselves justify new tables or migrations.

## Issue-to-design coverage

The open-issue review covered all 13 issues: #13–15 and #21–30. GitHub remains
the work/approval record; this map is a contract/dependency index, not a copy of
issue status. All acceptance criteria must be verified in the implementation PR.

| Issue | Design section | Database effect and gate |
|---|---|---|
| [#13](https://github.com/dhaval-mistry/unshaken-smart-coach/issues/13) readiness | [Check the running backend](foundation.md#check-the-running-backend), [deadline and cleanup](foundation.md#database-deadlines-and-connection-ownership) | Existing lookup reads; no #30 dependency |
| [#14](https://github.com/dhaval-mistry/unshaken-smart-coach/issues/14) form choices | [Load choices](foundation.md#load-choices-for-the-new-exercise-form) | Existing ordered active lookup reads; after #13 |
| [#15](https://github.com/dhaval-mistry/unshaken-smart-coach/issues/15) real API signals | [Logs, metrics and traces](foundation.md#logs-metrics-and-traces) | Instrument real reads; no application-table writes/new stack |
| [#21](https://github.com/dhaval-mistry/unshaken-smart-coach/issues/21) search/select provider exercise | [Search and provider selection](exercises.md#search-and-provider-selection) | Reads, plus conditional provider-catalog writes; auth and provider terms gate |
| [#22](https://github.com/dhaval-mistry/unshaken-smart-coach/issues/22) custom exercise | [Create a private custom exercise](exercises.md#create-a-private-custom-exercise) | Existing exercise/custom rows using #30 effective-kind field; auth gate |
| [#23](https://github.com/dhaval-mistry/unshaken-smart-coach/issues/23) template Save/edit | [Save a complete template](workouts.md#save-a-complete-template) | Existing template rows; #30 completeness guard and auth |
| [#24](https://github.com/dhaval-mistry/unshaken-smart-coach/issues/24) template start | [Start a workout](workouts.md#start-a-workout) | Existing session/snapshot children; #30 and auth |
| [#25](https://github.com/dhaval-mistry/unshaken-smart-coach/issues/25) complete set/rest | [Complete a set once](workouts.md#complete-a-set-once) | Existing actual/event fields; #30 kind guards and auth |
| [#26](https://github.com/dhaval-mistry/unshaken-smart-coach/issues/26) Finish/optional update | [Finish and optional template update](workouts.md#finish-and-optional-template-update) | Existing finish/choice/template fields; mapping decision D3 still open |
| [#27](https://github.com/dhaval-mistry/unshaken-smart-coach/issues/27) Save/Discard cancel | [Cancel with Save or Discard](workouts.md#cancel-with-save-or-discard) | Existing rows with #30 cancelled-set/scoped-discard changes; decisions D4/D5 |
| [#28](https://github.com/dhaval-mistry/unshaken-smart-coach/issues/28) retained history | [Read saved history](workouts.md#read-saved-history) | Read-only stored snapshots/actuals; history-producing flows first |
| [#29](https://github.com/dhaval-mistry/unshaken-smart-coach/issues/29) prior performance | [Read previous performance](workouts.md#read-previous-performance) | Read-only cross-workout original identity; result semantics D6 |
| [#30](https://github.com/dhaval-mistry/unshaken-smart-coach/issues/30) schema follow-up | [Migration contract](../database/design.md#issue-30-migration-contract-for-review) | Sole owner of the new schema/guard migration; not API/auth/UI implementation |

## Approved decisions retained

- Each saved template has at least one exercise; **each included exercise has
  at least one valid set**, both on creation and later updates. The owner
  explicitly resolved the zero-set question in this discussion. References to
  it as still open in GitHub need a human-approved record update, not a new answer.
- Required targets follow effective kind: positive reps, positive duration, or
  positive duration plus distance. Timed Bodyweight needs no dummy reps.
- Weight stays optional; zero with kg/lb is explicit, not missing. New sets use
  the existing 120-second rest default; completion starts rest only once.
- Only one workout per user is active. Snapshot and completed performance survive
  subsequent source edits/deletion; no completed-history correction feature is added.
- Ask once at normal Finish: No leaves the source unchanged; Yes updates the
  user's personal source or creates a personal copy of a shared sample. Completed
  history survives optional-update failure. Exact mapping remains undecided.
- Confirmed active-draft Discard removes even completed draft work; Cancel → Save
  retains completed work and cancels pending sets. No automatic template update
  is added to partial Save.

## Approval and implementation order

Review the bounded technical proposals and open decisions in the
[owner decision table](workouts.md#owner-decisions-and-approval-checklist).
Approval of this document's structure does not silently answer an open product
question. Record an explicit choice before the affected behavior is implemented.

Public #13 → #14 → #15 can proceed independently of #30 and private sign-in.
After design approval, #30 precedes effective-kind/template/cancellation APIs.
Verified identity is a prerequisite for every private route; its session/account
design and implementation require an approved authentication story. With that
prerequisite, exercise choice/#22 and #23 lead to #24 → #25 → #26/#27 → #28 → #29.
Provider persistence in #21 waits for verified rights, even if other APIs are ready.

No implementation should create a separate migration for each dependent API.
New schema requirements discovered in later designs must be reviewed explicitly.
Use the [developer reading path](../README.md), current setup commands and
implementation evidence; design examples are not proof an endpoint exists.
