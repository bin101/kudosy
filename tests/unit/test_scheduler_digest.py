"""Unit tests for KudosyScheduler.reschedule_digest."""

from __future__ import annotations

import pytest

from kudosy.models import AppSettings
from kudosy.scheduler import KudosyScheduler

_DIGEST_JOB_ID = "digest_job"


def _settings(**overrides: object) -> AppSettings:
    base: dict[str, object] = {
        "notifyWebhookUrl": "https://ntfy.sh/test",
        "notifyDailyDigest": True,
        "notifyDailyDigestTime": "20:00",
    }
    base.update(overrides)
    return AppSettings(**base)  # type: ignore[arg-type]


async def _noop() -> None:
    pass


# ── reschedule_digest ─────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_reschedule_digest_adds_job_when_enabled() -> None:
    sched = KudosyScheduler()
    sched.start()
    try:
        sched.reschedule_digest(_settings(), _noop)
        assert sched._scheduler.get_job(_DIGEST_JOB_ID) is not None
    finally:
        sched.shutdown()


@pytest.mark.asyncio
async def test_reschedule_digest_no_job_when_disabled() -> None:
    sched = KudosyScheduler()
    sched.start()
    try:
        sched.reschedule_digest(_settings(notifyDailyDigest=False), _noop)
        assert sched._scheduler.get_job(_DIGEST_JOB_ID) is None
    finally:
        sched.shutdown()


@pytest.mark.asyncio
async def test_reschedule_digest_no_job_when_url_empty() -> None:
    sched = KudosyScheduler()
    sched.start()
    try:
        sched.reschedule_digest(_settings(notifyWebhookUrl=""), _noop)
        assert sched._scheduler.get_job(_DIGEST_JOB_ID) is None
    finally:
        sched.shutdown()


@pytest.mark.asyncio
async def test_reschedule_digest_removes_existing_job_on_disable() -> None:
    sched = KudosyScheduler()
    sched.start()
    try:
        # First enable
        sched.reschedule_digest(_settings(), _noop)
        assert sched._scheduler.get_job(_DIGEST_JOB_ID) is not None
        # Then disable → job must be gone
        sched.reschedule_digest(_settings(notifyDailyDigest=False), _noop)
        assert sched._scheduler.get_job(_DIGEST_JOB_ID) is None
    finally:
        sched.shutdown()


@pytest.mark.asyncio
async def test_reschedule_digest_replaces_existing_job_on_time_change() -> None:
    sched = KudosyScheduler()
    sched.start()
    try:
        sched.reschedule_digest(_settings(notifyDailyDigestTime="08:00"), _noop)
        assert sched._scheduler.get_job(_DIGEST_JOB_ID) is not None
        sched.reschedule_digest(_settings(notifyDailyDigestTime="20:00"), _noop)
        assert sched._scheduler.get_job(_DIGEST_JOB_ID) is not None
    finally:
        sched.shutdown()
