"""FastAPI route handlers — preserve exact API surface of the Node.js wrapper.

Every path/verb/query-param/response shape matches the original so the
frontend (app.js) works unchanged.
"""

from __future__ import annotations

import logging
from typing import Any

from fastapi import APIRouter, BackgroundTasks, HTTPException, Request, Response
from fastapi.responses import PlainTextResponse

from kudosy import __version__
from kudosy.decision import decide
from kudosy.effective_config import build_effective_config
from kudosy.feed import AuthError, StravaHtmlFeedParser
from kudosy.models import RunResult, RunStatus
from kudosy.store import (
    cache_athlete_label,
    read_athlete_labels,
    read_defaults,
    read_log,
    read_settings,
    read_user_config,
    write_defaults_raw,
    write_settings,
    write_user_config_raw,
)
from kudosy.strava_client import StravaClient

log = logging.getLogger(__name__)

router = APIRouter()


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


# ── Defaults ──────────────────────────────────────────────────────────────────


@router.get("/api/defaults")
async def get_defaults() -> dict[str, Any]:
    return read_defaults().model_dump()


@router.put("/api/defaults")
async def put_defaults(request: Request) -> dict[str, Any]:
    data = await request.json()
    write_defaults_raw(data)
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

    return {"ok": True}


# ── Sport types ───────────────────────────────────────────────────────────────


@router.get("/api/sport-types")
async def get_sport_types(request: Request) -> list[str]:
    state = request.app.state
    return state.active_sport_types  # type: ignore[no-any-return]


# ── Athlete lookup ────────────────────────────────────────────────────────────


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

    job_fn = state.get("job_fn")
    if job_fn is None:
        raise HTTPException(
            status_code=503,
            detail={"code": "ENGINE_NOT_READY", "message": "Engine nicht bereit"},
        )

    async def _run() -> None:
        from kudosy.app import get_app_state

        st = get_app_state()
        # Store current dry_run override for this fire-and-forget call
        run_job = st.get("run_job_fn")
        if run_job:
            result = await run_job(dry_run)
            st["last_run"] = result

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

    return RunStatus(
        running=scheduler.is_running if scheduler else False,
        lastRun=last_run,
        nextRunAt=scheduler.next_run_at if scheduler else None,
        schedulerEnabled=settings.schedulerEnabled,
        intervalMinutes=settings.intervalMinutes,
        version=__version__,
    ).model_dump(mode="json")


# ── Feed ──────────────────────────────────────────────────────────────────────


@router.get("/api/feed")
async def get_feed() -> list[dict[str, Any]]:
    """Fetch the Strava following feed and annotate each activity with the engine decision."""
    cfg = read_user_config()
    if not cfg or not cfg.stravaSessionCookie:
        raise HTTPException(
            status_code=400,
            detail={"code": "NO_COOKIE", "message": "Kein Session-Cookie konfiguriert"},
        )

    defaults = read_defaults()
    effective = build_effective_config(cfg, defaults)
    client = StravaClient(cfg.stravaSessionCookie)
    try:
        raw_feed = await client.fetch_following_feed()
        activities = StravaHtmlFeedParser().parse(raw_feed)
        result: list[dict[str, Any]] = []
        for act in activities:
            decision = decide(act, effective)
            entry = act.model_dump()
            entry["give_kudos"] = decision.give_kudos
            entry["reason"] = str(decision.reason)
            result.append(entry)
        return result
    except AuthError as exc:
        code = getattr(exc, "code", "AUTH_FAILED")
        raise HTTPException(status_code=401, detail={"code": code, "message": str(exc)}) from exc
    finally:
        await client.aclose()


# ── Log ───────────────────────────────────────────────────────────────────────


@router.get("/api/log")
async def get_log() -> Response:
    return PlainTextResponse(read_log())
