# Kudosy — Claude Code Project Guide

## Project Overview

**Kudosy** is a self-hosted tool that automatically gives kudos on Strava activities based on
configurable rules (min distance, min duration, activity name patterns). It exposes a German-language
web UI on port 8080 and uses the user's `_strava4_session` browser cookie for authentication (no
official Strava API/OAuth).

**Stack:** Python 3.13, FastAPI, httpx (async), APScheduler, pydantic v2, PyYAML.
**Packaging:** `src/kudosy/` layout, PEP 621 (`pyproject.toml`), hatchling.
**License:** MIT.

## Architecture: single integrated process

The engine (`engine.py`) is imported as a module — **no subprocess spawning**, no separate image.
All network and response-shape assumptions are isolated in `feed.py` + `strava_client.py` behind
a `FeedParser` protocol (the "brittleness firewall").

```
FastAPI app (app.py / routes.py)
  └── scheduler.py  ──── engine.py ──── strava_client.py
                    └────────────────── feed.py  (FeedParser protocol)
                              │
                    decision.py ←── effective_config.py
                    parsers.py
                    humanizer.py
                    store.py
```

## Key Design Decisions

- **`KUDOSY_DATA_DIR`** (default `/data`): all user data lives here — `config.yaml`,
  `defaults.yaml`, `settings.json`, `athlete-labels.json`, `last-run.log`. Override in tests.
- **Clean-room**: no code from `aexel90/strava_kudos` — that repo has no license. Engine behavior
  is derived only from observed run-log output and the user's own wrapper code.
- **Human-like timing**: `humanizer.py` provides `compute_jitter` (interval ± jitter) and
  `compute_delay` (per-kudos random wait). RNG is injected for deterministic testing.
- **Versioning**: SemVer in `pyproject.toml`; `kudosy.__version__` via `importlib.metadata`.
  Releases via `release-please` + Conventional Commits.

## Development Workflow

### Setup

```bash
python -m venv .venv && source .venv/bin/activate
pip install -e ".[dev]"   # or: uv pip install -e ".[dev]"
```

> The package extras for dev deps are declared in `pyproject.toml` under `[project.optional-dependencies]`.

### Run locally (without Docker)

```bash
KUDOSY_DATA_DIR=./data KUDOSY_PORT=8080 python -m kudosy
```

### Tests (TDD — write tests first, then implementation)

```bash
pytest                            # run all tests
pytest tests/unit/                # pure functions only (fast)
pytest --cov=kudosy --cov-report=term-missing   # with coverage
```

Coverage targets: ≥85% overall, ≥90% for pure modules (`parsers`, `effective_config`,
`decision`, `humanizer`).

### Lint & type-check

```bash
ruff check src tests
ruff format --check src tests
mypy src
```

### Quality gate — mandatory before every PR merge

**All four checks must pass with zero errors, zero warnings, and zero lint issues:**

```bash
ruff check src tests          # zero lint errors
ruff format --check src tests # zero formatting issues
mypy src                      # zero type errors
pytest                        # zero test failures, zero warnings, coverage ≥ 85 %
```

pytest is configured to treat warnings as errors (`filterwarnings = ["error", ...]`).
Known unavoidable external warnings must be added to the `filterwarnings` ignore list in
`pyproject.toml` with a comment explaining why.

> **Keep CLAUDE.md up to date.** When the user changes a development process rule, workflow
> step, or quality requirement, update this file in the same PR. CLAUDE.md is the single source
> of truth for how this project is built and maintained.

### Docker

```bash
docker compose up --build   # builds image, starts on :8080
```

## Module Cheat-Sheet

| Module | Responsibility |
|---|---|
| `parsers.py` | Pure: `parse_distance`, `parse_duration`, `parse_athlete_name`, `decode_html_entities` |
| `sport_types.py` | `ALL_SPORT_TYPES` enum list, `fetch_sport_types`, `merge_sport_types` |
| `humanizer.py` | Pure: `compute_jitter`, `compute_delay` — RNG injected for tests |
| `models.py` | Pydantic v2: `UserConfig`, `Defaults`, `AppSettings`, `Activity`, `Decision`, `RunResult` |
| `effective_config.py` | Pure: `build_effective_config(user, defaults)` — three-layer merge |
| `decision.py` | Pure: `decide(activity, effective_config) -> Decision` |
| `feed.py` | `FeedParser` protocol + `StravaHtmlFeedParser` — all format assumptions here |
| `strava_client.py` | httpx async: CSRF, feed fetch, kudo POST, athlete lookup, name search |
| `engine.py` | Orchestrator: run-kudos loop with delays, dry-run, RunResult |
| `store.py` | `/data` file I/O — atomic YAML/JSON writes, bootstrap, migration; athlete-labels.json + athlete-avatars.json |
| `scheduler.py` | APScheduler wrapper with jitter, reschedule, in-flight guard |
| `logging_conf.py` | stdout + `/data/last-run.log` handler setup |
| `app.py` | FastAPI app factory + lifespan |
| `routes.py` | All `/api/*` endpoints |
| `settings.py` | `pydantic-settings` env config (`KUDOSY_DATA_DIR`, `KUDOSY_PORT`, …) |

## API Endpoints

All endpoints match the legacy Node.js wrapper exactly (so the frontend works unchanged):

```
GET  /api/config                    — read user config
PUT  /api/config                    — write user config (empty cookie → 400)
GET  /api/defaults                  — read defaults
PUT  /api/defaults                  — write defaults
GET  /api/settings                  — read scheduler/delay settings
PUT  /api/settings                  — write settings + reschedule
GET  /api/sport-types               — list of Strava sport types
GET  /api/athletes/search?q=<name>  — search athletes by name (requires cookie)
GET  /api/athletes/{id}             — lookup athlete name by ID (requires cookie)
GET  /api/athlete-labels            — all cached athlete names  {id → name}
GET  /api/athlete-avatars           — all cached athlete avatar URLs  {id → url}
GET  /api/feed                      — current following feed with give_kudos/reason
POST /api/kudos/{activity_id}       — send kudos for a specific activity
POST /api/run                       — trigger a run (409 if already running)
GET  /api/status                    — running state, lastRun, nextRunAt, version
GET  /api/log                       — last-run.log as text/plain
```

**Brittleness note:** `GET /api/athletes/search` and `GET /api/feed` depend on Strava's
undocumented web session endpoints. The HTML parsing is isolated in `feed.py` and
`strava_client.py` (`_extract_search_results`). If Strava changes their page structure,
only these modules need updating.

## Security Notes

- **Never commit `/data/`**: it contains the real `_strava4_session` cookie and real athlete names.
  `.gitignore` and `.dockerignore` both exclude it.
- **Cookie masking**: logs show only the first ~8 characters (e.g., `r2i8rfkf…`).
- **ToS grey area**: Kudosy uses the Strava web session (not the official API). Use it for personal,
  non-commercial purposes only. Keep the interval generous and dry-run frequently.

## Git Conventions

Conventional Commits: `feat:`, `fix:`, `chore:`, `docs:`, `test:`, `refactor:`.
Branch: `main`. Releases: `release-please` creates a PR on each push to `main`, cutting a
`vX.Y.Z` tag → GitHub Release → Docker image built+pushed to `ghcr.io/bin101/kudosy`.
To force a specific version (e.g. `1.0.0`), include `Release-As: 1.0.0` in a commit body
on `main`; release-please will pick it up and open/update its release PR accordingly.

### Feature branches

Every fix and every new feature gets its own branch — never commit directly to `main`.

- Branch naming: `feat/<short-slug>`, `fix/<short-slug>`, `chore/<short-slug>`, etc.
- When a feature branch is finished: commit all changes, push, and open a PR — do this
  autonomously without asking for confirmation. Only pause if something is genuinely ambiguous
  (e.g. a destructive force-push or a missing required value).
