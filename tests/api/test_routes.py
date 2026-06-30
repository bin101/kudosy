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
from kudosy.models import AppSettings, RunResult, UserConfig
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

    app = create_app()

    # Pre-seed app.state so routes that access it work (lifespan won't run)
    app.state.active_sport_types = ALL_SPORT_TYPES

    async def _fake_trigger_now(job: object) -> None:
        # Always called with a coroutine function — just await it.
        await job()  # type: ignore[operator]

    fake_scheduler = MagicMock()
    fake_scheduler.is_running = False
    fake_scheduler.next_run_at = None
    # trigger_now(job_fn) must actually await the job so that last_run is set
    # and the route behaves like the real scheduler.
    fake_scheduler.trigger_now = AsyncMock(side_effect=_fake_trigger_now)

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


# ── GET / — cache-busted index.html ───────────────────────────────────────────


def test_serve_index_injects_version(app_client: TestClient, data_dir: Path) -> None:
    """GET / injects versioned asset URLs and sets Cache-Control: no-store."""
    from kudosy import __version__

    resp = app_client.get("/")
    assert resp.status_code == 200
    body = resp.text
    assert f"app.js?v={__version__}" in body
    assert f"styles.css?v={__version__}" in body
    assert f'"./i18n.js?v={__version__}"' in body
    assert resp.headers["cache-control"] == "no-store"


def test_versioned_asset_gets_immutable_cache_header(
    app_client: TestClient, data_dir: Path
) -> None:
    """Static assets requested with ?v=... get a long immutable cache header."""
    resp = app_client.get("/app.js?v=test")
    assert resp.status_code == 200
    assert resp.headers["cache-control"] == "max-age=31536000, immutable"


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


# ── /api/defaults removed ────────────────────────────────────────────────────


def test_get_defaults_endpoint_removed(app_client: TestClient) -> None:
    """The /api/defaults endpoint no longer exists."""
    resp = app_client.get("/api/defaults")
    assert resp.status_code == 404


def test_put_defaults_endpoint_removed(app_client: TestClient) -> None:
    resp = app_client.put("/api/defaults", json={})
    # StaticFiles mount catches GET → FastAPI advertises path as GET-only → PUT gets 405
    assert resp.status_code in (404, 405)


# ── /api/config catchAll ──────────────────────────────────────────────────────


def test_put_config_with_catchall(app_client: TestClient) -> None:
    """catchAll is persisted as part of UserConfig via /api/config."""
    payload = {
        "stravaSessionCookie": "my-cookie",
        "athleteId": "20000099",
        "catchAll": {"minDistance": 5.0, "minTime": 30.0},
        "kudoRules": {"minDistance": {}, "minTime": {}, "activityNames": []},
    }
    resp = app_client.put("/api/config", json=payload)
    assert resp.status_code == 200

    resp2 = app_client.get("/api/config")
    data = resp2.json()
    assert data["catchAll"]["minDistance"] == 5.0
    assert data["catchAll"]["minTime"] == 30.0


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


# ── /api/sport-categories ─────────────────────────────────────────────────────


def test_get_sport_categories_structure(app_client: TestClient) -> None:
    """GET /api/sport-categories returns a dict with the five category keys."""
    from kudosy.sport_types import CATEGORY_NAMES

    resp = app_client.get("/api/sport-categories")
    assert resp.status_code == 200
    data = resp.json()
    assert isinstance(data, dict)
    assert list(data.keys()) == CATEGORY_NAMES


def test_get_sport_categories_well_known_placements(app_client: TestClient) -> None:
    """Run must be in FootSports, Ride in CycleSports."""
    resp = app_client.get("/api/sport-categories")
    assert resp.status_code == 200
    data = resp.json()
    assert "Run" in data["FootSports"]
    assert "Ride" in data["CycleSports"]
    assert "Swim" in data["WaterSports"]
    assert "AlpineSki" in data["WinterSports"]
    assert "WeightTraining" in data["OtherSports"]


def test_get_sport_categories_config_round_trip(app_client: TestClient) -> None:
    """PUT config with categoryMinDistance → GET config returns the field intact."""
    payload = {
        "stravaSessionCookie": "some-cookie",
        "athleteId": "20000001",
        "kudoRules": {
            "minDistance": {},
            "minTime": {},
            "categoryMinDistance": {"FootSports": 5.0},
            "categoryMinTime": {},
            "activityNames": [],
        },
    }
    put_resp = app_client.put("/api/config", json=payload)
    assert put_resp.status_code == 200

    get_resp = app_client.get("/api/config")
    assert get_resp.status_code == 200
    cfg = get_resp.json()
    assert cfg["kudoRules"]["categoryMinDistance"] == {"FootSports": 5.0}


# ── /api/athlete-labels ───────────────────────────────────────────────────────


def test_get_athlete_labels_empty(app_client: TestClient) -> None:
    resp = app_client.get("/api/athlete-labels")
    assert resp.status_code == 200
    assert isinstance(resp.json(), dict)


# ── /api/athlete-avatars ──────────────────────────────────────────────────────


def test_get_athlete_avatars_empty(app_client: TestClient) -> None:
    resp = app_client.get("/api/athlete-avatars")
    assert resp.status_code == 200
    assert isinstance(resp.json(), dict)


def test_get_athlete_avatars_with_cached_entries(app_client: TestClient, data_dir: Path) -> None:
    from kudosy import store

    store.write_athlete_avatars(
        {"99990001": "https://example.com/1.jpg", "99990002": "https://example.com/2.jpg"}
    )
    resp = app_client.get("/api/athlete-avatars")
    assert resp.status_code == 200
    data = resp.json()
    assert data["99990001"] == "https://example.com/1.jpg"
    assert data["99990002"] == "https://example.com/2.jpg"


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


def test_post_run_routes_through_scheduler(app_client: TestClient) -> None:
    """Manual run must go through scheduler.trigger_now() so is_running is set."""
    from kudosy.app import get_app_state

    state = get_app_state()
    resp = app_client.post("/api/run", json={})
    assert resp.status_code == 200
    # The background task runs synchronously inside TestClient.
    state["scheduler"].trigger_now.assert_awaited_once()


def test_post_run_dry_run_from_body(app_client: TestClient) -> None:
    resp = app_client.post("/api/run", json={"dryRun": True})
    assert resp.status_code == 200
    assert resp.json()["dryRun"] is True


# ── /api/feed ─────────────────────────────────────────────────────────────────


def test_get_feed_no_cookie_returns_400(app_client: TestClient, data_dir: Path) -> None:
    """Returns 400 when no session cookie is configured."""
    from kudosy import store

    store.write_user_config_raw({"stravaSessionCookie": "", "athleteId": ""})
    resp = app_client.get("/api/feed")
    assert resp.status_code == 400


def _make_feed_payload(
    activity_id: str,
    activity_name: str,
    sport_type: str = "Run",
    athlete_id: str = "300000001",
    athlete_name: str = "Test Runner",
    has_kudoed: bool = False,
    elapsed_time: int = 2700,
    distance_km: float = 10.0,
) -> dict[str, object]:
    """Build a minimal Strava JSON feed payload with a single Activity entry."""
    return {
        "entries": [
            {
                "entity": "Activity",
                "activity": {
                    "id": activity_id,
                    "activityName": activity_name,
                    "type": sport_type,
                    "elapsedTime": elapsed_time,
                    "startDate": "2026-06-30T08:00:00Z",
                    "athlete": {
                        "athleteId": athlete_id,
                        "athleteName": athlete_name,
                        "avatarUrl": None,
                    },
                    "kudosAndComments": {
                        "hasKudoed": has_kudoed,
                        "canKudo": not has_kudoed,
                        "kudosCount": 0,
                    },
                    "stats": [
                        {
                            "key": "stat_one",
                            "value": f"{distance_km:.2f}<abbr class='unit' title='kilometers'> km</abbr>",
                            "value_object": None,
                        },
                        {"key": "stat_one_subtitle", "value": "Distance", "value_object": None},
                    ],
                    "timeAndLocation": {"location": None, "displayDate": "Today"},
                    "isCommute": False,
                    "isVirtual": False,
                    "deviceName": None,
                },
            }
        ],
        "pagination": {"hasMore": False},
    }


def test_get_feed_returns_activities_with_decision(app_client: TestClient, data_dir: Path) -> None:
    """GET /api/feed returns activities enriched with give_kudos and reason."""
    from unittest.mock import AsyncMock, patch

    from kudosy import store

    store.write_user_config_raw({"stravaSessionCookie": "valid-cookie", "athleteId": "20000001"})

    mock_instance = AsyncMock()
    mock_instance.fetch_following_feed.return_value = _make_feed_payload(
        "55000000001", "Test Run", sport_type="Run", athlete_id="300000001"
    )
    mock_instance.aclose = AsyncMock()

    with patch("kudosy.routes.StravaClient", return_value=mock_instance):
        resp = app_client.get("/api/feed")

    assert resp.status_code == 200
    data = resp.json()
    assert isinstance(data, dict)
    assert "activities" in data
    assert "fetched_at" in data
    assert len(data["activities"]) == 1

    act = data["activities"][0]
    assert act["activity_id"] == "55000000001"
    assert act["activity_name"] == "Test Run"
    assert act["sport_type"] == "Run"
    assert act["has_kudoed"] is False
    assert "give_kudos" in act
    assert isinstance(act["give_kudos"], bool)
    assert "reason" in act
    assert isinstance(act["reason"], str)


def test_get_feed_auth_error_returns_401(app_client: TestClient, data_dir: Path) -> None:
    """AuthError from StravaClient propagates as HTTP 401."""
    from unittest.mock import AsyncMock, patch

    from kudosy import store
    from kudosy.feed import AuthError

    store.write_user_config_raw({"stravaSessionCookie": "expired-cookie", "athleteId": "20000001"})

    mock_instance = AsyncMock()
    mock_instance.fetch_following_feed.side_effect = AuthError("Cookie abgelaufen")
    mock_instance.aclose = AsyncMock()

    with patch("kudosy.routes.StravaClient", return_value=mock_instance):
        resp = app_client.get("/api/feed")

    assert resp.status_code == 401
    detail = resp.json()["detail"]
    # detail is now a structured dict with 'code' and 'message'
    assert isinstance(detail, dict)
    assert detail.get("code") in ("AUTH_INVALID_COOKIE", "AUTH_FAILED")
    assert "Cookie" in detail.get("message", "")


def test_get_feed_empty_feed_returns_empty_list(app_client: TestClient, data_dir: Path) -> None:
    """Empty feed returns an empty list (not an error)."""
    from unittest.mock import AsyncMock, patch

    from kudosy import store

    store.write_user_config_raw({"stravaSessionCookie": "valid-cookie", "athleteId": "20000001"})

    mock_instance = AsyncMock()
    mock_instance.fetch_following_feed.return_value = {
        "entries": [],
        "pagination": {"hasMore": False},
    }
    mock_instance.aclose = AsyncMock()

    with patch("kudosy.routes.StravaClient", return_value=mock_instance):
        resp = app_client.get("/api/feed")

    assert resp.status_code == 200
    body = resp.json()
    assert body["activities"] == []
    assert body["fetched_at"] is not None


# ── /api/feed — activity cache ─────────────────────────────────────────────────

_CACHED_ACTIVITY = {
    "athlete_name": "Alice Mustermann",
    "athlete_id": "300000001",
    "activity_id": "55000000001",
    "activity_name": "Morning Run",
    "sport_type": "Run",
    "has_kudoed": False,
    "stats": {
        "distance_m": 10000.0,
        "elapsed_time_s": 2700,
        "display": [
            {
                "key": "distance",
                "label": "Distance",
                "raw": "10.00 km",
                "value": 10000.0,
                "unit": "m",
            }
        ],
        "extra": {},
    },
}
_CACHE_TS = "2026-06-21T08:00:00+00:00"


def test_get_feed_serves_from_cache_without_strava(app_client: TestClient, data_dir: Path) -> None:
    """Cache-first: when a populated cache exists, Strava is not called."""
    from unittest.mock import AsyncMock, MagicMock, patch

    from kudosy import store

    store.write_user_config_raw({"stravaSessionCookie": "valid-cookie", "athleteId": "20000001"})
    store.write_activity_cache([dict(_CACHED_ACTIVITY)], _CACHE_TS)

    mock_cls = MagicMock()
    mock_instance = AsyncMock()
    mock_cls.return_value = mock_instance

    with patch("kudosy.routes.StravaClient", mock_cls):
        resp = app_client.get("/api/feed")

    assert resp.status_code == 200
    mock_instance.fetch_following_feed.assert_not_called()

    data = resp.json()
    assert data["fetched_at"] == _CACHE_TS
    acts = data["activities"]
    assert len(acts) == 1
    assert acts[0]["activity_id"] == "55000000001"
    assert "give_kudos" in acts[0]
    assert "reason" in acts[0]


def test_get_feed_refresh_true_fetches_from_strava_and_writes_cache(
    app_client: TestClient, data_dir: Path
) -> None:
    """?refresh=true forces a live Strava fetch and writes the result to the cache."""
    from unittest.mock import AsyncMock, patch

    from kudosy import store

    store.write_user_config_raw({"stravaSessionCookie": "valid-cookie", "athleteId": "20000001"})

    # Pre-populate cache with stale activity
    store.write_activity_cache([dict(_CACHED_ACTIVITY)], _CACHE_TS)

    mock_instance = AsyncMock()
    mock_instance.fetch_following_feed.return_value = _make_feed_payload(
        "55000000002",
        "Evening Ride",
        sport_type="Ride",
        athlete_id="300000002",
        athlete_name="Bob Radler",
        distance_km=30.0,
        elapsed_time=3600,
    )
    mock_instance.aclose = AsyncMock()

    with patch("kudosy.routes.StravaClient", return_value=mock_instance):
        resp = app_client.get("/api/feed?refresh=true")

    assert resp.status_code == 200
    mock_instance.fetch_following_feed.assert_called_once()

    data = resp.json()
    assert data["fetched_at"] is not None
    assert len(data["activities"]) == 1
    assert data["activities"][0]["activity_id"] == "55000000002"

    # Cache must now contain the fresh activity
    cached_acts, fetched_at = store.read_activity_cache()
    assert fetched_at is not None
    assert len(cached_acts) == 1
    assert cached_acts[0]["activity_id"] == "55000000002"


def test_get_feed_first_boot_empty_cache_fetches_live_and_writes(
    app_client: TestClient, data_dir: Path
) -> None:
    """Empty cache on first boot: fetches live and populates the cache."""
    from unittest.mock import AsyncMock, patch

    from kudosy import store

    store.write_user_config_raw({"stravaSessionCookie": "valid-cookie", "athleteId": "20000001"})
    # bootstrap seeded fetched_at=None — cache is empty

    mock_instance = AsyncMock()
    mock_instance.fetch_following_feed.return_value = _make_feed_payload(
        "55000000003",
        "First Run",
        sport_type="Run",
        athlete_id="300000003",
        athlete_name="Carol Läuferin",
        distance_km=5.0,
        elapsed_time=1500,
    )
    mock_instance.aclose = AsyncMock()

    with patch("kudosy.routes.StravaClient", return_value=mock_instance):
        resp = app_client.get("/api/feed")

    assert resp.status_code == 200
    mock_instance.fetch_following_feed.assert_called_once()

    cached_acts, fetched_at = store.read_activity_cache()
    assert fetched_at is not None
    assert len(cached_acts) == 1
    assert cached_acts[0]["activity_id"] == "55000000003"


def test_get_feed_recomputes_decisions_on_config_change(
    app_client: TestClient, data_dir: Path
) -> None:
    """Decisions are recomputed from the current config, not stored in the cache."""
    from unittest.mock import MagicMock, patch

    from kudosy import store

    # Include a Run rule so the activity passes the always-on rule gate
    store.write_user_config_raw({
        "stravaSessionCookie": "valid-cookie",
        "athleteId": "20000001",
        "kudoRules": {"minDistance": {"Run": 1.0}, "minTime": {}, "activityNames": []},
    })
    store.write_activity_cache([dict(_CACHED_ACTIVITY)], _CACHE_TS)

    mock_cls = MagicMock()
    mock_instance = MagicMock()
    mock_cls.return_value = mock_instance

    with patch("kudosy.routes.StravaClient", mock_cls):
        resp1 = app_client.get("/api/feed")
    assert resp1.status_code == 200
    assert resp1.json()["activities"][0]["give_kudos"] is True

    # Now ignore that athlete — decision should flip without any Strava call
    store.write_user_config_raw(
        {
            "stravaSessionCookie": "valid-cookie",
            "athleteId": "20000001",
            "ignoreAthletes": ["300000001"],
            "kudoRules": {"minDistance": {"Run": 1.0}, "minTime": {}, "activityNames": []},
        }
    )

    with patch("kudosy.routes.StravaClient", mock_cls):
        resp2 = app_client.get("/api/feed")
    assert resp2.status_code == 200
    act = resp2.json()["activities"][0]
    assert act["give_kudos"] is False
    assert act["reason"] == "ignore"

    mock_instance.fetch_following_feed.assert_not_called()


def test_post_kudos_flips_has_kudoed_in_cache(app_client: TestClient, data_dir: Path) -> None:
    """POST /api/kudos/{id} marks the activity as kudoed in the activity cache."""
    from unittest.mock import AsyncMock, patch

    from kudosy import store

    store.write_user_config_raw({"stravaSessionCookie": "valid-cookie", "athleteId": "20000001"})
    store.write_activity_cache([dict(_CACHED_ACTIVITY)], _CACHE_TS)

    mock_instance = AsyncMock()
    mock_instance.get_csrf_token.return_value = "csrf-token"
    mock_instance.send_kudos.return_value = True
    mock_instance.aclose = AsyncMock()

    with patch("kudosy.routes.StravaClient", return_value=mock_instance):
        resp = app_client.post("/api/kudos/55000000001")

    assert resp.status_code == 200
    assert resp.json()["ok"] is True

    cached_acts, _ = store.read_activity_cache()
    assert cached_acts[0]["has_kudoed"] is True
