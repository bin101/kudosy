"""Pure three-layer effective-config merge.

Priority (highest → lowest):
  1. User per-sport rules        (kudoRules.minDistance / minTime)
  2. User category rules         (kudoRules.categoryMinDistance / minTime),
                                  expanded over each category's member sports
  3. Catch-all rule              (catchAll.*), expanded over every sport type

At every layer: value > 0 SETS the rule, value == 0 REMOVES (pops) it.
A category 0 removes catch-all-set rules for that category's members; a
per-sport 0 removes whatever any lower layer set for that single sport.

activityNames is taken directly from the user config (single layer, no merge).
Category dicts are NOT copied onto the effective layer — they are fully
expanded into the flat per-sport dicts here.
"""

from __future__ import annotations

from kudosy.models import EffectiveConfig, KudoRules, UserConfig
from kudosy.sport_types import ALL_SPORT_TYPES, sports_in_category


def _apply_layer(target: dict[str, float], updates: dict[str, float]) -> None:
    """Apply one merge layer in-place: value > 0 sets, value == 0 removes."""
    for key, val in updates.items():
        if val > 0:
            target[key] = val
        else:
            target.pop(key, None)


def build_effective_config(
    user: UserConfig | None,
) -> EffectiveConfig:
    """Merge user config into the effective config for the engine."""
    catch_all = user.catchAll if user else None
    user_rules = user.kudoRules if user else KudoRules()

    min_distance: dict[str, float] = {}
    min_time: dict[str, float] = {}

    # ── Layer 3 (lowest): catch-all over every known sport type (only when > 0) ──
    if catch_all and catch_all.minDistance > 0:
        for sport in ALL_SPORT_TYPES:
            min_distance[sport] = catch_all.minDistance
    if catch_all and catch_all.minTime > 0:
        for sport in ALL_SPORT_TYPES:
            min_time[sport] = catch_all.minTime

    # ── Layer 2: category rules, expanded over each category's member sports ──
    # A category value of 0 removes any catch-all-set rule for its members.
    for category, val in user_rules.categoryMinDistance.items():
        _apply_layer(min_distance, {s: val for s in sports_in_category(category)})
    for category, val in user_rules.categoryMinTime.items():
        _apply_layer(min_time, {s: val for s in sports_in_category(category)})

    # ── Layer 1 (highest): per-sport rules ──
    _apply_layer(min_distance, user_rules.minDistance)
    _apply_layer(min_time, user_rules.minTime)

    return EffectiveConfig(
        stravaSessionCookie=user.stravaSessionCookie if user else "",
        athleteId=user.athleteId if user else "",
        ignoreAthletes=user.ignoreAthletes if user else [],
        allowAthletes=user.allowAthletes if user else [],
        kudoRules=KudoRules(
            minDistance=min_distance,
            minTime=min_time,
            # Category dicts intentionally left empty on the effective layer —
            # they have already been expanded into the flat per-sport dicts above.
            activityNames=user_rules.activityNames,
        ),
    )
