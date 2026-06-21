"""Integration tests for store.py — all /data file I/O.

Uses the `data_dir` fixture from conftest.py to redirect KUDOSY_DATA_DIR
to a tmp path, so tests never touch real /data.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from kudosy.models import AppSettings, KudoRules, UserConfig
from kudosy.store import (
    bootstrap,
    cache_athlete_avatar,
    cache_athlete_label,
    read_athlete_avatars,
    read_athlete_labels,
    read_log,
    read_settings,
    read_user_config,
    write_athlete_avatars,
    write_athlete_labels,
    write_settings,
    write_user_config,
    write_user_config_raw,
)

# ── bootstrap ──────────────────────────────────────────────────────────────────


def test_bootstrap_creates_data_dir(data_dir: Path) -> None:
    bootstrap()
    assert data_dir.is_dir()


def test_bootstrap_does_not_create_defaults_yaml(data_dir: Path) -> None:
    """bootstrap() no longer seeds defaults.yaml — that file is legacy."""
    bootstrap()
    assert not (data_dir / "defaults.yaml").exists()


def test_bootstrap_seeds_settings(data_dir: Path) -> None:
    bootstrap()
    assert (data_dir / "settings.json").exists()


def test_bootstrap_idempotent(data_dir: Path) -> None:
    """Calling bootstrap twice does not corrupt existing files."""
    bootstrap()
    write_settings(AppSettings(intervalMinutes=120))
    bootstrap()
    s = read_settings()
    assert s.intervalMinutes == 120  # existing value preserved


def test_bootstrap_adds_missing_settings_fields(
    data_dir: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """bootstrap() patches new fields into existing settings.json without overwriting known fields."""
    import json

    settings_path = data_dir / "settings.json"
    # Write an old-style settings without jitter fields
    settings_path.write_text(
        json.dumps({"schedulerEnabled": False, "intervalMinutes": 30, "dryRun": True}),
        encoding="utf-8",
    )
    bootstrap()
    s = read_settings()
    assert s.schedulerEnabled is False  # preserved
    assert s.intervalMinutes == 30  # preserved
    assert s.dryRun is True  # preserved
    assert isinstance(s.jitterMinutes, float)  # new field seeded


# ── UserConfig ─────────────────────────────────────────────────────────────────


def test_read_user_config_missing(data_dir: Path) -> None:
    assert read_user_config() is None


def test_write_read_user_config(data_dir: Path) -> None:
    cfg = UserConfig(
        stravaSessionCookie="test-cookie-value",
        athleteId="99900001",
        ignoreAthletes=["99900002", "99900003"],
        kudoRules=KudoRules(
            minDistance={"Run": 5.0},
            minTime={"Run": 20.0},
            activityNames=["Morning.*"],
        ),
    )
    write_user_config(cfg)
    loaded = read_user_config()
    assert loaded is not None
    assert loaded.stravaSessionCookie == "test-cookie-value"
    assert loaded.athleteId == "99900001"
    assert loaded.ignoreAthletes == ["99900002", "99900003"]
    assert loaded.kudoRules.minDistance == {"Run": 5.0}
    assert loaded.kudoRules.activityNames == ["Morning.*"]


def test_write_user_config_raw(data_dir: Path) -> None:
    raw = {"stravaSessionCookie": "raw-cookie", "athleteId": "12345"}
    write_user_config_raw(raw)
    loaded = read_user_config()
    assert loaded is not None
    assert loaded.stravaSessionCookie == "raw-cookie"


def test_write_is_atomic(data_dir: Path) -> None:
    """No .tmp files should remain after a write."""
    write_user_config(UserConfig(stravaSessionCookie="s", athleteId="1"))
    tmp_files = list(data_dir.glob("*.tmp"))
    assert tmp_files == []


# ── Migration: legacy defaults.yaml → config.yaml ─────────────────────────────


def test_migration_merges_catchall_into_config(data_dir: Path) -> None:
    """bootstrap() migrates catchAll from defaults.yaml into config.yaml."""
    import yaml

    # Write a legacy defaults.yaml with catchAll
    (data_dir / "defaults.yaml").write_text(
        yaml.dump({"catchAll": {"minDistance": 8.0, "minTime": 20.0}, "kudoRules": {}}),
        encoding="utf-8",
    )
    # Write a config.yaml without catchAll
    (data_dir / "config.yaml").write_text(
        yaml.dump({"stravaSessionCookie": "c", "athleteId": "1", "kudoRules": {}}),
        encoding="utf-8",
    )

    bootstrap()

    # defaults.yaml should be renamed, not left as-is
    assert not (data_dir / "defaults.yaml").exists()
    assert (data_dir / "defaults.yaml.migrated").exists()

    # config.yaml must contain the merged catchAll
    cfg = read_user_config()
    assert cfg is not None
    assert cfg.catchAll.minDistance == 8.0
    assert cfg.catchAll.minTime == 20.0


def test_migration_merges_per_sport_rules(data_dir: Path) -> None:
    """Per-sport rules from defaults are merged into config; config values win on conflict."""
    import yaml

    (data_dir / "defaults.yaml").write_text(
        yaml.dump(
            {
                "catchAll": {"minDistance": 0.0, "minTime": 0.0},
                "kudoRules": {
                    "minDistance": {"Run": 3.0, "Ride": 10.0},
                    "minTime": {},
                    "activityNames": ["^Race"],
                },
            }
        ),
        encoding="utf-8",
    )
    (data_dir / "config.yaml").write_text(
        yaml.dump(
            {
                "stravaSessionCookie": "c",
                "athleteId": "1",
                "kudoRules": {
                    "minDistance": {"Run": 5.0},  # user override → should win
                    "minTime": {},
                    "activityNames": ["^Morning"],
                },
            }
        ),
        encoding="utf-8",
    )

    bootstrap()

    cfg = read_user_config()
    assert cfg is not None
    # User value (5.0) wins over defaults value (3.0)
    assert cfg.kudoRules.minDistance["Run"] == 5.0
    # Defaults-only entry is merged in
    assert cfg.kudoRules.minDistance["Ride"] == 10.0
    # activityNames: defaults first, then user additions (dedup)
    assert cfg.kudoRules.activityNames[0] == "^Race"
    assert "^Morning" in cfg.kudoRules.activityNames


def test_migration_idempotent_no_defaults_yaml(data_dir: Path) -> None:
    """bootstrap() is safe when defaults.yaml does not exist (no migration needed)."""
    bootstrap()
    # No crash, no defaults.yaml created
    assert not (data_dir / "defaults.yaml").exists()


# ── AppSettings ───────────────────────────────────────────────────────────────


def test_read_settings_returns_defaults_when_missing(data_dir: Path) -> None:
    s = read_settings()
    assert s.schedulerEnabled is True
    assert s.intervalMinutes == 60
    assert s.jitterMinutes == 15.0


def test_write_read_settings(data_dir: Path) -> None:
    s = AppSettings(
        schedulerEnabled=False,
        intervalMinutes=90,
        jitterMinutes=10.0,
        minKudosDelaySeconds=5.0,
        maxKudosDelaySeconds=30.0,
        shuffleOrder=False,
        dryRun=True,
    )
    write_settings(s)
    loaded = read_settings()
    assert loaded.schedulerEnabled is False
    assert loaded.intervalMinutes == 90
    assert loaded.jitterMinutes == 10.0
    assert loaded.minKudosDelaySeconds == 5.0
    assert loaded.shuffleOrder is False
    assert loaded.dryRun is True


# ── Athlete labels ─────────────────────────────────────────────────────────────


def test_read_athlete_labels_empty(data_dir: Path) -> None:
    assert read_athlete_labels() == {}


def test_write_read_athlete_labels(data_dir: Path) -> None:
    labels = {"99900001": "Alex Runner", "99900002": "Sam Cyclist"}
    write_athlete_labels(labels)
    loaded = read_athlete_labels()
    assert loaded == labels


def test_cache_athlete_label_merges(data_dir: Path) -> None:
    write_athlete_labels({"99900001": "Alex Runner"})
    cache_athlete_label("99900002", "Sam Cyclist")
    loaded = read_athlete_labels()
    assert loaded["99900001"] == "Alex Runner"
    assert loaded["99900002"] == "Sam Cyclist"


# ── Athlete avatars ────────────────────────────────────────────────────────────


def test_read_athlete_avatars_empty(data_dir: Path) -> None:
    assert read_athlete_avatars() == {}


def test_write_read_athlete_avatars(data_dir: Path) -> None:
    avatars = {
        "99900001": "https://example.com/a/1.jpg",
        "99900002": "https://example.com/a/2.jpg",
    }
    write_athlete_avatars(avatars)
    assert read_athlete_avatars() == avatars


def test_cache_athlete_avatar_merges(data_dir: Path) -> None:
    write_athlete_avatars({"99900001": "https://example.com/a/1.jpg"})
    cache_athlete_avatar("99900002", "https://example.com/a/2.jpg")
    loaded = read_athlete_avatars()
    assert loaded["99900001"] == "https://example.com/a/1.jpg"
    assert loaded["99900002"] == "https://example.com/a/2.jpg"


# ── Log ───────────────────────────────────────────────────────────────────────


def test_read_log_missing(data_dir: Path) -> None:
    text = read_log()
    assert "Noch keine Logs vorhanden" in text


def test_read_log_existing(data_dir: Path) -> None:
    log_file = data_dir / "last-run.log"
    log_file.write_text("=== Lauf: 2026-01-01 ===\n", encoding="utf-8")
    text = read_log()
    assert "Lauf" in text


def test_bootstrap_seeds_config_yaml(data_dir: Path) -> None:
    """bootstrap() creates config.yaml with default values if missing."""
    bootstrap()
    assert (data_dir / "config.yaml").exists()
    cfg = read_user_config()
    assert cfg is not None
    assert cfg.stravaSessionCookie == ""
    assert cfg.athleteId == ""


def test_bootstrap_seeds_athlete_labels(data_dir: Path) -> None:
    """bootstrap() creates athlete-labels.json as empty dict if missing."""
    bootstrap()
    assert (data_dir / "athlete-labels.json").exists()
    assert read_athlete_labels() == {}


def test_bootstrap_does_not_overwrite_existing_config(data_dir: Path) -> None:
    """bootstrap() does not overwrite an existing config.yaml."""
    write_user_config(UserConfig(stravaSessionCookie="my-existing-cookie", athleteId="12345"))
    bootstrap()
    cfg = read_user_config()
    assert cfg is not None
    assert cfg.stravaSessionCookie == "my-existing-cookie"


def test_bootstrap_does_not_overwrite_existing_labels(data_dir: Path) -> None:
    """bootstrap() does not overwrite existing athlete-labels.json."""
    from kudosy.store import write_athlete_labels

    write_athlete_labels({"123": "Existing Athlete"})
    bootstrap()
    labels = read_athlete_labels()
    assert labels == {"123": "Existing Athlete"}


def test_bootstrap_seeds_athlete_avatars(data_dir: Path) -> None:
    """bootstrap() creates athlete-avatars.json as empty dict if missing."""
    bootstrap()
    assert (data_dir / "athlete-avatars.json").exists()
    assert read_athlete_avatars() == {}


def test_bootstrap_does_not_overwrite_existing_avatars(data_dir: Path) -> None:
    """bootstrap() does not overwrite existing athlete-avatars.json."""
    write_athlete_avatars({"123": "https://example.com/a/keep.jpg"})
    bootstrap()
    assert read_athlete_avatars() == {"123": "https://example.com/a/keep.jpg"}


# ── Error path coverage ────────────────────────────────────────────────────────


def test_read_athlete_labels_corrupt_json(data_dir: Path) -> None:
    """Corrupt JSON in athlete-labels.json is handled gracefully (returns {})."""
    (data_dir / "athlete-labels.json").write_text("{not valid json!!!", encoding="utf-8")
    # _read_json catches the exception; read_athlete_labels must return {}
    result = read_athlete_labels()
    assert result == {}


def test_read_athlete_avatars_corrupt_json(data_dir: Path) -> None:
    """Corrupt JSON in athlete-avatars.json is handled gracefully (returns {})."""
    (data_dir / "athlete-avatars.json").write_text("{not valid json!!!", encoding="utf-8")
    result = read_athlete_avatars()
    assert result == {}
