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

# Strava's five official top-level sport categories (source: support.strava.com).
# Maps category ID → list of sport types in that category.
#
# Deliberate deviation from Strava's own list: RollerSki is placed under
# WinterSports (not OtherSports) so it stays adjacent to its parent NordicSki
# in the dropdown and rule-inheritance UI.
SPORT_CATEGORIES: dict[str, list[str]] = {
    "FootSports": [
        "Run",
        "TrailRun",
        "VirtualRun",
        "Hike",
        "Walk",
        "Wheelchair",
    ],
    "CycleSports": [
        "Ride",
        "VirtualRide",
        "GravelRide",
        "MountainBikeRide",
        "EBikeRide",
        "EMountainBikeRide",
        "Velomobile",
        "IndoorCycling",
        "Handcycle",
    ],
    "WaterSports": [
        "Swim",
        "Rowing",
        "VirtualRow",
        "Canoeing",
        "Kayaking",
        "StandUpPaddling",
        "Surfing",
        "Kitesurf",
        "Windsurf",
        "Sail",
    ],
    "WinterSports": [
        "AlpineSki",
        "BackcountrySki",
        "NordicSki",
        "RollerSki",
        "IceSkate",
        "Snowboard",
        "Snowshoe",
    ],
    "OtherSports": [
        "Workout",
        "WeightTraining",
        "Crossfit",
        "HighIntensityIntervalTraining",
        "Elliptical",
        "StairStepper",
        "Yoga",
        "Pilates",
        "PhysicalTherapy",
        "RockClimbing",
        "InlineSkate",
        "Skateboard",
        "Golf",
        "Tennis",
        "TableTennis",
        "Badminton",
        "Squash",
        "Racquetball",
        "Padel",
        "Pickleball",
        "Basketball",
        "Volleyball",
        "Soccer",
        "Cricket",
        "Dance",
    ],
}


def category_members(category: str, all_sport_types: list[str]) -> list[str]:
    """Return all sport types that belong to *category* and are in *all_sport_types*.

    For ``OtherSports`` any sport type present in *all_sport_types* that is not
    assigned to any category is also included, providing robustness against future
    Strava sport types that haven't been categorised yet.
    """
    base = SPORT_CATEGORIES.get(category, [])
    all_types_set = set(all_sport_types)
    members = [t for t in base if t in all_types_set]
    if category == "OtherSports":
        known: set[str] = {s for ms in SPORT_CATEGORIES.values() for s in ms}
        extras = [t for t in all_sport_types if t not in known]
        members_set = set(members)
        members = members + [t for t in extras if t not in members_set]
    return members


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
