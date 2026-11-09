# UNShaken Smart Coach: database design

Status: **DRAFT FOR REVIEW**, not a deployed schema.

This design incorporates the owner's confirmed requirements and subsequent answers: ask about template updates once at workout finish; choosing Yes for a sample creates a personal copy. Unanswered product rules remain open below. Repository main baseline: 1e0129d2ee2d17430342139ad4c764e3fbb15a70. Existing compose.yaml uses PostgreSQL 17; docs/setup/backend.md selects Python/FastAPI with uv but backend code and migration tooling are not scaffolded. New field names and enforcement mechanisms below are technical design proposals for review, not evidence of implementation.

## Scope and confirmed requirements

- Google and Microsoft sign-in.
- Personal and sample workout templates; ordered exercises and sets.
- Reps per set, optional lifting weight, and rest after each completed set with default 120 seconds.
- Users can change weights and reps and add sets during a workout. Ask once at finish whether to save changes to the source template. No leaves the template unchanged; Yes updates a personal source or creates a personal copy of a sample. Always save the completed workout independently of template-update success.
- Catalog combines ExerciseDB exercises and only the user's own private custom exercises, default ascending by name with name filtering. Shared samples cannot reference private exercises.
- Ad hoc workouts need no template and are saved in history; saving them as a new template is outside this change.
- Preserve starting targets, suggested weights/units, and actual performance separately. Later template/catalog edits must not rewrite history.
- Newly added template and session sets default to 120 seconds of rest. Completing a set starts rest atomically; retries preserve the original timer start.
- Weight is optional for every category. NULL means missing; zero is an explicitly supplied value. Reps may be empty while editing a set; completed rep-based sets require valid actual reps.
- Custom exercise requires name, category and body part, using the screenshot options.
- Browser and mobile use the same database/API.

AI coaching, nutrition, billing, raw personal health profiles, and telemetry storage are not part of these 13 tables. Store telemetry in the selected observability systems, not this transactional schema.

## Model principles

Exercise definitions, reusable plans and performed sessions are separate. A workout contains exercises; Dumbbell Squat is an exercise, Afternoon Workout is a workout. Completed records retain snapshots and actual values. No destructive history rewrites on template changes.

UUID primary keys for application entities; SMALLINT stable lookup keys; TIMESTAMPTZ timestamps; decimal weights, never floating point. All unmarked nullable decisions below are explicit. PostgreSQL defaults do not automatically update updated_at: choose an application hook or trigger in implementation.

## ER diagram

See [diagram source](er-diagram.mmd) or [GitHub-rendered diagram](er-diagram.md). The two exercise-source relationships are mutually exclusive: exactly one is required per exercise; Mermaid alone does not express this invariant.

## Table dictionary

Each dictionary row describes exactly one physical database column. For example,
created_at and updated_at are separate TIMESTAMPTZ columns, not one combined
value. JSONB muscle-list columns are also separate from each other; each column
contains its own array.

exercise_categories and body_parts are master/reference tables. Seed their
approved values through versioned migrations. Additional master records may be
added later with new stable IDs; adding a new column is a separate schema
change made through a new migration. Existing data may require a backfill before
new NOT NULL or other constraints can be enabled. Do not modify an already
applied migration to introduce a later column. No extra master-table columns
are required or approved by this documentation clarification.

### users

| Column | PostgreSQL type | Rules and meaning |
|---|---|---|
| id | UUID | PK |
| display_name | VARCHAR(150) | Required |
| contact_email | VARCHAR(320) | Nullable; not the login identity key |
| preferred_weight_unit | VARCHAR(2) | Required; kg or lb; initial default needs agreement |
| status | VARCHAR(20) | active or disabled |
| created_at | TIMESTAMPTZ | Required; record creation time |
| updated_at | TIMESTAMPTZ | Required; last update time; maintenance mechanism remains open |

Contact email is not globally unique. Authentication uses user_identities, not an email match. Body weight and meal-planning profiles are outside this workout-tracking schema. Remove the proposed user-level rest default: no configurable default is required. Every new set receives the fixed default of 120 seconds.

### user_identities

| Column | PostgreSQL type | Rules and meaning |
|---|---|---|
| id | UUID | PK |
| user_id | UUID | Required FK users |
| provider | VARCHAR(20) | google or microsoft |
| issuer | TEXT | Required; validated OIDC issuer |
| subject | TEXT | Required; validated OIDC subject within that issuer |
| email_at_login | VARCHAR(320) | Nullable |
| email_verified | BOOLEAN | Nullable if not supplied |
| last_login_at | TIMESTAMPTZ | Nullable |
| created_at | TIMESTAMPTZ | Required |

Unique (provider, issuer, subject). Do not store provider passwords. Do not automatically link accounts by email. Validated identity tokens are an authentication-layer responsibility. Application sessions/refresh-token persistence requires a separate decision.

### exercise_categories

| Column | PostgreSQL type | Rules and meaning |
|---|---|---|
| id | SMALLINT | PK; stable seed identifier |
| name | VARCHAR(50) | Required; unique |
| sort_order | SMALLINT | Required; unique |
| is_active | BOOLEAN | Required; default true |

Seeds, in order: Barbell; Dumbbell; Machine/Other; Bodyweight; Assisted Bodyweight; Reps Only; Cardio; Duration.

### body_parts

| Column | PostgreSQL type | Rules and meaning |
|---|---|---|
| id | SMALLINT | PK; stable seed identifier |
| name | VARCHAR(50) | Required; unique |
| sort_order | SMALLINT | Required; unique |
| is_active | BOOLEAN | Required; default true |

Seeds, in order: None; Arms; Back; Cardio; Chest; Core; Full Body; Legs; Olympic; Other; Shoulders. None is an explicit selection, not SQL NULL. The form must require a deliberate selection.

### exercises

| Column | PostgreSQL type | Rules and meaning |
|---|---|---|
| id | UUID | PK |
| name | VARCHAR(200) | Required; trimmed, nonblank |
| category_id | SMALLINT | Required FK exercise_categories |
| body_part_id | SMALLINT | Required FK body_parts |
| source_type | VARCHAR(20) | provider or custom |
| description | TEXT | Nullable |
| is_active | BOOLEAN | Required; default true |
| created_at | TIMESTAMPTZ | Required; record creation time |
| updated_at | TIMESTAMPTZ | Required; last update time; maintenance mechanism remains open |

Names are not globally unique. A provider/custom source subtype must exist exactly once and match source_type. Use an atomic service transaction plus a deferred database constraint trigger if enforcing the invariant in PostgreSQL. A plain CHECK cannot enforce rows in another table.

### provider_exercises

| Column | PostgreSQL type | Rules and meaning |
|---|---|---|
| exercise_id | UUID | PK and FK exercises |
| provider_name | VARCHAR(50) | Required; exercisedb initially |
| provider_exercise_id | TEXT | Required; provider identifier |
| provider_body_part | TEXT | Nullable; original provider body-part label |
| provider_equipment | TEXT | Nullable; original provider equipment label |
| instructions | JSONB | Nullable; array of ordered instruction strings |
| target_muscles | JSONB | Nullable; array of primary target muscle labels |
| secondary_muscles | JSONB | Nullable; array of secondary muscle labels |
| media_references | JSONB | Nullable; array of URL/metadata objects |
| raw_payload | JSONB | Nullable; original exercise response object |
| last_synced_at | TIMESTAMPTZ | Required |
| provider_updated_at | TIMESTAMPTZ | Nullable; only if available |

Unique (provider_name, provider_exercise_id). These are internal proposed fields, not a verified ExerciseDB contract. Confirm API version, payload and caching/media terms. Validate JSON shapes for populated fields. Cache exercise records, never credentials/headers. Preserve provider values separately from local classification.

### custom_exercises

| Column | PostgreSQL type | Rules and meaning |
|---|---|---|
| exercise_id | UUID | PK and FK exercises |
| created_by_user_id | UUID | Required FK users |

Name/category/body part live only in exercises. A custom exercise consists of
one exercises row (including category_id and body_part_id) plus one
custom_exercises row with the same UUID in exercise_id. The latter stores only
custom-specific ownership. Retrieve category/body part by joining
custom_exercises.exercise_id to exercises.id, then the master tables through
exercises.category_id and exercises.body_part_id. Both classifications are
required for custom exercises; duplicating these FKs in custom_exercises would
create two competing values to keep synchronized. Insert both rows transactionally. Custom exercises are private to their creator; no visibility column or sharing option exists. Only the creator may retrieve or use one, including through direct IDs, template references, and session references. Personal templates may reference only provider exercises or custom exercises owned by the template owner. Sessions may reference only provider exercises or custom exercises owned by the session user. Shared samples may reference provider exercises only. Validate ownership on reads and writes; an unguessable UUID does not establish permission.

### workout_templates

| Column | PostgreSQL type | Rules and meaning |
|---|---|---|
| id | UUID | PK |
| owner_user_id | UUID | Nullable FK users; required for personal, null for sample |
| template_type | VARCHAR(20) | sample or personal |
| name | VARCHAR(150) | Required; trimmed, nonblank |
| notes | TEXT | Nullable |
| copied_from_template_id | UUID | Nullable FK workout_templates |
| version | INTEGER | Required; default 1; > 0 |
| archived_at | TIMESTAMPTZ | Nullable |
| created_at | TIMESTAMPTZ | Required; record creation time |
| updated_at | TIMESTAMPTZ | Required; last update time; maintenance mechanism remains open |

Check ownership/type consistency. Starting a sample captures its plan directly into session history; do not create a personal copy merely to record a workout. At finish, Yes creates a personal copy; No leaves the shared sample unchanged. Never modify a shared sample with user-specific performance. Increment version on approved relevant edits. Sample administration remains open; no sample editing permission is granted here.

### template_exercises

| Column | PostgreSQL type | Rules and meaning |
|---|---|---|
| id | UUID | PK |
| template_id | UUID | Required FK workout_templates |
| exercise_id | UUID | Required FK exercises |
| position | INTEGER | Required; > 0 |
| notes | TEXT | Nullable |

Unique (template_id, position). Repeated exercise IDs are allowed. Use deferrable uniqueness or temporary positions when reordering.

### template_sets

| Column | PostgreSQL type | Rules and meaning |
|---|---|---|
| id | UUID | PK |
| template_exercise_id | UUID | Required FK template_exercises |
| set_number | INTEGER | Required; > 0 |
| target_reps | INTEGER | Nullable while editing; > 0 when supplied; duration/distance model OPEN |
| suggested_weight | NUMERIC(10,3) | Nullable; >= 0 |
| weight_unit | VARCHAR(2) | kg/lb; required iff weight supplied |
| rest_seconds | INTEGER | Required; default 120; >= 0 |

Unique (template_exercise_id, set_number). NULL weight means not supplied; zero is explicit. Enforce the paired weight/unit invariant regardless of category. Every newly added set defaults to rest_seconds=120 as a concrete stored value; no configurable user default is introduced. Whether an incomplete template can be used before target reps are filled is OPEN. Completed-session template updates require an explicit Yes.

### workout_sessions

| Column | PostgreSQL type | Rules and meaning |
|---|---|---|
| id | UUID | PK |
| user_id | UUID | Required FK users |
| source_template_id | UUID | Nullable FK workout_templates; original source identity retained |
| source_template_version | INTEGER | Nullable; captured when starting from template |
| name_snapshot | VARCHAR(150) | Required |
| status | VARCHAR(20) | in_progress, completed, cancelled |
| started_at | TIMESTAMPTZ | Required |
| finished_at | TIMESTAMPTZ | Required for terminal status; NULL while in_progress; >= started_at |
| notes | TEXT | Nullable |
| template_updated_at | TIMESTAMPTZ | Nullable; successful template update time |
| template_update_requested | BOOLEAN | Nullable until choice; true=Yes, false=No; NULL for not applicable |
| template_update_status | VARCHAR(20) | Required; not_applicable, pending, declined, applied, conflict |
| applied_template_id | UUID | Nullable FK workout_templates; successful personal target, including sample copy |
| created_at | TIMESTAMPTZ | Required; record creation time |
| updated_at | TIMESTAMPTZ | Required; last update time; maintenance mechanism remains open |

Capture immutable history at start and actual values during execution. Ad hoc sessions have NULL source_template_id/version and not_applicable update status. Template-backed sessions capture source ID and a positive version together and begin pending. Complete workout persistence must not be rolled back by a declined, conflicting, or failed template update. Multiple in-progress sessions policy is OPEN; do not add a partial unique index without agreement. The choice/outcome state and retry behavior are detailed below.

### session_exercises

| Column | PostgreSQL type | Rules and meaning |
|---|---|---|
| id | UUID | PK |
| session_id | UUID | Required FK workout_sessions |
| exercise_id | UUID | Required FK exercises |
| source_template_exercise_id | UUID | Nullable FK template_exercises |
| name_snapshot | VARCHAR(200) | Required |
| category_snapshot | VARCHAR(50) | Required; exercise category name captured for this session |
| body_part_snapshot | VARCHAR(50) | Required; body-part name captured for this session |
| position | INTEGER | Required; > 0 |
| notes | TEXT | Nullable |

Unique (session_id, position). Retain snapshots after catalog changes. Validate source lineage: a referenced template exercise must belong to this session's source template and use the same exercise. Enforce in a transaction and optionally a constraint trigger.

### session_sets

| Column | PostgreSQL type | Rules and meaning |
|---|---|---|
| id | UUID | PK |
| session_exercise_id | UUID | Required FK session_exercises |
| source_template_set_id | UUID | Nullable FK template_sets |
| set_number | INTEGER | Required; > 0 |
| target_reps_snapshot | INTEGER | Nullable for ad hoc sets; > 0 when supplied |
| suggested_weight_snapshot | NUMERIC(10,3) | Nullable; original suggested weight at session start; >= 0 |
| suggested_weight_unit_snapshot | VARCHAR(2) | Nullable; kg/lb iff suggested weight snapshot is supplied |
| actual_reps | INTEGER | Nullable until completion; > 0 when supplied; required for completed |
| actual_weight | NUMERIC(10,3) | Nullable; >= 0 |
| weight_unit | VARCHAR(2) | kg/lb; required iff actual weight supplied |
| status | VARCHAR(20) | pending, completed, skipped |
| completed_at | TIMESTAMPTZ | Required iff completed |
| rest_seconds | INTEGER | Required; default 120; >= 0 |
| was_in_starting_plan | BOOLEAN | Required; true for sets captured at start, false for later additions |
| removed_at | TIMESTAMPTZ | Nullable; logical removal only; original row and snapshots retained |
| rest_started_at | TIMESTAMPTZ | Nullable before completion; set atomically with completed_at on completion |
| rest_ended_at | TIMESTAMPTZ | Nullable; if supplied, requires rest_started_at and must be >= it |
| created_at | TIMESTAMPTZ | Required; record creation time |
| updated_at | TIMESTAMPTZ | Required; last update time; maintenance mechanism remains open |

Unique (session_exercise_id, set_number). Validate source lineage: source set belongs to the referenced template exercise and same exercise. Original target reps and suggested weight/unit snapshots are immutable; later session additions have was_in_starting_plan=false and no original suggested targets. NULL original reps are also permitted for incomplete starting plans until template readiness rules are agreed. A completed rep-based set requires actual_reps and completed_at. No actual value is inferred from a target. All categories allow optional actual weight with a paired unit.

Design proposal for preserving removed sets without new tables: retain every starting set row and its original set_number, mark removal through removed_at, and use skipped status for an unperformed removed set. Do not reuse removed set numbers; added sets receive new numbers. Removal cannot erase a completed performance row. Skipping also retains the row and snapshots. Do not physically delete a session exercise that contains starting-plan or performed sets. Exercise removal/reordering and editing completed records remain open; this change does not grant those operations. Persisting a separate current draft-reps value is not specified; actual_reps is the submitted performance, never a target copy.

## Workflow and transaction boundaries

### Login
Validate the provider login and resolve (provider, issuer, subject). Create or locate the application user atomically. Never trust an email alone as identity. Do not log tokens.

### Catalog
Read provider exercises plus custom_exercises.created_by_user_id=current_user only, before searching, counting, or paginating. Apply the same ownership checks on direct access and when attaching an exercise to a template or session. Reject cross-user custom references and all custom references in shared samples. Proposed ordering: lower(name), id for stable pagination. Numeric/accent sorting remains open; duplicate names remain allowed as specified. Provider refresh upserts by stable external ID, preserving internal exercise UUIDs. Archive removed source exercises instead of deleting history. Local category mappings must be reviewed; raw provider body-part values may not match screenshot categories.

### Start workout
Within one transaction, verify access to a personal or sample template; capture its ID/version and ordered exercise/category/body-part names, target reps, suggested weight/unit, and concrete rest settings. Mark starting sets was_in_starting_plan=true. Never use a running session as a live view of the template. Ad hoc sessions begin with NULL source references; users add only exercises from their permitted catalog and enter sets/reps/optional weights, with no template creation. New sets have rest_seconds=120 and was_in_starting_plan=false. Authentication/ownership must be enforced on every query and direct resource reference. No authentication implementation is included in this design task.

### Complete set and rest
Allow NULL reps while editing; completing a rep-based set explicitly submits positive actual reps and optional weight/unit. Atomically lock or conditionally transition a pending set to completed, set completed_at and rest_started_at to the same server timestamp, and retain the selected rest_seconds. A retry of an already-completed set returns its existing result and original timestamps; it must not restart rest or overwrite performance. Changed completion data needs an explicitly agreed correction operation, not retry semantics. Calculate remaining rest from rest_started_at + rest_seconds; do not write every second. Rest adjustment, rest skip, pause/resume, and completion undo remain OPEN. A rest countdown can finish in the client without a required database write to rest_ended_at.

### Previous values
Query prior completed sessions for the same user and exercise, excluding the current session. Match set numbers as a proposal only; exact historical scope and repeated-exercise matching are OPEN. Display the prior unit or convert explicitly; never show kg as lb without conversion. Do not store a separate previous_weight copy that can become stale.

### Finish and template update
Ask once at finish whether changes should be saved to the source template. Persist the terminal session, actual performance, and explicit choice in one transaction. Do not infer Yes or automatically update from recent weights. Ad hoc workouts have no template-update question and remain not_applicable; saving as a new template is excluded.

Proposed outcome model:

| Outcome | Choice and behavior |
|---|---|
| not_applicable | No source template; choice, applied target and update timestamp NULL |
| pending | Template-backed; choice NULL before the finish answer, or true while an approved write awaits processing/retry |
| declined | Choice false; source unchanged; applied target and update timestamp NULL |
| applied | Choice true; personal source updated or personal sample copy created; applied_template_id and template_updated_at required |
| conflict | Choice true; source no longer matches captured version or is unavailable; history saved; no applied target/timestamp |

Perform the optional template write in a separate atomic transaction after session completion is durable. Lock the session and relevant source, compare source_template_version, recheck ownership, and apply the agreed weight/reps/added-set mapping. A personal source is the target; a shared sample is never modified and Yes creates a personal copy with copied_from_template_id pointing to the sample. Record applied_template_id, applied status and template_updated_at in the same transaction as that write/copy. Retain the session's ORIGINAL source ID/version even when a new personal copy is created.

Repeated finish/apply requests reuse the saved choice and terminal result; an already applied result returns the same target and never creates a second sample copy. Transient optional-write errors leave pending with choice=true for retry and must not erase completed history; report pending truthfully. A changed version yields conflict without silent overwrite. Conflict resolution, abandoned retry handling, missing weights, skipped/removed sets, exact addition mapping, unit conversion, and older sessions finishing late remain OPEN. Changing a saved answer requires a separately agreed operation. Cancelled-session template-update behavior remains OPEN. No full template-version table is introduced: immutable session snapshots provide starting-plan evidence and source version detects changes.

## Constraints and indexes

- Index every FK that participates in joins/deletion checks; PostgreSQL does not automatically index referencing columns.
- Unique identity key, provider key, per-template/session ordering, and per-exercise set numbers as specified above.
- Enforce allowed statuses, nonblank names, positive populated reps/set numbers/positions and nonnegative weights/rest durations. Target/actual reps may be NULL during editing; completed rep-based sets require actual reps. Duration/distance completion validation remains open.
- Enforce weight/unit pairs for template and session sets; weight NULL requires unit NULL, populated weight requires kg or lb.
- Enforce the suggested_weight_snapshot/suggested_weight_unit_snapshot pair independently of actual_weight/weight_unit. Never require weight based on category.
- Proposed removal constraints: removed_at requires skipped status and NULL actual performance/completed_at; retained original snapshots never change. Removal timestamps must be within the session chronology. Added rows cannot claim starting-plan membership or source-set lineage.
- Enforce template-update outcome/choice/target/timestamp consistency per the outcome table. Only completed sessions may be applied. Source ID/version are populated together, version > 0. An applied target must be personal and owned by the session user. For personal sources it must equal the source ID; for sample sources its copied_from_template_id must match the source. Pending/declined/conflict require a source. The source version is never rewritten after capture.
- Enforce completed_at only for completed sets; validate rest start/end chronology. Set event timestamps relative to session start/finish with service checks or triggers; cross-table CHECKs are insufficient.
- Index workout_templates(owner_user_id, archived_at), workout_sessions(user_id, started_at DESC), and workout_sessions(user_id, status).
- Index exercises(lower(name), id) for ordering; partial-name substring search may require pg_trgm/GIN. Confirm extension availability before using it.
- Avoid speculative indexes on JSONB; add only for demonstrated queries.
- Index custom_exercises(created_by_user_id) for private catalog access and workout_sessions(applied_template_id) for target lineage. Do not add an outcome index without a demonstrated query.
- Ownership/source-subtype/lineage and cross-table chronology require transactional validation and, where approved, deferred constraint triggers or composite FKs; plain row CHECKs are insufficient. Proposed database guards must also cover parent ownership/source changes, not only child inserts. Read access still needs user-scoped queries. No RLS or trigger implementation is claimed here.

## Deletion and history policy (proposed)

| Relationship | Proposed action |
|---|---|
| users to personal data | RESTRICT hard deletion initially; account erasure needs a separately agreed policy |
| exercises to template/session exercise | RESTRICT; use is_active=false |
| lookups to exercises | RESTRICT; deactivate lookup choices |
| exercises to matching provider/custom details | CASCADE only if an unused parent is intentionally removed |
| template to template exercises; exercise entry to planned sets | CASCADE only when no retained session source links prohibit deletion; archive referenced plans/entries instead |
| source template/entry/set links in session tables | Proposed RESTRICT instead of SET NULL; archive referenced source rows to retain ID/version and lineage; requires deletion-policy approval |
| applied_template_id | Proposed RESTRICT; archive applied personal target instead of deleting historical linkage |
| copied_from_template_id | SET NULL |
| session to session exercises; entry to actual sets | RESTRICT by default to protect history; explicit deletion workflow needed |

Foreign keys do not make completed sessions immutable. Application permissions and service rules must prevent unintended updates; consider triggers after edit/undo requirements are settled. Never delete starting sets to represent an in-workout removal; use the proposed logical-removal representation above. Source retention and deletion actions are technical proposals awaiting approval, while preservation of starting-plan evidence and actual performance is confirmed.

## Observability expectations

Add spans for login resolution (without tokens), catalog search, provider sync, session start, set completion and finish/template update. Capture latency, failures and conflict counts. Avoid logging emails, raw user notes, weights, provider credentials or full request bodies. Use opaque request/trace IDs. No per-request telemetry table is proposed.

## Open decisions: resolve before final migrations

Confirmed, not open: custom exercises are creator-only with no sharing option; weight is optional for every category; new sets default to 120 seconds without a configurable user default; completion starts rest atomically and retry cannot reset it; ask once at finish; Yes for a sample creates a personal copy; No never updates a template; completed history is saved independently. Do not reopen these requirements.

Remaining decisions:

1. Custom exercise editing/archive and completed-performance correction policies beyond creator-only access/use.
2. Previous performance across all workouts or only the same template? How to match repeated exercises?
3. Yes supports weights, reps and added sets. Exact mapping for repeated exercises, blank weights, skipped/removed sets, units, version conflict resolution, transient-write retry expiry and older sessions finished late remains open. Cancelled-session update behavior is open.
4. Cardio/Duration are lookup choices: are time/distance fields required now? Do not force duration exercises into reps if time tracking is intended.
5. ExerciseDB version, payload, caching permission, media use and mapping.
6. One or multiple in-progress workouts per user?
7. Timer adjustment, skip, undo and pause/resume behavior.
8. Account linking/session strategy, initial unit preference, sample administration and account deletion policy. Sample-copy-on-Yes is confirmed.
9. Template readiness with empty target reps; removal/reordering of exercises and completed-set correction/undo. Approve the proposed retained-row removal design and source-link deletion actions before migrations.
10. Timestamp maintenance hook/trigger choice, search collation/extensions, and database/service enforcement split.

## Implementation status

Migration `0001` (see [migrations.md](migrations.md)) creates the 13 tables in this design in an empty PostgreSQL 17 database. This design is still a proposal: the open decisions above have not been approved by a human. The migration therefore makes provisional choices, listed under "Implementation notes and unresolved design points" in [migrations.md](migrations.md), which need approval or change before the schema is treated as final. Master records, APIs, authentication, ExerciseDB import and cloud resources are not part of this work. The previously linked codex-handoff.txt is not present in this repository.
