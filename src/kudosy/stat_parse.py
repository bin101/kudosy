"""Pure stat-parsing functions — no I/O, no side effects.

Parses the HTML-wrapped display strings that Strava embeds in activity feed
stat items (e.g. ``"5.17<abbr class='unit' title='kilometers'> km</abbr>"``).
All functions return ``None`` on unparseable input; callers decide how to handle
missing stats gracefully (typically by leaving the corresponding field unset).

Feed format notes (verified against real dashboard/feed JSON, 2026-06-30):
  - Stat values contain ``<abbr class='unit' title='…'>…</abbr>`` markup that
    carries the unit string.  ``strip_unit_markup`` removes the markup and
    returns a clean human-readable string (e.g. "5.17 km", "41m 56s").
  - Numbers use English decimal format (period), but thousands are comma-separated
    (e.g. "1,300 m").
  - Feed is fetched with ``Accept-Language: en`` to guarantee English labels and
    English number formatting.

Canonical stat keys returned by ``classify_stat``:
    "distance"       — distance in metres (``distance_m``)
    "time"           — moving time in seconds (``moving_time_s``)
    "elevation_gain" — elevation gain in metres (``elevation_gain_m``)
    "pace"           — running/cycling pace in seconds/km (``pace_s_per_km``)
    "swim_pace"      — swim pace in seconds/100m (``pace_s_per_100m``)
    "unknown"        — unrecognised, goes into ``ActivityStats.extra``
"""

from __future__ import annotations

import re

# ── HTML markup removal ───────────────────────────────────────────────────────

_ABBR_TAG_RE = re.compile(r"<abbr[^>]*>|</abbr>", re.IGNORECASE)


def strip_unit_markup(raw: str | None) -> str | None:
    """Remove ``<abbr …>…</abbr>`` markup from a Strava stat value string.

    Returns the cleaned string with leading/trailing whitespace removed,
    or ``None`` when the input is falsy.

    Examples::

        "5.17<abbr class='unit' title='kilometers'> km</abbr>" → "5.17 km"
        "41<abbr title='minute'>m</abbr> 56<abbr title='second'>s</abbr>" → "41m 56s"
        "1:37<abbr title='per 100 Meters'> /100m</abbr>" → "1:37 /100m"
    """
    if not raw:
        return None
    return _ABBR_TAG_RE.sub("", raw).strip()


# ── Distance ─────────────────────────────────────────────────────────────────

# Handles "5.17 km", "53.24 km", "1,300 m", "116 m" (thousands comma-separator)
_DIST_RE = re.compile(
    r"(?P<val>[\d,]+(?:\.\d+)?)\s*(?P<unit>km|m)\b",
    re.IGNORECASE,
)


def parse_distance(raw: str | None) -> float | None:
    """Parse a distance string and return metres, or ``None`` if unparseable.

    Handles both km and m units, including comma-thousands separators.

    Examples::

        "5.17 km"  → 5170.0
        "1,300 m"  → 1300.0
        "116 m"    → 116.0
    """
    if not raw:
        return None
    cleaned = strip_unit_markup(raw)
    if not cleaned:
        return None
    m = _DIST_RE.search(cleaned)
    if not m:
        return None
    val = float(m.group("val").replace(",", ""))
    return val * 1000.0 if m.group("unit").lower() == "km" else val


# ── Duration ──────────────────────────────────────────────────────────────────

# Matches: "41m 56s", "1h 46m", "1h 0m", "30m 0s", "1h 0m 0s"
_DUR_RE = re.compile(
    r"(?:(?P<h>\d+)\s*h)?\s*(?:(?P<m>\d+)\s*m)?\s*(?:(?P<s>\d+)\s*s)?",
    re.IGNORECASE,
)


def parse_duration(raw: str | None) -> int | None:
    """Parse a duration display string and return seconds, or ``None``.

    Examples::

        "41m 56s" → 2516
        "1h 46m"  → 6360
        "1h 0m"   → 3600
        "30m 0s"  → 1800
    """
    if not raw:
        return None
    cleaned = strip_unit_markup(raw)
    if not cleaned:
        return None
    m = _DUR_RE.search(cleaned)
    if not m:
        return None
    h = int(m.group("h") or 0)
    mins = int(m.group("m") or 0)
    secs = int(m.group("s") or 0)
    if not any(m.group(g) for g in ("h", "m", "s")):
        return None
    return h * 3600 + mins * 60 + secs


# ── Pace ──────────────────────────────────────────────────────────────────────

# Matches "8:06 /km", "5:56 /km", "1:37 /100m"
_PACE_KM_RE = re.compile(r"(?P<min>\d+):(?P<sec>\d{2})\s*/km\b", re.IGNORECASE)
_PACE_100M_RE = re.compile(r"(?P<min>\d+):(?P<sec>\d{2})\s*/100m\b", re.IGNORECASE)


def parse_pace(raw: str | None) -> tuple[float, str] | None:
    """Parse a pace string and return ``(seconds, unit_key)`` or ``None``.

    The ``unit_key`` is ``"s/km"`` for running pace and ``"s/100m"`` for swim pace.

    Examples::

        "8:06 /km"   → (486.0, "s/km")
        "1:37 /100m" → (97.0, "s/100m")
    """
    if not raw:
        return None
    cleaned = strip_unit_markup(raw)
    if not cleaned:
        return None

    m = _PACE_100M_RE.search(cleaned)
    if m:
        return (int(m.group("min")) * 60 + int(m.group("sec")), "s/100m")

    m = _PACE_KM_RE.search(cleaned)
    if m:
        return (int(m.group("min")) * 60 + int(m.group("sec")), "s/km")

    return None


def parse_pace_km(raw: str | None) -> float | None:
    """Return pace in seconds/km, or ``None`` if not a /km pace string."""
    result = parse_pace(raw)
    if result and result[1] == "s/km":
        return result[0]
    return None


def parse_swim_pace(raw: str | None) -> float | None:
    """Return swim pace in seconds/100m, or ``None`` if not a /100m pace string."""
    result = parse_pace(raw)
    if result and result[1] == "s/100m":
        return result[0]
    return None


# ── Elevation ─────────────────────────────────────────────────────────────────

_ELEV_RE = re.compile(r"(?P<val>[\d,]+(?:\.\d+)?)\s*(?P<unit>m|ft)\b", re.IGNORECASE)


def parse_elevation(raw: str | None) -> float | None:
    """Parse an elevation string and return metres, or ``None`` if unparseable.

    Examples::

        "116 m"   → 116.0
        "320 m"   → 320.0
        "9 m"     → 9.0
    """
    if not raw:
        return None
    cleaned = strip_unit_markup(raw)
    if not cleaned:
        return None
    m = _ELEV_RE.search(cleaned)
    if not m:
        return None
    val = float(m.group("val").replace(",", ""))
    if m.group("unit").lower() == "ft":
        return val * 0.3048
    return val


# ── Stat classification ────────────────────────────────────────────────────────

# Subtitle labels as returned by the English feed (Accept-Language: en).
# All lookups are case-insensitive.
_LABEL_MAP: dict[str, str] = {
    "distance": "distance",
    "time": "time",
    "elev gain": "elevation_gain",
    "elevation gain": "elevation_gain",
    "pace": "pace",
}


def classify_stat(label: str, raw: str = "") -> str:
    """Map a Strava stat subtitle label to a canonical key.

    The raw value is always inspected for pace unit markers first (``/100m``
    vs ``/km``), because the label "Pace" is ambiguous across sport types.
    For all other labels the lookup table takes precedence.

    Returns one of: ``"distance"``, ``"time"``, ``"elevation_gain"``,
    ``"pace"``, ``"swim_pace"``, ``"unknown"``.
    """
    # Inspect the cleaned raw value for pace unit hints — must run before
    # the label lookup because "Pace" is used for both /km (Run) and /100m (Swim).
    cleaned = (strip_unit_markup(raw) or raw).lower()
    if "/100m" in cleaned:
        return "swim_pace"
    if "/km" in cleaned:
        return "pace"

    key = _LABEL_MAP.get(label.strip().lower())
    if key:
        return key

    return "unknown"
