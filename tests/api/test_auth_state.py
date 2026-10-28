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


class FakeFeedFailClient(FakeAuthFailClient):
    """Passes the auth probe, then fails like a changed Strava page would."""

    async def get_csrf_token(self) -> str:
        return "csrf"

    async def fetch_current_athlete_id(self) -> str | None:
        return "20000001"

    async def fetch_following_feed(self, athlete_id: str, **_: object) -> dict[str, object]:
        raise RuntimeError("Feed page 1 unavailable")


class FakeOkClient(FakeFeedFailClient):
    async def fetch_following_feed(self, athlete_id: str, **_: object) -> dict[str, object]:
        return {"entries": [], "pagination": {"hasMore": False}}


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


def test_auth_error_is_stored_as_failed_last_run_with_code(
    real_job_client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The error code reaches the UI through lastRun instead of 'no run yet'."""

    class ExpiredClient(FakeAuthFailClient):
        async def get_csrf_token(self) -> str:
            err = AuthError("Session weg")
            err.code = "AUTH_SESSION_EXPIRED"
            raise err

    monkeypatch.setattr("kudosy.strava_client.StravaClient", ExpiredClient)
    real_job_client.post("/api/run", json={})

    status = real_job_client.get("/api/status").json()
    last = status["lastRun"]
    assert last is not None
    assert last["success"] is False
    assert last["error_code"] == "AUTH_SESSION_EXPIRED"
    assert "Session weg" in last["error"]
    assert get_app_state()["last_run"].error_code == "AUTH_SESSION_EXPIRED"


def test_auth_error_run_is_not_written_to_run_history(real_job_client: TestClient) -> None:
    from kudosy import store

    real_job_client.post("/api/run", json={})
    assert store.read_run_history() == []


def test_failed_run_without_auth_error_does_not_claim_auth_ok(
    real_job_client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    get_app_state().pop("auth_ok", None)
    monkeypatch.setattr("kudosy.strava_client.StravaClient", FakeFeedFailClient)
    real_job_client.post("/api/run", json={})

    status = real_job_client.get("/api/status").json()
    assert status["authOk"] is None
    assert status["lastRun"]["success"] is False
    assert "Feed page 1 unavailable" in status["lastRun"]["error"]


def test_failed_run_keeps_previous_auth_failure(
    real_job_client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    get_app_state()["auth_ok"] = False
    monkeypatch.setattr("kudosy.strava_client.StravaClient", FakeFeedFailClient)
    real_job_client.post("/api/run", json={})
    assert real_job_client.get("/api/status").json()["authOk"] is False


def test_successful_run_sets_auth_ok_true(
    real_job_client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    get_app_state()["auth_ok"] = False
    monkeypatch.setattr("kudosy.strava_client.StravaClient", FakeOkClient)
    real_job_client.post("/api/run", json={})

    status = real_job_client.get("/api/status").json()
    assert status["authOk"] is True
    assert status["lastRun"]["error"] is None
