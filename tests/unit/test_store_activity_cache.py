"""Unit tests for the activity-cache functions in store.py."""

from __future__ import annotations

import json
from pathlib import Path

_SAMPLE_ACTIVITY = {
    "athlete_name": "Alice Mustermann",
    "athlete_id": "300000001",
    "activity_id": "55000000001",
    "activity_name": "Morning Run",
    "sport_type": "Run",
    "has_kudoed": False,
    "stats": {"Distance": "10.00 km"},
}

_TS = "2026-06-21T08:00:00+00:00"


# ── read_activity_cache ────────────────────────────────────────────────────────


def test_read_activity_cache_missing_file_returns_empty(data_dir: Path) -> None:
    """Returns ([], None) when the cache file does not exist."""
    from kudosy.store import read_activity_cache

    acts, fetched_at = read_activity_cache()
    assert acts == []
    assert fetched_at is None


def test_read_activity_cache_write_read_roundtrip(data_dir: Path) -> None:
    """write_activity_cache / read_activity_cache are a lossless round-trip."""
    from kudosy.store import read_activity_cache, write_activity_cache

    write_activity_cache([_SAMPLE_ACTIVITY], _TS)
    acts, fetched_at = read_activity_cache()

    assert fetched_at == _TS
    assert len(acts) == 1
    assert acts[0]["activity_id"] == "55000000001"
    assert acts[0]["has_kudoed"] is False


def test_read_activity_cache_corrupt_json_returns_empty(data_dir: Path) -> None:
    """Corrupt JSON → ([], None) without raising."""
    from kudosy.store import read_activity_cache

    (data_dir / "activity-cache.json").write_text("NOT VALID JSON", encoding="utf-8")
    acts, fetched_at = read_activity_cache()
    assert acts == []
    assert fetched_at is None


def test_read_activity_cache_non_dict_returns_empty(data_dir: Path) -> None:
    """Valid JSON that is not a dict (e.g. a bare list) → ([], None)."""
    from kudosy.store import read_activity_cache

    (data_dir / "activity-cache.json").write_text(json.dumps([_SAMPLE_ACTIVITY]), encoding="utf-8")
    acts, fetched_at = read_activity_cache()
    assert acts == []
    assert fetched_at is None


def test_read_activity_cache_missing_activities_key_returns_empty(data_dir: Path) -> None:
    """Dict without 'activities' key → ([], None)."""
    from kudosy.store import read_activity_cache

    (data_dir / "activity-cache.json").write_text(json.dumps({"fetched_at": _TS}), encoding="utf-8")
    acts, fetched_at = read_activity_cache()
    assert acts == []
    assert fetched_at is None


def test_read_activity_cache_non_string_fetched_at_returns_none_ts(data_dir: Path) -> None:
    """Non-string fetched_at (e.g. null) yields fetched_at=None but returns activities."""
    from kudosy.store import read_activity_cache

    (data_dir / "activity-cache.json").write_text(
        json.dumps({"fetched_at": None, "activities": [_SAMPLE_ACTIVITY]}),
        encoding="utf-8",
    )
    acts, fetched_at = read_activity_cache()
    assert fetched_at is None
    assert len(acts) == 1


# ── mark_activity_kudoed_in_cache ─────────────────────────────────────────────


def test_mark_activity_kudoed_in_cache_flips_has_kudoed(data_dir: Path) -> None:
    """Flips has_kudoed=True for the matching activity."""
    from kudosy.store import (
        mark_activity_kudoed_in_cache,
        read_activity_cache,
        write_activity_cache,
    )

    write_activity_cache([dict(_SAMPLE_ACTIVITY)], _TS)
    mark_activity_kudoed_in_cache("55000000001")

    acts, fetched_at = read_activity_cache()
    assert fetched_at == _TS
    assert acts[0]["has_kudoed"] is True


def test_mark_activity_kudoed_in_cache_leaves_other_activities_unchanged(data_dir: Path) -> None:
    """Only the matching activity is mutated; others remain untouched."""
    from kudosy.store import (
        mark_activity_kudoed_in_cache,
        read_activity_cache,
        write_activity_cache,
    )

    other = {**_SAMPLE_ACTIVITY, "activity_id": "55000000002", "athlete_id": "300000002"}
    write_activity_cache([dict(_SAMPLE_ACTIVITY), dict(other)], _TS)
    mark_activity_kudoed_in_cache("55000000001")

    acts, _ = read_activity_cache()
    by_id = {a["activity_id"]: a for a in acts}
    assert by_id["55000000001"]["has_kudoed"] is True
    assert by_id["55000000002"]["has_kudoed"] is False


def test_mark_activity_kudoed_in_cache_preserves_fetched_at(data_dir: Path) -> None:
    """fetched_at is preserved unchanged after marking a kudo."""
    from kudosy.store import (
        mark_activity_kudoed_in_cache,
        read_activity_cache,
        write_activity_cache,
    )

    write_activity_cache([dict(_SAMPLE_ACTIVITY)], _TS)
    mark_activity_kudoed_in_cache("55000000001")

    _, fetched_at = read_activity_cache()
    assert fetched_at == _TS


def test_mark_activity_kudoed_in_cache_noop_when_id_absent(data_dir: Path) -> None:
    """No-op (no write) when the activity_id is not in the cache."""
    from kudosy.store import (
        mark_activity_kudoed_in_cache,
        read_activity_cache,
        write_activity_cache,
    )

    write_activity_cache([dict(_SAMPLE_ACTIVITY)], _TS)
    mtime_before = (data_dir / "activity-cache.json").stat().st_mtime

    mark_activity_kudoed_in_cache("99999999999")  # doesn't exist

    mtime_after = (data_dir / "activity-cache.json").stat().st_mtime
    assert mtime_after == mtime_before  # file was not rewritten

    acts, _ = read_activity_cache()
    assert acts[0]["has_kudoed"] is False


def test_mark_activity_kudoed_in_cache_noop_when_cache_empty(data_dir: Path) -> None:
    """No-op when the cache file is missing — does not raise."""
    from kudosy.store import mark_activity_kudoed_in_cache

    mark_activity_kudoed_in_cache("55000000001")  # must not raise


def test_mark_activity_kudoed_in_cache_noop_when_already_kudoed(data_dir: Path) -> None:
    """No write when the activity is already marked as kudoed."""
    from kudosy.store import (
        mark_activity_kudoed_in_cache,
        write_activity_cache,
    )

    already_kudoed = {**_SAMPLE_ACTIVITY, "has_kudoed": True}
    write_activity_cache([already_kudoed], _TS)
    mtime_before = (data_dir / "activity-cache.json").stat().st_mtime

    mark_activity_kudoed_in_cache("55000000001")

    mtime_after = (data_dir / "activity-cache.json").stat().st_mtime
    assert mtime_after == mtime_before  # file was not rewritten


# ── bootstrap ─────────────────────────────────────────────────────────────────


def test_bootstrap_creates_activity_cache_file(data_dir: Path) -> None:
    """bootstrap() seeds activity-cache.json with an empty snapshot when missing."""
    from kudosy.store import bootstrap, read_activity_cache

    bootstrap()
    cache_path = data_dir / "activity-cache.json"
    assert cache_path.exists()

    acts, fetched_at = read_activity_cache()
    assert acts == []
    assert fetched_at is None


def test_bootstrap_does_not_overwrite_existing_cache(data_dir: Path) -> None:
    """bootstrap() is idempotent — it never overwrites an existing cache file."""
    from kudosy.store import bootstrap, read_activity_cache, write_activity_cache

    write_activity_cache([dict(_SAMPLE_ACTIVITY)], _TS)
    bootstrap()

    acts, fetched_at = read_activity_cache()
    assert fetched_at == _TS
    assert len(acts) == 1
