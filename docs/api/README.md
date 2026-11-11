# API design and review map

**Review status: mixed.** Confirmed product decisions and the issue #30 D1/D2
constraints are approved; new API paths, payloads and later-story decisions
remain proposals until accepted. The owner explicitly approved D1/D2 in the
Solution Architect follow-up on 2026-11-11, closing #30's remaining architecture
gates. Issue #30 can be marked Ready for a separately requested Developer. This
document does not assign work, implement a migration or authorize applying one.

**Implemented baseline:** application code through `a4cafb8` has the FastAPI
application, shared JSON errors/headers, `GET /health/live`, shared telemetry
helpers, and database revisions `0001_database_foundation` and
`0002_master_records`. Readiness, lookups, authenticated exercise/workout APIs
and the #30 follow-up migration remain unimplemented. PR #34 merged this design
package into main at `5a10833`; merging documentation did not implement those
contracts. Closed, unmerged PR #33 is not accepted implementation.

**GitHub review snapshot (2026-11-11):** the repository has 13 open issues,
#13–#15 and #21–#30. Their descriptions are aligned with this merged design,
with D1/D2 now approved and D3–D9 retained as later-story gates. The owner-authored
[PR #33 description](https://github.com/dhaval-mistry/unshaken-smart-coach/pull/33)
records the later decision that every saved template exercise needs at least
one valid set on creation and update. That pull request was closed without
merge, so its code and reported tests are not accepted implementation; its
explicit owner-decision record is retained as product context. Issues #23, #24,
#25 and #30 now record that resolved product rule without treating any proposed
migration mechanism as approved.

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
  explicitly resolved the zero-set question in the owner-decision section of
  [PR #33](https://github.com/dhaval-mistry/unshaken-smart-coach/pull/33).
  Issues #23, #24, #25 and #30 now record that approved rule; do not reopen it
  during implementation.
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
- D1: Discard uses one narrowly scoped trusted database capability. PUBLIC and
  ordinary writers cannot invoke or spoof it; it deletes only an explicitly
  confirmed, owner-matched `in_progress` draft and never retained history.
- D2: changing an exercise's effective kind is rejected while any saved live
  template references it. References must first be explicitly removed/replaced;
  no targets or historical workout measurements are converted or rewritten.

## Approval and implementation order

Review the approved #30 constraints and remaining later-story decisions in the
[owner decision table](workouts.md#owner-decisions-and-approval-checklist).
D1/D2 approval makes #30 ready for separate implementation; it does not answer
D3–D9 or authorize their affected API behavior.

Public #13 → #14 → #15 can proceed independently of #30 and private sign-in.
Issue #30 now has approved architecture and precedes effective-kind/template/
cancellation APIs; implementation still requires a separately requested role.
Verified identity is a prerequisite for every private route; its session/account
design and implementation require an approved authentication story. With that
prerequisite, exercise choice/#22 and #23 lead to #24 → #25 → #26/#27 → #28 → #29.
Provider persistence in #21 waits for verified rights, even if other APIs are ready.

No implementation should create a separate migration for each dependent API.
New schema requirements discovered in later designs must be reviewed explicitly.
Use the [developer reading path](../README.md), current setup commands and
implementation evidence; design examples are not proof an endpoint exists.
