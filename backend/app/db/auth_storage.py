"""Database operations for pending Apple onboarding credentials."""

import sqlalchemy as sa
from sqlalchemy.engine import Connection

from app.db.schema import auth_transactions


def admit_auth_source(connection: Connection, digest: bytes) -> bool:
    """Charge one attempt against a five-minute source window."""
    from sqlalchemy.dialects.postgresql import insert
    from app.db.schema import auth_source_windows

    w = auth_source_windows.c
    now = sa.func.statement_timestamp()
    deadline = now + sa.text("interval '5 minutes'")
    stmt = insert(auth_source_windows).values(source_hash=digest, expires_at=deadline, attempts=1)
    allowed = connection.execute(stmt.on_conflict_do_update(
        index_elements=[w.source_hash],
        set_={
            "expires_at": sa.case((w.expires_at <= now, deadline), else_=w.expires_at),
            "attempts": sa.case((w.expires_at <= now, 1), else_=w.attempts + 1),
        },
        where=sa.or_(w.expires_at <= now, w.attempts < 10),
    ).returning(w.attempts)).scalar_one_or_none()
    return allowed is not None


def clear_stale_auth_rows(connection: Connection, limit: int = 100) -> tuple[int, int]:
    """Delete bounded stale transaction and admission rows without waiting on active work."""
    from app.db.schema import auth_source_windows

    t, w = auth_transactions.c, auth_source_windows.c
    stale = sa.or_(t.consumed_at.is_not(None), t.expires_at <= sa.func.clock_timestamp())
    transactions = (
        sa.select(t.state_hash).where(stale).order_by(t.expires_at, t.state_hash)
        .limit(limit).with_for_update(skip_locked=True).cte("stale_transactions")
    )
    removed_transactions = connection.execute(auth_transactions.delete().where(
        t.state_hash == transactions.c.state_hash, stale,
    )).rowcount
    source_expired = w.expires_at <= sa.func.clock_timestamp()
    sources = (
        sa.select(w.source_hash).where(source_expired).order_by(w.expires_at, w.source_hash)
        .limit(limit).with_for_update(skip_locked=True).cte("stale_sources")
    )
    removed_sources = connection.execute(auth_source_windows.delete().where(
        w.source_hash == sources.c.source_hash, source_expired,
    )).rowcount
    return removed_transactions, removed_sources
