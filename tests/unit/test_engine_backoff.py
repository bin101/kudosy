"""Unit tests: the send loop must back off on rate limits and repeated failures.

Previously a 429 only produced a warning and the loop kept firing the
remaining kudos — the opposite of what a rate limit asks for.
"""

from __future__ import annotations

from typing import Any
from unittest.mock import AsyncMock

import pytest

from kudosy.engine import run_kudos
from kudosy.feed import RateLimitError
from kudosy.models import Activity, AppSettings, CatchAll, UserConfig

# ── Helpers ───────────────────────────────────────────────────────────────────


def make_activity(activity_id: str) -> Activity:
    return Activity(
        activity_id=activity_id,
        athlete_id="20000001",
        athlete_name="Alex Runner",
        activity_name="Morning Run",
        sport_type="Run",
        has_kudoed=False,
        stats={"Distance": "10.23 km"},
    )


class FakeFeedParser:
    def __init__(self, activities: list[Activity]) -> None:
        self._activities = activities

    def parse(self, payload: str | bytes | dict[str, Any]) -> list[Activity]:
        return self._activities


def make_client(send_kudos_side_effect: Any) -> AsyncMock:
    client = AsyncMock()
    client.get_csrf_token = AsyncMock(return_value="csrf-token-abc")
    client.fetch_following_feed = AsyncMock(return_value="dummy")
    client.send_kudos = AsyncMock(side_effect=send_kudos_side_effect)
    client.aclose = AsyncMock()
    return client


_USER_CFG = UserConfig(
    stravaSessionCookie="test-cookie",
    athleteId="20000001",
    catchAll=CatchAll(minDistance=1.0),
)

_SETTINGS = AppSettings(
    minKudosDelaySeconds=0,
    maxKudosDelaySeconds=0,
    shuffleOrder=False,
)


# ── Rate limit ────────────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_rate_limit_aborts_remaining_kudos() -> None:
    """RateLimitError on the 2nd kudo → 1 given, rest skipped, run completes."""
    acts = [make_activity(f"act-{i}") for i in range(4)]
    client = make_client([True, RateLimitError("429"), True, True])
    parser = FakeFeedParser(acts)

    result = await run_kudos(
        user_cfg=_USER_CFG,
        settings=_SETTINGS,
        client=client,
        feed_parser=parser,
        dry_run=False,
    )

    assert result.given == 1
    assert result.newly_kudoed == ["act-0"]
    assert client.send_kudos.call_count == 2  # aborted after the 429
    assert result.aborted_reason == "rate_limited"
    assert result.success is True  # a backoff is not a crash


@pytest.mark.asyncio
async def test_no_abort_without_rate_limit() -> None:
    """All sends succeed → no aborted_reason."""
    acts = [make_activity(f"act-{i}") for i in range(3)]
    client = make_client([True, True, True])
    parser = FakeFeedParser(acts)

    result = await run_kudos(
        user_cfg=_USER_CFG,
        settings=_SETTINGS,
        client=client,
        feed_parser=parser,
        dry_run=False,
    )

    assert result.given == 3
    assert result.aborted_reason is None


# ── Consecutive failures ──────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_three_consecutive_failures_abort_run() -> None:
    """3 failed sends in a row → stop hammering the remaining activities."""
    acts = [make_activity(f"act-{i}") for i in range(5)]
    client = make_client([False, False, False, True, True])
    parser = FakeFeedParser(acts)

    result = await run_kudos(
        user_cfg=_USER_CFG,
        settings=_SETTINGS,
        client=client,
        feed_parser=parser,
        dry_run=False,
    )

    assert client.send_kudos.call_count == 3
    assert result.given == 0
    assert result.aborted_reason == "consecutive_failures"


@pytest.mark.asyncio
async def test_non_consecutive_failures_do_not_abort() -> None:
    """A success in between resets the failure counter."""
    acts = [make_activity(f"act-{i}") for i in range(5)]
    client = make_client([False, False, True, False, False])
    parser = FakeFeedParser(acts)

    result = await run_kudos(
        user_cfg=_USER_CFG,
        settings=_SETTINGS,
        client=client,
        feed_parser=parser,
        dry_run=False,
    )

    assert client.send_kudos.call_count == 5
    assert result.given == 1
    assert result.aborted_reason is None
