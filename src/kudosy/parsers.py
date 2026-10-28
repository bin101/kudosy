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

_OG_CONTENT = r"""content=(?:"([^"]+)"|'([^']+)')"""
_OG_PROPERTY = r"""property=["']og:title["']"""
_OG_TITLE_RE = (
    re.compile(rf"<meta[^>]*{_OG_PROPERTY}[^>]*{_OG_CONTENT}", re.IGNORECASE),
    re.compile(rf"<meta[^>]*{_OG_CONTENT}[^>]*{_OG_PROPERTY}", re.IGNORECASE),
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
            name = _extract_name(m.group(1) or m.group(2))
            if name:
                return name
    m2 = _TITLE_RE.search(html)
    if m2:
        return _extract_name(m2.group(1))
    return None


# ── Strava cookies ────────────────────────────────────────────────────────────

SESSION_COOKIE = "_strava4_session"
REMEMBER_COOKIES = ("strava_remember_id", "strava_remember_token")

_COOKIE_PAIR_RE = re.compile(r"^([A-Za-z_][\w.\-]*)=(.*)$", re.DOTALL)
_COOKIE_HEADER_PREFIX_RE = re.compile(r"^cookie\s*:\s*", re.IGNORECASE)


def is_strava_cookie_name(name: str) -> bool:
    """True for cookies Kudosy needs (session + remember-me); tracking cookies are not."""
    return name in (SESSION_COOKIE, *REMEMBER_COOKIES) or name.startswith(("_strava", "strava_"))


def _strip_quotes(s: str) -> str:
    s = s.strip()
    if len(s) >= 2 and s[0] == s[-1] and s[0] in "\"'":
        return s[1:-1].strip()
    return s


def parse_strava_cookies(text: str) -> dict[str, str]:
    """Parse pasted cookie input into the Strava cookies Kudosy needs.

    Accepts a full ``Cookie:`` request header from DevTools (with or without the
    ``Cookie:`` prefix), ``name=value; name=value`` pairs, or a bare
    ``_strava4_session`` value. Surrounding quotes, whitespace and line breaks
    are ignored. Non-Strava (tracking) cookies are dropped.

    Raises ``ValueError`` unless the result contains ``_strava4_session`` or
    both remember-me cookies.
    """
    # Cookie values never contain whitespace; clipboard line breaks / wrapping must not survive.
    cleaned = _strip_quotes("".join(text.split()))
    cleaned = _strip_quotes(_COOKIE_HEADER_PREFIX_RE.sub("", cleaned))
    if not cleaned:
        raise ValueError("Cookie input is empty")

    pairs: dict[str, str] = {}
    for part in cleaned.split(";"):
        m = _COOKIE_PAIR_RE.match(part.strip())
        if m:
            pairs[m.group(1)] = _strip_quotes(m.group(2))

    if not any(is_strava_cookie_name(name) for name in pairs):
        # No recognisable cookie name: a bare value (may itself contain "=" padding).
        if ";" in cleaned:
            raise ValueError("No Strava cookie found in input")
        pairs = {SESSION_COOKIE: cleaned}

    cookies = {k: v for k, v in pairs.items() if v and is_strava_cookie_name(k)}
    has_remember = all(cookies.get(n) for n in REMEMBER_COOKIES)
    if not cookies.get(SESSION_COOKIE) and not has_remember:
        raise ValueError("Neither _strava4_session nor the remember-me cookies found")
    return cookies
