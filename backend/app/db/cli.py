"""Preview a nonsecret database target before applying any migration."""
import argparse
import hashlib
import json
from pathlib import Path

from alembic import command
from alembic.config import Config
from alembic.migration import MigrationContext
from alembic.script import ScriptDirectory
from app.db.config import database_engine, database_url

BACKEND=Path(__file__).resolve().parents[2]


def alembic_config():
    """Locate versioned migrations independently of the caller's working directory."""
    return Config(str(BACKEND/"alembic.ini"))


def migration_plan(connection, url):
    """Read current revision and return target details without secrets or writes."""
    major=int(connection.exec_driver_sql("SHOW server_version_num").scalar_one())//10000
    if major!=17:
        raise ValueError("This foundation requires PostgreSQL 17.")
    current=MigrationContext.configure(connection).get_current_revision()
    script=ScriptDirectory.from_config(alembic_config())
    revisions=[r.revision for r in reversed(list(script.iterate_revisions("heads",current or "base")))]
    details={"host":url.host or "local socket","port":url.port or 5432,"database":url.database,
             "current_revision":current or "base","planned_migrations":revisions}
    token=hashlib.sha256(json.dumps(details,sort_keys=True).encode()).hexdigest()[:20]
    return details,token


def main():
    """Print a plan; upgrade only when the caller confirms that exact target/revision."""
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument("action",choices=["plan","upgrade"])
    parser.add_argument("--approve-target",help="Confirmation token from the current plan")
    args=parser.parse_args()
    try:
        url=database_url()
        with database_engine(url).connect() as connection:
            # Serialize concurrent migration invocations on the selected database.
            if args.action=="upgrade":
                connection.exec_driver_sql("SELECT pg_advisory_lock(746231902)")
            try:
                details,token=migration_plan(connection,url)
                print(json.dumps(details,indent=2))
                print("Target confirmation token:",token)
                if args.action=="plan":
                    return 0
                if args.approve_target!=token:
                    print("No migrations applied. Review the target and rerun with --approve-target TOKEN.")
                    return 2
                connection.commit()
                if not details["planned_migrations"]:
                    print("Already at head; no schema or seed changes.")
                    return 0
                config=alembic_config()
                config.attributes["connection"]=connection
                command.upgrade(config,"head")
                connection.commit()
                print("Upgrade complete.")
                return 0
            finally:
                if args.action=="upgrade":
                    connection.rollback()
                    connection.exec_driver_sql("SELECT pg_advisory_unlock(746231902)")
    except Exception:
        print("Database command failed. No credentials or full connection string are displayed. Check private settings and migration conflicts locally.")
        return 1


if __name__=="__main__":
    raise SystemExit(main())
