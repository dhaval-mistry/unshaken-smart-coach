"""Same-origin authentication routes and the shared current-user boundary."""

import base64
import hmac
import json
from hashlib import sha256
from urllib.parse import parse_qs

from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import JSONResponse, RedirectResponse
from pydantic import BaseModel, Field
from sqlalchemy.exc import SQLAlchemyError
from starlette.concurrency import run_in_threadpool

from app.api.errors import error_response
from app.auth.encryption import EncryptionError
from app.auth.provider_proof import APPLE_ISSUER, InvalidProviderProof, verify_apple_notification
from app.auth.providers import ProviderUnavailable
from app.auth.sessions import (
    CSRF_HEADER, SESSION_COOKIE, SESSION_SECONDS, csrf_token, new_token,
    resolve_session, revoke_session, token_hash, valid_token,
)

router = APIRouter(prefix="/api/v1/auth", tags=["authentication"])
_BINDING = "__Host-unshaken_login"
_ONBOARDING = "__Host-unshaken_onboarding"
# These routes remain available to code review without entering the application.
_deferred_router = APIRouter(prefix="/api/v1/auth", tags=["authentication"])
_PROVIDERS = frozenset({"google"})


class Onboarding(BaseModel):
    """Only explicit display name and unit are accepted for a new profile."""

    display_name: str = Field(min_length=1, max_length=150)
    preferred_weight_unit: str


def _runtime(request: Request):
    """Require private settings and a configured authentication database."""
    runtime = getattr(request.app.state, "authentication", None)
    if runtime is None:
        raise HTTPException(503)
    return runtime


def _cookie(response, name, value, max_age, same_site):
    """Set a host-only browser credential on the canonical path."""
    response.set_cookie(
        name, value, max_age=max_age, secure=True, httponly=True, path="/", samesite=same_site
    )


def _opaque_cookie(request: Request, name: str, status: int = 401) -> str:
    """Read an opaque application cookie without accepting malformed inputs."""
    value = request.cookies.get(name)
    if not valid_token(value):
        raise HTTPException(status)
    return value


def _csrf(request: Request, secret: str, origin: str, purpose: str = "session") -> None:
    """Require both exact origin and a valid purpose-bound custom header."""
    supplied = request.headers.get(CSRF_HEADER, "")
    expected = csrf_token(secret, purpose)
    if (request.headers.get("Origin") != origin or not valid_token(supplied)
            or not hmac.compare_digest(supplied, expected)):
        raise HTTPException(403)


def _session_response(token: str, response=None):
    """Send the bearer only in the secure cookie after the database commit."""
    if response is None:
        response = JSONResponse({"status": "signed_in"})
    _cookie(response, SESSION_COOKIE, token, SESSION_SECONDS, "lax")
    return response


def _database_failure(request: Request):
    """Return a fixed response without emitting provider or database exception text."""
    return error_response(request, 503, "authentication_unavailable", "Authentication is unavailable.")


def current_user(request: Request):
    """Resolve an active user exclusively through the database session."""
    runtime = _runtime(request)
    token = _opaque_cookie(request, SESSION_COOKIE)
    try:
        with runtime.engine.begin() as connection:
            profile = resolve_session(connection, token)
    except SQLAlchemyError:
        raise HTTPException(503) from None
    if profile is None:
        raise HTTPException(401)
    return profile


def _admit_source(request: Request, connection, settings) -> bool:
    """Rate-limit the ASGI peer without storing its IP or reading raw forwarding headers."""
    from ipaddress import ip_address
    from app.db.auth_storage import admit_auth_source

    try:
        address = str(ip_address(request.client.host)) if request.client else "unknown"
    except ValueError:
        address = "unknown"
    key = settings.google_client_secret.encode("utf-8")
    digest = hmac.digest(key, b"unshaken:auth-source:v1:" + address.encode("ascii"), "sha256")
    return admit_auth_source(connection, digest)


def _rate_limit(request: Request):
    """Return a fixed response for a full source window."""
    return error_response(request, 429, "rate_limited", "Try again later.", {"Retry-After": "300"})


@router.get("/{provider}/start")
def start(provider: str, request: Request):
    """Start a five-minute browser-bound Google or Apple flow."""
    if provider not in _PROVIDERS:
        raise HTTPException(404)
    if request.query_params:
        raise HTTPException(422)
    runtime = _runtime(request)
    from app.auth.flows import AuthenticationBusy, create_transaction

    binding, state, nonce = new_token(), new_token(), new_token()
    verifier = csrf_token(binding, state)
    challenge = base64.urlsafe_b64encode(sha256(verifier.encode()).digest()).decode().rstrip("=")
    try:
        with runtime.engine.begin() as connection:
            if not _admit_source(request, connection, runtime.settings):
                return _rate_limit(request)
            create_transaction(connection, provider=provider, purpose="login",
                               binding=binding, state=state, nonce=nonce)
    except (SQLAlchemyError, AuthenticationBusy):
        return _database_failure(request)
    response = RedirectResponse(runtime.providers.authorization_url(provider, state, nonce, challenge), 303)
    _cookie(response, _BINDING, binding, 300, "none")
    return response


def _callback_error(request: Request, category: str):
    """Navigate to a fixed same-origin UI page without encoding failure details."""
    request.state.telemetry_failure_category = category
    return RedirectResponse("/auth/error", 303)


def _callback(request: Request, provider: str, values: dict):
    """Consume proof once before provider exchange and issue an approved result."""
    from app.auth.flows import AuthenticationBusy, AuthenticationFailed, consume, finish_link, finish_login

    state, code = values.get("state"), values.get("code")
    binding = request.cookies.get(_BINDING)
    response = None
    try:
        if not valid_token(state) or not valid_token(binding):
            raise AuthenticationFailed("Invalid authentication flow")
        runtime = _runtime(request)
        with runtime.engine.begin() as connection:
            transaction = consume(connection, state, binding, provider, ("login",))
        if not code or len(code) > 4096 or "error" in values:
            raise AuthenticationFailed("Invalid authentication proof")
        verified = runtime.providers.exchange(provider, code, csrf_token(binding, state),
                                              transaction["nonce_hash"])
        with runtime.engine.begin() as connection:
            if transaction["purpose"] == "link":
                result = "session"
                token = finish_link(connection, transaction, verified, runtime.settings)
            else:
                result, token = finish_login(
                    connection, verified, binding, runtime.settings, runtime.providers,
                    previous_session=request.cookies.get(SESSION_COOKIE),
                )
        if result == "revoked":
            raise AuthenticationFailed("Identity unavailable")
        response = RedirectResponse(runtime.settings.origin + transaction["return_path"], 303)
        if result == "session":
            _session_response(token, response)
        else:
            _cookie(response, _ONBOARDING, token, 300, "lax")
            _cookie(response, _BINDING, binding, 300, "lax")
            return response
    except (AuthenticationFailed, InvalidProviderProof):
        response = _callback_error(request, "authentication_failed")
    except (SQLAlchemyError, ProviderUnavailable, EncryptionError, AuthenticationBusy, HTTPException):
        response = _callback_error(request, "authentication_unavailable")
    response.delete_cookie(_BINDING, path="/", secure=True, httponly=True, samesite="none")
    return response


@router.get("/google/callback")
def google_callback(request: Request):
    """Complete Google's query callback without logging query values."""
    query = request.query_params
    if sum(len(value) for _, value in query.multi_items()) > 8192 or len(query.multi_items()) != len(query):
        return _callback(request, "google", {})
    return _callback(request, "google", dict(query))


@_deferred_router.post("/apple/callback")
async def apple_callback(request: Request):
    """Read a bounded Apple form POST and ignore optional user profile data."""
    try:
        if request.headers.get("content-type", "").split(";")[0] != "application/x-www-form-urlencoded":
            raise ValueError
        body = bytearray()
        async for chunk in request.stream():
            if len(body) + len(chunk) > 8192:
                raise ValueError
            body.extend(chunk)
        query = parse_qs(body.decode(), max_num_fields=12, keep_blank_values=True)
        if any(len(items) != 1 for items in query.values()):
            raise ValueError
        values = {name: items[0] for name, items in query.items()}
    except (ValueError, UnicodeError):
        values = {}
    return await run_in_threadpool(_callback, request, "apple", values)


@router.get("/session")
def read_session(request: Request):
    """Return the minimal session profile and CSRF proof."""
    token = request.cookies.get(SESSION_COOKIE)
    profile = current_user(request)
    return {"display_name": profile["display_name"],
            "preferred_weight_unit": profile["preferred_weight_unit"],
            "csrf_token": csrf_token(token)}


@router.get("/onboarding")
def onboarding_csrf(request: Request):
    """Give a browser-bound pending flow its own no-store CSRF token."""
    from app.auth.flows import onboarding_pending

    runtime = _runtime(request)
    state = _opaque_cookie(request, _ONBOARDING)
    binding = _opaque_cookie(request, _BINDING)
    try:
        with runtime.engine.connect() as connection:
            if not onboarding_pending(connection, state, binding, provider="google"):
                raise HTTPException(401)
    except SQLAlchemyError:
        return _database_failure(request)
    return {"csrf_token": csrf_token(state, "onboarding")}


@router.post("/onboarding")
def onboard(profile: Onboarding, request: Request):
    """Complete exactly one verified onboarding transaction."""
    runtime = _runtime(request)
    from app.auth.flows import AuthenticationFailed, finish_onboarding

    state = _opaque_cookie(request, _ONBOARDING)
    binding = _opaque_cookie(request, _BINDING)
    _csrf(request, state, runtime.settings.origin, "onboarding")
    name = profile.display_name.strip()
    if not name or profile.preferred_weight_unit not in {"kg", "lb"}:
        raise HTTPException(422)
    try:
        with runtime.engine.begin() as connection:
            token = finish_onboarding(connection, state, binding, name,
                                      profile.preferred_weight_unit, runtime.settings, provider="google",
                                      previous_session=request.cookies.get(SESSION_COOKIE))
    except AuthenticationFailed:
        response = error_response(request, 401, "authentication_failed",
                                  "Sign-in failed. Start a fresh authorization.")
        for key in (_ONBOARDING, _BINDING):
            response.delete_cookie(key, path="/", secure=True, httponly=True, samesite="lax")
        return response
    except (SQLAlchemyError, EncryptionError):
        return _database_failure(request)
    response = _session_response(token)
    for key in (_ONBOARDING, _BINDING):
        response.delete_cookie(key, path="/", secure=True, httponly=True, samesite="lax")
    return response


@router.post("/logout")
def logout(request: Request):
    """Commit revocation of the authenticated session before clearing the cookie."""
    runtime = _runtime(request)
    token = _opaque_cookie(request, SESSION_COOKIE)
    _csrf(request, token, runtime.settings.origin)
    try:
        with runtime.engine.begin() as connection:
            if resolve_session(connection, token) is None or not revoke_session(connection, token):
                raise HTTPException(401)
    except SQLAlchemyError:
        return _database_failure(request)
    response = JSONResponse({"status": "signed_out"})
    response.delete_cookie(SESSION_COOKIE, path="/", secure=True, httponly=True, samesite="lax")
    return response

def _process_notification(request: Request, token: str):
    """Verify a notification before applying identity revocation."""
    from app.auth.flows import revoke_apple_identity

    runtime = _runtime(request)
    try:
        kind, subject = verify_apple_notification(
            token, runtime.settings.apple_client_id, runtime.providers.keys("apple", token)
        )
        if kind in {"consent-revoked", "account-deleted"}:
            with runtime.engine.begin() as connection:
                revoke_apple_identity(connection, APPLE_ISSUER, subject)
    except InvalidProviderProof:
        return error_response(request, 401, "authentication_failed", "Invalid notification.")
    except (SQLAlchemyError, ProviderUnavailable):
        return _database_failure(request)
    return {"status": "accepted"}


@_deferred_router.post("/apple/notifications")
async def apple_notifications(request: Request):
    """Accept bounded JSON for Apple's signed server-to-server events."""
    try:
        body = bytearray()
        async for chunk in request.stream():
            if len(body) + len(chunk) > 20000:
                raise ValueError
            body.extend(chunk)
        token = json.loads(body)["payload"]
        if not isinstance(token, str) or not 1 <= len(token) <= 16384:
            raise ValueError
    except (ValueError, KeyError, TypeError):
        raise HTTPException(422) from None
    return await run_in_threadpool(_process_notification, request, token)

@_deferred_router.post("/identities/{provider}/link")
def link(provider: str, request: Request):
    """Start a separate linking flow after checking the source session and CSRF."""
    if provider not in _PROVIDERS:
        raise HTTPException(404)
    runtime = _runtime(request)
    session = _opaque_cookie(request, SESSION_COOKIE)
    _csrf(request, session, runtime.settings.origin)
    from app.auth.flows import AuthenticationBusy, create_transaction

    binding, state, nonce = new_token(), new_token(), new_token()
    from app.auth.flows import freshly_verified_owner

    source = token_hash(session)
    verifier = csrf_token(binding, state)
    challenge = base64.urlsafe_b64encode(sha256(verifier.encode()).digest()).decode().rstrip("=")
    try:
        with runtime.engine.begin() as connection:
            owner = freshly_verified_owner(connection, source, provider)
            if owner is None:
                return error_response(request, 403, "forbidden", "Sign in again before linking.")
            if not _admit_source(request, connection, runtime.settings):
                return _rate_limit(request)
            create_transaction(connection, provider=provider, purpose="link", binding=binding,
                               state=state, nonce=nonce, user_id=owner, link_session_hash=source)
    except (SQLAlchemyError, AuthenticationBusy):
        return _database_failure(request)
    response = JSONResponse({
        "authorization_url": runtime.providers.authorization_url(provider, state, nonce, challenge),
    })
    _cookie(response, _BINDING, binding, 300, "none")
    return response
