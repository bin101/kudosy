"""API tests for config backup/restore (GET /api/export, POST /api/import)."""

from __future__ import annotations

from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from kudosy.app import create_app, get_app_state
from kudosy.models import AppSettings, UserConfig
from kudosy.sport_types import ALL_SPORT_TYPES


@pytest.fixture()
def client(data_dir: Path) -> TestClient:
    from unittest.mock import AsyncMock, MagicMock

    from kudosy import store

    store.bootstrap()
    store.write_user_config(
        UserConfig(
            stravaSessionCookie="my-real-cookie",
            athleteId="42",
        )
    )
    store.write_settings(AppSettings(dryRun=True, intervalMinutes=30))

    app = create_app()
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

    with TestClient(app, raise_server_exceptions=True) as c:
        get_app_state().update(
            {
                "scheduler": fake_scheduler,
                "job_fn": AsyncMock(),
                "run_job_fn": AsyncMock(return_value=None),
                "last_run": None,
            }
        )
        yield c


# ── GET /api/export ───────────────────────────────────────────────────────────


def test_export_returns_200(client: TestClient) -> None:
    resp = client.get("/api/export")
    assert resp.status_code == 200


def test_export_content_disposition_attachment(client: TestClient) -> None:
    resp = client.get("/api/export")
    cd = resp.headers.get("content-disposition", "")
    assert "attachment" in cd


def test_export_content_type_json(client: TestClient) -> None:
    resp = client.get("/api/export")
    assert "application/json" in resp.headers.get("content-type", "")


def test_export_excludes_cookie(client: TestClient) -> None:
    resp = client.get("/api/export")
    data = resp.json()
    config = data.get("config", {})
    assert "stravaSessionCookie" not in config or config.get("stravaSessionCookie") == ""


def test_export_includes_config_section(client: TestClient) -> None:
    resp = client.get("/api/export")
    data = resp.json()
    assert "config" in data
    assert "athleteId" in data["config"]


def test_export_includes_settings_section(client: TestClient) -> None:
    resp = client.get("/api/export")
    data = resp.json()
    assert "settings" in data
    assert data["settings"]["intervalMinutes"] == 30


def test_export_includes_athlete_labels(client: TestClient) -> None:
    resp = client.get("/api/export")
    data = resp.json()
    assert "athleteLabels" in data


def test_export_filename_contains_kudosy(client: TestClient) -> None:
    resp = client.get("/api/export")
    cd = resp.headers.get("content-disposition", "")
    assert "kudosy" in cd


# ── POST /api/import ──────────────────────────────────────────────────────────


def _minimal_import(data_dir: Path) -> dict:
    """A minimal valid import payload built from the data dir's current state."""
    from kudosy import store

    cfg = store.read_user_config()
    settings = store.read_settings()
    cfg_dict = cfg.model_dump() if cfg else {}
    cfg_dict.pop("stravaSessionCookie", None)
    return {
        "config": cfg_dict,
        "settings": settings.model_dump(),
    }


def test_import_valid_payload_returns_ok(client: TestClient, data_dir: Path) -> None:
    payload = _minimal_import(data_dir)
    resp = client.post("/api/import", json=payload)
    assert resp.status_code == 200
    assert resp.json()["ok"] is True


def test_import_preserves_existing_cookie_when_omitted(client: TestClient, data_dir: Path) -> None:
    from kudosy import store

    payload = _minimal_import(data_dir)
    # Cookie not in payload → existing cookie must be preserved
    client.post("/api/import", json=payload)
    cfg = store.read_user_config()
    assert cfg is not None
    assert cfg.stravaSessionCookie == "my-real-cookie"


def test_import_updates_cookie_when_provided(client: TestClient, data_dir: Path) -> None:
    from kudosy import store

    payload = _minimal_import(data_dir)
    payload["config"]["stravaSessionCookie"] = "new-cookie-value"
    client.post("/api/import", json=payload)
    cfg = store.read_user_config()
    assert cfg is not None
    assert cfg.stravaSessionCookie == "new-cookie-value"


def test_import_does_not_overwrite_cookie_with_empty(client: TestClient, data_dir: Path) -> None:
    from kudosy import store

    payload = _minimal_import(data_dir)
    payload["config"]["stravaSessionCookie"] = ""
    client.post("/api/import", json=payload)
    cfg = store.read_user_config()
    assert cfg is not None
    assert cfg.stravaSessionCookie == "my-real-cookie"


def test_import_updates_settings(client: TestClient, data_dir: Path) -> None:
    from kudosy import store

    payload = _minimal_import(data_dir)
    payload["settings"]["intervalMinutes"] = 90
    client.post("/api/import", json=payload)
    settings = store.read_settings()
    assert settings.intervalMinutes == 90


def test_import_missing_config_returns_422(client: TestClient) -> None:
    resp = client.post("/api/import", json={"settings": {}})
    assert resp.status_code == 422


def test_import_missing_settings_returns_422(client: TestClient) -> None:
    resp = client.post("/api/import", json={"config": {}})
    assert resp.status_code == 422


def test_import_invalid_settings_interval_clamps(client: TestClient, data_dir: Path) -> None:
    from kudosy import store

    payload = _minimal_import(data_dir)
    payload["settings"]["intervalMinutes"] = 1  # below minimum (5)
    resp = client.post("/api/import", json=payload)
    assert resp.status_code == 200
    settings = store.read_settings()
    assert settings.intervalMinutes >= 5
