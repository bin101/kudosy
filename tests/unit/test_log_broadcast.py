"""Unit tests for the BroadcastHandler that feeds the SSE log stream."""

from __future__ import annotations

import logging
from pathlib import Path

import pytest

from kudosy.logging_conf import RESET, BroadcastHandler, reset_log_handler

# ── BroadcastHandler ──────────────────────────────────────────────────────────


def make_record(msg: str) -> logging.LogRecord:
    return logging.LogRecord(
        name="kudosy.test",
        level=logging.INFO,
        pathname=__file__,
        lineno=1,
        msg=msg,
        args=(),
        exc_info=None,
    )


@pytest.mark.asyncio
async def test_emit_delivers_formatted_line_to_subscribers() -> None:
    handler = BroadcastHandler()
    handler.setFormatter(logging.Formatter("%(levelname)s %(message)s"))
    q = handler.subscribe()

    handler.emit(make_record("hello"))

    assert await q.get() == "INFO hello"


@pytest.mark.asyncio
async def test_unsubscribed_queue_receives_nothing() -> None:
    handler = BroadcastHandler()
    q = handler.subscribe()
    handler.unsubscribe(q)

    handler.emit(make_record("dropped"))

    assert q.empty()


@pytest.mark.asyncio
async def test_multiple_subscribers_each_get_the_line() -> None:
    handler = BroadcastHandler()
    q1 = handler.subscribe()
    q2 = handler.subscribe()

    handler.emit(make_record("fan-out"))

    assert (await q1.get()).endswith("fan-out")
    assert (await q2.get()).endswith("fan-out")


@pytest.mark.asyncio
async def test_full_queue_does_not_raise() -> None:
    handler = BroadcastHandler()
    q = handler.subscribe()
    # Saturate the queue far beyond any sane maxsize
    for i in range(5000):
        handler.emit(make_record(f"line {i}"))
    # emit() must never raise on a slow/stuck subscriber
    assert q.qsize() > 0


@pytest.mark.asyncio
async def test_broadcast_reset_sends_sentinel() -> None:
    handler = BroadcastHandler()
    q = handler.subscribe()

    handler.broadcast_reset()

    assert await q.get() is RESET


# ── reset_log_handler integration ─────────────────────────────────────────────


@pytest.mark.asyncio
async def test_reset_log_handler_broadcasts_reset(tmp_path: Path) -> None:
    """Truncating the log for a new run must tell SSE subscribers to clear."""
    from kudosy.logging_conf import configure_logging, get_broadcast_handler

    root = logging.getLogger()
    saved_handlers = root.handlers[:]
    saved_level = root.level

    log_file = tmp_path / "last-run.log"
    log_file.write_text("old content", encoding="utf-8")
    q = get_broadcast_handler().subscribe()
    try:
        configure_logging("INFO", log_file)

        reset_log_handler(log_file)

        assert await q.get() is RESET
        assert log_file.read_text(encoding="utf-8") == ""
    finally:
        get_broadcast_handler().unsubscribe(q)
        # Restore pytest's root logger state (configure_logging uses force=True)
        for h in root.handlers[:]:
            if h not in saved_handlers:
                root.removeHandler(h)
                h.close()
        for h in saved_handlers:
            if h not in root.handlers:
                root.addHandler(h)
        root.setLevel(saved_level)
