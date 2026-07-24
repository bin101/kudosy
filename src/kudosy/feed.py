"""Feed parsing — the brittleness firewall.

All Strava response-format assumptions live here and ONLY here.
Everything downstream consumes the normalised list[Activity].

The FeedParser Protocol ensures the engine stays testable with fake parsers.

Feed format (verified 2026-06-30 via HAR capture):
  The following feed is a JSON XHR endpoint::

      GET /dashboard/feed?feed_type=following&athlete_id=<id>
      Accept: application/json, X-Requested-With: XMLHttpRequest

  Response structure::

      {
        "entries": [
          {
            "entity": "Activity",   # only this type is processed
            "activity": {
              "id": "12345678901",
              "activityName": "Morning Run",
              "type": "Run",
              "startDate": "2026-06-29T18:38:41Z",
              "elapsedTime": 2519,
              "athlete": {"athleteId": "…", "athleteName": "…", "avatarUrl": "…"},
              "kudosAndComments": {"hasKudoed": true, "canKudo": false, "kudosCount": 3},
              "timeAndLocation": {"location": "…", …},
              "isCommute": false, "isVirtual": false, "deviceName": "…",
              "stats": [
                {"key": "stat_one", "value": "5.17<abbr …> km</abbr>", "value_object": null},
                {"key": "stat_one_subtitle", "value": "Distance", "value_object": null},
                …up to stat_three / stat_three_subtitle…
              ]
            }
          },
          {"entity": "Challenge", …},   # skipped
          {"entity": "AthleteFeedEntry", …},  # skipped
        ],
        "pagination": {"hasMore": true}
      }
"""

from __future__ import annotations

import contextlib
import logging
from datetime import datetime
from typing import Any, Protocol

from kudosy.models import Activity, ActivityStats, StatValue
from kudosy.stat_parse import (
    classify_stat,
    parse_distance,
    parse_duration,
    parse_elevation,
    parse_pace_km,
    parse_swim_pace,
    strip_unit_markup,
)

log = logging.getLogger(__name__)

# ── Protocol ──────────────────────────────────────────────────────────────────


class FeedParser(Protocol):
    """Parse a raw Strava feed payload into a list of Activity objects."""

    def parse(self, payload: dict[str, Any]) -> list[Activity]:
        """Parse *payload* (the JSON dict from ``/dashboard/feed``) and return activities.

        Implementations must:
        - Skip unparseable entries (log WARN, do not raise).
        - Return an empty list rather than raising on total failure.
        """
        ...


# ── Concrete parser ───────────────────────────────────────────────────────────


class StructuredFeedParser:
    """Parse the JSON following-feed response from ``/dashboard/feed``.

    Accepts the decoded JSON dict (``{"entries": […], "pagination": {…}}``) and
    returns a normalised ``list[Activity]`` with typed ``ActivityStats``.

    Only ``entity == "Activity"`` entries are processed; ``Challenge``,
    ``AthleteFeedEntry`` and any other types are silently skipped.
    """

    def parse(self, payload: dict[str, Any]) -> list[Activity]:
        """Parse a feed JSON dict and return normalised activities."""
        if not isinstance(payload, dict):
            log.warning(
                "StructuredFeedParser: expected a dict, got %s — returning []",
                type(payload).__name__,
            )
            return []

        entries = payload.get("entries", [])
        if not isinstance(entries, list):
            log.warning("StructuredFeedParser: 'entries' is not a list — returning []")
            return []

        results: list[Activity] = []
        for entry in entries:
            try:
                if not isinstance(entry, dict) or entry.get("entity") != "Activity":
                    continue
                act_data = entry.get("activity")
                if not isinstance(act_data, dict):
                    continue
                act = self._parse_activity(act_data)
                if act is not None:
                    results.append(act)
            except Exception:
                log.warning(
                    "StructuredFeedParser: failed to parse entry %r",
                    str(entry)[:200],
                    exc_info=True,
                )

        log.debug(
            "StructuredFeedParser: parsed %d activities from %d entries",
            len(results),
            len(entries),
        )
        return results

    # ── Internal helpers ──────────────────────────────────────────────────────

    def _parse_activity(self, data: dict[str, Any]) -> Activity | None:
        """Parse a single activity JSON object into a typed Activity."""
        activity_id = str(data.get("id") or "").strip()
        if not activity_id:
            return None

        activity_name = str(data.get("activityName") or "").replace("\n", " ").strip()
        sport_type = str(data.get("type") or data.get("sportType") or "")

        ath = data.get("athlete") or {}
        athlete_id = str(ath.get("athleteId") or "")
        athlete_name = str(ath.get("athleteName") or "Unknown")
        athlete_avatar_url: str | None = ath.get("avatarUrl") or None

        kk = data.get("kudosAndComments") or {}
        has_kudoed = bool(kk.get("hasKudoed"))
        can_kudo = bool(kk.get("canKudo", True))
        kudos_count = int(kk.get("kudosCount") or 0)

        tl = data.get("timeAndLocation") or {}
        location: str | None = tl.get("location") or None

        start_date: datetime | None = None
        raw_date = data.get("startDate")
        if raw_date:
            with contextlib.suppress(ValueError):
                start_date = datetime.fromisoformat(str(raw_date).replace("Z", "+00:00"))

        elapsed_raw = data.get("elapsedTime")
        elapsed_time_s: int | None = int(elapsed_raw) if elapsed_raw is not None else None

        is_commute = bool(data.get("isCommute"))
        is_virtual = bool(data.get("isVirtual"))
        device_name: str | None = data.get("deviceName") or None

        stats = self._parse_stats(data.get("stats") or [], elapsed_time_s=elapsed_time_s)
        if stats.display and all(sv.key == "unknown" for sv in stats.display):
            # Every stat item was present but none matched a known label — a
            # strong signal that Strava changed its label format (localisation,
            # rename) rather than this particular activity being unusual.
            log.warning(
                "Activity %s (%s): %d stat(s) present but none classified — "
                "Strava's stat label format may have changed",
                activity_id,
                sport_type or "unknown sport",
                len(stats.display),
            )

        return Activity(
            activity_id=activity_id,
            activity_name=activity_name,
            sport_type=sport_type,
            athlete_id=athlete_id,
            athlete_name=athlete_name,
            athlete_avatar_url=athlete_avatar_url,
            has_kudoed=has_kudoed,
            can_kudo=can_kudo,
            kudos_count=kudos_count,
            start_date=start_date,
            location=location,
            is_commute=is_commute,
            is_virtual=is_virtual,
            device_name=device_name,
            stats=stats,
        )

    def _parse_stats(
        self,
        raw_stats: list[Any],
        *,
        elapsed_time_s: int | None,
    ) -> ActivityStats:
        """Build an ActivityStats from the activity's ``stats`` list.

        The feed delivers stat pairs::

            {"key": "stat_one",          "value": "5.17 km"}
            {"key": "stat_one_subtitle", "value": "Distance"}

        We collect value items and subtitle items in two passes, then combine.
        elapsed_time_s (from activity.elapsedTime) is always a clean int and is
        stored directly on the result even when the feed's "Time" stat is absent.
        """
        # Pass 1: collect value items and subtitles separately.
        value_items: list[tuple[str, str]] = []  # (machine_key, raw_value)
        subtitle_map: dict[str, str] = {}  # machine_key → human label

        for item in raw_stats:
            if not isinstance(item, dict):
                continue
            key = str(item.get("key") or "")
            value = str(item.get("value") or "")
            if not key or not value:
                continue
            if key.endswith("_subtitle"):
                subtitle_map[key[: -len("_subtitle")]] = value
            else:
                value_items.append((key, value))

        # Pass 2: pair values with their subtitles and parse.
        distance_m: float | None = None
        moving_time_s: int | None = None
        elevation_gain_m: float | None = None
        pace_s_per_km: float | None = None
        pace_s_per_100m: float | None = None
        extra: dict[str, str] = {}
        display: list[StatValue] = []

        for machine_key, raw_value in value_items:
            label = subtitle_map.get(machine_key) or machine_key
            cleaned = strip_unit_markup(raw_value) or raw_value
            canonical_key = classify_stat(label, raw_value)

            numeric_value: float | None = None
            unit: str | None = None

            if canonical_key == "distance":
                numeric_value = parse_distance(raw_value)
                unit = "m"
                if numeric_value is not None:
                    distance_m = numeric_value

            elif canonical_key == "time":
                parsed_s = parse_duration(raw_value)
                numeric_value = float(parsed_s) if parsed_s is not None else None
                unit = "s"
                if parsed_s is not None:
                    moving_time_s = parsed_s

            elif canonical_key == "elevation_gain":
                numeric_value = parse_elevation(raw_value)
                unit = "m"
                if numeric_value is not None:
                    elevation_gain_m = numeric_value

            elif canonical_key == "pace":
                numeric_value = parse_pace_km(raw_value)
                unit = "s/km"
                if numeric_value is not None:
                    pace_s_per_km = numeric_value

            elif canonical_key == "swim_pace":
                numeric_value = parse_swim_pace(raw_value)
                unit = "s/100m"
                if numeric_value is not None:
                    pace_s_per_100m = numeric_value

            elif canonical_key == "unknown":
                extra[label] = cleaned

            display.append(
                StatValue(
                    key=canonical_key,
                    label=label,
                    raw=cleaned,
                    value=numeric_value,
                    unit=unit if numeric_value is not None else None,
                )
            )

        return ActivityStats(
            distance_m=distance_m,
            moving_time_s=moving_time_s,
            elapsed_time_s=elapsed_time_s,
            elevation_gain_m=elevation_gain_m,
            pace_s_per_km=pace_s_per_km,
            pace_s_per_100m=pace_s_per_100m,
            extra=extra,
            display=display,
        )


# ── Auth error ────────────────────────────────────────────────────────────────


class AuthError(Exception):
    """Raised when Strava returns a login redirect (cookie expired).

    The ``code`` attribute is set to a machine-readable error code
    (e.g. ``AUTH_INVALID_COOKIE``) that the frontend can translate.
    """

    code: str = "AUTH_FAILED"


class RateLimitError(Exception):
    """Raised when Strava answers with HTTP 429 (rate limited).

    The engine aborts the remaining kudos of the current run; the next
    scheduled run retries naturally.
    """

    code: str = "RATE_LIMITED"
