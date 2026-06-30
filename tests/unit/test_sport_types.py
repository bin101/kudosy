"""Unit tests for sport_types.py — category mapping and helper functions."""

from kudosy.sport_types import (
    ALL_SPORT_TYPES,
    CATEGORY_IDS,
    SPORT_CATEGORIES,
    category_of,
    sports_in_category,
)


class TestCategoryCompleteness:
    def test_all_hardcoded_sports_are_categorised(self) -> None:
        """Every sport in ALL_SPORT_TYPES must appear in exactly one category."""
        all_categorised = {s for sports in SPORT_CATEGORIES.values() for s in sports}
        missing = [s for s in ALL_SPORT_TYPES if s not in all_categorised]
        assert missing == [], f"Sports not in any category: {missing}"

    def test_no_sport_appears_in_multiple_categories(self) -> None:
        seen: dict[str, str] = {}
        for cat, sports in SPORT_CATEGORIES.items():
            for sport in sports:
                assert sport not in seen, f"{sport!r} appears in both {seen[sport]!r} and {cat!r}"
                seen[sport] = cat

    def test_category_ids_match_sport_categories_keys(self) -> None:
        assert frozenset(SPORT_CATEGORIES) == CATEGORY_IDS

    def test_five_categories_defined(self) -> None:
        expected = {"FootSports", "CycleSports", "WaterSports", "WinterSports", "OtherSports"}
        assert set(SPORT_CATEGORIES.keys()) == expected


class TestCategoryOf:
    def test_known_run_is_foot_sports(self) -> None:
        assert category_of("Run") == "FootSports"

    def test_known_ride_is_cycle_sports(self) -> None:
        assert category_of("Ride") == "CycleSports"

    def test_known_swim_is_water_sports(self) -> None:
        assert category_of("Swim") == "WaterSports"

    def test_known_alpine_ski_is_winter_sports(self) -> None:
        assert category_of("AlpineSki") == "WinterSports"

    def test_known_yoga_is_other_sports(self) -> None:
        assert category_of("Yoga") == "OtherSports"

    def test_unknown_sport_defaults_to_other_sports(self) -> None:
        assert category_of("FutureUnknownSport") == "OtherSports"

    def test_all_hardcoded_sports_return_valid_category(self) -> None:
        for sport in ALL_SPORT_TYPES:
            cat = category_of(sport)
            assert cat in CATEGORY_IDS, f"{sport!r} → {cat!r} not in CATEGORY_IDS"


class TestSportsInCategory:
    def test_returns_foot_sports_members(self) -> None:
        members = sports_in_category("FootSports")
        assert "Run" in members
        assert "Walk" in members
        assert "Hike" in members

    def test_returns_cycle_sports_members(self) -> None:
        members = sports_in_category("CycleSports")
        assert "Ride" in members
        assert "GravelRide" in members

    def test_unknown_category_returns_empty(self) -> None:
        assert sports_in_category("NoSuchCategory") == []

    def test_returns_independent_copy(self) -> None:
        """Mutating the result must not affect SPORT_CATEGORIES."""
        members = sports_in_category("FootSports")
        original_len = len(SPORT_CATEGORIES["FootSports"])
        members.append("MUTANT")
        assert len(SPORT_CATEGORIES["FootSports"]) == original_len
