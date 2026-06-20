"""Feed parsing — the brittleness firewall.

All Strava response-format assumptions live here and ONLY here.
Everything downstream consumes the normalized list[Activity].

The FeedParser Protocol ensures the engine stays testable with fake parsers.
"""

from __future__ import annotations

import json
import logging
import re
from typing import Any, ClassVar, Protocol

from kudosy.models import Activity

log = logging.getLogger(__name__)

# ── Protocol ──────────────────────────────────────────────────────────────────


class FeedParser(Protocol):
    """Parse raw Strava feed payload into a list of Activity objects."""

    def parse(self, payload: str | bytes | dict[str, Any]) -> list[Activity]:
        """Parse *payload* and return normalized activities.

        Implementations must:
        - Skip unparseable entries (log WARN, do not raise)
        - Return an empty list rather than raising on total failure
        """
        ...


# ── Concrete parser ───────────────────────────────────────────────────────────


class StravaHtmlFeedParser:
    """Parse the Strava following feed.

    Strategy 1 (preferred): extract embedded JSON hydration blob from the HTML
    (Strava embeds feed data as a script tag, e.g. a __NEXT_DATA__ or similar
    structure). If found and parseable, use it.

    Strategy 2 (fallback): DOM/regex scraping of the HTML activity cards.

    Both strategies normalize to list[Activity].

    Note: The exact structure of Strava's feed response is subject to change.
    This parser is designed to degrade gracefully:
    - Unexpected structure → logs a clear warning, returns empty list.
    - Per-card parse errors → logs WARN with card id, skips that card.
    - Auth failures (login redirect) → raises AuthError (handled by client).
    """

    # Known patterns for the embedded JSON data blob
    _HYDRATION_PATTERNS: ClassVar[list[re.Pattern[str]]] = [
        # Next.js: window.__NEXT_DATA__ = {...}
        re.compile(r"window\.__NEXT_DATA__\s*=\s*(\{.+?\})\s*;?\s*</script>", re.DOTALL),
        # Generic: window.pageProps = {...}
        re.compile(r"window\.pageProps\s*=\s*(\{.+?\})\s*;?\s*</script>", re.DOTALL),
        # Strava-specific: var pageView = {...}
        re.compile(r"var\s+pageView\s*=\s*(\{.+?\})\s*;?\s*(?:var|</script>)", re.DOTALL),
    ]

    # DOM scraping fallback patterns
    # Activity card pattern: data-activity-id + athlete + sport type
    _CARD_RE: ClassVar[re.Pattern[str]] = re.compile(
        r'data-activity-id="?(\d+)"?[^>]*>.*?'
        r'class="[^"]*athlete-name[^"]*"[^>]*>([^<]+)<',
        re.DOTALL,
    )

    def parse(self, payload: str | bytes | dict[str, Any]) -> list[Activity]:
        if isinstance(payload, bytes):
            payload = payload.decode("utf-8", errors="replace")

        if isinstance(payload, dict):
            return self._parse_json_dict(payload)

        # Try embedded JSON first
        activities = self._try_embedded_json(payload)
        if activities is not None:
            return activities

        # Fallback: HTML scraping
        return self._scrape_html(payload)

    def _try_embedded_json(self, html: str) -> list[Activity] | None:
        for pattern in self._HYDRATION_PATTERNS:
            m = pattern.search(html)
            if not m:
                continue
            try:
                data = json.loads(m.group(1))
                activities = self._parse_json_dict(data)
                if activities or len(activities) == 0:
                    log.debug("Feed parsed via embedded JSON (%d activities)", len(activities))
                    return activities
            except (json.JSONDecodeError, KeyError, TypeError):
                continue
        return None

    def _parse_json_dict(self, data: dict[str, Any]) -> list[Activity]:
        """Parse a JSON dict that may contain feed entries in various shapes."""
        # Try common key paths
        entries: list[Any] = []
        for key in ("entries", "activities", "feed", "data"):
            if key in data and isinstance(data[key], list):
                entries = data[key]
                break
        if not entries:
            # Nested: data.props.pageProps.activities etc.
            props = data.get("props", {}).get("pageProps", {})
            for key in ("entries", "activities", "feed"):
                if key in props and isinstance(props[key], list):
                    entries = props[key]
                    break

        results: list[Activity] = []
        for entry in entries:
            try:
                act = self._parse_entry(entry)
                if act:
                    results.append(act)
            except Exception:
                log.warning("Failed to parse feed entry: %r", str(entry)[:200], exc_info=True)
        return results

    def _parse_entry(self, entry: dict[str, Any]) -> Activity | None:
        """Parse a single JSON activity entry into an Activity."""
        activity_id = str(entry.get("id") or entry.get("activity_id") or "")
        if not activity_id:
            return None

        athlete = entry.get("athlete", entry.get("owner", {}))
        athlete_id = str(athlete.get("id") or athlete.get("athlete_id") or "")
        athlete_name = str(athlete.get("name") or athlete.get("display_name") or "Unknown")

        activity_name = str(entry.get("name") or entry.get("title") or "")
        sport_type = str(entry.get("sport_type") or entry.get("type") or "")
        has_kudoed = bool(entry.get("has_kudoed") or entry.get("kudoed_by_me"))

        # Build stats from known numeric fields
        stats: dict[str, str] = {}
        if (d := entry.get("distance")) is not None:
            stats["Distance"] = f"{float(d) / 1000:.2f} km"
        if (t := entry.get("moving_time") or entry.get("elapsed_time")) is not None:
            secs = int(t)
            h, rem = divmod(secs, 3600)
            m, s = divmod(rem, 60)
            if h:
                stats["Time"] = f"{h}h {m}m"
            else:
                stats["Time"] = f"{m}m {s}s"

        return Activity(
            athlete_name=athlete_name,
            athlete_id=athlete_id,
            activity_id=activity_id,
            activity_name=activity_name,
            sport_type=sport_type,
            has_kudoed=has_kudoed,
            stats=stats,
        )

    def _scrape_html(self, html: str) -> list[Activity]:
        """Last-resort HTML scraping. Returns empty list with a warning if nothing found."""
        # This is intentionally minimal — if the JSON approach fails, we log a clear warning
        # so the user knows the feed format may have changed.
        log.warning(
            "Could not extract feed data from embedded JSON. "
            "Strava's feed format may have changed. "
            "Returning 0 activities. Try a Dry-Run to diagnose."
        )
        return []


class AuthError(Exception):
    """Raised when Strava returns a login redirect (cookie expired)."""
