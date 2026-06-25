"""Integration tests for engine.py — kudos run logic.

Uses injected fake client and fake parser so no real HTTP calls are made.
"""

from __future__ import annotations

import random
from datetime import UTC, datetime
from typing import Any
from unittest.mock import AsyncMock

import pytest

from kudosy.engine import run_kudos
from kudosy.models import Activity, AppSettings, CatchAll, KudoRules, RunResult, UserConfig

# ── Helpers ───────────────────────────────────────────────────────────────────


def _default_cfg(**kwargs: object) -> UserConfig:
    """Return a UserConfig with a catchAll rule so the NO_RULE gate passes by default."""
    return UserConfig(
        stravaSessionCookie="dummy",
        athleteId="11111",
        catchAll=CatchAll(minDistance=1.0, minTime=0),
        **kwargs,  # type: ignore[arg-type]
    )


def make_activity(
    activity_id: str = "10000000001",
    athlete_id: str = "20000001",
    athlete_name: str = "Alex Runner",
    activity_name: str = "Morning Run",
    sport_type: str = "Run",
    has_kudoed: bool = False,
    stats: dict[str, str] | None = None,
) -> Activity:
    return Activity(
        activity_id=activity_id,
        athlete_id=athlete_id,
        athlete_name=athlete_name,
        activity_name=activity_name,
        sport_type=sport_type,
        has_kudoed=has_kudoed,
        stats=stats or {"Distance": "10.23 km", "Time": "45m 0s"},
    )


class FakeFeedParser:
    """Configurable fake FeedParser."""

    def __init__(self, activities: list[Activity]) -> None:
        self._activities = activities

    def parse(self, payload: str | bytes | dict[str, Any]) -> list[Activity]:
        return self._activities


def make_fake_client(
    csrf: str = "csrf-token-abc",
    feed_payload: str = "dummy-html",
    send_kudos_result: bool = True,
    athlete_name: str | None = None,
) -> AsyncMock:
    """Return a mock StravaClient with configurable return values."""
    client = AsyncMock()
    client.get_csrf_token = AsyncMock(return_value=csrf)
    client.fetch_following_feed = AsyncMock(return_value=feed_payload)
    client.send_kudos = AsyncMock(return_value=send_kudos_result)
    client.lookup_athlete = AsyncMock(return_value=athlete_name)
    client.aclose = AsyncMock()
    return client


# ── Basic run tests ───────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_dry_run_returns_result() -> None:
    activities = [make_activity()]
    client = make_fake_client()
    parser = FakeFeedParser(activities)

    result = await run_kudos(
        user_cfg=_default_cfg(),
        settings=AppSettings(),
        client=client,
        feed_parser=parser,
        dry_run=True,
    )

    assert isinstance(result, RunResult)
    assert result.dry_run is True
    assert result.total == 1
    assert result.would_give == 1
    assert result.given == 0  # no real kudos in dry-run
    assert result.success is True
    assert result.error is None


@pytest.mark.asyncio
async def test_live_run_sends_kudos() -> None:
    activities = [make_activity()]
    client = make_fake_client(send_kudos_result=True)
    parser = FakeFeedParser(activities)

    result = await run_kudos(
        user_cfg=_default_cfg(),
        settings=AppSettings(
            minKudosDelaySeconds=0.0,
            maxKudosDelaySeconds=0.0,
            shuffleOrder=False,
        ),
        client=client,
        feed_parser=parser,
        dry_run=False,
        rng=random.Random(42),
    )

    assert result.given == 1
    assert result.would_give == 1
    assert result.success is True
    client.send_kudos.assert_awaited_once_with("10000000001", "csrf-token-abc")


@pytest.mark.asyncio
async def test_already_kudoed_not_given() -> None:
    activities = [make_activity(has_kudoed=True)]
    client = make_fake_client()
    parser = FakeFeedParser(activities)

    result = await run_kudos(
        user_cfg=None,
        settings=AppSettings(),
        client=client,
        feed_parser=parser,
        dry_run=True,
    )

    assert result.would_give == 0
    assert result.total == 1


@pytest.mark.asyncio
async def test_ignored_athlete_skipped() -> None:
    activities = [make_activity(athlete_id="99999")]
    user_cfg = UserConfig(
        stravaSessionCookie="dummy",
        athleteId="11111",
        ignoreAthletes=["99999"],
    )
    client = make_fake_client()
    parser = FakeFeedParser(activities)

    result = await run_kudos(
        user_cfg=user_cfg,
        settings=AppSettings(),
        client=client,
        feed_parser=parser,
        dry_run=True,
    )

    assert result.would_give == 0


@pytest.mark.asyncio
async def test_empty_feed_is_ok() -> None:
    client = make_fake_client()
    parser = FakeFeedParser([])

    result = await run_kudos(
        user_cfg=None,
        settings=AppSettings(),
        client=client,
        feed_parser=parser,
        dry_run=True,
    )

    assert result.total == 0
    assert result.would_give == 0
    assert result.success is True


@pytest.mark.asyncio
async def test_criteria_skips_short_run() -> None:
    """An activity shorter than the minDistance rule is skipped."""
    activities = [
        make_activity(
            sport_type="Run",
            stats={"Distance": "2.00 km", "Time": "15m 0s"},
        )
    ]
    user_cfg = UserConfig(
        stravaSessionCookie="dummy",
        athleteId="11111",
        kudoRules=KudoRules(minDistance={"Run": 5.0}),  # km
    )
    client = make_fake_client()
    parser = FakeFeedParser(activities)

    result = await run_kudos(
        user_cfg=user_cfg,
        settings=AppSettings(),
        client=client,
        feed_parser=parser,
        dry_run=True,
    )

    assert result.would_give == 0


@pytest.mark.asyncio
async def test_name_match_overrides_criteria() -> None:
    """An activity matching activityNames regex gets kudos even below threshold."""
    activities = [
        make_activity(
            sport_type="Run",
            activity_name="Epic Morning Run",
            stats={"Distance": "0.50 km", "Time": "5m 0s"},
        )
    ]
    user_cfg = UserConfig(
        stravaSessionCookie="dummy",
        athleteId="11111",
        kudoRules=KudoRules(
            minDistance={"Run": 10.0},
            activityNames=["Epic.*"],
        ),
    )
    client = make_fake_client()
    parser = FakeFeedParser(activities)

    result = await run_kudos(
        user_cfg=user_cfg,
        settings=AppSettings(),
        client=client,
        feed_parser=parser,
        dry_run=True,
    )

    assert result.would_give == 1


@pytest.mark.asyncio
async def test_failed_kudos_not_counted() -> None:
    activities = [make_activity(activity_id="10000000001")]
    client = make_fake_client(send_kudos_result=False)
    parser = FakeFeedParser(activities)

    result = await run_kudos(
        user_cfg=_default_cfg(),
        settings=AppSettings(
            minKudosDelaySeconds=0.0,
            maxKudosDelaySeconds=0.0,
        ),
        client=client,
        feed_parser=parser,
        dry_run=False,
        rng=random.Random(0),
    )

    assert result.given == 0  # send returned False
    assert result.would_give == 1  # we decided to give, but it failed


@pytest.mark.asyncio
async def test_error_captured_in_result() -> None:
    """If get_csrf_token raises, result.success is False and error is set."""
    client = AsyncMock()
    client.get_csrf_token = AsyncMock(side_effect=RuntimeError("network error"))
    parser = FakeFeedParser([])

    result = await run_kudos(
        user_cfg=None,
        settings=AppSettings(),
        client=client,
        feed_parser=parser,
        dry_run=True,
    )

    assert result.success is False
    assert "network error" in (result.error or "")


@pytest.mark.asyncio
async def test_result_timestamps_set() -> None:
    client = make_fake_client()
    parser = FakeFeedParser([])
    before = datetime.now(UTC)

    result = await run_kudos(
        user_cfg=None,
        settings=AppSettings(),
        client=client,
        feed_parser=parser,
        dry_run=True,
    )

    after = datetime.now(UTC)
    assert before <= result.started_at <= after
    assert result.started_at <= result.finished_at <= after


@pytest.mark.asyncio
async def test_multiple_activities_all_given() -> None:
    activities = [
        make_activity(activity_id=f"1000000000{i}", athlete_id=f"2000000{i}") for i in range(1, 4)
    ]
    client = make_fake_client()
    parser = FakeFeedParser(activities)

    result = await run_kudos(
        user_cfg=_default_cfg(),
        settings=AppSettings(
            minKudosDelaySeconds=0.0,
            maxKudosDelaySeconds=0.0,
            shuffleOrder=False,
        ),
        client=client,
        feed_parser=parser,
        dry_run=False,
        rng=random.Random(7),
    )

    assert result.total == 3
    assert result.given == 3
