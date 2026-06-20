"""Unit tests for feed.py — StravaHtmlFeedParser."""

from __future__ import annotations

import json

from kudosy.feed import StravaHtmlFeedParser


def _parser() -> StravaHtmlFeedParser:
    return StravaHtmlFeedParser()


# ── parse() entry-point ────────────────────────────────────────────────────────


def test_parse_dict_with_entries() -> None:
    """parse() accepts a dict directly and extracts activities."""
    data = {
        "entries": [
            {
                "id": "10000000001",
                "name": "Morning Run",
                "sport_type": "Run",
                "has_kudoed": False,
                "distance": 10234.5,
                "moving_time": 2700,
                "athlete": {"id": "20000001", "name": "Alex Runner"},
            }
        ]
    }
    result = _parser().parse(data)
    assert len(result) == 1
    assert result[0].activity_id == "10000000001"
    assert result[0].athlete_name == "Alex Runner"
    assert result[0].sport_type == "Run"
    assert result[0].has_kudoed is False


def test_parse_bytes_decoded() -> None:
    """parse() decodes bytes before processing."""
    data = {"entries": []}
    payload = json.dumps(data).encode("utf-8")
    result = _parser().parse(payload)
    assert result == []


def test_parse_html_with_next_data_pattern() -> None:
    """Embedded __NEXT_DATA__ JSON is extracted and parsed."""
    entries = [
        {
            "id": "20000000001",
            "name": "Evening Ride",
            "sport_type": "Ride",
            "has_kudoed": True,
            "distance": 32000.0,
            "moving_time": 5400,
            "athlete": {"id": "20000002", "name": "Sam Cyclist"},
        }
    ]
    html = f"""<html><head></head><body>
    <script>window.__NEXT_DATA__ = {{"entries": {json.dumps(entries)}}};</script>
    </body></html>"""
    result = _parser().parse(html)
    assert len(result) == 1
    assert result[0].activity_id == "20000000001"
    assert result[0].has_kudoed is True


def test_parse_html_with_page_view_pattern() -> None:
    """Embedded pageView JSON is extracted and parsed."""
    entries = [
        {
            "id": "30000000001",
            "name": "Yoga",
            "sport_type": "Yoga",
            "has_kudoed": False,
            "athlete": {"id": "20000003", "name": "Jordan Yogi"},
        }
    ]
    html = f"""<html><head></head><body>
    <script>var pageView = {{"entries": {json.dumps(entries)}}};</script>
    </body></html>"""
    result = _parser().parse(html)
    assert len(result) == 1
    assert result[0].sport_type == "Yoga"
    assert result[0].athlete_name == "Jordan Yogi"


def test_parse_html_with_page_props_nested() -> None:
    """Nested props.pageProps.entries structure is extracted."""
    entries = [
        {
            "id": "40000000001",
            "name": "Swim",
            "sport_type": "Swim",
            "has_kudoed": False,
            "athlete": {"id": "20000004", "name": "River Swimmer"},
        }
    ]
    data = {"props": {"pageProps": {"entries": entries}}}
    html = f"""<html><head></head><body>
    <script>window.__NEXT_DATA__ = {json.dumps(data)};</script>
    </body></html>"""
    result = _parser().parse(html)
    assert len(result) == 1
    assert result[0].activity_id == "40000000001"


def test_parse_html_fallback_scraping_returns_empty() -> None:
    """Plain HTML with no embedded JSON returns [] with a logged warning."""
    html = "<html><head></head><body><p>no feed data here</p></body></html>"
    result = _parser().parse(html)
    assert result == []


def test_parse_html_invalid_json_blob_skips_gracefully() -> None:
    """Malformed JSON in hydration script falls back without crashing."""
    html = """<html><head></head><body>
    <script>window.__NEXT_DATA__ = {broken json};</script>
    </body></html>"""
    result = _parser().parse(html)
    assert isinstance(result, list)


# ── _parse_entry ───────────────────────────────────────────────────────────────


def test_parse_entry_missing_id_returns_none() -> None:
    """Entries without an id are skipped."""
    data = {"entries": [{"name": "No ID Activity", "sport_type": "Run"}]}
    result = _parser().parse(data)
    assert result == []


def test_parse_entry_distance_and_time_stats() -> None:
    """Distance and moving_time are formatted into stats dict."""
    data = {
        "entries": [
            {
                "id": "50000000001",
                "name": "Long Run",
                "sport_type": "Run",
                "has_kudoed": False,
                "distance": 21097.5,  # ~21km
                "moving_time": 6600,  # 1h 50m
                "athlete": {"id": "99", "name": "Marathon Runner"},
            }
        ]
    }
    result = _parser().parse(data)
    assert len(result) == 1
    act = result[0]
    assert "Distance" in act.stats
    assert "21.10 km" in act.stats["Distance"]
    assert "Time" in act.stats
    assert "1h" in act.stats["Time"]


def test_parse_entry_time_under_one_hour() -> None:
    """Moving time under 1 hour formatted as 'Xm Ys'."""
    data = {
        "entries": [
            {
                "id": "60000000001",
                "name": "Quick Jog",
                "sport_type": "Run",
                "has_kudoed": False,
                "moving_time": 2231,  # 37m 11s
                "athlete": {"id": "88", "name": "Speedy"},
            }
        ]
    }
    result = _parser().parse(data)
    assert result[0].stats["Time"] == "37m 11s"


def test_parse_entry_no_stats_when_no_distance_time() -> None:
    """If no distance/time fields, stats dict is empty."""
    data = {
        "entries": [
            {
                "id": "70000000001",
                "name": "Weight Training",
                "sport_type": "WeightTraining",
                "has_kudoed": False,
                "athlete": {"id": "77", "name": "Gym Rat"},
            }
        ]
    }
    result = _parser().parse(data)
    assert result[0].stats == {}


def test_parse_entry_alternate_field_names() -> None:
    """activity_id / owner / title / kudoed_by_me field variants are handled."""
    data = {
        "activities": [
            {
                "activity_id": "80000000001",
                "title": "Alternate Fields",
                "type": "Hike",
                "kudoed_by_me": True,
                "elapsed_time": 3600,
                "owner": {"athlete_id": "66", "display_name": "Field Tester"},
            }
        ]
    }
    result = _parser().parse(data)
    assert len(result) == 1
    act = result[0]
    assert act.activity_id == "80000000001"
    assert act.activity_name == "Alternate Fields"
    assert act.has_kudoed is True
    assert act.athlete_name == "Field Tester"


def test_parse_multiple_entries() -> None:
    """Multiple entries in dict are all returned."""
    entries = [
        {
            "id": str(i),
            "name": f"Activity {i}",
            "sport_type": "Run",
            "has_kudoed": False,
            "athlete": {"id": str(i + 100), "name": f"Athlete {i}"},
        }
        for i in range(1, 6)
    ]
    result = _parser().parse({"entries": entries})
    assert len(result) == 5


def test_parse_entry_bad_entry_in_list_is_skipped() -> None:
    """An unparseable entry is skipped, valid entries still returned."""
    data = {
        "entries": [
            {
                "id": "good-id",
                "athlete": {"id": "1", "name": "Good"},
                "sport_type": "Run",
                "has_kudoed": False,
                "name": "Good",
            },
            None,  # bad entry
            {"id": ""},  # empty id → skipped
        ]
    }
    result = _parser().parse(data)
    # Only the first valid entry should be returned
    assert len(result) == 1
    assert result[0].activity_id == "good-id"


def test_parse_dict_uses_feed_key() -> None:
    """'feed' key is tried when 'entries' / 'activities' are absent."""
    data = {
        "feed": [
            {
                "id": "90000000001",
                "name": "Feed Key Test",
                "sport_type": "Ride",
                "has_kudoed": False,
                "athlete": {"id": "55", "name": "Rider"},
            }
        ]
    }
    result = _parser().parse(data)
    assert len(result) == 1
    assert result[0].activity_id == "90000000001"
