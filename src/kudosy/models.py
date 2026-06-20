"""Pydantic v2 data models — single source of truth for all data shapes."""

from __future__ import annotations

from datetime import datetime
from enum import StrEnum
from typing import Any

from pydantic import BaseModel, field_validator, model_validator

# ── Config models ─────────────────────────────────────────────────────────────


class KudoRules(BaseModel):
    """Kudos filter rules for a config layer (user or defaults)."""

    minDistance: dict[str, float] = {}
    minTime: dict[str, float] = {}
    activityNames: list[str] = []


class CatchAll(BaseModel):
    """Default thresholds applied to all sport types when no explicit rule exists."""

    minDistance: float = 0.0
    minTime: float = 0.0


class Defaults(BaseModel):
    """Contents of defaults.yaml."""

    catchAll: CatchAll = CatchAll()
    kudoRules: KudoRules = KudoRules()


class UserConfig(BaseModel):
    """Contents of config.yaml — user-specific Strava config."""

    stravaSessionCookie: str = ""
    athleteId: str = ""
    ignoreAthletes: list[str] = []
    kudoRules: KudoRules = KudoRules()

    @field_validator("athleteId", mode="before")
    @classmethod
    def coerce_athlete_id(cls, v: Any) -> str:
        return str(v) if v is not None else ""

    @field_validator("ignoreAthletes", mode="before")
    @classmethod
    def coerce_ignore_athletes(cls, v: Any) -> list[str]:
        if not isinstance(v, list):
            return []
        return [str(item) for item in v]


class AppSettings(BaseModel):
    """Contents of settings.json — scheduler and behavior settings."""

    schedulerEnabled: bool = True
    intervalMinutes: int = 60
    dryRun: bool = False
    # Human-like timing
    jitterMinutes: float = 15.0
    minKudosDelaySeconds: float = 3.0
    maxKudosDelaySeconds: float = 25.0
    shuffleOrder: bool = True

    @field_validator("intervalMinutes", mode="before")
    @classmethod
    def min_interval(cls, v: Any) -> int:
        return max(5, int(v))

    @model_validator(mode="after")
    def validate_delay_range(self) -> AppSettings:
        if self.maxKudosDelaySeconds < self.minKudosDelaySeconds:
            raise ValueError(
                f"maxKudosDelaySeconds ({self.maxKudosDelaySeconds}) must be ≥ "
                f"minKudosDelaySeconds ({self.minKudosDelaySeconds})"
            )
        return self


# ── Effective (merged) config ─────────────────────────────────────────────────


class EffectiveConfig(BaseModel):
    """The merged config handed to the engine."""

    stravaSessionCookie: str
    athleteId: str
    ignoreAthletes: list[str]
    kudoRules: KudoRules


# ── Activity & Decision ───────────────────────────────────────────────────────


class Activity(BaseModel):
    """A single activity entry parsed from the Strava feed."""

    athlete_name: str
    athlete_id: str
    activity_id: str
    activity_name: str
    sport_type: str
    has_kudoed: bool
    stats: dict[str, str]  # raw label→value map, e.g. {"Distance": "30.10 km"}


class DecisionReason(StrEnum):
    """Why the engine decided to give or skip kudos for an activity."""

    IGNORE = "ignore"  # athlete in ignore list
    ALREADY = "already"  # already kudoed
    CRITERIA = "criteria"  # below minDistance/minTime threshold
    NAME_MATCH = "name_match"  # activity name matched a regex → always give
    DEFAULT = "default"  # no rule matched → give kudos


class Decision(BaseModel):
    """The outcome of decide(activity, effective_config)."""

    give_kudos: bool
    reason: DecisionReason


# ── Run result ────────────────────────────────────────────────────────────────


class FeedActivity(BaseModel):
    """A feed activity enriched with the engine's decision, for GET /api/feed."""

    athlete_name: str
    athlete_id: str
    activity_id: str
    activity_name: str
    sport_type: str
    has_kudoed: bool
    stats: dict[str, str]
    give_kudos: bool
    reason: str  # DecisionReason value, e.g. "already", "default", "criteria"


class RunResult(BaseModel):
    """Structured result returned by engine.run_kudos()."""

    started_at: datetime
    finished_at: datetime
    success: bool
    dry_run: bool
    total: int  # total activities scanned
    would_give: int  # number that would receive kudos (dry-run count)
    given: int  # actually sent (0 in dry-run)
    error: str | None = None
    newly_kudoed: list[str] = []  # activity_ids successfully kudoed this run
    skipped_cached: int = 0  # activities skipped because already in cache


class RunStatus(BaseModel):
    """Response shape for GET /api/status."""

    running: bool
    lastRun: RunResult | None = None
    nextRunAt: datetime | None = None
    schedulerEnabled: bool
    intervalMinutes: int
    version: str
