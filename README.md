# Kudosy

<p align="center">
  <img src="src/kudosy/static/assets/logo.svg" alt="Kudosy logo" width="220">
</p>

**Kudosy** automatically gives kudos on Strava to activities in your following feed — based on configurable distance and duration rules, with **human-like random timing** so it doesn't look like a bot.

> ⚠️ **Strava Terms of Service notice:** Kudosy authenticates using your personal `_strava4_session` browser cookie (web session), not the official Strava API/OAuth. This is a personal/educational tool — use it responsibly. Keep the scheduler interval generous and rely on the built-in delays and jitter to stay under the radar. You are solely responsible for compliance with Strava's ToS.

## Features

- 🤖 → 🧑 **Human-like timing** — randomised interval jitter, per-kudos delays, shuffled send order,
  and automatic backoff on Strava rate limits (HTTP 429) or repeated send failures
- ⚙️ **Web UI** — four tabs (Feed, Configuration, Statistics, Status & Log) in five languages
  (DE/EN/FR/ES/IT), with light/dark theme (system default + manual override)
- 🧩 **Flexible rules** — catch-all, per-category and per-sport-type distance/duration thresholds,
  activity-name regex overrides, per-athlete allow/deny lists
- 🔁 **Scheduler** — configurable interval + jitter, quiet-hours matrix (7×24, drag-to-paint,
  timezone-aware), enable/disable, dry-run mode
- 📡 **Live feed view** — see your following feed with per-activity kudo decisions and reasons,
  send single kudos manually, filter by status/sport/text
- 📊 **Statistics** — run history with charts and per-sport aggregations
- 🔔 **Notifications** — webhook alerts (ntfy, Slack, Discord, Gotify or generic HTTP) on runs,
  auth errors, and as a daily digest
- 🪵 **Live log** — the log tab streams run output in real time via Server-Sent Events
- ⬆️ **Update check** — footer hint when a newer release is available (optional, max. 1 check/12 h)
- 💾 **Backup** — export/import config + settings as JSON (session cookie excluded from exports)
- 🐳 **Docker-first** — single `docker compose up` to run, multi-arch images on GHCR
- 🧪 **Test-driven** — ≥85% test coverage, pure functions tested in isolation

## Quick Start

### With Docker (recommended)

```bash
# Clone the repo
git clone https://github.com/bin101/kudosy.git
cd kudosy

# Copy the example config and fill in your cookie + athlete ID
cp data/config.example.yaml data/config.yaml
$EDITOR data/config.yaml

# Start
docker compose up -d
# Open http://localhost:8080
```

### Without Docker (local Python)

```bash
python3 -m venv .venv && source .venv/bin/activate
pip install -e ".[dev]"
KUDOSY_DATA_DIR=./data KUDOSY_PORT=8080 python -m kudosy
```

## Getting Your Strava Session Cookie

1. Log in to [strava.com](https://www.strava.com) in your browser.
2. Open DevTools → **Application** → **Cookies** → `https://www.strava.com`.
3. Copy the value of `_strava4_session`.
4. Paste it into `data/config.yaml` as `stravaSessionCookie`, or enter it in the web UI.

The cookie expires — if Kudosy suddenly stops finding activities, refresh it here.

## Configuration

All config lives in `./data/` (mounted as `/data` in Docker):

| File | Purpose |
|---|---|
| `config.yaml` | Your session cookie, athlete ID, allow/deny lists, catch-all + per-sport rules |
| `settings.json` | Scheduler interval, jitter, delays, quiet-hours matrix, notifications, dry-run flag |
| `athlete-labels.json` | Cached athlete ID → name lookups |
| `athlete-avatars.json` | Cached athlete ID → avatar URL lookups |
| `kudoed-activities.json` | Already-kudoed activity IDs (skip cache across runs) |
| `activity-cache.json` | Last parsed feed snapshot (survives restarts) |
| `run-history.json` | Compact per-run history entries (feeds the Statistics tab) |
| `last-digest.json` | Timestamp of the last daily-digest notification |
| `last-run.log` | Output of the most recent run |

A legacy `defaults.yaml` (from older versions) is automatically migrated into `config.yaml`
on first boot and renamed to `defaults.yaml.migrated`.

See `data/config.example.yaml` for a fully annotated example.

## Human-Like Timing

Kudosy has several layers of randomness and restraint to avoid a detectable machine pattern:

1. **Interval jitter**: each scheduled run fires after `intervalMinutes ± jitterMinutes` (uniform random). Default: 60 ± 15 minutes.
2. **Per-kudos delay**: between each individual kudo POST, Kudosy waits a random duration in `[minKudosDelaySeconds, maxKudosDelaySeconds]`. Default: 3–25 seconds.
3. **Shuffle order**: the list of activities to kudo can be shuffled randomly before sending.
4. **Quiet hours**: the 7×24 schedule matrix restricts kudos to allowed weekday/hour slots in your timezone.
5. **Rate-limit backoff**: on HTTP 429 (or three consecutive failed sends) the remaining kudos of the run are skipped; the next scheduled run retries naturally.

All timing parameters are configurable in the web UI on the **Configuration** tab.

## Docker Image

Pre-built multi-arch images (amd64 + arm64) are published to GitHub Container Registry:

```bash
docker pull ghcr.io/bin101/kudosy:latest
```

Tags: `latest` (from `main`), `vX.Y.Z` (releases), `X.Y` (minor), commit SHA.

## Development

```bash
# Install
python3 -m venv .venv && source .venv/bin/activate
pip install -e ".[dev]"

# TDD cycle: write tests first, then implementation
pytest tests/unit/          # pure functions (fast)
pytest --cov=kudosy --cov-report=term-missing

# Lint & type-check
ruff check src tests
ruff format --check src tests
mypy src
```

See [CLAUDE.md](CLAUDE.md) for the full architecture guide.

## Versioning

[Semantic Versioning](https://semver.org) via `pyproject.toml`. Releases are driven by
[Conventional Commits](https://www.conventionalcommits.org) and automated with
[release-please](https://github.com/googleapis/release-please).
See [CHANGELOG.md](CHANGELOG.md) for release history.

## License

MIT — see [LICENSE](LICENSE).
