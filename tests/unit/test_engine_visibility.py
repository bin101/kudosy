"""Engine error visibility: failure details in the log, athlete ID, unparsed stats."""

from __future__ import annotations

import random
from typing import Any
from unittest.mock import AsyncMock

import pytest

from kudosy.engine import run_kudos
from kudosy.models import Activity, ActivityStats, AppSettings, CatchAll, UserConfig


def _act(activity_id: str = "10000000001", *, distance_m: float | None = 10000.0) -> Activity:
    return Activity(
        activity_id=activity_id,
        athlete_id="20000001",
        athlete_name="Alex Runner",
        activity_name="Morning Run",
        sport_type="Run",
        has_kudoed=False,
        stats=ActivityStats(
            distance_m=distance_m,
            moving_time_s=2700,
            display=[{"key": "distance", "label": "Distance", "raw": "10 km"}]  # type: ignore[list-item]
            if distance_m is not None
            else [{"key": "time", "label": "Zeit", "raw": "45m"}],  # type: ignore[list-item]
        ),
    )


class _Parser:
    def __init__(self, activities: list[Activity]) -> None:
        self._activities = activities

    def parse(self, payload: str | bytes | dict[str, Any]) -> list[Activity]:
        return self._activities


def _cfg(athlete_id: str = "20000001") -> UserConfig:
    return UserConfig(
        stravaSessionCookie="c", athleteId=athlete_id, catchAll=CatchAll(minDistance=1.0)
    )


def _client(*, send_ok: bool = True, status: int | None = None) -> AsyncMock:
    client = AsyncMock()
    client.get_csrf_token = AsyncMock(return_value="csrf")
    client.fetch_following_feed = AsyncMock(return_value={})
    client.fetch_current_athlete_id = AsyncMock(return_value=None)
    client.send_kudos = AsyncMock(return_value=send_ok)
    client.last_kudo_status = status
    return client


_FAST = AppSettings(minKudosDelaySeconds=0, maxKudosDelaySeconds=0)


@pytest.mark.asyncio
async def test_failed_kudo_log_carries_http_status(caplog: pytest.LogCaptureFixture) -> None:
    with caplog.at_level("WARNING"):
        await run_kudos(
            _cfg(),
            _FAST,
            client=_client(send_ok=False, status=403),
            feed_parser=_Parser([_act()]),
            rng=random.Random(0),
        )
    line = next(r.getMessage() for r in caplog.records if "Kudos fehlgeschlagen" in r.getMessage())
    assert "HTTP 403" in line


@pytest.mark.asyncio
async def test_failed_kudo_log_without_status_has_no_http_text(
    caplog: pytest.LogCaptureFixture,
) -> None:
    with caplog.at_level("WARNING"):
        await run_kudos(
            _cfg(),
            _FAST,
            client=_client(send_ok=False, status=None),
            feed_parser=_Parser([_act()]),
            rng=random.Random(0),
        )
    line = next(r.getMessage() for r in caplog.records if "Kudos fehlgeschlagen" in r.getMessage())
    assert "HTTP" not in line


@pytest.mark.asyncio
async def test_missing_athlete_id_is_a_run_error_and_feed_is_not_fetched() -> None:
    client = _client()
    result = await run_kudos(
        _cfg(athlete_id=""), _FAST, client=client, feed_parser=_Parser([]), dry_run=True
    )
    assert result.success is False
    assert result.error is not None
    assert "Athleten-ID" in result.error
    client.fetch_following_feed.assert_not_awaited()


@pytest.mark.asyncio
async def test_athlete_id_resolved_live_still_works() -> None:
    client = _client()
    client.fetch_current_athlete_id = AsyncMock(return_value="20000001")
    result = await run_kudos(
        _cfg(athlete_id=""), _FAST, client=client, feed_parser=_Parser([_act()]), dry_run=True
    )
    assert result.success is True
    client.fetch_following_feed.assert_awaited_once_with("20000001")


@pytest.mark.asyncio
async def test_stat_missing_activity_is_skipped_and_logged(
    caplog: pytest.LogCaptureFixture,
) -> None:
    with caplog.at_level("DEBUG"):
        result = await run_kudos(
            _cfg(), _FAST, client=_client(), feed_parser=_Parser([_act(distance_m=None)]),
            dry_run=True,
        )  # fmt: skip
    assert result.would_give == 0
    assert "--- Activity has no value for an active minimum rule" in caplog.text


@pytest.mark.asyncio
async def test_warns_when_no_activity_has_a_parsable_distance(
    caplog: pytest.LogCaptureFixture,
) -> None:
    acts = [_act(f"1000000000{i}", distance_m=None) for i in range(3)]
    with caplog.at_level("WARNING"):
        await run_kudos(_cfg(), _FAST, client=_client(), feed_parser=_Parser(acts), dry_run=True)
    msg = next(r.getMessage() for r in caplog.records if "no parsable distance" in r.getMessage())
    assert msg.startswith("3 of 3 activities")
    assert "localized" in msg


@pytest.mark.asyncio
async def test_no_distance_warning_when_some_distance_parses(
    caplog: pytest.LogCaptureFixture,
) -> None:
    acts = [_act("1", distance_m=None), _act("2", distance_m=5000.0)]
    with caplog.at_level("WARNING"):
        await run_kudos(_cfg(), _FAST, client=_client(), feed_parser=_Parser(acts), dry_run=True)
    assert "no parsable distance" not in caplog.text


@pytest.mark.asyncio
async def test_no_distance_warning_for_empty_or_statless_feed(
    caplog: pytest.LogCaptureFixture,
) -> None:
    bare = Activity(
        activity_id="9",
        athlete_id="1",
        athlete_name="A",
        activity_name="x",
        sport_type="Run",
        has_kudoed=False,
    )
    with caplog.at_level("WARNING"):
        await run_kudos(_cfg(), _FAST, client=_client(), feed_parser=_Parser([bare]), dry_run=True)
    assert "no parsable distance" not in caplog.text
