# PR #37 code review

## Review target

- Pull request: <https://github.com/dhaval-mistry/unshaken-smart-coach/pull/37>
- Story: <https://github.com/dhaval-mistry/unshaken-smart-coach/issues/30>
- Base commit: `4124446328fae4556a4f5fc60836943b63d01c25`
- Reviewed commit: `4d2ad25486ea069a580e47a037752b1531c49002`
- Head branch: `feature/30-workout-schema-follow-up-v2`
- Review environment: synthetic data on a uniquely named, temporary PostgreSQL 17 container; the container was removed after each check.

## Overall conclusion

**Changes are required before Tester review or merge.** The migration order, D1 privileged-discard implementation, cancellation behavior, history preservation, disposable-database controls, and frozen `0001`/`0002` revisions are generally aligned with issue #30. However, one high-severity blocking defect allows an ordinary writer to bypass the new D2 and complete-template checks by controlling `search_path`. An independent PostgreSQL 17 reproduction committed an incompatible live state. A second blocking acceptance defect discards the conflict counts already computed by migration preflight, so operators do not receive the required safe category/count evidence.

## Findings ordered by severity

### F1 — Temporary-schema shadowing bypasses D2 and the complete-template guard

- Severity: **High**
- Blocking: **Yes**
- File and line: `backend/migrations/versions/0003_workout_guards.sql:58` and `backend/migrations/versions/0003_workout_guards.sql:242-250` (the same unsafe resolution pattern appears throughout both replacement trigger functions)
- Problem: `usc_write_guard()` and `usc_validate_database()` use unqualified application relations and helpers without a fixed safe `search_path`. These trigger functions execute with the ordinary writer's path. A role with table-write privileges and the normal ability to create temporary tables can put `pg_temp` first and shadow `template_exercises`, `workout_templates`, `template_sets`, and `exercises`. The D2 reference lookup and deferred whole-database validation then inspect the attacker's empty temporary relations instead of the protected `public` relations.
- Practical impact: an ordinary direct writer can change a Bodyweight exercise referenced by a saved live template from `reps` to `duration` while the template retains `target_reps=8` and no duration target. This violates approved D2, defeats complete-template/effective-target integrity, and can cause later workout capture or use of that template to fail or reinterpret intended targets.
- Code-path evidence:
  1. The before trigger checks `EXISTS (SELECT FROM template_exercises ...)` at line 58 with no schema qualification.
  2. The deferred validator likewise reads unqualified template and exercise relations at lines 242-250.
  3. On a fresh migrated PostgreSQL 17 database, a synthetic ordinary role was granted only `USAGE` on `public` and `SELECT, INSERT, UPDATE, DELETE` on public tables. After `SET ROLE`, it created empty temporary tables with `LIKE public.<table>`, set `search_path=pg_temp,public`, and executed a schema-qualified update of the real exercise.
  4. The update committed successfully. A query against the real public relations returned `measurement_kind='duration'`, `target_reps=8`, and `target_duration_seconds=NULL` for the same referenced exercise.
  5. The temporary PostgreSQL container was stopped and removed. No existing/shared database was used.
- Suggested correction: schema-qualify every application relation and application helper used by both replacement trigger functions (for example, `public.template_exercises`, `public.workout_templates`, and `public.usc_fail`). Also give the functions an explicitly fixed safe path such as `pg_catalog, public, pg_temp`, with `pg_temp` last and only a trusted application schema in between. Add an ordinary-role regression test that creates shadow temporary relations, sets an attacker-controlled path, and proves D2 and template completeness still reject the write. Review the entire replacement bodies rather than repairing only the first D2 query, because the deferred validator must not be made vacuous through the same technique.

### F2 — Upgrade preflight suppresses the required conflict category/count evidence

- Severity: **Medium**
- Blocking: **Yes** (issue #30 acceptance/design contract)
- File and line: `backend/migrations/versions/0003_workout_follow_up.py:41-65`
- Problem: preflight computes five separate conflict counts, but `if any(conflicts)` raises one generic message that includes neither the triggered category nor its count. The calculated evidence is discarded.
- Practical impact: the upgrade rolls back safely, but the database owner cannot tell whether the blocker is an empty template, zero-set exercise, invalid target, pending row in cancelled history, or incompatible Bodyweight category value, nor how many conflicts require separately authorized correction. This does not meet `docs/database/design.md:247-253` or issue #30's requirement for safe conflict evidence and encourages ad hoc/private investigation before a safe retry.
- Code-path evidence: the result row at lines 41-59 contains all five counts. Lines 60-65 reduce it to a Boolean and emit only a combined list of possible causes. `test_legacy_conflicts_abort_without_repair` checks only that the text contains `conflicts`, so the missing evidence is not detected.
- Suggested correction: alias each count, retain only nonzero categories, and raise a credential-free message containing category names and counts (not row identifiers or values). Add migration tests that assert distinct evidence for empty-template, zero-set, invalid-target, cancelled-pending, and incompatible-category preflight failures while also asserting complete rollback.

## Observed defects

F1 and F2 above are actionable observed defects. F1 was reproduced on genuine PostgreSQL 17; F2 follows directly from the executed preflight result being discarded before the raised error. No other blocking or actionable implementation defect was identified in the reviewed diff.

## Missing coverage

- No test sets an attacker-controlled `search_path` and shadows application relations from an ordinary table-writer role; this gap allowed F1 despite the permission/spoofing test.
- Legacy-upgrade tests do not independently exercise the empty-template-parent and zero-set-exercise preflight categories, and they do not assert category/count evidence; this gap allowed F2.
- D2 has positive coverage for an unreferenced exercise and negative/concurrency coverage for a referenced exercise, but no explicit test removes/replaces every live reference in one complete template transaction and then proves the compatible kind change can proceed.
- Bounded migration lock behavior is present in code, but the suite does not hold a conflicting lock and assert the upgrade fails within the configured bound with full rollback.

These are coverage gaps, not additional demonstrated product defects.

## Optional suggestions

No optional style-only suggestions. The report intentionally limits findings to behavior with practical acceptance, integrity, or operational impact.

## Checks performed

- Read `AGENTS.md`, root `README.md`, `agents/roles/code-reviewer.md`, `agents/roles/_shared.md`, current issue #30, PR #37, and the merged D1/D2 design in `docs/database/design.md` and `docs/api/workouts.md`.
- Confirmed PR #37 is open, targets the supplied base, and has the supplied head commit.
- Reviewed all changed lines in the eight-file base-to-head diff and relevant surrounding migration, trigger, operation, schema, CLI, and test paths.
- Confirmed `0003_workout_follow_up` follows `0002_master_records` and the tracked `0001`/`0002` migration files are unchanged by the PR.
- Traced migration locking/preflight/backfill/DDL/downgrade, D1 privilege and gate restoration, D2 serialization, template completeness, cancellation, snapshot/history protection, and disposable cleanup paths.
- Ran Python 3.12 bytecode compilation for `app`, `migrations`, `tests`, and `scripts`: passed.
- Ran `backend/scripts/verify_database.py` independently against a temporary PostgreSQL 17 container: **159 passed**, one third-party Starlette deprecation warning, revision reached `0003_workout_follow_up`, Alembic reported no drift, and the verifier removed its container.
- Ran the independent F1 PostgreSQL 17 proof described above and removed its temporary container.
- Searched open repository issues for matching `search_path`, preflight, or migration-conflict defects; no separate duplicate defect report was found beyond story #30.
- Confirmed no API, authentication, UI, provider integration, deployment, or D3-D9 implementation appears in the PR diff.

## Blocked checks

- No migration was applied to an existing, development, or shared database, by instruction.
- No GitHub Bug issue, PR review comment, Project 5 item, label, assignment, or PR metadata was created or changed, by instruction. Ready-to-post content is provided below instead.
- There is intentionally no runtime application-role grant in this story, so a future trusted backend grant and deployment role hierarchy cannot be validated in this review.
- The review did not merge or deploy the pull request.

## Residual risks

- The full suite passing does not mitigate F1 because current tests use the normal path and do not shadow relations. All affected trigger queries should be audited after the fix, not only the demonstrated D2 statement.
- Migration and trigger functions serialize writes through a global advisory key. The code uses bounded lock waiting during migration, but runtime contention/performance under realistic workload is not established by this review.
- Downgrade is deliberately disposable-only. Its compatible and incompatible paths passed the supplied tests, but it is not authorization to downgrade any retained database.

## Ready-to-post Bug issue content

### Bug 1

**Title:** Ordinary writer can bypass workout D2 guards with temporary-schema shadowing

**Body:**

> ## Category
> Observed defect
>
> ## Related work
> - Story: #30
> - Pull request: #37
> - Reviewed commit: `4d2ad25486ea069a580e47a037752b1531c49002`
>
> ## Severity and impact
> High. An ordinary role with table-write privileges can bypass D2 and complete-template effective-target validation by shadowing unqualified application relations in `pg_temp`. A saved template can retain a reps target while its referenced exercise commits as duration.
>
> ## Expected behavior
> An effective-kind change must fail while any saved live template references the exercise, including direct writers with a caller-controlled `search_path`.
>
> ## Actual behavior
> The write commits because `usc_write_guard()` and `usc_validate_database()` resolve unqualified relations through the caller's temporary schema.
>
> ## Reproduction / evidence
> 1. Upgrade a disposable PostgreSQL 17 database to `0003_workout_follow_up`.
> 2. Create a valid reps-based Bodyweight exercise and saved template with `target_reps=8`.
> 3. Grant a synthetic role `USAGE` on `public` and normal CRUD privileges on public tables; do not grant the D1 function.
> 4. `SET ROLE` to that writer, create empty temporary `workout_templates`, `template_exercises`, `template_sets`, and `exercises` tables using `LIKE public.<table>`, then set `search_path=pg_temp,public`.
> 5. Run `UPDATE public.exercises SET measurement_kind='duration' WHERE id=<referenced exercise>` and commit.
> 6. The real public rows show `duration`, `target_reps=8`, and no duration target.
>
> ## Relevant locations
> - `backend/migrations/versions/0003_workout_guards.sql:58`
> - `backend/migrations/versions/0003_workout_guards.sql:242-250`
>
> ## Suggested correction
> Schema-qualify all application relations/helpers in both replacement trigger functions, fix their safe search path with `pg_temp` last, and add an ordinary-role temporary-shadow regression test.
>
> ## Environment
> PostgreSQL 17 temporary container, synthetic data only; container removed after reproduction.

### Bug 2

**Title:** Workout migration preflight discards conflict category counts

**Body:**

> ## Category
> Observed defect
>
> ## Related work
> - Story: #30
> - Pull request: #37
> - Reviewed commit: `4d2ad25486ea069a580e47a037752b1531c49002`
>
> ## Severity and impact
> Medium. Upgrade preflight aborts safely, but it does not provide the required safe conflict category/count evidence needed to plan a separately authorized correction.
>
> ## Expected behavior
> Report each nonzero preflight category and count without exposing row data.
>
> ## Actual behavior
> `upgrade()` computes five counts, reduces them with `any(conflicts)`, and raises one generic list of possible causes with no triggered category or count.
>
> ## Code-path evidence
> - Counts are computed at `backend/migrations/versions/0003_workout_follow_up.py:41-59`.
> - They are discarded at `backend/migrations/versions/0003_workout_follow_up.py:60-65`.
> - The migration test asserts only the word `conflicts`.
>
> ## Suggested correction
> Alias and report nonzero categories/counts, and add separate empty-template, zero-set, invalid-target, cancelled-pending, and incompatible-category rollback assertions.
>
> ## Environment
> Reviewed against issue #30 and `docs/database/design.md:247-253`; no existing/shared database used.

## Manual handoff

The **Developer must fix F1 and F2 before Tester review**. After the fixes, rerun the full disposable PostgreSQL 17 verifier and add focused regression tests for temporary-schema shadowing and category/count preflight evidence. A separately requested Code Reviewer should then review the fix commit; only after that should the human hand the PR to Tester. Do not merge PR #37 in its current state.
