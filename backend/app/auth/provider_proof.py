"""Verify Google and Apple identity proofs against fixed provider keys."""

import hmac
from collections.abc import Mapping
from dataclasses import dataclass
from hashlib import sha256

import jwt
from jwt import InvalidTokenError

APPLE_ISSUER = "https://appleid.apple.com"
GOOGLE_ISSUER = "https://accounts.google.com"
_ISSUERS = {
    "apple": (APPLE_ISSUER,),
    "google": (GOOGLE_ISSUER, "accounts.google.com"),
}


class InvalidProviderProof(ValueError):
    """The presented provider proof could not authenticate a user."""


@dataclass(frozen=True)
class VerifiedIdentity:
    """Canonical provider identity derived solely from authenticated claims."""

    provider: str
    issuer: str
    subject: str


def _provider_key(token: str, jwks: Mapping):
    """Select exactly one RSA signing key for the presented key ID."""
    header = jwt.get_unverified_header(token)
    key_id = header.get("kid")
    if not isinstance(key_id, str) or not key_id or header.get("alg") != "RS256":
        raise InvalidProviderProof("Invalid identity proof")
    candidates = [
        key for key in jwks["keys"]
        if key.get("kid") == key_id and key.get("kty") == "RSA"
        and key.get("alg", "RS256") == "RS256" and key.get("use", "sig") == "sig"
    ]
    if len(candidates) != 1:
        raise InvalidProviderProof("Invalid identity proof")
    return jwt.PyJWK.from_dict(candidates[0], algorithm="RS256").key


def verify_identity_token(
    token: str,
    provider: str,
    client_id: str,
    jwks: Mapping,
    nonce_hash: bytes,
) -> VerifiedIdentity:
    """Check signed claims and bind the proof to the expected browser flow."""
    issuers = _ISSUERS.get(provider)
    if not issuers or not client_id or len(token) > 16384:
        raise InvalidProviderProof("Invalid identity proof")
    try:
        claims = jwt.decode(
            token,
            _provider_key(token, jwks),
            algorithms=["RS256"],
            audience=client_id,
            issuer=issuers,
            options={"require": ["iss", "sub", "aud", "iat", "exp", "nonce"],
                     "strict_aud": True},
        )
        nonce = claims["nonce"]
        subject = claims["sub"]
        if (not isinstance(nonce, str)
                or not hmac.compare_digest(sha256(nonce.encode()).digest(), nonce_hash)
                or not subject or len(subject) > 512 or subject.strip() != subject
                or ("azp" in claims and claims["azp"] != client_id)):
            raise InvalidProviderProof("Invalid identity proof")
    except (InvalidTokenError, jwt.PyJWTError, TypeError, KeyError, AttributeError):
        raise InvalidProviderProof("Invalid identity proof") from None
    return VerifiedIdentity(provider, issuers[0], subject)

def verify_apple_notification(token: str, client_id: str, jwks: Mapping) -> tuple[str, str]:
    """Validate a server notification against the expected Apple app."""
    import json

    if not 1 <= len(token) <= 16384:
        raise InvalidProviderProof("Invalid notification")
    try:
        claims = jwt.decode(
            token, _provider_key(token, jwks), algorithms=["RS256"],
            issuer=APPLE_ISSUER, audience=client_id,
            options={"require": ["iss", "aud", "iat", "jti", "events"], "strict_aud": True},
        )
        events = claims["events"]
        if isinstance(events, str):
            events = json.loads(events)
        kind, subject = events["type"], events["sub"]
        if (kind not in {"consent-revoked", "account-deleted", "email-disabled", "email-enabled"}
                or not isinstance(subject, str) or not 1 <= len(subject) <= 512
                or subject.strip() != subject):
            raise InvalidProviderProof("Invalid notification")
    except (jwt.PyJWTError, KeyError, TypeError, AttributeError, ValueError):
        raise InvalidProviderProof("Invalid notification") from None
    return kind, subject
