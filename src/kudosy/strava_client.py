"""Strava HTTP client — all network calls and authentication live here.

All assumptions about Strava's URL structure and response format are
encapsulated in this module and feed.py. Changing endpoints only touches here.

Authentication: uses the user's Strava browser cookies (``_strava4_session`` plus the
remember-me pair). They live in a real cookie jar, so ``Set-Cookie`` rotations — e.g. a
fresh session issued from the remember-me token — are sent on automatically and can be
read back via :meth:`StravaClient.current_cookies` for persistence.

Dashboard (verified 2026-10-28 via HAR): Strava migrated ``/dashboard`` to Next.js
(``GET /dashboard`` -> 302 ``/dashboard?dashboard_next=1``). One request now yields
everything needed to start a run: the CSRF token (``<meta name="csrf">``, the same kind of
token as the Rails ``csrf-token`` meta), the athlete ID and the first feed page, both
embedded in ``__NEXT_DATA__``. See :meth:`StravaClient.get_csrf_token` for the sources and
their order. The kudo endpoint itself (``POST /feed/activity/<id>/kudo`` +
``x-csrf-token``) is unchanged.

Feed format (verified 2026-07-01 via HAR capture):
  The following feed is a JSON XHR endpoint::

      GET /dashboard/feed?feed_type=following&athlete_id=<id>
      Accept: application/json
      X-Requested-With: XMLHttpRequest
      Accept-Language: en   ← forces English stat labels & decimal format

  The first page is already embedded in the dashboard HTML
  (``__NEXT_DATA__`` -> ``props.pageProps.dashboardData.feed``, same shape), so the XHR is
  only needed for pages 2+ (verified 2026-10-29 via HAR). The embedded page reports
  ``hasMore=false`` although the browser still loads more pages, so that flag is never
  trusted: one XHR page is always tried after it. Failures there degrade gracefully.

  Pagination: every response carries ``{"entries": [...], "pagination": {"hasMore": bool}}``.
  Each entry (Activity **and** Challenge) includes::

      "cursorData": {"updated_at": <unix seconds>, "rank": <int or float>}

  The next (older) page is fetched by appending to the same URL::

      before=int(min(cursorData["updated_at"] over ALL entries collected so far))
      cursor=int(last_entry_of_previous_page.cursorData["rank"])

  (``updated_at`` is not sorted, so ``before`` is a running minimum across pages; verified
  2026-10-29 via HAR, which also shows the browser sending ``X-CSRF-Token`` on the XHR.)
  Fetching continues while ``pagination.hasMore`` of an XHR response is true, until
  ``_FEED_MAX_PAGES`` pages or ``_FEED_TARGET_ACTIVITIES`` activity entries
  have been collected. The merged result looks like a single-page response so
  :class:`~kudosy.feed.StructuredFeedParser` stays unchanged.

  Use fetch_current_athlete_id() to resolve the athlete ID when the user has
  not configured one explicitly.
"""

from __future__ import annotations

import asyncio
import contextlib
import json
import logging
import random
import re
from collections.abc import Awaitable, Callable
from datetime import UTC, datetime
from email.utils import parsedate_to_datetime
from pathlib import Path
from typing import Any
from urllib.parse import urlsplit

import httpx

from kudosy.feed import AuthError, RateLimitError
from kudosy.parsers import REMEMBER_COOKIES, is_strava_cookie_name, parse_athlete_name

log = logging.getLogger(__name__)

# Strava endpoints — verified via browser DevTools / HAR captures.
_BASE = "https://www.strava.com"
_DASHBOARD_URL = f"{_BASE}/dashboard"
_FEED_URL = f"{_BASE}/dashboard/feed"
_CURRENT_ATHLETE_URL = f"{_BASE}/frontend/athletes/current"
_KUDO_URL = f"{_BASE}/feed/activity/{{activity_id}}/kudo"
# Rails page (has <meta name="csrf-token">) used as the last-resort CSRF source.
_TRAINING_URL = f"{_BASE}/athlete/training"
_ATHLETE_URL = f"{_BASE}/athletes/{{athlete_id}}"
_ATHLETE_SEARCH_URL = f"{_BASE}/athletes/search"

# Feed pagination limits — fixed constants, no UI knob needed.
# ~20 entries/page (Activities + Challenges mixed) → 6 pages ≈ 100+ activities.
_FEED_MAX_PAGES = 6
_FEED_TARGET_ACTIVITIES = 100
# Human-like pause between page requests (seconds). Keeps us gentle with Strava.
_FEED_PAGE_DELAY_RANGE = (0.5, 1.5)

# Rails pages call the meta "csrf-token", the Next.js dashboard "csrf"; same token kind.
_CSRF_RE = re.compile(r'<meta\s+name="csrf(?:-token)?"\s+content="([^"]+)"', re.IGNORECASE)
# Plausibility only (URL-safe Base64, no fixed length): keeps a stray non-token meta out.
_CSRF_PLAUSIBLE_RE = re.compile(r"^[A-Za-z0-9_\-+/=]{40,}$")

# Next.js pages embed their data in a <script id="__NEXT_DATA__"> tag: the athlete search
# results under props.pageProps.searchResults, the dashboard's athlete ID and first feed
# page under props.currentAthletePreload / props.pageProps.dashboardData (HAR captures).
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
# English labels and decimal format keep stat parsing deterministic (dashboard + feed XHR).
_EN_HEADERS = {"Accept-Language": "en"}


def _mask_cookie(cookie: str) -> str:
    """Return first 8 chars + '…' for safe logging."""
    return cookie[:8] + "…" if len(cookie) > 8 else "***"


_COOKIE_DOMAIN = ".strava.com"
_REMEMBER_TOKEN = "strava_remember_token"
# Redirect targets that mean "not logged in".
_LOGIN_PATH_RE = re.compile(r"(^|/)(login|sessions?)(/|$)")


def _cookie_names(header: str) -> list[str]:
    """Cookie names of a Cookie request header, in sent order."""
    return [p.strip().split("=", 1)[0] for p in header.split(";") if "=" in p]


def _masked_cookie_header(header: str) -> str:
    """``name=value`` pairs of a Cookie header with every value masked.

    The remember token is the long-lived credential, so it is shown by name only —
    not even a prefix of its value.
    """
    pairs = (p.strip().split("=", 1) for p in header.split(";") if "=" in p)
    return (
        ", ".join(n if n == _REMEMBER_TOKEN else f"{n}={_mask_cookie(v)}" for n, v in pairs)
        or "(none)"
    )


def _set_cookie_actions(resp: httpx.Response) -> list[str]:
    """``name:set`` / ``name:deleted`` for every ``Set-Cookie`` header of a response."""
    actions: list[str] = []
    for raw in resp.headers.get_list("set-cookie"):
        attrs = [a.strip() for a in raw.split(";")]
        name = attrs[0].split("=", 1)[0]
        deleted = False
        for attr in attrs[1:]:
            key, _, val = attr.partition("=")
            if key.lower() == "max-age":
                deleted = deleted or val.strip().lstrip("+").startswith(("0", "-"))
            elif key.lower() == "expires":
                try:
                    expires = parsedate_to_datetime(val.strip())
                except (TypeError, ValueError):
                    continue
                if expires.tzinfo is None:
                    expires = expires.replace(tzinfo=UTC)
                deleted = deleted or expires < datetime.now(UTC)
        actions.append(f"{name}:{'deleted' if deleted else 'set'}")
    return actions


def _page_kind(html: str) -> str:
    """Rough page flavour for diagnostics: Strava's Next.js frontend or classic Rails."""
    if "__NEXT_DATA__" in html or "/_next/" in html:
        return "Next.js"
    if _CSRF_RE.search(html):
        return "Rails"
    return "unknown"


# A transient network hiccup (DNS blip, reset connection, momentary timeout)
# shouldn't turn into a hard failure for idempotent GETs — retry a couple of
# times with a short backoff before giving up.
_GET_RETRY_ATTEMPTS = 3
_GET_RETRY_BACKOFF_BASE_S = 0.5


class StravaClient:
    """Async Strava HTTP client."""

    def __init__(
        self,
        cookies: dict[str, str],
        *,
        sleep: Callable[[float], Awaitable[None]] | None = None,
        rng: random.Random | None = None,
    ) -> None:
        self._initial_cookies = dict(cookies)
        # Set once Strava has treated the session as logged out; see current_cookies().
        self._auth_failed = False
        # Athlete ID read while looking for the CSRF token; saves a second request.
        self._athlete_id: str | None = None
        # First feed page embedded in the dashboard HTML; consumed by fetch_following_feed.
        self._dashboard_feed: dict[str, Any] | None = None
        # CSRF token from get_csrf_token(); sent on the feed XHR like the browser does.
        self._csrf_token: str | None = None
        # HTTP status of the most recent send_kudos response (None: no response / no call yet).
        self.last_kudo_status: int | None = None
        self._client: httpx.AsyncClient | None = None
        # Inject sleep/rng for deterministic testing (analogous to humanizer.py).
        self._sleep: Callable[[float], Awaitable[None]] = (
            sleep if sleep is not None else asyncio.sleep
        )
        self._rng = rng if rng is not None else random.Random()

    def _get_client(self) -> httpx.AsyncClient:
        if self._client is None or self._client.is_closed:
            jar = httpx.Cookies()
            for name, value in self._initial_cookies.items():
                jar.set(name, value, domain=_COOKIE_DOMAIN, path="/")
            self._client = httpx.AsyncClient(
                headers=_BROWSER_HEADERS,
                cookies=jar,
                follow_redirects=True,
                timeout=30.0,
                event_hooks={"response": [self._dedupe_cookies]},
            )
        return self._client

    async def _dedupe_cookies(self, response: httpx.Response) -> None:
        """Keep one entry per Strava cookie name: the one a response just set.

        The jar is seeded under ``.strava.com``; a ``Set-Cookie`` without ``Domain``
        lands under ``www.strava.com`` instead, so both would be sent and the server
        would read the old (first) value. httpx stores each hop's cookies before this
        hook runs, so redirect chains are covered too.
        """
        client = self._client
        if client is None:
            return
        for fresh in list(response.cookies.jar):
            if not is_strava_cookie_name(fresh.name) or fresh.is_expired():
                continue
            for old in list(client.cookies.jar):
                if old.name == fresh.name and (old.domain, old.path) != (fresh.domain, fresh.path):
                    client.cookies.jar.clear(old.domain, old.path, old.name)

    def current_cookies(self) -> dict[str, str]:
        """Strava cookies as they stand now, including any ``Set-Cookie`` rotations.

        Falls back to the initial cookies before the first request (or after
        ``aclose``). :meth:`_dedupe_cookies` guarantees one entry per name.

        After an auth failure the initial cookies are returned: whatever Strava set
        on a rejected session (an anonymous session, say) must never replace the
        user's stored cookies.
        """
        if self._client is None or self._auth_failed:
            return dict(self._initial_cookies)
        result: dict[str, str] = {}
        for c in self._client.cookies.jar:
            if not c.domain.endswith("strava.com") or c.value is None:
                continue
            if not is_strava_cookie_name(c.name):
                continue
            result[c.name] = c.value
        return result

    async def aclose(self) -> None:
        if self._client and not self._client.is_closed:
            await self._client.aclose()

    async def _get_with_retry(
        self, client: httpx.AsyncClient, url: str, **kwargs: Any
    ) -> httpx.Response:
        """GET with a short retry/backoff on transient network errors.

        Only retries ``httpx.RequestError`` (connection/DNS/timeout failures
        that never reached Strava) — HTTP error *status codes* are returned
        as-is so callers' own handling (``_check_auth``, ``is_success``
        checks) still applies; those aren't necessarily transient.
        """
        last_exc: httpx.RequestError | None = None
        for attempt in range(_GET_RETRY_ATTEMPTS):
            try:
                return await client.get(url, **kwargs)
            except httpx.RequestError as exc:
                last_exc = exc
                if attempt < _GET_RETRY_ATTEMPTS - 1:
                    delay = _GET_RETRY_BACKOFF_BASE_S * (2**attempt)
                    log.warning(
                        "GET %s failed (%s) — retrying in %.1fs (attempt %d/%d)",
                        url,
                        exc,
                        delay,
                        attempt + 1,
                        _GET_RETRY_ATTEMPTS,
                    )
                    await self._sleep(delay)
        assert last_exc is not None  # loop always returns or sets this
        raise last_exc

    async def get_csrf_token(self) -> str:
        """Auth probe plus CSRF token lookup.

        ``GET /dashboard`` (English) doubles as the login check. Its ``__NEXT_DATA__``
        also yields the athlete ID and the first feed page, cached for
        :meth:`fetch_current_athlete_id` and :meth:`fetch_following_feed`. The token is
        taken from the first of these sources that has a plausible one:

        1. ``<meta name="csrf">`` (Next.js dashboard) or ``<meta name="csrf-token">``
           (old Rails dashboard) on the dashboard.
        2. The ``csrf-token`` *response header* of ``/frontend/athletes/current``.
           The athlete ID in that response is cached as well.
        3. ``<meta name="csrf-token">`` on ``/athlete/training`` (a Rails page).

        Sources 2 and 3 are fallbacks for a dashboard without the meta tag.

        Raises :class:`~kudosy.feed.AuthError` on a logged-out session and
        ``RuntimeError`` when no source yields a token.
        """
        log.debug("Fetching CSRF token (cookies: %s)", ", ".join(sorted(self._initial_cookies)))
        client = self._get_client()
        tried: list[str] = []

        resp = await self._get_with_retry(client, _DASHBOARD_URL, headers=_EN_HEADERS, timeout=10.0)
        self._check_auth(resp, probe=True)
        athlete_id, self._dashboard_feed = _parse_next_data(resp.text)
        self._athlete_id = athlete_id or self._athlete_id
        log.debug(
            "Dashboard __NEXT_DATA__: athlete id %s, embedded feed %s",
            "found" if athlete_id else "missing",
            "found" if self._dashboard_feed else "missing",
        )
        token = _csrf_from_html(resp.text)
        tried.append(self._log_csrf_source("/dashboard", resp, token))
        if token:
            return self._csrf_found("/dashboard meta tag", token)

        resp = await self._get_with_retry(
            client, _CURRENT_ATHLETE_URL, headers={"Accept": "application/json"}, timeout=10.0
        )
        self._check_auth(resp)
        # The athlete ID is optional data and must never break the CSRF flow.
        identified: str | None = None
        with contextlib.suppress(ValueError):
            identified = _athlete_id_from(resp.json())
        self._athlete_id = identified or self._athlete_id
        # Only trust the header from a successful response that identified an athlete:
        # an anonymous session may get a csrf-token header too. Repeated headers are merged
        # by httpx with ", ", so a comma means the value is not a single token.
        header_token = resp.headers.get("csrf-token", "").strip()
        if not (resp.is_success and identified) or "," in header_token:
            header_token = ""
        tried.append(
            self._log_csrf_source("/frontend/athletes/current", resp, header_token or None)
        )
        if header_token:
            return self._csrf_found("/frontend/athletes/current header", header_token)

        resp = await self._get_with_retry(client, _TRAINING_URL, timeout=10.0)
        self._check_auth(resp)
        token = _csrf_from_html(resp.text)
        tried.append(self._log_csrf_source("/athlete/training", resp, token))
        if token:
            return self._csrf_found("/athlete/training meta tag", token)

        log.warning("No CSRF token found (%s)", "; ".join(tried))
        raise RuntimeError("Could not extract CSRF token from any known Strava source")

    @staticmethod
    def _log_csrf_source(path: str, resp: httpx.Response, token: str | None) -> str:
        """Log one CSRF source attempt and return the summary line.

        Only the token's length is logged, never its value.
        """
        line = (
            f"{path} -> {resp.status_code}, page={_page_kind(resp.text)}, "
            f"token={f'found len={len(token)}' if token else 'missing'}"
        )
        log.debug("CSRF source: %s", line)
        return line

    def _csrf_found(self, source: str, token: str) -> str:
        log.info("CSRF token from %s", source)
        self._csrf_token = token
        return token

    async def fetch_current_athlete_id(self) -> str | None:
        """Return the numeric athlete ID string for the current session.

        Fetches ``/frontend/athletes/current`` and reads
        ``currentAthlete.id_str``.  Returns ``None`` on any error. Makes no request
        when :meth:`get_csrf_token` already read the ID (from the dashboard's
        ``__NEXT_DATA__`` or that endpoint).
        """
        if self._athlete_id:
            return self._athlete_id
        client = self._get_client()
        try:
            resp = await self._get_with_retry(
                client,
                _CURRENT_ATHLETE_URL,
                headers={"Accept": "application/json"},
                timeout=10.0,
            )
            self._check_auth(resp)
            return _athlete_id_from(resp.json())
        except AuthError:
            # An expired/invalid cookie must reach the caller, not be
            # swallowed into a silent None — the feed fetch that follows would
            # otherwise fail with a much less clear error.
            raise
        except Exception:
            log.debug("Could not resolve current athlete ID", exc_info=True)
            return None

    async def fetch_following_feed(
        self, athlete_id: str, *, dump_raw: Path | None = None
    ) -> dict[str, Any]:
        """Fetch the following activity feed, merging multiple pages into one dict.

        Page 1 comes from the dashboard HTML when :meth:`get_csrf_token` found a usable
        embedded feed (entries of ``feedType`` ``following``); otherwise, and for every
        further page, it calls ``GET /dashboard/feed?feed_type=following&athlete_id=<id>``
        and follows Strava's cursor pagination (``before`` / ``cursor`` params
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

        A failing XHR for page 2+ (HTML, 4xx/5xx, unexpected format, network error after
        retries) only logs a WARNING and ends pagination with the entries collected so
        far. A login redirect still raises ``AuthError``. One WARNING
        also reports entries whose ``locale`` is not ``en``.

        Raises:
            AuthError: if the session cookie is expired/invalid.
            RuntimeError: if page 1 is neither embedded in the dashboard nor
                          readable from the XHR (the message carries status,
                          content type and path, never any values).
        """
        client = self._get_client()
        feed_headers = {
            "Accept": "application/json, text/plain, */*",
            "X-Requested-With": "XMLHttpRequest",
            "Referer": _DASHBOARD_URL,
            **_EN_HEADERS,
        }
        if self._csrf_token:
            feed_headers["X-CSRF-Token"] = self._csrf_token
        embedded = self._take_embedded_feed(athlete_id)
        params: dict[str, Any] = {"feed_type": "following", "athlete_id": athlete_id}
        merged_entries: list[Any] = []
        seen_activity_ids: set[str] = set()
        last_pagination: dict[str, Any] = {}

        for page_num in range(_FEED_MAX_PAGES):
            if page_num == 0 and embedded is not None:
                log.info("Feed: Seite 1 aus Dashboard")
                payload = embedded
            else:
                try:
                    resp = await self._get_with_retry(
                        client, _FEED_URL, params=params, headers=feed_headers, timeout=15.0
                    )
                except httpx.RequestError as exc:
                    if page_num == 0:
                        raise
                    log.warning(
                        "Feed page %d could not be fetched (%s) — stopping pagination with"
                        " %d activities",
                        page_num + 1,
                        type(exc).__name__,
                        len(seen_activity_ids),
                    )
                    break
                self._check_auth(resp)
                parsed, detail = _feed_payload(resp)
                if parsed is None:
                    if page_num == 0:
                        raise RuntimeError(
                            "Feed page 1 unavailable: no usable feed embedded in the dashboard"
                            f" and the feed request failed ({detail})"
                        )
                    log.warning(
                        "Feed page %d could not be read (%s) — stopping pagination with"
                        " %d activities",
                        page_num + 1,
                        detail,
                        len(seen_activity_ids),
                    )
                    break
                payload = parsed
            entries: list[Any] = payload["entries"]
            last_pagination = payload.get("pagination") or {}

            for entry in entries:
                act = entry.get("activity") if isinstance(entry, dict) else None
                # Page 1 (embedded JSON) and pages 2+ (XHR) may type the same ID differently.
                raw_id = act.get("id") if isinstance(act, dict) else None
                aid = str(raw_id) if raw_id is not None else None
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

            # The embedded page claims hasMore=false although more pages exist: only XHR
            # responses are trusted, so always try at least one XHR page after it.
            from_embedded = page_num == 0 and embedded is not None
            if not from_embedded and not last_pagination.get("hasMore"):
                break
            if len(seen_activity_ids) >= _FEED_TARGET_ACTIVITIES:
                log.debug(
                    "Reached target of %d activities, stopping pagination",
                    _FEED_TARGET_ACTIVITIES,
                )
                break

            cursor = _next_cursor_params(entries, merged_entries)
            if cursor is None:
                log.debug("No usable cursorData for the next page, stopping")
                break
            params = {"feed_type": "following", "athlete_id": athlete_id, **cursor}

            # Human-like pause before fetching the next page.
            await self._sleep(self._rng.uniform(*_FEED_PAGE_DELAY_RANGE))

        log.info(
            "Feed fetched: %d unique activities across up to %d pages",
            len(seen_activity_ids),
            _FEED_MAX_PAGES,
        )
        _warn_on_foreign_locale(merged_entries)

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

    def _take_embedded_feed(self, athlete_id: str) -> dict[str, Any] | None:
        """Hand out (once) the dashboard's embedded feed page if it is usable.

        Usable means: the entries are a list, at least one carries
        ``feedType == "following"``, none has a ``locale`` other than ``en`` (labels
        would not parse; the XHR is asked for English instead) and it belongs to the
        requested athlete.
        """
        feed, self._dashboard_feed = self._dashboard_feed, None
        if feed is None:
            return None
        if self._athlete_id and self._athlete_id != str(athlete_id):
            return None
        entries = feed.get("entries")
        if not isinstance(entries, list) or not any(
            isinstance(e, dict) and e.get("feedType") == "following" for e in entries
        ):
            return None
        if any(isinstance(e, dict) and e.get("locale") not in (None, "en") for e in entries):
            # The XHR page replacing it is checked by the aggregated locale warning.
            return None
        return feed

    async def send_kudos(self, activity_id: str, csrf_token: str) -> bool:
        """POST a kudo for *activity_id*. Returns True only on HTTP 200/201.

        Redirects are not followed: a followed redirect ends on a page that answers
        200 and would be counted as a kudo that was never given. A redirect to a
        login path (or a 401) raises :class:`~kudosy.feed.AuthError`; any other
        non-success status counts as a failure. The HTTP status of the answer is kept
        in :attr:`last_kudo_status` for the caller's log line.
        """
        client = self._get_client()
        url = _KUDO_URL.format(activity_id=activity_id)
        self.last_kudo_status = None
        try:
            resp = await client.post(
                url,
                headers={
                    "X-CSRF-Token": csrf_token,
                    "X-Requested-With": "XMLHttpRequest",
                    # Like the browser: empty body, no Content-Type.
                    "Accept": "application/json, text/plain, */*",
                    "Origin": _BASE,
                    "Referer": f"{_BASE}/dashboard",
                },
                timeout=15.0,
                follow_redirects=False,
            )
        except httpx.RequestError as exc:
            log.error("Network error sending kudos to %s: %s", activity_id, exc)
            return False
        status = resp.status_code
        self.last_kudo_status = status
        if status in (200, 201):
            return True
        if status == 429:
            log.warning(
                "Strava Rate-Limit (429) beim Senden der Kudos für Activity %s", activity_id
            )
            raise RateLimitError(f"HTTP 429 für Activity {activity_id}")
        if resp.is_redirect:
            target = urlsplit(resp.headers.get("location", "")).path
            if _LOGIN_PATH_RE.search(target):
                log.warning("Kudo POST for %s redirected to login (%s)", activity_id, target)
                self._auth_failed = True
                raise self._session_rejected_error()
            log.warning(
                "Kudo POST for %s answered HTTP %d (redirect to %s) — not counted as given",
                activity_id,
                status,
                target or "-",
            )
            return False
        self._check_auth(resp)  # 401 -> AuthError
        log.warning("Kudo POST for %s answered HTTP %d — not counted as given", activity_id, status)
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
        """Scrape an athlete's display name from their profile page.

        Raises :class:`~kudosy.feed.AuthError` when Strava bounces the request to login.
        """
        client = self._get_client()
        url = _ATHLETE_URL.format(athlete_id=athlete_id)
        try:
            resp = await client.get(url, timeout=8.0)
            self._check_auth(resp)
            if not resp.is_success:
                return None
            return parse_athlete_name(resp.text)
        except httpx.RequestError:
            return None

    def _check_auth(self, resp: httpx.Response, *, probe: bool = False) -> None:
        """Raise AuthError if Strava treats the session as logged out.

        Looks at the final URL *path* (not the whole URL) so a query like
        ``?x=sessions`` is no false positive, and logs the redirect chain so a
        failure can be diagnosed without exposing cookie values.

        ``probe`` marks the first call of a run (the dashboard load): only there is a
        400/500 read as a malformed cookie. Elsewhere a 5xx is an ordinary Strava error.
        """
        try:
            self._raise_for_auth(resp, probe=probe)
        except AuthError:
            self._auth_failed = True
            raise

    @staticmethod
    def _describe_hops(resp: httpx.Response) -> str:
        """One line per request of the chain: status, path, cookie names sent / set."""
        lines = []
        for hop in (*resp.history, resp):
            sent = ", ".join(_cookie_names(hop.request.headers.get("cookie", ""))) or "-"
            set_ = ", ".join(_set_cookie_actions(hop)) or "-"
            lines.append(f"  {hop.status_code} {hop.url.path} | sent=[{sent}] | set=[{set_}]")
        return "\n".join(lines)

    def _session_rejected_error(self) -> AuthError:
        """AuthError for a request Strava bounced to its login page."""
        has_remember = all(self._initial_cookies.get(n) for n in REMEMBER_COOKIES)
        if has_remember:
            err = AuthError(
                "Strava hat die Session trotz Remember-Cookies abgelehnt. "
                "Bitte den kompletten Cookie-Header neu eintragen."
            )
            err.code = "AUTH_REMEMBER_EXPIRED"
        else:
            err = AuthError(
                "Strava-Session ist abgelaufen und es sind keine Remember-Cookies "
                "hinterlegt. Bitte den kompletten Cookie-Header neu eintragen."
            )
            err.code = "AUTH_SESSION_EXPIRED"
        return err

    def _raise_for_auth(self, resp: httpx.Response, *, probe: bool) -> None:
        # httpx follows redirects, so resp.request is the *last* hop (after a 301 that is
        # the anonymous session Strava hands out); the stored cookies went out first.
        first = resp.history[0].request if resp.history else resp.request
        sent = first.headers.get("cookie", "")
        if _LOGIN_PATH_RE.search(resp.url.path):
            log.warning(
                "Strava redirected to login for %s\n%s\n  first request cookies: %s",
                first.url.path,
                self._describe_hops(resp),
                _masked_cookie_header(sent),
            )
            raise self._session_rejected_error()
        if probe and resp.status_code in (400, 500) and sent:
            log.warning(
                "Strava answered %d for %s\n%s\n  first request cookies: %s",
                resp.status_code,
                resp.url.path,
                self._describe_hops(resp),
                _masked_cookie_header(sent),
            )
            err = AuthError(
                f"Strava hat die Cookies abgelehnt (HTTP {resp.status_code}); "
                "vermutlich ist der Cookie unvollständig oder beschädigt."
            )
            err.code = "AUTH_MALFORMED_COOKIE"
            raise err
        if resp.status_code == 401:
            err = AuthError("Authentifizierung fehlgeschlagen (HTTP 401).")
            err.code = "AUTH_FAILED"
            raise err


def _csrf_from_html(html: str) -> str | None:
    """First plausible ``csrf`` / ``csrf-token`` meta value of a page, or ``None``."""
    for m in _CSRF_RE.finditer(html):
        if _CSRF_PLAUSIBLE_RE.match(m.group(1)):
            return m.group(1)
    return None


def _parse_next_data(html: str) -> tuple[str | None, dict[str, Any] | None]:
    """Athlete ID and embedded feed page from a Next.js dashboard's ``__NEXT_DATA__``.

    The ID is ``props.currentAthletePreload.id_str`` (fallback
    ``props.pageProps.dashboardData.currentAthlete``); the feed is
    ``props.pageProps.dashboardData.feed`` (``{"entries": [...], "pagination": {...}}``).
    Total: a missing tag, invalid JSON or any unexpected shape yields ``None`` for the
    affected part, never an exception.
    """
    m = _NEXT_DATA_RE.search(html)
    if not m:
        return None, None
    try:
        data = json.loads(m.group(1))
    except (ValueError, RecursionError):
        return None, None
    props = data.get("props") if isinstance(data, dict) else None
    if not isinstance(props, dict):
        return None, None
    page_props = props.get("pageProps")
    dashboard = page_props.get("dashboardData") if isinstance(page_props, dict) else None
    if not isinstance(dashboard, dict):
        dashboard = {}
    athlete_id = _athlete_id_from(
        {"currentAthlete": props.get("currentAthletePreload")}
    ) or _athlete_id_from(dashboard)
    feed = dashboard.get("feed")
    return athlete_id, feed if isinstance(feed, dict) else None


def _feed_payload(resp: httpx.Response) -> tuple[dict[str, Any] | None, str]:
    """Feed XHR body as ``{"entries": list, ...}``, or ``None`` plus a value-free reason."""
    detail = (
        f"HTTP {resp.status_code}, content-type {resp.headers.get('content-type', '-')!r},"
        f" path {resp.url.path}"
    )
    if not resp.is_success:
        return None, detail
    try:
        payload = resp.json()
    except ValueError:
        return None, f"{detail}, body is not JSON"
    if not isinstance(payload, dict) or not isinstance(payload.get("entries"), list):
        return None, f"{detail}, unexpected JSON shape"
    return payload, detail


def _warn_on_foreign_locale(entries: list[Any]) -> None:
    """One aggregated WARNING if entries come in a non-English locale (labels may not parse).

    Only the embedded dashboard page carries ``locale``; XHR entries have none, so for them
    this check is a no-op by design.
    """
    foreign = [
        e["locale"] for e in entries if isinstance(e, dict) and e.get("locale") not in (None, "en")
    ]
    if foreign:
        log.warning(
            "%d of %d feed entries have a locale other than 'en' (%s) — stat labels may not parse",
            len(foreign),
            len(entries),
            ", ".join(sorted({str(loc) for loc in foreign})),
        )


def _athlete_id_from(data: Any) -> str | None:
    """``currentAthlete.id_str`` (or numeric ``id``) from a ``/frontend/athletes/current`` body."""
    current = data.get("currentAthlete") if isinstance(data, dict) else None
    if not isinstance(current, dict):
        return None
    id_str = current.get("id_str")
    if isinstance(id_str, str) and id_str:
        return id_str
    numeric = current.get("id")
    if isinstance(numeric, int) and not isinstance(numeric, bool) and numeric:
        return str(numeric)
    return None


def _next_cursor_params(
    entries: list[Any], all_entries: list[Any] | None = None
) -> dict[str, int] | None:
    """Return next-page ``before``/``cursor`` params (verified 2026-10-29 via HAR).

    Each entry carries ``cursorData: {"updated_at": <unix s>, "rank": <int or float>}``.
    ``cursor`` is ``int(rank)`` of the *last* entry of *entries* (the previous page);
    ``before`` is ``int(min(updated_at))`` over *all_entries* (every entry collected so far,
    default *entries*), because ``updated_at`` is not sorted. Entries without a usable
    ``updated_at`` are skipped for the minimum.

    Returns ``None`` if the last entry has no usable rank or no entry yields a minimum, so
    the caller can abort pagination gracefully instead of making a malformed request.
    """
    if not entries:
        return None
    last = entries[-1]
    last_cd = last.get("cursorData") if isinstance(last, dict) else None
    rank = last_cd.get("rank") if isinstance(last_cd, dict) else None
    if rank is None:
        return None
    try:
        cursor = int(rank)
    except (TypeError, ValueError):
        # cursorData shape drifted (e.g. non-numeric strings) — abort
        # pagination gracefully instead of raising out of fetch_following_feed.
        log.warning("cursorData present but non-numeric (rank=%r)", rank)
        return None
    updated: list[int] = []
    for entry in entries if all_entries is None else all_entries:
        cd = entry.get("cursorData") if isinstance(entry, dict) else None
        raw = cd.get("updated_at") if isinstance(cd, dict) else None
        try:
            updated.append(int(raw))  # type: ignore[arg-type]
        except (TypeError, ValueError):
            continue
    if not updated:
        return None
    return {"before": min(updated), "cursor": cursor}


def _extract_search_results(html: str) -> list[Any]:
    """Pull ``props.pageProps.searchResults`` out of the ``__NEXT_DATA__`` blob.

    Strava's athlete search page embeds results as JSON in a
    ``<script id="__NEXT_DATA__" type="application/json">`` tag.
    Returns the raw list of athlete dicts, or [] on any failure.
    """
    m = _NEXT_DATA_RE.search(html)
    if not m:
        log.warning("No __NEXT_DATA__ in athlete search response — Strava's page may have changed")
        return []
    try:
        data = json.loads(m.group(1))
    except (json.JSONDecodeError, ValueError):
        log.warning("__NEXT_DATA__ JSON could not be parsed in athlete search response")
        return []
    props = data.get("props") if isinstance(data, dict) else None
    page_props = props.get("pageProps") if isinstance(props, dict) else None
    results = page_props.get("searchResults") if isinstance(page_props, dict) else None
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
