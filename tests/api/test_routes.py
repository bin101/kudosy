"""API tests — full round-trip through FastAPI routes using TestClient.

The lifespan is bypassed: app state is pre-seeded with stubs so the routes
themselves are tested without any real Strava HTTP calls or scheduler.
"""

from __future__ import annotations

from datetime import UTC
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock

import pytest
from fastapi.testclient import TestClient

from kudosy.app import create_app, get_app_state
from kudosy.models import AppSettings, Defaults, RunResult, UserConfig
from kudosy.sport_types import ALL_SPORT_TYPES

# ── App fixture ────────────────────────────────────────────────────────────────


@pytest.fixture()
def app_client(data_dir: Path) -> TestClient:
    """Create a TestClient with lifespan disabled and app state pre-seeded."""
    from kudosy import store

    store.bootstrap()

    # Seed a user config so cookie-dependent routes work
    store.write_user_config(
        UserConfig(
            stravaSessionCookie="test-session-cookie",
            athleteId="20000001",
        )
    )
    store.write_settings(AppSettings())
    store.write_defaults(Defaults())

    app = create_app()

    # Pre-seed app.state so routes that access it work (lifespan won't run)
    app.state.active_sport_types = ALL_SPORT_TYPES

    fake_scheduler = MagicMock()
    fake_scheduler.is_running = False
    fake_scheduler.next_run_at = None

    state = get_app_state()
    state.clear()
    state.update(
        {
            "scheduler": fake_scheduler,
            "job_fn": AsyncMock(),
            "run_job_fn": AsyncMock(return_value=None),
            "last_run": None,
        }
    )

    with TestClient(app, raise_server_exceptions=True) as client:
        # Clear the startup log so log-endpoint tests start from a clean state
        log_file = data_dir / "last-run.log"
        if log_file.exists():
            log_file.unlink()
        # Re-seed app state that the lifespan may have replaced
        get_app_state().update(
            {
                "scheduler": fake_scheduler,
                "job_fn": AsyncMock(),
                "run_job_fn": AsyncMock(return_value=None),
                "last_run": None,
            }
        )
        yield client


# ── /api/config ───────────────────────────────────────────────────────────────


def test_get_config(app_client: TestClient) -> None:
    resp = app_client.get("/api/config")
    assert resp.status_code == 200
    data = resp.json()
    assert data["athleteId"] == "20000001"
    assert data["stravaSessionCookie"] == "test-session-cookie"


def test_put_config_ok(app_client: TestClient) -> None:
    payload = {
        "stravaSessionCookie": "new-cookie",
        "athleteId": "20000002",
        "ignoreAthletes": ["99999"],
        "kudoRules": {"minDistance": {}, "minTime": {}, "activityNames": []},
    }
    resp = app_client.put("/api/config", json=payload)
    assert resp.status_code == 200
    assert resp.json() == {"ok": True}

    # Verify it was persisted
    resp2 = app_client.get("/api/config")
    assert resp2.json()["athleteId"] == "20000002"


def test_put_config_empty_cookie_is_400(app_client: TestClient) -> None:
    resp = app_client.put("/api/config", json={"stravaSessionCookie": ""})
    assert resp.status_code == 400


# ── /api/defaults ─────────────────────────────────────────────────────────────


def test_get_defaults(app_client: TestClient) -> None:
    resp = app_client.get("/api/defaults")
    assert resp.status_code == 200
    data = resp.json()
    assert "catchAll" in data
    assert "kudoRules" in data


def test_put_defaults_ok(app_client: TestClient) -> None:
    payload = {
        "catchAll": {"minDistance": 3.0, "minTime": 20.0},
        "kudoRules": {"minDistance": {"Run": 5.0}, "minTime": {}, "activityNames": []},
    }
    resp = app_client.put("/api/defaults", json=payload)
    assert resp.status_code == 200

    resp2 = app_client.get("/api/defaults")
    data = resp2.json()
    assert data["catchAll"]["minDistance"] == 3.0


# ── /api/settings ─────────────────────────────────────────────────────────────


def test_get_settings(app_client: TestClient) -> None:
    resp = app_client.get("/api/settings")
    assert resp.status_code == 200
    data = resp.json()
    assert "schedulerEnabled" in data
    assert "jitterMinutes" in data
    assert "minKudosDelaySeconds" in data
    assert "maxKudosDelaySeconds" in data
    assert "shuffleOrder" in data


def test_put_settings_ok(app_client: TestClient) -> None:
    payload = {
        "schedulerEnabled": False,
        "intervalMinutes": 120,
        "jitterMinutes": 20.0,
        "minKudosDelaySeconds": 5.0,
        "maxKudosDelaySeconds": 30.0,
        "shuffleOrder": False,
        "dryRun": False,
    }
    resp = app_client.put("/api/settings", json=payload)
    assert resp.status_code == 200

    resp2 = app_client.get("/api/settings")
    data = resp2.json()
    assert data["intervalMinutes"] == 120
    assert data["jitterMinutes"] == 20.0


# ── /api/sport-types ──────────────────────────────────────────────────────────


def test_get_sport_types(app_client: TestClient) -> None:
    resp = app_client.get("/api/sport-types")
    assert resp.status_code == 200
    types = resp.json()
    assert isinstance(types, list)
    assert "Run" in types
    assert "Ride" in types


# ── /api/athlete-labels ───────────────────────────────────────────────────────


def test_get_athlete_labels_empty(app_client: TestClient) -> None:
    resp = app_client.get("/api/athlete-labels")
    assert resp.status_code == 200
    assert isinstance(resp.json(), dict)


# ── /api/status ───────────────────────────────────────────────────────────────


def test_get_status(app_client: TestClient) -> None:
    resp = app_client.get("/api/status")
    assert resp.status_code == 200
    data = resp.json()
    assert "running" in data
    assert "schedulerEnabled" in data
    assert "version" in data
    assert "intervalMinutes" in data


def test_get_status_includes_version(app_client: TestClient) -> None:
    resp = app_client.get("/api/status")
    version = resp.json()["version"]
    assert isinstance(version, str)
    assert len(version) > 0


def test_get_status_with_last_run(app_client: TestClient, data_dir: Path) -> None:
    from datetime import datetime

    from kudosy.app import get_app_state

    last_run = RunResult(
        started_at=datetime.now(UTC),
        finished_at=datetime.now(UTC),
        success=True,
        dry_run=True,
        total=5,
        would_give=3,
        given=0,
    )
    get_app_state()["last_run"] = last_run

    resp = app_client.get("/api/status")
    data = resp.json()
    assert data["lastRun"] is not None
    assert data["lastRun"]["total"] == 5


# ── /api/log ──────────────────────────────────────────────────────────────────


def test_get_log_empty(app_client: TestClient, data_dir: Path) -> None:
    resp = app_client.get("/api/log")
    assert resp.status_code == 200
    assert "Noch keine Logs vorhanden" in resp.text


def test_get_log_with_content(app_client: TestClient, data_dir: Path) -> None:
    log_file = data_dir / "last-run.log"
    log_file.write_text("=== Lauf: 2026-01-01T12:00:00 ===\n", encoding="utf-8")

    resp = app_client.get("/api/log")
    assert resp.status_code == 200
    assert "Lauf" in resp.text


# ── /api/run ──────────────────────────────────────────────────────────────────


def test_post_run_accepted(app_client: TestClient) -> None:
    resp = app_client.post("/api/run", json={})
    assert resp.status_code == 200
    data = resp.json()
    assert data["started"] is True


def test_post_run_dry_run_from_query(app_client: TestClient) -> None:
    resp = app_client.post("/api/run?dryRun=1")
    assert resp.status_code == 200
    assert resp.json()["dryRun"] is True


def test_post_run_409_when_already_running(app_client: TestClient) -> None:
    from kudosy.app import get_app_state

    get_app_state()["scheduler"].is_running = True

    resp = app_client.post("/api/run", json={})
    assert resp.status_code == 409

    # Restore
    get_app_state()["scheduler"].is_running = False


# ── /api/feed ─────────────────────────────────────────────────────────────────


def test_get_feed_no_cookie_returns_400(app_client: TestClient, data_dir: Path) -> None:
    """Returns 400 when no session cookie is configured."""
    from kudosy import store

    store.write_user_config_raw({"stravaSessionCookie": "", "athleteId": ""})
    resp = app_client.get("/api/feed")
    assert resp.status_code == 400


def test_get_feed_returns_activities_with_decision(
    app_client: TestClient, data_dir: Path
) -> None:
    """GET /api/feed returns activities enriched with give_kudos and reason."""
    import json
    from unittest.mock import AsyncMock, patch

    from kudosy import store

    store.write_user_config_raw(
        {"stravaSessionCookie": "valid-cookie", "athleteId": "20000001"}
    )

    # HTML with a single activity via the pageView fallback format (generic shape)
    feed_entry = {
        "id": "55000000001",
        "name": "Test Run",
        "sport_type": "Run",
        "has_kudoed": False,
        "distance": 10000.0,
        "moving_time": 2700,
        "athlete": {"id": "300000001", "name": "Test Runner"},
    }
    feed_html = (
        "<html><script>var pageView = "
        + json.dumps({"entries": [feed_entry]})
        + ";</script></html>"
    )

    mock_instance = AsyncMock()
    mock_instance.fetch_following_feed.return_value = feed_html
    mock_instance.aclose = AsyncMock()

    with patch("kudosy.routes.StravaClient", return_value=mock_instance):
        resp = app_client.get("/api/feed")

    assert resp.status_code == 200
    data = resp.json()
    assert isinstance(data, list)
    assert len(data) == 1

    act = data[0]
    assert act["activity_id"] == "55000000001"
    assert act["activity_name"] == "Test Run"
    assert act["sport_type"] == "Run"
    assert act["has_kudoed"] is False
    assert "give_kudos" in act
    assert isinstance(act["give_kudos"], bool)
    assert "reason" in act
    assert isinstance(act["reason"], str)


def test_get_feed_auth_error_returns_401(
    app_client: TestClient, data_dir: Path
) -> None:
    """AuthError from StravaClient propagates as HTTP 401."""
    from unittest.mock import AsyncMock, patch

    from kudosy import store
    from kudosy.feed import AuthError

    store.write_user_config_raw(
        {"stravaSessionCookie": "expired-cookie", "athleteId": "20000001"}
    )

    mock_instance = AsyncMock()
    mock_instance.fetch_following_feed.side_effect = AuthError("Cookie abgelaufen")
    mock_instance.aclose = AsyncMock()

    with patch("kudosy.routes.StravaClient", return_value=mock_instance):
        resp = app_client.get("/api/feed")

    assert resp.status_code == 401
    assert "Cookie" in resp.json()["detail"]


def test_get_feed_empty_feed_returns_empty_list(
    app_client: TestClient, data_dir: Path
) -> None:
    """Empty feed returns an empty list (not an error)."""
    from unittest.mock import AsyncMock, patch

    from kudosy import store

    store.write_user_config_raw(
        {"stravaSessionCookie": "valid-cookie", "athleteId": "20000001"}
    )

    mock_instance = AsyncMock()
    mock_instance.fetch_following_feed.return_value = "<html><body>no feed data</body></html>"
    mock_instance.aclose = AsyncMock()

    with patch("kudosy.routes.StravaClient", return_value=mock_instance):
        resp = app_client.get("/api/feed")

    assert resp.status_code == 200
    assert resp.json() == []
