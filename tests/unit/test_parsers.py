"""Unit tests for parsers.py — all pure functions, no I/O."""

import pytest

from kudosy.parsers import (
    STAT_KEY_TIME,
    STAT_KEY_TOTAL_TIME,
    decode_html_entities,
    normalize_stats,
    parse_athlete_name,
    parse_distance,
    parse_duration,
)


class TestParseDistance:
    """Tests derived from the real last-run.log distance strings."""

    @pytest.mark.parametrize(
        ("raw", "expected_m"),
        [
            ("30.10 km", 30_100.0),
            ("222.02 km", 222_020.0),
            ("5.18 km", 5_180.0),
            ("1.36 km", 1_360.0),
            ("18.71 km", 18_710.0),
            ("107.45 km", 107_450.0),
            ("174.85 km", 174_850.0),
            # metres (thousands-comma)
            ("2,800 m", 2_800.0),
            ("1,000 m", 1_000.0),
            # plain metres
            ("500 m", 500.0),
            ("100 m", 100.0),
            # zero
            ("0.00 km", 0.0),
            ("0 km", 0.0),
        ],
    )
    def test_valid_distances(self, raw: str, expected_m: float) -> None:
        result = parse_distance(raw)
        assert result is not None
        assert abs(result - expected_m) < 0.1, f"{raw!r} → {result}, expected {expected_m}"

    @pytest.mark.parametrize(
        "raw",
        [
            "",
            None,
            "N/A",
            "-",
            "no distance",
        ],
    )
    def test_invalid_or_missing(self, raw: str | None) -> None:
        assert parse_distance(raw) is None  # type: ignore[arg-type]

    def test_decimal_comma_km(self) -> None:
        # European-style: "30,10 km" → should handle comma as decimal or fail gracefully
        # We define: comma as thousands separator in metres only; km always uses period
        # This is informational — currently we only see period-km in logs
        assert parse_distance("0.50 km") == 500.0

    def test_large_distance(self) -> None:
        assert parse_distance("1000.00 km") == pytest.approx(1_000_000.0)


class TestParseDuration:
    """Tests derived from the real last-run.log time strings."""

    @pytest.mark.parametrize(
        ("raw", "expected_s"),
        [
            ("1h 5m", 3_900),
            ("8h 36m", 30_960),
            ("3h 17m", 11_820),
            ("2h 20m", 8_400),
            ("4h 1m", 14_460),
            ("4h 17m", 15_420),
            ("49m 48s", 2_988),
            ("37m 11s", 2_231),
            ("30m 31s", 1_831),
            ("50m 14s", 3_014),
            ("1h 2m", 3_720),
            ("20m 0s", 1_200),
            ("7m 14s", 434),
            ("33m 2s", 1_982),
            # edge: zero
            ("0h 0m", 0),
            ("0m 0s", 0),
            # hours only (no minutes component)
            ("2h", 7_200),
            # minutes only
            ("45m", 2_700),
            # seconds only
            ("30s", 30),
        ],
    )
    def test_valid_durations(self, raw: str, expected_s: int) -> None:
        result = parse_duration(raw)
        assert result is not None
        assert result == expected_s, f"{raw!r} → {result}, expected {expected_s}"

    @pytest.mark.parametrize(
        "raw",
        [
            "",
            None,
            "N/A",
            "no time",
        ],
    )
    def test_invalid_or_missing(self, raw: str | None) -> None:
        assert parse_duration(raw) is None  # type: ignore[arg-type]


class TestNormalizeStats:
    """Tests for normalize_stats — canonical time-key normalization."""

    def test_no_time_entries_unchanged(self) -> None:
        stats = {"Distance": "10.00 km", "Avg Heart Rate": "164 bpm"}
        result = normalize_stats(stats)
        assert result == stats

    def test_single_time_entry_renamed_to_time(self) -> None:
        stats = {"Moving Time": "37m 11s", "Distance": "10.00 km"}
        result = normalize_stats(stats)
        assert result[STAT_KEY_TIME] == "37m 11s"
        assert "Moving Time" not in result

    def test_two_time_entries_moving_and_total(self) -> None:
        # Shorter = moving time, longer = total time
        stats = {"Moving Time": "37m 11s", "Elapsed Time": "45m 0s", "Distance": "10.00 km"}
        result = normalize_stats(stats)
        assert result[STAT_KEY_TIME] == "37m 11s"
        assert result[STAT_KEY_TOTAL_TIME] == "45m 0s"
        assert "Moving Time" not in result
        assert "Elapsed Time" not in result

    def test_two_time_entries_longer_second(self) -> None:
        # Order in dict doesn't matter — sort by value
        stats = {"Elapsed Time": "1h 5m", "Moving Time": "50m 0s"}
        result = normalize_stats(stats)
        assert result[STAT_KEY_TIME] == "50m 0s"
        assert result[STAT_KEY_TOTAL_TIME] == "1h 5m"

    def test_already_canonical_keys_are_idempotent(self) -> None:
        stats = {STAT_KEY_TIME: "37m 11s", STAT_KEY_TOTAL_TIME: "45m 0s"}
        result = normalize_stats(stats)
        assert result[STAT_KEY_TIME] == "37m 11s"
        assert result[STAT_KEY_TOTAL_TIME] == "45m 0s"

    def test_single_canonical_time_key_idempotent(self) -> None:
        stats = {STAT_KEY_TIME: "37m 11s", "Distance": "10.00 km"}
        result = normalize_stats(stats)
        assert result == stats

    def test_empty_stats(self) -> None:
        assert normalize_stats({}) == {}

    def test_non_time_stats_preserved(self) -> None:
        stats = {"Distance": "30.10 km", "Avg Heart Rate": "164 bpm", "Elevation": "320 m"}
        result = normalize_stats(stats)
        assert result["Distance"] == "30.10 km"
        assert result["Avg Heart Rate"] == "164 bpm"

    def test_decision_engine_reads_moving_time(self) -> None:
        """After normalization, decision.py must read stats['Time'] = moving time."""
        from kudosy.parsers import parse_duration

        stats = normalize_stats({"Bewegungszeit": "37m 11s", "Verstrichene Zeit": "45m 0s"})
        moving_secs = parse_duration(stats[STAT_KEY_TIME])
        assert moving_secs == 2231  # 37*60 + 11

    def test_zero_moving_time_two_entries(self) -> None:
        # Both are 0 → still idempotent; Time = Total Time = same value
        stats = {"Moving Time": "0h 0m", "Elapsed Time": "0h 0m"}
        result = normalize_stats(stats)
        assert STAT_KEY_TIME in result
        assert STAT_KEY_TOTAL_TIME in result


class TestDecodeHtmlEntities:
    @pytest.mark.parametrize(
        ("raw", "expected"),
        [
            ("Tom &amp; Jerry", "Tom & Jerry"),
            ("&lt;div&gt;", "<div>"),
            ("&gt;end", ">end"),
            ("say &quot;hi&quot;", 'say "hi"'),
            ("it&#39;s", "it's"),
            ("it&apos;s", "it's"),
            ("plain text", "plain text"),
            ("", ""),
            ("Köln &amp; Düsseldorf", "Köln & Düsseldorf"),
        ],
    )
    def test_entities(self, raw: str, expected: str) -> None:
        assert decode_html_entities(raw) == expected


class TestParseAthleteName:
    """HTML snippets exercising both og:title attribute orders + title fallback."""

    def test_og_title_property_first(self) -> None:
        html = '<meta property="og:title" content="Jens van Almsick | Strava-Athletenprofil">'
        assert parse_athlete_name(html) == "Jens van Almsick"

    def test_og_title_content_first(self) -> None:
        html = '<meta content="Maria Müller | Strava" property="og:title">'
        assert parse_athlete_name(html) == "Maria Müller"

    def test_title_fallback(self) -> None:
        html = "<title>Klaus Schmidt | Strava</title>"
        assert parse_athlete_name(html) == "Klaus Schmidt"

    def test_html_entities_decoded(self) -> None:
        html = '<meta property="og:title" content="Tom &amp; Jerry | Strava">'
        assert parse_athlete_name(html) == "Tom & Jerry"

    def test_strava_only_rejected(self) -> None:
        html = '<meta property="og:title" content="Strava">'
        assert parse_athlete_name(html) is None

    def test_login_page_rejected(self) -> None:
        html = "<title>Log In | Strava</title>"
        assert parse_athlete_name(html) is None

    def test_no_name_in_html(self) -> None:
        html = "<html><body><p>Some page</p></body></html>"
        assert parse_athlete_name(html) is None

    def test_empty_html(self) -> None:
        assert parse_athlete_name("") is None

    def test_multi_separator_takes_first_part(self) -> None:
        # "Name | Sport | Strava" → "Name"
        html = '<meta property="og:title" content="Franz Müller | Cycling | Strava">'
        assert parse_athlete_name(html) == "Franz Müller"

    def test_og_title_preferred_over_title(self) -> None:
        html = (
            '<meta property="og:title" content="Anna | Strava"><title>BetterName | Strava</title>'
        )
        # og:title is checked first and returns None → falls back to <title>? No:
        # "Anna" is a valid name (not "Strava", not "log in"), so og:title wins.
        assert parse_athlete_name(html) == "Anna"
