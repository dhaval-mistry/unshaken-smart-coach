# Exercise API design

**Status: proposal for owner review; not implemented.** This is the canonical
contract for issues [#21](https://github.com/dhaval-mistry/unshaken-smart-coach/issues/21)
and [#22](https://github.com/dhaval-mistry/unshaken-smart-coach/issues/22).
Use the [shared HTTP/access rules](foundation.md#private-access-and-error-boundary)
and [database model](../database/design.md). Paths, transport fields, result
limits and technical error codes here need review; provider rights and the
authentication prerequisite cannot be inferred from this proposal.

## Approved constraints and dependencies

A user can discover/use only their own custom exercises. Stored shared/provider
exercises and live provider matches are distinct sources. Search is on demand,
never a startup/full-catalog import. Provider outage must not hide available
stored matches or present an incomplete result as complete.

Custom creation stores nonblank name, selected active category, deliberately
selected active body part, and verified ownership. Names may repeat. None is an
explicit real body-part choice. Bodyweight offers reps or duration; other
categories retain their approved kind. Weight is not required to define an
exercise. Effective exercise kinds require the planned #30 migration; current
main has only category kinds and captured session kinds.

#14 supplies existing choices. Private routes wait for a separately approved,
implemented Google/Microsoft identity boundary; client-supplied user IDs never
select an owner. #21 provider persistence additionally waits for the rights
record below. No custom edit/delete, account-linking, sample administration,
bulk import or UI is added by these stories.

## Proposed endpoint summary

| Method/path | Action | Result |
|---|---|---|
| `GET /api/v1/exercises/search` | Search stored records and explicitly request live search | `200` app-owned items plus explicit provider availability |
| `POST /api/v1/provider-exercises` | Select and, only if allowed, retain a provider exercise | `201` stored exercise, or `200` existing provider identity |
| `POST /api/v1/exercises` | Create a private custom exercise | `201` exercise identity and classification |

These are application contracts, not claimed ExerciseDB vendor endpoints.
Provider credentials and provider request construction remain backend-only.

## Search and provider selection

### Read-only search proposal

Require a nonblank `q` and an explicit `live=true|false` query option.
Proposed technical bounds: trimmed query length 1–100 characters and at most
50 stored and 50 live results per request. These are reviewable safety limits,
not approved provider quotas or a promise of complete catalog pagination.
Unknown query fields/body are rejected with `422 invalid_request`. Do not
search all user data when a query is absent.

Filter custom ownership in the database query before serialization, not after
fetching a mixed-user result. Use bound parameters and app-controlled matching;
a search string is data, never SQL, telemetry text or an authorization scope.
The exact text-ranking/pagination policy remains D7; do not imply a partial
bounded result is an exhaustive catalog.

Proposed response (synthetic example):

```json
{
  "items": [
    {
      "source": "stored",
      "id": "11111111-1111-4111-8111-111111111111",
      "name": "Synthetic squat",
      "category_id": 1,
      "body_part_id": 9,
      "measurement_kind": "reps"
    }
  ],
  "provider": {"status": "unavailable", "reason": "timeout"},
  "truncated": false
}
```

Provider status is `not_requested`, `available` or `unavailable`; reasons use
fixed safe categories, not raw exception messages. Live items use
`source: "live_provider"` and a backend-defined selection reference, not a
fictional stored UUID or an unfiltered vendor payload. Expose only reviewed
app-owned fields. Do not claim a vendor result has a valid application category,
body part or kind until the adapter validates that mapping. Invalid items
cannot become partially persisted exercises.

When live search fails, return stored matches with the explicit unavailable
state; an empty items array still carries that state. Proposed distinction:
an unavailable provider with a working local query can return `200`;
an unavailable application database returns the shared
`503 database_unavailable` rather than pretending local matches are empty.
A malformed provider response counts as live unavailable unless individually
validated items can be reported without implying a complete result.

Proposed budgets: a three-second total provider-call budget and a five-second
end-to-end search budget including the local read. Allocate remaining time
rather than adding independent full-length waits. Cancel/close requests and
connections on deadline. Final provider-specific retries/quota handling must
come from verified documentation; do not retry a whole search indefinitely.
Routine verification uses deterministic provider stubs, not paid/live calls.

### Rights record before retaining a selection

Record the selected provider/version, official terms URL/date, permitted
fields and uses, attribution, media handling, retention/cache duration,
deletion obligations and whether historical snapshots may retain names or
measurements. Permission to display a result is not permission to save its
raw payload, media, or workout snapshots permanently.

If persistence is allowed, the selection operation resolves/revalidates the
backend selection reference, maps it to allowed fields and writes
`exercises` plus `provider_exercises` atomically. Never trust a client-supplied
URL/payload/category as already verified. Use the existing unique
(provider_name, provider_exercise_id) identity and return the existing row on
a valid repeated selection, without duplication or unauthorized overwrite.
Do not hold a database transaction/connection open while waiting for the vendor.
Retention expiry must not erase retained workout performance or silently break
template/history links; any conflict between provider deletion obligations and
approved historical retention requires owner/legal-term resolution before storage.

If terms prohibit retention, do not write restricted fields. Whether a selected
live result can be used without persistence is an unresolved product behavior,
not a reason to invent transient exercise rows or a new cache table. Block that
selection path with a documented safe outcome until D7 is resolved; stored
search can remain independently implementable.

Use the existing provider tables only where the approved fields fit. A need for
a retention/audit field discovered from verified terms requires a separately
reviewed schema change; #21 does not silently expand #30's migration.

## Create a private custom exercise

Proposed request:

```json
{
  "name": "Plank",
  "category_id": 4,
  "body_part_id": 6,
  "measurement_kind": "duration"
}
```

Proposed response: `201` with the generated exercise UUID, trimmed name,
category/body-part IDs and effective kind. It does not expose another user's
ownership or provider secrets. The server supplies `source_type=custom` and
the verified creator; request fields such as `created_by_user_id` are rejected.

For Bodyweight require an explicit reps/duration choice. For other categories
derive the kind from the selected category and reject a supplied mismatch.
Validate active choices within the transaction so a concurrent deactivation
cannot produce an invalid form choice. Insert the base exercise and its custom
subtype in one transaction; failure rolls back both. The database's subtype and
owner checks are additional enforcement, not a replacement for route authorization.
No name de-duplication, provider/model request or sample insertion occurs.

Possible errors under the shared safe envelope:

| Status/code | Situation |
|---|---|
| `401 authentication_required` | Verified identity unavailable |
| `404 not_found` | An addressed private record is unavailable to this caller |
| `422 invalid_request` | Blank name, unknown/inactive choices, missing Bodyweight kind, incompatible kind or unsupported input |
| `503 database_unavailable` | Expected database connection/timeout failure |
| `500 internal_error` | Unexpected programming/storage failure |

## Catalog edits and historical meaning

Changing an existing exercise kind is outside #22. The owner approved D2 in the
Solution Architect follow-up on 2026-11-11: reject a kind change while any saved
live template references that exercise. Every live reference must first be
explicitly removed or replaced through a complete valid template update;
creating a new exercise is preferred. Never convert live targets or rewrite
captured session kinds or completed performance. A compatible change to an
unreferenced exercise still needs a separately authorized edit/admin workflow.
Atomic conversion of referenced templates would require a separate future
product/design approval. Assisted Bodyweight duration is not implicitly added
by the Bodyweight exception.

## Verification required

Use synthetic users A/B, disposable PostgreSQL and provider stubs. Verify
ownership both through search and direct IDs; caller-ID forgery cannot change
scope. Exercise the explicit None choice, repeated names, both Bodyweight
kinds, inactive/unknown choices and transaction rollback. Test provider success,
empty/truncated results, timeout/unavailable, malformed mapping, denied
persistence, repeated selection and storage failure. Inspect returned fields,
safe telemetry, attribution/retention handling and OpenAPI together.

These are future acceptance checks, not results executed by this design task.
The [owner decision table](workouts.md#owner-decisions-and-approval-checklist)
records approved D2 and tracks unapproved D7 and identity dependencies.
