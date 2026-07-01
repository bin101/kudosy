"""Strava HTTP client — all network calls and authentication live here.

All assumptions about Strava's URL structure and response format are
encapsulated in this module and feed.py. Changing endpoints only touches here.

Authentication: uses the user's _strava4_session browser cookie.
The CSRF token is extracted from a page's <meta name="csrf-token"> tag.

Feed format (verified 2026-07-01 via HAR capture):
  The following feed is a JSON XHR endpoint::

      GET /dashboard/feed?feed_type=following&athlete_id=<id>
      Accept: application/json
      X-Requested-With: XMLHttpRequest
      Accept-Language: en   ← forces English stat labels & decimal format

  Pagination: every response carries ``{"entries": [...], "pagination": {"hasMore": bool}}``.
  Each entry (Activity **and** Challenge) includes::

      "cursorData": {"updated_at": <unix seconds>, "rank": <float>}

  The next (older) page is fetched by appending to the same URL::

      before=int(last_entry.cursorData["updated_at"])
      cursor=int(last_entry.cursorData["rank"])

  Fetching continues while ``pagination.hasMore`` is true, until
  ``_FEED_MAX_PAGES`` pages or ``_FEED_TARGET_ACTIVITIES`` activity entries
  have been collected. The merged result looks like a single-page response so
  :class:`~kudosy.feed.StructuredFeedParser` stays unchanged.

  Use fetch_current_athlete_id() to resolve the athlete ID when the user has
  not configured one explicitly.
"""

from __future__ import annotations

import asyncio
import json
import logging
import random
import re
from collections.abc import Awaitable, Callable
from pathlib import Path
from typing import Any

import httpx

from kudosy.feed import AuthError
from kudosy.parsers import parse_athlete_name

log = logging.getLogger(__name__)

# Strava endpoints — verified via browser DevTools / HAR captures.
_BASE = "https://www.strava.com"
_DASHBOARD_URL = f"{_BASE}/dashboard"
_FEED_URL = f"{_BASE}/dashboard/feed"
_CURRENT_ATHLETE_URL = f"{_BASE}/frontend/athletes/current"
_KUDO_URL = f"{_BASE}/feed/activity/{{activity_id}}/kudo"
_ATHLETE_URL = f"{_BASE}/athletes/{{athlete_id}}"
_ATHLETE_SEARCH_URL = f"{_BASE}/athletes/search"

# Feed pagination limits — fixed constants, no UI knob needed.
# ~20 entries/page (Activities + Challenges mixed) → 6 pages ≈ 100+ activities.
_FEED_MAX_PAGES = 6
_FEED_TARGET_ACTIVITIES = 100
# Human-like pause between page requests (seconds). Keeps us gentle with Strava.
_FEED_PAGE_DELAY_RANGE = (0.5, 1.5)

_CSRF_RE = re.compile(r'<meta\s+name="csrf-token"\s+content="([^"]+)"', re.IGNORECASE)

# Athlete search: results are embedded in a <script id="__NEXT_DATA__"> tag
# under props.pageProps.searchResults (verified from HAR traffic capture).
_NEXT_DATA_RE = re.compile(
    r'<script id="__NEXT_DATA__" type="application/json">(.*?)</script>',
    re.DOTALL,
)

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

    def __init__(
        self,
        session_cookie: str,
        *,
        sleep: Callable[[float], Awaitable[None]] | None = None,
        rng: random.Random | None = None,
    ) -> None:
        self._cookie = session_cookie
        self._client: httpx.AsyncClient | None = None
        # Inject sleep/rng for deterministic testing (analogous to humanizer.py).
        self._sleep: Callable[[float], Awaitable[None]] = (
            sleep if sleep is not None else asyncio.sleep
        )
        self._rng = rng if rng is not None else random.Random()

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

    async def fetch_current_athlete_id(self) -> str | None:
        """Return the numeric athlete ID string for the current session.

        Fetches ``/frontend/athletes/current`` and reads
        ``currentAthlete.id_str``.  Returns ``None`` on any error.
        """
        client = self._get_client()
        try:
            resp = await client.get(
                _CURRENT_ATHLETE_URL,
                headers={"Accept": "application/json"},
                timeout=10.0,
            )
            self._check_auth(resp)
            data = resp.json()
            id_str = (
                data.get("currentAthlete", {}).get("id_str")
                or str(data.get("currentAthlete", {}).get("id") or "")
                or None
            )
            return id_str or None
        except Exception:
            log.debug("Could not resolve current athlete ID", exc_info=True)
            return None

    async def fetch_following_feed(
        self, athlete_id: str, *, dump_raw: Path | None = None
    ) -> dict[str, Any]:
        """Fetch the following activity feed, merging multiple pages into one dict.

        Calls ``GET /dashboard/feed?feed_type=following&athlete_id=<id>`` and
        follows Strava's cursor pagination (``before`` / ``cursor`` params
        derived from each page's last entry ``cursorData``) until:

        * ``pagination.hasMore`` is false, or
        * ``_FEED_MAX_PAGES`` pages have been fetched, or
        * ``_FEED_TARGET_ACTIVITIES`` unique activities have been collected.

        A short random pause (``_FEED_PAGE_DELAY_RANGE``) is inserted between
        page requests to keep requests human-like.

        The ``Accept-Language: en`` header is sent to get English stat labels
        and English decimal formatting, ensuring deterministic parsing.

        Args:
            athlete_id:  The numeric Strava athlete ID of the logged-in user.
            dump_raw:    If given, write the merged JSON bytes to this path
                         (useful for debugging format changes).

        Returns:
            A merged ``{"entries": [...], "pagination": {...}}`` dict
            equivalent to what the caller would see from a single-page response.
            :class:`~kudosy.feed.StructuredFeedParser` can consume it unchanged.

        Raises:
            AuthError: if the session cookie is expired/invalid.
        """
        client = self._get_client()
        feed_headers = {
            "Accept": "application/json, text/plain, */*",
            "X-Requested-With": "XMLHttpRequest",
            "Referer": _DASHBOARD_URL,
            "Accept-Language": "en",
        }
        params: dict[str, Any] = {"feed_type": "following", "athlete_id": athlete_id}
        merged_entries: list[Any] = []
        seen_activity_ids: set[Any] = set()
        last_pagination: dict[str, Any] = {}

        for page_num in range(_FEED_MAX_PAGES):
            resp = await client.get(_FEED_URL, params=params, headers=feed_headers, timeout=15.0)
            self._check_auth(resp)
            payload: dict[str, Any] = resp.json()
            entries: list[Any] = payload.get("entries") or []
            last_pagination = payload.get("pagination") or {}

            for entry in entries:
                act = entry.get("activity") if isinstance(entry, dict) else None
                aid = act.get("id") if isinstance(act, dict) else None
                if aid is not None and aid in seen_activity_ids:
                    continue
                if aid is not None:
                    seen_activity_ids.add(aid)
                merged_entries.append(entry)

            log.debug(
                "Feed page %d: %d entries, %d unique activities so far",
                page_num + 1,
                len(entries),
                len(seen_activity_ids),
            )

            if not last_pagination.get("hasMore"):
                break
            if len(seen_activity_ids) >= _FEED_TARGET_ACTIVITIES:
                log.debug(
                    "Reached target of %d activities, stopping pagination",
                    _FEED_TARGET_ACTIVITIES,
                )
                break

            cursor = _next_cursor_params(entries)
            if cursor is None:
                log.debug("No cursorData on last entry despite hasMore=true, stopping")
                break
            params = {"feed_type": "following", "athlete_id": athlete_id, **cursor}

            # Human-like pause before fetching the next page.
            await self._sleep(self._rng.uniform(*_FEED_PAGE_DELAY_RANGE))

        log.info(
            "Feed fetched: %d unique activities across up to %d pages",
            len(seen_activity_ids),
            _FEED_MAX_PAGES,
        )

        merged: dict[str, Any] = {"entries": merged_entries, "pagination": last_pagination}
        if dump_raw is not None:
            try:
                dump_raw.write_bytes(json.dumps(merged).encode())
                log.debug(
                    "Raw feed (merged, %d entries) dumped to %s",
                    len(merged_entries),
                    dump_raw,
                )
            except OSError as exc:
                log.debug("Could not dump raw feed: %s", exc)
        return merged

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

    async def search_athletes(self, query: str) -> list[dict[str, str]]:
        """Search for athletes by name on Strava.

        Fetches ``/athletes/search?text=<query>&gsf=1`` as a regular browser
        document (text/html).  The results are embedded in the page as a
        Next.js ``__NEXT_DATA__`` JSON blob under
        ``props.pageProps.searchResults``.

        Verified via HAR traffic capture — not a JSON API, not XHR.
        On any error or unexpected response shape, returns an empty list.
        """
        client = self._get_client()
        try:
            resp = await client.get(
                _ATHLETE_SEARCH_URL,
                params={"text": query, "gsf": "1"},
                headers={
                    **_BROWSER_HEADERS,
                    "Referer": _DASHBOARD_URL,
                },
                timeout=15.0,
            )
            self._check_auth(resp)
            if not resp.is_success:
                log.warning("Athlete search returned %d for query %r", resp.status_code, query)
                return []
            return _parse_athlete_search_results(_extract_search_results(resp.text))
        except httpx.RequestError as exc:
            log.warning("Athlete search network error: %s", exc)
            return []

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
            err = AuthError(
                "Strava-Session-Cookie ist ungültig oder abgelaufen. "
                "Bitte neuen Cookie in der Konfiguration eintragen."
            )
            err.code = "AUTH_INVALID_COOKIE"
            raise err
        if resp.status_code == 401:
            err = AuthError("Authentifizierung fehlgeschlagen (HTTP 401).")
            err.code = "AUTH_FAILED"
            raise err


def _next_cursor_params(entries: list[Any]) -> dict[str, int] | None:
    """Return next-page ``before``/``cursor`` params from the last entry's ``cursorData``.

    Strava's following feed uses cursor pagination (verified 2026-07-01 via HAR):
    each entry carries ``cursorData: {"updated_at": <unix s>, "rank": <float>}``.
    The next (older) page is requested with ``before=int(updated_at)`` and
    ``cursor=int(rank)`` from the *last* entry in the current page.

    Returns ``None`` if ``cursorData`` is absent or incomplete so the caller
    can abort pagination gracefully instead of making a malformed request.
    """
    if not entries:
        return None
    last = entries[-1]
    if not isinstance(last, dict):
        return None
    cd = last.get("cursorData")
    if not isinstance(cd, dict):
        return None
    updated_at = cd.get("updated_at")
    rank = cd.get("rank")
    if updated_at is None or rank is None:
        return None
    return {"before": int(updated_at), "cursor": int(rank)}


def _extract_search_results(html: str) -> list[Any]:
    """Pull ``props.pageProps.searchResults`` out of the ``__NEXT_DATA__`` blob.

    Strava's athlete search page embeds results as JSON in a
    ``<script id="__NEXT_DATA__" type="application/json">`` tag.
    Returns the raw list of athlete dicts, or [] on any failure.
    """
    m = _NEXT_DATA_RE.search(html)
    if not m:
        return []
    try:
        data = json.loads(m.group(1))
    except (json.JSONDecodeError, ValueError):
        log.warning("__NEXT_DATA__ JSON could not be parsed in athlete search response")
        return []
    results = data.get("props", {}).get("pageProps", {}).get("searchResults")
    return results if isinstance(results, list) else []


def _parse_athlete_search_results(data: object) -> list[dict[str, str]]:
    """Normalise a raw athlete list from Strava's search page into uniform dicts.

    Each Strava athlete object (from ``props.pageProps.searchResults``) carries:
      - ``id`` (int) — numeric athlete ID
      - ``name`` — full display name
      - ``firstname`` — fallback if ``name`` is absent
      - ``picture`` — avatar URL (large; the real Strava field name)

    Also handles legacy/alternative shapes as fallbacks (``athlete_id``,
    ``display_name``, ``profile_medium``, ``avatar_url``, etc.) in case the
    response structure changes.

    Returns normalised ``{"id": str, "name": str, "avatarUrl": str}`` dicts.
    Unknown shapes and errors yield an empty list — never raises.
    """
    try:
        # Support both a bare list (from _extract_search_results) and legacy
        # wrapped shapes {"athletes": [...]} or {"results": [...]}
        if isinstance(data, dict):
            athletes_raw: list[Any] = (
                data.get("athletes") or data.get("results") or data.get("data") or []
            )
        elif isinstance(data, list):
            athletes_raw = data
        else:
            return []

        results: list[dict[str, str]] = []
        for item in athletes_raw:
            if not isinstance(item, dict):
                continue
            athlete_id = str(
                item.get("id") or item.get("athlete_id") or item.get("athleteId") or ""
            )
            if not athlete_id or athlete_id == "0":
                continue
            name = str(
                item.get("name")
                or item.get("display_name")
                or item.get("displayName")
                or (f"{item.get('firstname', '')} {item.get('lastname', '')}".strip())
                or "Unbekannt"
            )
            # Real Strava field is "picture"; keep fallbacks for robustness.
            avatar = str(
                item.get("picture")
                or item.get("profile_medium")
                or item.get("avatar_url")
                or item.get("avatarUrl")
                or item.get("profile")
                or ""
            )
            results.append({"id": athlete_id, "name": name, "avatarUrl": avatar})
        return results
    except Exception:
        log.warning("Unexpected athlete search response shape", exc_info=True)
        return []
