"""Strava HTTP client — all network calls and authentication live here.

All assumptions about Strava's URL structure and response format are
encapsulated in this module and feed.py. Changing endpoints only touches here.

Authentication: uses the user's _strava4_session browser cookie.
The CSRF token is extracted from a page's <meta name="csrf-token"> tag.
"""

from __future__ import annotations

import logging
import re
from typing import Any

import httpx

from kudosy.feed import AuthError
from kudosy.parsers import parse_athlete_name

log = logging.getLogger(__name__)

# Strava endpoints (hypotheses — verify via DevTools if the feed stops working)
_BASE = "https://www.strava.com"
_DASHBOARD_URL = f"{_BASE}/dashboard"
_FEED_URL = f"{_BASE}/dashboard/feed"
_KUDO_URL = f"{_BASE}/feed/activity/{{activity_id}}/kudo"
_ATHLETE_URL = f"{_BASE}/athletes/{{athlete_id}}"

_CSRF_RE = re.compile(r'<meta\s+name="csrf-token"\s+content="([^"]+)"', re.IGNORECASE)

_BROWSER_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/131.0.0.0 Safari/537.36"
    ),
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
    "Accept-Language": "de-DE,de;q=0.9,en;q=0.8",
}


def _mask_cookie(cookie: str) -> str:
    """Return first 8 chars + '…' for safe logging."""
    return cookie[:8] + "…" if len(cookie) > 8 else "***"


class StravaClient:
    """Async Strava HTTP client."""

    def __init__(self, session_cookie: str) -> None:
        self._cookie = session_cookie
        self._client: httpx.AsyncClient | None = None

    def _get_client(self) -> httpx.AsyncClient:
        if self._client is None or self._client.is_closed:
            self._client = httpx.AsyncClient(
                headers={
                    **_BROWSER_HEADERS,
                    "Cookie": f"_strava4_session={self._cookie}",
                },
                follow_redirects=True,
                timeout=30.0,
            )
        return self._client

    async def aclose(self) -> None:
        if self._client and not self._client.is_closed:
            await self._client.aclose()

    async def get_csrf_token(self) -> str:
        """Fetch the dashboard page and extract the CSRF token."""
        log.debug("Fetching CSRF token (cookie: %s)", _mask_cookie(self._cookie))
        client = self._get_client()
        resp = await client.get(_DASHBOARD_URL, timeout=10.0)
        self._check_auth(resp)
        m = _CSRF_RE.search(resp.text)
        if not m:
            raise RuntimeError("Could not extract CSRF token from dashboard page")
        token = m.group(1)
        log.debug("CSRF Token: %s…", token[:8])
        return token

    async def fetch_following_feed(self, *, page: int = 1) -> dict[str, Any] | str:
        """Fetch the following activity feed.

        Tries the JSON feed endpoint first; falls back to HTML dashboard.
        Returns either a parsed dict (JSON) or raw HTML string.
        """
        client = self._get_client()
        # Try JSON API endpoint
        try:
            resp = await client.get(
                _FEED_URL,
                params={"feed_type": "following", "athlete_id": "", "page": page},
                headers={
                    "Accept": "application/json, text/javascript, */*; q=0.01",
                    "X-Requested-With": "XMLHttpRequest",
                },
                timeout=15.0,
            )
            self._check_auth(resp)
            if resp.headers.get("content-type", "").startswith("application/json"):
                result: dict[str, Any] = resp.json()
                return result
        except (httpx.HTTPStatusError, httpx.RequestError) as exc:
            log.debug("JSON feed request failed (%s); trying HTML dashboard", exc)

        # Fallback: fetch HTML dashboard
        resp = await client.get(_DASHBOARD_URL, timeout=15.0)
        self._check_auth(resp)
        return resp.text

    async def send_kudos(self, activity_id: str, csrf_token: str) -> bool:
        """POST a kudo for *activity_id*. Returns True on success."""
        client = self._get_client()
        url = _KUDO_URL.format(activity_id=activity_id)
        try:
            resp = await client.post(
                url,
                headers={
                    "X-CSRF-Token": csrf_token,
                    "X-Requested-With": "XMLHttpRequest",
                    "Accept": "application/json, text/javascript, */*; q=0.01",
                    "Content-Type": "application/x-www-form-urlencoded; charset=UTF-8",
                    "Origin": _BASE,
                    "Referer": f"{_BASE}/dashboard",
                },
                timeout=15.0,
            )
            if resp.status_code in (200, 201):
                return True
            if resp.status_code == 429:
                log.warning(
                    "Strava Rate-Limit (429) beim Senden der Kudos für Activity %s", activity_id
                )
                return False
            log.warning("Unexpected status %d sending kudos to %s", resp.status_code, activity_id)
            return False
        except httpx.RequestError as exc:
            log.error("Network error sending kudos to %s: %s", activity_id, exc)
            return False

    async def lookup_athlete(self, athlete_id: str) -> str | None:
        """Scrape an athlete's display name from their profile page."""
        client = self._get_client()
        url = _ATHLETE_URL.format(athlete_id=athlete_id)
        try:
            resp = await client.get(url, timeout=8.0)
            if not resp.is_success:
                return None
            return parse_athlete_name(resp.text)
        except httpx.RequestError:
            return None

    def _check_auth(self, resp: httpx.Response) -> None:
        """Raise AuthError if Strava redirected to the login page."""
        url_str = str(resp.url)
        if "login" in url_str or "sessions" in url_str:
            raise AuthError(
                "Strava-Session-Cookie ist ungültig oder abgelaufen. "
                "Bitte neuen Cookie in der Konfiguration eintragen."
            )
        if resp.status_code == 401:
            raise AuthError("Authentifizierung fehlgeschlagen (HTTP 401).")
