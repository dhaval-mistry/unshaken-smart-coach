# Database foundation

The reviewed design from [PR #17](https://github.com/dhaval-mistry/unshaken-smart-coach/pull/17)
is implemented on main through PR #18 for stories #3 and #4 using Python 3.12, uv,
SQLAlchemy Core, Psycopg 3, and Alembic. No changes have been applied to the
owner's existing development database by this design-only task.

- [Design and confirmed requirements](design.md)
- [ER diagram](er-diagram.md) and [matching Mermaid source](er-diagram.mmd)
- [Verified setup and migration commands](../setup/backend.md)

The current 13 application tables contain 128 columns. Alembic has its separate
revision-tracking table. Two migrations create the schema/guards and install
stable master data: eight categories and eleven body parts, including None.

In the current migration, Cardio requires time and distance, Duration requires
time, and the other six categories require reps. The owner later approved
duration-only Bodyweight exercises, complete templates before Save, and a
Cancel choice: save completed work as partial history or discard an active
draft after warning that completed work will be deleted. These changes need a
new migration and API work; they are **not yet implemented**. Weight remains
optional. One workout per user may be in progress. Permanent source deletion
keeps retained history. Completed and saved-partial history remains protected.

The owner has resolved minimum-set completeness: every saved template exercise
requires at least one valid set, on initial creation and later updates. The
[migration contract](design.md#issue-30-migration-contract-for-review) describes
the proposed successor after `0002_master_records`, compatibility/conflict
handling and disposable-only rollback. Its
[privileged discard boundary](design.md#privileged-discard-boundary-proposal)
and live-template kind-edit restriction are proposals requiring review.
The owner-decision section of
[PR #33](https://github.com/dhaval-mistry/unshaken-smart-coach/pull/33) records
that minimum-set approval, but the closed, unmerged pull request is not
implemented/accepted main behavior. PR #34 merged the design package, and open
issues #23, #24, #25 and #30 now record the resolved minimum-set rule. No new
migration or SQL was included by the design merge.

The [API index](../api/README.md) maps all open API stories to contracts and
their migration/auth/provider prerequisites. Dependent APIs use #30's future
schema; they do not each create another foundation migration.

Validation uses fresh disposable PostgreSQL 17 databases and synthetic data.
Checks cover schema/keys/indexes/seeds, measurement/ownership/source failures,
atomic snapshot capture, deletion/history preservation, concurrent starts and
completion retries, version preflight, rollback refusal, fresh rollback/upgrade,
seed conflicts/custom-record preservation, and target-confirmation behavior.
The setup guide records limits, including serialized guarded writes and
service-level optional-update version preflight. No real provider/model calls
or application APIs are required.

Applying migrations to an existing/local/shared target needs its owner's
separate approval of the displayed nonsecret target, current revision and plan.
Never reset a database or delete a volume as normal setup.
