"""Pydantic v2 data models — single source of truth for all data shapes."""

from __future__ import annotations

from datetime import datetime
from enum import StrEnum
from typing import Any

from pydantic import BaseModel, Field, field_validator, model_validator

# ── Activity stats ─────────────────────────────────────────────────────────────


class StatValue(BaseModel):
    """A single parsed stat entry from the Strava activity feed."""

    key: str
    """Canonical key: "distance" | "time" | "elevation_gain" | "pace" | "swim_pace" | "carbon_saved" | "unknown"."""  # noqa: E501

    label: str
    """Display label as provided by Strava (e.g. "Elev Gain", "Pace")."""

    raw: str
    """Cleaned display string with HTML markup stripped (e.g. "116 m", "8:06 /km")."""

    value: float | None = None
    """Normalised numeric value in the canonical unit (see ``unit``)."""

    unit: str | None = None
    """Canonical unit: "m" (metres/seconds), "s" (seconds), "s/km", "s/100m"."""


class ActivityStats(BaseModel):
    """Typed, normalised stats for one activity from the following feed.

    The feed provides at most 3 headline stats per activity; which ones depend
    on the sport type (e.g. Run → distance/pace/time, Ride → distance/elev/time).

    All fields are optional because not every sport produces every stat.
    Numeric values are in SI/canonical units (metres, seconds, seconds-per-km …).
    The ``display`` list preserves the original order and labels for UI rendering.
    Unknown stat types land in ``extra`` as label→raw-string pairs.
    """

    distance_m: float | None = None
    """Total distance in metres."""

    moving_time_s: int | None = None
    """Moving time in seconds (from the "Time" stat)."""

    elapsed_time_s: int | None = None
    """Elapsed/total time in seconds (from activity.elapsedTime — always a clean int)."""

    elevation_gain_m: float | None = None
    """Elevation gain in metres."""

    pace_s_per_km: float | None = None
    """Average pace in seconds per kilometre (Run/TrailRun/Walk)."""

    pace_s_per_100m: float | None = None
    """Average pace in seconds per 100 m (Swim)."""

    extra: dict[str, str] = {}
    """Unclassified stats (label → cleaned raw string), preserved for transparency."""

    display: list[StatValue] = []
    """Stats in the order Strava presented them — use this for UI rendering."""


# ── Config models ─────────────────────────────────────────────────────────────


class KudoRules(BaseModel):
    """Kudos filter rules for a config layer (user or defaults)."""

    minDistance: dict[str, float] = {}
    minTime: dict[str, float] = {}
    # Category-level rules: keyed by category name (e.g. "FootSports").
    # On the user layer these hold the user's category settings; on the
    # effective layer they are always empty (already expanded into the
    # flat per-sport dicts by build_effective_config).
    categoryMinDistance: dict[str, float] = {}
    categoryMinTime: dict[str, float] = {}
    activityNames: list[str] = []


class CatchAll(BaseModel):
    """Default thresholds applied to all sport types when no explicit rule exists."""

    minDistance: float = 0.0
    minTime: float = 0.0


class UserConfig(BaseModel):
    """Contents of config.yaml — user-specific Strava config."""

    stravaSessionCookie: str = ""
    athleteId: str = ""
    ignoreAthletes: list[str] = []
    allowAthletes: list[str] = []
    catchAll: CatchAll = CatchAll()
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

    @field_validator("allowAthletes", mode="before")
    @classmethod
    def coerce_allow_athletes(cls, v: Any) -> list[str]:
        if not isinstance(v, list):
            return []
        return [str(item) for item in v]


def _default_schedule_matrix() -> list[list[bool]]:
    """7 rows (Mon-Sun) x 24 columns (hours), all True = always allowed."""
    return [[True] * 24 for _ in range(7)]


class AppSettings(BaseModel):
    """Contents of settings.json — scheduler and behavior settings."""

    schedulerEnabled: bool = True
    intervalMinutes: int = 60
    dryRun: bool = True
    # Human-like timing
    jitterMinutes: float = 15.0
    minKudosDelaySeconds: float = 3.0
    maxKudosDelaySeconds: float = 25.0
    shuffleOrder: bool = True
    # Quiet-hours matrix — kudos are only given during allowed time slots
    timezone: str = "Europe/Berlin"
    kudosScheduleEnabled: bool = False
    kudosScheduleMatrix: list[list[bool]] = Field(default_factory=_default_schedule_matrix)
    # Webhook notifications
    notifyWebhookUrl: str = ""
    notifyOnRun: bool = False
    notifyOnAuthError: bool = True

    @field_validator("intervalMinutes", mode="before")
    @classmethod
    def min_interval(cls, v: Any) -> int:
        return max(5, int(v))

    @field_validator("timezone", mode="before")
    @classmethod
    def validate_timezone(cls, v: Any) -> str:
        from kudosy.quiet_hours import is_valid_timezone

        name = str(v) if v else "Europe/Berlin"
        if not is_valid_timezone(name):
            raise ValueError(f"Unknown timezone: {name!r}")
        return name

    @field_validator("notifyWebhookUrl", mode="before")
    @classmethod
    def validate_webhook_url(cls, v: Any) -> str:
        url = str(v or "")
        if url and not (url.startswith("http://") or url.startswith("https://")):
            raise ValueError(f"notifyWebhookUrl must be an http/https URL or empty, got: {url!r}")
        return url

    @field_validator("kudosScheduleMatrix", mode="before")
    @classmethod
    def normalise_matrix(cls, v: Any) -> list[list[bool]]:
        """Ensure the matrix is always 7 rows x 24 columns.

        Missing rows or columns are filled with True (allowed) so that a
        partial config from an older settings.json never blocks the scheduler.
        """
        default = _default_schedule_matrix()
        if not isinstance(v, list):
            return default
        result: list[list[bool]] = []
        for i in range(7):
            if i < len(v) and isinstance(v[i], list):
                row = [bool(v[i][j]) if j < len(v[i]) else True for j in range(24)]
            else:
                row = [True] * 24
            result.append(row)
        return result

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
    allowAthletes: list[str]
    kudoRules: KudoRules


# ── Activity & Decision ───────────────────────────────────────────────────────


class Activity(BaseModel):
    """A single activity entry parsed from the Strava following feed.

    Identifiers and core metadata come directly from the JSON feed response
    (no HTML parsing needed).  The ``stats`` field holds typed, normalised
    values alongside the original display strings for UI rendering.
    """

    activity_id: str
    activity_name: str
    sport_type: str
    athlete_id: str
    athlete_name: str
    athlete_avatar_url: str | None = None
    has_kudoed: bool
    can_kudo: bool = True
    kudos_count: int = 0
    start_date: datetime | None = None
    location: str | None = None
    is_commute: bool = False
    is_virtual: bool = False
    device_name: str | None = None
    stats: ActivityStats = Field(default_factory=ActivityStats)


class DecisionReason(StrEnum):
    """Why the engine decided to give or skip kudos for an activity."""

    IGNORE = "ignore"  # athlete in ignore list
    ALREADY = "already"  # already kudoed
    ALLOW = "allow"  # athlete in allow list → always give kudos (overrides criteria)
    CRITERIA = "criteria"  # below minDistance/minTime threshold
    NAME_MATCH = "name_match"  # activity name matched a regex → always give
    NO_RULE = "no_rule"  # sport type has no effective rule → gating skips it
    DEFAULT = "default"  # rule exists and criteria passed → give kudos


class Decision(BaseModel):
    """The outcome of decide(activity, effective_config)."""

    give_kudos: bool
    reason: DecisionReason


# ── Run result ────────────────────────────────────────────────────────────────


class FeedActivity(BaseModel):
    """A feed activity enriched with the engine's decision, for GET /api/feed.

    Inherits all Activity fields plus the engine's give_kudos / reason verdict.
    """

    # ── Identity ──────────────────────────────────────────────────────────────
    activity_id: str
    activity_name: str
    sport_type: str
    athlete_id: str
    athlete_name: str
    athlete_avatar_url: str | None = None
    has_kudoed: bool
    can_kudo: bool = True
    kudos_count: int = 0
    start_date: datetime | None = None
    location: str | None = None
    is_commute: bool = False
    is_virtual: bool = False
    device_name: str | None = None
    stats: ActivityStats = Field(default_factory=ActivityStats)
    # ── Decision ──────────────────────────────────────────────────────────────
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
    # Parsed feed snapshot — not included in API responses (see exclude=True).
    # Populated by the engine so _run_job can persist the activity cache.
    activities: list[dict[str, Any]] = Field(default=[], exclude=True)


class RunStatus(BaseModel):
    """Response shape for GET /api/status."""

    running: bool
    lastRun: RunResult | None = None
    nextRunAt: datetime | None = None
    schedulerEnabled: bool
    intervalMinutes: int
    version: str
    authOk: bool | None = None  # None = no run attempted yet
