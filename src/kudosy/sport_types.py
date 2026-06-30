"""Strava SportType enum and category groupings — public API, not upstream-proprietary.

Hardcoded list mirrors https://developers.strava.com/swagger/sport_type.json
(SportType.enum), kept as a fallback when the live endpoint is unavailable.

Categories follow Strava's official grouping from
https://support.strava.com/hc/en-us/articles/216919407-Supported-Sport-Types-on-Strava
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

_SWAGGER_URL = "https://developers.strava.com/swagger/sport_type.json"

# ── Category groupings ────────────────────────────────────────────────────────
# Based on Strava's official sport-type help page (see module docstring).
# OtherSports is a named catch-all for the remaining hardcoded sport types.
# Live-fetched sport types not present in any category are implicitly treated
# as OtherSports by category_of(), but are NOT added to SPORT_CATEGORIES["OtherSports"].

SPORT_CATEGORIES: dict[str, list[str]] = {
    "FootSports": [
        "Hike",
        "Run",
        "TrailRun",
        "VirtualRun",
        "Walk",
        "Wheelchair",
    ],
    "CycleSports": [
        "EBikeRide",
        "EMountainBikeRide",
        "GravelRide",
        "Handcycle",
        "IndoorCycling",  # legacy ActivityType kept for backward compat
        "MountainBikeRide",
        "Ride",
        "Velomobile",
        "VirtualRide",
    ],
    "WaterSports": [
        "Canoeing",
        "Kayaking",
        "Kitesurf",
        "Rowing",
        "Sail",
        "StandUpPaddling",
        "Surfing",
        "Swim",
        "VirtualRow",
        "Windsurf",
    ],
    "WinterSports": [
        "AlpineSki",
        "BackcountrySki",
        "IceSkate",
        "NordicSki",
        "Snowboard",
        "Snowshoe",
    ],
    "OtherSports": [
        "Badminton",
        "Basketball",
        "Cricket",
        "Crossfit",
        "Dance",
        "Elliptical",
        "Golf",
        "HighIntensityIntervalTraining",
        "InlineSkate",
        "Padel",
        "PhysicalTherapy",
        "Pickleball",
        "Pilates",
        "Racquetball",
        "RockClimbing",
        "RollerSki",
        "Skateboard",
        "Soccer",
        "Squash",
        "StairStepper",
        "TableTennis",
        "Tennis",
        "Volleyball",
        "WeightTraining",
        "Workout",
        "Yoga",
    ],
}

# Frozenset of category IDs — used to distinguish category keys from sport-type keys.
CATEGORY_IDS: frozenset[str] = frozenset(SPORT_CATEGORIES)

# Reverse lookup: sport type → category ID (built once at module load).
_SPORT_TO_CATEGORY: dict[str, str] = {
    sport: cat for cat, sports in SPORT_CATEGORIES.items() for sport in sports
}


def category_of(sport: str) -> str:
    """Return the category ID for *sport*, defaulting to 'OtherSports' for unknowns."""
    return _SPORT_TO_CATEGORY.get(sport, "OtherSports")


def sports_in_category(category: str) -> list[str]:
    """Return the list of sport types belonging to *category*. Empty list for unknown category."""
    return list(SPORT_CATEGORIES.get(category, []))


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
