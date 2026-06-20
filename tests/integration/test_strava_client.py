"""Integration tests for strava_client.py — uses respx to mock httpx calls."""

from __future__ import annotations

from pathlib import Path

import httpx
import pytest
import respx

from kudosy.feed import AuthError
from kudosy.strava_client import StravaClient

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
async def test_fetch_feed_returns_html() -> None:
    """fetch_following_feed fetches /dashboard and returns raw HTML."""
    html = _load("feed_react_props.html")
    respx.get("https://www.strava.com/dashboard").mock(return_value=httpx.Response(200, text=html))

    client = StravaClient("test-cookie-value")
    result = await client.fetch_following_feed()
    await client.aclose()

    assert isinstance(result, str)
    assert "data-react-props" in result


@pytest.mark.asyncio
@respx.mock
async def test_fetch_feed_passes_num_entries_param() -> None:
    """fetch_following_feed passes num_entries as a query parameter."""
    respx.get("https://www.strava.com/dashboard").mock(
        return_value=httpx.Response(200, text="<html></html>")
    )

    client = StravaClient("test-cookie-value")
    await client.fetch_following_feed(num_entries=30)
    await client.aclose()

    assert respx.calls.last.request.url.params["num_entries"] == "30"


@pytest.mark.asyncio
@respx.mock
async def test_fetch_feed_auth_redirect_raises() -> None:
    """Auth redirect during feed fetch raises AuthError (redirect to login URL)."""
    # Simulate Strava redirecting an expired cookie to the login page
    respx.get("https://www.strava.com/dashboard").mock(
        return_value=httpx.Response(
            302,
            headers={"location": "https://www.strava.com/login"},
        )
    )
    respx.get("https://www.strava.com/login").mock(
        return_value=httpx.Response(200, text="<html>login page</html>")
    )

    client = StravaClient("expired-cookie")
    with pytest.raises(AuthError):
        await client.fetch_following_feed()
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
async def test_send_kudos_rate_limit_returns_false() -> None:
    respx.post("https://www.strava.com/feed/activity/10000000002/kudo").mock(
        return_value=httpx.Response(429, text="Rate limited")
    )

    client = StravaClient("test-cookie-value")
    result = await client.send_kudos("10000000002", "csrf")
    await client.aclose()

    assert result is False


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
