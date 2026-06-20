"""Shared pytest fixtures for all test levels.

Key design:
- Each test that touches the store gets its own tmp dir via `data_dir` fixture.
- The KUDOSY_DATA_DIR env var is monkeypatched so store._data_dir() is redirected.
- settings module cache is cleared after each test.
"""

from __future__ import annotations

from collections.abc import Generator
from pathlib import Path

import pytest


@pytest.fixture()
def data_dir(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Generator[Path]:
    """Redirect all store I/O to a temporary directory for test isolation."""
    d = tmp_path / "data"
    d.mkdir()
    monkeypatch.setenv("KUDOSY_DATA_DIR", str(d))

    # Clear the pydantic-settings singleton so it re-reads from env
    import kudosy.settings as settings_mod

    settings_mod._settings = None  # type: ignore[attr-defined]

    yield d

    # Teardown: clear singleton again
    settings_mod._settings = None  # type: ignore[attr-defined]
