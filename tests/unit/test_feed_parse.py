"""Unit tests for feed.py — StructuredFeedParser."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from kudosy.feed import StructuredFeedParser

_FIXTURES = Path(__file__).parent.parent / "fixtures"


def _parser() -> StructuredFeedParser:
    return StructuredFeedParser()


def _make_payload(activities: list[dict]) -> dict:
    """Wrap a list of activity dicts in the canonical feed payload structure."""
    return {
        "entries": [{"entity": "Activity", "activity": act} for act in activities],
        "pagination": {"hasMore": False},
    }


def _activity(**kwargs) -> dict:
    """Return a minimal valid activity dict, overridable via kwargs."""
    base: dict = {
        "id": "10000000001",
        "activityName": "Morning Run",
        "type": "Run",
        "elapsedTime": 2519,
        "startDate": "2026-06-29T18:38:41Z",
        "isCommute": False,
        "isVirtual": False,
        "deviceName": "Apple Watch",
        "athlete": {
            "athleteId": "A00000001",
            "athleteName": "Alice Mueller",
            "avatarUrl": "https://example.com/alice.jpg",
        },
        "kudosAndComments": {
            "hasKudoed": False,
            "canKudo": True,
            "kudosCount": 3,
        },
        "timeAndLocation": {
            "location": "Berlin, Germany",
            "displayDate": "Today",
        },
        "stats": [],
    }
    base.update(kwargs)
    return base


# ── parse() entry-point ────────────────────────────────────────────────────────


class TestParseEntryPoint:
    def test_returns_activity_for_valid_payload(self) -> None:
        result = _parser().parse(_make_payload([_activity()]))
        assert len(result) == 1
        assert result[0].activity_id == "10000000001"

    def test_non_dict_payload_returns_empty(self) -> None:
        result = _parser().parse([])  # type: ignore[arg-type]
        assert result == []

    def test_missing_entries_key_returns_empty(self) -> None:
        result = _parser().parse({"pagination": {"hasMore": False}})
        assert result == []

    def test_entries_not_a_list_returns_empty(self) -> None:
        result = _parser().parse({"entries": "not a list"})
        assert result == []

    def test_empty_entries_returns_empty(self) -> None:
        result = _parser().parse({"entries": [], "pagination": {}})
        assert result == []


# ── Entity filtering ──────────────────────────────────────────────────────────


class TestEntityFiltering:
    def test_only_activity_entities_parsed(self) -> None:
        payload = {
            "entries": [
                {"entity": "Activity", "activity": _activity(id="1")},
                {"entity": "Challenge", "rowData": {}},
                {"entity": "AthleteFeedEntry", "data": {}},
                {"entity": "Activity", "activity": _activity(id="2")},
            ],
            "pagination": {},
        }
        result = _parser().parse(payload)
        assert len(result) == 2
        ids = {a.activity_id for a in result}
        assert ids == {"1", "2"}

    def test_entry_without_activity_key_skipped(self) -> None:
        payload = {
            "entries": [{"entity": "Activity"}],  # no "activity" key
            "pagination": {},
        }
        result = _parser().parse(payload)
        assert result == []

    def test_entry_with_none_activity_skipped(self) -> None:
        payload = {
            "entries": [{"entity": "Activity", "activity": None}],
            "pagination": {},
        }
        result = _parser().parse(payload)
        assert result == []

    def test_entry_missing_id_skipped(self) -> None:
        payload = _make_payload([_activity(id="")])
        result = _parser().parse(payload)
        assert result == []

    def test_bad_entry_skipped_valid_continues(self) -> None:
        """An unparseable entry is skipped; the rest are returned."""
        payload = {
            "entries": [
                None,
                {"entity": "Activity", "activity": _activity(id="99")},
            ],
            "pagination": {},
        }
        result = _parser().parse(payload)
        assert len(result) == 1
        assert result[0].activity_id == "99"


# ── Activity field mapping ────────────────────────────────────────────────────


class TestActivityFieldMapping:
    def test_basic_fields(self) -> None:
        act_data = _activity(
            id="12345678901",
            activityName="Evening Ride",
            type="Ride",
            elapsedTime=6971,
        )
        result = _parser().parse(_make_payload([act_data]))
        act = result[0]
        assert act.activity_id == "12345678901"
        assert act.activity_name == "Evening Ride"
        assert act.sport_type == "Ride"
        assert act.stats.elapsed_time_s == 6971

    def test_athlete_fields(self) -> None:
        act_data = _activity()
        result = _parser().parse(_make_payload([act_data]))
        act = result[0]
        assert act.athlete_id == "A00000001"
        assert act.athlete_name == "Alice Mueller"
        assert act.athlete_avatar_url == "https://example.com/alice.jpg"

    def test_kudos_fields(self) -> None:
        act_data = _activity()
        act_data["kudosAndComments"]["hasKudoed"] = True
        act_data["kudosAndComments"]["canKudo"] = False
        act_data["kudosAndComments"]["kudosCount"] = 7
        result = _parser().parse(_make_payload([act_data]))
        act = result[0]
        assert act.has_kudoed is True
        assert act.can_kudo is False
        assert act.kudos_count == 7

    def test_start_date_parsed(self) -> None:
        result = _parser().parse(_make_payload([_activity()]))
        act = result[0]
        assert act.start_date is not None
        assert act.start_date.year == 2026
        assert act.start_date.month == 6
        assert act.start_date.day == 29

    def test_location_from_time_and_location(self) -> None:
        result = _parser().parse(_make_payload([_activity()]))
        assert result[0].location == "Berlin, Germany"

    def test_is_commute_false(self) -> None:
        assert _parser().parse(_make_payload([_activity(isCommute=False)]))[0].is_commute is False

    def test_is_commute_true(self) -> None:
        assert _parser().parse(_make_payload([_activity(isCommute=True)]))[0].is_commute is True

    def test_is_virtual(self) -> None:
        assert _parser().parse(_make_payload([_activity(isVirtual=True)]))[0].is_virtual is True

    def test_device_name(self) -> None:
        result = _parser().parse(_make_payload([_activity(deviceName="Garmin Forerunner 955")]))
        assert result[0].device_name == "Garmin Forerunner 955"

    def test_newline_stripped_from_activity_name(self) -> None:
        act_data = _activity(activityName="Morning\nRun")
        result = _parser().parse(_make_payload([act_data]))
        assert result[0].activity_name == "Morning Run"

    def test_unknown_athlete_name_fallback(self) -> None:
        act_data = _activity()
        act_data["athlete"] = {"athleteId": "X1"}  # no name
        result = _parser().parse(_make_payload([act_data]))
        assert result[0].athlete_name == "Unknown"

    def test_invalid_start_date_is_none(self) -> None:
        act_data = _activity(startDate="not-a-date")
        result = _parser().parse(_make_payload([act_data]))
        assert result[0].start_date is None

    def test_elapsed_time_none_when_absent(self) -> None:
        act_data = _activity()
        act_data.pop("elapsedTime", None)
        result = _parser().parse(_make_payload([act_data]))
        assert result[0].stats.elapsed_time_s is None


# ── Stat parsing ──────────────────────────────────────────────────────────────


def _stat(key: str, value: str) -> dict:
    return {"key": key, "value": value, "value_object": None}


def _stat_pair(machine_key: str, value: str, label: str) -> list[dict]:
    return [
        _stat(machine_key, value),
        _stat(f"{machine_key}_subtitle", label),
    ]


class TestStatParsing:
    def test_run_stats_distance_pace_time(self) -> None:
        """Run activity: Distance + Pace + Time with real feed format."""
        stats = (
            _stat_pair(
                "stat_one", "5.17<abbr class='unit' title='kilometers'> km</abbr>", "Distance"
            )
            + _stat_pair(
                "stat_two",
                "8:06<abbr class='unit' title='minutes per kilometer'> /km</abbr>",
                "Pace",
            )
            + _stat_pair(
                "stat_three",
                "41<abbr class='unit' title='minute'>m</abbr> 56<abbr class='unit' title='second'>s</abbr>",
                "Time",
            )
        )
        result = _parser().parse(_make_payload([_activity(type="Run", stats=stats)]))
        act = result[0]
        assert act.stats.distance_m == pytest.approx(5170.0)
        assert act.stats.pace_s_per_km == pytest.approx(486.0)
        assert act.stats.moving_time_s == 2516

    def test_ride_stats_distance_elevation_time(self) -> None:
        """Ride activity: Distance + Elev Gain + Time."""
        stats = (
            _stat_pair(
                "stat_one", "53.24<abbr class='unit' title='kilometers'> km</abbr>", "Distance"
            )
            + _stat_pair("stat_two", "116<abbr class='unit' title='meters'> m</abbr>", "Elev Gain")
            + _stat_pair(
                "stat_three",
                "1<abbr class='unit' title='hour'>h</abbr> 46<abbr class='unit' title='minute'>m</abbr>",
                "Time",
            )
        )
        result = _parser().parse(_make_payload([_activity(type="Ride", stats=stats)]))
        act = result[0]
        assert act.stats.distance_m == pytest.approx(53240.0)
        assert act.stats.elevation_gain_m == pytest.approx(116.0)
        assert act.stats.moving_time_s == 6360
        assert act.stats.pace_s_per_km is None

    def test_swim_stats_distance_time_pace(self) -> None:
        """Swim: Distance + Time + Pace (/100m)."""
        stats = (
            _stat_pair("stat_one", "1,300<abbr class='unit' title='meters'> m</abbr>", "Distance")
            + _stat_pair(
                "stat_two",
                "21<abbr class='unit' title='minute'>m</abbr> 10<abbr class='unit' title='second'>s</abbr>",
                "Time",
            )
            + _stat_pair(
                "stat_three", "1:37<abbr class='unit' title='per 100 Meters'> /100m</abbr>", "Pace"
            )
        )
        result = _parser().parse(_make_payload([_activity(type="Swim", stats=stats)]))
        act = result[0]
        assert act.stats.distance_m == pytest.approx(1300.0)  # 1,300 m
        assert act.stats.moving_time_s == 1270  # 21*60+10
        assert act.stats.pace_s_per_100m == pytest.approx(97.0)
        assert act.stats.pace_s_per_km is None

    def test_weight_training_time_only(self) -> None:
        """WeightTraining: only Time stat."""
        stats = _stat_pair(
            "stat_one",
            "30<abbr class='unit' title='minute'>m</abbr> 0<abbr class='unit' title='second'>s</abbr>",
            "Time",
        )
        result = _parser().parse(_make_payload([_activity(type="WeightTraining", stats=stats)]))
        act = result[0]
        assert act.stats.moving_time_s == 1800
        assert act.stats.distance_m is None
        assert act.stats.elevation_gain_m is None

    def test_no_stats_gives_empty_stats(self) -> None:
        result = _parser().parse(_make_payload([_activity(stats=[])]))
        act = result[0]
        assert act.stats.distance_m is None
        assert act.stats.moving_time_s is None
        assert act.stats.display == []

    def test_elapsed_time_always_set_from_activity_field(self) -> None:
        """stats.elapsed_time_s comes from activity.elapsedTime, not the stats list."""
        result = _parser().parse(_make_payload([_activity(elapsedTime=9999)]))
        assert result[0].stats.elapsed_time_s == 9999

    def test_display_list_preserves_order(self) -> None:
        """display list follows the order the stats appear in the feed."""
        stats = (
            _stat_pair(
                "stat_one", "5.17<abbr class='unit' title='kilometers'> km</abbr>", "Distance"
            )
            + _stat_pair(
                "stat_two",
                "8:06<abbr class='unit' title='minutes per kilometer'> /km</abbr>",
                "Pace",
            )
            + _stat_pair(
                "stat_three",
                "41<abbr class='unit' title='minute'>m</abbr> 56<abbr class='unit' title='second'>s</abbr>",
                "Time",
            )
        )
        result = _parser().parse(_make_payload([_activity(stats=stats)]))
        labels = [sv.label for sv in result[0].stats.display]
        assert labels == ["Distance", "Pace", "Time"]

    def test_display_stat_value_fields(self) -> None:
        """StatValue carries key, label, raw (cleaned), value, unit."""
        stats = _stat_pair(
            "stat_one",
            "5.17<abbr class='unit' title='kilometers'> km</abbr>",
            "Distance",
        )
        result = _parser().parse(_make_payload([_activity(stats=stats)]))
        sv = result[0].stats.display[0]
        assert sv.key == "distance"
        assert sv.label == "Distance"
        assert sv.raw == "5.17 km"
        assert sv.value == pytest.approx(5170.0)
        assert sv.unit == "m"

    def test_unknown_stat_goes_to_extra(self) -> None:
        stats = _stat_pair("stat_one", "999 something", "WeirdStat")
        result = _parser().parse(_make_payload([_activity(stats=stats)]))
        assert "WeirdStat" in result[0].stats.extra

    def test_carbon_saved_in_display_not_extra(self) -> None:
        """'Carbon Saved' is classified as carbon_saved, not unknown → must not land in extra."""
        stats = _stat_pair("stat_three", "4.16 kg CO2", "Carbon Saved")
        result = _parser().parse(_make_payload([_activity(stats=stats)]))
        act = result[0]
        # Must appear in display with key='carbon_saved'
        carbon_entries = [s for s in act.stats.display if s.key == "carbon_saved"]
        assert len(carbon_entries) == 1
        assert carbon_entries[0].label == "Carbon Saved"
        assert carbon_entries[0].raw == "4.16 kg CO2"
        # Must NOT land in extra
        assert "Carbon Saved" not in act.stats.extra

    def test_stat_item_without_subtitle_goes_to_extra(self) -> None:
        """If no subtitle is paired, the machine key becomes the label and the
        stat is unclassified (goes to extra), because there is no /km or /100m
        unit marker to distinguish a pace from a distance.
        Strava always sends subtitle pairs in practice."""
        stats = [_stat("stat_one", "5.00<abbr class='unit' title='kilometers'> km</abbr>")]
        result = _parser().parse(_make_payload([_activity(stats=stats)]))
        # Unrecognised label (machine key "stat_one") → extra, not a typed field
        assert result[0].stats.distance_m is None
        assert "stat_one" in result[0].stats.extra

    def test_stats_list_with_none_items_tolerant(self) -> None:
        """None items in stats list are skipped without error."""
        stats = [None, _stat("stat_one", "5.17 km"), _stat("stat_one_subtitle", "Distance")]
        result = _parser().parse(_make_payload([_activity(stats=stats)]))
        assert result[0].stats.distance_m == pytest.approx(5170.0)


# ── Real fixture ──────────────────────────────────────────────────────────────


@pytest.fixture(scope="module")
def real_fixture_parsed() -> list:
    payload = json.loads((_FIXTURES / "feed_following.json").read_text())
    return _parser().parse(payload)


class TestRealFixture:
    def test_all_activities_parsed(self, real_fixture_parsed: list) -> None:
        assert len(real_fixture_parsed) == 16

    def test_activity_ids_unique(self, real_fixture_parsed: list) -> None:
        ids = [a.activity_id for a in real_fixture_parsed]
        assert len(ids) == len(set(ids))

    def test_all_have_athlete_name(self, real_fixture_parsed: list) -> None:
        for a in real_fixture_parsed:
            assert a.athlete_name and a.athlete_name != "Unknown"

    def test_all_have_sport_type(self, real_fixture_parsed: list) -> None:
        for a in real_fixture_parsed:
            assert a.sport_type

    def test_sport_types_present(self, real_fixture_parsed: list) -> None:
        types = {a.sport_type for a in real_fixture_parsed}
        assert "Run" in types
        assert "Ride" in types

    def test_run_has_distance_and_pace(self, real_fixture_parsed: list) -> None:
        runs = [a for a in real_fixture_parsed if a.sport_type in ("Run", "TrailRun")]
        assert len(runs) > 0
        for run in runs:
            assert run.stats.distance_m is not None and run.stats.distance_m > 0
            assert run.stats.pace_s_per_km is not None and run.stats.pace_s_per_km > 0

    def test_ride_has_elevation(self, real_fixture_parsed: list) -> None:
        rides = [
            a for a in real_fixture_parsed if a.sport_type in ("Ride", "EBikeRide", "GravelRide")
        ]
        assert len(rides) > 0
        for ride in rides:
            assert ride.stats.elevation_gain_m is not None

    def test_weight_training_has_time_only(self, real_fixture_parsed: list) -> None:
        wt = [a for a in real_fixture_parsed if a.sport_type == "WeightTraining"]
        assert len(wt) > 0
        for a in wt:
            assert a.stats.moving_time_s is not None
            assert a.stats.distance_m is None

    def test_swim_has_swim_pace(self, real_fixture_parsed: list) -> None:
        swims = [a for a in real_fixture_parsed if a.sport_type == "Swim"]
        assert len(swims) > 0
        for swim in swims:
            assert swim.stats.pace_s_per_100m is not None

    def test_elapsed_time_from_activity_field(self, real_fixture_parsed: list) -> None:
        for a in real_fixture_parsed:
            assert a.stats.elapsed_time_s is not None and a.stats.elapsed_time_s > 0

    def test_no_pii_in_athlete_ids(self, real_fixture_parsed: list) -> None:
        """Fixture athletes should all use the anonymised A########-format IDs."""
        for a in real_fixture_parsed:
            assert a.athlete_id.startswith("A"), f"Non-anonymised ID: {a.athlete_id!r}"

    def test_avatar_urls_anonymised(self, real_fixture_parsed: list) -> None:
        for a in real_fixture_parsed:
            if a.athlete_avatar_url:
                assert "example.com" in a.athlete_avatar_url

    def test_display_stats_not_empty(self, real_fixture_parsed: list) -> None:
        """Every activity should have at least one display stat."""
        for a in real_fixture_parsed:
            assert len(a.stats.display) > 0, f"No display stats for {a.activity_id}"
