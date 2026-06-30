"""Unit tests for sport_types.py — category mapping helpers."""

from kudosy.sport_types import (
    ALL_SPORT_TYPES,
    CATEGORY_NAMES,
    SPORT_CATEGORIES,
    categorize_sport_types,
    category_for_sport,
    sports_in_category,
)


class TestCategoryNames:
    """CATEGORY_NAMES is the canonical ordered list of five categories."""

    def test_five_categories(self) -> None:
        assert len(CATEGORY_NAMES) == 5

    def test_expected_names(self) -> None:
        assert CATEGORY_NAMES == [
            "FootSports",
            "CycleSports",
            "WaterSports",
            "WinterSports",
            "OtherSports",
        ]


class TestSportCategoriesMapping:
    """Every sport in ALL_SPORT_TYPES maps to exactly one category."""

    def test_all_sports_covered(self) -> None:
        """Union of all category members == ALL_SPORT_TYPES (same elements, possibly different order)."""
        members: list[str] = []
        for sports in SPORT_CATEGORIES.values():
            members.extend(sports)
        assert set(members) == set(ALL_SPORT_TYPES)

    def test_no_sport_in_multiple_categories(self) -> None:
        seen: set[str] = set()
        for sports in SPORT_CATEGORIES.values():
            for sport in sports:
                assert sport not in seen, f"{sport} appears in more than one category"
                seen.add(sport)

    def test_specific_placements(self) -> None:
        assert "Run" in SPORT_CATEGORIES["FootSports"]
        assert "TrailRun" in SPORT_CATEGORIES["FootSports"]
        assert "Walk" in SPORT_CATEGORIES["FootSports"]
        assert "Ride" in SPORT_CATEGORIES["CycleSports"]
        assert "IndoorCycling" in SPORT_CATEGORIES["CycleSports"]
        assert "Swim" in SPORT_CATEGORIES["WaterSports"]
        assert "AlpineSki" in SPORT_CATEGORIES["WinterSports"]
        assert "WeightTraining" in SPORT_CATEGORIES["OtherSports"]
        assert "Yoga" in SPORT_CATEGORIES["OtherSports"]


class TestCategoryForSport:
    def test_known_sports(self) -> None:
        assert category_for_sport("Run") == "FootSports"
        assert category_for_sport("Ride") == "CycleSports"
        assert category_for_sport("Swim") == "WaterSports"
        assert category_for_sport("AlpineSki") == "WinterSports"
        assert category_for_sport("WeightTraining") == "OtherSports"

    def test_unknown_sport_fallback(self) -> None:
        assert category_for_sport("SomeNewStravaActivity") == "OtherSports"
        assert category_for_sport("") == "OtherSports"

    def test_all_static_sports_resolve(self) -> None:
        """No sport in ALL_SPORT_TYPES should fall through to OtherSports unexpectedly."""
        for sport in ALL_SPORT_TYPES:
            cat = category_for_sport(sport)
            assert cat in CATEGORY_NAMES, f"{sport} mapped to unknown category {cat!r}"


class TestSportsInCategory:
    def test_known_category_returns_members(self) -> None:
        foot = sports_in_category("FootSports")
        assert "Run" in foot
        assert "Hike" in foot

    def test_unknown_category_returns_empty(self) -> None:
        assert sports_in_category("NotACategory") == []
        assert sports_in_category("") == []

    def test_returns_a_copy_not_the_original(self) -> None:
        """Mutating the returned list must not affect SPORT_CATEGORIES."""
        lst = sports_in_category("FootSports")
        original_len = len(SPORT_CATEGORIES["FootSports"])
        lst.append("MutationTest")
        assert len(SPORT_CATEGORIES["FootSports"]) == original_len


class TestCategorizeSportTypes:
    def test_all_five_keys_always_present(self) -> None:
        grouped = categorize_sport_types([])
        assert set(grouped.keys()) == set(CATEGORY_NAMES)

    def test_keys_in_category_names_order(self) -> None:
        grouped = categorize_sport_types(ALL_SPORT_TYPES)
        assert list(grouped.keys()) == CATEGORY_NAMES

    def test_standard_sports_grouped_correctly(self) -> None:
        grouped = categorize_sport_types(["Run", "Ride", "Swim"])
        assert "Run" in grouped["FootSports"]
        assert "Ride" in grouped["CycleSports"]
        assert "Swim" in grouped["WaterSports"]
        # Other categories should be empty
        assert grouped["WinterSports"] == []
        assert grouped["OtherSports"] == []

    def test_unknown_live_sport_goes_to_other(self) -> None:
        grouped = categorize_sport_types(["Run", "BrandNewActivity"])
        assert "BrandNewActivity" in grouped["OtherSports"]

    def test_preserves_order_within_category(self) -> None:
        """The order within each category group must follow the input list."""
        grouped = categorize_sport_types(["Hike", "Run", "Walk"])
        # All three are FootSports; order must match input
        assert grouped["FootSports"] == ["Hike", "Run", "Walk"]

    def test_full_all_sport_types_round_trip(self) -> None:
        """All sports in ALL_SPORT_TYPES land in exactly one of the five groups."""
        grouped = categorize_sport_types(ALL_SPORT_TYPES)
        total = sum(len(v) for v in grouped.values())
        assert total == len(ALL_SPORT_TYPES)
        # Flat union equals ALL_SPORT_TYPES (no duplicates, no omissions)
        flat: list[str] = []
        for sports in grouped.values():
            flat.extend(sports)
        assert set(flat) == set(ALL_SPORT_TYPES)
