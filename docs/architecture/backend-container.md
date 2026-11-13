# Local FastAPI backend container design

Status: **owner-approved local design; not implemented**. The owner approved
this design on 2026-11-13 against main `20d0f7c`. No backend Dockerfile, backend
`.dockerignore`, or backend service exists in the root Compose file yet. Every
container command below is a future contract for a separately requested
Developer, not a command that works on the current checkout.

This document is the canonical design for building and running the existing
FastAPI backend as a local Linux container. The current host-run instructions
remain in [backend setup](../setup/backend.md). PostgreSQL setup remains in
[PostgreSQL setup](../setup/postgresql.md), and the optional telemetry stack
remains in [observability setup](../setup/observability.md).

## Scope and current baseline

The current repository has:

- a Python 3.12 uv project with committed `pyproject.toml` and `uv.lock`;
- a FastAPI application exposing `GET /health/live`, `/docs`, and
  `/openapi.json`;
- database migration tooling and revisions `0001_database_foundation`,
  `0002_master_records`, and `0003_workout_follow_up`;
- a root [Compose file](../../compose.yaml) with PostgreSQL 17 and an optional
  Alloy/Mimir/Loki/Tempo/Grafana profile; and
- host-run Uvicorn, migration, test, and telemetry commands.

The current repository does **not** have a backend container image, backend
Compose service, container health check, or container-specific database URL.
The existing application starts no migrations and its liveness handler makes no
database, provider, AI, or telemetry request.

The proposed local target adds one immutable backend image and one default
Compose service named `backend`. It preserves the current PostgreSQL service,
volumes, migration controls, telemetry routing, and application behavior.

| Concern | Current state | Proposed local-container state |
|---|---|---|
| API process | Host `uv run uvicorn ... --reload` | One Uvicorn process in an immutable, non-root container; no reload |
| Packaging | Repository checkout and local `.venv` | Multi-stage Python 3.12 image using locked production dependencies |
| Compose | PostgreSQL plus optional observability | Add `backend`; keep PostgreSQL and observability independently usable |
| Database address | Host URL normally uses loopback/published port | Container URL uses Compose DNS name `postgres` and port `5432` |
| Database changes | Explicit `unshaken-db plan` and confirmed upgrade | Same commands run as explicit one-off containers from the same image |
| Telemetry | Host endpoint or disabled | Disabled by default; explicitly target `http://alloy:4318` when the profile is used |
| Files | Host source and writable environment | Read-only root filesystem, bounded `/tmp`, no source bind mount |
| Exposure | Host Uvicorn on loopback | Container binds `0.0.0.0:8000`; Compose publishes only to host loopback |

## Goals and non-goals

The design must provide a repeatable local image, safe Compose integration,
explicit migration workflow, optional telemetry, graceful lifecycle, and
verification evidence. The same built artifact may be evaluated elsewhere
later, but this design makes no remote-platform, registry, production, load,
TLS, ingress, scaling, or cloud deployment decision.

It does not add product endpoints, readiness, authentication, migrations,
database records, a source-reload workflow, or container-log collection.

## Image and build design

### Build context and inputs

Use `backend/` as the build context, not the repository root. The private root
`.env`, Git metadata, frontend, UI samples, observability volumes, editor files,
and unrelated repository content are then outside the context by construction.

A future `backend/.dockerignore` must also exclude at least:

- `.env`, `.env.*`, `.venv/`, caches, bytecode, coverage and test output;
- tests, examples, local verification scripts and editor/OS files; and
- build artifacts, logs, temporary files, credentials and private keys.

Allow only the files needed to resolve/install the locked project and run the
API/migrations: `pyproject.toml`, `uv.lock`, `app/`, `migrations/`,
`alembic.ini`, and the future Dockerfile. Use explicit `COPY` instructions;
never use a broad root-context `COPY . .` as a substitute for review.

### Reproducible multi-stage build

Use Linux Python 3.12 slim builder and runtime stages. Pin the full Python image
tag and digest during implementation. Copy a specific uv release from its
official image pinned by digest; do not download and execute an unpinned install
script. Builder and runtime must use the same distribution family and CPU
architecture.

In the builder:

1. Set a dedicated project environment such as `/opt/venv`.
2. Copy `pyproject.toml` and `uv.lock`, then run `uv sync --frozen --no-dev
   --no-install-project` for dependency caching.
3. Copy the reviewed application source and migration resources, then run
   `uv sync --frozen --no-dev` and precompile bytecode.
4. Fail instead of modifying the lock or resolving a different dependency set.

The current migration CLI locates `alembic.ini` and `migrations/` relative to
the backend source tree. Preserve the same `/app` layout in both stages and copy
only `/opt/venv`, `app/`, `migrations/`, and `alembic.ini` into the runtime.
This keeps `unshaken-db` working without shipping uv, compilers, tests, examples,
the lock file, or package-manager caches in the runtime image. The source inside
the image is immutable image content; it is not a host bind mount.

Use BuildKit cache mounts only for nonsecret package caches. Do not pass tokens,
URLs containing credentials, `.env`, or secret build arguments. Record OCI
labels for source repository and exact commit without embedding contributor
identity or private paths. Tag a reviewed local artifact with its commit or
content digest; do not rely on a mutable `latest` tag as evidence.

Reproducibility here means pinned base/uv artifacts, frozen dependency
resolution, explicit build inputs, and an image referenced by immutable digest.
Do not claim byte-for-byte reproducibility until two clean builds have proved it.

## Runtime process and lifecycle

Create a fixed unprivileged UID/GID (recommended `10001`) in the runtime image.
Run one Uvicorn worker with an exec-form command equivalent to:

```text
uvicorn app.main:app --host 0.0.0.0 --port 8000 --no-access-log
```

This command is planned and unavailable today. Container port `8000` listens on
all container interfaces because Compose networking requires it; Compose must
publish it only as `127.0.0.1:${BACKEND_PORT:-8000}:8000`. Do not use reload,
a shell wrapper, or a source bind mount in the reproducible baseline. Disable
Uvicorn's generic access log until a separately reviewed safe access-log format
can guarantee that raw query values and private data are excluded. Application
and server diagnostics go to stdout/stderr; no file log or Docker log collector
is added.

Use `init: true` and an exec-form process so SIGTERM reaches Uvicorn. Configure
a ten-second stop grace period. The FastAPI lifespan then runs the existing
bounded telemetry shutdown (at most three seconds) before process exit. A normal
stop must not require SIGKILL.

Recommended initial local limits are one CPU, 512 MiB memory, and 128 PIDs. They
are safety bounds, not production sizing or measured capacity. The Developer
must verify startup, migration planning, telemetry shutdown, and tests within
them and document any justified adjustment.

## Filesystem and container security

The proposed Compose service must use:

- `read_only: true`;
- a size-bounded `tmpfs` at `/tmp` with `noexec`, `nosuid`, and `nodev` where
  supported;
- `cap_drop: [ALL]`;
- `security_opt: [no-new-privileges:true]`;
- the fixed non-root user;
- no privileged mode, host networking, Docker socket, device, or host-path
  mount; and
- no persistent backend volume.

Set `PYTHONDONTWRITEBYTECODE=1` and `PYTHONUNBUFFERED=1`. Any runtime component
that unexpectedly needs another writable path must fail verification and receive
a narrow reviewed tmpfs, not a writable root filesystem.

Local Docker administrators can inspect a container's environment. This design
prevents secrets from entering source, image layers, history, logs, or rendered
configuration output; it does not treat access to the local Docker daemon as a
security boundary.

## Compose integration

Add one default service named `backend` to the root Compose project. It should:

- build from `./backend` and carry a local image tag tied to the source commit;
- depend on `postgres` with `condition: service_healthy`;
- publish only the loopback backend port;
- use the health check below;
- apply the runtime filesystem, user, capability, process, and resource rules;
- use `restart: unless-stopped` for the stateless local API; and
- declare no dependency on Alloy or another observability-profile service.

`depends_on` controls initial local ordering only. It does not make liveness a
database readiness check, prove credentials, migrate a database, or restart the
backend when PostgreSQL later becomes unavailable. The API remains independently
usable for liveness when telemetry export fails.

### Health check

Use Python's standard library from inside the image; do not add curl only for a
probe. The check should request `http://127.0.0.1:8000/health/live` with a short
timeout and require HTTP 200 plus JSON `{"status":"alive"}`. Recommended initial
timing is a five-second interval, two-second timeout, ten retries, and ten-second
start period.

This uses only the implemented contract. It proves that the process can answer
HTTP, not that PostgreSQL, migrations, ExerciseDB, authentication, AI, Alloy, or
the telemetry stores are ready.

## Configuration and secret boundaries

The private root `.env` remains host-local for Compose interpolation. Never copy
it into the build context, image, or layer; never mount it into the container;
and do not use Compose `env_file` to expose every setting. The service lists and
passes only required runtime variables.

Keep these three database concerns distinct:

| Setting | Consumer and meaning |
|---|---|
| `POSTGRES_DB`, `POSTGRES_USER`, `POSTGRES_PASSWORD` | Official PostgreSQL image; initialize an **empty** data volume only |
| `DATABASE_URL` | Existing host-run API/migration setting; normally addresses `127.0.0.1` and the published `POSTGRES_PORT` |
| proposed `BACKEND_CONTAINER_DATABASE_URL` | Private host-side Compose interpolation value mapped to `DATABASE_URL` inside `backend`; must address service `postgres` on container port `5432` |

Example shape only, never a real credential:

```text
postgresql://APP_USER:ENCODED_PASSWORD@postgres:5432/APP_DATABASE
```

Percent-encode reserved username/password characters before composing either
URL. Do not derive the URL in Compose by string-concatenating raw credentials.
Changing `POSTGRES_*`, the host URL, or the proposed container URL does not
change credentials or rename a database in an initialized volume. Never print
the URL, render full Compose configuration into shared evidence, or pass it as a
build argument. Use `docker compose config --quiet` for ordinary validation.

Compose maps only the following application settings initially:

- `DATABASE_URL=${BACKEND_CONTAINER_DATABASE_URL:?set a private container URL}`;
- `OTEL_SDK_DISABLED=${BACKEND_CONTAINER_OTEL_SDK_DISABLED:-true}`; and
- `OTEL_EXPORTER_OTLP_ENDPOINT=${BACKEND_CONTAINER_OTEL_ENDPOINT:-http://alloy:4318}`.

The container-specific telemetry disabled flag prevents the existing host
default from accidentally enabling exporters when the observability profile is
absent. Do not pass `POSTGRES_*`, Grafana credentials, provider credentials,
development identities, or unused future settings to the backend service.

## Optional observability

The baseline backend starts with telemetry disabled and needs only PostgreSQL's
healthy start ordering. To send telemetry, a contributor explicitly sets the
private container flag to `false`, keeps the endpoint at `http://alloy:4318`,
and starts the existing `observability` profile. Containers use service DNS;
`127.0.0.1:4318` would incorrectly point back to the backend container.

Alloy remains optional and receives application OTLP only. Do not mount the
Docker socket or add broad container-log collection. If Alloy or a downstream
store is absent or fails, the application result and liveness response remain
unchanged; signal loss remains possible under the documented local limitations.

## Startup never migrates data

The image entry command starts Uvicorn only. Backend startup and health checks
must never:

- run Alembic or `unshaken-db`;
- create or repair a database, schema, table, index, function, seed, or user;
- reset a volume or rewrite existing rows; or
- wait for migration head before serving liveness.

Database planning and upgrades remain explicit one-off actions using the same
reviewed image and existing target-confirmation controls. A future workflow is:

```text
# Planned; unavailable until the backend service/image is implemented.
docker compose up -d --wait postgres
docker compose run --rm --no-deps backend unshaken-db plan

# Only after the displayed nonsecret target/revision/plan is approved:
docker compose run --rm --no-deps backend unshaken-db upgrade --approve-target TOKEN_FROM_CURRENT_PLAN
```

The one-off container joins the same Compose network and receives the same
container `DATABASE_URL`; it publishes no port. Start PostgreSQL explicitly
before `--no-deps`. A stale/wrong token must fail without changes. Do not add an
automatic migration entrypoint, retry loop, downgrade shortcut, or startup
repair. Applying any migration to an existing/local/shared target still needs
that target owner's separate approval. Destructive downgrade remains limited to
the existing disposable-test safeguards.

## Planned local commands and URLs

All commands in this section are design examples and will fail on current main
because the backend image/service has not been implemented.

```text
# Validate without printing interpolated secrets.
docker compose config --quiet

# Build and start the normal local stack.
docker compose build backend
docker compose up -d --wait postgres backend

# Inspect only the backend service.
docker compose ps --all backend
docker compose logs --tail 100 backend

# Exercise the implemented HTTP surface.
curl -i http://127.0.0.1:8000/health/live

# Lifecycle without deleting PostgreSQL or telemetry volumes.
docker compose restart backend
docker compose stop -t 10 backend
```

Planned URLs are:

- API liveness: `http://127.0.0.1:8000/health/live`
- Swagger UI: `http://127.0.0.1:8000/docs`
- OpenAPI JSON: `http://127.0.0.1:8000/openapi.json`

If `BACKEND_PORT` is changed privately, substitute that loopback port. Do not
use `docker compose down -v` as a normal stop or rebuild command.

An observability-enabled start additionally requires private Grafana settings,
`BACKEND_CONTAINER_OTEL_SDK_DISABLED=false`, and the existing profile:

```text
# Planned backend integration; existing observability services are already implemented.
docker compose --profile observability up -d --build --wait postgres alloy mimir loki tempo grafana backend
```

No source bind mount or `--reload` belongs in these baseline commands. A future
developer override may provide those conveniences in a separate, explicitly
selected file, but it must not change the reproducible default or be required by
tests and migration commands.

## Implementation acceptance and verification

A later implementation is complete only with evidence for all items below.

### Build and supply chain

- Dockerfile and `.dockerignore` use only the reviewed backend context and
  explicit copies; a context manifest proves `.env`, `.git`, `.venv`, caches,
  tests, examples and unrelated source are absent.
- Python and uv artifacts are pinned by version and digest; `uv sync --frozen
  --no-dev` succeeds without changing `uv.lock`.
- The runtime contains no uv binary, compiler, package-manager cache, test suite,
  example, `.env`, VCS metadata, or development dependency.
- A layer/history inspection and an approved secret scanner find no credential,
  token, private URL, `.env` content, or private path. Scan image layers, not
  only the final filesystem.
- The artifact records source provenance and is exercised by immutable digest.

### Runtime and HTTP

- The process runs as the fixed non-root user with a read-only root filesystem,
  bounded `/tmp`, all capabilities dropped, no-new-privileges, and no mounts or
  Docker socket.
- Only the configured loopback host port is published. Another LAN host cannot
  reach it through an all-interface binding.
- Compose reaches healthy using only `/health/live`; the response headers/body,
  `/docs`, and `/openapi.json` match existing API tests.
- Health remains green during a telemetry outage and correctly does not claim
  database readiness.
- Rebuild/restart uses the same PostgreSQL volume and preserves its cluster
  identifier and existing rows. Backend restart neither recreates PostgreSQL nor
  changes its credentials.
- SIGTERM produces a clean stop within ten seconds and runs bounded telemetry
  shutdown; evidence distinguishes graceful exit from forced kill.
- stdout/stderr contain useful startup/shutdown errors but no full connection
  URL, credential, token, request body, personal data, or raw exception secret.

### Database and telemetry boundaries

- Starting, health-checking, stopping, restarting and rebuilding the backend do
  not change the Alembic revision, create tables/seeds, or modify application
  row counts.
- `unshaken-db plan` works from a one-off container and exposes only the existing
  nonsecret target summary/token. Wrong/missing approval performs no migration.
- A separately approved upgrade reaches current head on a disposable PostgreSQL
  17 database; no existing/shared database is used for implementation tests.
- Baseline telemetry-disabled startup has no exporter dependency. With the
  profile explicitly enabled, the backend uses `alloy:4318`; removing Alloy does
  not change HTTP results.

### Configuration, lifecycle and tests

- `docker compose config --quiet` succeeds with documented private placeholders;
  tests assert backend loopback exposure, health command, PostgreSQL healthy
  dependency, explicit environment allowlist, read-only/security settings, no
  source mount, and optional telemetry behavior.
- Existing API/telemetry tests pass outside and, where applicable, inside the
  built image. Database integration remains on the disposable verification
  runner. Add focused image/Compose smoke tests without weakening current tests.
- A clean `docker compose stop` leaves PostgreSQL and named volumes intact. No
  verification step depends on deleting a user volume.

Record exact commands, source commit, image ID/digest, Docker/Compose versions,
operating system, architecture, results, simulated failures and limitations.
Never include resolved Compose output or private values in evidence.

## Limitations and review boundary

- `/health/live` proves only that the process can answer. `/health/ready` and
  product database endpoints are not implemented.
- PostgreSQL `service_healthy` start ordering is not application readiness or
  proof that migrations are current.
- The baseline uses one Uvicorn worker and initial local resource limits; it is
  not a load, availability, or production-sizing claim.
- Local environment variables can be inspected by a person with Docker daemon
  access. A different secret-delivery design is required before treating the
  image as a production deployment.
- No TLS, authentication, external ingress, image registry, multi-architecture
  publication, remote orchestration, or production telemetry design is included.
- This local design does not approve any remote or cloud deployment.

No product decision remains open for this bounded local design. The owner
approved it on 2026-11-13. A separately requested Developer may add the
Dockerfile, `.dockerignore`, Compose service, safe example variables, focused
tests, and implemented setup commands.
