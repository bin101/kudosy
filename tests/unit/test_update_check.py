"""Unit tests for update_check — GitHub latest-release lookup and comparison."""

from __future__ import annotations

from typing import Any

import pytest

from kudosy.update_check import (
    CHECK_INTERVAL_S,
    fetch_latest_version,
    is_newer,
    maybe_schedule_update_check,
    parse_version,
)

# ── parse_version ─────────────────────────────────────────────────────────────


def test_parse_version_plain() -> None:
    assert parse_version("1.8.0") == (1, 8, 0)


def test_parse_version_strips_v_prefix() -> None:
    assert parse_version("v1.9.2") == (1, 9, 2)


def test_parse_version_garbage_is_none() -> None:
    assert parse_version("latest") is None
    assert parse_version("") is None
    assert parse_version("1.x.0") is None


# ── is_newer ──────────────────────────────────────────────────────────────────


@pytest.mark.parametrize(
    ("current", "latest", "expected"),
    [
        ("1.8.0", "1.9.0", True),
        ("1.8.0", "2.0.0", True),
        ("1.8.0", "1.8.1", True),
        ("1.8.0", "1.8.0", False),
        ("1.9.0", "1.8.0", False),
        ("1.8.0", "v1.9.0", True),  # tag prefix tolerated
        ("1.8.0", "garbage", False),
        ("garbage", "1.9.0", False),
    ],
)
def test_is_newer(current: str, latest: str, expected: bool) -> None:
    assert is_newer(current, latest) is expected


# ── fetch_latest_version ──────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_fetch_latest_version_returns_tag() -> None:
    async def fake_get(url: str) -> dict[str, Any]:
        assert "bin101/kudosy" in url
        return {"tag_name": "v1.9.0"}

    assert await fetch_latest_version(get_fn=fake_get) == "1.9.0"


@pytest.mark.asyncio
async def test_fetch_latest_version_error_returns_none() -> None:
    async def fake_get(url: str) -> dict[str, Any]:
        raise RuntimeError("network down")

    assert await fetch_latest_version(get_fn=fake_get) is None


@pytest.mark.asyncio
async def test_fetch_latest_version_bad_payload_returns_none() -> None:
    async def fake_get(url: str) -> dict[str, Any]:
        return {"message": "Not Found"}

    assert await fetch_latest_version(get_fn=fake_get) is None


# ── maybe_schedule_update_check ───────────────────────────────────────────────


@pytest.mark.asyncio
async def test_schedule_runs_and_stores_result() -> None:
    state: dict[str, Any] = {}

    async def fake_fetch() -> str | None:
        return "9.9.9"

    scheduled = maybe_schedule_update_check(state, True, fetch_fn=fake_fetch)
    assert scheduled is True
    await state["update_check_task"]
    assert state["latest_version"] == "9.9.9"


@pytest.mark.asyncio
async def test_schedule_disabled_does_nothing() -> None:
    state: dict[str, Any] = {}
    assert maybe_schedule_update_check(state, False) is False
    assert "update_check_task" not in state


@pytest.mark.asyncio
async def test_schedule_respects_check_interval() -> None:
    state: dict[str, Any] = {}
    clock = [1000.0]

    async def fake_fetch() -> str | None:
        return "9.9.9"

    def now() -> float:
        return clock[0]

    assert maybe_schedule_update_check(state, True, fetch_fn=fake_fetch, now_fn=now) is True
    await state["update_check_task"]

    # Within the interval → not scheduled again
    clock[0] += CHECK_INTERVAL_S - 1
    assert maybe_schedule_update_check(state, True, fetch_fn=fake_fetch, now_fn=now) is False

    # After the interval → scheduled again
    clock[0] += 2
    assert maybe_schedule_update_check(state, True, fetch_fn=fake_fetch, now_fn=now) is True
    await state["update_check_task"]
