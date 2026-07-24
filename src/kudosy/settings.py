"""Runtime environment settings via pydantic-settings.

All values can be overridden with environment variables (prefix KUDOSY_).
"""

from __future__ import annotations

from pydantic_settings import BaseSettings, SettingsConfigDict


class KudosySettings(BaseSettings):
    """Top-level environment configuration for Kudosy."""

    model_config = SettingsConfigDict(
        env_prefix="KUDOSY_",
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    data_dir: str = "/data"
    port: int = 8080
    log_level: str = "INFO"
    # Loopback-only by default for the no-Docker "run locally" path (see
    # CLAUDE.md) — there is no authentication in front of the API unless
    # KUDOSY_AUTH_PASSWORD is set, so binding to all interfaces by default
    # would expose the Strava session cookie and full control of the app to
    # anyone on the same network. Set KUDOSY_HOST=0.0.0.0 to allow LAN access.
    # The Docker image explicitly sets KUDOSY_HOST=0.0.0.0 (see Dockerfile) —
    # this default only affects `python -m kudosy` runs outside a container.
    host: str = "127.0.0.1"

    # ── Optional login screen ──────────────────────────────────────────────
    # Unset by default → no auth, exactly today's behavior. Set
    # KUDOSY_AUTH_PASSWORD to require a login before any /api/* call works
    # (see auth.py and README "Access Control").
    auth_password: str | None = None
    # How long a successful login stays valid before requiring a fresh one.
    session_ttl_hours: int = 720  # 30 days
    # HMAC key signing session cookies. If unset, a random key is generated
    # once and persisted to KUDOSY_DATA_DIR/session-secret (see
    # store.read_or_create_session_secret) so sessions survive restarts.
    # Set explicitly to invalidate all sessions on demand, or to share a key
    # across multiple replicas (not a supported deployment shape today, but
    # this keeps the option open).
    secret_key: str | None = None
    # Send the session cookie with Secure (HTTPS-only). Only enable this if
    # Kudosy is actually served over HTTPS (e.g. behind a TLS-terminating
    # reverse proxy) — otherwise the browser will silently drop the cookie.
    cookie_secure: bool = False


# Singleton loaded at import time — override in tests via env var KUDOSY_DATA_DIR
_settings: KudosySettings | None = None


def get_settings() -> KudosySettings:
    global _settings
    if _settings is None:
        _settings = KudosySettings()
    return _settings
