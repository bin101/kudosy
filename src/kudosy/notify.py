"""Webhook notification helper.

Detects the target system from the URL and formats messages appropriately
for ntfy, Slack, Discord, Gotify, and generic HTTP webhooks.

The HTTP POST callable is injected so unit tests never touch the network.
Failures are logged but never re-raised — a broken webhook must not crash
the application or interrupt the kudos scheduler.
"""

from __future__ import annotations

import logging
import re
from collections.abc import Awaitable, Callable
from typing import Any

log = logging.getLogger(__name__)

PostFn = Callable[[str, dict[str, Any]], Awaitable[None]]


async def _default_post(url: str, payload: dict[str, Any]) -> None:
    import httpx

    async with httpx.AsyncClient(timeout=10) as client:
        resp = await client.post(url, json=payload)
        resp.raise_for_status()


# ── System detection ──────────────────────────────────────────────────────────


def detect_system(url: str) -> str:
    """Return a canonical system name inferred from the webhook URL.

    Supported values: ``"ntfy"`` | ``"slack"`` | ``"discord"`` | ``"gotify"``
    | ``"generic"``.
    """
    u = url.lower()
    if re.search(r"\bntfy\b", u):
        return "ntfy"
    if "hooks.slack.com" in u:
        return "slack"
    if "discord.com/api/webhooks" in u:
        return "discord"
    # Gotify's publish endpoint is typically POST /message
    if re.search(r"/message(?:\?|$)", u):
        return "gotify"
    return "generic"


# ── Per-system payload formatters ─────────────────────────────────────────────


def _format_ntfy(msg: dict[str, Any]) -> dict[str, Any]:
    """ntfy JSON API body (POST to https://ntfy.sh/<topic>).

    ntfy reads ``title``, ``message``, ``priority`` (1-5), and ``tags``
    (list of emoji alias strings) from the JSON body when Content-Type is
    application/json.  The topic comes from the URL path, so we don't include
    it here.
    """
    return {
        "title": msg["title"],
        "message": msg["message"],
        "priority": msg.get("priority", 3),
        "tags": msg.get("tags", []),
    }


def _format_slack(msg: dict[str, Any]) -> dict[str, Any]:
    """Slack Incoming Webhook — bold title + message body."""
    return {"text": f"*{msg['title']}*\n{msg['message']}"}


def _format_discord(msg: dict[str, Any]) -> dict[str, Any]:
    """Discord webhook — single embed with brand or error colour."""
    color = 0xDC2626 if msg.get("event") == "auth_error" else 0x6366F1
    return {
        "embeds": [
            {
                "title": msg["title"],
                "description": msg["message"],
                "color": color,
            }
        ]
    }


def _format_gotify(msg: dict[str, Any]) -> dict[str, Any]:
    """Gotify message — title + message + priority (1-10)."""
    # Map ntfy-style 1-5 priority to Gotify's 1-10 scale
    ntfy_prio = msg.get("priority", 3)
    gotify_prio = max(1, min(10, ntfy_prio * 2))
    return {
        "title": msg["title"],
        "message": msg["message"],
        "priority": gotify_prio,
    }


def _format_generic(msg: dict[str, Any]) -> dict[str, Any]:
    """Generic webhook — human-readable title + message plus structured data."""
    out: dict[str, Any] = {
        "title": msg["title"],
        "message": msg["message"],
    }
    # Include structured fields for integrations that can parse them
    for key in (
        "event",
        "success",
        "dry_run",
        "total",
        "would_give",
        "given",
        "error",
        "started_at",
        "finished_at",
    ):
        if key in msg:
            out[key] = msg[key]
    return out


_FORMATTERS = {
    "ntfy": _format_ntfy,
    "slack": _format_slack,
    "discord": _format_discord,
    "gotify": _format_gotify,
    "generic": _format_generic,
}


# ── Public API ────────────────────────────────────────────────────────────────


async def send_notification(
    url: str,
    message: dict[str, Any],
    *,
    post_fn: PostFn = _default_post,
) -> None:
    """Format *message* for the detected system and POST it to *url*.

    *message* must contain at least ``"title"`` and ``"message"`` keys.
    Silently does nothing when *url* is empty.  Any exception from *post_fn*
    is caught and logged so callers are never interrupted.
    """
    if not url:
        return
    system = detect_system(url)
    formatter = _FORMATTERS[system]
    payload = formatter(message)
    try:
        await post_fn(url, payload)
        log.debug("Notification sent to %.40s (%s)", url, system)
    except Exception as exc:
        log.warning("Notification failed (%s): %s", url[:40], exc)


# ── Message builders ──────────────────────────────────────────────────────────


def _run_summary(result: Any, *, lang: str = "de") -> str:
    if result.dry_run:
        return f"{result.total} Aktivitäten geprüft · {result.would_give} Kudos simuliert"
    return f"{result.total} Aktivitäten geprüft · {result.given} Kudos vergeben"


def build_run_payload(result: Any) -> dict[str, Any]:
    """Build a system-agnostic notification message for a completed run."""
    if result.success:
        if result.dry_run:
            icon, title = "🔍", "Kudosy — Dry-Run abgeschlossen"
            tags = ["mag"]
            priority = 2
        else:
            icon, title = "✅", "Kudosy — Lauf abgeschlossen"
            tags = ["white_check_mark"]
            priority = 3
    else:
        icon, title = "❌", "Kudosy — Lauf fehlgeschlagen"
        tags = ["x"]
        priority = 4

    message_text = f"{icon} {_run_summary(result)}"
    if not result.success and result.error:
        message_text += f"\nFehler: {result.error}"

    return {
        "event": "run_complete",
        "title": title,
        "message": message_text,
        "tags": tags,
        "priority": priority,
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
    """Build a system-agnostic notification message for an auth failure."""
    return {
        "event": "auth_error",
        "title": "Kudosy — Cookie abgelaufen",
        "message": f"⚠️ Der Strava Session-Cookie ist abgelaufen.\n{exc}",
        "tags": ["warning"],
        "priority": 4,
    }
