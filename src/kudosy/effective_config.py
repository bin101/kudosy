"""Pure three-layer effective-config merge.

Priority (highest → lowest):
  1. User per-sport rules  (from config.yaml kudoRules, sport-type keys)
  2. User per-category rules (from config.yaml kudoRules, Strava-category keys,
     e.g. "CycleSports") — expanded to all member sport types
  3. Catch-all rule (from config.yaml catchAll) expanded over every sport type

Setting a value to 0 explicitly removes a rule for a sport type, even if a
higher-priority layer would otherwise apply.

Category keys (e.g. "CycleSports", "FootSports") are resolved to their member
sport types during the merge; the resulting EffectiveConfig contains only
sport-type keys.  activityNames is taken directly from the user config (no union
— there is only one layer).
"""

from __future__ import annotations

from kudosy.models import EffectiveConfig, KudoRules, UserConfig
from kudosy.sport_types import ALL_SPORT_TYPES, CATEGORY_IDS, sports_in_category


def _apply_rules(
    target: dict[str, float],
    items: dict[str, float],
    *,
    category_keys_only: bool,
) -> None:
    """Apply a subset of *items* to *target* in place.

    When *category_keys_only* is True, only category-ID keys are processed and
    each is expanded to all member sport types.  When False, only non-category
    keys (individual sport types) are processed.

    A value of 0 removes the entry from *target* (explicit opt-out).
    """
    for key, val in items.items():
        if category_keys_only:
            if key not in CATEGORY_IDS:
                continue
            for sport in sports_in_category(key):
                if val > 0:
                    target[sport] = val
                else:
                    target.pop(sport, None)
        else:
            if key in CATEGORY_IDS:
                continue
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

    # Layer 1: expand catch-all over all known sport types (only when > 0)
    if catch_all and catch_all.minDistance > 0:
        for sport in ALL_SPORT_TYPES:
            min_distance[sport] = catch_all.minDistance
    if catch_all and catch_all.minTime > 0:
        for sport in ALL_SPORT_TYPES:
            min_time[sport] = catch_all.minTime

    # Layer 2: expand category-keys from user rules (override catch-all per member sport)
    _apply_rules(min_distance, user_rules.minDistance, category_keys_only=True)
    _apply_rules(min_time, user_rules.minTime, category_keys_only=True)

    # Layer 3: per-sport-type keys (highest priority; override category and catch-all)
    _apply_rules(min_distance, user_rules.minDistance, category_keys_only=False)
    _apply_rules(min_time, user_rules.minTime, category_keys_only=False)

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
