"""FastAPI application factory with lifespan management."""

from __future__ import annotations

import logging
from contextlib import asynccontextmanager
from pathlib import Path
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from collections.abc import AsyncGenerator

import httpx
from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles

from kudosy import __version__
from kudosy.engine import run_kudos
from kudosy.feed import StravaHtmlFeedParser
from kudosy.logging_conf import configure_logging, reset_log_handler
from kudosy.routes import router
from kudosy.scheduler import KudosyScheduler
from kudosy.settings import get_settings
from kudosy.sport_types import ALL_SPORT_TYPES, fetch_sport_types, merge_sport_types
from kudosy.store import (
    bootstrap,
    log_path,
    mark_kudoed,
    prune_kudoed,
    read_kudoed_ids,
    read_settings,
    read_user_config,
    write_activity_cache,
)

log = logging.getLogger(__name__)

# Shared mutable application state (set during lifespan, read from routes)
_app_state: dict[str, Any] = {}


def get_app_state() -> dict[str, Any]:
    return _app_state


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncGenerator[None]:
    """Startup: bootstrap, load sport types, start scheduler."""
    env = get_settings()

    # Ensure the data directory exists before configure_logging tries to open
    # the log file — on a fresh Docker volume /data does not exist yet.
    log_path().parent.mkdir(parents=True, exist_ok=True)

    configure_logging(env.log_level, log_path())

    log.info("Kudosy %s starting up", __version__)

    # Bootstrap /data directory and seed all missing files
    bootstrap()

    # Load sport types (try live fetch, fall back to hardcoded)
    async with httpx.AsyncClient() as client:
        live = await fetch_sport_types(client)
    if live:
        active = merge_sport_types(live, ALL_SPORT_TYPES)
        log.info(
            "Loaded %d sport types from Strava (+%d legacy)", len(live), len(active) - len(live)
        )
    else:
        active = ALL_SPORT_TYPES
        log.info("Using %d hardcoded sport types", len(active))

    app.state.active_sport_types = active

    # Scheduler
    scheduler = KudosyScheduler()
    scheduler.start()
    _app_state["scheduler"] = scheduler

    feed_parser = StravaHtmlFeedParser()

    async def _run_job(dry_run: bool | None = None) -> Any:
        settings = read_settings()
        if dry_run is None:
            dry_run = settings.dryRun
        user_cfg = read_user_config()
        if not user_cfg or not user_cfg.stravaSessionCookie:
            log.error("Kein Session-Cookie konfiguriert — Job abgebrochen")
            return None
        from kudosy.strava_client import StravaClient

        reset_log_handler(log_path())
        kudoed_ids = read_kudoed_ids()
        client = StravaClient(user_cfg.stravaSessionCookie)
        try:
            result = await run_kudos(
                user_cfg,
                settings,
                client=client,
                feed_parser=feed_parser,
                dry_run=dry_run,
                kudoed_ids=kudoed_ids,
            )
            # Persist newly kudoed activity IDs (dry-run never sends, so list is empty)
            if result and result.newly_kudoed:
                now_iso = result.finished_at.isoformat()
                for activity_id in result.newly_kudoed:
                    mark_kudoed(activity_id, now_iso)
                prune_kudoed()
                if result.skipped_cached:
                    log.info(
                        "Cache: %d activities skipped (already kudoed), %d newly cached",
                        result.skipped_cached,
                        len(result.newly_kudoed),
                    )
            # Persist activity feed snapshot (survives restarts; never overwrite with
            # a failed or empty run to protect the last valid cache).
            if result and result.success and result.activities:
                acts = result.activities
                if not dry_run and result.newly_kudoed:
                    # Reconcile: the snapshot was captured before kudos were sent,
                    # so flip has_kudoed=True for any ID we just successfully kudoed.
                    given_ids = set(result.newly_kudoed)
                    for act in acts:
                        if act.get("activity_id") in given_ids:
                            act["has_kudoed"] = True
                write_activity_cache(acts, result.started_at.isoformat())
                log.debug("Activity cache updated (%d entries)", len(acts))
            return result
        finally:
            await client.aclose()

    async def _scheduled_job() -> None:
        settings = read_settings()
        result = await _run_job(settings.dryRun)
        if result:
            _app_state["last_run"] = result

    _app_state["job_fn"] = _scheduled_job
    _app_state["run_job_fn"] = _run_job
    _app_state["last_run"] = None

    settings = read_settings()
    scheduler.reschedule(settings, _scheduled_job)

    log.info("Kudosy ready on port %d", env.port)

    yield

    # Shutdown
    log.info("Kudosy shutting down")
    scheduler.shutdown()


def create_app() -> FastAPI:
    """Create and configure the FastAPI application."""
    app = FastAPI(
        title="Kudosy",
        version=__version__,
        lifespan=lifespan,
    )
    app.include_router(router)

    # Serve frontend static files
    static_dir = Path(__file__).parent / "static"
    if static_dir.exists():
        app.mount("/", StaticFiles(directory=static_dir, html=True), name="static")

    return app
