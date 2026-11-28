"""Opaque application sessions and browser request binding."""

import base64
import hmac
import re
import secrets
from hashlib import sha256

import sqlalchemy as sa
from sqlalchemy.engine import Connection


SESSION_COOKIE = "__Host-unshaken_session"
CSRF_HEADER = "X-CSRF-Token"
SESSION_SECONDS = 8 * 60 * 60
_TOKEN_PATTERN = re.compile(r"[A-Za-z0-9_-]{43}")


def new_token() -> str:
    """Generate a URL-safe opaque 256-bit application token."""
    return secrets.token_urlsafe(32)


def token_hash(token: str) -> bytes:
    """Hash a token for storage without persisting its bearer value."""
    return sha256(token.encode("ascii")).digest()


def valid_token(token: str | None) -> bool:
    """Check the canonical shape of an application-generated token."""
    return bool(token and _TOKEN_PATTERN.fullmatch(token))


def csrf_token(token: str, purpose: str = "session") -> str:
    """Derive a purpose-bound CSRF proof from a browser-only bearer token."""
    digest = hmac.digest(token.encode("ascii"), purpose.encode("ascii"), "sha256")
    return base64.urlsafe_b64encode(digest).decode("ascii").rstrip("=")


def create_session(connection: Connection, user_id, identity_id) -> str:
    """Persist the digest of a fresh session and return its cookie value."""
    from app.db.schema import auth_sessions

    token = new_token()
    connection.execute(auth_sessions.insert().values(
        token_hash=token_hash(token), user_id=user_id, identity_id=identity_id,
    ))
    return token


def replace_session(connection: Connection, user_id, identity_id, previous: str | None) -> str:
    """Revoke the cookie's prior session and create its successor atomically."""
    if previous is not None and valid_token(previous):
        revoke_session(connection, previous)
    return create_session(connection, user_id, identity_id)


def resolve_session(connection: Connection, token: str):
    """Refresh idle expiry and resolve the user from an active session."""
    from app.db.schema import auth_sessions, user_identities, users

    session, user, identity = auth_sessions.c, users.c, user_identities.c
    now = sa.func.clock_timestamp()
    return connection.execute(
        auth_sessions.update().where(
            session.token_hash == token_hash(token),
            session.user_id == user.id,
            session.identity_id == identity.id,
            identity.user_id == user.id,
            user.status == "active",
            identity.provider == "google",
            identity.provider_revoked_at.is_(None),
            session.revoked_at.is_(None),
            session.created_at + sa.text("interval '8 hours'") > now,
            session.last_seen_at + sa.text("interval '30 minutes'") > now,
        ).values(last_seen_at=sa.func.greatest(session.last_seen_at, now)).returning(
            user.id, user.display_name, user.preferred_weight_unit, session.identity_id,
        )
    ).mappings().one_or_none()


def revoke_session(connection: Connection, token: str) -> bool:
    """Revoke the selected application session without affecting other browsers."""
    from app.db.schema import auth_sessions

    session = auth_sessions.c
    result = connection.execute(
        auth_sessions.update().where(
            session.token_hash == token_hash(token), session.revoked_at.is_(None),
        ).values(revoked_at=sa.func.clock_timestamp())
    )
    return result.rowcount == 1
