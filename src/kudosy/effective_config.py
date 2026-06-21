"""Pure three-layer effective-config merge.

Priority (highest → lowest):
  1. User per-sport rules  (from config.yaml kudoRules)
  2. Default per-sport rules (from defaults.yaml kudoRules)
  3. Catch-all rule (from defaults.yaml catchAll) expanded over every sport type

Setting a value to 0 explicitly removes a rule for a sport type, even if a
higher-level rule would otherwise apply.  activityNames is the order-preserving
dedup-union of defaults + user names.
"""

from __future__ import annotations

from kudosy.models import Defaults, EffectiveConfig, KudoRules, UserConfig
from kudosy.sport_types import ALL_SPORT_TYPES


def build_effective_config(
    user: UserConfig | None,
    defaults: Defaults,
) -> EffectiveConfig:
    """Merge user config + defaults into the effective config for the engine."""
    catch_all = defaults.catchAll
    default_rules = defaults.kudoRules
    user_rules = user.kudoRules if user else KudoRules()

    min_distance: dict[str, float] = {}
    min_time: dict[str, float] = {}

    # Step 1: expand catch-all over all known sport types (only when > 0)
    if catch_all.minDistance > 0:
        for sport in ALL_SPORT_TYPES:
            min_distance[sport] = catch_all.minDistance
    if catch_all.minTime > 0:
        for sport in ALL_SPORT_TYPES:
            min_time[sport] = catch_all.minTime

    # Step 2: overlay default per-sport rules (> 0 sets; 0 removes)
    for sport, val in default_rules.minDistance.items():
        if val > 0:
            min_distance[sport] = val
        else:
            min_distance.pop(sport, None)
    for sport, val in default_rules.minTime.items():
        if val > 0:
            min_time[sport] = val
        else:
            min_time.pop(sport, None)

    # Step 3: overlay user per-sport rules (highest priority)
    for sport, val in user_rules.minDistance.items():
        if val > 0:
            min_distance[sport] = val
        else:
            min_distance.pop(sport, None)
    for sport, val in user_rules.minTime.items():
        if val > 0:
            min_time[sport] = val
        else:
            min_time.pop(sport, None)

    # activityNames: order-preserving dedup-union (defaults first, then user additions)
    seen: set[str] = set()
    activity_names: list[str] = []
    for name in [*default_rules.activityNames, *user_rules.activityNames]:
        if name not in seen:
            seen.add(name)
            activity_names.append(name)

    return EffectiveConfig(
        stravaSessionCookie=user.stravaSessionCookie if user else "",
        athleteId=user.athleteId if user else "",
        ignoreAthletes=user.ignoreAthletes if user else [],
        allowAthletes=user.allowAthletes if user else [],
        kudoRules=KudoRules(
            minDistance=min_distance,
            minTime=min_time,
            activityNames=activity_names,
        ),
    )
