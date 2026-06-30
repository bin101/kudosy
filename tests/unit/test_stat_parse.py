"""Unit tests for stat_parse.py — pure stat normalisation functions."""

from __future__ import annotations

import pytest

from kudosy.stat_parse import (
    classify_stat,
    parse_distance,
    parse_duration,
    parse_elevation,
    parse_pace,
    parse_pace_km,
    parse_swim_pace,
    strip_unit_markup,
)

# ── strip_unit_markup ─────────────────────────────────────────────────────────


class TestStripUnitMarkup:
    def test_distance_abbr(self) -> None:
        raw = "5.17<abbr class='unit' title='kilometers'> km</abbr>"
        assert strip_unit_markup(raw) == "5.17 km"

    def test_duration_multiple_abbr(self) -> None:
        raw = "41<abbr class='unit' title='minute'>m</abbr> 56<abbr class='unit' title='second'>s</abbr>"
        assert strip_unit_markup(raw) == "41m 56s"

    def test_pace_abbr(self) -> None:
        raw = "8:06<abbr class='unit' title='minutes per kilometer'> /km</abbr>"
        assert strip_unit_markup(raw) == "8:06 /km"

    def test_swim_pace_abbr(self) -> None:
        raw = "1:37<abbr class='unit' title='per 100 Meters'> /100m</abbr>"
        assert strip_unit_markup(raw) == "1:37 /100m"

    def test_metres_abbr(self) -> None:
        raw = "116<abbr class='unit' title='meters'> m</abbr>"
        assert strip_unit_markup(raw) == "116 m"

    def test_hour_minute_abbr(self) -> None:
        raw = (
            "1<abbr class='unit' title='hour'>h</abbr> 46<abbr class='unit' title='minute'>m</abbr>"
        )
        assert strip_unit_markup(raw) == "1h 46m"

    def test_plain_string_unchanged(self) -> None:
        assert strip_unit_markup("5.17 km") == "5.17 km"

    def test_none_returns_none(self) -> None:
        assert strip_unit_markup(None) is None

    def test_empty_string_returns_none(self) -> None:
        assert strip_unit_markup("") is None

    def test_leading_trailing_whitespace_stripped(self) -> None:
        assert strip_unit_markup("  5.17 km  ") == "5.17 km"


# ── parse_distance ────────────────────────────────────────────────────────────


class TestParseDistance:
    def test_km_to_metres(self) -> None:
        assert parse_distance("5.17 km") == pytest.approx(5170.0)

    def test_km_with_abbr_markup(self) -> None:
        raw = "5.17<abbr class='unit' title='kilometers'> km</abbr>"
        assert parse_distance(raw) == pytest.approx(5170.0)

    def test_large_km(self) -> None:
        assert parse_distance("53.24 km") == pytest.approx(53240.0)

    def test_metres_plain(self) -> None:
        assert parse_distance("116 m") == pytest.approx(116.0)

    def test_metres_with_comma_thousands(self) -> None:
        # Real feed: "1,300 m" (Swim distance)
        assert parse_distance("1,300 m") == pytest.approx(1300.0)

    def test_metres_with_abbr_markup(self) -> None:
        raw = "116<abbr class='unit' title='meters'> m</abbr>"
        assert parse_distance(raw) == pytest.approx(116.0)

    def test_sub_kilometre(self) -> None:
        assert parse_distance("0.45 km") == pytest.approx(450.0)

    def test_none_input(self) -> None:
        assert parse_distance(None) is None

    def test_empty_string(self) -> None:
        assert parse_distance("") is None

    def test_no_unit(self) -> None:
        assert parse_distance("5.17") is None

    def test_garbage_input(self) -> None:
        assert parse_distance("no distance here") is None


# ── parse_duration ────────────────────────────────────────────────────────────


class TestParseDuration:
    def test_minutes_seconds(self) -> None:
        # "41m 56s" → 41*60+56 = 2516
        raw = "41<abbr class='unit' title='minute'>m</abbr> 56<abbr class='unit' title='second'>s</abbr>"
        assert parse_duration(raw) == 2516

    def test_plain_minutes_seconds(self) -> None:
        assert parse_duration("41m 56s") == 2516

    def test_hours_minutes(self) -> None:
        raw = (
            "1<abbr class='unit' title='hour'>h</abbr> 46<abbr class='unit' title='minute'>m</abbr>"
        )
        assert parse_duration(raw) == 6360

    def test_plain_hours_minutes(self) -> None:
        assert parse_duration("1h 46m") == 6360

    def test_one_hour_zero_minutes(self) -> None:
        # Real feed: "1h 0m" (e.g. PhysicalTherapy 1h session)
        raw = (
            "1<abbr class='unit' title='hour'>h</abbr> 0<abbr class='unit' title='minute'>m</abbr>"
        )
        assert parse_duration(raw) == 3600

    def test_plain_one_hour_zero_minutes(self) -> None:
        assert parse_duration("1h 0m") == 3600

    def test_thirty_minutes(self) -> None:
        raw = "30<abbr class='unit' title='minute'>m</abbr> 0<abbr class='unit' title='second'>s</abbr>"
        assert parse_duration(raw) == 1800

    def test_five_minutes_thirty_six_seconds(self) -> None:
        assert parse_duration("5m 36s") == 336

    def test_none_input(self) -> None:
        assert parse_duration(None) is None

    def test_empty_string(self) -> None:
        assert parse_duration("") is None

    def test_no_time_components(self) -> None:
        assert parse_duration("no time here") is None


# ── parse_pace ────────────────────────────────────────────────────────────────


class TestParsePace:
    def test_per_km(self) -> None:
        # "8:06 /km" → 8*60+6 = 486 s/km
        raw = "8:06<abbr class='unit' title='minutes per kilometer'> /km</abbr>"
        result = parse_pace(raw)
        assert result is not None
        assert result[0] == 486
        assert result[1] == "s/km"

    def test_per_km_plain(self) -> None:
        result = parse_pace("8:06 /km")
        assert result is not None
        assert result == (486, "s/km")

    def test_fast_pace(self) -> None:
        result = parse_pace("5:56 /km")
        assert result is not None
        assert result[0] == 356

    def test_per_100m_swim(self) -> None:
        # "1:37 /100m" → 1*60+37 = 97 s/100m
        raw = "1:37<abbr class='unit' title='per 100 Meters'> /100m</abbr>"
        result = parse_pace(raw)
        assert result is not None
        assert result[0] == 97
        assert result[1] == "s/100m"

    def test_per_100m_plain(self) -> None:
        result = parse_pace("1:37 /100m")
        assert result == (97, "s/100m")

    def test_none_input(self) -> None:
        assert parse_pace(None) is None

    def test_no_pace_string(self) -> None:
        assert parse_pace("5.17 km") is None


class TestParsePaceKm:
    def test_extracts_km_pace(self) -> None:
        assert parse_pace_km("8:06 /km") == 486.0

    def test_swim_pace_returns_none(self) -> None:
        assert parse_pace_km("1:37 /100m") is None

    def test_none_returns_none(self) -> None:
        assert parse_pace_km(None) is None


class TestParseSwimPace:
    def test_extracts_swim_pace(self) -> None:
        assert parse_swim_pace("1:37 /100m") == 97.0

    def test_run_pace_returns_none(self) -> None:
        assert parse_swim_pace("8:06 /km") is None

    def test_none_returns_none(self) -> None:
        assert parse_swim_pace(None) is None


# ── parse_elevation ───────────────────────────────────────────────────────────


class TestParseElevation:
    def test_metres_plain(self) -> None:
        assert parse_elevation("116 m") == pytest.approx(116.0)

    def test_metres_with_abbr_markup(self) -> None:
        raw = "116<abbr class='unit' title='meters'> m</abbr>"
        assert parse_elevation(raw) == pytest.approx(116.0)

    def test_small_elevation(self) -> None:
        assert parse_elevation("9 m") == pytest.approx(9.0)

    def test_large_elevation(self) -> None:
        assert parse_elevation("320 m") == pytest.approx(320.0)

    def test_feet_converted(self) -> None:
        result = parse_elevation("100 ft")
        assert result is not None
        assert result == pytest.approx(30.48)

    def test_none_input(self) -> None:
        assert parse_elevation(None) is None

    def test_no_unit(self) -> None:
        assert parse_elevation("116") is None


# ── classify_stat ─────────────────────────────────────────────────────────────


class TestClassifyStat:
    def test_distance_label(self) -> None:
        assert classify_stat("Distance") == "distance"

    def test_distance_label_lowercase(self) -> None:
        assert classify_stat("distance") == "distance"

    def test_time_label(self) -> None:
        assert classify_stat("Time") == "time"

    def test_elev_gain_label(self) -> None:
        assert classify_stat("Elev Gain") == "elevation_gain"

    def test_elevation_gain_label(self) -> None:
        assert classify_stat("Elevation Gain") == "elevation_gain"

    def test_pace_label(self) -> None:
        assert classify_stat("Pace") == "pace"

    def test_unknown_label(self) -> None:
        assert classify_stat("Something Else") == "unknown"

    def test_swim_pace_detected_from_raw(self) -> None:
        # Even if label is generic "Pace", /100m in raw signals swim pace.
        assert classify_stat("Pace", "1:37 /100m") == "swim_pace"

    def test_run_pace_detected_from_raw(self) -> None:
        assert classify_stat("Pace", "8:06 /km") == "pace"

    def test_empty_label_unknown_with_km_raw(self) -> None:
        # /km in raw → pace even with empty label
        assert classify_stat("", "8:06 /km") == "pace"

    def test_whitespace_label_normalised(self) -> None:
        assert classify_stat("  Distance  ") == "distance"
