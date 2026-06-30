"""Unit tests for effective_config.py — three-layer merge (catchAll → category → per-sport)."""

from kudosy.effective_config import build_effective_config
from kudosy.models import CatchAll, KudoRules, UserConfig


def _user(
    *,
    catch_min_dist: float = 0,
    catch_min_time: float = 0,
    per_dist: dict[str, float] | None = None,
    per_time: dict[str, float] | None = None,
    cat_dist: dict[str, float] | None = None,
    cat_time: dict[str, float] | None = None,
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
            categoryMinDistance=cat_dist or {},
            categoryMinTime=cat_time or {},
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


class TestCategoryLayer:
    """Category rules occupy the middle layer: above catchAll, below per-sport."""

    def test_category_expands_over_members(self) -> None:
        """FootSports category rule sets all foot sport members."""
        from kudosy.sport_types import SPORT_CATEGORIES

        cfg = build_effective_config(_user(cat_dist={"FootSports": 5.0}))
        for sport in SPORT_CATEGORIES["FootSports"]:
            assert cfg.kudoRules.minDistance.get(sport) == 5.0, sport

    def test_category_does_not_affect_non_members(self) -> None:
        """FootSports category rule must not set Ride (CycleSports)."""
        cfg = build_effective_config(_user(cat_dist={"FootSports": 5.0}))
        assert "Ride" not in cfg.kudoRules.minDistance

    def test_category_overrides_catchall_for_its_members(self) -> None:
        """Category (layer 2) beats catchAll (layer 3): Run gets 8, not 10."""
        cfg = build_effective_config(_user(catch_min_dist=10, cat_dist={"FootSports": 8.0}))
        assert cfg.kudoRules.minDistance["Run"] == 8.0
        # Non-foot sports still get catchAll value
        assert cfg.kudoRules.minDistance["Ride"] == 10.0

    def test_category_zero_removes_catchall_for_members(self) -> None:
        """Category=0 removes catchAll-set rules for all its members."""
        cfg = build_effective_config(_user(catch_min_dist=10, cat_dist={"FootSports": 0}))
        assert "Run" not in cfg.kudoRules.minDistance
        assert "Hike" not in cfg.kudoRules.minDistance
        # Non-foot sports still have catchAll
        assert cfg.kudoRules.minDistance["Ride"] == 10.0

    def test_per_sport_overrides_category(self) -> None:
        """Per-sport (layer 1) beats category (layer 2): Run=3 wins over FootSports=8."""
        cfg = build_effective_config(_user(cat_dist={"FootSports": 8.0}, per_dist={"Run": 3.0}))
        assert cfg.kudoRules.minDistance["Run"] == 3.0
        assert cfg.kudoRules.minDistance["Walk"] == 8.0  # other foot sports unaffected

    def test_per_sport_zero_removes_category_entry(self) -> None:
        """Per-sport=0 carves out a single sport from an active category rule."""
        cfg = build_effective_config(_user(cat_dist={"FootSports": 8.0}, per_dist={"Run": 0}))
        assert "Run" not in cfg.kudoRules.minDistance
        assert cfg.kudoRules.minDistance["Walk"] == 8.0  # sibling unaffected

    def test_category_time_layer(self) -> None:
        """Category rules work identically for minTime."""
        cfg = build_effective_config(_user(cat_time={"CycleSports": 30.0}))
        assert cfg.kudoRules.minTime["Ride"] == 30.0
        assert cfg.kudoRules.minTime["MountainBikeRide"] == 30.0
        assert "Run" not in cfg.kudoRules.minTime

    def test_category_dicts_empty_on_effective_layer(self) -> None:
        """Effective layer must not copy category dicts (they are fully expanded)."""
        cfg = build_effective_config(_user(cat_dist={"FootSports": 5.0}))
        assert cfg.kudoRules.categoryMinDistance == {}
        assert cfg.kudoRules.categoryMinTime == {}

    def test_unknown_category_name_ignored(self) -> None:
        """An unknown category key must not raise — it just produces no expansion."""
        cfg = build_effective_config(_user(cat_dist={"UnknownCategory": 5.0}))
        # No sport should be set from an unknown category
        assert cfg.kudoRules.minDistance == {}


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
