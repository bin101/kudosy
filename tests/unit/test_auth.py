"""Unit tests for kudosy.auth — the optional login-gate for /api/*.

All tests go through the `data_dir` fixture (redirects KUDOSY_DATA_DIR and
resets the settings + auth module singletons) so the session secret and
KUDOSY_AUTH_PASSWORD env var never leak between tests.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from kudosy import auth


def _enable_auth(monkeypatch: pytest.MonkeyPatch, password: str = "correct-horse") -> None:
    monkeypatch.setenv("KUDOSY_AUTH_PASSWORD", password)
    import kudosy.settings as settings_mod

    settings_mod._settings = None  # type: ignore[attr-defined]


# ── auth_enabled ──────────────────────────────────────────────────────────────


def test_auth_disabled_by_default(data_dir: Path) -> None:
    assert auth.auth_enabled() is False


def test_auth_enabled_when_password_set(data_dir: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    _enable_auth(monkeypatch)
    assert auth.auth_enabled() is True


# ── session tokens ────────────────────────────────────────────────────────────


def test_create_and_verify_session_token_round_trip(data_dir: Path) -> None:
    token = auth.create_session_token(now=1_000_000.0)
    assert auth.verify_session_token(token, now=1_000_000.0) is True


def test_verify_session_token_rejects_tampered_signature(data_dir: Path) -> None:
    token = auth.create_session_token(now=1_000_000.0)
    issued_at, _, _sig = token.partition(".")
    tampered = f"{issued_at}.deadbeef"
    assert auth.verify_session_token(tampered, now=1_000_000.0) is False


def test_verify_session_token_rejects_expired(
    data_dir: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("KUDOSY_SESSION_TTL_HOURS", "1")
    import kudosy.settings as settings_mod

    settings_mod._settings = None  # type: ignore[attr-defined]

    token = auth.create_session_token(now=1_000_000.0)
    one_hour_and_one_second_later = 1_000_000.0 + 3601
    assert auth.verify_session_token(token, now=one_hour_and_one_second_later) is False


def test_verify_session_token_rejects_none_and_malformed(data_dir: Path) -> None:
    assert auth.verify_session_token(None) is False
    assert auth.verify_session_token("") is False
    assert auth.verify_session_token("not-a-token") is False
    assert auth.verify_session_token("abc.def") is False  # non-numeric issued_at


def test_secret_persists_across_calls(data_dir: Path) -> None:
    """Two independently-created tokens must verify against the same secret
    (i.e. the secret is persisted to disk, not regenerated per call)."""
    token1 = auth.create_session_token(now=1_000_000.0)
    auth.reset_auth_state_for_tests()  # force _secret() to re-read from disk
    assert auth.verify_session_token(token1, now=1_000_000.0) is True


# ── password verification ─────────────────────────────────────────────────────


def test_verify_password_rejects_when_auth_disabled(data_dir: Path) -> None:
    assert auth.verify_password("anything") is False


def test_verify_password_correct(data_dir: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    _enable_auth(monkeypatch, password="correct-horse")
    assert auth.verify_password("correct-horse") is True


def test_verify_password_incorrect(data_dir: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    _enable_auth(monkeypatch, password="correct-horse")
    assert auth.verify_password("wrong") is False


# ── login lockout ─────────────────────────────────────────────────────────────


def test_login_not_locked_out_initially(data_dir: Path) -> None:
    assert auth.is_login_locked_out() is False


def test_login_locks_out_after_max_failures(data_dir: Path) -> None:
    for _ in range(auth._LOGIN_LOCKOUT_MAX_FAILURES):
        auth.record_login_failure(now=1_000_000.0)
    assert auth.is_login_locked_out(now=1_000_000.0) is True


def test_login_lockout_expires_after_window(data_dir: Path) -> None:
    for _ in range(auth._LOGIN_LOCKOUT_MAX_FAILURES):
        auth.record_login_failure(now=1_000_000.0)
    later = 1_000_000.0 + auth._LOGIN_LOCKOUT_WINDOW_S + 1
    assert auth.is_login_locked_out(now=later) is False


def test_login_success_clears_failure_history(data_dir: Path) -> None:
    for _ in range(auth._LOGIN_LOCKOUT_MAX_FAILURES):
        auth.record_login_failure(now=1_000_000.0)
    auth.record_login_success()
    assert auth.is_login_locked_out(now=1_000_000.0) is False


# ── require_auth dependency ───────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_require_auth_passes_when_disabled(data_dir: Path) -> None:
    from unittest.mock import MagicMock

    request = MagicMock()
    request.cookies = {}
    await auth.require_auth(request)  # must not raise


@pytest.mark.asyncio
async def test_require_auth_raises_without_cookie_when_enabled(
    data_dir: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from unittest.mock import MagicMock

    from fastapi import HTTPException

    _enable_auth(monkeypatch)
    request = MagicMock()
    request.cookies = {}
    with pytest.raises(HTTPException) as exc_info:
        await auth.require_auth(request)
    assert exc_info.value.status_code == 401


@pytest.mark.asyncio
async def test_require_auth_passes_with_valid_cookie(
    data_dir: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from unittest.mock import MagicMock

    _enable_auth(monkeypatch)
    token = auth.create_session_token()
    request = MagicMock()
    request.cookies = {auth.SESSION_COOKIE_NAME: token}
    await auth.require_auth(request)  # must not raise
