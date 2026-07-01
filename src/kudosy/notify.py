"""Webhook notification helper.

The HTTP POST callable is injected so unit tests never touch the network.
Failures are logged but never re-raised — a broken webhook must not crash
the application or interrupt the kudos scheduler.
"""

from __future__ import annotations

import logging
from collections.abc import Awaitable, Callable
from typing import Any

log = logging.getLogger(__name__)

PostFn = Callable[[str, dict[str, Any]], Awaitable[None]]


async def _default_post(url: str, payload: dict[str, Any]) -> None:
    import httpx

    async with httpx.AsyncClient(timeout=10) as client:
        resp = await client.post(url, json=payload)
        resp.raise_for_status()


async def send_notification(
    url: str,
    payload: dict[str, Any],
    *,
    post_fn: PostFn = _default_post,
) -> None:
    """POST *payload* as JSON to *url* via *post_fn*.

    Silently does nothing when *url* is empty.  Any exception from *post_fn*
    is caught and logged so callers are never interrupted.
    """
    if not url:
        return
    try:
        await post_fn(url, payload)
        log.debug("Notification sent to %.40s", url)
    except Exception as exc:
        log.warning("Notification failed (%s): %s", url[:40], exc)


def build_run_payload(result: Any) -> dict[str, Any]:
    """Build a generic JSON payload describing a completed run."""
    return {
        "event": "run_complete",
        "started_at": result.started_at.isoformat(),
        "finished_at": result.finished_at.isoformat(),
        "success": result.success,
        "dry_run": result.dry_run,
        "total": result.total,
        "would_give": result.would_give,
        "given": result.given,
        "error": result.error,
    }


def build_auth_error_payload(exc: Exception) -> dict[str, Any]:
    """Build a generic JSON payload describing an authentication failure."""
    return {
        "event": "auth_error",
        "message": str(exc),
    }
