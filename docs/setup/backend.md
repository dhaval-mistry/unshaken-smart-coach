# Backend database setup

The database foundation uses **Python 3.12**, uv, SQLAlchemy Core, Psycopg 3,
and Alembic. `backend/.python-version` selects the Python minor version;
`backend/pyproject.toml` declares dependencies and `uv.lock` locks them.
The verified interpreter was Python 3.12.10 on Windows. A minimal FastAPI
application with a liveness check is available; see
[Run the API locally](#run-the-api-locally).

The API can run on the host or as the local Compose `backend` service. The
[local backend container design](../architecture/backend-container.md) defines
the implemented image, runtime, security and lifecycle boundaries.

The shared Python telemetry package and synthetic FastAPI/script examples are
now available. Product endpoints remain separate work. See
[telemetry examples](../../backend/examples/README.md) and
[normal signal verification](observability.md#normal-local-verification).

## Prerequisites and uv

Follow [Docker](docker.md) and [PostgreSQL](postgresql.md). Use the existing
root Compose project and root private `.env`; do not create another runtime
PostgreSQL service, virtual-environment convention, or environment file format.

Install uv using one method:

- Windows: `winget install --id=astral-sh.uv -e`.
- macOS with Homebrew: `brew install uv`.
- Other supported methods: [official uv installation guide](https://docs.astral.sh/uv/getting-started/installation/).

Open a new terminal and verify `uv --version`. From the repository root:

```text
cd backend
uv sync --locked
```

uv uses the selected interpreter and local ignored `.venv`. If Python 3.12 is
not installed, use `uv python install 3.12` before synchronization. Commit
reviewed `pyproject.toml` and `uv.lock` together when publishing a change;
never include `.venv` or a real `.env`.

## Private connection settings

Keep the existing `DATABASE_URL` variable in the private root `.env`. The
loader reads that file without overwriting environment variables or files.
The checked-in `.env.example` retains placeholders only. Do not copy it over
an existing private file.

Use a PostgreSQL URL for the intended host, port, database, username and
password. Plain `postgresql://` is normalized internally to the Psycopg driver.
Percent-encode reserved characters in credentials when composing a URL.
Never paste the URL into GitHub, Discord, logs, or verification evidence.

POSTGRES_* settings initialize Docker's database on an empty volume;
DATABASE_URL chooses the backend connection. Editing either does not rename
an existing database, change its password, or authorize a reset.

## Preview before any application-schema changes

The commands below are implemented and were verified on fresh disposable
PostgreSQL 17. They have **not** been applied to the owner's development database.

```text
uv run unshaken-db plan
```

This connects read-only to inspect PostgreSQL's major version and current
Alembic revision, then prints only host, port, database, current revision,
planned migration IDs, and a nonsecret target-confirmation token. It never
prints credentials or a full connection string and does not create tables.

For a fresh database the normal plan is:

1. `0001_database_foundation`: 13 application tables, keys/indexes, checks,
   timestamp/ownership/history/snapshot/measurement guards.
2. `0002_master_records`: stable 8 categories and 11 body parts, including
   explicit None and category measurement kinds.
3. `0003_workout_follow_up`: effective exercise kinds, complete saved-template
   guards, cancelled-set consistency, and narrowly authorized active-draft
   discard while preserving terminal history.

Alembic also owns its separate `alembic_version` tracking table. That is not
a fourteenth application table.

**For an existing/local/shared target, show the plan to its owner and obtain
that target's approval first.** After approval of the displayed target and plan:

```text
uv run unshaken-db upgrade --approve-target TOKEN_FROM_CURRENT_PLAN
```

The command prints and rechecks the target/revision. A missing, wrong, or stale
token exits without applying changes. On head it reports no pending work and
does not recreate tables or duplicate seeds. Keep DATABASE_URL private and
unchanged between preview and execution. Connection failures/conflicts exit
with a safe message; investigate locally without sharing secrets.

These commands do not create a PostgreSQL server/database, import ExerciseDB,
start an API, call a model, or start observability. They create the approved
application schema inside an already existing PostgreSQL 17 database.

## Inspect the installed revision and master records

```text
uv run alembic current
uv run alembic check
```

Both print a nonsecret target summary first. The second compares live schema
against the metadata; it does not prove trigger behavior, which needs the
integration tests. Direct Alembic upgrades also require target approval
(`-x approve_target=TOKEN` before the subcommand). Prefer the wrapper above;
never use raw commands to bypass target review.

Use pgAdmin or psql with your private settings for read-only checks:

```sql
SELECT id, name, sort_order, measurement_kind, is_active
FROM exercise_categories ORDER BY sort_order;
SELECT id, name, sort_order, is_active FROM body_parts ORDER BY sort_order;
```

Migration #2 preserves unrelated records and accepts an exact existing seed
match. A conflicting ID/name/order/value stops the migration without replacing
custom data. Fix conflicts through a separately reviewed change; do not edit an
already applied migration or reset the volume.

## Run the API locally on the host

From `backend/`, start the FastAPI application:

```text
uv run uvicorn app.main:app --reload
```

It serves `http://127.0.0.1:8000`. The generated OpenAPI documentation is at
`/docs`, and the raw schema at `/openapi.json`. `--reload` restarts the server
when Python files change; restart it manually after editing `.env`.

Check liveness:

```text
curl -i http://127.0.0.1:8000/health/live
```

Expect `200` with `{"status":"alive"}`, a server-generated UUID in
`X-Request-ID`, and `Cache-Control: no-store`. Liveness only confirms the
process can answer: it does not contact PostgreSQL, exercise providers, AI, or
telemetry stores, so it still returns `200` when they are unavailable. Startup
does not run migrations, create tables, or load seeds.

Check bounded database readiness separately:

```text
curl -i http://127.0.0.1:8000/health/ready
```

With a migrated PostgreSQL database and at least one active row in both
`exercise_categories` and `body_parts`, it returns `200`
`{"status":"ready"}`. The check has one three-second deadline, including
executor queueing, pool wait, connection, reads, cleanup, and response
handling. It does not migrate, seed, repair, write, or verify every table.

A missing lookup table or no active lookup row returns `503` with
`reference_data_unavailable`. Invalid configuration, outage, permission,
pool, or read timeout failures return `503` with `database_unavailable`.
Incompatible schema and unexpected application failures return `500` with
`internal_error`. PostgreSQL and application errors are hidden from responses
and process logs.

Readiness is not migration verification and does not replace container
health. Use PostgreSQL container health for the database process, migration
commands or `alembic current/check` for the schema revision, and
`GET /health/ready` for bounded application reads.

Telemetry starts once at application startup through `app.telemetry`. When the
observability stack is not running, export attempts fail in the background and
log connection warnings without changing HTTP responses. To silence them during
local development, set `OTEL_SDK_DISABLED=true` in your private root `.env`.

Errors use the shared envelope from the
[initial API design](../api/foundation.md#shared-errors), with `422`
`invalid_request`, `404` `not_found`, `405` `method_not_allowed` (with `Allow`),
and `500` `internal_error`. Error messages never include submitted input,
stack traces, or connection details.

Paths are matched exactly. A trailing slash such as `/health/live/` returns the
shared JSON `404 not_found` instead of redirecting. The generated OpenAPI
document at `/openapi.json` (shown as interactive docs at `/docs`) lists the
liveness `200`, `422` and `500` responses with the shared error schema and
headers; app-wide `404` and `405` behavior is described in its API description,
shown at the top of `/docs`.

## Run the API in Docker

Keep the root `.env` private. In addition to the existing `POSTGRES_*`
settings, set `BACKEND_CONTAINER_DATABASE_URL` to the same empty/local database
using Compose hostname `postgres` and container port `5432`. Percent-encode
reserved credential characters. Do not print the URL or use a loopback hostname
inside the container. The safe `.env.example` shows the required shape.
Compose configuration and PostgreSQL/observability-only commands remain usable
when this setting is absent. Starting the backend or its one-off migration CLI
fails with a fixed, nonsecret error until the value names `postgres:5432` and
contains concrete, non-placeholder database credentials and database name.

From the repository root, validate configuration without rendering private
values, then build and start PostgreSQL and the API:

```text
docker compose config --quiet
docker compose build backend
docker compose up -d --wait postgres backend
```

The backend image uses the committed lock, contains no development dependencies
or uv executable, runs as UID/GID `10001`, and starts one Uvicorn process with
no reload or host source mount. Compose publishes only
`127.0.0.1:${BACKEND_PORT:-8000}`, uses a read-only root filesystem with a
bounded temporary filesystem, drops all capabilities, and applies local CPU,
memory and process limits.

Use these endpoints (substitute a private `BACKEND_PORT` override if needed):

- liveness: `http://127.0.0.1:8000/health/live`
- readiness: `http://127.0.0.1:8000/health/ready`
- Swagger UI: `http://127.0.0.1:8000/docs`
- OpenAPI JSON: `http://127.0.0.1:8000/openapi.json`

Implementation boundary for exercise forms: issue #14's future form is not
built here, but a future implementation must load
`GET /api/v1/exercise-categories` and `GET /api/v1/body-parts` independently,
wait for both successful `items` responses, and keep submission unavailable
until both lists are available. One successful response is not enough to show
an incomplete form. Any lookup failure must show a clear load failure and offer
a person-controlled retry; the form must not invent choices or silently select
`None`. This requirement follows
[issue #14](https://github.com/dhaval-mistry/unshaken-smart-coach/issues/14)
and [the approved API behavior](../api/foundation.md).

`/health/live` is process liveness only. `/health/ready` is the bounded
application/database read check and is not container health or migration
verification. The PostgreSQL healthy dependency orders initial container
startup; neither it nor liveness proves migrations or application readiness.
Starting, health-checking, restarting, rebuilding, and stopping the backend
never runs migrations or changes database rows.

Review backend status and logs without rendering configuration:

```text
docker compose ps --all backend
docker compose logs --tail 100 backend
docker compose restart backend
docker compose stop -t 10 backend
```

Stopping the stateless backend leaves PostgreSQL and named volumes intact. Do
not use `docker compose down -v` as a normal stop or rebuild command.

### Explicit migrations from the image

The same image provides the existing guarded database CLI. Start PostgreSQL,
preview the nonsecret target and revisions, and obtain the database owner's
approval before changing an existing/local/shared target:

```text
docker compose up -d --wait postgres
docker compose run --rm --no-deps backend unshaken-db plan
```

Only after approving that exact current plan:

```text
docker compose run --rm --no-deps backend unshaken-db upgrade --approve-target TOKEN_FROM_CURRENT_PLAN
```

A missing, wrong, or stale token makes no schema change. The one-off container
publishes no API port. Automatic migration, seeding, reset, and downgrade are
not part of backend startup.

### Optional container telemetry

Container telemetry defaults off independently of host telemetry. To opt in,
set `BACKEND_CONTAINER_OTEL_SDK_DISABLED=false` privately, keep
`BACKEND_CONTAINER_OTEL_ENDPOINT=http://alloy:4318`, and explicitly start the
existing observability profile:

```text
docker compose --profile observability up -d --build --wait postgres alloy mimir loki tempo grafana backend
```

The service has no dependency on Alloy. An unavailable exporter may lose local
signals but must not change liveness or application results. Never use
`127.0.0.1:4318` for an exporter inside the backend container because that
address points back to the container itself.

### HTTP contract tests

These tests need no database or observability stack. From `backend/`:

```text
uv run pytest tests/api tests/telemetry -q
```

They call the application in-process with FastAPI's `TestClient`. Telemetry
startup is replaced with no-op functions, except one test that runs real
telemetry against an unreachable endpoint in a separate process. Another test
confirms that importing and calling the application never loads database code.
Running plain `uv run pytest` also collects the PostgreSQL integration tests
below, which require `TEST_DATABASE_URL`.

## Testing without touching development data

From `backend/`, the repeatable verification runner creates a uniquely labeled
temporary PostgreSQL 17 container on a random loopback port, generates private
test credentials in process memory, upgrades it from empty, runs the integration
suite/schema-drift check, and removes only that test container:

```text
uv run python scripts/verify_database.py
```

The runner uses a 512 MiB temporary data filesystem and needs Docker access.
It does not read the private development URL or attach any existing data volume.
All test databases disappear when the disposable container is stopped. Run it
only when this disposable test activity is intended.

For a test server you have already prepared instead of using that runner:

Integration tests require a **separate fresh disposable PostgreSQL 17 database**
whose name begins `unshaken_foundation_test_`. Its connection is supplied in
private process variable `TEST_DATABASE_URL`. Never point this variable at the
shared or normal development database. The tests do not run provider/model calls.
Some lifecycle tests create additional disposable databases on that same test
server; this requires database-creation permission on the isolated test server.

After approving/migrating the fresh test target to head, run from `backend/`:

```text
uv run pytest -q --tb=short
```

Set TEST_DATABASE_URL privately in your shell or task runner; do not put a real
value in a checked-in example or command history shared with others. The tests
use synthetic data and refuse non-test database names. They deliberately
exercise invalid rows, concurrency and rejected deletes. A failing test must
not be repaired by changing the development database.

Rollback is destructive and kept separate from normal setup. It is refused
unless the connected database has the disposable prefix and the private
process flag `USC_ALLOW_DISPOSABLE_DOWNGRADE=1` is set. The test suite checks
both refusal and successful downgrade/upgrade on newly created disposable data.
Never enable that flag for a development/shared target.

Limitations: downgrade removes this foundation and its test data. Seed removal
can fail if records reference it, which safely aborts rollback; use fresh
unreferenced disposable data for the lifecycle test. It is not an existing-data
migration/recovery strategy, and application-history protection is not a backup.

## Enforcement and current limits

The database enforces source subtypes, ownership/lineage, weight pairs, required
measurements, one active workout, atomic capture, completed-history immutability,
source detachment, and timestamp chronology with constraints and triggers.
Capture must insert initial rows and seal its snapshot in one transaction.
See the [design](../database/design.md) for the JSON contract and deletion rules.

`app.db.operations` supplies three internal primitives: seal capture, complete
once with a stable server timer, and lock/check a template's captured version
**before** a future optional-update mapping operation. Source-version comparison
and mapping must use that transaction primitive; row guards alone cannot infer
the exact mapping/retry behavior of a future API. Completed history is committed
before that optional transaction. No workout API or template mapping is supplied.

For this initial foundation, a transaction advisory lock serializes guarded
writes, and deferred guards inspect the database state at transaction end.
This favors clear correctness for local development over throughput. It needs
load testing and equivalent concurrency protections before substantial API
traffic. Do not remove guards to improve performance without replacement tests.
A privileged database owner can still alter/disable schema protections;
these guards are not authentication or a substitute for least-privilege roles.

Package resources/migrations currently run from a repository checkout, not as a
standalone deployed wheel. Runtime checks were on Windows/Docker Desktop;
other operating systems were not exercised in this task. Database-backed API
endpoints remain separate implementation stories.

## Historical foundation verification evidence

The evidence below predates merged revision `0003_workout_follow_up`; it proves
the original 0001/0002 foundation, not current migration head or the approved
backend container. Current main includes 0003 through PR #37. The historical
run used an uncommitted working tree on `feature/database-foundation-local`,
based on main `c42d624`; no commit or GitHub publication was made by that task.
Environment: Python 3.12.10, PostgreSQL 17.11, Docker Engine 29.7.2 and Compose
5.5.0 on Windows. Locked libraries include SQLAlchemy 2.0.55, Alembic 1.20.1
and Psycopg 3.3.6.

| Command | Result |
|---|---|
| `uv sync --locked` from backend | Dependency lock synchronized; 17 packages resolved/checked |
| `uv run python scripts/verify_database.py` from backend | Fresh upgrade from base to `0002_master_records`; 74 integration tests passed; no schema drift; disposable server removed |
| `uv run alembic current` on the disposable target | `0002_master_records (head)` |
| `uv run alembic check` on the disposable target | No new upgrade operations detected |
| `python -m unittest discover -s tests -v` from repository root | 8 existing tests passed |
| `uv run --no-project python scripts/sync_agents.py --tool all --check` from repository root | 5 roles / 10 generated files checked; no drift |
| `git diff --check` plus local documentation checks | Whitespace, local links, fences and diagram/dictionary synchronization checked |

The integration suite includes rollback refusal without authorization, fresh
disposable downgrade/upgrade, seed conflict rollback and custom-row preservation,
actual FK rejection, source/ownership/lineage checks, three measurement kinds,
concurrent active-slot/complete-once behavior, immutable capture, source deletion,
TRUNCATE/delete/rewind rejection, terminal/event chronology, and safe target
confirmation. These are live PostgreSQL checks, not mocked database results.
No existing development tables/records were changed or real provider/model
requests made. Database guards were exercised with synthetic data only.

References: [SQLAlchemy constraints](https://docs.sqlalchemy.org/en/20/core/constraints.html),
[Alembic tutorial](https://alembic.sqlalchemy.org/en/latest/tutorial.html),
[Psycopg installation](https://www.psycopg.org/psycopg3/docs/basic/install.html).

### Local browser authentication

The opt-in Compose overlay serves a small verification page and the Google
authentication routes at `https://localhost:8443`. It publishes HTTPS only
on host loopback. FastAPI listens on loopback inside the shared network
namespace and accepts forwarded addresses only from its Caddy peer.

Use Docker Compose 2.24.4 or newer. Run these commands from the repository
root. Continue to use the base `compose.yaml` for normal database, backend, and
observability work.

1. In Google Auth Platform, register exactly
   `https://localhost:8443/api/v1/auth/google/callback` under **Authorized redirect
   URIs** for the existing Web client. Leave **Authorized JavaScript origins**
   empty. If the OAuth audience is in Testing, add your test account privately.

2. Use the existing private file or create a private copy of
   [the placeholder JSON](authentication.local.example.json) outside the source
   tree. The file contains the HTTPS origin, Google client ID and secret. Keep
   Apple settings unset. On Windows, use the existing file:

   ```powershell
   $env:USC_LOCAL_AUTH_FILE = Join-Path $env:USERPROFILE '.unshaken\authentication.local.json'
   ```

   On Linux, use your private file with mode `600`. Pass your numeric user and
   group IDs so the nonroot backend can read the owner-only bind mount:

   ```bash
   export USC_LOCAL_AUTH_FILE="$HOME/.unshaken/authentication.local.json"
   export USC_AUTH_BACKEND_USER="$(id -u):$(id -g)"
   ```

   Compose mounts the file read-only into FastAPI. Caddy receives only the
   static verification page and its own TLS files.

3. Use a database that already has reviewed migration `0005`. The overlay
   performs no migration. For a first test, use a disposable database. Supply
   the existing private Compose database URL for the intended database first.
   With that database container already running, start the HTTPS stack:

   ```console
   docker compose -f compose.yaml -f compose.auth.yaml up -d --no-deps --build --wait backend
   docker compose -f compose.yaml -f compose.auth.yaml up -d --no-deps --force-recreate caddy
   ```

4. Export only the public Caddy root certificate. Keep the named Caddy data
   volume so it can reuse the same local CA on later starts:

   On Windows:

   ```powershell
   $ca = Join-Path $env:USERPROFILE '.unshaken\unshaken-local-auth-root.crt'
   docker compose -f compose.yaml -f compose.auth.yaml cp caddy:/data/caddy/pki/authorities/local/root.crt "$ca"
   ```

   On Linux:

   ```bash
   ca="$HOME/.unshaken/unshaken-local-auth-root.crt"
   docker compose -f compose.yaml -f compose.auth.yaml cp caddy:/data/caddy/pki/authorities/local/root.crt "$ca"
   ```

   If the file is not ready yet, retry after Caddy starts. Inspect the
   certificate before installing it. Installing browser trust is a local
   owner action. On Windows, for the current user:

   ```powershell
   certutil -dump "$ca"
   certutil -user -addstore Root "$ca"
   ```

   On Debian or Ubuntu, to use the Linux system trust store:

   ```bash
   sudo install -m 0644 "$ca" /usr/local/share/ca-certificates/unshaken-local-auth-root.crt
   sudo update-ca-certificates
   ```

   On Fedora or RHEL, use `sudo trust anchor "$ca"`.
   If the browser uses a separate certificate store, import only this public
   certificate under Authorities. Restart the browser if needed. Keep the
   exported certificate and the CA private key out of the repository.

5. Open `https://localhost:8443` and confirm there is no certificate warning.
   Start Google sign-in, confirm a display name and unit if onboarding is
   shown, verify the signed-in state, and log out. Do not publish account
   details, cookie values, redirects or callback query strings as evidence.
   Caddy access logs are disabled and request error logs are excluded.
   FastAPI native access logs are disabled for this stack.

To stop the optional setup while keeping both database and CA volumes:

```console
docker compose -f compose.yaml -f compose.auth.yaml stop caddy backend
```

To return to the ordinary local backend, remove the stopped Caddy container
before starting the backend from the base configuration:

```console
docker compose -f compose.yaml -f compose.auth.yaml rm -f caddy
docker compose -f compose.yaml up -d --no-deps backend
```

For a synthetic source and rate-limit check without provider credentials, run
`uv run --no-project --python 3.12 python scripts/verify_auth_proxy.py` from the
repository root. It starts its own disposable PostgreSQL and publishes test
listeners on randomly assigned IPv4 loopback ports. It measures the TCP source
Docker presents, compares that address to the database window key after serving
HTTPS through Caddy and Uvicorn, checks that an inert client-supplied forwarding
header leaves both requests in the same window, and verifies HTTP 429 and
`Retry-After` from the saturated window.

Docker Desktop on Windows may show a Docker network peer for local requests.
Browsers behind that peer share one limit window. This local test verifies
attribution at the Docker boundary. A production ingress would need its own
explicit proxy trust configuration and source verification.

If verifier cleanup fails, the command exits nonzero and prints the unique
`usc-proxy-test-...` project and label-filtered inspection commands. Inspect
only those labeled resources. After confirming they belong to the disposable
project, remove those specific containers, volumes, network, and the matching
`unshaken-backend:<project>` image tag if present. Leave the browser verification
project and development database volumes in place.
