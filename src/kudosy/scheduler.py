"""APScheduler wrapper with jitter and in-flight guard."""

from __future__ import annotations

import logging
import random
from collections.abc import Callable, Coroutine
from datetime import UTC, datetime, timedelta
from typing import Any

from apscheduler.schedulers.asyncio import AsyncIOScheduler

from kudosy.humanizer import compute_jitter
from kudosy.models import AppSettings

log = logging.getLogger(__name__)

_JOB_ID = "kudos_job"


class KudosyScheduler:
    """Wraps AsyncIOScheduler for the auto-kudos job.

    - Computes next run interval with jitter on each reschedule.
    - Guards against overlapping runs with a single in-flight flag.
    - next_run_at is exposed for /api/status.
    """

    def __init__(self) -> None:
        self._scheduler = AsyncIOScheduler()
        self._is_running = False
        self._next_run_at: datetime | None = None
        self._rng = random.Random()

    @property
    def is_running(self) -> bool:
        return self._is_running

    @property
    def next_run_at(self) -> datetime | None:
        return self._next_run_at

    def start(self) -> None:
        self._scheduler.start()

    def shutdown(self) -> None:
        if self._scheduler.running:
            self._scheduler.shutdown(wait=False)

    def reschedule(
        self,
        settings: AppSettings,
        job_fn: Callable[[], Coroutine[Any, Any, None]],
    ) -> None:
        """Cancel the current job and schedule the next one with jitter."""
        if self._scheduler.get_job(_JOB_ID):
            self._scheduler.remove_job(_JOB_ID)
        self._next_run_at = None

        if not settings.schedulerEnabled:
            log.info("[scheduler] Disabled — no next run scheduled")
            return

        interval_min = compute_jitter(settings.intervalMinutes, settings.jitterMinutes, self._rng)
        run_at = datetime.now(UTC) + timedelta(minutes=interval_min)
        self._next_run_at = run_at

        async def _guarded_job() -> None:
            if self._is_running:
                log.warning("[scheduler] Job already running — skipping this tick")
                return
            self._is_running = True
            try:
                await job_fn()
            finally:
                self._is_running = False
            # Reschedule next run (with fresh jitter) after completion
            self.reschedule(settings, job_fn)

        self._scheduler.add_job(
            _guarded_job,
            trigger="date",
            run_date=run_at,
            id=_JOB_ID,
            replace_existing=True,
        )
        log.info(
            "[scheduler] Next run at %s (interval %.1f min)",
            run_at.isoformat(),
            interval_min,
        )

    async def trigger_now(
        self,
        job_fn: Callable[[], Coroutine[Any, Any, None]],
    ) -> None:
        """Trigger the job immediately (used by POST /api/run)."""
        if self._is_running:
            raise RuntimeError("Job läuft bereits")
        self._is_running = True
        try:
            await job_fn()
        finally:
            self._is_running = False
