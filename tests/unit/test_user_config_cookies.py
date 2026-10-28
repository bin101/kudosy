"""UserConfig.stravaCookies and the migration from the legacy single-cookie field."""

from __future__ import annotations

from kudosy.models import UserConfig


def test_legacy_session_cookie_is_migrated() -> None:
    cfg = UserConfig.model_validate({"stravaSessionCookie": "old-value", "athleteId": "1"})
    assert cfg.stravaCookies == {"_strava4_session": "old-value"}
    assert "stravaSessionCookie" not in cfg.model_dump()


def test_legacy_empty_session_cookie_gives_no_cookies() -> None:
    assert UserConfig.model_validate({"stravaSessionCookie": ""}).stravaCookies == {}


def test_new_field_wins_over_legacy() -> None:
    cfg = UserConfig.model_validate(
        {"stravaSessionCookie": "old", "stravaCookies": {"_strava4_session": "new"}}
    )
    assert cfg.stravaCookies == {"_strava4_session": "new"}


def test_default_is_empty() -> None:
    assert UserConfig().stravaCookies == {}
