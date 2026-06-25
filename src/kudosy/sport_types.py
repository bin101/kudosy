"""Strava SportType enum — public API, not upstream-proprietary.

Hardcoded list mirrors https://developers.strava.com/swagger/sport_type.json
(SportType.enum), kept as a fallback when the live endpoint is unavailable.
"""

from __future__ import annotations

import logging

import httpx

log = logging.getLogger(__name__)

ALL_SPORT_TYPES: list[str] = [
    "AlpineSki",
    "BackcountrySki",
    "Badminton",
    "Basketball",
    "Canoeing",
    "Cricket",
    "Crossfit",
    "Dance",
    "EBikeRide",
    "Elliptical",
    "EMountainBikeRide",
    "Golf",
    "GravelRide",
    "Handcycle",
    "HighIntensityIntervalTraining",
    "Hike",
    "IceSkate",
    "IndoorCycling",  # legacy ActivityType kept for backward compat
    "InlineSkate",
    "Kayaking",
    "Kitesurf",
    "MountainBikeRide",
    "NordicSki",
    "Padel",
    "PhysicalTherapy",
    "Pickleball",
    "Pilates",
    "Racquetball",
    "Ride",
    "RockClimbing",
    "RollerSki",
    "Rowing",
    "Run",
    "Sail",
    "Skateboard",
    "Snowboard",
    "Snowshoe",
    "Soccer",
    "Squash",
    "StairStepper",
    "StandUpPaddling",
    "Surfing",
    "Swim",
    "TableTennis",
    "Tennis",
    "TrailRun",
    "Velomobile",
    "VirtualRide",
    "VirtualRow",
    "VirtualRun",
    "Volleyball",
    "Walk",
    "WeightTraining",
    "Wheelchair",
    "Windsurf",
    "Workout",
    "Yoga",
]

# Parent → child sport-type inheritance map.
# When a user configures a rule for a parent (e.g. "Ride"), that rule is
# automatically inherited by all children that don't have their own explicit rule.
# Children can override with a more specific value, or set 0 to opt out entirely.
SPORT_PARENTS: dict[str, list[str]] = {
    "Ride": [
        "VirtualRide",
        "GravelRide",
        "MountainBikeRide",
        "EBikeRide",
        "EMountainBikeRide",
        "Velomobile",
        "IndoorCycling",
    ],
    "Run": ["TrailRun", "VirtualRun"],
    "Rowing": ["VirtualRow"],
}

_SWAGGER_URL = "https://developers.strava.com/swagger/sport_type.json"


def merge_sport_types(live: list[str], hardcoded: list[str]) -> list[str]:
    """Merge live + hardcoded lists: live list first, append any legacy extras."""
    live_set = set(live)
    extras = [t for t in hardcoded if t not in live_set]
    return [*live, *extras]


async def fetch_sport_types(client: httpx.AsyncClient) -> list[str] | None:
    """Fetch the live SportType enum from the Strava swagger spec.

    Returns None (caller falls back to ALL_SPORT_TYPES) on any error.
    """
    try:
        resp = await client.get(_SWAGGER_URL, timeout=5.0)
        if not resp.is_success:
            return None
        data = resp.json()
        lst: list[str] | None = None
        if isinstance(data, list):
            lst = data
        elif isinstance(data, dict):
            sport_type = data.get("SportType", {})
            enum_val = sport_type.get("enum") if isinstance(sport_type, dict) else None
            if isinstance(enum_val, list):
                lst = enum_val
            elif isinstance(data.get("enum"), list):
                lst = data["enum"]
        if lst and len(lst) > 0:
            return lst
        return None
    except Exception:
        log.debug("Failed to fetch live sport types; using hardcoded fallback", exc_info=True)
        return None
