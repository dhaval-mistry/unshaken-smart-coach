"""Plan and apply migrations with an explicit, owner-approved target."""

from __future__ import annotations

from pathlib import Path

from alembic.config import Config
from alembic.runtime.migration import MigrationContext
from alembic.script import ScriptDirectory
from alembic import command
from sqlalchemy import create_engine, text
from sqlalchemy.engine import URL, Connection

from app.db.config import describe_target

BACKEND_DIR = Path(__file__).resolve().parents[2]


class ApprovalError(RuntimeError):
    pass


def alembic_config(connection: Connection | None = None) -> Config:
    cfg = Config(str(BACKEND_DIR / "alembic.ini"))
    cfg.set_main_option("script_location", str(BACKEND_DIR / "migrations"))
    if connection is not None:
        cfg.attributes["connection"] = connection
    return cfg


def current_revision(connection: Connection) -> str | None:
    return MigrationContext.configure(connection).get_current_revision()


def pending_migrations(connection: Connection) -> list[tuple[str, str]]:
    script = ScriptDirectory.from_config(alembic_config())
    current = current_revision(connection)
    pending = [
        (rev.revision, (rev.doc or "").strip().splitlines()[0])
        for rev in script.iterate_revisions("head", current or "base")
    ]
    return list(reversed(pending))


def existing_unmanaged_tables(connection: Connection) -> list[str]:
    rows = connection.execute(
        text(
            "SELECT table_name FROM information_schema.tables "
            "WHERE table_schema = current_schema() AND table_type = 'BASE TABLE' "
            "AND table_name <> 'alembic_version' ORDER BY table_name"
        )
    )
    return [r[0] for r in rows]


def build_plan(url: URL) -> str:
    """Read-only report: nonsecret target, current version, planned changes."""
    engine = create_engine(url)
    with engine.connect() as conn:
        version = conn.execute(text("SHOW server_version")).scalar_one()
        current = current_revision(conn)
        pending = pending_migrations(conn)
        tables = existing_unmanaged_tables(conn)
    engine.dispose()
    head = ScriptDirectory.from_config(alembic_config()).get_current_head()
    lines = [
        f"Target host:      {url.host or 'localhost'}",
        f"Target port:      {url.port or 5432}",
        f"Target database:  {url.database}",
        f"Server version:   PostgreSQL {version}",
        f"Current version:  {current or 'none (no migrations applied)'}",
        f"Latest version:   {head}",
        f"Existing tables:  {len(tables)}" + (f" ({', '.join(tables)})" if tables else ""),
    ]
    if not pending:
        lines.append("Planned changes:  none (already at the latest version)")
    else:
        lines.append("Planned changes:")
        lines += [f"  - {rev}: {doc}" for rev, doc in pending]
        if current is None and tables:
            lines.append(
                "WARNING: the database has tables but no migration history. "
                "Applying will fail rather than replace them; do not proceed "
                "until the owner has reviewed this target."
            )
        lines.append("Data is preserved: upgrades only add objects; nothing is dropped.")
        lines.append(f"To apply, re-run with: upgrade --approve-target {describe_target(url)}")
    return "\n".join(lines)


def apply_upgrade(url: URL, approved_target: str | None) -> str:
    expected = describe_target(url)
    if approved_target != expected:
        raise ApprovalError(
            f"Target not approved. Review the plan, then pass "
            f"--approve-target {expected} (exact match required)."
        )
    engine = create_engine(url)
    try:
        with engine.connect() as conn:
            before = current_revision(conn)
            conn.rollback()  # end the read transaction before migrating
            command.upgrade(alembic_config(conn), "head")
            conn.commit()
            after = current_revision(conn)
    finally:
        engine.dispose()
    return f"Upgraded {expected}: {before or 'none'} -> {after}" if before != after else (
        f"{expected} already at {after}; nothing to do."
    )
