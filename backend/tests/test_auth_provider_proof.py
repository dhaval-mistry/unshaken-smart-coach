"""Verify identity claims using synthetic, locally signed Google and Apple JWTs."""

from datetime import datetime, timedelta, timezone
from hashlib import sha256

import jwt
import pytest
from cryptography.hazmat.primitives.asymmetric import rsa

from app.auth.provider_proof import InvalidProviderProof, verify_identity_token


@pytest.mark.parametrize("provider,issuer", [
    ("google", "https://accounts.google.com"),
    ("apple", "https://appleid.apple.com"),
])
def test_signed_provider_claims(provider, issuer):
    """Accept only an intact proof for the selected client, issuer and flow."""
    key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    jwk = jwt.algorithms.RSAAlgorithm.to_jwk(key.public_key(), as_dict=True)
    jwk["kid"] = "fixture"
    now = datetime.now(timezone.utc)
    claims = dict(iss=issuer, sub="synthetic-user", aud="local-client", iat=now,
                  exp=now + timedelta(minutes=1), nonce="synthetic-nonce")
    expected_nonce = sha256(b"synthetic-nonce").digest()

    def verify(**overrides):
        """Sign modified claims and validate them against the original flow."""
        proof = jwt.encode(claims | overrides, key, algorithm="RS256", headers={"kid": "fixture"})
        return verify_identity_token(proof, provider, "local-client", {"keys": [jwk]}, expected_nonce)

    assert verify().subject == "synthetic-user"
    for invalid in (
        {"nonce": "other"}, {"aud": "other"}, {"iss": "https://wrong.invalid"},
        {"exp": now - timedelta(seconds=1)},
    ):
        with pytest.raises(InvalidProviderProof):
            verify(**invalid)
