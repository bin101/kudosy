"""APScheduler wrapper with jitter and in-flight guard."""

from __future__ import annotations

import logging
import random
from collections.abc import Callable, Coroutine
from datetime import UTC, datetime, timedelta
from typing import Any
from zoneinfo import ZoneInfo

from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.cron import CronTrigger

from kudosy.humanizer import compute_jitter
from kudosy.models import AppSettings
from kudosy.quiet_hours import next_allowed_run
from kudosy.store import read_settings

log = logging.getLogger(__name__)

_JOB_ID = "kudos_job"
_DIGEST_JOB_ID = "digest_job"


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
        candidate = datetime.now(UTC) + timedelta(minutes=interval_min)

        # Shift to the next allowed slot if the quiet-hours matrix is active.
        run_at = next_allowed_run(
            candidate,
            settings.kudosScheduleMatrix,
            settings.timezone,
            enabled=settings.kudosScheduleEnabled,
            rng=self._rng,
        )
        if run_at is None:
            log.warning(
                "[scheduler] All time slots blocked — scheduler paused until settings change"
            )
            return

        self._next_run_at = run_at

        async def _guarded_job() -> None:
            # Re-read settings on every tick (rather than closing over the
            # `settings` this job was scheduled with) so that a PUT
            # /api/settings change made while a run is in flight isn't
            # clobbered by this job's own end-of-run reschedule below.
            if self._is_running:
                log.warning(
                    "[scheduler] Job already running — skipping this tick, "
                    "scheduling the next one so the chain doesn't stall"
                )
                self.reschedule(read_settings(), job_fn)
                return
            self._is_running = True
            try:
                await job_fn()
            finally:
                self._is_running = False
                # Reschedule next run (fresh jitter + settings) even if job_fn
                # raised — otherwise a single failed run would permanently
                # stall the scheduler until the next manual settings change.
                self.reschedule(read_settings(), job_fn)

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

    def reschedule_digest(
        self,
        settings: AppSettings,
        digest_fn: Callable[[], Coroutine[Any, Any, None]],
    ) -> None:
        """Cancel any existing digest job and schedule the daily digest cron job.

        Only schedules when *notifyDailyDigest* is True and a webhook URL is set.
        Uses a CronTrigger so APScheduler repeats it automatically every day
        without manual reschedule-after-completion.
        """
        # Always remove the previous job first so disabling takes effect immediately.
        if self._scheduler.get_job(_DIGEST_JOB_ID):
            self._scheduler.remove_job(_DIGEST_JOB_ID)

        if not (settings.notifyDailyDigest and settings.notifyWebhookUrl):
            log.info("[scheduler] Daily digest disabled — no job scheduled")
            return

        hour, minute = (int(x) for x in settings.notifyDailyDigestTime.split(":"))
        trigger = CronTrigger(
            hour=hour,
            minute=minute,
            timezone=ZoneInfo(settings.timezone),
        )
        self._scheduler.add_job(
            digest_fn,
            trigger=trigger,
            id=_DIGEST_JOB_ID,
            replace_existing=True,
        )
        log.info(
            "[scheduler] Daily digest scheduled at %s %s",
            settings.notifyDailyDigestTime,
            settings.timezone,
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
