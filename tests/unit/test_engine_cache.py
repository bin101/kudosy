"""Unit tests for the kudoed-activities cache integration in engine.run_kudos()."""

from __future__ import annotations

from typing import Any
from unittest.mock import AsyncMock

import pytest

from kudosy.engine import run_kudos
from kudosy.models import Activity, AppSettings, UserConfig

# ── Helpers ───────────────────────────────────────────────────────────────────


def make_activity(
    activity_id: str = "10000000001",
    athlete_name: str = "Alex Runner",
    has_kudoed: bool = False,
) -> Activity:
    return Activity(
        activity_id=activity_id,
        athlete_id="20000001",
        athlete_name=athlete_name,
        activity_name="Morning Run",
        sport_type="Run",
        has_kudoed=has_kudoed,
        stats={"Distance": "10.23 km"},
    )


class FakeFeedParser:
    def __init__(self, activities: list[Activity]) -> None:
        self._activities = activities

    def parse(self, payload: str | bytes | dict[str, Any]) -> list[Activity]:
        return self._activities


def make_fake_client(send_kudos_result: bool = True) -> AsyncMock:
    client = AsyncMock()
    client.get_csrf_token = AsyncMock(return_value="csrf-token-abc")
    client.fetch_following_feed = AsyncMock(return_value="dummy-html")
    client.send_kudos = AsyncMock(return_value=send_kudos_result)
    client.aclose = AsyncMock()
    return client


_USER_CFG = UserConfig(stravaSessionCookie="test-cookie", athleteId="20000001")


# ── Cache skip tests ──────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_cached_activity_is_skipped() -> None:
    """An activity_id in kudoed_ids is not evaluated or sent."""
    act = make_activity(activity_id="cached-001")
    client = make_fake_client()
    parser = FakeFeedParser([act])

    result = await run_kudos(
        user_cfg=_USER_CFG,
        settings=AppSettings(),
        client=client,
        feed_parser=parser,
        dry_run=False,
        kudoed_ids={"cached-001"},
    )

    # No kudos should have been sent
    client.send_kudos.assert_not_called()
    assert result.given == 0
    assert result.skipped_cached == 1
    assert result.newly_kudoed == []


@pytest.mark.asyncio
async def test_uncached_activity_is_processed() -> None:
    """An activity_id NOT in kudoed_ids is evaluated and sent normally."""
    act = make_activity(activity_id="new-001")
    client = make_fake_client(send_kudos_result=True)
    parser = FakeFeedParser([act])

    result = await run_kudos(
        user_cfg=_USER_CFG,
        settings=AppSettings(minKudosDelaySeconds=0, maxKudosDelaySeconds=0),
        client=client,
        feed_parser=parser,
        dry_run=False,
        kudoed_ids={"other-id"},  # different id — should not skip "new-001"
    )

    client.send_kudos.assert_called_once_with("new-001", "csrf-token-abc")
    assert result.given == 1
    assert result.skipped_cached == 0
    assert "new-001" in result.newly_kudoed


@pytest.mark.asyncio
async def test_newly_kudoed_populated_after_successful_send() -> None:
    """Activity IDs that were successfully kudoed appear in result.newly_kudoed."""
    acts = [make_activity(activity_id=f"act-{i}") for i in range(3)]
    client = make_fake_client(send_kudos_result=True)
    parser = FakeFeedParser(acts)

    result = await run_kudos(
        user_cfg=_USER_CFG,
        settings=AppSettings(minKudosDelaySeconds=0, maxKudosDelaySeconds=0),
        client=client,
        feed_parser=parser,
        dry_run=False,
    )

    assert sorted(result.newly_kudoed) == ["act-0", "act-1", "act-2"]
    assert result.given == 3


@pytest.mark.asyncio
async def test_dry_run_does_not_populate_newly_kudoed() -> None:
    """Dry-run must not add any IDs to newly_kudoed (no kudos sent)."""
    act = make_activity(activity_id="dry-001")
    client = make_fake_client()
    parser = FakeFeedParser([act])

    result = await run_kudos(
        user_cfg=_USER_CFG,
        settings=AppSettings(),
        client=client,
        feed_parser=parser,
        dry_run=True,
    )

    client.send_kudos.assert_not_called()
    assert result.newly_kudoed == []
    assert result.skipped_cached == 0


@pytest.mark.asyncio
async def test_mixed_cached_and_new_activities() -> None:
    """Only new activities are sent; cached ones are skipped."""
    cached_act = make_activity(activity_id="cached-99")
    new_act = make_activity(activity_id="new-99")
    client = make_fake_client(send_kudos_result=True)
    parser = FakeFeedParser([cached_act, new_act])

    result = await run_kudos(
        user_cfg=_USER_CFG,
        settings=AppSettings(minKudosDelaySeconds=0, maxKudosDelaySeconds=0),
        client=client,
        feed_parser=parser,
        dry_run=False,
        kudoed_ids={"cached-99"},
    )

    client.send_kudos.assert_called_once_with("new-99", "csrf-token-abc")
    assert result.skipped_cached == 1
    assert result.given == 1
    assert result.newly_kudoed == ["new-99"]


@pytest.mark.asyncio
async def test_failed_send_not_added_to_newly_kudoed() -> None:
    """A failed send_kudos should NOT add the ID to newly_kudoed."""
    act = make_activity(activity_id="fail-001")
    client = make_fake_client(send_kudos_result=False)
    parser = FakeFeedParser([act])

    result = await run_kudos(
        user_cfg=_USER_CFG,
        settings=AppSettings(minKudosDelaySeconds=0, maxKudosDelaySeconds=0),
        client=client,
        feed_parser=parser,
        dry_run=False,
    )

    assert result.newly_kudoed == []
    assert result.given == 0


@pytest.mark.asyncio
async def test_no_kudoed_ids_arg_behaves_like_empty_set() -> None:
    """Calling run_kudos without kudoed_ids (None) uses an empty set."""
    act = make_activity(activity_id="vanilla-001")
    client = make_fake_client(send_kudos_result=True)
    parser = FakeFeedParser([act])

    result = await run_kudos(
        user_cfg=_USER_CFG,
        settings=AppSettings(minKudosDelaySeconds=0, maxKudosDelaySeconds=0),
        client=client,
        feed_parser=parser,
        dry_run=False,
        # kudoed_ids omitted (default None)
    )

    assert result.skipped_cached == 0
    assert result.given == 1
