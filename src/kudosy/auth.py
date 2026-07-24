"""Optional password-gated session auth for the whole /api/* surface.

Inactive unless ``KUDOSY_AUTH_PASSWORD`` is set (see settings.py) — every
function here is a no-op / always-pass in that case, so existing
unauthenticated deployments keep working exactly as before.

When active, a signed, timestamped session cookie gates every ``/api/*``
route except ``/api/login`` and ``/api/auth-status`` (``/api/logout`` is also
exempt so a stale/invalid cookie can always be cleared). The cookie is an
HMAC-SHA256-signed timestamp — no server-side session store needed, verified
with a timing-safe comparison. See routes.py for the login/logout/status
endpoints and the ``require_auth`` dependency wiring.
"""

from __future__ import annotations

import hashlib
import hmac
import logging
import time

from fastapi import HTTPException, Request

from kudosy.settings import get_settings
from kudosy.store import read_or_create_session_secret

log = logging.getLogger(__name__)

SESSION_COOKIE_NAME = "kudosy_session"

# In-process brute-force guard for /api/login. Not distributed and not
# per-IP — deliberately simple for a single-process, single-user self-hosted
# app; it just slows down repeated guesses rather than being a hard limiter.
_LOGIN_LOCKOUT_MAX_FAILURES = 5
_LOGIN_LOCKOUT_WINDOW_S = 60.0

_secret_cache: bytes | None = None
_failed_login_timestamps: list[float] = []


def reset_auth_state_for_tests() -> None:
    """Clear process-level caches. Test-only — see conftest.py."""
    global _secret_cache
    _secret_cache = None
    _failed_login_timestamps.clear()


def _secret() -> bytes:
    global _secret_cache
    if _secret_cache is not None:
        return _secret_cache
    env_secret = get_settings().secret_key
    _secret_cache = env_secret.encode("utf-8") if env_secret else read_or_create_session_secret()
    return _secret_cache


def auth_enabled() -> bool:
    """True when a login is required (KUDOSY_AUTH_PASSWORD is set and non-empty)."""
    return bool(get_settings().auth_password)


def create_session_token(*, now: float | None = None) -> str:
    """Return a new signed session token: ``"<issued_at>.<hmac_hex>"``."""
    issued_at = str(int(now if now is not None else time.time()))
    sig = hmac.new(_secret(), issued_at.encode("ascii"), hashlib.sha256).hexdigest()
    return f"{issued_at}.{sig}"


def verify_session_token(token: str | None, *, now: float | None = None) -> bool:
    """Check signature validity and expiry (session_ttl_hours) of *token*."""
    if not token or "." not in token:
        return False
    issued_at_str, _, sig = token.partition(".")
    if not issued_at_str.isdigit():
        return False
    expected_sig = hmac.new(_secret(), issued_at_str.encode("ascii"), hashlib.sha256).hexdigest()
    if not hmac.compare_digest(sig, expected_sig):
        return False
    issued_at = int(issued_at_str)
    ttl_seconds = get_settings().session_ttl_hours * 3600
    current = now if now is not None else time.time()
    return 0 <= (current - issued_at) <= ttl_seconds


def is_login_locked_out(*, now: float | None = None) -> bool:
    """True when too many login attempts failed within the lockout window."""
    current = now if now is not None else time.time()
    cutoff = current - _LOGIN_LOCKOUT_WINDOW_S
    while _failed_login_timestamps and _failed_login_timestamps[0] < cutoff:
        _failed_login_timestamps.pop(0)
    return len(_failed_login_timestamps) >= _LOGIN_LOCKOUT_MAX_FAILURES


def record_login_failure(*, now: float | None = None) -> None:
    _failed_login_timestamps.append(now if now is not None else time.time())


def record_login_success() -> None:
    _failed_login_timestamps.clear()


def verify_password(password: str) -> bool:
    """Timing-safe comparison against the configured KUDOSY_AUTH_PASSWORD."""
    expected = get_settings().auth_password or ""
    if not expected:
        return False
    return hmac.compare_digest(password, expected)


async def require_auth(request: Request) -> None:
    """FastAPI dependency: raise 401 unless a valid session cookie is present.

    A no-op when auth isn't configured at all.
    """
    if not auth_enabled():
        return
    token = request.cookies.get(SESSION_COOKIE_NAME)
    if not verify_session_token(token):
        raise HTTPException(
            status_code=401,
            detail={"code": "AUTH_REQUIRED", "message": "Anmeldung erforderlich"},
        )
