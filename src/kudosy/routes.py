"""FastAPI route handlers — preserve exact API surface of the Node.js wrapper.

Every path/verb/query-param/response shape matches the original so the
frontend (app.js) works unchanged.
"""

from __future__ import annotations

import json
import logging
from collections.abc import AsyncGenerator
from pathlib import Path
from typing import Any

import httpx
from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException, Request, Response
from fastapi import Path as ApiPath
from fastapi.responses import (
    HTMLResponse,
    JSONResponse,
    PlainTextResponse,
    StreamingResponse,
)
from pydantic import BaseModel

from kudosy import __version__
from kudosy.auth import (
    SESSION_COOKIE_NAME,
    auth_enabled,
    create_session_token,
    is_login_locked_out,
    record_login_failure,
    record_login_success,
    require_auth,
    verify_password,
)
from kudosy.decision import decide
from kudosy.effective_config import build_effective_config
from kudosy.feed import AuthError, RateLimitError, StructuredFeedParser
from kudosy.models import Activity, RunResult, RunStatus
from kudosy.parsers import (
    REMEMBER_COOKIES,
    SESSION_COOKIE,
    is_strava_cookie_name,
    parse_strava_cookies,
)
from kudosy.settings import get_settings
from kudosy.sport_types import categorize_sport_types
from kudosy.store import (
    cache_athlete_avatar,
    cache_athlete_label,
    mark_activity_kudoed_in_cache,
    mark_kudoed,
    persist_client_cookies,
    read_activity_cache,
    read_athlete_avatars,
    read_athlete_labels,
    read_log,
    read_run_history,
    read_settings,
    read_user_config,
    write_activity_cache,
    write_settings,
    write_user_config,
)
from kudosy.strava_client import StravaClient
from kudosy.update_check import is_newer, maybe_schedule_update_check

log = logging.getLogger(__name__)

# `router` carries the require_auth dependency on every route — a no-op when
# no KUDOSY_AUTH_PASSWORD is configured (see auth.py). `public_router` holds
# the handful of endpoints that must stay reachable *without* a session:
# the frontend shell itself, and the login/logout/status endpoints a client
# needs before it can even have a session. Both are mounted in app.py.
router = APIRouter(dependencies=[Depends(require_auth)])
public_router = APIRouter()

_STATIC_DIR = Path(__file__).parent / "static"


# ── Frontend ──────────────────────────────────────────────────────────────────


@public_router.get("/", response_class=HTMLResponse, include_in_schema=False)
async def serve_index() -> HTMLResponse:
    """Serve index.html with versioned asset URLs for cache busting."""
    import secrets

    from kudosy.app import build_csp  # avoid circular import

    v = __version__
    # All local ES modules are mapped to their cache-busted ?v= variant so that
    # a new release immediately invalidates every module in every browser.
    _MODULES = [
        "./i18n.js",
        "./state.js",
        "./dom.js",
        "./api.js",
        "./auth.js",
        "./format.js",
        "./schedule-matrix.js",
        "./athletes.js",
        "./config.js",
        "./settings.js",
        "./feed.js",
        "./status.js",
        "./stats.js",
        "./backup.js",
        "./tabs.js",
        "./main.js",
    ]
    importmap = json.dumps({"imports": {m: f"{m}?v={v}" for m in _MODULES}})
    content = (_STATIC_DIR / "index.html").read_text()
    content = content.replace('href="styles.css"', f'href="styles.css?v={v}"')
    # The importmap is inline (no src=), so it needs a per-request nonce to
    # satisfy the strict `script-src 'self'` CSP set below (see app.build_csp).
    nonce = secrets.token_urlsafe(16)
    content = content.replace(
        '<script src="main.js" type="module"></script>',
        f'<script type="importmap" nonce="{nonce}">{importmap}</script>\n  '
        f'<script src="main.js?v={v}" type="module"></script>',
    )
    return HTMLResponse(
        content=content,
        headers={
            "Cache-Control": "no-store",
            "Content-Security-Policy": build_csp(script_nonce=nonce),
        },
    )


# ── Login / session ───────────────────────────────────────────────────────────


class _LoginBody(BaseModel):
    password: str


@public_router.get("/api/auth-status")
async def get_auth_status(request: Request) -> dict[str, Any]:
    """Always reachable — tells the frontend whether to show the login overlay."""
    from kudosy.auth import verify_session_token

    required = auth_enabled()
    authenticated = (not required) or verify_session_token(request.cookies.get(SESSION_COOKIE_NAME))
    return {"authRequired": required, "authenticated": authenticated}


@public_router.post("/api/login")
async def post_login(body: _LoginBody, response: Response) -> dict[str, Any]:
    if not auth_enabled():
        # Nothing to log into — treat as already authenticated rather than
        # exposing whether a password happens to be configured.
        return {"ok": True}

    if is_login_locked_out():
        raise HTTPException(
            status_code=429,
            detail={
                "code": "TOO_MANY_ATTEMPTS",
                "message": "Zu viele Fehlversuche — bitte kurz warten.",
            },
        )

    if not verify_password(body.password):
        record_login_failure()
        raise HTTPException(
            status_code=401,
            detail={"code": "INVALID_PASSWORD", "message": "Falsches Passwort"},
        )

    record_login_success()
    settings = get_settings()
    response.set_cookie(
        key=SESSION_COOKIE_NAME,
        value=create_session_token(),
        max_age=settings.session_ttl_hours * 3600,
        httponly=True,
        samesite="lax",
        secure=settings.cookie_secure,
        path="/",
    )
    return {"ok": True}


@public_router.post("/api/logout")
async def post_logout(response: Response) -> dict[str, Any]:
    response.delete_cookie(key=SESSION_COOKIE_NAME, path="/")
    return {"ok": True}


# ── Config ────────────────────────────────────────────────────────────────────


def _unexpected_response(exc: Exception, action: str) -> HTTPException:
    """502 for a Strava answer Kudosy cannot interpret (page structure probably changed)."""
    log.warning("%s failed — unexpected Strava response: %s", action, exc)
    return HTTPException(
        status_code=502,
        detail={
            "code": "UNEXPECTED_RESPONSE",
            "message": "Unerwartete Antwort von Strava — die Seitenstruktur hat sich "
            "vermutlich geändert. Bitte das Log prüfen und Kudosy aktualisieren.",
        },
    )


def _mask_cookie_preview(cookie: str) -> str:
    """Return a short, non-sensitive preview of a session cookie for display only."""
    return cookie[:6] + "…" if len(cookie) > 6 else "***"


def _has_remember_token(cookies: dict[str, str]) -> bool:
    return all(cookies.get(n) for n in REMEMBER_COOKIES)


@router.get("/api/config")
async def get_config() -> dict[str, Any]:
    """Return the user config with all Strava cookies redacted.

    The raw cookies are never sent to the client — only whether a session is
    set (``hasCookie``), whether the remember-me pair is present
    (``hasRememberToken``, i.e. Kudosy can renew the session itself) and a
    short, non-sensitive preview of the session (``cookiePreview``). This
    prevents session-hijacking via a leaked/XSS'd response (see PUT
    /api/config for how cookies are set/kept).
    """
    cfg = read_user_config()
    if not cfg:
        return {"hasCookie": False, "hasRememberToken": False, "cookiePreview": ""}
    data = cfg.model_dump()
    cookies = data.pop("stravaCookies", {})
    session = cookies.get(SESSION_COOKIE, "")
    data["hasCookie"] = bool(cookies)
    data["hasRememberToken"] = _has_remember_token(cookies)
    data["cookiePreview"] = _mask_cookie_preview(session) if session else ""
    return data


@router.put("/api/config")
async def put_config(request: Request) -> dict[str, Any]:
    """Merge incoming config with the stored one, then validate before writing.

    ``stravaSessionCookie`` is the *input* field: a full ``Cookie`` header,
    ``name=value`` pairs or a bare session value, normalised by
    :func:`parse_strava_cookies` into ``stravaCookies``. An absent or empty
    value keeps the existing cookies (the frontend never has them to send
    back, see GET /api/config); that is rejected only when there are none
    stored. Unparseable input is a 422 (``INVALID_COOKIE``).
    """
    from kudosy.models import UserConfig

    data = await request.json()
    existing = read_user_config()

    raw_input = data.pop("stravaSessionCookie", None)
    data.pop("stravaCookies", None)  # never accept the parsed form directly
    if raw_input and str(raw_input).strip():
        try:
            data["stravaCookies"] = parse_strava_cookies(str(raw_input))
        except ValueError as exc:
            raise HTTPException(
                status_code=422,
                detail={"code": "INVALID_COOKIE", "message": str(exc)},
            ) from exc
    elif not (existing and existing.stravaCookies):
        raise HTTPException(
            status_code=400,
            detail={
                "code": "EMPTY_COOKIE",
                "message": "stravaSessionCookie darf nicht leer sein",
            },
        )

    merged = {**(existing.model_dump() if existing else {}), **data}
    try:
        new_cfg = UserConfig.model_validate(merged)
    except Exception as exc:
        raise HTTPException(
            status_code=422, detail={"code": "INVALID_CONFIG", "message": str(exc)}
        ) from exc

    write_user_config(new_cfg)
    return {"ok": True}


@router.post("/api/cookie/test")
async def test_cookie() -> dict[str, Any]:
    """Check the stored Strava cookies against Strava right now.

    Loads the dashboard (CSRF) and the current athlete; persists cookies
    Strava rotated on the way and updates the auth state shown in the UI.
    """
    from kudosy.app import get_app_state  # avoid circular import

    cfg = read_user_config()
    if not cfg or not cfg.stravaCookies:
        raise HTTPException(
            status_code=400,
            detail={"code": "NO_COOKIE", "message": "Kein Session-Cookie konfiguriert"},
        )

    state = get_app_state()
    client = StravaClient(cfg.stravaCookies)
    try:
        await client.get_csrf_token()
        athlete_id = await client.fetch_current_athlete_id()
        state["auth_ok"] = True
        return {
            "ok": True,
            "athleteId": athlete_id,
            "hasRememberToken": _has_remember_token(client.current_cookies()),
        }
    except AuthError as exc:
        state["auth_ok"] = False
        return {
            "ok": False,
            "code": getattr(exc, "code", "AUTH_FAILED"),
            "hasRememberToken": _has_remember_token(cfg.stravaCookies),
        }
    except RateLimitError:
        return {
            "ok": False,
            "code": "RATE_LIMITED",
            "hasRememberToken": _has_remember_token(cfg.stravaCookies),
        }
    except RuntimeError:
        # No usable page 1 or CSRF token anywhere: Strava served something unexpected.
        return {
            "ok": False,
            "code": "UNEXPECTED_RESPONSE",
            "hasRememberToken": _has_remember_token(cfg.stravaCookies),
        }
    except httpx.RequestError as exc:
        log.warning("Cookie test failed (network error): %s", exc)
        raise HTTPException(
            status_code=502,
            detail={
                "code": "STRAVA_UNREACHABLE",
                "message": "Strava war nicht erreichbar. Bitte später erneut versuchen.",
            },
        ) from exc
    finally:
        persist_client_cookies(cfg.stravaCookies, client)
        await client.aclose()


# ── Settings ──────────────────────────────────────────────────────────────────


@router.get("/api/settings")
async def get_settings_route() -> dict[str, Any]:
    return read_settings().model_dump()


@router.put("/api/settings")
async def put_settings(request: Request) -> dict[str, Any]:
    from kudosy.app import get_app_state  # avoid circular import

    data = await request.json()
    state = get_app_state()
    current = read_settings().model_dump()
    merged = {**current, **data}
    from kudosy.models import AppSettings

    new_settings = AppSettings.model_validate(merged)
    write_settings(new_settings)

    # Reschedule with new settings
    scheduler = state.get("scheduler")
    if scheduler:
        job_fn = state.get("job_fn")
        if job_fn:
            scheduler.reschedule(new_settings, job_fn)
        digest_fn = state.get("digest_fn")
        if digest_fn:
            scheduler.reschedule_digest(new_settings, digest_fn)

    return {"ok": True}


# ── Sport types ───────────────────────────────────────────────────────────────


@router.get("/api/sport-types")
async def get_sport_types(request: Request) -> list[str]:
    state = request.app.state
    return state.active_sport_types  # type: ignore[no-any-return]


@router.get("/api/sport-categories")
async def get_sport_categories(request: Request) -> dict[str, list[str]]:
    """Return active sport types grouped into the five official Strava categories.

    Unknown (live-fetched) sport types that are not in the static category map
    fall into ``OtherSports``.  All five category keys are always present.
    """
    active: list[str] = request.app.state.active_sport_types
    return categorize_sport_types(active)


# ── Athlete lookup ────────────────────────────────────────────────────────────


@router.get("/api/athletes/search")
async def search_athletes_route(q: str = "") -> list[dict[str, Any]]:
    """Search for athletes by name using the Strava search endpoint.

    Returns a list of ``{"id": str, "name": str, "avatarUrl": str}`` objects.
    The Strava search API is undocumented — results depend on the current
    Strava session and may vary.  On any error, returns an empty list.

    NOTE: This endpoint must be declared before /api/athletes/{athlete_id}
    so FastAPI does not treat 'search' as a path parameter.
    """
    if not q or not q.strip():
        return []

    cfg = read_user_config()
    if not cfg or not cfg.stravaCookies:
        raise HTTPException(
            status_code=400,
            detail={"code": "NO_COOKIE", "message": "Kein Session-Cookie konfiguriert"},
        )

    client = StravaClient(cfg.stravaCookies)
    try:
        results = await client.search_athletes(q.strip())
        # Cache names and avatars so they survive across page reloads
        labels = read_athlete_labels()
        avatars = read_athlete_avatars()
        for item in results:
            aid = item.get("id", "")
            if aid and item.get("name") and aid not in labels:
                cache_athlete_label(aid, item["name"])
            if aid and item.get("avatarUrl") and aid not in avatars:
                cache_athlete_avatar(aid, item["avatarUrl"])
        return results
    except AuthError as exc:
        code = getattr(exc, "code", "AUTH_FAILED")
        raise HTTPException(status_code=401, detail={"code": code, "message": str(exc)}) from exc
    finally:
        persist_client_cookies(cfg.stravaCookies, client)
        await client.aclose()


@router.get("/api/athletes/{athlete_id}")
async def get_athlete(
    athlete_id: str = ApiPath(pattern=r"^\d+$"),
) -> dict[str, Any]:
    cfg = read_user_config()
    if not cfg or not cfg.stravaCookies:
        raise HTTPException(
            status_code=400,
            detail={"code": "NO_COOKIE", "message": "Kein Session-Cookie konfiguriert"},
        )

    # Check persistent cache first
    labels = read_athlete_labels()
    if athlete_id in labels:
        return {"id": athlete_id, "name": labels[athlete_id]}

    client = StravaClient(cfg.stravaCookies)
    try:
        name = await client.lookup_athlete(athlete_id)
    except AuthError as exc:
        code = getattr(exc, "code", "AUTH_FAILED")
        raise HTTPException(status_code=401, detail={"code": code, "message": str(exc)}) from exc
    finally:
        persist_client_cookies(cfg.stravaCookies, client)
        await client.aclose()

    if name:
        cache_athlete_label(athlete_id, name)
    return {"id": athlete_id, "name": name}


@router.get("/api/athlete-labels")
async def get_athlete_labels() -> dict[str, str]:
    return read_athlete_labels()


@router.get("/api/athlete-avatars")
async def get_athlete_avatars() -> dict[str, str]:
    return read_athlete_avatars()


# ── Run ───────────────────────────────────────────────────────────────────────


@router.post("/api/run")
async def post_run(
    request: Request,
    background_tasks: BackgroundTasks,
) -> dict[str, Any]:
    from kudosy.app import get_app_state

    state = get_app_state()
    scheduler = state.get("scheduler")

    if scheduler and scheduler.is_running:
        raise HTTPException(
            status_code=409,
            detail={"code": "JOB_RUNNING", "message": "Job läuft bereits — bitte warten"},
        )

    # dryRun from ?dryRun=1 or body
    dry_run = request.query_params.get("dryRun") == "1"
    try:
        body = await request.json()
        if isinstance(body, dict) and body.get("dryRun") is True:
            dry_run = True
    except Exception:
        pass

    run_job_fn = state.get("run_job_fn")
    if run_job_fn is None:
        raise HTTPException(
            status_code=503,
            detail={"code": "ENGINE_NOT_READY", "message": "Engine nicht bereit"},
        )

    async def _run() -> None:
        from kudosy.app import get_app_state

        st = get_app_state()
        sched = st.get("scheduler")
        run_job = st.get("run_job_fn")
        if run_job is None:
            return

        async def _job() -> None:
            st["last_run"] = await run_job(dry_run)

        try:
            if sched is not None:
                # Route the manual run through the scheduler so is_running is set
                # for the full duration — this keeps /api/status accurate and lets
                # the frontend spinner persist until the run actually finishes.
                await sched.trigger_now(_job)
            else:
                await _job()
        except RuntimeError:
            # Race between the 409 pre-check and trigger_now's own guard —
            # ignore silently; the caller already received {"started": true}.
            log.warning("Manual run skipped — job already running")

    background_tasks.add_task(_run)
    return {"started": True, "dryRun": dry_run}


# ── Status ────────────────────────────────────────────────────────────────────


@router.get("/api/status")
async def get_status(request: Request) -> dict[str, Any]:
    from kudosy.app import get_app_state

    state = get_app_state()
    scheduler = state.get("scheduler")
    settings = read_settings()
    last_run: RunResult | None = state.get("last_run")

    auth_ok: bool | None = state.get("auth_ok")

    # Lazily refresh the latest-release info in the background (max once per 12 h)
    maybe_schedule_update_check(state, settings.updateCheckEnabled)
    latest_version: str | None = state.get("latest_version")

    return RunStatus(
        running=scheduler.is_running if scheduler else False,
        lastRun=last_run,
        nextRunAt=scheduler.next_run_at if scheduler else None,
        schedulerEnabled=settings.schedulerEnabled,
        intervalMinutes=settings.intervalMinutes,
        version=__version__,
        authOk=auth_ok,
        latestVersion=latest_version,
        updateAvailable=bool(latest_version) and is_newer(__version__, latest_version or ""),
    ).model_dump(mode="json")


# ── Feed ──────────────────────────────────────────────────────────────────────


def _decorate_feed(raw_acts: list[dict[str, Any]], effective: Any) -> list[dict[str, Any]]:
    """Re-compute engine decisions over raw Activity dicts and return decorated entries.

    Decisions are never persisted — they are always recomputed from the current
    config so that config changes are reflected immediately without a live Strava
    fetch.  Entries that fail Activity validation are silently skipped.
    """
    out: list[dict[str, Any]] = []
    for raw in raw_acts:
        try:
            act = Activity.model_validate(raw)
        except Exception:
            log.debug("_decorate_feed: skipping invalid activity entry: %s", raw)
            continue
        decision = decide(act, effective)
        entry = act.model_dump()
        entry["give_kudos"] = decision.give_kudos
        entry["reason"] = str(decision.reason)
        out.append(entry)
    return out


@router.get("/api/feed")
async def get_feed(request: Request) -> dict[str, Any]:
    """Return the Strava following feed annotated with engine decisions.

    By default serves from the persistent activity cache (populated by the
    background scheduler and by explicit refreshes).  Pass ``?refresh=true``
    to force a live Strava fetch and update the cache.
    """
    cfg = read_user_config()
    if not cfg or not cfg.stravaCookies:
        raise HTTPException(
            status_code=400,
            detail={"code": "NO_COOKIE", "message": "Kein Session-Cookie konfiguriert"},
        )

    effective = build_effective_config(cfg)
    refresh = request.query_params.get("refresh") == "true"

    # Cache-first: serve the persisted snapshot when not explicitly refreshing.
    if not refresh:
        cached_acts, fetched_at = read_activity_cache()
        if fetched_at is not None:
            log.debug("Serving feed from activity cache (%d entries)", len(cached_acts))
            return {"fetched_at": fetched_at, "activities": _decorate_feed(cached_acts, effective)}

    # Live fetch (explicit refresh or empty cache / first boot).
    import contextlib
    import datetime as _dt
    from pathlib import Path

    client = StravaClient(cfg.stravaCookies)
    try:
        # Same path as the engine: the dashboard request yields CSRF token, athlete ID and
        # the embedded first feed page, so the feed works even if the XHR is gone.
        await client.get_csrf_token()
        athlete_id = cfg.athleteId or await client.fetch_current_athlete_id() or ""
        if not athlete_id:
            raise RuntimeError("Strava athlete ID could not be determined")
        # Optional raw feed dump for debugging (written to DATA_DIR/last-feed-raw.json).
        # Gated on KUDOSY_LOG_LEVEL=DEBUG: this writes third-party athletes'
        # full feed data (names, locations, device info) to disk on every
        # live refresh — only worth that PII-on-disk tradeoff when actively
        # debugging a Strava format change, not on every default-config refresh.
        dump_path: Path | None = None
        if get_settings().log_level.upper() == "DEBUG":
            with contextlib.suppress(Exception):
                dump_path = Path(get_settings().data_dir) / "last-feed-raw.json"
        raw_feed = await client.fetch_following_feed(athlete_id, dump_raw=dump_path)
        activities = StructuredFeedParser().parse(raw_feed)
        # Cache avatar URLs from the live feed.
        avatars = read_athlete_avatars()
        for act in activities:
            if act.athlete_id and act.athlete_avatar_url and act.athlete_id not in avatars:
                cache_athlete_avatar(act.athlete_id, act.athlete_avatar_url)
        raw_acts = [a.model_dump(mode="json") for a in activities]
        now_ts = _dt.datetime.now(_dt.UTC).isoformat()
        if raw_acts:
            write_activity_cache(raw_acts, now_ts)
        else:
            # An empty result is more likely a parse problem than an empty feed:
            # keep the last good snapshot instead of overwriting it.
            log.warning("Live feed returned no activities — activity cache left unchanged")
        return {"fetched_at": now_ts, "activities": _decorate_feed(raw_acts, effective)}
    except AuthError as exc:
        code = getattr(exc, "code", "AUTH_FAILED")
        raise HTTPException(status_code=401, detail={"code": code, "message": str(exc)}) from exc
    except (RuntimeError, ValueError) as exc:
        raise _unexpected_response(exc, "Live feed fetch") from exc
    except httpx.RequestError as exc:
        # A network-level failure reaching Strava (already retried inside
        # StravaClient) — report it cleanly instead of an unhandled 500.
        log.warning("Live feed fetch failed (network error): %s", exc)
        raise HTTPException(
            status_code=502,
            detail={
                "code": "STRAVA_UNREACHABLE",
                "message": "Strava war nicht erreichbar. Bitte später erneut versuchen.",
            },
        ) from exc
    finally:
        persist_client_cookies(cfg.stravaCookies, client)
        await client.aclose()


# ── Single-kudo ───────────────────────────────────────────────────────────────


@router.post("/api/kudos/{activity_id}")
async def post_single_kudos(
    activity_id: str = ApiPath(pattern=r"^\d+$"),
) -> dict[str, Any]:
    """Give kudos to a single activity from the feed UI.

    Fetches a fresh CSRF token, sends the kudo, and caches the activity_id so
    the scheduler does not re-kudo it during the next run.
    """
    import datetime as _dt

    cfg = read_user_config()
    if not cfg or not cfg.stravaCookies:
        raise HTTPException(
            status_code=400,
            detail={"code": "NO_COOKIE", "message": "Kein Session-Cookie konfiguriert"},
        )

    client = StravaClient(cfg.stravaCookies)
    try:
        csrf_token = await client.get_csrf_token()
        ok = await client.send_kudos(activity_id, csrf_token)
        if ok:
            mark_kudoed(activity_id, _dt.datetime.now(_dt.UTC).isoformat())
            mark_activity_kudoed_in_cache(activity_id)
        return {"ok": ok}
    except AuthError as exc:
        code = getattr(exc, "code", "AUTH_FAILED")
        raise HTTPException(status_code=401, detail={"code": code, "message": str(exc)}) from exc
    except RateLimitError as exc:
        raise HTTPException(
            status_code=429,
            detail={"code": "RATE_LIMITED", "message": "Strava meldet zu viele Anfragen."},
        ) from exc
    except (RuntimeError, ValueError) as exc:
        raise _unexpected_response(exc, "Single kudo") from exc
    except httpx.RequestError as exc:
        log.warning("Single kudo failed (network error): %s", exc)
        raise HTTPException(
            status_code=502,
            detail={
                "code": "STRAVA_UNREACHABLE",
                "message": "Strava war nicht erreichbar. Bitte später erneut versuchen.",
            },
        ) from exc
    finally:
        persist_client_cookies(cfg.stravaCookies, client)
        await client.aclose()


# ── History ───────────────────────────────────────────────────────────────────


@router.get("/api/history")
async def get_history(limit: int = 100) -> list[dict[str, Any]]:
    """Return the *limit* most-recent run-history entries (newest first).

    Each entry is a compact dict with: started_at, finished_at, dry_run,
    total, would_give, given, success.
    """
    return read_run_history(limit=max(1, min(limit, 500)))


# ── Backup / Restore ─────────────────────────────────────────────────────────


@router.get("/api/export")
async def export_config() -> JSONResponse:
    """Export config + settings as a downloadable JSON backup.

    ``stravaCookies`` is intentionally omitted from the export for
    security — it contains a live browser session and remember-me token.
    """
    import datetime as _dt

    cfg = read_user_config()
    settings = read_settings()

    cfg_dict = cfg.model_dump(mode="json") if cfg else {}
    cfg_dict.pop("stravaCookies", None)  # never export the live session cookies

    payload = {
        "version": 1,
        "exported_at": _dt.datetime.now(_dt.UTC).isoformat(),
        "config": cfg_dict,
        "settings": settings.model_dump(mode="json"),
        "athleteLabels": read_athlete_labels(),
        "athleteAvatars": read_athlete_avatars(),
    }
    filename = "kudosy-backup.json"
    return JSONResponse(
        content=payload,
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )


class _ImportBody(BaseModel):
    config: dict[str, Any]
    settings: dict[str, Any]


@router.post("/api/import")
async def import_config(body: _ImportBody) -> dict[str, Any]:
    """Restore config + settings from a backup payload.

    The Strava cookies are only updated when explicitly present and non-empty
    in the import payload (``stravaCookies``, or the legacy
    ``stravaSessionCookie``) — otherwise the existing ones are kept.
    """
    from kudosy.models import AppSettings, UserConfig

    config = dict(body.config)
    legacy = config.pop("stravaSessionCookie", None)
    if isinstance(config.get("stravaCookies"), dict):
        # Same whitelist as pasted input: no tracking cookies or non-string junk.
        config["stravaCookies"] = {
            k: v
            for k, v in config["stravaCookies"].items()
            if isinstance(v, str) and v and is_strava_cookie_name(k)
        }
    elif "stravaCookies" in config:
        del config["stravaCookies"]
    if legacy and str(legacy).strip() and not config.get("stravaCookies"):
        try:
            config["stravaCookies"] = parse_strava_cookies(str(legacy))
        except ValueError as exc:
            raise HTTPException(
                status_code=422, detail={"code": "INVALID_COOKIE", "message": str(exc)}
            ) from exc

    # Validate imported config (may raise 422 automatically via Pydantic)
    try:
        new_cfg = UserConfig.model_validate(config)
    except Exception as exc:
        raise HTTPException(
            status_code=422, detail={"code": "INVALID_CONFIG", "message": str(exc)}
        ) from exc

    try:
        new_settings = AppSettings.model_validate(body.settings)
    except Exception as exc:
        raise HTTPException(
            status_code=422, detail={"code": "INVALID_SETTINGS", "message": str(exc)}
        ) from exc

    # Preserve the existing session cookie unless the import explicitly supplies one
    if not new_cfg.stravaCookies:
        existing = read_user_config()
        if existing and existing.stravaCookies:
            new_cfg = new_cfg.model_copy(update={"stravaCookies": existing.stravaCookies})

    write_user_config(new_cfg)
    write_settings(new_settings)
    return {"ok": True}


# ── Log ───────────────────────────────────────────────────────────────────────


@router.get("/api/log")
async def get_log() -> Response:
    return PlainTextResponse(read_log())


def _sse_event(event: str, data: str) -> str:
    """Format one SSE event; multi-line data needs one ``data:`` line per line."""
    lines = "".join(f"data: {line}\n" for line in data.split("\n")) or "data: \n"
    return f"event: {event}\n{lines}\n"


_SSE_HEARTBEAT_S = 15.0


@router.get("/api/log/stream")
async def stream_log() -> StreamingResponse:
    """Live log via Server-Sent Events.

    Events: ``snapshot`` (current file content, sent once on connect),
    ``line`` (one new log line), ``reset`` (new run started — clear the view).
    A comment heartbeat is sent every 15 s so proxies keep the socket open.
    """
    import asyncio

    from kudosy.logging_conf import RESET, get_broadcast_handler

    handler = get_broadcast_handler()
    queue = handler.subscribe()

    async def gen() -> AsyncGenerator[str]:
        try:
            yield _sse_event("snapshot", read_log())
            while True:
                try:
                    item = await asyncio.wait_for(queue.get(), timeout=_SSE_HEARTBEAT_S)
                except TimeoutError:
                    yield ": heartbeat\n\n"
                    continue
                if item is RESET:
                    yield _sse_event("reset", "")
                else:
                    yield _sse_event("line", str(item))
        finally:
            handler.unsubscribe(queue)

    return StreamingResponse(
        gen(),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-store", "X-Accel-Buffering": "no"},
    )
