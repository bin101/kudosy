"""Feed parsing — the brittleness firewall.

All Strava response-format assumptions live here and ONLY here.
Everything downstream consumes the normalized list[Activity].

The FeedParser Protocol ensures the engine stays testable with fake parsers.
"""

from __future__ import annotations

import html as _html_stdlib
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

    Strategy 1 (preferred): extract embedded JSON from data-react-props HTML
    attributes (current Strava format). Navigates appContext.feedProps.preFetchedEntries
    and handles both 'Activity' and 'GroupActivity' entry types.

    Strategy 2 (fallback): extract embedded JSON hydration blobs from script
    tags (older patterns: __NEXT_DATA__, pageProps, pageView).

    Strategy 3 (last resort): HTML card scraping — currently returns [] with a
    warning, since DOM structure alone is too fragile to extract kudo status.

    All strategies normalize to list[Activity].

    Note: The exact structure of Strava's feed response is subject to change.
    This parser is designed to degrade gracefully:
    - Unexpected structure → logs a clear warning, returns empty list.
    - Per-card parse errors → logs WARN with card id, skips that card.
    - Auth failures (login redirect) → raises AuthError (handled by client).
    """

    # Primary: current Strava format — data-react-props='...' HTML attribute
    _REACT_PROPS_RE: ClassVar[re.Pattern[str]] = re.compile(r"data-react-props='([^']+)'")

    # Fallback: older embedded-JSON patterns in <script> tags
    _HYDRATION_PATTERNS: ClassVar[list[re.Pattern[str]]] = [
        # Next.js: window.__NEXT_DATA__ = {...}
        re.compile(r"window\.__NEXT_DATA__\s*=\s*(\{.+?\})\s*;?\s*</script>", re.DOTALL),
        # Generic: window.pageProps = {...}
        re.compile(r"window\.pageProps\s*=\s*(\{.+?\})\s*;?\s*</script>", re.DOTALL),
        # Strava-specific: var pageView = {...}
        re.compile(r"var\s+pageView\s*=\s*(\{.+?\})\s*;?\s*(?:var|</script>)", re.DOTALL),
    ]

    # DOM scraping fallback patterns
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

        # Strategy 1: data-react-props (current Strava format)
        activities = self._try_react_props(payload)
        if activities is not None:
            return activities

        # Strategy 2: embedded JSON blobs in script tags (older patterns)
        activities = self._try_embedded_json(payload)
        if activities is not None:
            return activities

        # Strategy 3: last-resort HTML scraping
        return self._scrape_html(payload)

    # ── Strategy 1: data-react-props ──────────────────────────────────────────

    def _try_react_props(self, html: str) -> list[Activity] | None:
        """Primary strategy: extract from data-react-props attributes (current Strava).

        Strava embeds activity data as HTML-entity-encoded JSON in
        data-react-props='...' attributes. The feed lives at
        appContext.feedProps.preFetchedEntries.
        """
        for raw in self._REACT_PROPS_RE.findall(html):
            try:
                decoded = _html_stdlib.unescape(raw)
                data = json.loads(decoded)
                entries = data.get("appContext", {}).get("feedProps", {}).get("preFetchedEntries")
                if not isinstance(entries, list):
                    continue
                activities = self._parse_pre_fetched_entries(entries)
                log.debug("Feed parsed via data-react-props (%d activities)", len(activities))
                return activities
            except (json.JSONDecodeError, KeyError, TypeError):
                continue
        return None

    def _parse_pre_fetched_entries(self, entries: list[Any]) -> list[Activity]:
        """Parse preFetchedEntries from appContext.feedProps."""
        results: list[Activity] = []
        for entry in entries:
            try:
                entity = entry.get("entity", "")
                if entity == "Activity":
                    act_data = entry.get("activity")
                    if act_data:
                        act = self._parse_react_activity(act_data, is_group=False)
                        if act:
                            results.append(act)
                elif entity == "GroupActivity":
                    group_acts = entry.get("rowData", {}).get("activities", [])
                    for ga in group_acts:
                        act = self._parse_react_activity(ga, is_group=True)
                        if act:
                            results.append(act)
                # Other entity types (e.g. 'Promotion') are silently skipped
            except Exception:
                log.warning(
                    "Failed to parse preFetchedEntry: %r",
                    str(entry)[:200],
                    exc_info=True,
                )
        return results

    def _parse_react_activity(self, activity: dict[str, Any], *, is_group: bool) -> Activity | None:
        """Parse a single activity from the data-react-props feed format.

        Activity entries use camelCase fields from the React component;
        GroupActivity sub-entries use snake_case after the reference transformation.
        """
        if is_group:
            activity_id = str(activity.get("activity_id") or "")
            activity_name = str(activity.get("name") or "").replace("\n", " ").strip()
            athlete_id = str(activity.get("athlete_id") or "")
            athlete_name = str(activity.get("athlete_name") or "Unknown")
            has_kudoed = bool(activity.get("has_kudoed"))
            sport_type = str(
                activity.get("type")
                or activity.get("sport_type")
                or activity.get("activity_type")
                or ""
            )
        else:
            activity_id = str(activity.get("id") or "")
            activity_name = (
                str(activity.get("activityName") or activity.get("name") or "")
                .replace("\n", " ")
                .strip()
            )
            athlete = activity.get("athlete", {})
            athlete_id = str(athlete.get("athleteId") or athlete.get("id") or "")
            athlete_name = str(athlete.get("athleteName") or athlete.get("name") or "Unknown")
            kudos_data = activity.get("kudosAndComments", {})
            has_kudoed = bool(kudos_data.get("hasKudoed") or activity.get("has_kudoed"))
            sport_type = str(
                activity.get("type")
                or activity.get("sportType")
                or activity.get("sport_type")
                or activity.get("activity_type")
                or ""
            )

        if not activity_id:
            return None

        # Build stats: try structured stats list first, then numeric fallback
        stats: dict[str, str] = {}
        raw_stats = activity.get("stats")
        if isinstance(raw_stats, list):
            for item in raw_stats:
                if isinstance(item, dict):
                    label = str(item.get("label") or item.get("key") or "")
                    value = str(item.get("value") or "")
                    if label and value:
                        stats[label] = value

        # Numeric fallback (covers both camelCase movingTime and snake_case moving_time)
        if "Distance" not in stats:
            d = activity.get("distance")
            if d is not None:
                stats["Distance"] = f"{float(d) / 1000:.2f} km"
        if "Time" not in stats:
            t = (
                activity.get("movingTime")
                or activity.get("moving_time")
                or activity.get("elapsed_time")
                or activity.get("elapsedTime")
            )
            if t is not None:
                secs = int(t)
                h, rem = divmod(secs, 3600)
                m, s = divmod(rem, 60)
                stats["Time"] = f"{h}h {m}m" if h else f"{m}m {s}s"

        return Activity(
            athlete_name=athlete_name,
            athlete_id=athlete_id,
            activity_id=activity_id,
            activity_name=activity_name,
            sport_type=sport_type,
            has_kudoed=has_kudoed,
            stats=stats,
        )

    # ── Strategy 2: embedded JSON blobs ───────────────────────────────────────

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
        entries: list[Any] = []
        for key in ("entries", "activities", "feed", "data"):
            if key in data and isinstance(data[key], list):
                entries = data[key]
                break
        if not entries:
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
        """Parse a single JSON activity entry into an Activity (generic/fallback format)."""
        activity_id = str(entry.get("id") or entry.get("activity_id") or "")
        if not activity_id:
            return None

        athlete = entry.get("athlete", entry.get("owner", {}))
        athlete_id = str(athlete.get("id") or athlete.get("athlete_id") or "")
        athlete_name = str(athlete.get("name") or athlete.get("display_name") or "Unknown")

        activity_name = str(entry.get("name") or entry.get("title") or "")
        sport_type = str(entry.get("sport_type") or entry.get("type") or "")
        has_kudoed = bool(entry.get("has_kudoed") or entry.get("kudoed_by_me"))

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

    # ── Strategy 3: last-resort HTML scraping ─────────────────────────────────

    def _scrape_html(self, html: str) -> list[Activity]:
        """Last-resort HTML scraping. Returns empty list with a warning if nothing found."""
        log.warning(
            "Could not extract feed data from embedded JSON. "
            "Strava's feed format may have changed. "
            "Returning 0 activities. Try a Dry-Run to diagnose."
        )
        return []


class AuthError(Exception):
    """Raised when Strava returns a login redirect (cookie expired)."""
