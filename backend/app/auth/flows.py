"""Atomic authentication transactions and persistence."""

import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.engine import Connection

from app.auth.encryption import (
    decrypt_pending_token,
    encrypt_pending_token,
    encrypt_refresh_token,
)
from app.auth.providers import ExchangeResult
from app.auth.sessions import create_session, new_token, token_hash
from app.auth.settings import AuthSettings
from app.db.schema import (
    apple_onboarding_credentials,
    apple_revocation_credentials,
    auth_sessions,
    auth_transactions,
    user_identities,
    users,
)

FIVE_MINUTES = sa.text("interval '5 minutes'")


class AuthenticationFailed(ValueError):
    """The supplied proof or transaction did not authorize authentication."""


class AuthenticationBusy(RuntimeError):
    """The system cannot accept another pending authentication flow."""


def create_transaction(
    c: Connection, *, provider: str, purpose: str, binding: str, state: str,
    nonce: str, user_id=None, issuer=None, subject=None, link_session_hash=None,
) -> None:
    """Bind a five-minute flow to a browser and fixed completion destination."""
    # Serialize admission briefly across workers without waiting behind calls.
    if not c.execute(sa.select(sa.func.pg_try_advisory_xact_lock(746231902))).scalar_one():
        raise AuthenticationBusy("Authentication capacity unavailable")
    t = auth_transactions.c
    active = c.execute(sa.select(sa.func.count()).select_from(auth_transactions).where(
        t.consumed_at.is_(None), t.expires_at > sa.func.clock_timestamp(),
    )).scalar_one()
    if active >= 1000:
        raise AuthenticationBusy("Authentication capacity unavailable")
    c.execute(auth_transactions.insert().values(
        binding_hash=token_hash(binding), state_hash=token_hash(state),
        nonce_hash=token_hash(nonce), provider=provider, purpose=purpose,
        user_id=user_id, verified_issuer=issuer, verified_subject=subject,
        link_session_hash=link_session_hash,
        return_path="/auth/complete", expires_at=sa.func.statement_timestamp() + FIVE_MINUTES,
    ))


def consume(c: Connection, state: str, binding: str, provider: str | None, purposes: tuple):
    """Claim one live transaction without accepting another browser or purpose."""
    t = auth_transactions.c
    criteria = [
        t.state_hash == token_hash(state), t.binding_hash == token_hash(binding),
        t.purpose.in_(purposes), t.consumed_at.is_(None),
        t.expires_at > sa.func.clock_timestamp(),
    ]
    if provider is not None:
        criteria.append(t.provider == provider)
    row = c.execute(
        auth_transactions.update().where(*criteria)
        .values(consumed_at=sa.func.clock_timestamp()).returning(auth_transactions)
    ).mappings().one_or_none()
    if row is None:
        raise AuthenticationFailed("Invalid authentication flow")
    return row


def _store_apple(c: Connection, settings: AuthSettings, identity, refresh: bytes) -> None:
    """Encrypt a credential for durable identity storage before writing it."""
    version = settings.active_key_version
    value = encrypt_refresh_token(refresh, identity, version, settings.encryption_keys)
    stmt = insert(apple_revocation_credentials).values(
        identity_id=identity, ciphertext=value, key_version=version,
    )
    c.execute(stmt.on_conflict_do_update(
        index_elements=[apple_revocation_credentials.c.identity_id],
        set_=dict(ciphertext=stmt.excluded.ciphertext, key_version=stmt.excluded.key_version),
    ))


def finish_login(c: Connection, result: ExchangeResult, binding: str, settings: AuthSettings):
    """Issue a session to an existing identity or begin browser-bound onboarding."""
    identity = result.identity
    ids, user = user_identities.c, users.c
    current = c.execute(
        sa.select(ids.id, ids.user_id, ids.provider_revoked_at, user.status)
        .join(users, user.id == ids.user_id)
        .where(ids.provider == identity.provider, ids.issuer == identity.issuer,
               ids.subject == identity.subject)
        .with_for_update(of=(user_identities, users))
    ).mappings().one_or_none()
    if current:
        if current["status"] != "active" or current["provider_revoked_at"] is not None:
            raise AuthenticationFailed("Identity unavailable")
        if result.refresh_token is not None:
            _store_apple(c, settings, current["id"], result.refresh_token)
        c.execute(user_identities.update().where(ids.id == current["id"]).values(
            last_login_at=sa.func.clock_timestamp()))
        return "session", create_session(c, current["user_id"], current["id"])

    if identity.provider == "apple" and result.refresh_token is None:
        raise AuthenticationFailed("Restart Apple authorization")
    state = new_token()
    create_transaction(
        c, provider=identity.provider, purpose="onboarding", binding=binding, state=state,
        nonce=new_token(), issuer=identity.issuer, subject=identity.subject,
    )
    if result.refresh_token is not None:
        version = settings.active_key_version
        state_digest = token_hash(state)
        cipher = encrypt_pending_token(
            result.refresh_token, state_digest, identity.issuer, identity.subject,
            version, settings.encryption_keys,
        )
        c.execute(apple_onboarding_credentials.insert().values(
            state_hash=state_digest, ciphertext=cipher, key_version=version,
        ))
    return "onboarding", state


def finish_onboarding(
    c: Connection, state: str, binding: str, name: str, unit: str, settings: AuthSettings
) -> str:
    """Consume proof and atomically create the user, identity and session."""
    tx = consume(c, state, binding, None, ("onboarding",))
    pending = apple_onboarding_credentials
    refresh = None
    if tx["provider"] == "apple":
        envelope = c.execute(
            sa.select(pending).where(pending.c.state_hash == tx["state_hash"])
        ).mappings().one_or_none()
        if envelope is None:
            raise AuthenticationFailed("Restart Apple authorization")
        refresh = decrypt_pending_token(
            envelope["ciphertext"], tx["state_hash"], tx["verified_issuer"],
            tx["verified_subject"], envelope["key_version"], settings.encryption_keys,
        )
    owner = c.execute(users.insert().values(
        display_name=name, preferred_weight_unit=unit, status="active",
    ).returning(users.c.id)).scalar_one()
    identity = c.execute(insert(user_identities).values(
        user_id=owner, provider=tx["provider"], issuer=tx["verified_issuer"],
        subject=tx["verified_subject"], last_login_at=tx["created_at"],
    ).on_conflict_do_nothing(
        index_elements=[user_identities.c.provider, user_identities.c.issuer,
                        user_identities.c.subject],
    ).returning(user_identities.c.id)).scalar_one_or_none()
    if identity is None:
        raise AuthenticationFailed("Identity unavailable")
    if refresh is not None:
        _store_apple(c, settings, identity, refresh)
        c.execute(pending.delete().where(pending.c.state_hash == tx["state_hash"]))
    return create_session(c, owner, identity)


def revoke_apple_identity(c: Connection, issuer: str, subject: str) -> None:
    """Revoke a verified Apple identity and invalidate all sessions it created."""
    ids = user_identities.c
    identity = c.execute(
        user_identities.update().where(
            ids.provider == "apple", ids.issuer == issuer, ids.subject == subject,
            ids.provider_revoked_at.is_(None),
        ).values(provider_revoked_at=sa.func.clock_timestamp()).returning(ids.id)
    ).scalar_one_or_none()
    if identity is not None:
        sessions = auth_sessions.c
        c.execute(auth_sessions.update().where(
            sessions.identity_id == identity, sessions.revoked_at.is_(None),
        ).values(revoked_at=sa.func.clock_timestamp()))

def freshly_verified_owner(c: Connection, session_hash: bytes, provider: str):
    """Resolve a live, freshly verified session for a different provider."""
    sessions, user, ids = auth_sessions.c, users.c, user_identities.c
    now = sa.func.clock_timestamp()
    return c.execute(
        sa.select(user.id)
        .select_from(auth_sessions.join(users, sessions.user_id == user.id)
                     .join(user_identities, ids.id == sessions.identity_id))
        .where(sessions.token_hash == session_hash, user.status == "active",
               ids.provider != provider, ids.provider_revoked_at.is_(None),
               sessions.revoked_at.is_(None), sessions.created_at > now - FIVE_MINUTES,
               ids.last_login_at > now - FIVE_MINUTES)
    ).scalar_one_or_none()


def finish_link(c: Connection, tx, result: ExchangeResult, settings: AuthSettings) -> str:
    """Attach only an unowned identity and rotate all old sessions atomically."""
    identity = result.identity
    owner = tx["user_id"]
    active = c.execute(
        sa.select(users.c.id).where(users.c.id == owner, users.c.status == "active")
        .with_for_update()
    ).scalar_one_or_none()
    source = tx["link_session_hash"]
    if (active is None or source is None
            or freshly_verified_owner(c, source, identity.provider) != owner):
        raise AuthenticationFailed("Fresh verification is required")
    if identity.provider == "apple" and result.refresh_token is None:
        raise AuthenticationFailed("Restart Apple authorization")
    ids = user_identities.c
    attached = c.execute(insert(user_identities).values(
        user_id=owner, provider=identity.provider, issuer=identity.issuer,
        subject=identity.subject, last_login_at=sa.func.clock_timestamp(),
    ).on_conflict_do_nothing(
        index_elements=[ids.provider, ids.issuer, ids.subject],
    ).returning(ids.id)).scalar_one_or_none()
    if attached is None:
        raise AuthenticationFailed("Identity unavailable")
    if result.refresh_token is not None:
        _store_apple(c, settings, attached, result.refresh_token)
    sessions = auth_sessions.c
    c.execute(auth_sessions.update().where(
        sessions.user_id == owner, sessions.revoked_at.is_(None),
    ).values(revoked_at=sa.func.clock_timestamp()))
    return create_session(c, owner, attached)
