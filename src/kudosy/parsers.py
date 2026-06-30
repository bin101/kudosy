"""Pure parsing functions — no I/O, no side effects.

All functions accept str | None and return None on unparseable input,
so callers can decide how to handle missing stats gracefully.
"""

from __future__ import annotations

import re

# ── HTML entity decoding ──────────────────────────────────────────────────────

_ENTITIES: dict[str, str] = {
    "&amp;": "&",
    "&lt;": "<",
    "&gt;": ">",
    "&quot;": '"',
    "&#39;": "'",
    "&apos;": "'",
}
_ENTITY_RE = re.compile("|".join(re.escape(k) for k in _ENTITIES))


def decode_html_entities(s: str) -> str:
    """Replace the six most common HTML entities in *s*."""
    return _ENTITY_RE.sub(lambda m: _ENTITIES[m.group()], s)


# ── Distance ──────────────────────────────────────────────────────────────────

# "30.10 km", "222.02 km", "2,800 m", "500 m"
_DIST_RE = re.compile(
    r"(?P<val>[\d,]+(?:\.\d+)?)\s*(?P<unit>km|m)\b",
    re.IGNORECASE,
)


def parse_distance(raw: str | None) -> float | None:
    """Parse a Strava distance string and return metres, or None if unparseable.

    Examples:
        "30.10 km"  → 30100.0
        "2,800 m"   → 2800.0
        "500 m"     → 500.0
    """
    if not raw:
        return None
    m = _DIST_RE.search(raw)
    if not m:
        return None
    # Remove thousands comma before float conversion
    val = float(m.group("val").replace(",", ""))
    if m.group("unit").lower() == "km":
        return val * 1000.0
    return val


# ── Duration ──────────────────────────────────────────────────────────────────

# Matches: "1h 5m", "37m 11s", "0h 0m", "2h", "45m", "30s"
_DUR_PARTS_RE = re.compile(
    r"(?:(?P<h>\d+)\s*h)?"
    r"\s*(?:(?P<m>\d+)\s*m)?"
    r"\s*(?:(?P<s>\d+)\s*s)?",
    re.IGNORECASE,
)


def parse_duration(raw: str | None) -> int | None:
    """Parse a Strava duration string and return seconds, or None if unparseable.

    Examples:
        "1h 5m"    → 3900
        "37m 11s"  → 2231
        "0h 0m"    → 0
    """
    if not raw:
        return None
    m = _DUR_PARTS_RE.search(raw)
    if not m or not m.group():
        return None
    h = int(m.group("h") or 0)
    mins = int(m.group("m") or 0)
    secs = int(m.group("s") or 0)
    total = h * 3600 + mins * 60 + secs
    # Require at least one component was present
    if h == 0 and mins == 0 and secs == 0 and not any(m.group(g) for g in ("h", "m", "s")):
        return None
    return total


# ── Stats normalization ───────────────────────────────────────────────────────

# Canonical keys used throughout the engine and frontend.
STAT_KEY_TIME = "Time"  # moving time (decision.py reads this for minTime checks)
STAT_KEY_TOTAL_TIME = "Total Time"  # elapsed/total time
STAT_KEY_DISTANCE = "Distance"
STAT_KEY_ELEVATION = "Elevation"

# Matches bare distance values: "30.10 km", "500 m", "2,800 m".
# For the "m" unit a space is required ("500 m", not "500m") to distinguish
# distance-in-metres from time-in-minutes ("45m" without space = 45 minutes).
# Excludes compound units like "23.4 km/h" (speed) or "5:23 /km" (pace).
_DIST_ONLY_RE = re.compile(r"^[\d,]+(?:\.\d+)?(?:\s+m|\s*km)\s*$", re.IGNORECASE)


def _is_distance_value(val: str) -> bool:
    return bool(_DIST_ONLY_RE.match(val.strip()))


def normalize_stats(stats: dict[str, str]) -> dict[str, str]:
    """Normalize time and distance entries in *stats* to canonical keys.

    Time normalization (value-based, via parse_duration):
    - 0 duration entries: unchanged.
    - 1 duration entry:   renamed to ``"Time"`` (moving time).
    - 2+ duration entries: shortest → ``"Time"``, longest → ``"Total Time"``;
      intermediate values are discarded.

    Distance/elevation normalization (value-based + position-based):
    - 1 distance entry:  renamed to ``"Distance"``.
    - 2+ entries: first (by insertion order) → ``"Distance"``,
      second → ``"Elevation"``; further entries are discarded.
    - Insertion order mirrors Strava's consistent stat ordering (Distance first).
    - Speed ("23.4 km/h") and pace ("5:23 /km") are NOT matched.

    Non-time, non-distance entries (pace, heart rate, etc.) are kept as-is.
    This function is idempotent.
    """
    time_entries: list[tuple[str, int]] = []  # (original_key, seconds)
    dist_entries: list[tuple[str, str]] = []  # (original_key, original_value)
    rest: dict[str, str] = {}

    for key, value in stats.items():
        # Distance check must come first: "500 m" would be parsed as 500 minutes
        # by parse_duration if we checked time first.
        if _is_distance_value(value):
            dist_entries.append((key, value))
        else:
            secs = parse_duration(value)
            if secs is not None:
                time_entries.append((key, secs))
            else:
                rest[key] = value

    result = dict(rest)

    if time_entries:
        if len(time_entries) == 1:
            result[STAT_KEY_TIME] = stats[time_entries[0][0]]
        else:
            # Sort ascending by seconds; shortest = moving time, longest = total time.
            time_entries.sort(key=lambda x: x[1])
            result[STAT_KEY_TIME] = stats[time_entries[0][0]]
            result[STAT_KEY_TOTAL_TIME] = stats[time_entries[-1][0]]

    if dist_entries:
        result[STAT_KEY_DISTANCE] = dist_entries[0][1]
        if len(dist_entries) >= 2:
            result[STAT_KEY_ELEVATION] = dist_entries[1][1]

    return result


# ── Athlete name ──────────────────────────────────────────────────────────────

_OG_TITLE_RE = (
    re.compile(r'<meta[^>]*property="og:title"[^>]*content="([^"]+)"', re.IGNORECASE),
    re.compile(r'<meta[^>]*content="([^"]+)"[^>]*property="og:title"', re.IGNORECASE),
)
_TITLE_RE = re.compile(r"<title>([^<]+)</title>", re.IGNORECASE)

_REJECT_NAMES = frozenset(["strava"])


def _extract_name(raw: str) -> str | None:
    """Extract the athlete name from the first segment of a '…|…' string."""
    name = decode_html_entities(raw.split(" | ")[0].strip())
    if not name:
        return None
    if name.lower() in _REJECT_NAMES:
        return None
    if "log in" in name.lower():
        return None
    return name


def parse_athlete_name(html: str) -> str | None:
    """Extract an athlete's display name from a Strava profile page.

    Tries ``og:title`` first (both attribute orders), then ``<title>``.
    Returns None when the page looks like a login redirect or is blank.
    """
    if not html:
        return None
    for pattern in _OG_TITLE_RE:
        m = pattern.search(html)
        if m:
            name = _extract_name(m.group(1))
            if name:
                return name
    m2 = _TITLE_RE.search(html)
    if m2:
        return _extract_name(m2.group(1))
    return None
