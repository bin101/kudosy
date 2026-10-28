"""App-level tests: an expired cookie (AuthError) must flip authOk to false.

Unlike test_routes.py these tests keep the REAL run_job_fn created by the
lifespan, so the AuthError handling in app._run_job is exercised end-to-end:
StravaClient (faked) raises AuthError → engine propagates → app sets
auth_ok=False → GET /api/status reports authOk: false.
"""

from __future__ import annotations

from collections.abc import Generator
from pathlib import Path
from unittest.mock import AsyncMock

import pytest
from fastapi.testclient import TestClient

from kudosy.app import create_app, get_app_state
from kudosy.feed import AuthError
from kudosy.models import AppSettings, UserConfig

# ── Fakes ─────────────────────────────────────────────────────────────────────


class FakeAuthFailClient:
    """StravaClient stand-in whose CSRF fetch always raises AuthError."""

    def __init__(self, cookies: dict[str, str]) -> None:
        self.cookies = cookies

    def current_cookies(self) -> dict[str, str]:
        return self.cookies

    async def get_csrf_token(self) -> str:
        raise AuthError("Cookie abgelaufen")

    async def aclose(self) -> None:
        return None


# ── Fixture: real lifespan, real run_job_fn, faked Strava client ──────────────


@pytest.fixture()
def real_job_client(data_dir: Path, monkeypatch: pytest.MonkeyPatch) -> Generator[TestClient]:
    from kudosy import store

    store.bootstrap()
    store.write_user_config(UserConfig(stravaSessionCookie="expired-cookie", athleteId="20000001"))
    # updateCheckEnabled=False keeps /api/status from calling out to GitHub
    # (ignored until the update-check feature lands — pydantic drops extras).
    store.write_settings(
        AppSettings.model_validate({"schedulerEnabled": False, "updateCheckEnabled": False})
    )

    # No network during lifespan startup
    monkeypatch.setattr("kudosy.app.fetch_sport_types", AsyncMock(return_value=[]))
    # _run_job imports StravaClient lazily from kudosy.strava_client
    monkeypatch.setattr("kudosy.strava_client.StravaClient", FakeAuthFailClient)

    app = create_app()
    with TestClient(app, raise_server_exceptions=True) as client:
        yield client


# ── Tests ─────────────────────────────────────────────────────────────────────


def test_auth_error_sets_auth_ok_false(real_job_client: TestClient) -> None:
    """POST /api/run with an expired cookie → /api/status reports authOk false."""
    resp = real_job_client.post("/api/run", json={})
    assert resp.status_code == 200

    status = real_job_client.get("/api/status").json()
    assert status["authOk"] is False
    assert get_app_state()["auth_ok"] is False


def test_run_with_auth_error_keeps_stored_cookies(
    real_job_client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    """After an AuthError the client reports its initial cookies, so nothing is rewritten."""
    from kudosy import store

    store.write_user_config(
        UserConfig(stravaCookies={"_strava4_session": "expired-cookie"}, athleteId="20000001")
    )
    real_job_client.post("/api/run", json={})

    cfg = store.read_user_config()
    assert cfg is not None
    assert cfg.stravaCookies == {"_strava4_session": "expired-cookie"}


def test_run_persists_rotated_cookies_without_logging_values(
    real_job_client: TestClient,
    monkeypatch: pytest.MonkeyPatch,
    caplog: pytest.LogCaptureFixture,
) -> None:
    """A client whose jar rotated gets its cookies stored; the log never shows full values."""
    from kudosy import store

    class RotatingClient(FakeAuthFailClient):
        def current_cookies(self) -> dict[str, str]:
            return {"_strava4_session": "rotated-session-value"}

    store.write_user_config(
        UserConfig(stravaCookies={"_strava4_session": "expired-cookie"}, athleteId="20000001")
    )
    monkeypatch.setattr("kudosy.strava_client.StravaClient", RotatingClient)
    with caplog.at_level("DEBUG"):
        real_job_client.post("/api/run", json={})

    cfg = store.read_user_config()
    assert cfg is not None
    assert cfg.stravaCookies == {"_strava4_session": "rotated-session-value"}
    assert "Strava-Session erneuert" in caplog.text
    assert "rotated-session-value" not in caplog.text
    assert "expired-cookie" not in caplog.text


def test_failing_persist_does_not_mask_result_or_skip_aclose(
    real_job_client: TestClient, monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture
) -> None:
    closed: list[bool] = []

    class BrokenPersistClient(FakeAuthFailClient):
        def current_cookies(self) -> dict[str, str]:
            raise OSError("disk full")

        async def aclose(self) -> None:
            closed.append(True)

    monkeypatch.setattr("kudosy.strava_client.StravaClient", BrokenPersistClient)
    with caplog.at_level("WARNING"):
        resp = real_job_client.post("/api/run", json={})

    assert resp.status_code == 200
    assert closed == [True]
    assert "Could not persist refreshed Strava cookies" in caplog.text
    assert get_app_state()["auth_ok"] is False  # the original AuthError handling still ran
