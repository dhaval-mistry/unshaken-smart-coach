# Database foundation

The reviewed design from [PR #17](https://github.com/dhaval-mistry/unshaken-smart-coach/pull/17)
is implemented locally for stories #3 and #4 using Python 3.12, uv,
SQLAlchemy Core, Psycopg 3, and Alembic. No changes have been applied to the
owner's existing development database. Existing/shared database upgrades require separate target approval.

- [Design and confirmed requirements](design.md)
- [ER diagram](er-diagram.md) and [matching Mermaid source](er-diagram.mmd)
- [Verified setup and migration commands](../setup/backend.md)

The current 13 application tables contain 129 columns. Alembic has its separate
revision-tracking table. Revisions 0001/0002 create the schema/guards and install
stable master data: eight categories and eleven body parts, including None.

Successor migration `0003_workout_follow_up` adds effective exercise measurement
kinds: Bodyweight may use reps or duration; other categories retain their kind.
Saved templates require at least one exercise and one valid set per exercise.
Cancel then Save retains completed work and cancels pending sets; confirmed
Discard removes only an owned active draft. Completed and saved-partial history
remains protected. Workout APIs are separate work. Weight remains optional,
one active workout per user is enforced, and permanent source deletion keeps
retained history. Existing incomplete templates or cancelled sessions with
pending sets block migration rather than being silently repaired.

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

