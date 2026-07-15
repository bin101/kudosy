"""Unit tests for kudosy.notify (webhook notifications, TDD)."""

from __future__ import annotations

import datetime

import pytest

from kudosy.feed import AuthError
from kudosy.models import AppSettings, RunResult
from kudosy.notify import (
    build_auth_error_payload,
    build_digest_payload,
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
    assert body["X-Title"] == msg["title"]
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


# ── build_digest_payload ──────────────────────────────────────────────────────

_NOW = datetime.datetime(2026, 7, 2, 20, 0, tzinfo=datetime.UTC)
_SINCE = datetime.datetime(2026, 7, 1, 20, 0, tzinfo=datetime.UTC)


def _entry(**overrides: object) -> dict[str, object]:
    base: dict[str, object] = {
        "started_at": "2026-07-02T10:00:00+00:00",
        "finished_at": "2026-07-02T10:01:00+00:00",
        "dry_run": False,
        "total": 5,
        "would_give": 2,
        "given": 2,
        "success": True,
    }
    base.update(overrides)
    return base


def test_build_digest_payload_has_required_keys() -> None:
    payload = build_digest_payload([_entry()], since=_SINCE, until=_NOW)
    for key in ("event", "title", "message", "tags", "priority"):
        assert key in payload, f"missing key: {key}"


def test_build_digest_payload_event_type() -> None:
    payload = build_digest_payload([_entry()], since=_SINCE, until=_NOW)
    assert payload["event"] == "daily_digest"


def test_build_digest_payload_aggregates_live_given() -> None:
    entries = [_entry(given=3, total=10), _entry(given=5, total=8)]
    payload = build_digest_payload(entries, since=_SINCE, until=_NOW)
    assert payload["given"] == 8
    assert payload["total"] == 18
    assert payload["runs"] == 2


def test_build_digest_payload_aggregates_dry_run_would_give() -> None:
    entries = [
        _entry(dry_run=True, would_give=4, given=0, total=10),
        _entry(dry_run=True, would_give=6, given=0, total=12),
    ]
    payload = build_digest_payload(entries, since=_SINCE, until=_NOW)
    assert payload["would_give"] == 10
    assert payload["given"] == 0


def test_build_digest_payload_dedupes_activities_scanned_across_runs() -> None:
    """Same activity stays in the feed across two runs — must count once, not twice."""
    entries = [
        _entry(activity_ids=["a1", "a2", "a3"], total=3),
        _entry(activity_ids=["a2", "a3", "a4"], total=3),
    ]
    payload = build_digest_payload(entries, since=_SINCE, until=_NOW)
    assert payload["total"] == 4  # a1, a2, a3, a4 — not 6


def test_build_digest_payload_dedupes_would_give_across_dry_runs() -> None:
    """A still-eligible activity reappears in every dry run until it's given kudos."""
    entries = [
        _entry(dry_run=True, would_give_ids=["a1", "a2"], would_give=2, given=0),
        _entry(dry_run=True, would_give_ids=["a2"], would_give=1, given=0),
    ]
    payload = build_digest_payload(entries, since=_SINCE, until=_NOW)
    assert payload["would_give"] == 2  # a1, a2 — not 3


def test_build_digest_payload_dedupes_given_ids() -> None:
    entries = [
        _entry(given_ids=["a1"], given=1),
        _entry(given_ids=["a1", "a2"], given=2),
    ]
    payload = build_digest_payload(entries, since=_SINCE, until=_NOW)
    assert payload["given"] == 2  # a1, a2 — not 3


def test_build_digest_payload_falls_back_to_raw_count_without_id_lists() -> None:
    """Entries written before the *_ids fields existed still aggregate correctly."""
    entries = [_entry(total=10, given=3), _entry(total=8, given=5)]
    payload = build_digest_payload(entries, since=_SINCE, until=_NOW)
    assert payload["total"] == 18
    assert payload["given"] == 8


def test_build_digest_payload_counts_failed_runs() -> None:
    entries = [_entry(success=True), _entry(success=False), _entry(success=False)]
    payload = build_digest_payload(entries, since=_SINCE, until=_NOW)
    assert payload["failed"] == 2


def test_build_digest_payload_zero_entries_sends_empty_message() -> None:
    payload = build_digest_payload([], since=_SINCE, until=_NOW)
    assert payload["runs"] == 0
    assert payload["given"] == 0
    assert "message" in payload
    assert len(payload["message"]) > 0  # non-empty string


def test_build_digest_payload_includes_since_until() -> None:
    payload = build_digest_payload([_entry()], since=_SINCE, until=_NOW)
    assert payload["since"] == _SINCE.isoformat()
    assert payload["until"] == _NOW.isoformat()


def test_build_digest_payload_since_none_allowed() -> None:
    """since=None means 'first ever digest — include everything'."""
    payload = build_digest_payload([_entry()], since=None, until=_NOW)
    assert payload["since"] is None


def test_build_digest_payload_excludes_activities_seen_before_window() -> None:
    """An activity already counted in an earlier digest must not be counted again."""
    previous = [_entry(started_at="2026-07-01T10:00:00+00:00", activity_ids=["a1", "a2"], total=2)]
    entries = [_entry(activity_ids=["a2", "a3"], total=2)]
    payload = build_digest_payload(entries, since=_SINCE, until=_NOW, previous_entries=previous)
    assert payload["total"] == 1  # only a3 is new


def test_build_digest_payload_excludes_would_give_seen_before_window() -> None:
    """A still-eligible dry-run activity from before the window is not re-counted."""
    previous = [
        _entry(
            started_at="2026-07-01T10:00:00+00:00",
            dry_run=True,
            would_give_ids=["a1"],
            would_give=1,
            given=0,
        )
    ]
    entries = [_entry(dry_run=True, would_give_ids=["a1", "a2"], would_give=2, given=0)]
    payload = build_digest_payload(entries, since=_SINCE, until=_NOW, previous_entries=previous)
    assert payload["would_give"] == 1  # only a2 is new


def test_build_digest_payload_excludes_given_seen_before_window() -> None:
    previous = [_entry(started_at="2026-07-01T10:00:00+00:00", given_ids=["a1"], given=1)]
    entries = [_entry(given_ids=["a1", "a2"], given=2)]
    payload = build_digest_payload(entries, since=_SINCE, until=_NOW, previous_entries=previous)
    assert payload["given"] == 1  # only a2 is new


def test_build_digest_payload_previous_entries_default_empty() -> None:
    """Without previous_entries the behaviour is unchanged (backwards compatible)."""
    entries = [_entry(activity_ids=["a1", "a2"], total=2)]
    payload = build_digest_payload(entries, since=_SINCE, until=_NOW)
    assert payload["total"] == 2


def test_build_digest_payload_legacy_entries_unaffected_by_previous() -> None:
    """Entries without id lists keep their raw counts — no exclusion possible."""
    previous = [_entry(started_at="2026-07-01T10:00:00+00:00", activity_ids=["a1"], total=1)]
    entries = [_entry(total=5)]  # legacy entry, no activity_ids
    payload = build_digest_payload(entries, since=_SINCE, until=_NOW, previous_entries=previous)
    assert payload["total"] == 5


def test_build_digest_payload_previous_legacy_entries_exclude_nothing() -> None:
    """Previous entries without id lists cannot exclude anything."""
    previous = [_entry(started_at="2026-07-01T10:00:00+00:00", total=3)]  # legacy, no ids
    entries = [_entry(activity_ids=["a1", "a2"], total=2)]
    payload = build_digest_payload(entries, since=_SINCE, until=_NOW, previous_entries=previous)
    assert payload["total"] == 2


def test_build_digest_payload_generic_formatter_passes_extra_keys() -> None:
    """_format_generic must include digest-specific keys (runs, failed, since, until)."""
    from kudosy.notify import _format_generic

    payload = build_digest_payload([_entry()], since=_SINCE, until=_NOW)
    formatted = _format_generic(payload)
    for key in ("runs", "failed", "since", "until"):
        assert key in formatted, f"_format_generic must pass through '{key}'"


# ── AppSettings daily digest fields ──────────────────────────────────────────


def test_appsettings_daily_digest_defaults() -> None:
    s = AppSettings()
    assert s.notifyDailyDigest is False
    assert s.notifyDailyDigestTime == "20:00"


def test_appsettings_daily_digest_time_valid() -> None:
    for t in ("00:00", "08:30", "23:59"):
        s = AppSettings(notifyDailyDigestTime=t)
        assert s.notifyDailyDigestTime == t


def test_appsettings_daily_digest_time_invalid_hour_raises() -> None:
    import pydantic

    with pytest.raises(pydantic.ValidationError):
        AppSettings(notifyDailyDigestTime="25:00")


def test_appsettings_daily_digest_time_invalid_format_raises() -> None:
    import pydantic

    with pytest.raises(pydantic.ValidationError):
        AppSettings(notifyDailyDigestTime="abc")


def test_appsettings_daily_digest_time_empty_uses_default() -> None:
    s = AppSettings(notifyDailyDigestTime="")
    assert s.notifyDailyDigestTime == "20:00"
