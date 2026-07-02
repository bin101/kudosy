"""Unit tests for digest-state store helpers (read_last_digest_at / write_last_digest_at)."""

from __future__ import annotations

import json
from pathlib import Path

# ── read_last_digest_at ───────────────────────────────────────────────────────


def test_read_last_digest_at_missing_file_returns_none(data_dir: Path) -> None:
    from kudosy.store import read_last_digest_at

    assert read_last_digest_at() is None


def test_read_last_digest_at_returns_stored_value(data_dir: Path) -> None:
    from kudosy.store import read_last_digest_at, write_last_digest_at

    ts = "2026-07-01T20:00:00+00:00"
    write_last_digest_at(ts)
    assert read_last_digest_at() == ts


def test_read_last_digest_at_corrupt_file_returns_none(data_dir: Path) -> None:
    from kudosy.store import read_last_digest_at

    (data_dir / "last-digest.json").write_text("not json at all", encoding="utf-8")
    assert read_last_digest_at() is None


def test_read_last_digest_at_missing_key_returns_none(data_dir: Path) -> None:
    from kudosy.store import read_last_digest_at

    (data_dir / "last-digest.json").write_text(json.dumps({"other_key": "value"}), encoding="utf-8")
    assert read_last_digest_at() is None


# ── write_last_digest_at ──────────────────────────────────────────────────────


def test_write_last_digest_at_creates_file(data_dir: Path) -> None:
    from kudosy.store import write_last_digest_at

    write_last_digest_at("2026-07-02T20:00:00+00:00")
    assert (data_dir / "last-digest.json").exists()


def test_write_last_digest_at_round_trip(data_dir: Path) -> None:
    from kudosy.store import read_last_digest_at, write_last_digest_at

    ts = "2026-07-02T20:00:00+00:00"
    write_last_digest_at(ts)
    assert read_last_digest_at() == ts


def test_write_last_digest_at_overwrites_previous_value(data_dir: Path) -> None:
    from kudosy.store import read_last_digest_at, write_last_digest_at

    write_last_digest_at("2026-07-01T20:00:00+00:00")
    write_last_digest_at("2026-07-02T20:00:00+00:00")
    assert read_last_digest_at() == "2026-07-02T20:00:00+00:00"
