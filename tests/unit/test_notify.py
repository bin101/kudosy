"""Unit tests for kudosy.notify (webhook notifications, TDD)."""

from __future__ import annotations

import datetime

import pytest

from kudosy.feed import AuthError
from kudosy.models import AppSettings, RunResult


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


# ── build_run_payload ─────────────────────────────────────────────────────────


def test_build_run_payload_live_run() -> None:
    from kudosy.notify import build_run_payload

    result = _result(given=5, total=12, dry_run=False)
    payload = build_run_payload(result)
    assert payload["event"] == "run_complete"
    assert payload["given"] == 5
    assert payload["total"] == 12
    assert payload["dry_run"] is False
    assert "started_at" in payload


def test_build_run_payload_dry_run() -> None:
    from kudosy.notify import build_run_payload

    result = _result(given=0, would_give=4, dry_run=True)
    payload = build_run_payload(result)
    assert payload["dry_run"] is True
    assert payload["would_give"] == 4
    assert payload["given"] == 0


def test_build_run_payload_failed_run() -> None:
    from kudosy.notify import build_run_payload

    result = _result(success=False, error="timeout", given=0, total=0, would_give=0)
    payload = build_run_payload(result)
    assert payload["success"] is False
    assert payload["error"] == "timeout"


# ── build_auth_error_payload ──────────────────────────────────────────────────


def test_build_auth_error_payload_event_field() -> None:
    from kudosy.notify import build_auth_error_payload

    exc = AuthError("Cookie abgelaufen")
    payload = build_auth_error_payload(exc)
    assert payload["event"] == "auth_error"


def test_build_auth_error_payload_message_contains_exc() -> None:
    from kudosy.notify import build_auth_error_payload

    exc = AuthError("Session expired")
    payload = build_auth_error_payload(exc)
    assert "Session expired" in payload["message"]


# ── send_notification ─────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_send_notification_calls_post_fn() -> None:
    from kudosy.notify import send_notification

    calls: list[tuple[str, dict[str, object]]] = []

    async def fake_post(url: str, payload: dict[str, object]) -> None:
        calls.append((url, payload))

    await send_notification("https://ntfy.example.com/kudosy", {"event": "test"}, post_fn=fake_post)
    assert len(calls) == 1
    assert calls[0][0] == "https://ntfy.example.com/kudosy"
    assert calls[0][1] == {"event": "test"}


@pytest.mark.asyncio
async def test_send_notification_empty_url_is_noop() -> None:
    from kudosy.notify import send_notification

    calls: list[str] = []

    async def fake_post(url: str, payload: dict[str, object]) -> None:
        calls.append(url)

    await send_notification("", {"event": "test"}, post_fn=fake_post)
    assert calls == []


@pytest.mark.asyncio
async def test_send_notification_swallows_post_errors() -> None:
    """A failing webhook must never crash the application."""
    from kudosy.notify import send_notification

    async def bad_post(url: str, payload: dict[str, object]) -> None:
        raise RuntimeError("network error")

    # Must not raise
    await send_notification("https://example.com/hook", {}, post_fn=bad_post)


# ── AppSettings notify fields ─────────────────────────────────────────────────


def test_appsettings_notify_defaults() -> None:
    s = AppSettings()
    assert s.notifyWebhookUrl == ""
    assert s.notifyOnRun is False
    assert s.notifyOnAuthError is True


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
