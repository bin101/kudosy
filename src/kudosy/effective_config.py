"""Pure three-layer effective-config merge.

Priority (highest → lowest):
  1. User per-sport rules  (from config.yaml kudoRules)
  2. Category inheritance  (e.g. CycleSports → all cycle sport types)
  3. Catch-all rule (from config.yaml catchAll) expanded over every sport type

Setting a value to 0 explicitly removes a rule for a sport type, even if the
catch-all or category would otherwise apply.  activityNames is taken directly
from the user config (no union needed — there is only one layer).
"""

from __future__ import annotations

from kudosy.models import EffectiveConfig, KudoRules, UserConfig
from kudosy.sport_types import ALL_SPORT_TYPES, SPORT_CATEGORIES, category_members


def build_effective_config(
    user: UserConfig | None,
) -> EffectiveConfig:
    """Merge user config into the effective config for the engine."""
    catch_all = user.catchAll if user else None
    user_rules = user.kudoRules if user else KudoRules()

    min_distance: dict[str, float] = {}
    min_time: dict[str, float] = {}

    # Step 1: expand catch-all over all known sport types (only when > 0)
    if catch_all and catch_all.minDistance > 0:
        for sport in ALL_SPORT_TYPES:
            min_distance[sport] = catch_all.minDistance
    if catch_all and catch_all.minTime > 0:
        for sport in ALL_SPORT_TYPES:
            min_time[sport] = catch_all.minTime

    # Step 1.2: inherit category rules to all members without their own explicit rule.
    #   Priority: catchAll → category → per-sport (lowest → highest).
    #   Only explicit user_rules entries trigger inheritance (not catchAll-expanded values).
    for cat_key in SPORT_CATEGORIES:
        c_dist = user_rules.minDistance.get(cat_key)
        if c_dist and c_dist > 0:
            for member in category_members(cat_key, ALL_SPORT_TYPES):
                if member not in user_rules.minDistance:
                    min_distance[member] = c_dist
        c_time = user_rules.minTime.get(cat_key)
        if c_time and c_time > 0:
            for member in category_members(cat_key, ALL_SPORT_TYPES):
                if member not in user_rules.minTime:
                    min_time[member] = c_time

    # Step 2: overlay user per-sport rules (highest priority; > 0 sets, 0 removes).
    #   Category keys (e.g. "CycleSports") are skipped — they are pseudo-entries
    #   that drive inheritance only and must not appear in the final effective rules.
    for sport, val in user_rules.minDistance.items():
        if sport in SPORT_CATEGORIES:
            continue
        if val > 0:
            min_distance[sport] = val
        else:
            min_distance.pop(sport, None)
    for sport, val in user_rules.minTime.items():
        if sport in SPORT_CATEGORIES:
            continue
        if val > 0:
            min_time[sport] = val
        else:
            min_time.pop(sport, None)

    return EffectiveConfig(
        stravaSessionCookie=user.stravaSessionCookie if user else "",
        athleteId=user.athleteId if user else "",
        ignoreAthletes=user.ignoreAthletes if user else [],
        allowAthletes=user.allowAthletes if user else [],
        kudoRules=KudoRules(
            minDistance=min_distance,
            minTime=min_time,
            activityNames=user_rules.activityNames,
        ),
    )
