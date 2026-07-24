"""Unit tests for the kudoed-activities cache in store.py."""

from __future__ import annotations

import datetime
from pathlib import Path

# ── read/write/mark ───────────────────────────────────────────────────────────


def test_read_kudoed_missing_file_returns_empty(data_dir: Path) -> None:
    """read_kudoed() returns {} when the cache file does not exist."""
    from kudosy.store import read_kudoed

    assert read_kudoed() == {}


def test_read_kudoed_ids_missing_file_returns_empty_set(data_dir: Path) -> None:
    """read_kudoed_ids() returns an empty set when the cache file does not exist."""
    from kudosy.store import read_kudoed_ids

    assert read_kudoed_ids() == set()


def test_write_and_read_kudoed_round_trip(data_dir: Path) -> None:
    """write_kudoed / read_kudoed are a lossless round-trip."""
    from kudosy.store import read_kudoed, write_kudoed

    data = {"111": "2026-01-01T10:00:00+00:00", "222": "2026-02-15T08:30:00+00:00"}
    write_kudoed(data)
    assert read_kudoed() == data


def test_mark_kudoed_adds_entry(data_dir: Path) -> None:
    """mark_kudoed() appends a new entry without overwriting existing ones."""
    from kudosy.store import mark_kudoed, read_kudoed

    mark_kudoed("aaa", "2026-01-01T00:00:00+00:00")
    mark_kudoed("bbb", "2026-01-02T00:00:00+00:00")
    data = read_kudoed()
    assert "aaa" in data
    assert "bbb" in data
    assert len(data) == 2


def test_mark_kudoed_many_adds_all_entries_in_one_write(data_dir: Path) -> None:
    """mark_kudoed_many() persists every ID from a single read+write cycle."""
    from kudosy.store import mark_kudoed_many, read_kudoed

    mark_kudoed_many(["a1", "a2", "a3"], "2026-01-01T00:00:00+00:00")
    data = read_kudoed()
    assert set(data.keys()) == {"a1", "a2", "a3"}
    assert all(v == "2026-01-01T00:00:00+00:00" for v in data.values())


def test_mark_kudoed_many_merges_with_existing_entries(data_dir: Path) -> None:
    """mark_kudoed_many() doesn't clobber IDs cached by a previous run."""
    from kudosy.store import mark_kudoed, mark_kudoed_many, read_kudoed

    mark_kudoed("existing", "2026-01-01T00:00:00+00:00")
    mark_kudoed_many(["new-1", "new-2"], "2026-01-02T00:00:00+00:00")
    data = read_kudoed()
    assert set(data.keys()) == {"existing", "new-1", "new-2"}


def test_mark_kudoed_many_empty_list_is_a_no_op(data_dir: Path) -> None:
    """mark_kudoed_many([]) does not create the cache file / touch existing data."""
    from kudosy.store import mark_kudoed, mark_kudoed_many, read_kudoed

    mark_kudoed("existing", "2026-01-01T00:00:00+00:00")
    mark_kudoed_many([], "2026-01-02T00:00:00+00:00")
    assert read_kudoed() == {"existing": "2026-01-01T00:00:00+00:00"}


def test_read_kudoed_ids_returns_keys(data_dir: Path) -> None:
    """read_kudoed_ids() returns just the keys as a set."""
    from kudosy.store import mark_kudoed, read_kudoed_ids

    mark_kudoed("x1", "2026-01-01T00:00:00+00:00")
    mark_kudoed("x2", "2026-01-02T00:00:00+00:00")
    ids = read_kudoed_ids()
    assert ids == {"x1", "x2"}


# ── prune_kudoed ──────────────────────────────────────────────────────────────


def test_prune_kudoed_removes_old_entries(data_dir: Path) -> None:
    """prune_kudoed() drops entries older than max_age_days."""
    from kudosy.store import prune_kudoed, read_kudoed, write_kudoed

    old = (datetime.datetime.now(datetime.UTC) - datetime.timedelta(days=40)).isoformat()
    recent = datetime.datetime.now(datetime.UTC).isoformat()
    write_kudoed({"old-id": old, "new-id": recent})

    prune_kudoed(max_age_days=30)

    remaining = read_kudoed()
    assert "old-id" not in remaining
    assert "new-id" in remaining


def test_prune_kudoed_keeps_recent_entries(data_dir: Path) -> None:
    """prune_kudoed() does not remove entries within the age limit."""
    from kudosy.store import prune_kudoed, read_kudoed, write_kudoed

    recent = datetime.datetime.now(datetime.UTC).isoformat()
    write_kudoed({"keep-me": recent})

    prune_kudoed(max_age_days=30)

    assert "keep-me" in read_kudoed()


def test_prune_kudoed_handles_invalid_ts(data_dir: Path) -> None:
    """prune_kudoed() removes entries with unparseable timestamps (epoch fallback)."""
    from kudosy.store import prune_kudoed, read_kudoed, write_kudoed

    write_kudoed({"bad-ts": "not-a-date"})
    prune_kudoed(max_age_days=30)
    assert "bad-ts" not in read_kudoed()


# ── bootstrap ──────────────────────────────────────────────────────────────────


def test_bootstrap_creates_kudoed_file(data_dir: Path) -> None:
    """bootstrap() seeds kudoed-activities.json when it does not exist."""
    from kudosy.store import bootstrap, read_kudoed

    bootstrap()
    kudoed_path = data_dir / "kudoed-activities.json"
    assert kudoed_path.exists()
    assert read_kudoed() == {}
