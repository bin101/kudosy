"""Runtime environment settings via pydantic-settings.

All values can be overridden with environment variables (prefix KUDOSY_).
"""

from __future__ import annotations

from pydantic_settings import BaseSettings, SettingsConfigDict


class KudosySettings(BaseSettings):
    """Top-level environment configuration for Kudosy."""

    model_config = SettingsConfigDict(
        env_prefix="KUDOSY_",
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    data_dir: str = "/data"
    port: int = 8080
    log_level: str = "INFO"
    host: str = "0.0.0.0"


# Singleton loaded at import time — override in tests via env var KUDOSY_DATA_DIR
_settings: KudosySettings | None = None


def get_settings() -> KudosySettings:
    global _settings
    if _settings is None:
        _settings = KudosySettings()
    return _settings
