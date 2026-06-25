"""Unit tests for effective_config.py — pure two-layer merge."""

from kudosy.effective_config import build_effective_config
from kudosy.models import CatchAll, KudoRules, UserConfig


def _user(
    *,
    catch_min_dist: float = 0,
    catch_min_time: float = 0,
    per_dist: dict[str, float] | None = None,
    per_time: dict[str, float] | None = None,
    names: list[str] | None = None,
    ignore: list[str] | None = None,
) -> UserConfig:
    return UserConfig(
        stravaSessionCookie="test-cookie",
        athleteId="12345",
        ignoreAthletes=ignore or [],
        catchAll=CatchAll(minDistance=catch_min_dist, minTime=catch_min_time),
        kudoRules=KudoRules(
            minDistance=per_dist or {},
            minTime=per_time or {},
            activityNames=names or [],
        ),
    )


class TestCatchAll:
    def test_catchall_zero_not_expanded(self) -> None:
        cfg = build_effective_config(_user())
        assert cfg.kudoRules.minDistance == {}
        assert cfg.kudoRules.minTime == {}

    def test_catchall_expands_over_all_sport_types(self) -> None:
        from kudosy.sport_types import ALL_SPORT_TYPES

        cfg = build_effective_config(_user(catch_min_dist=10))
        assert len(cfg.kudoRules.minDistance) == len(ALL_SPORT_TYPES)
        for t in ALL_SPORT_TYPES:
            assert cfg.kudoRules.minDistance[t] == 10

    def test_catchall_time_expands_independently(self) -> None:
        from kudosy.sport_types import ALL_SPORT_TYPES

        cfg = build_effective_config(_user(catch_min_time=45))
        assert len(cfg.kudoRules.minTime) == len(ALL_SPORT_TYPES)
        assert cfg.kudoRules.minDistance == {}

    def test_null_user_config_returns_empty_rules(self) -> None:
        cfg = build_effective_config(None)
        assert cfg.kudoRules.minDistance == {}
        assert cfg.kudoRules.minTime == {}
        assert cfg.stravaSessionCookie == ""
        assert cfg.athleteId == ""
        assert cfg.ignoreAthletes == []


class TestCatchAllWithPerSportOverride:
    def test_per_sport_overrides_catchall(self) -> None:
        cfg = build_effective_config(_user(catch_min_dist=10, per_dist={"Run": 5}))
        assert cfg.kudoRules.minDistance["Run"] == 5

    def test_zero_per_sport_removes_catchall_entry(self) -> None:
        cfg = build_effective_config(_user(catch_min_dist=10, per_dist={"Run": 0}))
        assert "Run" not in cfg.kudoRules.minDistance

    def test_other_sports_unaffected_by_zero_override(self) -> None:
        cfg = build_effective_config(_user(catch_min_dist=10, per_dist={"Run": 0}))
        assert cfg.kudoRules.minDistance.get("Ride") == 10

    def test_new_sport_not_in_catchall(self) -> None:
        cfg = build_effective_config(_user(per_dist={"VirtualRide": 20}))
        assert cfg.kudoRules.minDistance["VirtualRide"] == 20


class TestCategoryInheritance:
    """Category rules (e.g. CycleSports) propagate to all member sport types."""

    def test_category_dist_propagates_to_members(self) -> None:
        cfg = build_effective_config(_user(per_dist={"CycleSports": 20}))
        assert cfg.kudoRules.minDistance.get("Ride") == 20
        assert cfg.kudoRules.minDistance.get("GravelRide") == 20
        assert cfg.kudoRules.minDistance.get("Handcycle") == 20

    def test_category_time_propagates_to_members(self) -> None:
        cfg = build_effective_config(_user(per_time={"FootSports": 30}))
        assert cfg.kudoRules.minTime.get("Run") == 30
        assert cfg.kudoRules.minTime.get("Hike") == 30
        assert cfg.kudoRules.minTime.get("Walk") == 30

    def test_category_key_absent_from_effective_rules(self) -> None:
        """Category pseudo-keys must never appear in the final effective rules."""
        cfg = build_effective_config(_user(per_dist={"CycleSports": 20}))
        assert "CycleSports" not in cfg.kudoRules.minDistance

    def test_explicit_per_sport_overrides_category(self) -> None:
        """A per-sport rule wins over the category rule for that specific sport type only."""
        cfg = build_effective_config(_user(per_dist={"CycleSports": 20, "Ride": 5}))
        assert cfg.kudoRules.minDistance["Ride"] == 5  # per-sport wins
        assert cfg.kudoRules.minDistance["GravelRide"] == 20  # category (no parent inheritance)
        assert cfg.kudoRules.minDistance["Handcycle"] == 20  # category

    def test_explicit_member_in_user_rules_not_overridden_by_category(self) -> None:
        """If a member has an explicit user rule, category does not touch it."""
        cfg = build_effective_config(_user(per_dist={"CycleSports": 20, "GravelRide": 50}))
        assert cfg.kudoRules.minDistance["GravelRide"] == 50

    def test_category_with_zero_has_no_effect(self) -> None:
        cfg = build_effective_config(_user(per_dist={"CycleSports": 0}))
        assert "Ride" not in cfg.kudoRules.minDistance
        assert "GravelRide" not in cfg.kudoRules.minDistance

    def test_water_sports_category(self) -> None:
        cfg = build_effective_config(_user(per_time={"WaterSports": 15}))
        assert cfg.kudoRules.minTime.get("Swim") == 15
        assert cfg.kudoRules.minTime.get("Rowing") == 15
        assert cfg.kudoRules.minTime.get("VirtualRow") == 15

    def test_category_overrides_catchall(self) -> None:
        """Category (Step 1.2) overrides catchAll (Step 1) for its members."""
        cfg = build_effective_config(_user(catch_min_dist=5, per_dist={"CycleSports": 20}))
        assert cfg.kudoRules.minDistance["GravelRide"] == 20  # category overrides catchAll
        assert cfg.kudoRules.minDistance["Run"] == 5  # catchAll still applies to non-cycle


class TestActivityNames:
    def test_activity_names_from_user(self) -> None:
        cfg = build_effective_config(_user(names=["Morning.*", "^Lunch"]))
        assert cfg.kudoRules.activityNames == ["Morning.*", "^Lunch"]

    def test_empty_names(self) -> None:
        cfg = build_effective_config(_user())
        assert cfg.kudoRules.activityNames == []

    def test_null_user_config_empty_names(self) -> None:
        cfg = build_effective_config(None)
        assert cfg.kudoRules.activityNames == []
