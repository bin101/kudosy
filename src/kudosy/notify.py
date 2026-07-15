"""Webhook notification helper.

Formats messages for ntfy, Slack, Discord, Gotify, and generic HTTP webhooks.
The target system is supplied explicitly by the caller (stored in AppSettings).

The HTTP POST callable is injected so unit tests never touch the network.
Failures are logged but never re-raised — a broken webhook must not crash
the application or interrupt the kudos scheduler.
"""

from __future__ import annotations

import logging
import re
from collections.abc import Awaitable, Callable
from datetime import datetime
from typing import Any

log = logging.getLogger(__name__)

PostFn = Callable[[str, dict[str, Any]], Awaitable[None]]


async def _default_post(url: str, payload: dict[str, Any]) -> None:
    import httpx

    async with httpx.AsyncClient(timeout=10) as client:
        if "_body" in payload:
            # Plain-text body + X-* headers (ntfy headers API).
            # Values are (bytes, bytes) tuples so httpx skips ASCII validation;
            # ntfy receives and decodes UTF-8 bytes directly (handles em-dashes etc.).
            headers = [
                (k.encode("ascii"), v.encode("utf-8"))
                for k, v in payload.items()
                if not k.startswith("_")
            ]
            resp = await client.post(url, content=payload["_body"].encode("utf-8"), headers=headers)
        else:
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
    """ntfy headers API — plain-text body + X-* metadata headers.

    Using headers instead of JSON body avoids Content-Type stripping by
    reverse proxies (nginx, Traefik, Caddy), which causes ntfy to show raw
    JSON as the notification text.  The ``_body`` sentinel triggers
    ``_default_post`` to send ``content=`` with HTTP headers instead of
    ``json=``.
    """
    return {
        "_body": msg["message"],
        "X-Title": msg["title"],
        "X-Priority": str(msg.get("priority", 3)),
        "X-Tags": ",".join(msg.get("tags", [])),
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
        # daily_digest fields
        "runs",
        "failed",
        "since",
        "until",
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
    system: str = "generic",
    post_fn: PostFn = _default_post,
) -> None:
    """Format *message* for *system* and POST it to *url*.

    *system* must be one of ``"ntfy"``, ``"slack"``, ``"discord"``,
    ``"gotify"``, or ``"generic"`` (the default).
    *message* must contain at least ``"title"`` and ``"message"`` keys.
    Silently does nothing when *url* is empty.  Any exception from *post_fn*
    is caught and logged so callers are never interrupted.
    """
    if not url:
        return
    formatter = _FORMATTERS.get(system, _format_generic)
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


def _collect_ids(entries: list[dict[str, Any]], id_key: str) -> set[str]:
    """Union of all *id_key* lists across *entries* (entries without the key are skipped)."""
    ids: set[str] = set()
    for e in entries:
        entry_ids = e.get(id_key)
        if entry_ids:
            ids.update(entry_ids)
    return ids


def _unique_count(
    entries: list[dict[str, Any]],
    id_key: str,
    fallback_key: str,
    *,
    exclude: set[str] | frozenset[str] = frozenset(),
) -> int:
    """Count activities across *entries* by *id_key*, deduplicated by activity ID.

    The same activity is frequently re-scanned across consecutive runs (e.g. it
    stays in the Strava feed until it scrolls off), so summing per-run counts
    would count it once per run instead of once overall. Entries carrying an
    ``id_key`` list are deduplicated via a set; older entries that predate this
    field (no ``id_key``) fall back to their raw *fallback_key* count.

    IDs in *exclude* (activities already counted in an earlier digest) are
    ignored entirely — legacy fallback counts cannot be excluded.
    """
    seen: set[str] = set()
    legacy_total = 0
    for e in entries:
        ids = e.get(id_key)
        if ids:
            seen.update(i for i in ids if i not in exclude)
        else:
            legacy_total += int(e.get(fallback_key, 0))
    return len(seen) + legacy_total


def build_digest_payload(
    entries: list[dict[str, Any]],
    *,
    since: datetime | None,
    until: datetime,
    previous_entries: list[dict[str, Any]] | None = None,
) -> dict[str, Any]:
    """Build a system-agnostic daily-digest notification message.

    *entries* is the list of run-history dicts (each with keys: dry_run, total,
    would_give, given, success) covering the period since the last digest.
    *since* is None for the very first digest (all available history was used).

    Activities that appear in more than one run (e.g. still in the feed on the
    next scheduled run) are counted once, not once per run — see
    :func:`_unique_count`.

    *previous_entries* are run-history dicts from before the digest window
    (i.e. already covered by earlier digests). Activity IDs seen there are
    excluded from all counts, so each digest only reports newly appeared
    activities instead of re-counting ones that linger in the Strava feed
    for days.
    """
    previous = previous_entries or []
    runs = len(entries)
    total = _unique_count(
        entries, "activity_ids", "total", exclude=_collect_ids(previous, "activity_ids")
    )
    given = _unique_count(
        entries, "given_ids", "given", exclude=_collect_ids(previous, "given_ids")
    )
    would_give = _unique_count(
        entries, "would_give_ids", "would_give", exclude=_collect_ids(previous, "would_give_ids")
    )
    failed = sum(1 for e in entries if not e.get("success", True))

    if runs == 0:
        message_text = "📊 Keine Läufe seit der letzten Zusammenfassung."
    else:
        live_runs = sum(1 for e in entries if not e.get("dry_run", False))
        dry_runs = runs - live_runs
        parts: list[str] = [f"📊 {runs} Lauf/Läufe · {total} neue Aktivitäten"]
        if live_runs:
            parts.append(f"{given} Kudos vergeben")
        if dry_runs:
            parts.append(f"{would_give} Kudos simuliert")
        if failed:
            parts.append(f"{failed} fehlgeschlagen")
        message_text = " · ".join(parts)

    return {
        "event": "daily_digest",
        "title": "Kudosy — Tägliche Zusammenfassung",
        "message": message_text,
        "tags": ["bar_chart"],
        "priority": 3,
        "runs": runs,
        "total": total,
        "given": given,
        "would_give": would_give,
        "failed": failed,
        "since": since.isoformat() if since is not None else None,
        "until": until.isoformat(),
    }
