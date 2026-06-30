"""Pure decision logic — given an activity and effective config, decide whether to give kudos.

Precedence (highest → lowest):
  1. Athlete in ignoreAthletes → SKIP (IGNORE)
  2. has_kudoed == True        → SKIP (ALREADY)
  3. Athlete in allowAthletes  → GIVE (ALLOW) — overrides distance/time criteria
  4. activity name matches a regex → GIVE (NAME_MATCH) — overrides thresholds
  5. Sport type has no effective rule → SKIP (NO_RULE) — rule-gating (always active)
  6. Stats below minDistance or minTime for sport type → SKIP (CRITERIA)
  7. Default → GIVE (DEFAULT)

Rule-gating (step 5): kudos are given only when the sport type has at least one
effective Distance or Duration rule, regardless of whether it comes from a
per-sport rule, a category rule, or a catchAll rule (all three sources collapse
into the same flat per-sport dicts after build_effective_config, so a single
dict lookup captures all sources).

Note on missing stats: If a rule (e.g. minDistance) exists for a sport type
but the activity has no Distance stat, the rule is treated as not violated
(we give kudos). This mirrors upstream behavior where time-only activities
like WeightTraining still receive kudos when only a minTime rule exists but no
time is recorded.
"""

from __future__ import annotations

import logging
import re

from kudosy.models import Activity, Decision, DecisionReason, EffectiveConfig

log = logging.getLogger(__name__)

_GIVE = True
_SKIP = False


def _check_name_match(activity_name: str, patterns: list[str]) -> bool:
    """Return True if the activity name matches any pattern via re.search."""
    for pattern in patterns:
        try:
            if re.search(pattern, activity_name):
                return True
        except re.error:
            log.warning("Invalid regex pattern %r — skipping", pattern)
    return False


def _has_rule(sport: str, eff: EffectiveConfig) -> bool:
    """Return True when *sport* has at least one effective Distance OR Duration rule.

    After build_effective_config, catchAll / category / per-sport rules are all
    collapsed into the flat per-sport dicts — a single dict lookup per metric
    captures all three sources.  A rule "counts" only when its value is > 0
    (the merge never stores non-positive values, so presence in the dict already
    implies > 0; the explicit check is a defensive guard).
    """
    dist = eff.kudoRules.minDistance.get(sport)
    if dist is not None and dist > 0:
        return True
    time = eff.kudoRules.minTime.get(sport)
    return time is not None and time > 0


def _check_criteria(activity: Activity, eff: EffectiveConfig) -> bool:
    """Return True when the activity fails the distance or time threshold.

    'Fails' means: a rule exists AND the measured value is below the threshold.
    Missing stat → treat as not failing (return False = does not fail criteria).

    Reads typed numeric values directly from ActivityStats — no string reparsing.
    For time we prefer moving_time_s; elapsed_time_s is the fallback (always
    present as a clean int from the feed's activity.elapsedTime field).
    """
    sport = activity.sport_type
    stats = activity.stats

    # --- minDistance check ---
    min_dist_km = eff.kudoRules.minDistance.get(sport)
    if (
        min_dist_km is not None
        and min_dist_km > 0
        and stats.distance_m is not None
        and stats.distance_m < min_dist_km * 1000
    ):
        return True  # fails criteria

    # --- minTime check ---
    min_time_min = eff.kudoRules.minTime.get(sport)
    if min_time_min is not None and min_time_min > 0:
        time_s = stats.moving_time_s if stats.moving_time_s is not None else stats.elapsed_time_s
        if time_s is not None and time_s < min_time_min * 60:
            return True  # fails criteria

    return False


def decide(activity: Activity, eff: EffectiveConfig) -> Decision:
    """Decide whether to give kudos for *activity* given *eff*.

    Returns a :class:`Decision` with ``give_kudos`` and ``reason``.
    """
    # 1. Ignore list (highest precedence)
    if activity.athlete_id in eff.ignoreAthletes:
        return Decision(give_kudos=_SKIP, reason=DecisionReason.IGNORE)

    # 2. Already kudoed
    if activity.has_kudoed:
        return Decision(give_kudos=_SKIP, reason=DecisionReason.ALREADY)

    # 3. Allow list → always give kudos (overrides distance/time criteria)
    if activity.athlete_id in eff.allowAthletes:
        return Decision(give_kudos=_GIVE, reason=DecisionReason.ALLOW)

    # 4. Name match → always give kudos (before criteria check)
    if eff.kudoRules.activityNames and _check_name_match(
        activity.activity_name, eff.kudoRules.activityNames
    ):
        return Decision(give_kudos=_GIVE, reason=DecisionReason.NAME_MATCH)

    # 5. Rule-gating: sport type must have at least one effective rule
    if not _has_rule(activity.sport_type, eff):
        return Decision(give_kudos=_SKIP, reason=DecisionReason.NO_RULE)

    # 6. Stats criteria
    if _check_criteria(activity, eff):
        return Decision(give_kudos=_SKIP, reason=DecisionReason.CRITERIA)

    # 7. Default → give kudos
    return Decision(give_kudos=_GIVE, reason=DecisionReason.DEFAULT)
