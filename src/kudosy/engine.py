"""Kudos engine — orchestrates one run of the auto-kudos loop.

Design principles:
- All dependencies (client, feed parser) are injected → fully testable with fakes.
- Dry-run: decisions are logged, delays are simulated (not waited), no POSTs sent.
- Structured RunResult returned — no stdout-scraping needed.
- Delays between kudos use humanizer.compute_delay (injectable RNG for tests).
"""

from __future__ import annotations

import asyncio
import logging
import random
from datetime import UTC, datetime
from typing import TYPE_CHECKING

from kudosy.decision import decide
from kudosy.effective_config import build_effective_config
from kudosy.feed import AuthError, RateLimitError
from kudosy.humanizer import compute_delay
from kudosy.models import Activity, AppSettings, DecisionReason, RunResult, UserConfig

if TYPE_CHECKING:
    from kudosy.feed import FeedParser
    from kudosy.strava_client import StravaClient

log = logging.getLogger(__name__)

_RUN_HEADER = "=== Lauf: {ts}  dryRun={dry} ==="
# Abort the send loop after this many failed kudos in a row (network/5xx).
_MAX_CONSECUTIVE_FAILURES = 3
_RUN_FOOTER = "=== Beendet: {ts}  Exit-Code: {code}  Kudos: {kudos} ==="

_SKIP_REASONS = {
    DecisionReason.IGNORE: "--- Athlete is in ignore list",
    DecisionReason.ALREADY: "--- Already kudoed this activity",
    DecisionReason.CRITERIA: "--- Activity stats do not meet criteria",
}


def _fmt_stats(stats: object) -> str:
    from kudosy.models import ActivityStats

    if isinstance(stats, ActivityStats):
        parts = [f"{sv.label}={sv.raw}" for sv in stats.display]
        return "{" + ", ".join(parts) + "}"
    return str(stats)


async def run_kudos(
    user_cfg: UserConfig | None,
    settings: AppSettings,
    *,
    client: StravaClient,
    feed_parser: FeedParser,
    dry_run: bool = False,
    rng: random.Random | None = None,
    kudoed_ids: set[str] | None = None,
) -> RunResult:
    """Execute one kudos run.

    Args:
        user_cfg:    The user's config (None → no cookie, likely fails auth).
        settings:    App settings (delay params, shuffle, etc.).
        client:      Injected StravaClient (or fake for tests).
        feed_parser: Injected FeedParser (or fake for tests).
        dry_run:     When True, log decisions but do not send any kudos.
        rng:         Optional seeded RNG for deterministic tests.

    Returns:
        A :class:`RunResult` with structured outcome data.
    """
    started_at = datetime.now(UTC)
    log.info(_RUN_HEADER.format(ts=started_at.isoformat(), dry=dry_run))

    effective = build_effective_config(user_cfg)
    _cached_ids: set[str] = kudoed_ids if kudoed_ids is not None else set()
    total = 0
    activities: list[Activity] = []
    to_give: list[Activity] = []
    newly_kudoed: list[str] = []
    skipped_cached = 0
    given = 0
    error: str | None = None
    aborted_reason: str | None = None

    try:
        # 1. Authenticate & get CSRF token
        csrf_token = await client.get_csrf_token()

        # 2. Resolve athlete ID (from config or live lookup)
        athlete_id = (user_cfg.athleteId if user_cfg else "") or ""
        if not athlete_id:
            athlete_id = await client.fetch_current_athlete_id() or ""
            if athlete_id:
                log.debug("Resolved athlete ID from Strava: %s", athlete_id)
            else:
                log.warning("Could not resolve athlete ID — feed fetch may fail")

        # 3. Fetch feed (JSON endpoint)
        raw_feed = await client.fetch_following_feed(athlete_id)
        activities = feed_parser.parse(raw_feed)  # reassigns the pre-init'd list
        total = len(activities)
        log.info("Found %d activities", total)

        if total == 0:
            log.warning(
                "0 activities in feed — Strava's feed format may have changed. "
                "Run a Dry-Run after refreshing your session cookie."
            )

        # 3. Decide for each activity
        for act in activities:
            # Skip activities we already kudoed in a previous run (persistent cache)
            if act.activity_id in _cached_ids:
                skipped_cached += 1
                log.debug("--- Skipped (cached): %s — %s", act.athlete_name, act.activity_name)
                continue

            decision = decide(act, effective)
            stats_str = _fmt_stats(act.stats)
            log.debug(
                "Athlete: %s, Activity: %s, Type: %s, Has Kudoed: %s, Stats: %s",
                act.athlete_name,
                act.activity_name,
                act.sport_type,
                act.has_kudoed,
                stats_str,
            )
            if decision.give_kudos:
                log.debug("+++ Would give kudos")
                to_give.append(act)
            else:
                reason_msg = _SKIP_REASONS.get(decision.reason, f"--- {decision.reason.value}")
                log.debug(reason_msg)

        # rng is only ever consumed below (shuffle + delay computation), both of
        # which are skipped in dry-run — lazily init it once here rather than
        # separately at each call site.
        if rng is None and not dry_run:
            rng = random.Random()

        # 4. Optionally shuffle order for more human-like sending
        if settings.shuffleOrder and not dry_run:
            rng.shuffle(to_give)  # type: ignore[union-attr]

        # 5. Summary
        log.info("Would send kudos to %d out of %d activities", len(to_give), total)

        if dry_run:
            log.info("Dry run mode - no kudos will be sent")
            for act in to_give:
                log.info("Would send kudos to: %s - %s", act.athlete_name, act.activity_name)
        else:
            # 6. Send kudos with human-like delays
            consecutive_failures = 0
            for i, act in enumerate(to_give):
                if i > 0:
                    delay = compute_delay(
                        settings.minKudosDelaySeconds,
                        settings.maxKudosDelaySeconds,
                        rng,
                    )
                    log.debug("Waiting %.1fs before next kudo…", delay)
                    await asyncio.sleep(delay)

                try:
                    success = await client.send_kudos(act.activity_id, csrf_token)
                except RateLimitError:
                    aborted_reason = "rate_limited"
                    log.warning(
                        "Rate-Limit erreicht — %d verbleibende Kudos übersprungen",
                        len(to_give) - i,
                    )
                    break
                if success:
                    given += 1
                    consecutive_failures = 0
                    newly_kudoed.append(act.activity_id)
                    log.info("✓ Kudos gesendet: %s — %s", act.athlete_name, act.activity_name)
                else:
                    consecutive_failures += 1
                    log.warning(
                        "✗ Kudos fehlgeschlagen: %s — %s", act.athlete_name, act.activity_name
                    )
                    if consecutive_failures >= _MAX_CONSECUTIVE_FAILURES:
                        aborted_reason = "consecutive_failures"
                        log.warning(
                            "%d Kudos in Folge fehlgeschlagen — Lauf abgebrochen, "
                            "%d verbleibende Kudos übersprungen",
                            consecutive_failures,
                            len(to_give) - i - 1,
                        )
                        break

    except AuthError:
        # Auth failures must reach the caller (app.py) so it can flip
        # auth_ok=False and fire the notifyOnAuthError webhook.
        raise
    except Exception as exc:
        error = str(exc)
        log.error("Kudos run failed: %s", error, exc_info=True)

    finished_at = datetime.now(UTC)
    kudos_count = len(to_give) if dry_run else given
    # A run that stopped early (rate limit / consecutive send failures) did
    # not complete as intended, even though it didn't raise — don't report it
    # as a success (see app.py auth_ok handling and notify.build_run_payload).
    success = error is None and aborted_reason is None
    log.info(
        _RUN_FOOTER.format(
            ts=finished_at.isoformat(),
            code=0 if success else 1,
            kudos=kudos_count,
        )
    )

    return RunResult(
        started_at=started_at,
        finished_at=finished_at,
        success=success,
        dry_run=dry_run,
        total=total,
        would_give=len(to_give),
        given=given if not dry_run else 0,
        error=error,
        newly_kudoed=newly_kudoed,
        would_give_ids=[act.activity_id for act in to_give],
        activity_ids=[act.activity_id for act in activities],
        skipped_cached=skipped_cached,
        aborted_reason=aborted_reason,
        activities=[a.model_dump(mode="json") for a in activities],
    )
