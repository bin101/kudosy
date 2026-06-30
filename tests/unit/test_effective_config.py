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


class TestCategoryRules:
    """Category keys are expanded to member sport types during the merge."""

    def test_category_key_expands_to_members(self) -> None:
        from kudosy.sport_types import SPORT_CATEGORIES

        cfg = build_effective_config(_user(per_dist={"CycleSports": 10}))
        for sport in SPORT_CATEGORIES["CycleSports"]:
            assert cfg.kudoRules.minDistance.get(sport) == 10, f"Expected {sport} to have rule"

    def test_category_key_does_not_appear_in_result(self) -> None:
        cfg = build_effective_config(_user(per_dist={"FootSports": 5}))
        assert "FootSports" not in cfg.kudoRules.minDistance

    def test_sport_overrides_category(self) -> None:
        # Category sets 10 km for all cycle sports; Run explicitly overrides to 3 km
        cfg = build_effective_config(_user(per_dist={"FootSports": 10, "Run": 3}))
        assert cfg.kudoRules.minDistance["Run"] == 3
        assert cfg.kudoRules.minDistance["Walk"] == 10

    def test_sport_zero_removes_category_member(self) -> None:
        # Category sets 10 km; Run=0 removes Run specifically
        cfg = build_effective_config(_user(per_dist={"FootSports": 10, "Run": 0}))
        assert "Run" not in cfg.kudoRules.minDistance
        assert cfg.kudoRules.minDistance["Walk"] == 10

    def test_category_zero_removes_catchall_members(self) -> None:
        # catchAll sets 5 km for all; CycleSports=0 removes cycle sports
        from kudosy.sport_types import SPORT_CATEGORIES

        cfg = build_effective_config(_user(catch_min_dist=5, per_dist={"CycleSports": 0}))
        for sport in SPORT_CATEGORIES["CycleSports"]:
            assert sport not in cfg.kudoRules.minDistance, f"{sport} should be removed"
        # Non-cycle sports still have the catchAll value
        assert cfg.kudoRules.minDistance.get("Run") == 5

    def test_category_time_rule_expands(self) -> None:
        from kudosy.sport_types import SPORT_CATEGORIES

        cfg = build_effective_config(_user(per_time={"WaterSports": 30}))
        for sport in SPORT_CATEGORIES["WaterSports"]:
            assert cfg.kudoRules.minTime.get(sport) == 30

    def test_multiple_categories(self) -> None:
        from kudosy.sport_types import SPORT_CATEGORIES

        cfg = build_effective_config(_user(per_dist={"CycleSports": 10, "FootSports": 5}))
        for sport in SPORT_CATEGORIES["CycleSports"]:
            assert cfg.kudoRules.minDistance.get(sport) == 10
        for sport in SPORT_CATEGORIES["FootSports"]:
            assert cfg.kudoRules.minDistance.get(sport) == 5
