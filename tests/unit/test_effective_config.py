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


class TestSportInheritance:
    """Parent sport rules are inherited by child types (Ride → VirtualRide etc.)."""

    def test_ride_dist_inherited_by_virtual_ride(self) -> None:
        cfg = build_effective_config(_user(per_dist={"Ride": 10}))
        assert cfg.kudoRules.minDistance["VirtualRide"] == 10

    def test_ride_dist_inherited_by_gravel_ride(self) -> None:
        cfg = build_effective_config(_user(per_dist={"Ride": 10}))
        assert cfg.kudoRules.minDistance["GravelRide"] == 10

    def test_ride_dist_inherited_by_mtb_ride(self) -> None:
        cfg = build_effective_config(_user(per_dist={"Ride": 10}))
        assert cfg.kudoRules.minDistance["MountainBikeRide"] == 10

    def test_ride_time_inherited_by_children(self) -> None:
        cfg = build_effective_config(_user(per_time={"Ride": 45}))
        for child in ("VirtualRide", "GravelRide", "MountainBikeRide", "EBikeRide"):
            assert cfg.kudoRules.minTime[child] == 45, f"{child} should inherit Ride time rule"

    def test_run_dist_inherited_by_trail_run(self) -> None:
        cfg = build_effective_config(_user(per_dist={"Run": 5}))
        assert cfg.kudoRules.minDistance["TrailRun"] == 5

    def test_run_dist_inherited_by_virtual_run(self) -> None:
        cfg = build_effective_config(_user(per_dist={"Run": 5}))
        assert cfg.kudoRules.minDistance["VirtualRun"] == 5

    def test_rowing_time_inherited_by_virtual_row(self) -> None:
        cfg = build_effective_config(_user(per_time={"Rowing": 20}))
        assert cfg.kudoRules.minTime["VirtualRow"] == 20

    def test_child_explicit_rule_overrides_inherited(self) -> None:
        """Explicit child rule takes precedence over parent inheritance."""
        cfg = build_effective_config(_user(per_dist={"Ride": 10, "VirtualRide": 20}))
        assert cfg.kudoRules.minDistance["VirtualRide"] == 20
        assert cfg.kudoRules.minDistance["GravelRide"] == 10  # sibling still inherits

    def test_child_zero_removes_inherited_rule(self) -> None:
        """Child with explicit 0 disables parent inheritance (opt-out)."""
        cfg = build_effective_config(_user(per_dist={"Ride": 10, "VirtualRide": 0}))
        assert "VirtualRide" not in cfg.kudoRules.minDistance

    def test_catchall_not_overridden_by_inheritance(self) -> None:
        """catchAll applies to all sports; parent rule does NOT override catchAll for child
        if the child already has a catchAll-derived value — parent rule applies if it's > 0
        but the existing overlay step runs last so explicit child rules still win."""
        # catchAll=5, Ride=10 → children should get Ride's 10 (inheritance), not 5
        cfg = build_effective_config(_user(catch_min_dist=5, per_dist={"Ride": 10}))
        # VirtualRide: catchAll gives 5, then inheritance gives 10 → 10 wins
        assert cfg.kudoRules.minDistance["VirtualRide"] == 10

    def test_parent_without_explicit_rule_does_not_propagate(self) -> None:
        """If only catchAll is set (no explicit Ride rule), inheritance does NOT propagate
        the catchAll value — catchAll already expanded directly to all children."""
        cfg = build_effective_config(_user(catch_min_dist=5))
        # VirtualRide already has 5 from catchAll expansion; inheritance step is a no-op
        # (it only propagates explicit user_rules, not catchAll-expanded values)
        assert cfg.kudoRules.minDistance["VirtualRide"] == 5
        assert cfg.kudoRules.minDistance["Ride"] == 5


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
        """A per-sport rule wins over the category rule (highest priority).

        GravelRide is a *child* of Ride (SPORT_PARENTS), so it inherits Ride's value
        (5) via parent-inheritance — which supersedes the category value (20).
        Handcycle is in CycleSports but NOT a Ride child, so it keeps the category value.
        """
        cfg = build_effective_config(_user(per_dist={"CycleSports": 20, "Ride": 5}))
        assert cfg.kudoRules.minDistance["Ride"] == 5
        assert cfg.kudoRules.minDistance["GravelRide"] == 5  # parent-inheritance wins over category
        assert cfg.kudoRules.minDistance["Handcycle"] == 20  # category (not a Ride child)

    def test_parent_inheritance_overrides_category(self) -> None:
        """Parent-type inheritance (Step 1.5) wins over category rule (Step 1.2)."""
        # CycleSports=20 → all cycle members get 20
        # Ride=30 → Ride's children get 30 via parent inheritance
        cfg = build_effective_config(_user(per_dist={"CycleSports": 20, "Ride": 30}))
        assert cfg.kudoRules.minDistance.get("VirtualRide") == 30  # parent wins
        assert cfg.kudoRules.minDistance.get("Handcycle") == 20  # category only (not a Ride child)

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
