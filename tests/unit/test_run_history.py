"""Unit tests for run-history store functions (append_run_history / read_run_history)."""

from __future__ import annotations

from pathlib import Path
from typing import Any

# ── helpers ───────────────────────────────────────────────────────────────────


def _make_entry(**overrides: Any) -> dict[str, Any]:
    """Return a minimal but valid RunHistoryEntry dict."""
    base: dict[str, Any] = {
        "started_at": "2026-01-01T10:00:00+00:00",
        "finished_at": "2026-01-01T10:01:00+00:00",
        "dry_run": False,
        "total": 5,
        "would_give": 3,
        "given": 3,
        "success": True,
    }
    base.update(overrides)
    return base


# ── read_run_history ──────────────────────────────────────────────────────────


def test_read_run_history_missing_file_returns_empty_list(data_dir: Path) -> None:
    """read_run_history() returns [] when run-history.json does not exist."""
    from kudosy.store import read_run_history

    result = read_run_history()
    assert result == []


def test_read_run_history_default_limit(data_dir: Path) -> None:
    """read_run_history() with no argument returns up to 100 entries."""
    from kudosy.store import append_run_history, read_run_history

    for i in range(5):
        append_run_history(_make_entry(total=i))

    result = read_run_history()
    assert len(result) == 5


def test_read_run_history_limit(data_dir: Path) -> None:
    """read_run_history(limit=2) returns only the 2 most recent entries."""
    from kudosy.store import append_run_history, read_run_history

    for i in range(5):
        append_run_history(_make_entry(total=i))

    result = read_run_history(limit=2)
    assert len(result) == 2
    # Most recent first: total=4, then total=3
    assert result[0]["total"] == 4
    assert result[1]["total"] == 3


# ── append_run_history ────────────────────────────────────────────────────────


def test_append_run_history_creates_file(data_dir: Path) -> None:
    """append_run_history() creates run-history.json when it does not exist."""
    from kudosy.store import append_run_history, read_run_history

    history_file = data_dir / "run-history.json"
    assert not history_file.exists()

    append_run_history(_make_entry())

    assert history_file.exists()
    result = read_run_history()
    assert len(result) == 1


def test_append_run_history_accumulates_entries(data_dir: Path) -> None:
    """Multiple append calls accumulate entries in reverse-chronological order."""
    from kudosy.store import append_run_history, read_run_history

    append_run_history(_make_entry(total=1))
    append_run_history(_make_entry(total=2))
    append_run_history(_make_entry(total=3))

    result = read_run_history()
    assert len(result) == 3
    # Most recent (total=3) must be first
    assert result[0]["total"] == 3
    assert result[1]["total"] == 2
    assert result[2]["total"] == 1


def test_append_run_history_rolling_window(data_dir: Path) -> None:
    """The history file is capped at _MAX_HISTORY entries; oldest are pruned."""
    from kudosy import store
    from kudosy.store import append_run_history, read_run_history

    cap = store._MAX_HISTORY
    # Write cap + 10 entries
    for i in range(cap + 10):
        append_run_history(_make_entry(total=i))

    result = read_run_history(limit=cap + 100)
    assert len(result) == cap
    # Most recent entry should have total = cap + 9
    assert result[0]["total"] == cap + 9


def test_append_run_history_entry_fields(data_dir: Path) -> None:
    """Appended entries contain the expected subset of RunResult fields."""
    from kudosy.store import append_run_history, read_run_history

    entry = _make_entry(
        started_at="2026-06-01T08:00:00+00:00",
        finished_at="2026-06-01T08:01:30+00:00",
        dry_run=True,
        total=10,
        would_give=7,
        given=0,
        success=True,
    )
    append_run_history(entry)

    result = read_run_history()
    assert len(result) == 1
    saved = result[0]
    assert saved["started_at"] == "2026-06-01T08:00:00+00:00"
    assert saved["finished_at"] == "2026-06-01T08:01:30+00:00"
    assert saved["dry_run"] is True
    assert saved["total"] == 10
    assert saved["would_give"] == 7
    assert saved["given"] == 0
    assert saved["success"] is True
