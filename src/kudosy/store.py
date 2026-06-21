"""Persistent data store — all /data file I/O in one place.

Uses atomic writes (temp file + rename) to avoid partial writes.
KUDOSY_DATA_DIR env var overrides the default /data path, so tests
can use a temp directory without touching real config.
"""

from __future__ import annotations

import contextlib
import datetime as _dt
import json
import logging
import os
import tempfile
from pathlib import Path
from typing import Any

import yaml

from kudosy.models import AppSettings, UserConfig
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
_DEFAULTS_FILE = "defaults.yaml"  # legacy — migrated away from on first boot
_SETTINGS_FILE = "settings.json"
_LABELS_FILE = "athlete-labels.json"
_AVATARS_FILE = "athlete-avatars.json"
_KUDOED_FILE = "kudoed-activities.json"
_LOG_FILE = "last-run.log"

_DEFAULT_SETTINGS = AppSettings()
_DEFAULT_CONFIG = UserConfig()


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


def read_athlete_avatars() -> dict[str, str]:
    raw = _read_json(_path(_AVATARS_FILE))
    return raw if isinstance(raw, dict) else {}


def write_athlete_avatars(avatars: dict[str, str]) -> None:
    _write_json_atomic(_path(_AVATARS_FILE), avatars)


def cache_athlete_avatar(athlete_id: str, avatar_url: str) -> None:
    avatars = read_athlete_avatars()
    avatars[athlete_id] = avatar_url
    write_athlete_avatars(avatars)


def read_kudoed() -> dict[str, str]:
    """Return mapping of activity_id → ISO-timestamp for all cached kudoed activities."""
    raw = _read_json(_path(_KUDOED_FILE))
    return raw if isinstance(raw, dict) else {}


def read_kudoed_ids() -> set[str]:
    """Return the set of activity_ids that were already kudoed (fast lookup)."""
    return set(read_kudoed().keys())


def write_kudoed(data: dict[str, str]) -> None:
    """Persist the full kudoed-activities mapping atomically."""
    _write_json_atomic(_path(_KUDOED_FILE), data)


def mark_kudoed(activity_id: str, ts_iso: str) -> None:
    """Add a single kudoed activity_id to the persistent cache."""
    data = read_kudoed()
    data[activity_id] = ts_iso
    write_kudoed(data)


def prune_kudoed(max_age_days: int = 30) -> None:
    """Remove cached entries older than *max_age_days* days.

    Since Activity has no timestamp field, we track when we cached the kudo.
    The Strava feed only holds ~60 recent items, so entries older than
    max_age_days are guaranteed to be out of the feed and can be dropped.
    """
    data = read_kudoed()
    cutoff = _dt.datetime.now(_dt.UTC) - _dt.timedelta(days=max_age_days)
    pruned = {aid: ts for aid, ts in data.items() if _parse_ts(ts) > cutoff}
    if len(pruned) < len(data):
        log.debug("prune_kudoed: removed %d old entries", len(data) - len(pruned))
        write_kudoed(pruned)


def _parse_ts(ts: str) -> _dt.datetime:
    """Parse an ISO timestamp string; return epoch on failure (triggers pruning)."""
    try:
        return _dt.datetime.fromisoformat(ts)
    except (ValueError, TypeError):
        return _dt.datetime(1970, 1, 1, tzinfo=_dt.UTC)


def log_path() -> Path:
    return _path(_LOG_FILE)


def read_log() -> str:
    try:
        return log_path().read_text(encoding="utf-8")
    except FileNotFoundError:
        return "Noch keine Logs vorhanden."


# ── Bootstrap / Migration ──────────────────────────────────────────────────────


def _migrate_defaults(defaults_path: Path) -> None:
    """Merge legacy defaults.yaml into config.yaml, then rename it .migrated.

    Called once during bootstrap when defaults.yaml still exists.  After the
    migration, defaults.yaml is renamed to defaults.yaml.migrated so this
    function is never triggered again (idempotent).

    Merge strategy (config wins on conflicts):
      - catchAll:         taken from defaults (config has no catchAll yet)
      - kudoRules per sport: defaults first, then config overlays (config wins)
      - activityNames:    dedup-union (defaults first, then config additions)
    """
    log.info("[bootstrap] Migrating legacy defaults.yaml into config.yaml")
    raw_defaults = _read_yaml(defaults_path) or {}
    raw_config = _read_yaml(_path(_CONFIG_FILE)) or {}

    # --- catchAll: copy from defaults (UserConfig gains this field) ---
    if "catchAll" in raw_defaults and "catchAll" not in raw_config:
        raw_config["catchAll"] = raw_defaults["catchAll"]

    # --- kudoRules: merge (defaults base, config overlay) ---
    def_rules: dict[str, Any] = raw_defaults.get("kudoRules") or {}
    cfg_rules: dict[str, Any] = raw_config.get("kudoRules") or {}

    # minDistance
    merged_dist: dict[str, float] = dict(def_rules.get("minDistance") or {})
    merged_dist.update(cfg_rules.get("minDistance") or {})

    # minTime
    merged_time: dict[str, float] = dict(def_rules.get("minTime") or {})
    merged_time.update(cfg_rules.get("minTime") or {})

    # activityNames: dedup-union (defaults first)
    def_names: list[str] = def_rules.get("activityNames") or []
    cfg_names: list[str] = cfg_rules.get("activityNames") or []
    seen: set[str] = set()
    merged_names: list[str] = []
    for n in [*def_names, *cfg_names]:
        if n not in seen:
            seen.add(n)
            merged_names.append(n)

    raw_config["kudoRules"] = {
        "minDistance": merged_dist,
        "minTime": merged_time,
        "activityNames": merged_names,
    }

    # Validate the merged result before writing (raises on invalid data)
    UserConfig.model_validate(raw_config)
    _write_yaml_atomic(_path(_CONFIG_FILE), raw_config)

    # Rename defaults.yaml → defaults.yaml.migrated (non-destructive)
    migrated_path = defaults_path.with_suffix(".yaml.migrated")
    defaults_path.rename(migrated_path)
    log.info("[bootstrap] Migration complete — %s → %s", defaults_path.name, migrated_path.name)


def bootstrap() -> None:
    """Create /data and seed all missing files with safe defaults.

    Idempotent: existing files are never overwritten (except settings.json,
    which is merged to add any new fields while preserving existing values).
    Safe to call on every startup.
    """
    data_dir = _data_dir()
    data_dir.mkdir(parents=True, exist_ok=True)

    # Migrate legacy defaults.yaml into config.yaml (idempotent: only while defaults.yaml exists)
    defaults_path = _path(_DEFAULTS_FILE)
    if defaults_path.exists():
        _migrate_defaults(defaults_path)

    # Seed config.yaml if missing (user fills in cookie via the UI)
    config_path = _path(_CONFIG_FILE)
    if not config_path.exists():
        log.info("[bootstrap] Creating %s", config_path)
        _write_yaml_atomic(config_path, _DEFAULT_CONFIG.model_dump())

    # Seed settings.json (also merges new fields into existing settings.json)
    settings_path = _path(_SETTINGS_FILE)
    if settings_path.exists():
        existing = _read_json(settings_path) or {}
        fresh = _DEFAULT_SETTINGS.model_dump()
        merged = {**fresh, **existing}  # new fields get defaults, existing preserved
        _write_json_atomic(settings_path, merged)
    else:
        log.info("[bootstrap] Creating %s", settings_path)
        _write_json_atomic(settings_path, _DEFAULT_SETTINGS.model_dump())

    # Seed athlete-labels.json if missing
    labels_path = _path(_LABELS_FILE)
    if not labels_path.exists():
        log.info("[bootstrap] Creating %s", labels_path)
        _write_json_atomic(labels_path, {})

    # Seed athlete-avatars.json if missing
    avatars_path = _path(_AVATARS_FILE)
    if not avatars_path.exists():
        log.info("[bootstrap] Creating %s", avatars_path)
        _write_json_atomic(avatars_path, {})

    # Seed kudoed-activities.json if missing
    kudoed_path = _path(_KUDOED_FILE)
    if not kudoed_path.exists():
        log.info("[bootstrap] Creating %s", kudoed_path)
        _write_json_atomic(kudoed_path, {})
