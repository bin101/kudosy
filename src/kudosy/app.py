"""FastAPI application factory with lifespan management."""

from __future__ import annotations

import logging
from collections.abc import Awaitable, Callable
from contextlib import asynccontextmanager
from pathlib import Path
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from collections.abc import AsyncGenerator

import httpx
from fastapi import FastAPI, Request, Response
from fastapi.staticfiles import StaticFiles

from kudosy import __version__
from kudosy.engine import run_kudos
from kudosy.feed import AuthError, StructuredFeedParser
from kudosy.logging_conf import configure_logging, reset_log_handler
from kudosy.notify import (
    build_auth_error_payload,
    build_digest_payload,
    build_run_payload,
    send_notification,
)
from kudosy.routes import router
from kudosy.scheduler import KudosyScheduler
from kudosy.settings import get_settings
from kudosy.sport_types import ALL_SPORT_TYPES, fetch_sport_types, merge_sport_types
from kudosy.store import (
    append_run_history,
    bootstrap,
    log_path,
    mark_kudoed,
    prune_kudoed,
    read_kudoed_ids,
    read_last_digest_at,
    read_run_history,
    read_settings,
    read_user_config,
    write_activity_cache,
    write_last_digest_at,
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

    feed_parser = StructuredFeedParser()

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
            _app_state["auth_ok"] = True
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
            # Persist a compact history entry for every completed run
            if result:
                append_run_history(
                    {
                        "started_at": result.started_at.isoformat(),
                        "finished_at": result.finished_at.isoformat(),
                        "dry_run": result.dry_run,
                        "total": result.total,
                        "would_give": result.would_give,
                        "given": result.given,
                        "success": result.success,
                    }
                )
                # Send run-complete webhook notification if configured
                if settings.notifyOnRun and settings.notifyWebhookUrl:
                    await send_notification(
                        settings.notifyWebhookUrl,
                        build_run_payload(result),
                        system=settings.notifySystem,
                    )
            return result
        except AuthError as exc:
            _app_state["auth_ok"] = False
            log.error("Strava auth failed (cookie expired?): %s", exc)
            if settings.notifyOnAuthError and settings.notifyWebhookUrl:
                await send_notification(
                    settings.notifyWebhookUrl,
                    build_auth_error_payload(exc),
                    system=settings.notifySystem,
                )
            return None
        finally:
            await client.aclose()

    async def _scheduled_job() -> None:
        settings = read_settings()
        result = await _run_job(settings.dryRun)
        if result:
            _app_state["last_run"] = result

    async def _digest_job() -> None:
        from datetime import UTC, datetime

        settings = read_settings()
        if not settings.notifyWebhookUrl:
            log.debug("[digest] No webhook URL configured — skipping digest")
            return

        since_iso = read_last_digest_at()
        now = datetime.now(UTC)

        # Collect all history entries since the last digest.
        # since_iso=None means first ever digest — use all available history.
        history = read_run_history(limit=500)
        if since_iso is not None:
            entries = [e for e in history if e.get("started_at", "") > since_iso]
        else:
            entries = history

        since_dt = None
        if since_iso is not None:
            from datetime import datetime as _dt

            try:
                since_dt = _dt.fromisoformat(since_iso)
            except (ValueError, TypeError):
                since_dt = None

        await send_notification(
            settings.notifyWebhookUrl,
            build_digest_payload(entries, since=since_dt, until=now),
            system=settings.notifySystem,
        )
        write_last_digest_at(now.isoformat())
        log.info("[digest] Daily digest sent (%d entries)", len(entries))

    _app_state["job_fn"] = _scheduled_job
    _app_state["digest_fn"] = _digest_job
    _app_state["run_job_fn"] = _run_job
    _app_state["last_run"] = None

    settings = read_settings()
    scheduler.reschedule(settings, _scheduled_job)
    scheduler.reschedule_digest(settings, _digest_job)

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

    @app.middleware("http")
    async def cache_control(
        request: Request, call_next: Callable[[Request], Awaitable[Response]]
    ) -> Response:
        response = await call_next(request)
        if "v=" in request.url.query:
            response.headers["Cache-Control"] = "max-age=31536000, immutable"
        return response

    app.include_router(router)

    # Serve frontend static files; index.html is handled by GET / in routes.py
    static_dir = Path(__file__).parent / "static"
    if static_dir.exists():
        app.mount("/", StaticFiles(directory=static_dir, html=False), name="static")

    return app
