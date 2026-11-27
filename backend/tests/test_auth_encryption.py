"""Verify the Apple credential envelope with synthetic keys and tokens."""

from uuid import uuid4

import pytest

from app.auth.encryption import (
    EncryptionError,
    decrypt_refresh_token,
    encrypt_refresh_token,
)


def test_round_trip_and_authentication():
    """Only the matching key and identity can open an intact envelope."""
    identity = uuid4()
    token = b"synthetic refresh token"
    keys = {"test.v1": b"a" * 32}
    envelope = encrypt_refresh_token(token, identity, "test.v1", keys)
    assert token not in envelope
    assert decrypt_refresh_token(envelope, identity, "test.v1", keys) == token

    for contents, owner, runtime_keys in (
        (envelope, identity, {}),
        (envelope, identity, {"test.v1": b"b" * 32}),
        (envelope[:-1] + bytes([envelope[-1] ^ 1]), identity, keys),
        (envelope, uuid4(), keys),
    ):
        with pytest.raises(EncryptionError):
            decrypt_refresh_token(contents, owner, "test.v1", runtime_keys)

    with pytest.raises(EncryptionError):
        encrypt_refresh_token(token, identity, "test.v1", {})
