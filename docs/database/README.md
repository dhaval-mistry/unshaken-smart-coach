# Database foundation

The reviewed design from [PR #17](https://github.com/dhaval-mistry/unshaken-smart-coach/pull/17)
is implemented locally for stories #3 and #4 using Python 3.12, uv,
SQLAlchemy Core, Psycopg 3, and Alembic. No changes have been applied to the
owner's existing development database. Local changes are not committed or
published by this task.

- [Design and confirmed requirements](design.md)
- [ER diagram](er-diagram.md) and [matching Mermaid source](er-diagram.mmd)
- [Verified setup and migration commands](../setup/backend.md)

The 13 application tables contain 128 columns. Alembic has its separate
revision-tracking table. Two migrations create the schema/guards and install
stable master data: eight categories and eleven body parts, including None.

Cardio completion requires time and distance; Duration requires time; the other
six categories require reps. Weight is optional for all. One workout per user
may be in progress. Permanent source deletion keeps the starting plan/original
UUIDs and completed performance. Completed-workout/set deletion is not an API
feature; database guards reject destructive history changes.

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

