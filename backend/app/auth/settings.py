"""Load one private runtime settings file for browser authentication."""

import base64
import json
import os
from dataclasses import dataclass, field
from pathlib import Path
from urllib.parse import urlsplit


@dataclass(frozen=True)
class AuthSettings:
    """Provider settings and encryption keys read only at runtime."""

    origin: str
    google_client_id: str
    google_client_secret: str = field(repr=False)
    apple_client_id: str
    apple_team_id: str
    apple_key_id: str
    apple_signing_key: str = field(repr=False)
    active_key_version: str
    encryption_keys: dict[str, bytes] = field(repr=False)

    def callback(self, provider: str) -> str:
        """Return the single registered callback for the selected provider."""
        if provider not in {"apple", "google"}:
            raise ValueError("Unsupported provider")
        return f"{self.origin}/api/v1/auth/{provider}/callback"


def load_auth_settings() -> AuthSettings:
    """Fail safely when the private runtime settings are absent or unusable."""
    try:
        with Path(os.environ["USC_AUTH_SETTINGS_FILE"]).open("rb") as handle:
            payload = handle.read(65537)
        if len(payload) > 65536:
            raise ValueError
        values = json.loads(payload)
        values["encryption_keys"] = {
            version: base64.b64decode(key, validate=True)
            for version, key in values["encryption_keys"].items()
        }
        settings = AuthSettings(**values)
        origin = urlsplit(settings.origin)
        if (origin.scheme != "https" or not origin.hostname or origin.username
                or origin.password or origin.path or origin.query or origin.fragment
                or settings.origin != f"https://{origin.netloc}"
                or any(char.isspace() for char in settings.origin)
                or any(len(key) != 32 for key in settings.encryption_keys.values())
                or settings.active_key_version not in settings.encryption_keys):
            raise ValueError
    except (OSError, KeyError, TypeError, AttributeError, ValueError):
        raise ValueError("Authentication settings unavailable") from None
    return settings
