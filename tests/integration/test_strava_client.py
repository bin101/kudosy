"""Integration tests for strava_client.py — uses respx to mock httpx calls."""

from __future__ import annotations

import random
from pathlib import Path
from unittest.mock import AsyncMock

import httpx
import pytest
import respx

from kudosy.feed import AuthError, RateLimitError
from kudosy.strava_client import StravaClient, _next_cursor_params

# Fixtures directory
_FIXTURES = Path(__file__).parent.parent / "fixtures"


def _load(name: str) -> str:
    return (_FIXTURES / name).read_text(encoding="utf-8")


# ── get_csrf_token ─────────────────────────────────────────────────────────────


@pytest.mark.asyncio
@respx.mock
async def test_get_csrf_token_success() -> None:
    html = _load("csrf_page.html")
    respx.get("https://www.strava.com/dashboard").mock(return_value=httpx.Response(200, text=html))

    client = StravaClient({"_strava4_session": "test-cookie-value"})
    token = await client.get_csrf_token()
    await client.aclose()

    assert token == "test-csrf-abc123"


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


def _act_entry(act_id: int, rank: float = 9000.0, updated_at: int = 1000) -> dict:
    """Build a minimal Activity feed entry with cursorData."""
    return {
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
    """Loop stops after _FEED_MAX_PAGES even when hasMore stays true forever."""
    from kudosy.strava_client import _FEED_MAX_PAGES

    infinite_page = _page([_act_entry(1, rank=9000.0, updated_at=1800)], has_more=True)

    # Provide more responses than the cap — only _FEED_MAX_PAGES should be consumed
    respx.get("https://www.strava.com/dashboard/feed").mock(
        side_effect=[httpx.Response(200, json=infinite_page)] * (_FEED_MAX_PAGES + 2)
    )

    client = StravaClient({"_strava4_session": "cookie"}, sleep=AsyncMock(), rng=random.Random(0))
    await client.fetch_following_feed("111")
    await client.aclose()

    assert len(respx.calls) == _FEED_MAX_PAGES


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
    """sleep is called exactly (n_pages - 1) times."""
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

    # 3 pages → 2 pauses (after page 1, after page 2, not after the last)
    assert mock_sleep.call_count == 2


# ── Cookie jar, rotation & auth diagnostics ───────────────────────────────────

_CSRF_HTML = '<html><head><meta name="csrf-token" content="tok123"></head></html>'
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

_NEXT_DASHBOARD = (
    '<html><head><script id="__NEXT_DATA__" type="application/json">{}</script>'
    '<meta name="csrf" content="next-token-not-used"></head></html>'
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
    assert await client.get_csrf_token() == "tok123"
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
    assert await client.get_csrf_token() == "tok123"
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
    assert "next-token-not-used" not in caplog.text


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
    assert await client.get_csrf_token() == "tok123"
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
    assert await client.get_csrf_token() == "tok123"
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
    assert await client.get_csrf_token() == "tok123"
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
    assert "len=6" in caplog.text
    assert "tok123" not in caplog.text
