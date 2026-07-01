"""Unit tests for kudosy.notify (webhook notifications, TDD)."""

from __future__ import annotations

import datetime
from urllib.parse import quote

import pytest

from kudosy.feed import AuthError
from kudosy.models import AppSettings, RunResult
from kudosy.notify import (
    build_auth_error_payload,
    build_run_payload,
    detect_system,
    send_notification,
)


def _result(**kwargs: object) -> RunResult:
    base: dict[str, object] = {
        "started_at": datetime.datetime(2025, 1, 1, 10, 0, tzinfo=datetime.UTC),
        "finished_at": datetime.datetime(2025, 1, 1, 10, 5, tzinfo=datetime.UTC),
        "success": True,
        "dry_run": False,
        "total": 10,
        "would_give": 3,
        "given": 3,
    }
    return RunResult(**(base | kwargs))  # type: ignore[arg-type]


# ── detect_system ─────────────────────────────────────────────────────────────


def test_detect_ntfy_sh() -> None:
    assert detect_system("https://ntfy.sh/my-topic") == "ntfy"


def test_detect_self_hosted_ntfy() -> None:
    assert detect_system("https://ntfy.example.com/kudosy") == "ntfy"


def test_detect_slack() -> None:
    assert detect_system("https://hooks.slack.com/services/T00/B00/xxx") == "slack"


def test_detect_discord() -> None:
    assert detect_system("https://discord.com/api/webhooks/123/token") == "discord"


def test_detect_gotify() -> None:
    assert detect_system("https://gotify.example.com/message") == "gotify"
    assert detect_system("https://gotify.example.com/message?token=abc") == "gotify"


def test_detect_generic_fallback() -> None:
    assert detect_system("https://hooks.example.com/my-webhook") == "generic"


# ── build_run_payload ─────────────────────────────────────────────────────────


def test_build_run_payload_has_title_and_message() -> None:
    result = _result(given=5, total=12, dry_run=False)
    payload = build_run_payload(result)
    assert payload["title"]
    assert payload["message"]


def test_build_run_payload_live_summary_in_message() -> None:
    result = _result(given=5, total=12, dry_run=False)
    payload = build_run_payload(result)
    assert "12" in payload["message"]
    assert "5" in payload["message"]


def test_build_run_payload_dry_run_summary_uses_would_give() -> None:
    result = _result(given=0, would_give=4, total=8, dry_run=True)
    payload = build_run_payload(result)
    assert payload["dry_run"] is True
    assert "4" in payload["message"]
    assert "8" in payload["message"]


def test_build_run_payload_failed_run_includes_error() -> None:
    result = _result(success=False, error="timeout", given=0, total=0, would_give=0)
    payload = build_run_payload(result)
    assert payload["success"] is False
    assert "timeout" in payload["message"]


def test_build_run_payload_has_structured_fields() -> None:
    result = _result(given=5, total=12)
    payload = build_run_payload(result)
    assert payload["event"] == "run_complete"
    assert "started_at" in payload
    assert "tags" in payload
    assert "priority" in payload


def test_build_run_payload_dry_run_lower_priority_than_live() -> None:
    dry = build_run_payload(_result(dry_run=True, given=0, would_give=2))
    live = build_run_payload(_result(dry_run=False, given=2))
    assert dry["priority"] < live["priority"]


# ── build_auth_error_payload ──────────────────────────────────────────────────


def test_build_auth_error_payload_event_field() -> None:
    exc = AuthError("Cookie abgelaufen")
    payload = build_auth_error_payload(exc)
    assert payload["event"] == "auth_error"


def test_build_auth_error_payload_has_title_and_message() -> None:
    exc = AuthError("Session expired")
    payload = build_auth_error_payload(exc)
    assert payload["title"]
    assert "Session expired" in payload["message"]


def test_build_auth_error_payload_high_priority() -> None:
    payload = build_auth_error_payload(AuthError("x"))
    assert payload["priority"] >= 4


# ── send_notification — ntfy formatting ───────────────────────────────────────


@pytest.mark.asyncio
async def test_send_ntfy_payload_has_ntfy_fields() -> None:
    calls: list[tuple[str, dict[str, object]]] = []

    async def fake_post(url: str, payload: dict[str, object]) -> None:
        calls.append((url, payload))

    msg = build_run_payload(_result(given=5, total=12))
    await send_notification("https://ntfy.sh/kudosy", msg, system="ntfy", post_fn=fake_post)

    assert len(calls) == 1
    _url, body = calls[0]
    # ntfy uses headers API: plain text _body + X-* header keys
    assert "_body" in body
    assert body["_body"] == msg["message"]
    assert "X-Title" in body
    assert body["X-Title"] == quote(msg["title"])  # ntfy URL-decodes header values
    assert "X-Priority" in body
    assert "X-Tags" in body
    assert isinstance(body["X-Tags"], str)  # comma-separated, not a list


# ── send_notification — slack formatting ─────────────────────────────────────


@pytest.mark.asyncio
async def test_send_slack_payload_has_text_field() -> None:
    calls: list[tuple[str, dict[str, object]]] = []

    async def fake_post(url: str, payload: dict[str, object]) -> None:
        calls.append((url, payload))

    msg = build_run_payload(_result(given=3, total=10))
    await send_notification(
        "https://hooks.slack.com/services/T00/B00/xxx", msg, system="slack", post_fn=fake_post
    )
    body = calls[0][1]
    assert "text" in body
    assert isinstance(body["text"], str)
    assert msg["title"] in str(body["text"])


# ── send_notification — discord formatting ────────────────────────────────────


@pytest.mark.asyncio
async def test_send_discord_payload_has_embeds() -> None:
    calls: list[tuple[str, dict[str, object]]] = []

    async def fake_post(url: str, payload: dict[str, object]) -> None:
        calls.append((url, payload))

    msg = build_run_payload(_result(given=2, total=8))
    await send_notification(
        "https://discord.com/api/webhooks/123/token", msg, system="discord", post_fn=fake_post
    )
    body = calls[0][1]
    assert "embeds" in body
    embed = body["embeds"][0]  # type: ignore[index]
    assert "title" in embed
    assert "description" in embed
    assert "color" in embed


@pytest.mark.asyncio
async def test_send_discord_auth_error_uses_red_color() -> None:
    calls: list[tuple[str, dict[str, object]]] = []

    async def fake_post(url: str, payload: dict[str, object]) -> None:
        calls.append((url, payload))

    msg = build_auth_error_payload(AuthError("expired"))
    await send_notification(
        "https://discord.com/api/webhooks/123/token", msg, system="discord", post_fn=fake_post
    )
    embed = calls[0][1]["embeds"][0]  # type: ignore[index]
    assert embed["color"] == 0xDC2626  # red


# ── send_notification — gotify formatting ─────────────────────────────────────


@pytest.mark.asyncio
async def test_send_gotify_payload_has_required_fields() -> None:
    calls: list[tuple[str, dict[str, object]]] = []

    async def fake_post(url: str, payload: dict[str, object]) -> None:
        calls.append((url, payload))

    msg = build_run_payload(_result(given=1, total=5))
    await send_notification(
        "https://gotify.example.com/message?token=abc", msg, system="gotify", post_fn=fake_post
    )
    body = calls[0][1]
    assert "title" in body
    assert "message" in body
    assert "priority" in body


# ── send_notification — generic ───────────────────────────────────────────────


@pytest.mark.asyncio
async def test_send_generic_includes_structured_data() -> None:
    calls: list[tuple[str, dict[str, object]]] = []

    async def fake_post(url: str, payload: dict[str, object]) -> None:
        calls.append((url, payload))

    msg = build_run_payload(_result(given=5, total=12))
    await send_notification(
        "https://hooks.example.com/kudosy", msg, system="generic", post_fn=fake_post
    )
    body = calls[0][1]
    assert "title" in body
    assert "message" in body
    assert body["event"] == "run_complete"
    assert body["given"] == 5


# ── send_notification — general behaviour ────────────────────────────────────


@pytest.mark.asyncio
async def test_send_notification_empty_url_is_noop() -> None:
    calls: list[str] = []

    async def fake_post(url: str, payload: dict[str, object]) -> None:
        calls.append(url)

    await send_notification("", {"title": "x", "message": "y"}, post_fn=fake_post)
    assert calls == []


@pytest.mark.asyncio
async def test_send_notification_swallows_post_errors() -> None:
    async def bad_post(url: str, payload: dict[str, object]) -> None:
        raise RuntimeError("network error")

    await send_notification(
        "https://ntfy.sh/test", {"title": "x", "message": "y"}, post_fn=bad_post
    )


# ── AppSettings notify fields ─────────────────────────────────────────────────


def test_appsettings_notify_defaults() -> None:
    s = AppSettings()
    assert s.notifyWebhookUrl == ""
    assert s.notifyOnRun is False
    assert s.notifyOnAuthError is True
    assert s.notifySystem == "generic"


def test_appsettings_notify_system_valid_values() -> None:
    for system in ("ntfy", "slack", "discord", "gotify", "generic"):
        s = AppSettings(notifySystem=system)
        assert s.notifySystem == system


def test_appsettings_notify_system_invalid_raises() -> None:
    import pydantic

    with pytest.raises(pydantic.ValidationError):
        AppSettings(notifySystem="telegram")


def test_appsettings_notify_url_valid_https() -> None:
    s = AppSettings(notifyWebhookUrl="https://ntfy.sh/my-topic")
    assert s.notifyWebhookUrl == "https://ntfy.sh/my-topic"


def test_appsettings_notify_url_valid_http() -> None:
    s = AppSettings(notifyWebhookUrl="http://localhost:8080/hook")
    assert s.notifyWebhookUrl == "http://localhost:8080/hook"


def test_appsettings_notify_url_empty_ok() -> None:
    s = AppSettings(notifyWebhookUrl="")
    assert s.notifyWebhookUrl == ""


def test_appsettings_notify_url_invalid_raises() -> None:
    import pydantic

    with pytest.raises(pydantic.ValidationError):
        AppSettings(notifyWebhookUrl="not-a-url")
