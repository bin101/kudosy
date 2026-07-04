"""Logging configuration — stdout + /data/last-run.log + SSE broadcast handler."""

from __future__ import annotations

import asyncio
import contextlib
import logging
import sys
from pathlib import Path
from typing import Final

# Sentinel pushed into subscriber queues when the log is truncated for a new
# run — tells SSE clients to clear their view.
RESET: Final = object()


class BroadcastHandler(logging.Handler):
    """Fan out formatted log lines to per-subscriber asyncio queues.

    Feeds ``GET /api/log/stream``. Everything runs on the single event loop
    (uvicorn + AsyncIOScheduler), so ``put_nowait`` needs no locking. A full
    queue (stuck client) drops lines silently rather than blocking logging.
    """

    def __init__(self, *, queue_size: int = 1000) -> None:
        super().__init__()
        self._queue_size = queue_size
        self._queues: set[asyncio.Queue[object]] = set()

    def subscribe(self) -> asyncio.Queue[object]:
        q: asyncio.Queue[object] = asyncio.Queue(maxsize=self._queue_size)
        self._queues.add(q)
        return q

    def unsubscribe(self, q: asyncio.Queue[object]) -> None:
        self._queues.discard(q)

    def broadcast_reset(self) -> None:
        self._put_all(RESET)

    def emit(self, record: logging.LogRecord) -> None:
        if not self._queues:
            return
        try:
            msg = self.format(record)
        except Exception:  # pragma: no cover - format errors must never propagate
            return
        self._put_all(msg)

    def _put_all(self, item: object) -> None:
        for q in list(self._queues):
            # A full queue (slow subscriber) drops the line rather than block logging.
            with contextlib.suppress(asyncio.QueueFull):
                q.put_nowait(item)


_broadcast = BroadcastHandler()


def get_broadcast_handler() -> BroadcastHandler:
    return _broadcast


def configure_logging(
    level: str = "INFO",
    log_file: Path | None = None,
) -> None:
    """Set up root logger: stdout + optional per-run file handler."""
    fmt = "%(asctime)s %(levelname)-8s %(name)s: %(message)s"
    date_fmt = "%Y-%m-%dT%H:%M:%S"

    handlers: list[logging.Handler] = [
        logging.StreamHandler(sys.stdout),
    ]
    if log_file is not None:
        fh = logging.FileHandler(log_file, mode="a", encoding="utf-8")
        fh.setFormatter(logging.Formatter(fmt, datefmt=date_fmt))
        handlers.append(fh)
    # SSE live-log fan-out (singleton — survives reconfiguration)
    _broadcast.setFormatter(logging.Formatter(fmt, datefmt=date_fmt))
    handlers.append(_broadcast)

    logging.basicConfig(
        level=getattr(logging, level.upper(), logging.INFO),
        format=fmt,
        datefmt=date_fmt,
        handlers=handlers,
        force=True,
    )
    # Quiet noisy libraries
    for noisy in ("httpx", "httpcore", "uvicorn.access"):
        logging.getLogger(noisy).setLevel(logging.WARNING)


def reset_log_handler(log_file: Path) -> None:
    """Truncate and reopen the log file for a new run (keeps existing handlers)."""
    log_file.write_text("", encoding="utf-8")  # truncate
    _broadcast.broadcast_reset()  # tell SSE clients to clear their view
    # Re-attach file handler
    root = logging.getLogger()
    # Remove any existing FileHandlers for this path
    for h in list(root.handlers):
        if isinstance(h, logging.FileHandler) and Path(h.baseFilename) == log_file.resolve():
            root.removeHandler(h)
            h.close()
    fh = logging.FileHandler(log_file, mode="a", encoding="utf-8")
    fh.setFormatter(root.handlers[0].formatter)
    root.addHandler(fh)
