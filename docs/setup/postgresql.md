# Run PostgreSQL with Docker

The root [compose.yaml](../../compose.yaml) defines the existing PostgreSQL 17
service, named `postgres`. Run the commands below from the repository root.
Do not install a second PostgreSQL server for this project.

Starting the service initializes the configured development database only when
its data volume is empty. It does **not** create application tables, install
master records, or run migrations. The local migration tooling for stories #3
and #4 is described in [backend setup](backend.md). Review and approve the
specific target before applying it to an existing development database.

## Prepare private settings without overwriting them

First follow the [Docker installation guide](docker.md), start Docker Desktop
where applicable, and verify both the engine and Compose:

```text
docker version
docker compose version
```

If the server section is unavailable, the engine is not ready or your account
cannot access it. Fix that before starting the database.

Copy the example only if a private `.env` does not already exist.

PowerShell:

```powershell
if (-not (Test-Path -LiteralPath .env)) {
    Copy-Item -LiteralPath .env.example -Destination .env
}
```

macOS/Linux:

```bash
if [ ! -e .env ]; then
    cp .env.example .env
fi
```

Review your private settings locally. The example supplies these defaults:

| Setting | Default or purpose |
|---|---|
| Host | `localhost` |
| `POSTGRES_PORT` | `5432` on your computer |
| `POSTGRES_DB` | `unshaken_smart_coach` |
| `POSTGRES_USER` | `unshaken` |
| `POSTGRES_PASSWORD` | Set your own local password in `.env` |

The example leaves the password blank. Set a private password before starting a
new database: PostgreSQL refuses to initialize an empty volume without one.
Keep real credentials only
in your private configuration; never paste them or a connection string into
Git, issue evidence, or screenshots. Do not copy private values back into
`.env.example`.

PostgreSQL is published on `127.0.0.1`, so local clients can connect without
exposing the port on every network interface. Changes to Compose settings do
not update an already running container. Changing the port binding requires a
separately reviewed container recreation; preserve the existing volume and data.
Changing `.env` does not change the password in an initialized database.

Check that the private file is ignored and not tracked:

```text
git check-ignore .env
git ls-files .env
```

The first command should report `.env`; the second should print nothing.
Validate Compose without printing its resolved settings, which include secrets:

```text
docker compose config --quiet
```

## Start only PostgreSQL and wait for health

```text
docker compose up -d --no-recreate --wait --wait-timeout 90 postgres
docker compose ps --all postgres
```

The first command waits for the existing health check, with a 90-second health
deadline. The first image download can take additional time.
`--no-recreate` preserves an existing service container. Repeating the command
starts/reuses that service and its named volume; it does not reset the database.
If configuration changes need recreation later, review them separately.

The project volume is `unshaken-smart-coach_postgres_data` unless the Compose
project name is overridden. It is mounted at `/var/lib/postgresql/data`,
the data location used by the existing PostgreSQL 17 configuration.
Inspect only the intended project; similarly named containers/volumes from
other projects must not be removed or repurposed.

If startup fails or times out, inspect the scoped status and recent logs:

```text
docker compose ps --all postgres
docker compose logs --tail 50 postgres
```

Review logs locally before sharing; existing databases may log sensitive SQL.

## Verify the configured database and server version

The examples below use the template username and database. If your private
`POSTGRES_USER` or `POSTGRES_DB` differs, substitute those values in every
`-U` and `-d` argument. These commands use the container's PostgreSQL client;
no host installation of psql is needed.

```text
docker compose exec -T postgres pg_isready -U unshaken -d unshaken_smart_coach
docker compose exec -T postgres psql -X -w -v ON_ERROR_STOP=1 -U unshaken -d unshaken_smart_coach -c "SELECT current_database() AS database_name, current_setting('server_version') AS server_version;"
```

Expect `accepting connections`, a successful SQL connection to your configured
database, and a server version beginning with `17.`. A healthy container alone
does not prove that a particular database exists or that credentials work for
an external client. These in-container checks use the local connection; pgAdmin
host/password connection instructions remain in [pgadmin.md](pgadmin.md).

## Verify persistence without adding application data

These checks read PostgreSQL's existing system records. They create no tables,
insert no master records, and modify no application data.

Record the cluster identifier and configured database's catalog row:

```text
docker compose exec -T postgres psql -X -w -v ON_ERROR_STOP=1 -U unshaken -d unshaken_smart_coach -c "SELECT system_identifier FROM pg_control_system(); SELECT oid, datname FROM pg_database WHERE datname = current_database();"
```

Stop and start only this service, preserving its container and volume:

```text
docker compose stop --timeout 30 postgres
docker compose start --wait --wait-timeout 90 postgres
docker compose ps --all postgres
```

Run the same SQL again. The cluster identifier and database OID/name should be
unchanged, and the service should be healthy. Record the before/after results.
The default local database owner can read `pg_control_system()`; a restricted
external role may not have that permission.

On a newly initialized database this proves persistence of the cluster and
database catalog records, not application-row behavior or a backup/restore
guarantee. If application tables already exist, use approved read-only checks
of those records before/after as well; never insert a test row into an existing
table or change its data simply to test setup.

## Stop or resume normal development

```text
docker compose stop --timeout 30 postgres
docker compose start --wait --wait-timeout 90 postgres
```

Stopping the service intentionally interrupts local database connections; choose
a suitable time if someone is using it. Scope these commands to `postgres` so
future observability services are unaffected.

Normal setup never deletes volumes. Do not use `docker compose down -v`,
`docker volume rm`, automatic reset scripts, or a major-version image change
to fix a startup problem. Any destructive reset needs separate explicit
authorization for the exact target and data.

## Common startup problems

| Symptom | What to check |
|---|---|
| Docker engine unavailable or access denied | Start Docker Desktop/Engine and verify your account's engine access; retry `docker version`. Do not change database storage. |
| `docker compose` unavailable | Install/update Docker Desktop or the Linux Compose plugin from the existing Docker guide. |
| Port 5432 is already allocated | Identify the owner before changing anything. If appropriate, choose a free `POSTGRES_PORT` in private `.env` before first startup and use it in pgAdmin. |
| Container name already exists | Inspect that container's project/image. Do not remove an unrelated container or start another project as a workaround. |
| Health check times out | Inspect scoped status/logs for initialization, disk-space, volume-permission, or version errors. Increasing a timeout does not fix an incompatible data directory. |
| Database or role does not exist; password fails | Confirm the target and original initialization settings. Changing `.env` does not rename an existing database/role or reset its password. |
| Data directory belongs to another PostgreSQL major version | Keep the existing data intact and plan a separately approved upgrade. Never point PostgreSQL 17 at a PostgreSQL 16/18 data directory. |
| `.env` changed but container settings did not | `--no-recreate` deliberately preserves the existing container. Review the intended change and existing data first; ordinary stop/start does not apply new container settings. |

For a Windows port check:

```powershell
Get-NetTCPConnection -State Listen -LocalPort 5432 |
    Select-Object LocalAddress, LocalPort, OwningProcess
```

On macOS/Linux, if lsof is installed:

```bash
lsof -nP -iTCP:5432 -sTCP:LISTEN
```

Do not stop an unrelated process without its owner's approval. An older
project's unused database volume may contain valuable data; leave it intact.

## Environment changes after first startup

The official image uses `POSTGRES_DB`, `POSTGRES_USER`, and
`POSTGRES_PASSWORD` to initialize an empty data directory. Editing these
values later does not alter records in an existing database. Resolve changes
through a separately agreed administrative operation or migration, preserving
data; do not silently recreate the volume.

For issue/PR evidence, record the tested image/version, exact commands and
results, health state, nonsecret target, and before/after persistence checks.
State whether the database was new or contained existing application records.
Do not claim application-schema verification from this infrastructure check.

References: [PostgreSQL official image](https://hub.docker.com/_/postgres),
[Compose startup and wait options](https://docs.docker.com/reference/cli/docker/compose/up/),
[Compose start](https://docs.docker.com/reference/cli/docker/compose/start/).
