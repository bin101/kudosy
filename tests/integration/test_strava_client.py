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

    client = StravaClient("test-cookie-value")
    token = await client.get_csrf_token()
    await client.aclose()

    assert token == "test-csrf-abc123"


@pytest.mark.asyncio
@respx.mock
async def test_get_csrf_token_missing_raises() -> None:
    respx.get("https://www.strava.com/dashboard").mock(
        return_value=httpx.Response(200, text="<html><head></head><body>no csrf</body></html>")
    )

    client = StravaClient("test-cookie-value")
    with pytest.raises(RuntimeError, match="CSRF"):
        await client.get_csrf_token()
    await client.aclose()


@pytest.mark.asyncio
@respx.mock
async def test_get_csrf_token_login_redirect_raises_auth_error() -> None:
    """When the resolved URL is a login page, _check_auth raises AuthError."""
    client = StravaClient("expired-cookie")
    login_resp = httpx.Response(
        200,
        text="<html>login</html>",
        request=httpx.Request("GET", "https://www.strava.com/login"),
    )
    with pytest.raises(AuthError):
        client._check_auth(login_resp)


@pytest.mark.asyncio
async def test_check_auth_raises_on_login_url() -> None:
    client = StravaClient("bad-cookie")
    resp = httpx.Response(
        200,
        text="",
        request=httpx.Request("GET", "https://www.strava.com/login"),
    )
    with pytest.raises(AuthError):
        client._check_auth(resp)


@pytest.mark.asyncio
async def test_check_auth_raises_on_401() -> None:
    client = StravaClient("bad-cookie")
    resp = httpx.Response(
        401,
        text="Unauthorized",
        request=httpx.Request("GET", "https://www.strava.com/dashboard"),
    )
    with pytest.raises(AuthError, match="401"):
        client._check_auth(resp)


# ── fetch_following_feed ───────────────────────────────────────────────────────


@pytest.mark.asyncio
@respx.mock
async def test_fetch_feed_returns_json_dict() -> None:
    """fetch_following_feed calls the JSON XHR endpoint and returns a parsed dict."""
    feed_payload = {"entries": [], "pagination": {"hasMore": False}}
    respx.get("https://www.strava.com/dashboard/feed").mock(
        return_value=httpx.Response(200, json=feed_payload)
    )

    client = StravaClient("test-cookie-value")
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

    client = StravaClient("test-cookie-value")
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

    client = StravaClient("test-cookie-value")
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

    client = StravaClient("expired-cookie")
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

    client = StravaClient("test-cookie-value")
    result = await client.send_kudos("10000000001", "test-csrf-abc123")
    await client.aclose()

    assert result is True


@pytest.mark.asyncio
@respx.mock
async def test_send_kudos_rate_limit_raises() -> None:
    respx.post("https://www.strava.com/feed/activity/10000000002/kudo").mock(
        return_value=httpx.Response(429, text="Rate limited")
    )

    client = StravaClient("test-cookie-value")
    with pytest.raises(RateLimitError):
        await client.send_kudos("10000000002", "csrf")
    await client.aclose()


@pytest.mark.asyncio
@respx.mock
async def test_send_kudos_network_error_returns_false() -> None:
    respx.post("https://www.strava.com/feed/activity/10000000003/kudo").mock(
        side_effect=httpx.ConnectError("Connection refused")
    )

    client = StravaClient("test-cookie-value")
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

    client = StravaClient("test-cookie-value")
    name = await client.lookup_athlete("20000001")
    await client.aclose()

    assert name == "Alex Runner"


@pytest.mark.asyncio
@respx.mock
async def test_lookup_athlete_not_found_returns_none() -> None:
    respx.get("https://www.strava.com/athletes/99999999").mock(
        return_value=httpx.Response(404, text="Not Found")
    )

    client = StravaClient("test-cookie-value")
    name = await client.lookup_athlete("99999999")
    await client.aclose()

    assert name is None


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

    client = StravaClient("cookie", sleep=AsyncMock(), rng=random.Random(0))
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

    client = StravaClient("cookie", sleep=AsyncMock(), rng=random.Random(0))
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

    client = StravaClient("cookie", sleep=AsyncMock(), rng=random.Random(0))
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

    client = StravaClient("cookie", sleep=AsyncMock(), rng=random.Random(0))
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

    client = StravaClient("cookie", sleep=AsyncMock(), rng=random.Random(0))
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

    client = StravaClient("cookie", sleep=AsyncMock(), rng=random.Random(0))
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

    client = StravaClient("cookie", sleep=AsyncMock(), rng=random.Random(0))
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
    client = StravaClient("cookie", sleep=mock_sleep, rng=random.Random(0))
    await client.fetch_following_feed("42")
    await client.aclose()

    # 3 pages → 2 pauses (after page 1, after page 2, not after the last)
    assert mock_sleep.call_count == 2
