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

# ── Category mapping ──────────────────────────────────────────────────────────

# Five official Strava categories in display order.  Each value is an ordered
# list of sport types belonging to that category (Strava-official grouping).
# IndoorCycling is a legacy ActivityType kept in CycleSports for backward compat.
SPORT_CATEGORIES: dict[str, list[str]] = {
    "FootSports": [
        "Run",
        "TrailRun",
        "VirtualRun",
        "Walk",
        "Hike",
    ],
    "CycleSports": [
        "Ride",
        "MountainBikeRide",
        "GravelRide",
        "EBikeRide",
        "EMountainBikeRide",
        "Velomobile",
        "VirtualRide",
        "Handcycle",
        "IndoorCycling",  # legacy ActivityType
    ],
    "WaterSports": [
        "Canoeing",
        "Kayaking",
        "Kitesurf",
        "Rowing",
        "StandUpPaddling",
        "Surfing",
        "Swim",
        "Windsurf",
        "Sail",
        "VirtualRow",
    ],
    "WinterSports": [
        "AlpineSki",
        "BackcountrySki",
        "NordicSki",
        "Snowboard",
        "Snowshoe",
        "IceSkate",
    ],
    "OtherSports": [
        "RollerSki",
        "Crossfit",
        "Elliptical",
        "StairStepper",
        "WeightTraining",
        "Workout",
        "Yoga",
        "Pilates",
        "HighIntensityIntervalTraining",
        "PhysicalTherapy",
        "Golf",
        "InlineSkate",
        "RockClimbing",
        "Skateboard",
        "Wheelchair",
        "Badminton",
        "Basketball",
        "Cricket",
        "Dance",
        "Padel",
        "Pickleball",
        "Racquetball",
        "Soccer",
        "Squash",
        "TableTennis",
        "Tennis",
        "Volleyball",
    ],
}

# Canonical ordered list of the five category names.
CATEGORY_NAMES: list[str] = list(SPORT_CATEGORIES)

# Reverse index: sport type → category name.  Built once at import time.
# Unknown sports (e.g. newly added live types) map to "OtherSports".
_SPORT_TO_CATEGORY: dict[str, str] = {
    sport: cat for cat, sports in SPORT_CATEGORIES.items() for sport in sports
}


def category_for_sport(sport: str) -> str:
    """Return the Strava category for *sport*, defaulting to ``"OtherSports"``."""
    return _SPORT_TO_CATEGORY.get(sport, "OtherSports")


def sports_in_category(category: str) -> list[str]:
    """Return the static member list for *category* (empty list for unknown categories).

    Returns a copy — callers must not mutate the result.
    """
    members = SPORT_CATEGORIES.get(category)
    return list(members) if members is not None else []


def categorize_sport_types(active: list[str]) -> dict[str, list[str]]:
    """Group *active* sport types into the five official Strava categories.

    Sports not present in the static map are placed in ``"OtherSports"``.
    The order within each category follows *active*'s order.
    All five category keys are always emitted (empty list when no members active).
    """
    grouped: dict[str, list[str]] = {cat: [] for cat in CATEGORY_NAMES}
    for sport in active:
        grouped[category_for_sport(sport)].append(sport)
    return grouped


# ── Swagger fetch ──────────────────────────────────────────────────────────────

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
