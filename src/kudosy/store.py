"""Persistent data store — all /data file I/O in one place.

Uses atomic writes (temp file + rename) to avoid partial writes.
KUDOSY_DATA_DIR env var overrides the default /data path, so tests
can use a temp directory without touching real config.
"""

from __future__ import annotations

import contextlib
import json
import logging
import os
import tempfile
from pathlib import Path
from typing import Any

import yaml

from kudosy.models import AppSettings, Defaults, UserConfig
from kudosy.settings import get_settings

log = logging.getLogger(__name__)


def _data_dir() -> Path:
    return Path(get_settings().data_dir)


def _path(name: str) -> Path:
    return _data_dir() / name


# ── Low-level YAML / JSON I/O ─────────────────────────────────────────────────


def _read_yaml(path: Path) -> dict[str, Any] | None:
    try:
        raw = path.read_text(encoding="utf-8")
        return yaml.safe_load(raw) or {}
    except FileNotFoundError:
        return None
    except Exception:
        log.warning("Failed to read YAML %s", path, exc_info=True)
        return None


def _write_yaml_atomic(path: Path, data: Any) -> None:
    """Write YAML atomically via a temp file + rename."""
    path.parent.mkdir(parents=True, exist_ok=True)
    content = yaml.dump(data, allow_unicode=True, default_flow_style=False, sort_keys=False)
    fd, tmp = tempfile.mkstemp(dir=path.parent, suffix=".tmp")
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            f.write(content)
        os.replace(tmp, path)
    except Exception:
        with contextlib.suppress(OSError):
            os.unlink(tmp)
        raise


def _read_json(path: Path) -> dict[str, Any] | None:
    try:
        result: dict[str, Any] = json.loads(path.read_text(encoding="utf-8"))
        return result
    except FileNotFoundError:
        return None
    except Exception:
        log.warning("Failed to read JSON %s", path, exc_info=True)
        return None


def _write_json_atomic(path: Path, data: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    content = json.dumps(data, indent=2, ensure_ascii=False)
    fd, tmp = tempfile.mkstemp(dir=path.parent, suffix=".tmp")
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            f.write(content)
        os.replace(tmp, path)
    except Exception:
        with contextlib.suppress(OSError):
            os.unlink(tmp)
        raise


# ── Domain-level read/write ───────────────────────────────────────────────────

_CONFIG_FILE = "config.yaml"
_DEFAULTS_FILE = "defaults.yaml"
_SETTINGS_FILE = "settings.json"
_LABELS_FILE = "athlete-labels.json"
_LOG_FILE = "last-run.log"
_LEGACY_CONFIG = Path("/tmp/legacy-config.yaml")

_DEFAULT_SETTINGS = AppSettings()
_DEFAULT_DEFAULTS = Defaults()


def read_user_config() -> UserConfig | None:
    raw = _read_yaml(_path(_CONFIG_FILE))
    if raw is None:
        return None
    try:
        return UserConfig.model_validate(raw)
    except Exception:
        log.warning("Invalid config.yaml; returning None", exc_info=True)
        return None


def write_user_config(cfg: UserConfig) -> None:
    _write_yaml_atomic(_path(_CONFIG_FILE), cfg.model_dump())


def write_user_config_raw(data: dict[str, Any]) -> None:
    """Write user config from a raw dict (used by the API endpoint)."""
    _write_yaml_atomic(_path(_CONFIG_FILE), data)


def read_defaults() -> Defaults:
    raw = _read_yaml(_path(_DEFAULTS_FILE))
    if raw is None:
        return _DEFAULT_DEFAULTS
    try:
        return Defaults.model_validate(raw)
    except Exception:
        log.warning("Invalid defaults.yaml; using defaults", exc_info=True)
        return _DEFAULT_DEFAULTS


def write_defaults(d: Defaults) -> None:
    _write_yaml_atomic(_path(_DEFAULTS_FILE), d.model_dump())


def write_defaults_raw(data: dict[str, Any]) -> None:
    _write_yaml_atomic(_path(_DEFAULTS_FILE), data)


def read_settings() -> AppSettings:
    raw = _read_json(_path(_SETTINGS_FILE))
    if raw is None:
        return _DEFAULT_SETTINGS
    try:
        return AppSettings.model_validate(raw)
    except Exception:
        log.warning("Invalid settings.json; using defaults", exc_info=True)
        return _DEFAULT_SETTINGS


def write_settings(s: AppSettings) -> None:
    _write_json_atomic(_path(_SETTINGS_FILE), s.model_dump())


def read_athlete_labels() -> dict[str, str]:
    raw = _read_json(_path(_LABELS_FILE))
    return raw if isinstance(raw, dict) else {}


def write_athlete_labels(labels: dict[str, str]) -> None:
    _write_json_atomic(_path(_LABELS_FILE), labels)


def cache_athlete_label(athlete_id: str, name: str) -> None:
    labels = read_athlete_labels()
    labels[athlete_id] = name
    write_athlete_labels(labels)


def log_path() -> Path:
    return _path(_LOG_FILE)


def read_log() -> str:
    try:
        return log_path().read_text(encoding="utf-8")
    except FileNotFoundError:
        return "Noch keine Logs vorhanden."


# ── Bootstrap ─────────────────────────────────────────────────────────────────


def bootstrap() -> None:
    """Create /data, seed missing defaults/settings, migrate legacy config."""
    data_dir = _data_dir()
    data_dir.mkdir(parents=True, exist_ok=True)

    # Migrate legacy config if not yet done
    config_path = _path(_CONFIG_FILE)
    if not config_path.exists() and _LEGACY_CONFIG.exists():
        log.info("[bootstrap] Migrating legacy config → %s", config_path)
        raw = _read_yaml(_LEGACY_CONFIG)
        if raw:
            _write_yaml_atomic(config_path, raw)

    # Seed defaults file
    defaults_path = _path(_DEFAULTS_FILE)
    if not defaults_path.exists():
        log.info("[bootstrap] Creating %s", defaults_path)
        _write_yaml_atomic(defaults_path, _DEFAULT_DEFAULTS.model_dump())

    # Seed settings file (also adds new fields to existing settings.json)
    settings_path = _path(_SETTINGS_FILE)
    if settings_path.exists():
        existing = _read_json(settings_path) or {}
        fresh = _DEFAULT_SETTINGS.model_dump()
        merged = {**fresh, **existing}  # new fields get defaults, existing preserved
        _write_json_atomic(settings_path, merged)
    else:
        log.info("[bootstrap] Creating %s", settings_path)
        _write_json_atomic(settings_path, _DEFAULT_SETTINGS.model_dump())
