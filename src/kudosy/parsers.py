"""Pure parsing functions — no I/O, no side effects.

Contains helper parsers used by :mod:`kudosy.strava_client` and other modules.

Note: distance/duration parsing has moved to :mod:`kudosy.stat_parse` which
handles the full Strava feed stat format (HTML-wrapped display strings).
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
