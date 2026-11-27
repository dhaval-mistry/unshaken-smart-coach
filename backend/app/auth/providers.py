"""Provider redirects and bounded backend requests to Google and Apple."""

import json
import threading
import time
from dataclasses import dataclass, field
from urllib.parse import urlencode

import httpx
import jwt

from app.auth.provider_proof import VerifiedIdentity, verify_identity_token
from app.auth.settings import AuthSettings

_AUTHORIZE = {
    "google": "https://accounts.google.com/o/oauth2/v2/auth",
    "apple": "https://appleid.apple.com/auth/authorize",
}
_TOKEN = {
    "google": "https://oauth2.googleapis.com/token",
    "apple": "https://appleid.apple.com/auth/token",
}
_JWKS = {
    "google": "https://www.googleapis.com/oauth2/v3/certs",
    "apple": "https://appleid.apple.com/auth/keys",
}
_MAX_PROVIDER_BYTES = 64 * 1024


class AppleRefreshRejected(ValueError):
    """Apple returned a definitive invalid-refresh response."""


class ProviderUnavailable(RuntimeError):
    """A bounded provider request could not produce a usable response."""


@dataclass(frozen=True)
class ExchangeResult:
    """The authenticated identity and optional Apple revocation credential."""

    identity: VerifiedIdentity
    refresh_token: bytes | None = field(repr=False)


class Providers:
    """Manage fixed provider endpoints and a bounded process-local key cache."""

    def __init__(self, settings: AuthSettings, client: httpx.Client | None = None):
        """Create the provider client, with a transport seam for signed fixtures."""
        self.settings = settings
        self.client = client or httpx.Client(timeout=4.0, trust_env=False)
        self._cache = {}
        self._lock = threading.Lock()

    def close(self) -> None:
        """Release the provider HTTP connection pool."""
        self.client.close()

    def client_id(self, provider: str) -> str:
        """Return the configured audience for a selected provider."""
        return {"google": self.settings.google_client_id,
                "apple": self.settings.apple_client_id}[provider]

    def authorization_url(self, provider: str, state: str, nonce: str, challenge: str) -> str:
        """Construct a redirect with a fixed provider and exact callback."""
        params = dict(client_id=self.client_id(provider),
                      redirect_uri=self.settings.callback(provider), response_type="code",
                      state=state, nonce=nonce)
        if provider == "google":
            params.update(scope="openid", code_challenge=challenge, code_challenge_method="S256")
        else:
            params.update(scope="name email", response_mode="form_post")
        return f"{_AUTHORIZE[provider]}?{urlencode(params)}"

    def _request(self, method: str, target: str, data=None, *, apple_refresh=False) -> dict:
        """Read a small JSON object from a fixed TLS endpoint."""
        try:
            with self.client.stream(method, target, data=data, follow_redirects=False) as response:
                check_rejection = apple_refresh and response.status_code == 400
                if not check_rejection:
                    response.raise_for_status()
                contents = bytearray()
                for chunk in response.iter_bytes(chunk_size=8192):
                    contents.extend(chunk)
                    if len(contents) > _MAX_PROVIDER_BYTES:
                        raise ProviderUnavailable("Authentication provider unavailable")
            result = json.loads(contents)
            if not isinstance(result, dict):
                raise ValueError
            if check_rejection:
                if result.get("error") == "invalid_grant":
                    raise AppleRefreshRejected("Apple refresh rejected")
                raise ProviderUnavailable("Authentication provider unavailable")
            return result
        except AppleRefreshRejected:
            raise
        except (httpx.HTTPError, ValueError):
            raise ProviderUnavailable("Authentication provider unavailable") from None

    def keys(self, provider: str, token: str) -> dict:
        """Refresh cached keys periodically and throttle unknown-key refreshes."""
        try:
            key_id = jwt.get_unverified_header(token).get("kid")
        except jwt.InvalidTokenError:
            return {"keys": []}
        with self._lock:
            now = time.monotonic()
            fetched, keys = self._cache.get(provider, (float("-inf"), {"keys": []}))
            known = any(isinstance(key, dict) and key.get("kid") == key_id
                        for key in keys["keys"])
            if now - fetched >= 300 or (not known and now - fetched >= 15):
                keys = self._request("GET", _JWKS[provider])
                if not isinstance(keys.get("keys"), list):
                    raise ProviderUnavailable("Authentication provider unavailable")
                self._cache[provider] = (now, keys)
            return keys

    def _apple_secret(self) -> str:
        """Sign a short-lived Apple client assertion with the runtime key."""
        now = int(time.time())
        settings = self.settings
        try:
            return jwt.encode(
                {"iss": settings.apple_team_id, "iat": now, "exp": now + 300,
                 "aud": "https://appleid.apple.com", "sub": settings.apple_client_id},
                settings.apple_signing_key, algorithm="ES256",
                headers={"kid": settings.apple_key_id},
            )
        except (jwt.PyJWTError, ValueError, TypeError):
            raise ProviderUnavailable("Authentication provider unavailable") from None

    def exchange(self, provider: str, code: str, verifier: str, nonce_hash: bytes) -> ExchangeResult:
        """Exchange one authorization code and verify the signed identity proof."""
        form = dict(grant_type="authorization_code", code=code,
                    redirect_uri=self.settings.callback(provider), client_id=self.client_id(provider))
        if provider == "google":
            form.update(client_secret=self.settings.google_client_secret, code_verifier=verifier)
        else:
            form.update(client_secret=self._apple_secret())
        result = self._request("POST", _TOKEN[provider], form)
        token = result.get("id_token")
        if not isinstance(token, str) or not 1 <= len(token) <= 16384:
            raise ProviderUnavailable("Authentication provider unavailable")
        identity = verify_identity_token(
            token, provider, self.client_id(provider), self.keys(provider, token), nonce_hash
        )
        refresh = result.get("refresh_token") if provider == "apple" else None
        return ExchangeResult(identity, refresh.encode() if isinstance(refresh, str) and refresh else None)


    def refresh_apple(self, refresh_token: bytes) -> None:
        """Verify a stored refresh credential and classify definitive invalidation."""
        try:
            refresh = refresh_token.decode()
        except UnicodeError:
            raise ProviderUnavailable("Authentication provider unavailable") from None
        response = self._request("POST", _TOKEN["apple"], {
            "grant_type": "refresh_token",
            "refresh_token": refresh,
            "client_id": self.settings.apple_client_id,
            "client_secret": self._apple_secret(),
        }, apple_refresh=True)
        if not isinstance(response.get("access_token"), str) or not response["access_token"]:
            raise ProviderUnavailable("Authentication provider unavailable")
