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

    def __init__(self, cookie: str) -> None:
        self.cookie = cookie

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
    store.write_settings(AppSettings(schedulerEnabled=False))

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
