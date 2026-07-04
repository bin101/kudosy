"""Update check — compare the running version against the latest GitHub release.

Pure helpers plus a small scheduler hook. The HTTP GET is injected
(``get_fn``, analogous to ``notify.post_fn``) so everything is testable
without network access. All failures degrade to "no update info" — the
status endpoint must never break because GitHub is unreachable.
"""

from __future__ import annotations

import asyncio
import logging
import time
from collections.abc import Awaitable, Callable
from typing import Any

log = logging.getLogger(__name__)

LATEST_RELEASE_URL = "https://api.github.com/repos/bin101/kudosy/releases/latest"
RELEASES_PAGE_URL = "https://github.com/bin101/kudosy/releases"

# Re-check at most every 12 hours.
CHECK_INTERVAL_S = 12 * 3600

GetFn = Callable[[str], Awaitable[dict[str, Any]]]


async def _default_get(url: str) -> dict[str, Any]:
    import httpx

    async with httpx.AsyncClient(timeout=5.0) as client:
        resp = await client.get(url, headers={"Accept": "application/vnd.github+json"})
        resp.raise_for_status()
        data = resp.json()
        return data if isinstance(data, dict) else {}


def parse_version(version: str) -> tuple[int, ...] | None:
    """Parse ``"1.8.0"`` or ``"v1.8.0"`` into an int tuple; None on garbage."""
    s = version.strip().removeprefix("v")
    if not s:
        return None
    try:
        return tuple(int(part) for part in s.split("."))
    except ValueError:
        return None


def is_newer(current: str, latest: str) -> bool:
    """True when *latest* is a strictly newer SemVer than *current*."""
    cur = parse_version(current)
    new = parse_version(latest)
    if cur is None or new is None:
        return False
    return new > cur


async def fetch_latest_version(*, get_fn: GetFn = _default_get) -> str | None:
    """Return the latest release version (without ``v`` prefix), or None."""
    try:
        data = await get_fn(LATEST_RELEASE_URL)
    except Exception:
        log.debug("Update check failed", exc_info=True)
        return None
    tag = str(data.get("tag_name") or "").removeprefix("v")
    if parse_version(tag) is None:
        return None
    return tag


FetchFn = Callable[[], Awaitable[str | None]]


def maybe_schedule_update_check(
    state: dict[str, Any],
    enabled: bool,
    *,
    fetch_fn: FetchFn = fetch_latest_version,
    now_fn: Callable[[], float] = time.monotonic,
) -> bool:
    """Spawn a background refresh of ``state["latest_version"]`` when due.

    Called lazily from GET /api/status. Returns True when a check was
    scheduled. At most one check per ``CHECK_INTERVAL_S``; a still-running
    task is never duplicated.
    """
    if not enabled:
        return False
    last: float | None = state.get("update_check_at")
    if last is not None and now_fn() - last < CHECK_INTERVAL_S:
        return False
    task: asyncio.Task[None] | None = state.get("update_check_task")
    if task is not None and not task.done():
        return False

    state["update_check_at"] = now_fn()

    async def _refresh() -> None:
        state["latest_version"] = await fetch_fn()

    state["update_check_task"] = asyncio.create_task(_refresh())
    return True
