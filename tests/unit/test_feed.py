"""Unit tests for feed.py — StravaHtmlFeedParser."""

from __future__ import annotations

import html
import json
from pathlib import Path

from kudosy.feed import StravaHtmlFeedParser

_FIXTURES = Path(__file__).parent.parent / "fixtures"


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


# ── data-react-props / preFetchedEntries (current Strava format) ───────────────


def _make_react_html(entries: list) -> str:
    """Wrap a preFetchedEntries list in a minimal data-react-props HTML page."""
    payload = {"appContext": {"feedProps": {"preFetchedEntries": entries}}}
    encoded = html.escape(json.dumps(payload), quote=False)
    return f"<html><body><div data-react-props='{encoded}'></div></body></html>"


def test_react_props_activity_entity() -> None:
    """Activity entity type is extracted with correct field mapping."""
    entries = [
        {
            "entity": "Activity",
            "activity": {
                "id": 11000000001,
                "activityName": "Morning Run",
                "type": "Run",
                "distance": 10234.5,
                "movingTime": 2700,
                "athlete": {"athleteId": 300000001, "athleteName": "Alex Runner"},
                "kudosAndComments": {"hasKudoed": False},
            },
        }
    ]
    result = _parser().parse(_make_react_html(entries))
    assert len(result) == 1
    act = result[0]
    assert act.activity_id == "11000000001"
    assert act.activity_name == "Morning Run"
    assert act.sport_type == "Run"
    assert act.athlete_id == "300000001"
    assert act.athlete_name == "Alex Runner"
    assert act.has_kudoed is False
    assert "Distance" in act.stats
    assert "10.23 km" in act.stats["Distance"]
    assert "Time" in act.stats
    assert "45m" in act.stats["Time"]


def test_react_props_activity_already_kudoed() -> None:
    """has_kudoed=True is correctly read from kudosAndComments.hasKudoed."""
    entries = [
        {
            "entity": "Activity",
            "activity": {
                "id": 11000000002,
                "activityName": "Evening Ride",
                "type": "Ride",
                "athlete": {"athleteId": 300000002, "athleteName": "Sam Cyclist"},
                "kudosAndComments": {"hasKudoed": True},
            },
        }
    ]
    result = _parser().parse(_make_react_html(entries))
    assert len(result) == 1
    assert result[0].has_kudoed is True


def test_react_props_group_activity_entity() -> None:
    """GroupActivity entity extracts sub-activities using snake_case fields."""
    entries = [
        {
            "entity": "GroupActivity",
            "rowData": {
                "activities": [
                    {
                        "activity_id": 11000000003,
                        "name": "Yoga Session",
                        "type": "Yoga",
                        "has_kudoed": False,
                        "athlete_id": 300000003,
                        "athlete_name": "Jordan Yogi",
                    }
                ]
            },
        }
    ]
    result = _parser().parse(_make_react_html(entries))
    assert len(result) == 1
    act = result[0]
    assert act.activity_id == "11000000003"
    assert act.activity_name == "Yoga Session"
    assert act.sport_type == "Yoga"
    assert act.athlete_name == "Jordan Yogi"
    assert act.has_kudoed is False


def test_react_props_promotion_entity_is_skipped() -> None:
    """Promotion entities are silently ignored."""
    entries = [
        {"entity": "Promotion", "promo": "some ad"},
        {
            "entity": "Activity",
            "activity": {
                "id": 11000000004,
                "activityName": "After Promo",
                "type": "Run",
                "athlete": {"athleteId": 300000004, "athleteName": "Runner"},
                "kudosAndComments": {"hasKudoed": False},
            },
        },
    ]
    result = _parser().parse(_make_react_html(entries))
    assert len(result) == 1
    assert result[0].activity_id == "11000000004"


def test_react_props_html_entity_decoding() -> None:
    """HTML entities in activity name are decoded correctly."""
    name_raw = "Run & Ride <Special>"
    entries = [
        {
            "entity": "Activity",
            "activity": {
                "id": 11000000005,
                "activityName": name_raw,
                "type": "Run",
                "athlete": {"athleteId": 300000005, "athleteName": "Tester"},
                "kudosAndComments": {"hasKudoed": False},
            },
        }
    ]
    result = _parser().parse(_make_react_html(entries))
    assert len(result) == 1
    assert result[0].activity_name == name_raw


def test_react_props_empty_entries_returns_empty_list() -> None:
    """Empty preFetchedEntries list → empty result (not None → not falling back)."""
    result = _parser().parse(_make_react_html([]))
    assert result == []


def test_react_props_no_prefetched_entries_falls_through() -> None:
    """data-react-props without preFetchedEntries falls through to pageView fallback."""
    payload = {"appContext": {"other": "stuff"}}
    encoded = html.escape(json.dumps(payload), quote=False)
    entries_for_fallback = [
        {
            "id": "99000000001",
            "name": "Fallback Run",
            "sport_type": "Run",
            "has_kudoed": False,
            "athlete": {"id": "99", "name": "Fallback Athlete"},
        }
    ]
    html_text = (
        f"<html><body>"
        f"<div data-react-props='{encoded}'></div>"
        f'<script>var pageView = {{"entries": {json.dumps(entries_for_fallback)}}};</script>'
        f"</body></html>"
    )
    result = _parser().parse(html_text)
    assert len(result) == 1
    assert result[0].activity_id == "99000000001"


def test_react_props_fixture_file() -> None:
    """Full fixture file with Activity, GroupActivity, and Promotion entries."""
    html_text = (_FIXTURES / "feed_react_props.html").read_text(encoding="utf-8")
    result = _parser().parse(html_text)
    # Activity + GroupActivity sub-entry; Promotion skipped
    assert len(result) == 3
    ids = {act.activity_id for act in result}
    assert "10000000001" in ids
    assert "10000000002" in ids
    assert "10000000003" in ids
    # Check has_kudoed mapping
    by_id = {act.activity_id: act for act in result}
    assert by_id["10000000001"].has_kudoed is False
    assert by_id["10000000002"].has_kudoed is True
    assert by_id["10000000003"].has_kudoed is False


def test_react_props_stats_from_structured_list() -> None:
    """stats list [{label, value}] is used when present."""
    entries = [
        {
            "entity": "Activity",
            "activity": {
                "id": 11000000006,
                "activityName": "Stats Run",
                "type": "Run",
                "athlete": {"athleteId": 300000006, "athleteName": "Stats Athlete"},
                "kudosAndComments": {"hasKudoed": False},
                "stats": [
                    {"label": "Distance", "value": "15.00 km"},
                    {"label": "Time", "value": "1h 12m"},
                ],
            },
        }
    ]
    result = _parser().parse(_make_react_html(entries))
    assert len(result) == 1
    assert result[0].stats == {"Distance": "15.00 km", "Time": "1h 12m"}


def test_react_props_camel_case_moving_time() -> None:
    """movingTime (camelCase) is handled as numeric fallback for stats."""
    entries = [
        {
            "entity": "Activity",
            "activity": {
                "id": 11000000007,
                "activityName": "Camel Run",
                "type": "Run",
                "movingTime": 3600,  # camelCase
                "athlete": {"athleteId": 300000007, "athleteName": "Camel Runner"},
                "kudosAndComments": {"hasKudoed": False},
            },
        }
    ]
    result = _parser().parse(_make_react_html(entries))
    assert len(result) == 1
    assert "Time" in result[0].stats
    assert "1h" in result[0].stats["Time"]
