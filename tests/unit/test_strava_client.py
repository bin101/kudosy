"""Unit tests for strava_client parsing helpers.

Tests cover the pure module-level functions _extract_search_results and
_parse_athlete_search_results only — no network calls, no StravaClient instance.
"""

from __future__ import annotations

import json
from pathlib import Path

from kudosy.strava_client import _extract_search_results, _parse_athlete_search_results

FIXTURE_DIR = Path(__file__).parent.parent / "fixtures"


def _fixture_html() -> str:
    return (FIXTURE_DIR / "athlete_search.html").read_text(encoding="utf-8")


# ── _extract_search_results ───────────────────────────────────────────────────


def test_extract_search_results_from_fixture() -> None:
    """Happy path: extracts all athlete dicts from a well-formed page."""
    results = _extract_search_results(_fixture_html())
    # Fixture has 3 raw items (one with id=0 which is valid at this stage)
    assert len(results) == 3
    assert results[0]["id"] == 11111111
    assert results[0]["name"] == "Alice Example"
    assert results[1]["id"] == 22222222


def test_extract_search_results_empty_html() -> None:
    assert _extract_search_results("") == []


def test_extract_search_results_no_next_data() -> None:
    assert _extract_search_results("<html><body>Nothing here</body></html>") == []


def test_extract_search_results_broken_json() -> None:
    html = '<script id="__NEXT_DATA__" type="application/json">{bad json</script>'
    assert _extract_search_results(html) == []


def test_extract_search_results_missing_search_results_key() -> None:
    """__NEXT_DATA__ present but searchResults key absent -> []."""
    payload = {"props": {"pageProps": {"otherKey": []}}}
    html = f'<script id="__NEXT_DATA__" type="application/json">{json.dumps(payload)}</script>'
    assert _extract_search_results(html) == []


def test_extract_search_results_search_results_not_list() -> None:
    payload = {"props": {"pageProps": {"searchResults": {"unexpected": "dict"}}}}
    html = f'<script id="__NEXT_DATA__" type="application/json">{json.dumps(payload)}</script>'
    assert _extract_search_results(html) == []


# ── _parse_athlete_search_results ─────────────────────────────────────────────


def test_parse_maps_real_strava_fields() -> None:
    """Verifies the actual field names from the HAR capture (id, name, picture)."""
    raw = [
        {
            "id": 54325058,
            "firstname": "Alice",
            "name": "Alice Example",
            "picture": "https://example.com/avatars/large.jpg",
            "location": "Berlin",
        }
    ]
    results = _parse_athlete_search_results(raw)
    assert len(results) == 1
    r = results[0]
    assert r["id"] == "54325058"
    assert r["name"] == "Alice Example"
    assert r["avatarUrl"] == "https://example.com/avatars/large.jpg"


def test_parse_full_pipeline_from_fixture() -> None:
    """End-to-end: fixture HTML -> extract -> parse -> normalised dicts."""
    raw = _extract_search_results(_fixture_html())
    results = _parse_athlete_search_results(raw)
    # id=0 item is skipped by the parser
    assert len(results) == 2
    assert results[0] == {
        "id": "11111111",
        "name": "Alice Example",
        "avatarUrl": "https://example.com/avatars/11111111/large.jpg",
    }
    assert results[1] == {
        "id": "22222222",
        "name": "Bob Sample",
        "avatarUrl": "https://example.com/avatars/22222222/large.jpg",
    }


def test_parse_skips_zero_id() -> None:
    raw = [{"id": 0, "name": "Nobody", "picture": ""}]
    assert _parse_athlete_search_results(raw) == []


def test_parse_skips_missing_id() -> None:
    raw = [{"name": "No ID at all", "picture": ""}]
    assert _parse_athlete_search_results(raw) == []


def test_parse_uses_firstname_when_name_absent() -> None:
    raw = [{"id": 99, "firstname": "OnlyFirst", "picture": ""}]
    results = _parse_athlete_search_results(raw)
    assert results[0]["name"] == "OnlyFirst"


def test_parse_avatar_fallback_to_profile_medium() -> None:
    """When 'picture' absent, fall back to legacy 'profile_medium' field."""
    raw = [{"id": 7, "name": "Bob", "profile_medium": "https://cdn.example.com/p.jpg"}]
    results = _parse_athlete_search_results(raw)
    assert results[0]["avatarUrl"] == "https://cdn.example.com/p.jpg"


def test_parse_avatar_fallback_to_avatar_url() -> None:
    """When 'picture' and 'profile_medium' absent, use 'avatar_url'."""
    raw = [{"id": 8, "name": "Carol", "avatar_url": "https://cdn.example.com/a.jpg"}]
    results = _parse_athlete_search_results(raw)
    assert results[0]["avatarUrl"] == "https://cdn.example.com/a.jpg"


def test_parse_empty_avatar_returns_empty_string() -> None:
    raw = [{"id": 9, "name": "Dave"}]
    results = _parse_athlete_search_results(raw)
    assert results[0]["avatarUrl"] == ""


def test_parse_wrapped_dict_with_athletes_key() -> None:
    """Legacy shape: {'athletes': [...]} — kept for forward-compat."""
    data = {"athletes": [{"id": 5, "name": "Eve", "picture": ""}]}
    results = _parse_athlete_search_results(data)
    assert len(results) == 1
    assert results[0]["id"] == "5"


def test_parse_invalid_type_returns_empty() -> None:
    assert _parse_athlete_search_results(None) == []  # type: ignore[arg-type]
    assert _parse_athlete_search_results(42) == []  # type: ignore[arg-type]
    assert _parse_athlete_search_results("oops") == []  # type: ignore[arg-type]


def test_parse_non_dict_items_are_skipped() -> None:
    raw: list = [{"id": 1, "name": "A", "picture": ""}, "garbage", 99, None]
    results = _parse_athlete_search_results(raw)
    assert len(results) == 1
    assert results[0]["id"] == "1"
