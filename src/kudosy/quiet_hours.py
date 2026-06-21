"""Quiet-hours helpers - pure functions for the 7x24 schedule matrix.

The matrix is a list of 7 rows (weekdays, Monday=0 to Sunday=6) x 24 columns
(hours 0-23).  Each cell is True when kudos are *allowed* in that hour.

This module is intentionally pure: all time references are passed in, and the
RNG is injected, so it is fully deterministic in tests.
"""

from __future__ import annotations

import logging
import random as _random
from datetime import UTC, datetime, timedelta
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

log = logging.getLogger(__name__)

# Maximum hours to scan forward when looking for the next allowed slot.
# 7 * 24 = 168 — one full week is enough; if every slot is blocked we give up.
_MAX_SCAN_HOURS = 168


def is_valid_timezone(tz_name: str) -> bool:
    """Return True if *tz_name* is a recognised IANA timezone identifier."""
    try:
        ZoneInfo(tz_name)
        return True
    except (ZoneInfoNotFoundError, KeyError, ValueError):
        return False


def is_allowed(matrix: list[list[bool]], dt_local: datetime) -> bool:
    """Return True when *dt_local* falls inside an allowed cell of *matrix*.

    *dt_local* must carry timezone info (i.e. be timezone-aware).
    The weekday is ISO-style: Monday=0, Sunday=6 — matching Python's
    ``datetime.weekday()``.
    """
    row = dt_local.weekday()  # 0=Mon ... 6=Sun
    col = dt_local.hour  # 0-23
    try:
        return bool(matrix[row][col])
    except IndexError:
        # Malformed matrix — treat as allowed to avoid blocking the scheduler.
        return True


def next_allowed_run(
    candidate_utc: datetime,
    matrix: list[list[bool]],
    tz_name: str,
    *,
    enabled: bool,
    rng: _random.Random | None = None,
) -> datetime | None:
    """Return the earliest allowed run time ≥ *candidate_utc*.

    When ``enabled`` is False (quiet-hours feature disabled) the candidate is
    returned unchanged.

    When the candidate already falls in an allowed slot it is returned
    unchanged.  Otherwise the function scans forward hour-by-hour (in local
    time) until it finds an allowed slot, then places the run at the start of
    that hour plus a random offset of 0-59 minutes (to avoid exact alignment).

    Returns ``None`` if no allowed slot is found within one full week
    (``_MAX_SCAN_HOURS`` iterations), which means the entire matrix is blocked.
    In that case the scheduler should not schedule a run.
    """
    if not enabled:
        return candidate_utc

    _rng = rng or _random.Random()

    try:
        tz = ZoneInfo(tz_name)
    except (ZoneInfoNotFoundError, KeyError):
        log.warning("[quiet_hours] Unknown timezone %r — treating all hours as allowed", tz_name)
        return candidate_utc

    # Convert to local time for hour/weekday comparisons.
    dt_local = candidate_utc.astimezone(tz)

    if is_allowed(matrix, dt_local):
        return candidate_utc

    # Scan forward: advance to the start of the next hour, then check.
    # We move in whole hours so we don't drift within the same slot.
    scan_local = dt_local.replace(minute=0, second=0, microsecond=0) + timedelta(hours=1)

    for _ in range(_MAX_SCAN_HOURS):
        if is_allowed(matrix, scan_local):
            # Place the run somewhere within this allowed hour (human-like timing).
            random_offset_min = _rng.randint(0, 59)
            run_local = scan_local + timedelta(minutes=random_offset_min)
            return run_local.astimezone(UTC)
        scan_local += timedelta(hours=1)

    log.warning(
        "[quiet_hours] No allowed slot found in the next %d hours — scheduler paused",
        _MAX_SCAN_HOURS,
    )
    return None
