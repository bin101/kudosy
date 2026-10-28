"""Pure decision logic — given an activity and effective config, decide whether to give kudos.

Precedence (highest → lowest):
  1. Athlete in ignoreAthletes → SKIP (IGNORE)
  2. has_kudoed == True        → SKIP (ALREADY)
  3. Athlete in allowAthletes  → GIVE (ALLOW) — overrides distance/time criteria
  4. activity name matches a regex → GIVE (NAME_MATCH) — overrides thresholds
  5. Sport type has no effective rule → SKIP (NO_RULE) — rule-gating (always active)
  6. Stats below minDistance or minTime for sport type → SKIP (CRITERIA)
  7. An active minDistance/minTime rule but no such value → SKIP (STAT_MISSING)
  8. Default → GIVE (DEFAULT)

Rule-gating (step 5): kudos are given only when the sport type has at least one
effective Distance or Duration rule, regardless of whether it comes from a
per-sport rule, a category rule, or a catchAll rule (all three sources collapse
into the same flat per-sport dicts after build_effective_config, so a single
dict lookup captures all sources).

Note on missing stats: if a rule (e.g. minDistance) is active for a sport type but
the activity has no such value, the rule cannot be verified and no kudos are given
(STAT_MISSING). Before this rule a missing value counted as "not violated", which
silently gave kudos to everything whenever Strava's stat labels stopped parsing.
Activities that legitimately have no distance (e.g. WeightTraining) therefore need
minDistance set to 0 for that sport or category (which removes a catch-all distance
rule there; add a minTime rule if wanted), an allow-list entry or a name match.
A catch-all minDistance skips such activities.
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


def _check_criteria(activity: Activity, eff: EffectiveConfig) -> DecisionReason | None:
    """Return why the activity fails the distance or time rules, or ``None`` if it passes.

    ``CRITERIA``: a rule is active and the measured value is below the threshold.
    ``STAT_MISSING``: a rule is active but the activity has no such value. A value
    that is present and too low wins over a missing one (more informative reason).

    Reads typed numeric values directly from ActivityStats — no string reparsing.
    For time we prefer moving_time_s; elapsed_time_s is the fallback (always
    present as a clean int from the feed's activity.elapsedTime field).
    """
    sport = activity.sport_type
    stats = activity.stats
    missing = False

    # --- minDistance check ---
    min_dist_km = eff.kudoRules.minDistance.get(sport)
    if min_dist_km is not None and min_dist_km > 0:
        if stats.distance_m is None:
            missing = True
        elif stats.distance_m < min_dist_km * 1000:
            return DecisionReason.CRITERIA

    # --- minTime check ---
    min_time_min = eff.kudoRules.minTime.get(sport)
    if min_time_min is not None and min_time_min > 0:
        time_s = stats.moving_time_s if stats.moving_time_s is not None else stats.elapsed_time_s
        if time_s is None:
            missing = True
        elif time_s < min_time_min * 60:
            return DecisionReason.CRITERIA

    return DecisionReason.STAT_MISSING if missing else None


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

    # 6. Stats criteria (below threshold, or an active rule without a value to check)
    failed = _check_criteria(activity, eff)
    if failed is not None:
        return Decision(give_kudos=_SKIP, reason=failed)

    # 7. Default → give kudos
    return Decision(give_kudos=_GIVE, reason=DecisionReason.DEFAULT)
