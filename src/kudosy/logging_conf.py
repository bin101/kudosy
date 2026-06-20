"""Logging configuration — stdout + optional /data/last-run.log file handler."""

from __future__ import annotations

import logging
import sys
from pathlib import Path


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
