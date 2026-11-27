"""Database operations for pending Apple onboarding credentials."""

import sqlalchemy as sa
from sqlalchemy.engine import Connection

from app.db.schema import apple_onboarding_credentials, auth_transactions


def clear_expired_apple_credentials(connection: Connection, limit: int = 100) -> int:
    """Clear one bounded batch, serializing with onboarding consumption."""
    transaction = auth_transactions.c
    pending = apple_onboarding_credentials.c
    expired = (
        sa.select(transaction.state_hash)
        .join(apple_onboarding_credentials, pending.state_hash == transaction.state_hash)
        .where(transaction.expires_at <= sa.func.clock_timestamp())
        .order_by(transaction.expires_at, transaction.state_hash)
        .limit(limit)
        .with_for_update(of=auth_transactions, skip_locked=True)
        .cte("expired")
    )
    result = connection.execute(
        sa.delete(apple_onboarding_credentials)
        .where(pending.state_hash == expired.c.state_hash)
        .where(transaction.state_hash == expired.c.state_hash)
        .where(transaction.expires_at <= sa.func.clock_timestamp())
    )
    return result.rowcount
