"""Unit tests for decision.py — pure filter logic.

Decision precedence (highest → lowest):
  ignore → already → allow → name_match → no_rule (gating) → criteria → default (give kudos)

Test corpus is derived from the real last-run.log to guarantee behavioral parity.
"""

from kudosy.decision import decide
from kudosy.effective_config import build_effective_config
from kudosy.models import Activity, ActivityStats, CatchAll, DecisionReason, KudoRules, UserConfig


def _eff(
    *,
    catch_min_dist: float = 0,
    catch_min_time: float = 0,
    per_dist: dict[str, float] | None = None,
    per_time: dict[str, float] | None = None,
    cat_dist: dict[str, float] | None = None,
    cat_time: dict[str, float] | None = None,
    names: list[str] | None = None,
    ignore: list[str] | None = None,
    allow: list[str] | None = None,
) -> object:
    """Build an EffectiveConfig via the real merge function."""
    user = UserConfig(
        stravaSessionCookie="x",
        athleteId="99",
        ignoreAthletes=ignore or [],
        allowAthletes=allow or [],
        catchAll=CatchAll(minDistance=catch_min_dist, minTime=catch_min_time),
        kudoRules=KudoRules(
            minDistance=per_dist or {},
            minTime=per_time or {},
            categoryMinDistance=cat_dist or {},
            categoryMinTime=cat_time or {},
            activityNames=names or [],
        ),
    )
    return build_effective_config(user)


def _act(
    *,
    athlete_id: str = "111",
    activity_id: str = "act001",
    activity_name: str = "Morning Ride",
    sport_type: str = "Ride",
    has_kudoed: bool = False,
    distance_m: float | None = None,
    moving_time_s: int | None = None,
    elapsed_time_s: int | None = None,
    elevation_gain_m: float | None = None,
    pace_s_per_km: float | None = None,
) -> Activity:
    """Build a minimal Activity with typed ActivityStats.

    Convenience params (distance_m, moving_time_s, etc.) populate ActivityStats
    directly — no string-parsing round-trip.
    """
    stats = ActivityStats(
        distance_m=distance_m,
        moving_time_s=moving_time_s,
        elapsed_time_s=elapsed_time_s,
        elevation_gain_m=elevation_gain_m,
        pace_s_per_km=pace_s_per_km,
    )
    return Activity(
        athlete_name="Test Athlete",
        athlete_id=athlete_id,
        activity_id=activity_id,
        activity_name=activity_name,
        sport_type=sport_type,
        has_kudoed=has_kudoed,
        stats=stats,
    )


class TestIgnoreList:
    """Athlete in ignore list → always skip, even if not yet kudoed."""

    def test_athlete_in_ignore_list(self) -> None:
        eff = _eff(ignore=["111"])
        act = _act(athlete_id="111")
        d = decide(act, eff)  # type: ignore[arg-type]
        assert d.give_kudos is False
        assert d.reason == DecisionReason.IGNORE

    def test_athlete_not_in_ignore_list(self) -> None:
        # Provide a catchAll rule so the activity passes the gate
        eff = _eff(ignore=["999"], catch_min_dist=1.0)
        act = _act(athlete_id="111", distance_m=30100.0)
        d = decide(act, eff)  # type: ignore[arg-type]
        # Not ignored and has a rule → give kudos
        assert d.give_kudos is True

    def test_ignore_takes_precedence_over_kudoed(self) -> None:
        """Even if already kudoed, ignore must fire — but in practice we won't re-kudo anyway."""
        eff = _eff(ignore=["111"])
        act = _act(athlete_id="111", has_kudoed=True)
        d = decide(act, eff)  # type: ignore[arg-type]
        assert d.reason == DecisionReason.IGNORE


class TestAlreadyKudoed:
    def test_already_kudoed_skipped(self) -> None:
        eff = _eff()
        act = _act(has_kudoed=True)
        d = decide(act, eff)  # type: ignore[arg-type]
        assert d.give_kudos is False
        assert d.reason == DecisionReason.ALREADY


class TestCriteriaSkip:
    """Activity stats do not meet criteria → skip."""

    def test_below_min_distance(self) -> None:
        # catch-all minDistance = 10 km = 10000 m; activity is 1.36 km = 1360 m
        eff = _eff(catch_min_dist=10)
        act = _act(sport_type="Ride", distance_m=1360.0)
        d = decide(act, eff)  # type: ignore[arg-type]
        assert d.give_kudos is False
        assert d.reason == DecisionReason.CRITERIA

    def test_below_min_time(self) -> None:
        # catch-all minTime = 45 min = 2700 s; activity is 5m 5s = 305 s
        eff = _eff(catch_min_time=45)
        act = _act(sport_type="Ride", moving_time_s=305)
        d = decide(act, eff)  # type: ignore[arg-type]
        assert d.give_kudos is False
        assert d.reason == DecisionReason.CRITERIA

    def test_below_min_time_via_elapsed_time(self) -> None:
        """When moving_time_s is absent, elapsed_time_s is used as fallback."""
        eff = _eff(catch_min_time=45)
        act = _act(sport_type="Run", elapsed_time_s=305)  # ~5 min, below 45
        d = decide(act, eff)  # type: ignore[arg-type]
        assert d.give_kudos is False
        assert d.reason == DecisionReason.CRITERIA

    def test_zero_duration_fails_time_criteria(self) -> None:
        # 0 s < 45 min threshold → skip
        eff = _eff(catch_min_time=45)
        act = _act(sport_type="Run", moving_time_s=0)
        d = decide(act, eff)  # type: ignore[arg-type]
        assert d.give_kudos is False

    def test_above_criteria_gives_kudos(self) -> None:
        # 30.10 km > 10 km threshold
        eff = _eff(catch_min_dist=10)
        act = _act(sport_type="Ride", distance_m=30100.0)
        d = decide(act, eff)  # type: ignore[arg-type]
        assert d.give_kudos is True

    def test_missing_distance_does_not_fail_criteria(self) -> None:
        """WeightTraining has no distance; a minDistance rule must not block it."""
        eff = _eff(catch_min_dist=10)
        act = _act(sport_type="WeightTraining", moving_time_s=2988)  # 49m 48s
        d = decide(act, eff)  # type: ignore[arg-type]
        # Missing distance → treat as "not failing" → give kudos
        assert d.give_kudos is True

    def test_missing_time_does_not_fail_time_criteria(self) -> None:
        """No time stat and no elapsed time → rule not violated."""
        eff = _eff(catch_min_time=45)
        act = _act(sport_type="Ride")  # no time at all
        d = decide(act, eff)  # type: ignore[arg-type]
        assert d.give_kudos is True


class TestNameMatch:
    """activityNames regex match → always give kudos, even below threshold."""

    def test_name_match_overrides_criteria(self) -> None:
        eff = _eff(catch_min_dist=10, names=["^Race"])
        # Only 1 km but name matches
        act = _act(activity_name="Race Day 5k", sport_type="Run", distance_m=1000.0)
        d = decide(act, eff)  # type: ignore[arg-type]
        assert d.give_kudos is True
        assert d.reason == DecisionReason.NAME_MATCH

    def test_name_no_match_falls_through(self) -> None:
        eff = _eff(catch_min_dist=10, names=["^Race"])
        act = _act(activity_name="Morning Run", sport_type="Run", distance_m=1000.0)
        d = decide(act, eff)  # type: ignore[arg-type]
        assert d.give_kudos is False
        assert d.reason == DecisionReason.CRITERIA

    def test_regex_partial_match(self) -> None:
        # re.search, not re.fullmatch
        eff = _eff(names=["GBI"])
        act = _act(activity_name="GBI Europe 2026 Day 7 Part 1", sport_type="Ride")
        d = decide(act, eff)  # type: ignore[arg-type]
        assert d.give_kudos is True
        assert d.reason == DecisionReason.NAME_MATCH

    def test_invalid_regex_skipped_gracefully(self) -> None:
        # Invalid regex should not crash — just ignore that pattern
        eff = _eff(names=["[invalid", "^Race"])
        act = _act(activity_name="Race Day", sport_type="Run")
        d = decide(act, eff)  # type: ignore[arg-type]
        assert d.give_kudos is True  # valid "^Race" still matches


class TestRuleGating:
    """Rule-gating is always active: kudos only when a rule exists for the sport.

    Precedence: ALLOW and NAME_MATCH fire before the gate and are unaffected.
    The gate fires before CRITERIA.
    """

    def test_no_rule_sport_skipped(self) -> None:
        """Sport with no rule at any layer → NO_RULE skip."""
        eff = _eff()  # no rules at all
        act = _act(sport_type="Yoga")
        d = decide(act, eff)  # type: ignore[arg-type]
        assert d.give_kudos is False
        assert d.reason == DecisionReason.NO_RULE

    def test_per_sport_rule_passes_gate(self) -> None:
        """Sport with a per-sport rule → gate passes; if criteria also pass → DEFAULT."""
        eff = _eff(per_dist={"Yoga": 5.0})
        act = _act(sport_type="Yoga", distance_m=10_000.0)
        d = decide(act, eff)  # type: ignore[arg-type]
        assert d.give_kudos is True
        assert d.reason == DecisionReason.DEFAULT

    def test_per_sport_rule_passes_gate_but_criteria_fails(self) -> None:
        """Rule exists (gate passes) but activity is below threshold → CRITERIA."""
        eff = _eff(per_dist={"Run": 10.0})
        act = _act(sport_type="Run", distance_m=1_000.0)
        d = decide(act, eff)  # type: ignore[arg-type]
        assert d.give_kudos is False
        assert d.reason == DecisionReason.CRITERIA

    def test_catchall_rule_passes_gate(self) -> None:
        """A catchAll rule counts as a rule for all sports."""
        eff = _eff(catch_min_dist=5.0)
        act = _act(sport_type="Yoga", distance_m=10_000.0)
        d = decide(act, eff)  # type: ignore[arg-type]
        assert d.give_kudos is True
        assert d.reason == DecisionReason.DEFAULT

    def test_category_rule_passes_gate(self) -> None:
        """A category rule (e.g. FootSports) counts as a rule for its members."""
        eff = _eff(cat_dist={"FootSports": 5.0})
        act = _act(sport_type="Run", distance_m=10_000.0)
        d = decide(act, eff)  # type: ignore[arg-type]
        assert d.give_kudos is True
        assert d.reason == DecisionReason.DEFAULT

    def test_category_rule_member_no_rule_is_sibling(self) -> None:
        """Category rule covers its members; a sport from another category is NOT covered."""
        eff = _eff(cat_dist={"FootSports": 5.0})
        act = _act(sport_type="Ride")  # CycleSports, not FootSports
        d = decide(act, eff)  # type: ignore[arg-type]
        assert d.give_kudos is False
        assert d.reason == DecisionReason.NO_RULE

    def test_allow_bypasses_gate(self) -> None:
        """ALLOW fires before the gate — allowed athlete gets kudos even with no rule."""
        eff = _eff(allow=["111"])  # no rules at all
        act = _act(athlete_id="111", sport_type="Yoga")
        d = decide(act, eff)  # type: ignore[arg-type]
        assert d.give_kudos is True
        assert d.reason == DecisionReason.ALLOW

    def test_name_match_bypasses_gate(self) -> None:
        """NAME_MATCH fires before the gate — matched activity gets kudos even with no rule."""
        eff = _eff(names=["^Race"])  # no distance/time rules
        act = _act(activity_name="Race Day 5k", sport_type="Yoga")
        d = decide(act, eff)  # type: ignore[arg-type]
        assert d.give_kudos is True
        assert d.reason == DecisionReason.NAME_MATCH

    def test_missing_stat_with_rule_passes_gate(self) -> None:
        """Sport has a rule (gate passes); missing stat does not count as CRITERIA failure."""
        eff = _eff(per_dist={"WeightTraining": 1.0})
        act = _act(sport_type="WeightTraining")  # no distance stat
        d = decide(act, eff)  # type: ignore[arg-type]
        assert d.give_kudos is True
        assert d.reason == DecisionReason.DEFAULT

    def test_only_time_rule_passes_gate(self) -> None:
        """A minTime rule (no distance rule) is sufficient to pass the gate."""
        eff = _eff(per_time={"Yoga": 30.0})
        act = _act(sport_type="Yoga", moving_time_s=3600)
        d = decide(act, eff)  # type: ignore[arg-type]
        assert d.give_kudos is True
        assert d.reason == DecisionReason.DEFAULT


class TestDefaultGiveKudos:
    def test_sport_with_rule_and_no_threshold_violation_gives_default(self) -> None:
        """Sport has a rule; activity passes criteria → DEFAULT give."""
        eff = _eff(per_dist={"Ride": 5.0})
        act = _act(sport_type="Ride", distance_m=30_000.0)
        d = decide(act, eff)  # type: ignore[arg-type]
        assert d.give_kudos is True
        assert d.reason == DecisionReason.DEFAULT

    def test_sport_with_no_rule_skipped_by_gating(self) -> None:
        """Sports without a rule → NO_RULE (was DEFAULT in old behavior)."""
        eff = _eff(per_dist={"Run": 5})
        act = _act(sport_type="Padel")
        d = decide(act, eff)  # type: ignore[arg-type]
        assert d.give_kudos is False
        assert d.reason == DecisionReason.NO_RULE


class TestRealLogOracle:
    """Replay representative rows from last-run.log and assert outcomes."""

    def test_ride_30km_gives_kudos(self) -> None:
        # log: "+++ Would give kudos" — 30.10 km Ride, 1h 5m
        eff = _eff(catch_min_dist=10, catch_min_time=45)
        act = _act(sport_type="Ride", distance_m=30100.0, moving_time_s=3900)
        assert decide(act, eff).give_kudos is True  # type: ignore[arg-type]

    def test_short_run_below_distance_skipped(self) -> None:
        # log: "--- Activity stats do not meet criteria" — 4.02 km Run
        eff = _eff(catch_min_dist=10, catch_min_time=45)
        act = _act(sport_type="Run", distance_m=4020.0, moving_time_s=2489)  # 41m 29s
        d = decide(act, eff)  # type: ignore[arg-type]
        assert d.give_kudos is False
        assert d.reason == DecisionReason.CRITERIA

    def test_zero_time_run_skipped(self) -> None:
        # log: "--- Activity stats do not meet criteria" — 0h 0m Run
        eff = _eff(catch_min_dist=10, catch_min_time=45)
        act = _act(sport_type="Run", moving_time_s=0, distance_m=5010.0)
        d = decide(act, eff)  # type: ignore[arg-type]
        assert d.give_kudos is False


class TestAllowList:
    """Athlete in allow list → always give kudos (overrides criteria, not IGNORE/ALREADY)."""

    def test_allow_overrides_criteria(self) -> None:
        """Activity below distance threshold is still kudoed when athlete is allowed."""
        eff = _eff(catch_min_dist=10, allow=["111"])
        act = _act(athlete_id="111", sport_type="Run", distance_m=1000.0)
        d = decide(act, eff)  # type: ignore[arg-type]
        assert d.give_kudos is True
        assert d.reason == DecisionReason.ALLOW

    def test_allow_overrides_criteria_time(self) -> None:
        eff = _eff(catch_min_time=45, allow=["222"])
        act = _act(athlete_id="222", sport_type="Run", moving_time_s=300)
        d = decide(act, eff)  # type: ignore[arg-type]
        assert d.give_kudos is True
        assert d.reason == DecisionReason.ALLOW

    def test_allow_does_not_override_already_kudoed(self) -> None:
        """ALREADY takes precedence over ALLOW: never re-kudo the same activity."""
        eff = _eff(allow=["111"])
        act = _act(athlete_id="111", has_kudoed=True)
        d = decide(act, eff)  # type: ignore[arg-type]
        assert d.give_kudos is False
        assert d.reason == DecisionReason.ALREADY

    def test_ignore_takes_precedence_over_allow(self) -> None:
        """IGNORE beats ALLOW — if someone is both listed, they are still skipped."""
        eff = _eff(ignore=["111"], allow=["111"])
        act = _act(athlete_id="111")
        d = decide(act, eff)  # type: ignore[arg-type]
        assert d.give_kudos is False
        assert d.reason == DecisionReason.IGNORE

    def test_athlete_not_in_allow_list_still_blocked_by_criteria(self) -> None:
        eff = _eff(catch_min_dist=10, allow=["999"])
        act = _act(athlete_id="111", sport_type="Run", distance_m=1000.0)
        d = decide(act, eff)  # type: ignore[arg-type]
        assert d.give_kudos is False
        assert d.reason == DecisionReason.CRITERIA

    def test_allow_athlete_no_criteria_gives_allow(self) -> None:
        """Athlete in allow list with no criteria → ALLOW (not DEFAULT, allow fires first)."""
        eff = _eff(allow=["111"])
        act = _act(athlete_id="111")
        d = decide(act, eff)  # type: ignore[arg-type]
        assert d.give_kudos is True
        assert d.reason == DecisionReason.ALLOW
