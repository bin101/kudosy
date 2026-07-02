"""FastAPI route handlers — preserve exact API surface of the Node.js wrapper.

Every path/verb/query-param/response shape matches the original so the
frontend (app.js) works unchanged.
"""

from __future__ import annotations

import json
import logging
from pathlib import Path
from typing import Any

from fastapi import APIRouter, BackgroundTasks, HTTPException, Request, Response
from fastapi.responses import HTMLResponse, PlainTextResponse

from kudosy import __version__
from kudosy.decision import decide
from kudosy.effective_config import build_effective_config
from kudosy.feed import AuthError, StructuredFeedParser
from kudosy.models import Activity, RunResult, RunStatus
from kudosy.sport_types import categorize_sport_types
from kudosy.store import (
    cache_athlete_avatar,
    cache_athlete_label,
    mark_activity_kudoed_in_cache,
    mark_kudoed,
    read_activity_cache,
    read_athlete_avatars,
    read_athlete_labels,
    read_log,
    read_run_history,
    read_settings,
    read_user_config,
    write_activity_cache,
    write_settings,
    write_user_config_raw,
)
from kudosy.strava_client import StravaClient

log = logging.getLogger(__name__)

router = APIRouter()

_STATIC_DIR = Path(__file__).parent / "static"


# ── Frontend ──────────────────────────────────────────────────────────────────


@router.get("/", response_class=HTMLResponse, include_in_schema=False)
async def serve_index() -> HTMLResponse:
    """Serve index.html with versioned asset URLs for cache busting."""
    v = __version__
    # All local ES modules are mapped to their cache-busted ?v= variant so that
    # a new release immediately invalidates every module in every browser.
    _MODULES = [
        "./i18n.js",
        "./state.js",
        "./dom.js",
        "./api.js",
        "./format.js",
        "./schedule-matrix.js",
        "./athletes.js",
        "./config.js",
        "./settings.js",
        "./feed.js",
        "./status.js",
        "./stats.js",
        "./tabs.js",
        "./main.js",
    ]
    importmap = json.dumps({"imports": {m: f"{m}?v={v}" for m in _MODULES}})
    content = (_STATIC_DIR / "index.html").read_text()
    content = content.replace('href="styles.css"', f'href="styles.css?v={v}"')
    content = content.replace(
        '<script src="main.js" type="module"></script>',
        f'<script type="importmap">{importmap}</script>\n  '
        f'<script src="main.js?v={v}" type="module"></script>',
    )
    return HTMLResponse(content=content, headers={"Cache-Control": "no-store"})


# ── Config ────────────────────────────────────────────────────────────────────


@router.get("/api/config")
async def get_config() -> dict[str, Any]:
    cfg = read_user_config()
    return cfg.model_dump() if cfg else {}


@router.put("/api/config")
async def put_config(request: Request) -> dict[str, Any]:
    data = await request.json()
    cookie = data.get("stravaSessionCookie")
    if cookie is not None and not cookie:
        raise HTTPException(
            status_code=400,
            detail={"code": "EMPTY_COOKIE", "message": "stravaSessionCookie darf nicht leer sein"},
        )
    write_user_config_raw(data)
    return {"ok": True}


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
    if not cfg or not cfg.stravaSessionCookie:
        raise HTTPException(
            status_code=400,
            detail={"code": "NO_COOKIE", "message": "Kein Session-Cookie konfiguriert"},
        )

    client = StravaClient(cfg.stravaSessionCookie)
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
        await client.aclose()


@router.get("/api/athletes/{athlete_id}")
async def get_athlete(athlete_id: str) -> dict[str, Any]:
    cfg = read_user_config()
    if not cfg or not cfg.stravaSessionCookie:
        raise HTTPException(
            status_code=400,
            detail={"code": "NO_COOKIE", "message": "Kein Session-Cookie konfiguriert"},
        )

    # Check persistent cache first
    labels = read_athlete_labels()
    if athlete_id in labels:
        return {"id": athlete_id, "name": labels[athlete_id]}

    client = StravaClient(cfg.stravaSessionCookie)
    try:
        name = await client.lookup_athlete(athlete_id)
    except AuthError as exc:
        code = getattr(exc, "code", "AUTH_FAILED")
        raise HTTPException(status_code=401, detail={"code": code, "message": str(exc)}) from exc
    finally:
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
    return RunStatus(
        running=scheduler.is_running if scheduler else False,
        lastRun=last_run,
        nextRunAt=scheduler.next_run_at if scheduler else None,
        schedulerEnabled=settings.schedulerEnabled,
        intervalMinutes=settings.intervalMinutes,
        version=__version__,
        authOk=auth_ok,
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
    if not cfg or not cfg.stravaSessionCookie:
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

    from kudosy.settings import get_settings

    client = StravaClient(cfg.stravaSessionCookie)
    try:
        # Resolve athlete ID (from config or live lookup).
        athlete_id = cfg.athleteId or await client.fetch_current_athlete_id() or ""
        # Optional raw feed dump for debugging (written to DATA_DIR/last-feed-raw.json).
        dump_path: Path | None = None
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
        write_activity_cache(raw_acts, now_ts)
        return {"fetched_at": now_ts, "activities": _decorate_feed(raw_acts, effective)}
    except AuthError as exc:
        code = getattr(exc, "code", "AUTH_FAILED")
        raise HTTPException(status_code=401, detail={"code": code, "message": str(exc)}) from exc
    finally:
        await client.aclose()


# ── Single-kudo ───────────────────────────────────────────────────────────────


@router.post("/api/kudos/{activity_id}")
async def post_single_kudos(activity_id: str) -> dict[str, Any]:
    """Give kudos to a single activity from the feed UI.

    Fetches a fresh CSRF token, sends the kudo, and caches the activity_id so
    the scheduler does not re-kudo it during the next run.
    """
    import datetime as _dt

    cfg = read_user_config()
    if not cfg or not cfg.stravaSessionCookie:
        raise HTTPException(
            status_code=400,
            detail={"code": "NO_COOKIE", "message": "Kein Session-Cookie konfiguriert"},
        )

    client = StravaClient(cfg.stravaSessionCookie)
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
    finally:
        await client.aclose()


# ── History ───────────────────────────────────────────────────────────────────


@router.get("/api/history")
async def get_history(limit: int = 100) -> list[dict[str, Any]]:
    """Return the *limit* most-recent run-history entries (newest first).

    Each entry is a compact dict with: started_at, finished_at, dry_run,
    total, would_give, given, success.
    """
    return read_run_history(limit=max(1, min(limit, 500)))


# ── Log ───────────────────────────────────────────────────────────────────────


@router.get("/api/log")
async def get_log() -> Response:
    return PlainTextResponse(read_log())
