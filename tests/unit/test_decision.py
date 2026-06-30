"""Unit tests for decision.py — pure filter logic.

Decision precedence (highest → lowest):
  ignore → already → allow → name_match → criteria → default (give kudos)

Test corpus is derived from the real last-run.log to guarantee behavioral parity.
"""

from kudosy.decision import decide
from kudosy.effective_config import build_effective_config
from kudosy.models import Activity, CatchAll, DecisionReason, KudoRules, UserConfig


def _eff(
    *,
    catch_min_dist: float = 0,
    catch_min_time: float = 0,
    per_dist: dict[str, float] | None = None,
    per_time: dict[str, float] | None = None,
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
    stats: dict[str, str] | None = None,
) -> Activity:
    return Activity(
        athlete_name="Test Athlete",
        athlete_id=athlete_id,
        activity_id=activity_id,
        activity_name=activity_name,
        sport_type=sport_type,
        has_kudoed=has_kudoed,
        stats=stats or {},
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
        eff = _eff(ignore=["999"], catch_min_dist=1)
        act = _act(athlete_id="111", stats={"Distance": "30.10 km"})
        d = decide(act, eff)  # type: ignore[arg-type]
        # Not ignored, has a rule, meets criteria → give kudos
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
        act = _act(sport_type="Ride", stats={"Distance": "1.36 km"})
        d = decide(act, eff)  # type: ignore[arg-type]
        assert d.give_kudos is False
        assert d.reason == DecisionReason.CRITERIA

    def test_below_min_time(self) -> None:
        # catch-all minTime = 45 min = 2700 s; activity is 5m 5s = 305 s
        eff = _eff(catch_min_time=45)
        act = _act(sport_type="Ride", stats={"Time": "5m 5s"})
        d = decide(act, eff)  # type: ignore[arg-type]
        assert d.give_kudos is False
        assert d.reason == DecisionReason.CRITERIA

    def test_zero_duration_fails_time_criteria(self) -> None:
        # "0h 0m" = 0 s; minTime = 45 → skip
        eff = _eff(catch_min_time=45)
        act = _act(sport_type="Run", stats={"Time": "0h 0m"})
        d = decide(act, eff)  # type: ignore[arg-type]
        assert d.give_kudos is False

    def test_above_criteria_gives_kudos(self) -> None:
        # 30.10 km > 10 km threshold
        eff = _eff(catch_min_dist=10)
        act = _act(sport_type="Ride", stats={"Distance": "30.10 km"})
        d = decide(act, eff)  # type: ignore[arg-type]
        assert d.give_kudos is True

    def test_missing_stat_does_not_fail_criteria(self) -> None:
        """WeightTraining has no Distance; a minDistance rule must not block it."""
        eff = _eff(catch_min_dist=10)
        act = _act(sport_type="WeightTraining", stats={"Time": "49m 48s"})
        d = decide(act, eff)  # type: ignore[arg-type]
        # Missing distance → treat as "not failing" → give kudos
        assert d.give_kudos is True


class TestNameMatch:
    """activityNames regex match → always give kudos, even below threshold."""

    def test_name_match_overrides_criteria(self) -> None:
        eff = _eff(catch_min_dist=10, names=["^Race"])
        # Only 1 km but name matches
        act = _act(activity_name="Race Day 5k", sport_type="Run", stats={"Distance": "1 km"})
        d = decide(act, eff)  # type: ignore[arg-type]
        assert d.give_kudos is True
        assert d.reason == DecisionReason.NAME_MATCH

    def test_name_no_match_falls_through_to_criteria(self) -> None:
        # Name doesn't match, but sport has a rule (catchAll) and fails criteria
        eff = _eff(catch_min_dist=10, names=["^Race"])
        act = _act(activity_name="Morning Run", sport_type="Run", stats={"Distance": "1 km"})
        d = decide(act, eff)  # type: ignore[arg-type]
        assert d.give_kudos is False
        assert d.reason == DecisionReason.CRITERIA

    def test_name_no_match_no_rule_gives_no_rule(self) -> None:
        # Name doesn't match and sport has no rule at all → NO_RULE
        eff = _eff(names=["^Race"])
        act = _act(activity_name="Morning Run", sport_type="Yoga")
        d = decide(act, eff)  # type: ignore[arg-type]
        assert d.give_kudos is False
        assert d.reason == DecisionReason.NO_RULE

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


class TestNoRule:
    """No distance/duration rule configured for sport → NO_RULE (opt-in model)."""

    def test_no_criteria_at_all_gives_no_rule(self) -> None:
        # No catchAll, no per-sport rules → NO_RULE for any sport
        eff = _eff()
        act = _act()
        d = decide(act, eff)  # type: ignore[arg-type]
        assert d.give_kudos is False
        assert d.reason == DecisionReason.NO_RULE

    def test_sport_with_no_rule_gives_no_rule(self) -> None:
        # Only Run has a rule; Padel has none → NO_RULE
        eff = _eff(per_dist={"Run": 5})
        act = _act(sport_type="Padel")
        d = decide(act, eff)  # type: ignore[arg-type]
        assert d.give_kudos is False
        assert d.reason == DecisionReason.NO_RULE

    def test_sport_with_rule_gives_default(self) -> None:
        # Run has a rule and the activity meets it → DEFAULT (give kudos)
        eff = _eff(per_dist={"Run": 5})
        act = _act(sport_type="Run", stats={"Distance": "10 km"})
        d = decide(act, eff)  # type: ignore[arg-type]
        assert d.give_kudos is True
        assert d.reason == DecisionReason.DEFAULT

    def test_catchall_sets_rule_for_all_sports(self) -> None:
        # catchAll > 0 sets a rule for all sports → should give kudos when criteria met
        eff = _eff(catch_min_dist=5)
        act = _act(sport_type="Yoga", stats={"Distance": "10 km"})
        d = decide(act, eff)  # type: ignore[arg-type]
        assert d.give_kudos is True

    def test_allow_overrides_no_rule(self) -> None:
        # Allow fires before NO_RULE check → always gives kudos
        eff = _eff(allow=["111"])
        act = _act(athlete_id="111", sport_type="Yoga")
        d = decide(act, eff)  # type: ignore[arg-type]
        assert d.give_kudos is True
        assert d.reason == DecisionReason.ALLOW

    def test_name_match_overrides_no_rule(self) -> None:
        # Name match fires before NO_RULE check → always gives kudos
        eff = _eff(names=["^Race"])
        act = _act(activity_name="Race Day", sport_type="Yoga")
        d = decide(act, eff)  # type: ignore[arg-type]
        assert d.give_kudos is True
        assert d.reason == DecisionReason.NAME_MATCH


class TestDefaultGiveKudos:
    """Legacy class kept; redirected to the new rule-required semantics."""

    def test_sport_with_rule_meets_criteria_gives_default(self) -> None:
        # Rule exists, stat present and above threshold → DEFAULT
        eff = _eff(catch_min_dist=1)
        act = _act(sport_type="Ride", stats={"Distance": "30.10 km"})
        d = decide(act, eff)  # type: ignore[arg-type]
        assert d.give_kudos is True
        assert d.reason == DecisionReason.DEFAULT


class TestRealLogOracle:
    """Replay representative rows from last-run.log and assert outcomes."""

    def setup_method(self) -> None:
        # The real defaults: catchAll minDistance=10km, minTime=45min
        self.eff = _eff(
            catch_min_dist=10,
            catch_min_time=45,
            ignore=["real-id-redacted"],  # placeholder; tested conceptually
        )

    def test_fortuna_martin_ride_30km_gives_kudos(self) -> None:
        # log: "+++ Would give kudos" — 30.10 km Ride
        eff = _eff(catch_min_dist=10, catch_min_time=45)
        act = _act(
            sport_type="Ride",
            stats={"Distance": "30.10 km", "Time": "1h 5m"},
        )
        assert decide(act, eff).give_kudos is True  # type: ignore[arg-type]

    def test_short_run_below_distance_skipped(self) -> None:
        # log: "--- Activity stats do not meet criteria" — 4.02 km Run
        eff = _eff(catch_min_dist=10, catch_min_time=45)
        act = _act(sport_type="Run", stats={"Distance": "4.02 km", "Time": "41m 29s"})
        d = decide(act, eff)  # type: ignore[arg-type]
        assert d.give_kudos is False
        assert d.reason == DecisionReason.CRITERIA

    def test_zero_time_run_skipped(self) -> None:
        # log: "--- Activity stats do not meet criteria" — 0h 0m Run
        eff = _eff(catch_min_dist=10, catch_min_time=45)
        act = _act(sport_type="Run", stats={"Time": "0h 0m", "Distance": "5.01 km"})
        d = decide(act, eff)  # type: ignore[arg-type]
        assert d.give_kudos is False


class TestAllowList:
    """Athlete in allow list → always give kudos (overrides criteria, not IGNORE/ALREADY)."""

    def test_allow_overrides_criteria(self) -> None:
        """Activity below distance threshold is still kudoed when athlete is allowed."""
        eff = _eff(catch_min_dist=10, allow=["111"])
        act = _act(athlete_id="111", sport_type="Run", stats={"Distance": "1 km"})
        d = decide(act, eff)  # type: ignore[arg-type]
        assert d.give_kudos is True
        assert d.reason == DecisionReason.ALLOW

    def test_allow_overrides_criteria_time(self) -> None:
        eff = _eff(catch_min_time=45, allow=["222"])
        act = _act(athlete_id="222", sport_type="Run", stats={"Time": "5m 0s"})
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
        act = _act(athlete_id="111", sport_type="Run", stats={"Distance": "1 km"})
        d = decide(act, eff)  # type: ignore[arg-type]
        assert d.give_kudos is False
        assert d.reason == DecisionReason.CRITERIA

    def test_allow_athlete_no_criteria_gives_default(self) -> None:
        """Athlete in allow list with no criteria → ALLOW (not DEFAULT, allow fires first)."""
        eff = _eff(allow=["111"])
        act = _act(athlete_id="111")
        d = decide(act, eff)  # type: ignore[arg-type]
        assert d.give_kudos is True
        assert d.reason == DecisionReason.ALLOW
