"""Unit tests for effective_config.py — pure three-layer merge."""

from kudosy.effective_config import build_effective_config
from kudosy.models import CatchAll, Defaults, KudoRules, UserConfig


def _defaults(
    *,
    catch_min_dist: float = 0,
    catch_min_time: float = 0,
    per_dist: dict[str, float] | None = None,
    per_time: dict[str, float] | None = None,
    names: list[str] | None = None,
) -> Defaults:
    return Defaults(
        catchAll=CatchAll(minDistance=catch_min_dist, minTime=catch_min_time),
        kudoRules=KudoRules(
            minDistance=per_dist or {},
            minTime=per_time or {},
            activityNames=names or [],
        ),
    )


def _user(
    *,
    per_dist: dict[str, float] | None = None,
    per_time: dict[str, float] | None = None,
    names: list[str] | None = None,
    ignore: list[str] | None = None,
) -> UserConfig:
    return UserConfig(
        stravaSessionCookie="test-cookie",
        athleteId="12345",
        ignoreAthletes=ignore or [],
        kudoRules=KudoRules(
            minDistance=per_dist or {},
            minTime=per_time or {},
            activityNames=names or [],
        ),
    )


class TestCatchAll:
    def test_catchall_zero_not_expanded(self) -> None:
        cfg = build_effective_config(None, _defaults())
        assert cfg.kudoRules.minDistance == {}
        assert cfg.kudoRules.minTime == {}

    def test_catchall_expands_over_all_sport_types(self) -> None:
        from kudosy.sport_types import ALL_SPORT_TYPES

        cfg = build_effective_config(None, _defaults(catch_min_dist=10))
        assert len(cfg.kudoRules.minDistance) == len(ALL_SPORT_TYPES)
        for t in ALL_SPORT_TYPES:
            assert cfg.kudoRules.minDistance[t] == 10

    def test_catchall_time_expands_independently(self) -> None:
        from kudosy.sport_types import ALL_SPORT_TYPES

        cfg = build_effective_config(None, _defaults(catch_min_time=45))
        assert len(cfg.kudoRules.minTime) == len(ALL_SPORT_TYPES)
        assert cfg.kudoRules.minDistance == {}


class TestDefaultPerSportOverridesCatchAll:
    def test_override(self) -> None:
        cfg = build_effective_config(
            None,
            _defaults(catch_min_dist=10, per_dist={"Run": 5}),
        )
        assert cfg.kudoRules.minDistance["Run"] == 5

    def test_zero_in_default_removes_catch_all(self) -> None:
        cfg = build_effective_config(
            None,
            _defaults(catch_min_dist=10, per_dist={"Run": 0}),
        )
        assert "Run" not in cfg.kudoRules.minDistance

    def test_other_sports_unchanged(self) -> None:
        cfg = build_effective_config(
            None,
            _defaults(catch_min_dist=10, per_dist={"Run": 0}),
        )
        assert cfg.kudoRules.minDistance.get("Ride") == 10


class TestUserPerSportOverridesDefault:
    def test_user_overrides_default_per_sport(self) -> None:
        cfg = build_effective_config(
            _user(per_dist={"Run": 3}),
            _defaults(catch_min_dist=10, per_dist={"Run": 5}),
        )
        assert cfg.kudoRules.minDistance["Run"] == 3

    def test_user_zero_removes_even_if_default_set(self) -> None:
        cfg = build_effective_config(
            _user(per_dist={"Run": 0}),
            _defaults(catch_min_dist=10, per_dist={"Run": 5}),
        )
        assert "Run" not in cfg.kudoRules.minDistance

    def test_user_zero_removes_catch_all_for_sport(self) -> None:
        cfg = build_effective_config(
            _user(per_dist={"Ride": 0}),
            _defaults(catch_min_dist=10),
        )
        assert "Ride" not in cfg.kudoRules.minDistance

    def test_user_adds_new_sport_not_in_defaults(self) -> None:
        cfg = build_effective_config(
            _user(per_dist={"VirtualRide": 20}),
            _defaults(),
        )
        assert cfg.kudoRules.minDistance["VirtualRide"] == 20


class TestActivityNamesUnion:
    def test_union_dedup(self) -> None:
        cfg = build_effective_config(
            _user(names=["Morning.*", "^Lunch"]),
            _defaults(names=["Morning.*", "^Evening"]),
        )
        names = cfg.kudoRules.activityNames
        # order: defaults first, then user additions; deduplicated
        assert names.count("Morning.*") == 1
        assert "^Evening" in names
        assert "^Lunch" in names
        # defaults appear before user-only entries
        assert names.index("^Evening") < names.index("^Lunch")

    def test_empty_both(self) -> None:
        cfg = build_effective_config(_user(), _defaults())
        assert cfg.kudoRules.activityNames == []

    def test_only_user_names(self) -> None:
        cfg = build_effective_config(_user(names=["Race"]), _defaults())
        assert cfg.kudoRules.activityNames == ["Race"]

    def test_only_default_names(self) -> None:
        cfg = build_effective_config(_user(), _defaults(names=["Race"]))
        assert cfg.kudoRules.activityNames == ["Race"]


class TestNullUserConfig:
    def test_null_user_config_uses_catch_all_only(self) -> None:
        cfg = build_effective_config(None, _defaults(catch_min_dist=10))
        assert cfg.stravaSessionCookie == ""
        assert cfg.athleteId == ""
        assert cfg.ignoreAthletes == []

    def test_null_user_no_crash(self) -> None:
        cfg = build_effective_config(None, _defaults())
        assert cfg is not None
