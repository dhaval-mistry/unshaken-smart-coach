"""Verify this foundation on a new disposable PostgreSQL 17 container only.

Creates synthetic test databases and removes the test container afterward.
Never reads or modifies the normal development database or its volumes.
"""
import json
import os
from pathlib import Path
import secrets
import subprocess
import sys
import time
from uuid import uuid4

from alembic import command
from sqlalchemy.engine import URL
from app.db.cli import alembic_config, migration_plan
from app.db.config import database_engine

BACKEND=Path(__file__).resolve().parents[1]


def docker(*arguments, check=True, **options):
    """Run Docker without a shell or displaying private environment values."""
    result=subprocess.run(["docker",*arguments],text=True,capture_output=True,**options)
    if check and result.returncode:
        raise RuntimeError("Docker operation failed; inspect Docker availability locally.")
    return result


def main():
    """Create one uniquely labeled test server, run real checks, and clean up only that server."""
    marker=uuid4().hex
    name="unshaken-foundation-test-"+marker[:10]
    database="unshaken_foundation_test_"+marker[:10]
    password=secrets.token_hex(24)
    container=None
    try:
        environment=dict(os.environ,POSTGRES_PASSWORD=password)
        created=docker("run","-d","--rm","--name",name,"--label","usc.disposable="+marker,
            "--tmpfs","/var/lib/postgresql/data:rw,size=512m","-p","127.0.0.1::5432",
            "-e","POSTGRES_PASSWORD","-e","POSTGRES_USER=foundation_test",
            "-e","POSTGRES_DB="+database,"postgres:17-alpine",env=environment)
        container=created.stdout.strip()
        ports=json.loads(docker("inspect",container,"--format","{{json .NetworkSettings.Ports}}").stdout)
        port=int(ports["5432/tcp"][0]["HostPort"])
        deadline=time.monotonic()+60
        while docker("exec",container,"pg_isready","-U","foundation_test","-d",database,check=False).returncode:
            if time.monotonic()>=deadline:
                raise RuntimeError("Disposable PostgreSQL readiness timed out.")
            time.sleep(0.25)
        url=URL.create("postgresql+psycopg",username="foundation_test",password=password,
                       host="127.0.0.1",port=port,database=database)
        with database_engine(url).connect() as connection:
            details,token=migration_plan(connection,url)
            print(json.dumps(details,indent=2),flush=True)
        private_environment=dict(os.environ,DATABASE_URL=url.render_as_string(hide_password=False),
                                 TEST_DATABASE_URL=url.render_as_string(hide_password=False))
        # The new random target is explicitly disposable; no existing-target approval is implied.
        result=subprocess.run([sys.executable,"-m","app.db.cli","upgrade","--approve-target",token],
                              cwd=BACKEND,env=private_environment)
        if result.returncode:
            return result.returncode
        result=subprocess.run([sys.executable,"-m","pytest","-q","--tb=short"],cwd=BACKEND,env=private_environment)
        if result.returncode:
            return result.returncode
        with database_engine(url).connect() as connection:
            details,_=migration_plan(connection,url)
            print(json.dumps(details,indent=2),flush=True)
            if details["current_revision"]!="0002_master_records" or details["planned_migrations"]:
                raise RuntimeError("Test target did not reach migration head.")
            config=alembic_config()
            config.attributes["connection"]=connection
            command.check(config)
        print("PASS: fresh upgrade, database contracts, lifecycle tests, seeds and schema drift.",flush=True)
        return 0
    except Exception:
        print("Verification failed; no credentials or full connection string are displayed.",flush=True)
        return 1
    finally:
        if container:
            labels=json.loads(docker("inspect",container,"--format","{{json .Config.Labels}}").stdout)
            if labels.get("usc.disposable")!=marker:
                raise RuntimeError("Refusing cleanup: test-container label no longer matches.")
            docker("stop","-t","10",container)
            print("Removed only the disposable test server; development data was not touched.",flush=True)


if __name__=="__main__":
    raise SystemExit(main())
