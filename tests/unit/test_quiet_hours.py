"""Unit tests for kudosy.quiet_hours — pure quiet-hours / schedule-matrix logic."""

from __future__ import annotations

import random
from datetime import UTC, datetime, timedelta

from kudosy.quiet_hours import is_allowed, is_valid_timezone, next_allowed_run

# A 7x24 matrix where every slot is allowed.
ALL_ALLOWED: list[list[bool]] = [[True] * 24 for _ in range(7)]

# A 7x24 matrix where every slot is blocked.
ALL_BLOCKED: list[list[bool]] = [[False] * 24 for _ in range(7)]


def _dt(weekday: int, hour: int) -> datetime:
    """Return a timezone-aware datetime for the given weekday (Mon=0) and hour in Europe/Berlin."""
    from zoneinfo import ZoneInfo

    # 2025-01-06 is a Monday.  Offset by weekday to get the desired day.
    base = datetime(2025, 1, 6, hour, 0, 0, tzinfo=ZoneInfo("Europe/Berlin"))
    return base + timedelta(days=weekday)


def _utc(weekday: int, hour: int) -> datetime:
    """Return a UTC datetime that maps to Europe/Berlin weekday/hour (CET = UTC+1)."""
    local = _dt(weekday, hour)
    return local.astimezone(UTC)


# ── is_valid_timezone ─────────────────────────────────────────────────────────


def test_valid_timezone_known() -> None:
    assert is_valid_timezone("Europe/Berlin") is True
    assert is_valid_timezone("UTC") is True
    assert is_valid_timezone("America/New_York") is True


def test_valid_timezone_unknown() -> None:
    assert is_valid_timezone("Mars/Olympus") is False
    assert is_valid_timezone("") is False


# ── is_allowed ────────────────────────────────────────────────────────────────


def test_is_allowed_all_allowed() -> None:
    for wd in range(7):
        for h in range(24):
            assert is_allowed(ALL_ALLOWED, _dt(wd, h)) is True


def test_is_allowed_all_blocked() -> None:
    for wd in range(7):
        for h in range(24):
            assert is_allowed(ALL_BLOCKED, _dt(wd, h)) is False


def test_is_allowed_single_slot() -> None:
    matrix = [[False] * 24 for _ in range(7)]
    matrix[2][14] = True  # Wednesday 14:00 is allowed
    assert is_allowed(matrix, _dt(2, 14)) is True
    assert is_allowed(matrix, _dt(2, 13)) is False
    assert is_allowed(matrix, _dt(3, 14)) is False


def test_is_allowed_malformed_matrix_returns_true() -> None:
    """Out-of-bounds access in a malformed matrix should return True (safe default)."""
    assert is_allowed([], _dt(0, 0)) is True
    assert is_allowed([[True, False]], _dt(1, 0)) is True  # row 1 missing


# ── next_allowed_run — disabled ───────────────────────────────────────────────


def test_next_allowed_run_disabled_returns_candidate() -> None:
    """When enabled=False the candidate is returned unchanged, even if the slot is blocked."""
    candidate = _utc(0, 3)  # Monday 3:00 AM
    result = next_allowed_run(candidate, ALL_BLOCKED, "Europe/Berlin", enabled=False)
    assert result == candidate


# ── next_allowed_run — already allowed ────────────────────────────────────────


def test_next_allowed_run_already_allowed() -> None:
    candidate = _utc(0, 10)  # Monday 10:00, all allowed
    result = next_allowed_run(candidate, ALL_ALLOWED, "Europe/Berlin", enabled=True)
    assert result == candidate


# ── next_allowed_run — shift to next slot ─────────────────────────────────────


def test_next_allowed_run_shifts_to_next_hour() -> None:
    """A blocked slot is shifted to the first allowed hour (11:xx of the same day)."""
    matrix = [[False] * 24 for _ in range(7)]
    matrix[0][11] = True  # Monday 11:00 is allowed; 10:00 is blocked

    candidate = _utc(0, 10)  # Monday 10:00 — blocked
    rng = random.Random(42)
    result = next_allowed_run(candidate, matrix, "Europe/Berlin", enabled=True, rng=rng)
    assert result is not None
    result_local = result.astimezone(__import__("zoneinfo").ZoneInfo("Europe/Berlin"))
    assert result_local.weekday() == 0  # still Monday
    assert result_local.hour == 11
    assert 0 <= result_local.minute <= 59


def test_next_allowed_run_crosses_midnight() -> None:
    """A slot at 23:00 being blocked shifts to the first allowed slot the next day."""
    matrix = [[False] * 24 for _ in range(7)]
    matrix[1][6] = True  # Tuesday 06:00 is the first allowed slot

    candidate = _utc(0, 23)  # Monday 23:00 — blocked
    rng = random.Random(0)
    result = next_allowed_run(candidate, matrix, "Europe/Berlin", enabled=True, rng=rng)
    assert result is not None
    result_local = result.astimezone(__import__("zoneinfo").ZoneInfo("Europe/Berlin"))
    assert result_local.weekday() == 1  # Tuesday
    assert result_local.hour == 6


def test_next_allowed_run_crosses_week() -> None:
    """Scans across the weekday wrap-around (Sun → Mon)."""
    matrix = [[False] * 24 for _ in range(7)]
    matrix[0][8] = True  # Monday 08:00 is the only allowed slot

    candidate = _utc(6, 12)  # Sunday 12:00 — blocked
    rng = random.Random(7)
    result = next_allowed_run(candidate, matrix, "Europe/Berlin", enabled=True, rng=rng)
    assert result is not None
    result_local = result.astimezone(__import__("zoneinfo").ZoneInfo("Europe/Berlin"))
    assert result_local.weekday() == 0  # Monday
    assert result_local.hour == 8


# ── next_allowed_run — all blocked ────────────────────────────────────────────


def test_next_allowed_run_all_blocked_returns_none() -> None:
    candidate = _utc(3, 12)
    result = next_allowed_run(candidate, ALL_BLOCKED, "Europe/Berlin", enabled=True)
    assert result is None


# ── next_allowed_run — unknown timezone ───────────────────────────────────────


def test_next_allowed_run_unknown_tz_returns_candidate() -> None:
    """An unknown timezone falls back to returning the candidate unchanged."""
    candidate = _utc(0, 3)
    result = next_allowed_run(candidate, ALL_BLOCKED, "Mars/Olympus", enabled=True)
    assert result == candidate


# ── random offset is in range ─────────────────────────────────────────────────


def test_next_allowed_run_random_offset_in_range() -> None:
    """The minute offset of the shifted run is always 0-59."""
    matrix = [[False] * 24 for _ in range(7)]
    matrix[0][12] = True  # Monday 12:00 allowed

    candidate = _utc(0, 10)  # Monday 10:00 blocked
    for seed in range(50):
        rng = random.Random(seed)
        result = next_allowed_run(candidate, matrix, "Europe/Berlin", enabled=True, rng=rng)
        assert result is not None
        local = result.astimezone(__import__("zoneinfo").ZoneInfo("Europe/Berlin"))
        assert local.hour == 12
        assert 0 <= local.minute <= 59
