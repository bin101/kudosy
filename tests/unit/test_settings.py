"""Unit tests for kudosy.settings (env-driven runtime config)."""

from __future__ import annotations

import pytest

from kudosy.settings import KudosySettings


def test_default_host_is_loopback_only(monkeypatch: pytest.MonkeyPatch) -> None:
    """Loopback-only by default: there is no auth in front of the API unless
    KUDOSY_AUTH_PASSWORD is set, so binding to all interfaces must be an
    explicit opt-in (KUDOSY_HOST=0.0.0.0), not the out-of-the-box default.
    The Docker image overrides this via ENV KUDOSY_HOST=0.0.0.0 in the Dockerfile.
    """
    monkeypatch.delenv("KUDOSY_HOST", raising=False)
    assert KudosySettings().host == "127.0.0.1"


def test_host_can_be_overridden_via_env(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("KUDOSY_HOST", "0.0.0.0")
    assert KudosySettings().host == "0.0.0.0"
