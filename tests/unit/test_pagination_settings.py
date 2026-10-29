"""AppSettings feed pagination fields: defaults, clamping, validation, legacy files."""

from __future__ import annotations

import pytest

from kudosy.models import AppSettings


def test_defaults_keep_current_behaviour() -> None:
    s = AppSettings()
    assert s.feedPaginationMode == "count"
    assert s.feedPaginationTarget == 100


def test_legacy_settings_without_new_fields_load() -> None:
    s = AppSettings.model_validate({"intervalMinutes": 30, "dryRun": False})
    assert (s.feedPaginationMode, s.feedPaginationTarget) == ("count", 100)


@pytest.mark.parametrize(
    ("raw", "expected"), [(5, 20), (20, 20), (250, 250), (9999, 500), ("60", 60)]
)
def test_target_is_clamped(raw: object, expected: int) -> None:
    assert AppSettings(feedPaginationTarget=raw).feedPaginationTarget == expected  # type: ignore[arg-type]


def test_mode_accepts_known_values() -> None:
    assert AppSettings(feedPaginationMode="untilKnown").feedPaginationMode == "untilKnown"


@pytest.mark.parametrize("raw", [None, "abc", "", [], {}])
def test_invalid_target_falls_back_to_default(raw: object) -> None:
    assert AppSettings(feedPaginationTarget=raw).feedPaginationTarget == 100  # type: ignore[arg-type]


@pytest.mark.parametrize("raw", [None, "", "bogus", 5])
def test_invalid_mode_falls_back_to_default(raw: object) -> None:
    assert AppSettings(feedPaginationMode=raw).feedPaginationMode == "count"  # type: ignore[arg-type]
