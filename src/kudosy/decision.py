"""Pure decision logic — given an activity and effective config, decide whether to give kudos.

Precedence (highest → lowest):
  1. Athlete in ignoreAthletes → SKIP (IGNORE)
  2. has_kudoed == True        → SKIP (ALREADY)
  3. activity name matches a regex → GIVE (NAME_MATCH) — overrides thresholds
  4. Stats below minDistance or minTime for sport type → SKIP (CRITERIA)
  5. Default → GIVE (DEFAULT)

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
from kudosy.parsers import parse_distance, parse_duration

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


def _check_criteria(activity: Activity, eff: EffectiveConfig) -> bool:
    """Return True when the activity fails the distance or time threshold.

    'Fails' means: a rule exists AND the measured value is below the threshold.
    Missing stat → treat as not failing (return False = does not fail criteria).
    """
    sport = activity.sport_type
    stats = activity.stats

    # --- minDistance check ---
    min_dist_km = eff.kudoRules.minDistance.get(sport)
    if min_dist_km is not None and min_dist_km > 0:
        dist_str = stats.get("Distance")
        if dist_str is not None:
            dist_m = parse_distance(dist_str)
            if dist_m is not None and dist_m < min_dist_km * 1000:
                return True  # fails criteria

    # --- minTime check ---
    min_time_min = eff.kudoRules.minTime.get(sport)
    if min_time_min is not None and min_time_min > 0:
        time_str = stats.get("Time")
        if time_str is not None:
            dur_s = parse_duration(time_str)
            if dur_s is not None and dur_s < min_time_min * 60:
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

    # 3. Name match → always give kudos (before criteria check)
    if eff.kudoRules.activityNames and _check_name_match(
        activity.activity_name, eff.kudoRules.activityNames
    ):
        return Decision(give_kudos=_GIVE, reason=DecisionReason.NAME_MATCH)

    # 4. Stats criteria
    if _check_criteria(activity, eff):
        return Decision(give_kudos=_SKIP, reason=DecisionReason.CRITERIA)

    # 5. Default → give kudos
    return Decision(give_kudos=_GIVE, reason=DecisionReason.DEFAULT)
