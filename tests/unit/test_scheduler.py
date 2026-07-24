"""Unit tests for KudosyScheduler.reschedule / trigger_now.

Regression coverage for the fix that prevents the scheduler from permanently
stalling after an overlapping tick or an exception raised by job_fn — before
the fix, the reschedule-after-completion call sat outside `finally` and the
overlap-skip path returned without rescheduling at all, so either condition
could silently kill the recurring job until the next manual settings change.
"""

from __future__ import annotations

from unittest.mock import patch

import pytest

from kudosy.models import AppSettings
from kudosy.scheduler import KudosyScheduler

_JOB_ID = "kudos_job"


def _settings(**overrides: object) -> AppSettings:
    base: dict[str, object] = {
        "schedulerEnabled": True,
        "intervalMinutes": 60,
        "jitterMinutes": 0.0,
    }
    base.update(overrides)
    return AppSettings(**base)  # type: ignore[arg-type]


async def _noop() -> None:
    pass


def _get_guarded_job(sched: KudosyScheduler):
    """Pull out the actual `_guarded_job` coroutine APScheduler holds for _JOB_ID."""
    job = sched._scheduler.get_job(_JOB_ID)
    assert job is not None
    return job.func


# ── reschedule ────────────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_reschedule_adds_job_when_enabled() -> None:
    sched = KudosyScheduler()
    sched.start()
    try:
        sched.reschedule(_settings(), _noop)
        assert sched._scheduler.get_job(_JOB_ID) is not None
        assert sched.next_run_at is not None
    finally:
        sched.shutdown()


@pytest.mark.asyncio
async def test_reschedule_no_job_when_disabled() -> None:
    sched = KudosyScheduler()
    sched.start()
    try:
        sched.reschedule(_settings(schedulerEnabled=False), _noop)
        assert sched._scheduler.get_job(_JOB_ID) is None
        assert sched.next_run_at is None
    finally:
        sched.shutdown()


# ── stall regressions ─────────────────────────────────────────────────────────


@pytest.mark.asyncio
@patch("kudosy.scheduler.read_settings")
async def test_guarded_job_reschedules_after_job_fn_raises(mock_read_settings: object) -> None:
    """A job_fn exception must not permanently stall the scheduler."""
    mock_read_settings.return_value = _settings()  # type: ignore[attr-defined]

    async def _boom() -> None:
        raise RuntimeError("boom")

    sched = KudosyScheduler()
    sched.start()
    try:
        sched.reschedule(_settings(), _boom)
        guarded = _get_guarded_job(sched)
        # In production APScheduler's own job-execution layer catches this;
        # calling `_guarded_job` directly bypasses that layer, so the
        # exception still propagates here — the fix under test is that the
        # reschedule in `finally` runs *before* it does.
        with pytest.raises(RuntimeError, match="boom"):
            await guarded()  # simulate the date-trigger firing
        assert sched.is_running is False
        assert sched._scheduler.get_job(_JOB_ID) is not None  # rescheduled, not dropped
        assert sched.next_run_at is not None
    finally:
        sched.shutdown()


@pytest.mark.asyncio
@patch("kudosy.scheduler.read_settings")
async def test_guarded_job_reschedules_when_overlap_skips_tick(mock_read_settings: object) -> None:
    """If a manual run is in flight when the tick fires, the tick must skip
    but still arrange a next run instead of leaving the scheduler stalled."""
    mock_read_settings.return_value = _settings()  # type: ignore[attr-defined]

    sched = KudosyScheduler()
    sched.start()
    try:
        sched.reschedule(_settings(), _noop)
        guarded = _get_guarded_job(sched)
        sched._is_running = True  # simulate an in-flight manual run (POST /api/run)
        await guarded()
        assert sched._scheduler.get_job(_JOB_ID) is not None
        assert sched.next_run_at is not None
    finally:
        sched._is_running = False
        sched.shutdown()


@pytest.mark.asyncio
@patch("kudosy.scheduler.read_settings")
async def test_guarded_job_uses_fresh_settings_not_stale_closure(
    mock_read_settings: object,
) -> None:
    """A settings change made while a run is in flight must be picked up by
    the end-of-run reschedule, not overwritten by the settings this job was
    originally scheduled with."""
    sched = KudosyScheduler()
    sched.start()
    try:
        sched.reschedule(_settings(intervalMinutes=60), _noop)
        guarded = _get_guarded_job(sched)
        # Simulate PUT /api/settings disabling the scheduler while the run was in flight.
        mock_read_settings.return_value = _settings(schedulerEnabled=False)  # type: ignore[attr-defined]
        await guarded()
        assert sched._scheduler.get_job(_JOB_ID) is None  # fresh (disabled) settings won
        assert sched.next_run_at is None
    finally:
        sched.shutdown()


# ── trigger_now ───────────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_trigger_now_raises_when_already_running() -> None:
    sched = KudosyScheduler()
    sched._is_running = True
    with pytest.raises(RuntimeError):
        await sched.trigger_now(_noop)


@pytest.mark.asyncio
async def test_trigger_now_resets_running_flag_after_success() -> None:
    sched = KudosyScheduler()
    await sched.trigger_now(_noop)
    assert sched.is_running is False


@pytest.mark.asyncio
async def test_trigger_now_resets_running_flag_after_exception() -> None:
    sched = KudosyScheduler()

    async def _boom() -> None:
        raise RuntimeError("boom")

    with pytest.raises(RuntimeError):
        await sched.trigger_now(_boom)
    assert sched.is_running is False
