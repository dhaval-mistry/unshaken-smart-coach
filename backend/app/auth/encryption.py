"""Encrypt Apple refresh tokens before they enter database storage."""

import os
import re
from collections.abc import Mapping
from uuid import UUID

from cryptography.exceptions import InvalidTag
from cryptography.hazmat.primitives.ciphers.aead import AESGCM

_NONCE_SIZE = 12
_MAX_STORAGE_SIZE = 16384


class EncryptionError(ValueError):
    """A credential could not be encrypted or verified safely."""


def _cipher(keys: Mapping[str, bytes], version: str) -> AESGCM:
    """Load an explicitly versioned AES-256 key."""
    key = keys.get(version)
    if not re.fullmatch(r"[A-Za-z0-9._-]{1,64}", version) or key is None or len(key) != 32:
        raise EncryptionError("Credential key unavailable")
    return AESGCM(key)


def _context(identity_id: UUID, version: str) -> bytes:
    """Bind the envelope to its Apple identity and key version."""
    return b"unshaken:apple-refresh:v1:" + identity_id.bytes + version.encode("ascii")


def encrypt_refresh_token(
    token: bytes, identity_id: UUID, version: str, keys: Mapping[str, bytes]
) -> bytes:
    """Return a nonce followed by authenticated ciphertext for storage."""
    if not 1 <= len(token) <= _MAX_STORAGE_SIZE - _NONCE_SIZE - 16:
        raise EncryptionError("Invalid credential length")
    cipher = _cipher(keys, version)
    nonce = os.urandom(_NONCE_SIZE)
    return nonce + cipher.encrypt(nonce, token, _context(identity_id, version))


def decrypt_refresh_token(
    envelope: bytes, identity_id: UUID, version: str, keys: Mapping[str, bytes]
) -> bytes:
    """Return a verified refresh token or raise a generic failure."""
    if not _NONCE_SIZE + 16 < len(envelope) <= _MAX_STORAGE_SIZE:
        raise EncryptionError("Invalid encrypted credential")
    cipher = _cipher(keys, version)
    try:
        return cipher.decrypt(
            envelope[:_NONCE_SIZE], envelope[_NONCE_SIZE:], _context(identity_id, version)
        )
    except InvalidTag:
        raise EncryptionError("Invalid encrypted credential") from None

def _pending_context(state_hash: bytes, issuer: str, subject: str, version: str) -> bytes:
    """Bind an onboarding credential to its transaction and verified Apple claims."""
    import json

    claims = json.dumps(["apple", issuer, subject, "onboarding", version])
    return b"unshaken:apple-onboarding:v1:" + state_hash + claims.encode("ascii")


def encrypt_pending_token(
    token: bytes, state_hash: bytes, issuer: str, subject: str,
    version: str, keys: Mapping[str, bytes],
) -> bytes:
    """Seal an Apple credential for its short-lived onboarding transaction."""
    if not 1 <= len(token) <= _MAX_STORAGE_SIZE - _NONCE_SIZE - 16:
        raise EncryptionError("Invalid credential length")
    cipher = _cipher(keys, version)
    nonce = os.urandom(_NONCE_SIZE)
    return nonce + cipher.encrypt(
        nonce, token, _pending_context(state_hash, issuer, subject, version)
    )


def decrypt_pending_token(
    envelope: bytes, state_hash: bytes, issuer: str, subject: str,
    version: str, keys: Mapping[str, bytes],
) -> bytes:
    """Verify the pending envelope before promoting it to durable storage."""
    if not _NONCE_SIZE + 16 < len(envelope) <= _MAX_STORAGE_SIZE:
        raise EncryptionError("Invalid encrypted credential")
    cipher = _cipher(keys, version)
    try:
        return cipher.decrypt(
            envelope[:_NONCE_SIZE], envelope[_NONCE_SIZE:],
            _pending_context(state_hash, issuer, subject, version),
        )
    except InvalidTag:
        raise EncryptionError("Invalid encrypted credential") from None
