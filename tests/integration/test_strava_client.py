"""Integration tests for strava_client.py — uses respx to mock httpx calls."""

from __future__ import annotations

import itertools
import json
import random
from collections.abc import Callable
from pathlib import Path
from unittest.mock import AsyncMock

import httpx
import pytest
import respx

from kudosy.feed import AuthError, RateLimitError, StructuredFeedParser
from kudosy.strava_client import _NEXT_DATA_RE, StravaClient, _next_cursor_params, _parse_next_data

# Fixtures directory
_FIXTURES = Path(__file__).parent.parent / "fixtures"


# Synthetic 86-char URL-safe Base64 token, the size of a real Strava CSRF token.
_TOKEN = "Zm9vYmFyLXN5bnRoZXRpYy1jc3JmLXRva2VuLW5vdC1yZWFsLTAxMjM0NTY3ODlBQkNERUZHSElKS0xNTk9QUVJTVFVWV1hZ"


def _load(name: str) -> str:
    return (_FIXTURES / name).read_text(encoding="utf-8")


# ── get_csrf_token ─────────────────────────────────────────────────────────────


@pytest.mark.asyncio
@respx.mock
async def test_get_csrf_token_success() -> None:
    html = _load("rails_dashboard_legacy.html")
    respx.get("https://www.strava.com/dashboard").mock(return_value=httpx.Response(200, text=html))

    client = StravaClient({"_strava4_session": "test-cookie-value"})
    token = await client.get_csrf_token()
    await client.aclose()

    assert token == _TOKEN


@pytest.mark.asyncio
@respx.mock
async def test_get_csrf_token_missing_raises() -> None:
    respx.get("https://www.strava.com/dashboard").mock(
        return_value=httpx.Response(200, text="<html><head></head><body>no csrf</body></html>")
    )
    respx.get("https://www.strava.com/frontend/athletes/current").mock(
        return_value=httpx.Response(200, json={})
    )
    respx.get("https://www.strava.com/athlete/training").mock(
        return_value=httpx.Response(200, text="<html></html>")
    )

    client = StravaClient({"_strava4_session": "test-cookie-value"})
    with pytest.raises(RuntimeError, match="CSRF"):
        await client.get_csrf_token()
    await client.aclose()


@pytest.mark.asyncio
@respx.mock
async def test_get_csrf_token_login_redirect_raises_auth_error() -> None:
    """When the resolved URL is a login page, _check_auth raises AuthError."""
    client = StravaClient({"_strava4_session": "expired-cookie"})
    login_resp = httpx.Response(
        200,
        text="<html>login</html>",
        request=httpx.Request("GET", "https://www.strava.com/login"),
    )
    with pytest.raises(AuthError):
        client._check_auth(login_resp)


@pytest.mark.asyncio
async def test_check_auth_raises_on_login_url() -> None:
    client = StravaClient({"_strava4_session": "bad-cookie"})
    resp = httpx.Response(
        200,
        text="",
        request=httpx.Request("GET", "https://www.strava.com/login"),
    )
    with pytest.raises(AuthError):
        client._check_auth(resp)


@pytest.mark.asyncio
async def test_check_auth_raises_on_401() -> None:
    client = StravaClient({"_strava4_session": "bad-cookie"})
    resp = httpx.Response(
        401,
        text="Unauthorized",
        request=httpx.Request("GET", "https://www.strava.com/dashboard"),
    )
    with pytest.raises(AuthError, match="401"):
        client._check_auth(resp)


# ── fetch_current_athlete_id ──────────────────────────────────────────────────


@pytest.mark.asyncio
@respx.mock
async def test_fetch_current_athlete_id_success() -> None:
    respx.get("https://www.strava.com/frontend/athletes/current").mock(
        return_value=httpx.Response(200, json={"currentAthlete": {"id_str": "20000001"}})
    )
    client = StravaClient({"_strava4_session": "test-cookie-value"})
    athlete_id = await client.fetch_current_athlete_id()
    await client.aclose()
    assert athlete_id == "20000001"


@pytest.mark.asyncio
@respx.mock
async def test_fetch_current_athlete_id_falls_back_to_numeric_id() -> None:
    """id_str absent → falls back to the numeric `id` field, stringified."""
    respx.get("https://www.strava.com/frontend/athletes/current").mock(
        return_value=httpx.Response(200, json={"currentAthlete": {"id": 20000002}})
    )
    client = StravaClient({"_strava4_session": "test-cookie-value"})
    athlete_id = await client.fetch_current_athlete_id()
    await client.aclose()
    assert athlete_id == "20000002"


@pytest.mark.asyncio
@respx.mock
async def test_fetch_current_athlete_id_auth_error_propagates() -> None:
    """An expired cookie must raise AuthError, not be swallowed into None —
    the caller (run_kudos / GET /api/feed) needs it to report auth failure."""
    respx.get("https://www.strava.com/frontend/athletes/current").mock(
        return_value=httpx.Response(401, text="Unauthorized")
    )
    client = StravaClient({"_strava4_session": "expired-cookie"})
    with pytest.raises(AuthError):
        await client.fetch_current_athlete_id()
    await client.aclose()


@pytest.mark.asyncio
@respx.mock
async def test_fetch_current_athlete_id_malformed_json_returns_none() -> None:
    """Any non-auth error (e.g. malformed response) is swallowed → None."""
    respx.get("https://www.strava.com/frontend/athletes/current").mock(
        return_value=httpx.Response(200, text="not json")
    )
    client = StravaClient({"_strava4_session": "test-cookie-value"})
    athlete_id = await client.fetch_current_athlete_id()
    await client.aclose()
    assert athlete_id is None


# ── _get_with_retry ───────────────────────────────────────────────────────────


@pytest.mark.asyncio
@respx.mock
async def test_get_with_retry_recovers_after_transient_network_error() -> None:
    """A ConnectError on the first attempt is retried and can still succeed."""
    respx.get("https://www.strava.com/frontend/athletes/current").mock(
        side_effect=[
            httpx.ConnectError("boom"),
            httpx.Response(200, json={"currentAthlete": {"id_str": "20000003"}}),
        ]
    )
    client = StravaClient({"_strava4_session": "test-cookie-value"}, sleep=AsyncMock())
    athlete_id = await client.fetch_current_athlete_id()
    await client.aclose()
    assert athlete_id == "20000003"


@pytest.mark.asyncio
@respx.mock
async def test_get_with_retry_gives_up_after_max_attempts() -> None:
    """Persistent network failure exhausts retries — the caller still sees a
    clean outcome (fetch_current_athlete_id swallows it into None)."""
    respx.get("https://www.strava.com/frontend/athletes/current").mock(
        side_effect=httpx.ConnectError("boom")
    )
    client = StravaClient({"_strava4_session": "test-cookie-value"}, sleep=AsyncMock())
    athlete_id = await client.fetch_current_athlete_id()
    await client.aclose()
    assert athlete_id is None
    # 3 attempts total (see _GET_RETRY_ATTEMPTS), not an unbounded retry loop.
    assert respx.calls.call_count == 3


# ── fetch_following_feed ───────────────────────────────────────────────────────


@pytest.mark.asyncio
@respx.mock
async def test_fetch_feed_returns_json_dict() -> None:
    """fetch_following_feed calls the JSON XHR endpoint and returns a parsed dict."""
    feed_payload = {"entries": [], "pagination": {"hasMore": False}}
    respx.get("https://www.strava.com/dashboard/feed").mock(
        return_value=httpx.Response(200, json=feed_payload)
    )

    client = StravaClient({"_strava4_session": "test-cookie-value"})
    result = await client.fetch_following_feed("20000001")
    await client.aclose()

    assert isinstance(result, dict)
    assert "entries" in result
    assert result["entries"] == []


@pytest.mark.asyncio
@respx.mock
async def test_fetch_feed_passes_athlete_id_param() -> None:
    """fetch_following_feed includes athlete_id and feed_type as query parameters."""
    respx.get("https://www.strava.com/dashboard/feed").mock(
        return_value=httpx.Response(200, json={"entries": []})
    )

    client = StravaClient({"_strava4_session": "test-cookie-value"})
    await client.fetch_following_feed("99887766")
    await client.aclose()

    params = respx.calls.last.request.url.params
    assert params["feed_type"] == "following"
    assert params["athlete_id"] == "99887766"


@pytest.mark.asyncio
@respx.mock
async def test_fetch_feed_sends_accept_language_en() -> None:
    """fetch_following_feed sends Accept-Language: en to force English stat labels."""
    respx.get("https://www.strava.com/dashboard/feed").mock(
        return_value=httpx.Response(200, json={"entries": []})
    )

    client = StravaClient({"_strava4_session": "test-cookie-value"})
    await client.fetch_following_feed("20000001")
    await client.aclose()

    headers = respx.calls.last.request.headers
    assert headers.get("accept-language") == "en"


@pytest.mark.asyncio
@respx.mock
async def test_fetch_feed_auth_redirect_raises() -> None:
    """An expired cookie on the feed endpoint raises AuthError (HTTP 401)."""
    respx.get("https://www.strava.com/dashboard/feed").mock(
        return_value=httpx.Response(401, text="Unauthorized")
    )

    client = StravaClient({"_strava4_session": "expired-cookie"})
    with pytest.raises(AuthError):
        await client.fetch_following_feed("20000001")
    await client.aclose()


# ── send_kudos ────────────────────────────────────────────────────────────────


@pytest.mark.asyncio
@respx.mock
async def test_send_kudos_success() -> None:
    respx.post("https://www.strava.com/feed/activity/10000000001/kudo").mock(
        return_value=httpx.Response(200, text="")
    )

    client = StravaClient({"_strava4_session": "test-cookie-value"})
    result = await client.send_kudos("10000000001", "test-csrf-abc123")
    await client.aclose()

    assert result is True


@pytest.mark.asyncio
@respx.mock
async def test_send_kudos_rate_limit_raises() -> None:
    respx.post("https://www.strava.com/feed/activity/10000000002/kudo").mock(
        return_value=httpx.Response(429, text="Rate limited")
    )

    client = StravaClient({"_strava4_session": "test-cookie-value"})
    with pytest.raises(RateLimitError):
        await client.send_kudos("10000000002", "csrf")
    await client.aclose()


@pytest.mark.asyncio
@respx.mock
async def test_send_kudos_network_error_returns_false() -> None:
    respx.post("https://www.strava.com/feed/activity/10000000003/kudo").mock(
        side_effect=httpx.ConnectError("Connection refused")
    )

    client = StravaClient({"_strava4_session": "test-cookie-value"})
    result = await client.send_kudos("10000000003", "csrf")
    await client.aclose()

    assert result is False


# ── lookup_athlete ─────────────────────────────────────────────────────────────


@pytest.mark.asyncio
@respx.mock
async def test_lookup_athlete_success() -> None:
    html = _load("athlete_page.html")
    respx.get("https://www.strava.com/athletes/20000001").mock(
        return_value=httpx.Response(200, text=html)
    )

    client = StravaClient({"_strava4_session": "test-cookie-value"})
    name = await client.lookup_athlete("20000001")
    await client.aclose()

    assert name == "Alex Runner"


@pytest.mark.asyncio
@respx.mock
async def test_lookup_athlete_not_found_returns_none() -> None:
    respx.get("https://www.strava.com/athletes/99999999").mock(
        return_value=httpx.Response(404, text="Not Found")
    )

    client = StravaClient({"_strava4_session": "test-cookie-value"})
    name = await client.lookup_athlete("99999999")
    await client.aclose()

    assert name is None


@pytest.mark.asyncio
@respx.mock
async def test_lookup_athlete_network_error_returns_none() -> None:
    """A transient network failure must degrade to None, not raise — the
    caller (GET /api/athletes/{id}) has no other fallback for this lookup."""
    respx.get("https://www.strava.com/athletes/20000001").mock(
        side_effect=httpx.ConnectError("boom")
    )

    client = StravaClient({"_strava4_session": "test-cookie-value"})
    name = await client.lookup_athlete("20000001")
    await client.aclose()

    assert name is None


# ── search_athletes ────────────────────────────────────────────────────────────


@pytest.mark.asyncio
@respx.mock
async def test_search_athletes_success_from_fixture() -> None:
    html = _load("athlete_search.html")
    respx.get("https://www.strava.com/athletes/search").mock(
        return_value=httpx.Response(200, text=html)
    )

    client = StravaClient({"_strava4_session": "test-cookie-value"})
    results = await client.search_athletes("Alex")
    await client.aclose()

    assert len(results) > 0
    assert all({"id", "name", "avatarUrl"} <= result.keys() for result in results)


@pytest.mark.asyncio
@respx.mock
async def test_search_athletes_auth_error_propagates() -> None:
    respx.get("https://www.strava.com/athletes/search").mock(
        return_value=httpx.Response(401, text="Unauthorized")
    )

    client = StravaClient({"_strava4_session": "expired-cookie"})
    with pytest.raises(AuthError):
        await client.search_athletes("Alex")
    await client.aclose()


@pytest.mark.asyncio
@respx.mock
async def test_search_athletes_non_success_status_returns_empty_list() -> None:
    respx.get("https://www.strava.com/athletes/search").mock(
        return_value=httpx.Response(500, text="Internal Server Error")
    )

    client = StravaClient({"_strava4_session": "test-cookie-value"})
    results = await client.search_athletes("Alex")
    await client.aclose()

    assert results == []


@pytest.mark.asyncio
@respx.mock
async def test_search_athletes_network_error_returns_empty_list() -> None:
    respx.get("https://www.strava.com/athletes/search").mock(side_effect=httpx.ConnectError("boom"))

    client = StravaClient({"_strava4_session": "test-cookie-value"})
    results = await client.search_athletes("Alex")
    await client.aclose()

    assert results == []


# ── _mask_cookie ──────────────────────────────────────────────────────────────


def test_mask_cookie_truncates() -> None:
    from kudosy.strava_client import _mask_cookie

    assert _mask_cookie("abcdefghijklmnop") == "abcdefgh…"


def test_mask_cookie_short_returns_stars() -> None:
    from kudosy.strava_client import _mask_cookie

    assert _mask_cookie("abc") == "***"


# ── _next_cursor_params (unit) ────────────────────────────────────────────────


def test_next_cursor_params_returns_before_and_cursor() -> None:
    """Extracts before/cursor from the last entry's cursorData."""
    entries = [
        {"entity": "Activity", "cursorData": {"updated_at": 1000, "rank": 5000.9}},
        {"entity": "Activity", "cursorData": {"updated_at": 900, "rank": 4000.1}},
    ]
    result = _next_cursor_params(entries)
    assert result == {"before": 900, "cursor": 4000}


def test_next_cursor_params_empty_returns_none() -> None:
    assert _next_cursor_params([]) is None


def test_next_cursor_params_missing_cursor_data_returns_none() -> None:
    entries = [{"entity": "Activity"}]
    assert _next_cursor_params(entries) is None


def test_next_cursor_params_partial_cursor_data_returns_none() -> None:
    entries = [{"entity": "Activity", "cursorData": {"updated_at": 1000}}]
    assert _next_cursor_params(entries) is None


def test_next_cursor_params_non_numeric_values_returns_none() -> None:
    """A Strava format drift (non-numeric cursorData) must abort pagination
    gracefully rather than raising ValueError out of fetch_following_feed."""
    entries = [{"entity": "Activity", "cursorData": {"updated_at": "not-a-number", "rank": 5000.9}}]
    assert _next_cursor_params(entries) is None


# ── fetch_following_feed — pagination ────────────────────────────────────────


def _act_entry(
    act_id: int | str, rank: float = 9000.0, updated_at: int = 1000, locale: str | None = None
) -> dict:
    """Build a minimal Activity feed entry with cursorData."""
    return {
        **({"locale": locale} if locale else {}),
        "entity": "Activity",
        "activity": {"id": act_id, "activityName": f"Run {act_id}"},
        "cursorData": {"updated_at": updated_at, "rank": rank},
    }


def _page(entries: list, has_more: bool) -> dict:
    return {"entries": entries, "pagination": {"hasMore": has_more}}


@pytest.mark.asyncio
@respx.mock
async def test_fetch_feed_merges_multiple_pages() -> None:
    """Three pages are fetched and all activities appear in the merged result."""
    page1 = _page([_act_entry(1, rank=9000.0, updated_at=1800)], has_more=True)
    page2 = _page([_act_entry(2, rank=8000.0, updated_at=1700)], has_more=True)
    page3 = _page([_act_entry(3, rank=7000.0, updated_at=1600)], has_more=False)

    respx.get("https://www.strava.com/dashboard/feed").mock(
        side_effect=[
            httpx.Response(200, json=page1),
            httpx.Response(200, json=page2),
            httpx.Response(200, json=page3),
        ]
    )

    client = StravaClient({"_strava4_session": "cookie"}, sleep=AsyncMock(), rng=random.Random(0))
    result = await client.fetch_following_feed("111")
    await client.aclose()

    ids = [e["activity"]["id"] for e in result["entries"] if e.get("entity") == "Activity"]
    assert ids == [1, 2, 3]
    assert len(respx.calls) == 3


@pytest.mark.asyncio
@respx.mock
async def test_fetch_feed_stops_on_hasmore_false() -> None:
    """A single page with hasMore=false triggers exactly one request."""
    page1 = _page([_act_entry(1)], has_more=False)

    respx.get("https://www.strava.com/dashboard/feed").mock(
        return_value=httpx.Response(200, json=page1)
    )

    client = StravaClient({"_strava4_session": "cookie"}, sleep=AsyncMock(), rng=random.Random(0))
    result = await client.fetch_following_feed("111")
    await client.aclose()

    assert len(respx.calls) == 1
    assert not result["pagination"]["hasMore"]


@pytest.mark.asyncio
@respx.mock
async def test_fetch_feed_stops_at_max_pages() -> None:
    """Loop stops at the target-derived page cap even when hasMore stays true forever."""
    from kudosy.strava_client import _feed_page_cap

    max_pages = _feed_page_cap(100)
    infinite_page = _page([_act_entry(1, rank=9000.0, updated_at=1800)], has_more=True)

    # Provide more responses than the cap — only _FEED_MAX_PAGES should be consumed
    respx.get("https://www.strava.com/dashboard/feed").mock(
        side_effect=[httpx.Response(200, json=infinite_page)] * (max_pages + 2)
    )

    client = StravaClient({"_strava4_session": "cookie"}, sleep=AsyncMock(), rng=random.Random(0))
    await client.fetch_following_feed("111")
    await client.aclose()

    assert len(respx.calls) == max_pages


@pytest.mark.asyncio
@respx.mock
async def test_fetch_feed_first_request_has_no_cursor() -> None:
    """The very first page request carries only feed_type and athlete_id."""
    page1 = _page([_act_entry(1)], has_more=False)

    respx.get("https://www.strava.com/dashboard/feed").mock(
        return_value=httpx.Response(200, json=page1)
    )

    client = StravaClient({"_strava4_session": "cookie"}, sleep=AsyncMock(), rng=random.Random(0))
    await client.fetch_following_feed("42")
    await client.aclose()

    first_params = dict(respx.calls[0].request.url.params)
    assert first_params == {"feed_type": "following", "athlete_id": "42"}


@pytest.mark.asyncio
@respx.mock
async def test_fetch_feed_passes_cursor_on_second_page() -> None:
    """Second request includes before/cursor derived from last entry's cursorData."""
    page1 = _page([_act_entry(1, rank=9001.7, updated_at=1777)], has_more=True)
    page2 = _page([_act_entry(2, rank=8000.0, updated_at=1600)], has_more=False)

    respx.get("https://www.strava.com/dashboard/feed").mock(
        side_effect=[
            httpx.Response(200, json=page1),
            httpx.Response(200, json=page2),
        ]
    )

    client = StravaClient({"_strava4_session": "cookie"}, sleep=AsyncMock(), rng=random.Random(0))
    await client.fetch_following_feed("42")
    await client.aclose()

    second_params = dict(respx.calls[1].request.url.params)
    assert second_params["before"] == "1777"
    assert second_params["cursor"] == "9001"  # int(9001.7)
    assert second_params["feed_type"] == "following"
    assert second_params["athlete_id"] == "42"


@pytest.mark.asyncio
@respx.mock
async def test_fetch_feed_deduplicates_activities() -> None:
    """Same activity id on two pages appears only once in the merged result."""
    page1 = _page([_act_entry(99, rank=9000.0, updated_at=1800)], has_more=True)
    page2 = _page(
        [
            _act_entry(99, rank=8000.0, updated_at=1700),  # duplicate
            _act_entry(100, rank=7000.0, updated_at=1600),
        ],
        has_more=False,
    )

    respx.get("https://www.strava.com/dashboard/feed").mock(
        side_effect=[
            httpx.Response(200, json=page1),
            httpx.Response(200, json=page2),
        ]
    )

    client = StravaClient({"_strava4_session": "cookie"}, sleep=AsyncMock(), rng=random.Random(0))
    result = await client.fetch_following_feed("42")
    await client.aclose()

    ids = [e["activity"]["id"] for e in result["entries"] if e.get("entity") == "Activity"]
    assert ids == [99, 100]


@pytest.mark.asyncio
@respx.mock
async def test_fetch_feed_stops_gracefully_when_cursor_data_missing() -> None:
    """Missing cursorData on the last entry stops pagination cleanly despite hasMore=true."""
    page1 = _page(
        [{"entity": "Activity", "activity": {"id": 1}}],  # no cursorData
        has_more=True,
    )

    respx.get("https://www.strava.com/dashboard/feed").mock(
        return_value=httpx.Response(200, json=page1)
    )

    client = StravaClient({"_strava4_session": "cookie"}, sleep=AsyncMock(), rng=random.Random(0))
    result = await client.fetch_following_feed("42")
    await client.aclose()

    assert len(respx.calls) == 1
    assert len(result["entries"]) == 1


@pytest.mark.asyncio
@respx.mock
async def test_fetch_feed_sleep_called_between_pages() -> None:
    """One pause before the first XHR page, then one between each following XHR page."""
    page1 = _page([_act_entry(1, rank=9000.0, updated_at=1800)], has_more=True)
    page2 = _page([_act_entry(2, rank=8000.0, updated_at=1700)], has_more=True)
    page3 = _page([_act_entry(3, rank=7000.0, updated_at=1600)], has_more=False)

    respx.get("https://www.strava.com/dashboard/feed").mock(
        side_effect=[
            httpx.Response(200, json=page1),
            httpx.Response(200, json=page2),
            httpx.Response(200, json=page3),
        ]
    )

    mock_sleep = AsyncMock()
    client = StravaClient({"_strava4_session": "cookie"}, sleep=mock_sleep, rng=random.Random(0))
    await client.fetch_following_feed("42")
    await client.aclose()

    # 3 XHR pages → 1 initial pause + 2 between pages (none after the last)
    assert mock_sleep.call_count == 3


def _embedded_with(entries: list, *, has_more: bool = False) -> str:
    def mutate(data: dict) -> None:
        data["props"]["pageProps"]["dashboardData"]["feed"] = {
            "entries": [{**e, "feedType": "following"} for e in entries],
            "pagination": {"hasMore": has_more},
        }

    return _nextjs_dashboard(mutate=mutate)


@pytest.mark.asyncio
@respx.mock
async def test_embedded_has_more_false_still_fetches_xhr_page_2() -> None:
    _mock_nextjs_dashboard(_embedded_with([_act_entry(1, rank=500.5, updated_at=900)]))
    xhr = respx.get(_FEED).mock(
        return_value=httpx.Response(200, json=_page([_act_entry(2)], has_more=False))
    )
    client = StravaClient(_FULL_COOKIES, sleep=AsyncMock(), rng=random.Random(0))
    await client.get_csrf_token()
    result = await client.fetch_following_feed("20000001")
    await client.aclose()
    assert xhr.call_count == 1
    assert [e["activity"]["id"] for e in result["entries"]] == [1, 2]


@pytest.mark.asyncio
@respx.mock
async def test_before_is_running_minimum_across_pages_and_cursor_is_last_rank() -> None:
    # updated_at is not sorted; the minimum (100) sits in the embedded page.
    _mock_nextjs_dashboard(
        _embedded_with(
            [_act_entry(1, rank=900, updated_at=100), _act_entry(2, rank=800.9, updated_at=500)]
        )
    )
    xhr = respx.get(_FEED).mock(
        side_effect=[
            httpx.Response(
                200,
                json=_page(
                    [
                        _act_entry(3, rank=700, updated_at=400),
                        _act_entry(4, rank=650.2, updated_at=600),
                    ],
                    has_more=True,
                ),
            ),
            httpx.Response(200, json=_page([_act_entry(5)], has_more=False)),
        ]
    )
    client = StravaClient(_FULL_COOKIES, sleep=AsyncMock(), rng=random.Random(0))
    await client.get_csrf_token()
    await client.fetch_following_feed("20000001")
    await client.aclose()
    first, second = (dict(c.request.url.params) for c in xhr.calls)
    assert (first["before"], first["cursor"]) == ("100", "800")  # int(800.9)
    assert (second["before"], second["cursor"]) == ("100", "650")  # int(650.2)


@pytest.mark.asyncio
@respx.mock
async def test_feed_xhr_sends_csrf_header_only_when_token_known() -> None:
    respx.get(_DASHBOARD).mock(return_value=httpx.Response(200, text=_CSRF_HTML))
    xhr = respx.get(_FEED).mock(
        return_value=httpx.Response(200, json=_page([_act_entry(1)], False))
    )
    client = StravaClient(_FULL_COOKIES, sleep=AsyncMock(), rng=random.Random(0))
    await client.get_csrf_token()
    await client.fetch_following_feed("1")
    await client.aclose()
    assert xhr.calls.last.request.headers["x-csrf-token"] == _TOKEN

    xhr.reset()
    anonymous = StravaClient(_FULL_COOKIES, sleep=AsyncMock(), rng=random.Random(0))
    await anonymous.fetch_following_feed("1")
    await anonymous.aclose()
    assert "x-csrf-token" not in xhr.calls.last.request.headers


@pytest.mark.asyncio
@respx.mock
async def test_embedded_page_without_cursor_data_stops_gracefully() -> None:
    _mock_nextjs_dashboard(_embedded_with([{"entity": "Activity", "activity": {"id": 1}}]))
    xhr = respx.get(_FEED).mock(return_value=httpx.Response(200, json=_page([], False)))
    client = StravaClient(_FULL_COOKIES, sleep=AsyncMock(), rng=random.Random(0))
    await client.get_csrf_token()
    result = await client.fetch_following_feed("20000001")
    await client.aclose()
    assert not xhr.called
    assert len(result["entries"]) == 1


@pytest.mark.asyncio
@respx.mock
async def test_send_kudos_has_no_content_type_and_no_body() -> None:
    route = respx.post("https://www.strava.com/feed/activity/1/kudo").mock(
        return_value=httpx.Response(200, text="")
    )
    client = StravaClient({"_strava4_session": "c"})
    await client.send_kudos("1", "tok")
    await client.aclose()
    req = route.calls.last.request
    assert "content-type" not in req.headers
    assert req.content == b""
    assert req.headers["accept"] == "application/json, text/plain, */*"
    assert req.headers["x-csrf-token"] == "tok"
    assert req.headers["x-requested-with"] == "XMLHttpRequest"


# ── Cookie jar, rotation & auth diagnostics ───────────────────────────────────

_CSRF_HTML = f'<html><head><meta name="csrf-token" content="{_TOKEN}"></head></html>'
_FULL_COOKIES = {
    "_strava4_session": "sess-old-0123456789",
    "strava_remember_id": "4242",
    "strava_remember_token": "remember-secret-token",
}


@pytest.mark.asyncio
@respx.mock
async def test_all_cookies_are_sent() -> None:
    route = respx.get("https://www.strava.com/dashboard").mock(
        return_value=httpx.Response(200, text=_CSRF_HTML)
    )
    client = StravaClient(_FULL_COOKIES)
    await client.get_csrf_token()
    await client.aclose()

    sent = route.calls[0].request.headers["cookie"]
    for name, value in _FULL_COOKIES.items():
        assert f"{name}={value}" in sent


@pytest.mark.asyncio
@respx.mock
async def test_set_cookie_rotation_is_sent_next_and_exposed() -> None:
    respx.get("https://www.strava.com/dashboard").mock(
        return_value=httpx.Response(
            200,
            text=_CSRF_HTML,
            headers={"Set-Cookie": "_strava4_session=sess-new; Domain=.strava.com; Path=/"},
        )
    )
    athlete = respx.get("https://www.strava.com/frontend/athletes/current").mock(
        return_value=httpx.Response(200, json={"currentAthlete": {"id_str": "1"}})
    )
    client = StravaClient(_FULL_COOKIES)
    await client.get_csrf_token()
    await client.fetch_current_athlete_id()

    assert "_strava4_session=sess-new" in athlete.calls[0].request.headers["cookie"]
    assert "sess-old" not in athlete.calls[0].request.headers["cookie"]
    current = client.current_cookies()
    assert current["_strava4_session"] == "sess-new"
    assert current["strava_remember_id"] == "4242"
    await client.aclose()


@pytest.mark.asyncio
@respx.mock
async def test_host_only_set_cookie_wins_over_initial_domain_cookie() -> None:
    respx.get("https://www.strava.com/dashboard").mock(
        return_value=httpx.Response(
            200, text=_CSRF_HTML, headers={"Set-Cookie": "_strava4_session=sess-host; Path=/"}
        )
    )
    client = StravaClient(_FULL_COOKIES)
    await client.get_csrf_token()
    assert client.current_cookies()["_strava4_session"] == "sess-host"
    await client.aclose()


@pytest.mark.asyncio
@respx.mock
async def test_current_cookies_drops_tracking_cookies() -> None:
    respx.get("https://www.strava.com/dashboard").mock(
        return_value=httpx.Response(
            200,
            text=_CSRF_HTML,
            headers=[
                ("Set-Cookie", "_ga=GA1; Domain=.strava.com; Path=/"),
                ("Set-Cookie", "sp=zz; Domain=.strava.com; Path=/"),
            ],
        )
    )
    client = StravaClient({"_strava4_session": "s"})
    await client.get_csrf_token()
    assert client.current_cookies() == {"_strava4_session": "s"}
    await client.aclose()


@pytest.mark.asyncio
async def test_current_cookies_before_first_request_returns_initial() -> None:
    client = StravaClient(_FULL_COOKIES)
    assert client.current_cookies() == _FULL_COOKIES


def _login_redirect_mocks() -> None:
    respx.get("https://www.strava.com/dashboard").mock(
        return_value=httpx.Response(302, headers={"Location": "https://www.strava.com/login"})
    )
    respx.get("https://www.strava.com/login").mock(
        return_value=httpx.Response(200, text="<html>login</html>")
    )


@pytest.mark.asyncio
@respx.mock
async def test_login_redirect_without_remember_cookies_is_session_expired(
    caplog: pytest.LogCaptureFixture,
) -> None:
    _login_redirect_mocks()
    client = StravaClient({"_strava4_session": "sess-old-0123456789"})
    with caplog.at_level("WARNING"), pytest.raises(AuthError) as exc_info:
        await client.get_csrf_token()
    await client.aclose()

    assert exc_info.value.code == "AUTH_SESSION_EXPIRED"
    assert "302 /dashboard" in caplog.text
    assert "200 /login" in caplog.text
    assert "_strava4_session=sess-old" in caplog.text
    assert "sess-old-0123456789" not in caplog.text


@pytest.mark.asyncio
@respx.mock
async def test_login_redirect_with_remember_cookies_is_remember_expired(
    caplog: pytest.LogCaptureFixture,
) -> None:
    _login_redirect_mocks()
    client = StravaClient(_FULL_COOKIES)
    with caplog.at_level("WARNING"), pytest.raises(AuthError) as exc_info:
        await client.get_csrf_token()
    await client.aclose()

    assert exc_info.value.code == "AUTH_REMEMBER_EXPIRED"
    # The remember token appears by name only — not even a prefix of its value.
    assert "strava_remember_token" in caplog.text
    assert "remember-" not in caplog.text
    assert "remember-secret-token" not in caplog.text


@pytest.mark.asyncio
@respx.mock
async def test_sessions_in_query_is_not_an_auth_error() -> None:
    respx.get("https://www.strava.com/dashboard").mock(
        return_value=httpx.Response(200, text=_CSRF_HTML)
    )
    client = StravaClient({"_strava4_session": "s"})
    resp = await client._get_client().get("https://www.strava.com/dashboard?x=sessions&y=login")
    client._check_auth(resp)  # must not raise
    await client.aclose()


@pytest.mark.asyncio
@respx.mock
@pytest.mark.parametrize("status", [400, 500])
async def test_dashboard_400_500_with_cookie_is_malformed_cookie(status: int) -> None:
    respx.get("https://www.strava.com/dashboard").mock(return_value=httpx.Response(status))
    client = StravaClient({"_strava4_session": "garbage"})
    with pytest.raises(AuthError) as exc_info:
        await client.get_csrf_token()
    await client.aclose()
    assert exc_info.value.code == "AUTH_MALFORMED_COOKIE"


@pytest.mark.asyncio
@respx.mock
async def test_rotation_on_rejected_session_is_not_exposed() -> None:
    """Cookies Strava sets while rejecting the session never replace the stored ones."""
    respx.get("https://www.strava.com/dashboard").mock(
        return_value=httpx.Response(
            302,
            headers=[
                ("Location", "https://www.strava.com/login"),
                ("Set-Cookie", "_strava4_session=anonymous; Domain=.strava.com; Path=/"),
            ],
        )
    )
    respx.get("https://www.strava.com/login").mock(return_value=httpx.Response(200, text="x"))
    client = StravaClient(_FULL_COOKIES)
    with pytest.raises(AuthError):
        await client.get_csrf_token()
    assert client.current_cookies() == _FULL_COOKIES
    await client.aclose()


def _session_values(cookie_header: str) -> list[str]:
    return [
        p.strip().split("=", 1)[1]
        for p in cookie_header.split(";")
        if p.strip().startswith("_strava4_session=")
    ]


@pytest.mark.asyncio
@respx.mock
async def test_host_only_rotation_is_sent_exactly_once_and_old_value_never() -> None:
    respx.get("https://www.strava.com/dashboard").mock(
        return_value=httpx.Response(
            200, text=_CSRF_HTML, headers={"Set-Cookie": "_strava4_session=NEW; Path=/"}
        )
    )
    athlete = respx.get("https://www.strava.com/frontend/athletes/current").mock(
        return_value=httpx.Response(200, json={"currentAthlete": {"id_str": "1"}})
    )
    client = StravaClient(_FULL_COOKIES)
    await client.get_csrf_token()
    await client.fetch_current_athlete_id()

    sent = athlete.calls[0].request.headers["cookie"]
    assert _session_values(sent) == ["NEW"]
    assert "strava_remember_id=4242" in sent
    assert "strava_remember_token=remember-secret-token" in sent
    assert client.current_cookies()["_strava4_session"] == "NEW"
    await client.aclose()


@pytest.mark.asyncio
@respx.mock
async def test_host_only_rotation_within_redirect_chain_applies_to_next_hop() -> None:
    respx.get("https://www.strava.com/dashboard").mock(
        return_value=httpx.Response(
            302,
            headers={
                "Location": "https://www.strava.com/dashboard/home",
                "Set-Cookie": "_strava4_session=NEW; Path=/",
            },
        )
    )
    final = respx.get("https://www.strava.com/dashboard/home").mock(
        return_value=httpx.Response(200, text=_CSRF_HTML)
    )
    client = StravaClient(_FULL_COOKIES)
    await client.get_csrf_token()

    sent = final.calls[0].request.headers["cookie"]
    assert _session_values(sent) == ["NEW"]
    assert "strava_remember_token=remember-secret-token" in sent
    await client.aclose()


@pytest.mark.asyncio
@respx.mock
async def test_locale_prefixed_login_path_is_auth_error() -> None:
    respx.get("https://www.strava.com/dashboard").mock(
        return_value=httpx.Response(302, headers={"Location": "https://www.strava.com/de-de/login"})
    )
    respx.get("https://www.strava.com/de-de/login").mock(return_value=httpx.Response(200, text="x"))
    client = StravaClient({"_strava4_session": "s"})
    with pytest.raises(AuthError) as exc_info:
        await client.get_csrf_token()
    assert exc_info.value.code == "AUTH_SESSION_EXPIRED"
    await client.aclose()


# ── CSRF token sources (Next.js dashboard, 2026-10-28) ─────────────────────────

# Next.js dashboard without any usable CSRF meta (forces the fallback sources).
_NEXT_DASHBOARD = (
    '<html><head><script id="__NEXT_DATA__" type="application/json">{}</script></head></html>'
)
_DASHBOARD = "https://www.strava.com/dashboard"
_CURRENT = "https://www.strava.com/frontend/athletes/current"
_TRAINING = "https://www.strava.com/athlete/training"


@pytest.mark.asyncio
@respx.mock
async def test_csrf_from_dashboard_meta_makes_no_further_requests() -> None:
    respx.get(_DASHBOARD).mock(return_value=httpx.Response(200, text=_CSRF_HTML))
    current = respx.get(_CURRENT).mock(return_value=httpx.Response(200, json={}))
    training = respx.get(_TRAINING).mock(return_value=httpx.Response(200, text=""))

    client = StravaClient(_FULL_COOKIES)
    assert await client.get_csrf_token() == _TOKEN
    await client.aclose()

    assert not current.called
    assert not training.called


@pytest.mark.asyncio
@respx.mock
async def test_csrf_from_current_athlete_header_and_cached_athlete_id() -> None:
    respx.get(_DASHBOARD).mock(return_value=httpx.Response(200, text=_NEXT_DASHBOARD))
    current = respx.get(_CURRENT).mock(
        return_value=httpx.Response(
            200, json={"currentAthlete": {"id_str": "777"}}, headers={"csrf-token": "hdr-token"}
        )
    )
    training = respx.get(_TRAINING).mock(return_value=httpx.Response(200, text=""))

    client = StravaClient(_FULL_COOKIES)
    assert await client.get_csrf_token() == "hdr-token"
    assert await client.fetch_current_athlete_id() == "777"
    await client.aclose()

    assert current.call_count == 1  # athlete ID came from the cache
    assert not training.called


@pytest.mark.asyncio
@respx.mock
async def test_csrf_from_training_page_when_header_missing() -> None:
    respx.get(_DASHBOARD).mock(return_value=httpx.Response(200, text=_NEXT_DASHBOARD))
    respx.get(_CURRENT).mock(return_value=httpx.Response(200, json={}))
    respx.get(_TRAINING).mock(return_value=httpx.Response(200, text=_CSRF_HTML))

    client = StravaClient(_FULL_COOKIES)
    assert await client.get_csrf_token() == _TOKEN
    await client.aclose()


@pytest.mark.asyncio
@respx.mock
async def test_csrf_not_found_anywhere_raises_and_logs_sources_without_values(
    caplog: pytest.LogCaptureFixture,
) -> None:
    respx.get(_DASHBOARD).mock(return_value=httpx.Response(200, text=_NEXT_DASHBOARD))
    respx.get(_CURRENT).mock(return_value=httpx.Response(200, json={}))
    respx.get(_TRAINING).mock(return_value=httpx.Response(200, text="<html></html>"))

    client = StravaClient(_FULL_COOKIES)
    with caplog.at_level("DEBUG"), pytest.raises(RuntimeError, match="CSRF"):
        await client.get_csrf_token()
    await client.aclose()

    for path in ("/dashboard", "/frontend/athletes/current", "/athlete/training"):
        assert path in caplog.text
    assert "Next.js" in caplog.text


@pytest.mark.asyncio
@respx.mock
async def test_csrf_source_is_logged_without_token_value(
    caplog: pytest.LogCaptureFixture,
) -> None:
    respx.get(_DASHBOARD).mock(return_value=httpx.Response(200, text=_NEXT_DASHBOARD))
    respx.get(_CURRENT).mock(
        return_value=httpx.Response(
            200,
            json={"currentAthlete": {"id_str": "1"}},
            headers={"csrf-token": "hdr-token-secret"},
        )
    )

    client = StravaClient(_FULL_COOKIES)
    with caplog.at_level("DEBUG"):
        await client.get_csrf_token()
    await client.aclose()

    assert "CSRF token from /frontend/athletes/current header" in caplog.text
    assert "hdr-token-secret" not in caplog.text
    assert "hdr-toke" not in caplog.text


@pytest.mark.asyncio
@respx.mock
async def test_login_redirect_on_training_page_raises_auth_error() -> None:
    respx.get(_DASHBOARD).mock(return_value=httpx.Response(200, text=_NEXT_DASHBOARD))
    respx.get(_CURRENT).mock(return_value=httpx.Response(200, json={}))
    respx.get(_TRAINING).mock(
        return_value=httpx.Response(302, headers={"Location": "https://www.strava.com/login"})
    )
    respx.get("https://www.strava.com/login").mock(return_value=httpx.Response(200, text="x"))

    client = StravaClient(_FULL_COOKIES)
    with pytest.raises(AuthError) as exc_info:
        await client.get_csrf_token()
    await client.aclose()
    assert exc_info.value.code == "AUTH_REMEMBER_EXPIRED"


@pytest.mark.asyncio
@respx.mock
async def test_auth_diagnostics_log_hops_cookie_names_and_deletions(
    caplog: pytest.LogCaptureFixture,
) -> None:
    respx.get(_DASHBOARD).mock(
        return_value=httpx.Response(
            301,
            headers=[
                ("Location", "https://www.strava.com/login"),
                ("Set-Cookie", "_strava4_session=anon-value; Path=/"),
                ("Set-Cookie", "strava_remember_id=; Max-Age=0; Path=/"),
                ("Set-Cookie", "_strava_cpra=x; Expires=Thu, 01 Jan 1970 00:00:00 GMT; Path=/"),
            ],
        )
    )
    respx.get("https://www.strava.com/login").mock(return_value=httpx.Response(200, text="x"))

    client = StravaClient(_FULL_COOKIES)
    with caplog.at_level("WARNING"), pytest.raises(AuthError):
        await client.get_csrf_token()
    await client.aclose()

    text = caplog.text
    assert "301 /dashboard" in text
    assert "200 /login" in text
    # Cookie names the first request sent, as a name list.
    assert "sent=[_strava4_session, strava_remember_id, strava_remember_token]" in text
    assert "_strava4_session:set" in text
    assert "strava_remember_id:deleted" in text
    assert "_strava_cpra:deleted" in text
    # Values never appear beyond the 8-char mask; the remember token only as a name.
    assert "anon-value" not in text
    assert "sess-old-0123456789" not in text
    assert "_strava4_session=sess-old" in text
    assert "remember-" not in text


@pytest.mark.asyncio
@respx.mock
@pytest.mark.parametrize("current", [None, ["x"], "str"])
async def test_csrf_odd_current_athlete_shape_falls_through_to_training(current: object) -> None:
    respx.get(_DASHBOARD).mock(return_value=httpx.Response(200, text=_NEXT_DASHBOARD))
    respx.get(_CURRENT).mock(
        return_value=httpx.Response(
            200, json={"currentAthlete": current}, headers={"csrf-token": "hdr-token"}
        )
    )
    respx.get(_TRAINING).mock(return_value=httpx.Response(200, text=_CSRF_HTML))

    client = StravaClient(_FULL_COOKIES)
    assert await client.get_csrf_token() == _TOKEN
    await client.aclose()


@pytest.mark.asyncio
@respx.mock
@pytest.mark.parametrize("current", [None, ["x"]])
async def test_csrf_odd_current_athlete_shape_without_any_token_raises_runtime_error(
    current: object,
) -> None:
    respx.get(_DASHBOARD).mock(return_value=httpx.Response(200, text=_NEXT_DASHBOARD))
    respx.get(_CURRENT).mock(
        return_value=httpx.Response(
            200, json={"currentAthlete": current}, headers={"csrf-token": "hdr-token"}
        )
    )
    respx.get(_TRAINING).mock(return_value=httpx.Response(200, text="<html></html>"))

    client = StravaClient(_FULL_COOKIES)
    with pytest.raises(RuntimeError, match="CSRF"):
        await client.get_csrf_token()
    assert await client.fetch_current_athlete_id() is None  # must not raise either
    await client.aclose()


@pytest.mark.asyncio
@respx.mock
@pytest.mark.parametrize("header", ["   ", "a, b"])
async def test_csrf_unusable_header_falls_through_to_training(header: str) -> None:
    respx.get(_DASHBOARD).mock(return_value=httpx.Response(200, text=_NEXT_DASHBOARD))
    respx.get(_CURRENT).mock(
        return_value=httpx.Response(
            200, json={"currentAthlete": {"id_str": "1"}}, headers={"csrf-token": header}
        )
    )
    respx.get(_TRAINING).mock(return_value=httpx.Response(200, text=_CSRF_HTML))

    client = StravaClient(_FULL_COOKIES)
    assert await client.get_csrf_token() == _TOKEN
    await client.aclose()


@pytest.mark.asyncio
@respx.mock
async def test_csrf_header_without_athlete_id_does_not_short_circuit() -> None:
    respx.get(_DASHBOARD).mock(return_value=httpx.Response(200, text=_NEXT_DASHBOARD))
    respx.get(_CURRENT).mock(
        return_value=httpx.Response(200, json={}, headers={"csrf-token": "anon-token"})
    )
    training = respx.get(_TRAINING).mock(return_value=httpx.Response(200, text=_CSRF_HTML))

    client = StravaClient(_FULL_COOKIES)
    assert await client.get_csrf_token() == _TOKEN
    await client.aclose()
    assert training.called


@pytest.mark.asyncio
@respx.mock
async def test_csrf_header_is_stripped() -> None:
    respx.get(_DASHBOARD).mock(return_value=httpx.Response(200, text=_NEXT_DASHBOARD))
    respx.get(_CURRENT).mock(
        return_value=httpx.Response(
            200, json={"currentAthlete": {"id_str": "1"}}, headers={"csrf-token": " hdr-token "}
        )
    )
    client = StravaClient(_FULL_COOKIES)
    assert await client.get_csrf_token() == "hdr-token"
    await client.aclose()


@pytest.mark.asyncio
@respx.mock
async def test_csrf_current_athlete_401_raises_auth_error() -> None:
    respx.get(_DASHBOARD).mock(return_value=httpx.Response(200, text=_NEXT_DASHBOARD))
    respx.get(_CURRENT).mock(return_value=httpx.Response(401))
    client = StravaClient(_FULL_COOKIES)
    with pytest.raises(AuthError):
        await client.get_csrf_token()
    await client.aclose()


@pytest.mark.asyncio
@respx.mock
async def test_csrf_source_log_has_token_length_not_value(
    caplog: pytest.LogCaptureFixture,
) -> None:
    respx.get(_DASHBOARD).mock(return_value=httpx.Response(200, text=_CSRF_HTML))
    client = StravaClient(_FULL_COOKIES)
    with caplog.at_level("DEBUG"):
        await client.get_csrf_token()
    await client.aclose()
    assert f"len={len(_TOKEN)}" in caplog.text
    assert _TOKEN not in caplog.text


# ── Next.js dashboard as single source (CSRF + athlete ID + feed page 1) ──────

_FEED = "https://www.strava.com/dashboard/feed"


def _nextjs_dashboard(*, mutate: Callable[[dict], None] | None = None) -> str:
    """The synthetic Next.js dashboard fixture, optionally with its __NEXT_DATA__ altered."""
    html = _load("nextjs_dashboard.html")
    if mutate is None:
        return html
    m = _NEXT_DATA_RE.search(html)
    assert m
    data = json.loads(m.group(1))
    mutate(data)
    return html.replace(m.group(1), json.dumps(data))


def _mock_nextjs_dashboard(html: str | None = None) -> None:
    respx.get(_DASHBOARD).mock(
        return_value=httpx.Response(200, text=html if html is not None else _nextjs_dashboard())
    )


@pytest.mark.asyncio
@respx.mock
async def test_csrf_from_nextjs_meta_csrf_makes_no_further_requests() -> None:
    _mock_nextjs_dashboard()
    current = respx.get(_CURRENT).mock(return_value=httpx.Response(200, json={}))
    training = respx.get(_TRAINING).mock(return_value=httpx.Response(200, text=""))

    client = StravaClient(_FULL_COOKIES)
    assert await client.get_csrf_token() == _TOKEN
    await client.aclose()

    assert respx.calls.call_count == 1
    assert not current.called
    assert not training.called


@pytest.mark.asyncio
@respx.mock
async def test_legacy_rails_dashboard_makes_no_further_requests() -> None:
    respx.get(_DASHBOARD).mock(
        return_value=httpx.Response(200, text=_load("rails_dashboard_legacy.html"))
    )
    client = StravaClient(_FULL_COOKIES)
    assert await client.get_csrf_token() == _TOKEN
    await client.aclose()
    assert respx.calls.call_count == 1


@pytest.mark.asyncio
@respx.mock
async def test_dashboard_request_asks_for_english() -> None:
    _mock_nextjs_dashboard()
    client = StravaClient(_FULL_COOKIES)
    await client.get_csrf_token()
    await client.aclose()
    assert respx.calls.last.request.headers["accept-language"] == "en"


@pytest.mark.asyncio
@respx.mock
@pytest.mark.parametrize("token", ["short", "has space " + "a" * 60, "<b>" + "a" * 60])
async def test_implausible_meta_csrf_falls_through_to_next_source(token: str) -> None:
    html = f'<html><head><meta name="csrf" content="{token}"></head></html>'
    respx.get(_DASHBOARD).mock(return_value=httpx.Response(200, text=html))
    respx.get(_CURRENT).mock(return_value=httpx.Response(200, json={}))
    respx.get(_TRAINING).mock(return_value=httpx.Response(200, text=_CSRF_HTML))

    client = StravaClient(_FULL_COOKIES)
    assert await client.get_csrf_token() == _TOKEN
    await client.aclose()


@pytest.mark.asyncio
@respx.mock
async def test_nextjs_dashboard_without_meta_still_yields_athlete_id_from_next_data() -> None:
    html = _nextjs_dashboard().replace('name="csrf"', 'name="viewport"')
    respx.get(_DASHBOARD).mock(return_value=httpx.Response(200, text=html))
    current = respx.get(_CURRENT).mock(
        return_value=httpx.Response(
            200, json={"currentAthlete": {"id_str": "20000001"}}, headers={"csrf-token": "hdr"}
        )
    )
    client = StravaClient(_FULL_COOKIES)
    assert await client.get_csrf_token() == "hdr"
    assert await client.fetch_current_athlete_id() == "20000001"
    await client.aclose()
    assert current.call_count == 1


@pytest.mark.asyncio
@respx.mock
async def test_dashboard_athlete_id_does_not_fake_athlete_identification() -> None:
    """An ID read from the dashboard must not make an anonymous /current header trusted."""
    html = _nextjs_dashboard().replace('name="csrf"', 'name="viewport"')
    respx.get(_DASHBOARD).mock(return_value=httpx.Response(200, text=html))
    respx.get(_CURRENT).mock(
        return_value=httpx.Response(200, json={}, headers={"csrf-token": "anon-token"})
    )
    respx.get(_TRAINING).mock(return_value=httpx.Response(200, text=_CSRF_HTML))
    client = StravaClient(_FULL_COOKIES)
    assert await client.get_csrf_token() == _TOKEN
    await client.aclose()


@pytest.mark.asyncio
@respx.mock
async def test_athlete_id_from_next_data_needs_no_second_request() -> None:
    _mock_nextjs_dashboard()
    current = respx.get(_CURRENT).mock(return_value=httpx.Response(200, json={}))
    client = StravaClient(_FULL_COOKIES)
    await client.get_csrf_token()
    assert await client.fetch_current_athlete_id() == "20000001"
    await client.aclose()
    assert not current.called


@pytest.mark.asyncio
@respx.mock
async def test_athlete_id_falls_back_to_dashboard_data_current_athlete() -> None:
    def mutate(data: dict) -> None:
        del data["props"]["currentAthletePreload"]

    _mock_nextjs_dashboard(_nextjs_dashboard(mutate=mutate))
    client = StravaClient(_FULL_COOKIES)
    await client.get_csrf_token()
    assert await client.fetch_current_athlete_id() == "20000001"
    await client.aclose()
    assert respx.calls.call_count == 1


@pytest.mark.asyncio
@respx.mock
async def test_feed_page_1_comes_from_dashboard_and_parses() -> None:
    _mock_nextjs_dashboard()
    xhr = respx.get(_FEED).mock(
        return_value=httpx.Response(200, json={"entries": [], "pagination": {"hasMore": False}})
    )
    client = StravaClient(_FULL_COOKIES, sleep=AsyncMock(), rng=random.Random(0))
    await client.get_csrf_token()
    feed = await client.fetch_following_feed("20000001")
    await client.aclose()

    # Page 1 was embedded; hasMore=true asks for page 2, which the XHR answers (empty).
    assert xhr.call_count == 1
    assert "before" in xhr.calls.last.request.url.params
    # before = minimum updated_at over all entries of page 1 (fixture: the last one)
    assert xhr.calls.last.request.url.params["before"] == str(1790000000 - 2000)
    activities = StructuredFeedParser().parse(feed)
    assert [a.activity_id for a in activities] == ["10000000001", "10000000002"]
    assert activities[0].stats.distance_m == pytest.approx(10500)
    assert activities[0].stats.moving_time_s == 3010
    assert activities[0].location == "Example City"
    assert activities[1].location is None


@pytest.mark.asyncio
@respx.mock
async def test_embedded_feed_is_used_once() -> None:
    def mutate(data: dict) -> None:
        data["props"]["pageProps"]["dashboardData"]["feed"]["pagination"]["hasMore"] = False

    _mock_nextjs_dashboard(_nextjs_dashboard(mutate=mutate))
    xhr = respx.get(_FEED).mock(
        return_value=httpx.Response(200, json={"entries": [], "pagination": {"hasMore": False}})
    )
    client = StravaClient(_FULL_COOKIES)
    await client.get_csrf_token()
    await client.fetch_following_feed("20000001")
    # The embedded page's hasMore is never trusted: one XHR page 2 is always tried.
    assert xhr.call_count == 1
    assert "before" in xhr.calls.last.request.url.params
    await client.fetch_following_feed("20000001")  # second call: no stale embedded page
    await client.aclose()
    assert xhr.call_count == 2
    assert "before" not in xhr.calls.last.request.url.params


@pytest.mark.asyncio
@respx.mock
async def test_embedded_feed_of_other_athlete_is_ignored() -> None:
    _mock_nextjs_dashboard()
    xhr = respx.get(_FEED).mock(
        return_value=httpx.Response(200, json=_page([_act_entry(5)], False))
    )
    client = StravaClient(_FULL_COOKIES)
    await client.get_csrf_token()
    result = await client.fetch_following_feed("99999999")
    await client.aclose()
    assert xhr.call_count == 1
    assert [e["activity"]["id"] for e in result["entries"]] == [5]


@pytest.mark.asyncio
@respx.mock
@pytest.mark.parametrize(
    "feed",
    [
        {"entries": "nope", "pagination": {}},
        {"entries": [{"entity": "Activity", "feedType": "suggested"}], "pagination": {}},
        {"entries": [], "pagination": {}},
        [],
    ],
)
async def test_unusable_embedded_feed_falls_back_to_xhr(feed: object) -> None:
    def mutate(data: dict) -> None:
        data["props"]["pageProps"]["dashboardData"]["feed"] = feed

    _mock_nextjs_dashboard(_nextjs_dashboard(mutate=mutate))
    xhr = respx.get(_FEED).mock(
        return_value=httpx.Response(200, json=_page([_act_entry(7)], False))
    )
    client = StravaClient(_FULL_COOKIES)
    await client.get_csrf_token()
    result = await client.fetch_following_feed("20000001")
    await client.aclose()
    assert xhr.call_count == 1
    assert [e["activity"]["id"] for e in result["entries"]] == [7]


@pytest.mark.asyncio
@respx.mock
@pytest.mark.parametrize(
    "response",
    [
        httpx.Response(200, text="<html>nope</html>", headers={"content-type": "text/html"}),
        httpx.Response(404, text="gone"),
        httpx.Response(503, text="down"),
        httpx.Response(200, json={"unexpected": True}),
        httpx.Response(200, json=[1, 2]),
    ],
)
async def test_pagination_failure_warns_and_keeps_page_1(
    response: httpx.Response, caplog: pytest.LogCaptureFixture
) -> None:
    _mock_nextjs_dashboard()
    respx.get(_FEED).mock(return_value=response)
    client = StravaClient(_FULL_COOKIES, sleep=AsyncMock(), rng=random.Random(0))
    await client.get_csrf_token()
    with caplog.at_level("WARNING"):
        feed = await client.fetch_following_feed("20000001")
    await client.aclose()

    assert len(feed["entries"]) == 3  # 2 activities + 1 challenge from page 1
    warning = next(r for r in caplog.records if "Feed page 2" in r.getMessage())
    assert warning.levelname == "WARNING"
    for part in ("HTTP", "content-type", "/dashboard/feed"):
        assert part in warning.getMessage()


@pytest.mark.asyncio
@respx.mock
async def test_page_1_missing_and_xhr_broken_raises_runtime_error_with_details(
    caplog: pytest.LogCaptureFixture,
) -> None:
    def drop_feed(data: dict) -> None:
        del data["props"]["pageProps"]["dashboardData"]["feed"]

    _mock_nextjs_dashboard(_nextjs_dashboard(mutate=drop_feed))
    respx.get(_FEED).mock(
        return_value=httpx.Response(
            200, text="<html>secret-body</html>", headers={"content-type": "text/html"}
        )
    )
    client = StravaClient(_FULL_COOKIES)
    await client.get_csrf_token()
    with pytest.raises(RuntimeError) as exc_info:
        await client.fetch_following_feed("20000001")
    await client.aclose()

    msg = str(exc_info.value)
    assert "HTTP 200" in msg
    assert "text/html" in msg
    assert "/dashboard/feed" in msg
    assert "not JSON" in msg
    assert "secret-body" not in msg
    assert _TOKEN not in msg
    assert "sess-old" not in msg


@pytest.mark.asyncio
@respx.mock
async def test_page_1_xhr_json_decode_error_is_not_leaked_as_jsondecodeerror() -> None:
    respx.get(_FEED).mock(return_value=httpx.Response(200, text="not json"))
    client = StravaClient(_FULL_COOKIES)
    with pytest.raises(RuntimeError, match="Feed page 1 unavailable"):
        await client.fetch_following_feed("20000001")
    await client.aclose()


@pytest.mark.asyncio
@respx.mock
async def test_foreign_locale_logs_one_aggregated_warning(
    caplog: pytest.LogCaptureFixture,
) -> None:
    respx.get(_FEED).mock(
        return_value=httpx.Response(
            200,
            json=_page(
                [_act_entry(1, locale="de"), _act_entry(2, locale="de"), _act_entry(3)], False
            ),
        )
    )
    client = StravaClient(_FULL_COOKIES)
    with caplog.at_level("WARNING"):
        await client.fetch_following_feed("20000001")
    await client.aclose()

    warnings = [r.getMessage() for r in caplog.records if "locale" in r.getMessage()]
    assert len(warnings) == 1
    assert "2 of 3" in warnings[0]
    assert "de" in warnings[0]


@pytest.mark.asyncio
@respx.mock
async def test_english_locale_logs_no_warning(caplog: pytest.LogCaptureFixture) -> None:
    respx.get(_FEED).mock(return_value=httpx.Response(200, json=_page([_act_entry(1)], False)))
    client = StravaClient(_FULL_COOKIES)
    with caplog.at_level("WARNING"):
        await client.fetch_following_feed("20000001")
    await client.aclose()
    assert "locale" not in caplog.text


@pytest.mark.parametrize(
    "html",
    [
        "",
        '<script id="__NEXT_DATA__" type="application/json">not json</script>',
        '<script id="__NEXT_DATA__" type="application/json">[1]</script>',
        '<script id="__NEXT_DATA__" type="application/json">{"props": 5}</script>',
        '<script id="__NEXT_DATA__" type="application/json">{"props": {"pageProps": 3}}</script>',
        '<script id="__NEXT_DATA__" type="application/json">'
        '{"props": {"currentAthletePreload": ["x"], "pageProps": {"dashboardData": []}}}</script>',
        '<script id="__NEXT_DATA__" type="application/json">'
        '{"props": {"currentAthletePreload": {"id_str": 5}, '
        '"pageProps": {"dashboardData": {"feed": "x"}}}}</script>',
    ],
)
def test_parse_next_data_is_total(html: str) -> None:
    assert _parse_next_data(html) == (None, None)


def test_parse_next_data_reads_id_and_feed() -> None:
    athlete_id, feed = _parse_next_data(_nextjs_dashboard())
    assert athlete_id == "20000001"
    assert feed is not None
    assert len(feed["entries"]) == 3
    assert feed["entries"][1]["activity"]["timeAndLocation"]["location"] is None
    assert isinstance(feed["entries"][0]["cursorData"]["rank"], int)


@pytest.mark.asyncio
@respx.mock
@pytest.mark.parametrize(("first_id", "second_id"), [(5, "5"), ("5", 5)])
async def test_fetch_feed_deduplicates_int_and_str_activity_ids(
    first_id: object, second_id: object
) -> None:
    """Page 1 (SSR JSON) and page 2 (XHR) may type the same id differently."""
    respx.get(_FEED).mock(
        side_effect=[
            httpx.Response(200, json=_page([_act_entry(first_id)], True)),  # type: ignore[arg-type]
            httpx.Response(200, json=_page([_act_entry(second_id)], False)),  # type: ignore[arg-type]
        ]
    )
    client = StravaClient(_FULL_COOKIES, sleep=AsyncMock(), rng=random.Random(0))
    result = await client.fetch_following_feed("1")
    await client.aclose()
    assert len(result["entries"]) == 1


@pytest.mark.asyncio
@respx.mock
async def test_embedded_feed_with_foreign_locale_falls_back_to_xhr(
    caplog: pytest.LogCaptureFixture,
) -> None:
    def mutate(data: dict) -> None:
        feed = data["props"]["pageProps"]["dashboardData"]["feed"]
        feed["entries"][0]["locale"] = "de"

    _mock_nextjs_dashboard(_nextjs_dashboard(mutate=mutate))
    xhr = respx.get(_FEED).mock(
        return_value=httpx.Response(200, json=_page([_act_entry(7, locale="de")], False))
    )
    client = StravaClient(_FULL_COOKIES)
    await client.get_csrf_token()
    with caplog.at_level("WARNING"):
        result = await client.fetch_following_feed("20000001")
    await client.aclose()
    assert xhr.call_count == 1
    assert [e["activity"]["id"] for e in result["entries"]] == [7]
    assert sum("locale" in r.getMessage() for r in caplog.records) == 1


# ── PR 2: kudo POST without redirect following, honest failures ───────────────

_KUDO = "https://www.strava.com/feed/activity/10000000001/kudo"


@pytest.mark.asyncio
@respx.mock
async def test_send_kudos_does_not_follow_redirects() -> None:
    respx.post(_KUDO).mock(
        return_value=httpx.Response(302, headers={"location": "https://www.strava.com/dashboard"})
    )
    landing = respx.get(_DASHBOARD).mock(return_value=httpx.Response(200, text="<html></html>"))
    client = StravaClient({"_strava4_session": "c"})
    ok = await client.send_kudos("10000000001", "csrf")
    await client.aclose()

    assert ok is False
    assert landing.call_count == 0
    assert client.last_kudo_status == 302


@pytest.mark.asyncio
@respx.mock
async def test_send_kudos_redirect_to_login_is_auth_error() -> None:
    respx.post(_KUDO).mock(
        return_value=httpx.Response(302, headers={"location": "https://www.strava.com/login"})
    )
    client = StravaClient({"_strava4_session": "c"})
    with pytest.raises(AuthError) as exc_info:
        await client.send_kudos("10000000001", "csrf")
    assert exc_info.value.code == "AUTH_SESSION_EXPIRED"
    # A rejected session must not replace the stored cookies.
    assert client.current_cookies() == {"_strava4_session": "c"}
    await client.aclose()


@pytest.mark.asyncio
@respx.mock
async def test_send_kudos_relative_login_redirect_is_auth_error() -> None:
    respx.post(_KUDO).mock(return_value=httpx.Response(302, headers={"location": "/session"}))
    client = StravaClient({"_strava4_session": "c"})
    with pytest.raises(AuthError):
        await client.send_kudos("10000000001", "csrf")
    await client.aclose()


@pytest.mark.asyncio
@respx.mock
async def test_send_kudos_401_is_auth_error() -> None:
    respx.post(_KUDO).mock(return_value=httpx.Response(401, text="no"))
    client = StravaClient({"_strava4_session": "c"})
    with pytest.raises(AuthError) as exc_info:
        await client.send_kudos("10000000001", "csrf")
    assert exc_info.value.code == "AUTH_FAILED"
    await client.aclose()


@pytest.mark.asyncio
@respx.mock
@pytest.mark.parametrize("status", [403, 404, 422, 500, 204, 304])
async def test_send_kudos_other_statuses_fail_with_status_in_log(
    status: int, caplog: pytest.LogCaptureFixture
) -> None:
    respx.post(_KUDO).mock(return_value=httpx.Response(status))
    client = StravaClient({"_strava4_session": "c"})
    with caplog.at_level("WARNING"):
        ok = await client.send_kudos("10000000001", "csrf-secret-value")
    await client.aclose()

    assert ok is False
    assert client.last_kudo_status == status
    assert f"HTTP {status}" in caplog.text
    assert "csrf-secret-value" not in caplog.text


@pytest.mark.asyncio
@respx.mock
@pytest.mark.parametrize("status", [200, 201])
async def test_send_kudos_success_records_status(status: int) -> None:
    respx.post(_KUDO).mock(return_value=httpx.Response(status, json={"success": "true"}))
    client = StravaClient({"_strava4_session": "c"})
    assert await client.send_kudos("10000000001", "csrf") is True
    assert client.last_kudo_status == status
    await client.aclose()


@pytest.mark.asyncio
@respx.mock
async def test_send_kudos_network_error_resets_status() -> None:
    respx.post(_KUDO).mock(return_value=httpx.Response(403))
    client = StravaClient({"_strava4_session": "c"})
    await client.send_kudos("10000000001", "csrf")
    respx.post(_KUDO).mock(side_effect=httpx.ConnectError("boom"))
    assert await client.send_kudos("10000000001", "csrf") is False
    assert client.last_kudo_status is None
    await client.aclose()


@pytest.mark.asyncio
@respx.mock
async def test_csrf_source_is_logged_once_at_info_without_value(
    caplog: pytest.LogCaptureFixture,
) -> None:
    _mock_nextjs_dashboard()
    client = StravaClient(_FULL_COOKIES)
    with caplog.at_level("INFO"):
        token = await client.get_csrf_token()
    await client.aclose()

    lines = [r for r in caplog.records if "CSRF token from" in r.getMessage()]
    assert len(lines) == 1
    assert lines[0].levelname == "INFO"
    assert token not in caplog.text


# ── PR 2: athlete lookup / search robustness ──────────────────────────────────


@pytest.mark.asyncio
@respx.mock
async def test_lookup_athlete_login_redirect_raises_auth_error() -> None:
    respx.get("https://www.strava.com/athletes/20000001").mock(
        return_value=httpx.Response(302, headers={"location": "https://www.strava.com/login"})
    )
    respx.get("https://www.strava.com/login").mock(
        return_value=httpx.Response(200, text="<html>login</html>")
    )
    client = StravaClient({"_strava4_session": "c"})
    with pytest.raises(AuthError):
        await client.lookup_athlete("20000001")
    await client.aclose()


@pytest.mark.asyncio
@respx.mock
async def test_search_athletes_warns_when_next_data_is_missing(
    caplog: pytest.LogCaptureFixture,
) -> None:
    respx.get("https://www.strava.com/athletes/search").mock(
        return_value=httpx.Response(200, text="<html><body>no next data</body></html>")
    )
    client = StravaClient({"_strava4_session": "c"})
    with caplog.at_level("WARNING"):
        results = await client.search_athletes("Alex")
    await client.aclose()

    assert results == []
    assert "__NEXT_DATA__" in caplog.text
    assert any(r.levelname == "WARNING" for r in caplog.records)


@pytest.mark.asyncio
@respx.mock
@pytest.mark.parametrize(
    "data",
    [
        {"props": []},
        {"props": "x"},
        {"props": {"pageProps": []}},
        {"props": {"pageProps": None}},
        [],
        "string",
    ],
)
async def test_search_athletes_tolerates_untyped_next_data(data: object) -> None:
    html = '<script id="__NEXT_DATA__" type="application/json">' + json.dumps(data) + "</script>"
    respx.get("https://www.strava.com/athletes/search").mock(
        return_value=httpx.Response(200, text=html)
    )
    client = StravaClient({"_strava4_session": "c"})
    assert await client.search_athletes("Alex") == []
    await client.aclose()


# ── PR 2: feed pagination failures after page 1 ───────────────────────────────


@pytest.mark.asyncio
@respx.mock
async def test_pagination_network_error_keeps_page_1_and_warns(
    caplog: pytest.LogCaptureFixture,
) -> None:
    _mock_nextjs_dashboard()
    respx.get(_FEED).mock(side_effect=httpx.ConnectError("boom"))
    client = StravaClient(_FULL_COOKIES, sleep=AsyncMock(), rng=random.Random(0))
    await client.get_csrf_token()
    with caplog.at_level("WARNING"):
        feed = await client.fetch_following_feed("20000001")
    await client.aclose()

    assert len(feed["entries"]) == 3
    warning = next(r for r in caplog.records if "Feed page 2" in r.getMessage())
    assert warning.levelname == "WARNING"


@pytest.mark.asyncio
@respx.mock
async def test_pagination_login_redirect_still_raises_and_keeps_stored_cookies() -> None:
    _mock_nextjs_dashboard()
    respx.get(_FEED).mock(
        return_value=httpx.Response(302, headers={"location": "https://www.strava.com/login"})
    )
    respx.get("https://www.strava.com/login").mock(return_value=httpx.Response(200, text="login"))
    client = StravaClient(_FULL_COOKIES, sleep=AsyncMock(), rng=random.Random(0))
    await client.get_csrf_token()
    with pytest.raises(AuthError):
        await client.fetch_following_feed("20000001")
    assert client.current_cookies() == _FULL_COOKIES
    await client.aclose()


# ── fetch_following_feed — pagination settings, stop reasons, pacing ─────────


def _mock_pages(n_pages: int, per_page: int = 15, *, last_has_more: bool = True) -> None:
    pages = []
    for p in range(n_pages):
        entries = [
            _act_entry(p * per_page + i, rank=9000.0 - p, updated_at=2000 - p)
            for i in range(per_page)
        ]
        pages.append(httpx.Response(200, json=_page(entries, p < n_pages - 1 or last_has_more)))
    respx.get("https://www.strava.com/dashboard/feed").mock(side_effect=pages)


def _ids(result: dict) -> list[int]:
    return [e["activity"]["id"] for e in result["entries"]]


def _client(sleep: AsyncMock | None = None, seed: int = 0) -> StravaClient:
    return StravaClient(
        {"_strava4_session": "cookie"}, sleep=sleep or AsyncMock(), rng=random.Random(seed)
    )


def test_feed_page_cap_derivation() -> None:
    from kudosy.strava_client import _feed_page_cap

    assert _feed_page_cap(100) == 9
    assert _feed_page_cap(20) == 4
    assert _feed_page_cap(500) == 36
    assert _feed_page_cap(100000) == 40


@pytest.mark.asyncio
@respx.mock
async def test_count_mode_stops_at_target(caplog: pytest.LogCaptureFixture) -> None:
    _mock_pages(10)
    client = _client()
    with caplog.at_level("INFO", logger="kudosy.strava_client"):
        result = await client.fetch_following_feed("1", target=40)
    await client.aclose()
    assert len(respx.calls) == 3  # 15, 30, 45 >= 40
    assert len(_ids(result)) == 45
    assert "stop reason: target reached" in caplog.text


@pytest.mark.asyncio
@respx.mock
async def test_large_target_reaches_beyond_old_cap() -> None:
    _mock_pages(12)
    client = _client()
    await client.fetch_following_feed("1", target=150)
    await client.aclose()
    assert len(respx.calls) == 10


@pytest.mark.asyncio
@respx.mock
async def test_until_known_fetches_one_safety_page_after_known_page(
    caplog: pytest.LogCaptureFixture,
) -> None:
    _mock_pages(6)
    client = _client()
    with caplog.at_level("INFO", logger="kudosy.strava_client"):
        result = await client.fetch_following_feed(
            "1", target=500, known_ids={"20"}, mode="untilKnown"
        )
    await client.aclose()
    assert len(respx.calls) == 3  # id 20 is on page 2, plus one safety page
    assert len(_ids(result)) == 45  # whole page 2 and the safety page included
    assert "stop reason: known activity reached (+1 safety page)" in caplog.text


@pytest.mark.asyncio
@respx.mock
async def test_until_known_without_snapshot_falls_back_to_count() -> None:
    for known in (None, set()):
        respx.calls.reset()
        _mock_pages(10)
        client = _client()
        result = await client.fetch_following_feed(
            "1", target=40, known_ids=known, mode="untilKnown"
        )
        await client.aclose()
        assert len(_ids(result)) == 45


@pytest.mark.asyncio
@respx.mock
async def test_until_known_target_is_upper_bound(caplog: pytest.LogCaptureFixture) -> None:
    _mock_pages(10)
    client = _client()
    with caplog.at_level("INFO", logger="kudosy.strava_client"):
        result = await client.fetch_following_feed(
            "1", target=20, known_ids={"99999"}, mode="untilKnown"
        )
    await client.aclose()
    assert len(_ids(result)) == 30
    assert "stop reason: target reached" in caplog.text


@pytest.mark.asyncio
@respx.mock
async def test_embedded_page_with_known_id_fetches_one_xhr_safety_page() -> None:
    _mock_nextjs_dashboard(_embedded_with([_act_entry(5, updated_at=100)]))
    xhr = respx.get(_FEED).mock(
        return_value=httpx.Response(200, json=_page([_act_entry(6, updated_at=90)], True))
    )
    client = StravaClient(_FULL_COOKIES, sleep=AsyncMock(), rng=random.Random(0))
    await client.get_csrf_token()
    result = await client.fetch_following_feed("20000001", known_ids={"5"}, mode="untilKnown")
    await client.aclose()
    assert _ids(result) == [5, 6]
    assert xhr.call_count == 1


@pytest.mark.asyncio
@respx.mock
async def test_page_cap_stop_reason_and_info_page_logs(caplog: pytest.LogCaptureFixture) -> None:
    from kudosy.strava_client import _feed_page_cap

    cap = _feed_page_cap(20)
    _mock_pages(cap + 3, per_page=2)
    client = _client()
    with caplog.at_level("INFO", logger="kudosy.strava_client"):
        await client.fetch_following_feed("1", target=20)
    await client.aclose()
    assert len(respx.calls) == cap
    assert "Feed page 1: 2 entries, 2 unique activities so far" in caplog.text
    assert f"Feed page {cap}: 2 entries, {2 * cap} unique activities so far" in caplog.text
    assert "stop reason: page cap" in caplog.text


@pytest.mark.asyncio
@respx.mock
async def test_until_known_on_last_page_needs_no_extra_request(
    caplog: pytest.LogCaptureFixture,
) -> None:
    _mock_pages(2, last_has_more=False)
    client = _client()
    with caplog.at_level("INFO", logger="kudosy.strava_client"):
        result = await client.fetch_following_feed(
            "1", target=500, known_ids={"20"}, mode="untilKnown"
        )
    await client.aclose()
    assert len(respx.calls) == 2
    assert len(_ids(result)) == 30
    assert "stop reason: feed end" in caplog.text


@pytest.mark.asyncio
@respx.mock
async def test_safety_page_respects_target() -> None:
    _mock_pages(6)
    client = _client()
    await client.fetch_following_feed("1", target=20, known_ids={"20"}, mode="untilKnown")
    await client.aclose()
    assert len(respx.calls) == 2  # target reached on the known page: no safety page


@pytest.mark.asyncio
@respx.mock
async def test_safety_page_respects_page_cap(caplog: pytest.LogCaptureFixture) -> None:
    from kudosy.strava_client import _feed_page_cap

    cap = _feed_page_cap(20)
    _mock_pages(cap + 3, per_page=2)  # more pages available than the cap allows
    client = _client()
    with caplog.at_level("INFO", logger="kudosy.strava_client"):
        await client.fetch_following_feed(
            "1", target=20, known_ids={str(2 * (cap - 1))}, mode="untilKnown"
        )
    await client.aclose()
    assert len(respx.calls) == cap  # known id on the last allowed page; no extra page
    assert "stop reason: page cap" in caplog.text


@pytest.mark.asyncio
@respx.mock
@pytest.mark.parametrize(("mode", "pages", "ids"), [("count", 4, 60), ("untilKnown", 2, 30)])
async def test_count_mode_ignores_known_ids_and_safety_page(
    mode: str, pages: int, ids: int
) -> None:
    _mock_pages(10)
    client = _client()
    result = await client.fetch_following_feed("1", target=60, known_ids={"0"}, mode=mode)
    await client.aclose()
    # count: target of 60 unique activities, known id on page 1 ignored;
    # untilKnown: known page 1 plus exactly one safety page
    assert len(respx.calls) == pages
    assert len(_ids(result)) == ids


@pytest.mark.asyncio
@respx.mock
async def test_failing_safety_page_keeps_entries_and_reports_feed_error(
    caplog: pytest.LogCaptureFixture,
) -> None:
    respx.get(_FEED).mock(
        side_effect=[
            httpx.Response(200, json=_page([_act_entry(1), _act_entry(2)], True)),
            httpx.Response(200, text="<html>nope</html>"),
        ]
    )
    client = _client()
    with caplog.at_level("INFO", logger="kudosy.strava_client"):
        result = await client.fetch_following_feed("1", known_ids={"2"}, mode="untilKnown")
    await client.aclose()
    assert _ids(result) == [1, 2]
    assert "stop reason: feed error" in caplog.text


@pytest.mark.asyncio
@respx.mock
async def test_duplicate_only_safety_page_adds_nothing(caplog: pytest.LogCaptureFixture) -> None:
    respx.get(_FEED).mock(
        side_effect=[
            httpx.Response(200, json=_page([_act_entry(1), _act_entry(2)], True)),
            httpx.Response(200, json=_page([_act_entry(2), _act_entry(1)], True)),
        ]
    )
    client = _client()
    with caplog.at_level("INFO", logger="kudosy.strava_client"):
        result = await client.fetch_following_feed("1", known_ids={"2"}, mode="untilKnown")
    await client.aclose()
    assert _ids(result) == [1, 2]
    assert len(respx.calls) == 2
    assert "stop reason: known activity reached (+1 safety page)" in caplog.text


@pytest.mark.asyncio
@respx.mock
async def test_feed_end_stop_reason(caplog: pytest.LogCaptureFixture) -> None:
    _mock_pages(2, last_has_more=False)
    client = _client()
    with caplog.at_level("INFO", logger="kudosy.strava_client"):
        await client.fetch_following_feed("1", target=500)
    await client.aclose()
    assert "stop reason: feed end" in caplog.text


@pytest.mark.asyncio
@respx.mock
async def test_pacing_pauses_within_ranges_and_long_pause_rate_limited() -> None:
    from kudosy.strava_client import (
        _FEED_FIRST_PAGE_DELAY_RANGE,
        _FEED_LONG_PAUSE_RANGE,
        _FEED_PAGE_DELAY_RANGE,
    )

    class AlwaysLong(random.Random):
        def random(self) -> float:  # always below the long-pause probability
            return 0.0

    _mock_pages(40, per_page=1)
    sleep = AsyncMock()
    client = StravaClient({"_strava4_session": "cookie"}, sleep=sleep, rng=AlwaysLong(1))
    await client.fetch_following_feed("1", target=500)
    await client.aclose()
    pauses = [c.args[0] for c in sleep.call_args_list]
    assert _FEED_FIRST_PAGE_DELAY_RANGE[0] <= pauses[0] <= _FEED_FIRST_PAGE_DELAY_RANGE[1]
    kinds = []
    for pause in pauses[1:]:
        if _FEED_LONG_PAUSE_RANGE[0] <= pause <= _FEED_LONG_PAUSE_RANGE[1]:
            kinds.append("long")
        else:
            assert _FEED_PAGE_DELAY_RANGE[0] <= pause <= _FEED_PAGE_DELAY_RANGE[1]
            kinds.append("short")
    assert "long" in kinds
    longs = [i for i, k in enumerate(kinds) if k == "long"]
    assert len(longs) >= 2
    assert all(b - a == 4 for a, b in itertools.pairwise(longs))


@pytest.mark.asyncio
@respx.mock
async def test_later_page_failure_stop_reason_feed_error(
    caplog: pytest.LogCaptureFixture,
) -> None:
    respx.get("https://www.strava.com/dashboard/feed").mock(
        side_effect=[
            httpx.Response(200, json=_page([_act_entry(1)], True)),
            httpx.Response(200, text="<html>nope</html>"),
        ]
    )
    client = _client()
    with caplog.at_level("INFO", logger="kudosy.strava_client"):
        result = await client.fetch_following_feed("1")
    await client.aclose()
    assert _ids(result) == [1]
    assert "stop reason: feed error" in caplog.text
