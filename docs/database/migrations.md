# Database migrations

Migrations are numbered database changes tracked in Git, run with
[Alembic](https://alembic.sqlalchemy.org/) through uv. Migration `0001` creates
the 13 tables in [design.md](design.md). All commands run from `backend/`.

## Setup

```text
cd backend
uv sync
```

Python 3.12 is declared in `backend/.python-version` and `pyproject.toml`;
dependencies are locked in `backend/uv.lock`.

The database target comes only from private environment variables, read from
the repository-root `.env` (never committed) or your shell. In order of
precedence:

1. `DATABASE_URL` (a placeholder such as `<<YOUR_DATABASE_URL>>` is ignored), or
2. `POSTGRES_USER`, `POSTGRES_PASSWORD`, `POSTGRES_DB`, `POSTGRES_PORT`
   (and optional `POSTGRES_HOST`, default `localhost`).

Copy `.env.example` to `.env` as described in [postgresql.md](../setup/postgresql.md).
Never paste a password or full connection string into an issue, PR or log.

## Step 1: review the plan (read-only)

```text
uv run python -m app.db plan
```

Prints the nonsecret host, port and database name, the server version, the
current migration version, the latest version, any existing tables and the
planned changes. It writes nothing.

## Step 2: owner approves the exact target, then apply

The owner of the database checks the plan's target, then re-runs with that
target spelled out:

```text
uv run python -m app.db upgrade --approve-target HOST:PORT/DATABASE
```

Without an exact match the command exits with an error and changes nothing.
Upgrades only add objects, so existing data is preserved. All of `0001` runs in
one transaction: if anything fails (for example a table named `users` already
exists), PostgreSQL rolls back and the database is unchanged. The migration
uses plain `CREATE` statements and never replaces existing tables.

Running the command again at the latest version reports "nothing to do" and does
not recreate tables. Normal setup never drops tables or deletes volumes.

## Tests

```text
uv run pytest
```

The tests connect to the server named by your private settings only to create
and drop a uniquely named `unshaken_disposable_*` database; the configured
database is never modified. They need a role allowed to create databases, as
the Compose role is. To keep the test server separate from your own data, point
`DATABASE_URL` at a throwaway PostgreSQL 17 container.

They cover: empty-to-latest upgrade; the 13 tables and columns; foreign-key
deletion actions and indexes; invalid relationships; another user's private
exercises (templates, shared samples, sessions, later ownership changes);
incorrect source links; invalid weight/unit pairs; invalid completion and rest
timestamps; template-update outcome consistency; history being unaffected by
later plan edits; the plan/approval commands; data preservation; and rollback.

## Rollback limitations

`downgrade()` in `0001` **drops all 13 tables and their data**. It is exposed only
through Alembic and the test suite, not through the `app.db` commands, and is
tested only on disposable databases:

```text
uv run alembic downgrade base   # DESTRUCTIVE: disposable databases only
```

Do not run it against a database holding data you want to keep. Rollback of a
shared or real database needs a separate backup and the owner's written
authorization. There is no data-preserving rollback for table creation.

## Implementation notes and unresolved design points

The design is still marked draft and lists open decisions. These choices were
made in review of this branch and are recorded here; the owner should copy them
into `design.md` when the design is approved:

- **Master records are not inserted** (separate story). `exercise_categories`
  and `body_parts` are created empty.
- **`updated_at` is maintained by a database trigger** (decision 10): a shared
  `trg_set_updated_at()` function runs before every update on `users`,
  `exercises`, `workout_templates`, `workout_sessions` and `session_sets`.
- **One in-progress workout per user** (decision 6): the partial unique index
  `ux_workout_sessions_one_in_progress_per_user` rejects a second one. Completed
  and cancelled sessions are unlimited.
- **Retained-row removal and source-link deletes** (decision 9): removed sets stay as rows
  marked `removed_at`/skipped and are never physically deleted. Source-link and applied-template
  foreign keys are RESTRICT, with `copied_from_template_id` SET NULL. Approved by the story
  requester during review of this branch; the design owner should still record it in `design.md`.
- **No duration/distance columns** (decision 4, deferred to a later migration). Completed sets require
  `actual_reps` unless the session exercise's category snapshot is `Cardio` or
  `Duration`, so those are not forced into reps. This relies on the lookup names
  in the design's seed list.
- **No default for `users.status` or `preferred_weight_unit`** (decision 8): the
  service must choose explicitly.
- Cross-table rules are deferred constraint triggers, checked at commit, so a
  service can insert parent and child rows in one transaction in any order.
  A violation raises SQLSTATE `23514`. Snapshot columns of sessions, session
  exercises and session sets cannot be changed after capture.
- Deleting a referenced source (template, template exercise or set, exercise,
  user) fails with a foreign-key error; archive or deactivate instead.
