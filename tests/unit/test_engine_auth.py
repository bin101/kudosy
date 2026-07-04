"""Unit tests: AuthError must propagate out of engine.run_kudos().

Regression: the blanket ``except Exception`` in run_kudos swallowed AuthError,
so app.py's ``except AuthError`` handler never fired — auth_ok stayed True and
the notifyOnAuthError webhook was never sent after a cookie expired.
"""

from __future__ import annotations

from typing import Any
from unittest.mock import AsyncMock

import pytest

from kudosy.engine import run_kudos
from kudosy.feed import AuthError
from kudosy.models import Activity, AppSettings, CatchAll, UserConfig

# ── Helpers ───────────────────────────────────────────────────────────────────


def make_activity(activity_id: str = "10000000001") -> Activity:
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


_USER_CFG = UserConfig(
    stravaSessionCookie="test-cookie",
    athleteId="20000001",
    catchAll=CatchAll(minDistance=1.0),
)


# ── AuthError propagation ─────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_auth_error_from_csrf_propagates() -> None:
    """AuthError raised while fetching the CSRF token must not be swallowed."""
    client = AsyncMock()
    client.get_csrf_token = AsyncMock(side_effect=AuthError("Cookie abgelaufen"))
    client.aclose = AsyncMock()

    with pytest.raises(AuthError):
        await run_kudos(
            user_cfg=_USER_CFG,
            settings=AppSettings(),
            client=client,
            feed_parser=FakeFeedParser([]),
            dry_run=False,
        )


@pytest.mark.asyncio
async def test_auth_error_from_feed_fetch_propagates() -> None:
    """AuthError raised while fetching the feed must not be swallowed."""
    client = AsyncMock()
    client.get_csrf_token = AsyncMock(return_value="csrf-token-abc")
    client.fetch_following_feed = AsyncMock(side_effect=AuthError("HTTP 401"))
    client.aclose = AsyncMock()

    with pytest.raises(AuthError):
        await run_kudos(
            user_cfg=_USER_CFG,
            settings=AppSettings(),
            client=client,
            feed_parser=FakeFeedParser([]),
            dry_run=True,
        )


@pytest.mark.asyncio
async def test_generic_error_is_still_captured_in_result() -> None:
    """Non-auth exceptions keep the existing behavior: captured in RunResult."""
    client = AsyncMock()
    client.get_csrf_token = AsyncMock(side_effect=RuntimeError("boom"))
    client.aclose = AsyncMock()

    result = await run_kudos(
        user_cfg=_USER_CFG,
        settings=AppSettings(),
        client=client,
        feed_parser=FakeFeedParser([]),
        dry_run=False,
    )

    assert result.success is False
    assert result.error == "boom"
