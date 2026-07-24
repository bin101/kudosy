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
  `settings.json`, `athlete-labels.json`, `last-run.log`. Override in tests.
  Legacy `defaults.yaml` files are automatically migrated into `config.yaml` on first boot
  and renamed to `defaults.yaml.migrated`.
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
`decision`, `humanizer`). Both are enforced in CI — the overall gate via `pytest
--cov-fail-under=85`, the per-module one via `.github/scripts/check_module_coverage.py`
(reads `coverage.json`, since coverage.py has no built-in per-file threshold).

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

### Browser-based UI verification

When verifying frontend/UI changes visually, always use an isolated, dedicated browser
automation tool — **never** drive the user's currently-running personal browser (Safari,
Chrome, etc.) via AppleScript/UI automation or by opening new windows/tabs in it. Doing so
interferes with the user's actual, in-progress work (open tabs, unsaved state).

**Use the `agent-browser` CLI** (`brew install agent-browser` or `npm i -g agent-browser`;
run `agent-browser skills get core --full` once for the full command reference). It launches
its own isolated Chrome instance via CDP — no Playwright/Puppeteer dependency, no interaction
with the user's browser session. Typical flow:

```bash
agent-browser open http://127.0.0.1:8080/
agent-browser snapshot -i          # accessibility tree with @eN refs for interactive elements
agent-browser screenshot out.png   # visual check — Read the PNG to actually look at it
agent-browser fill @e13 "value"
agent-browser click @e14
agent-browser console              # check for JS errors / CSP violations
agent-browser close --all          # clean up when done
```

Gotcha: `serve_index()` in `routes.py` serves JS/CSS with `?v={version}` and
`Cache-Control: max-age=31536000, immutable`. If you edit a static file and re-test in the
*same* browser session without bumping the package version, the browser serves the stale
cached copy under that identical URL — `agent-browser reload` is not enough to see your edit.
Run `agent-browser close --all` and re-`open` (a fresh session has no disk cache) instead.

If no such isolated browser tool is available in the environment, say so explicitly and
report verification as blocked/skipped rather than falling back to automating the user's
live browser session.

### Docker

```bash
docker compose up --build   # builds image, starts on :8080
```

## Module Cheat-Sheet

| Module | Responsibility |
|---|---|
| `parsers.py` | Pure: `parse_athlete_name`, `decode_html_entities` |
| `stat_parse.py` | Pure: `strip_unit_markup`, `parse_distance`, `parse_duration`, `parse_pace`, `parse_elevation`, `classify_stat` — all stat string→number conversions |
| `sport_types.py` | `ALL_SPORT_TYPES` enum list, `fetch_sport_types`, `merge_sport_types` |
| `humanizer.py` | Pure: `compute_jitter`, `compute_delay` — RNG injected for tests |
| `models.py` | Pydantic v2: `StatValue`, `ActivityStats`, `Activity`, `UserConfig` (incl. `catchAll`), `AppSettings`, `Decision`, `RunResult` |
| `effective_config.py` | Pure: `build_effective_config(user)` — two-layer merge (catchAll → user per-sport) |
| `decision.py` | Pure: `decide(activity, effective_config) -> Decision` — reads typed `ActivityStats` fields directly |
| `feed.py` | `FeedParser` protocol + `StructuredFeedParser` — parses JSON XHR feed response into `list[Activity]` |
| `strava_client.py` | httpx async: CSRF, JSON feed fetch (`/dashboard/feed` XHR), kudo POST, athlete lookup, name search, `fetch_current_athlete_id` |
| `engine.py` | Orchestrator: run-kudos loop with delays, dry-run, RunResult |
| `notify.py` | Pure: `send_notification(url, payload, *, post_fn)` — HTTP POST injected for tests; `build_run_payload`, `build_auth_error_payload` |
| `store.py` | `/data` file I/O — atomic YAML/JSON writes, bootstrap, one-time migration of legacy `defaults.yaml`; athlete-labels.json + athlete-avatars.json; `append_run_history` / `read_run_history` |
| `scheduler.py` | APScheduler wrapper with jitter, reschedule, in-flight guard |
| `logging_conf.py` | stdout + `/data/last-run.log` handler setup |
| `app.py` | FastAPI app factory + lifespan |
| `routes.py` | All `/api/*` endpoints (split into `public_router` + auth-gated `router`) |
| `settings.py` | `pydantic-settings` env config (`KUDOSY_DATA_DIR`, `KUDOSY_PORT`, `KUDOSY_AUTH_PASSWORD`, …) |
| `auth.py` | Optional login gate: `require_auth` dependency, signed session-cookie tokens (HMAC-SHA256), login lockout — no-op unless `KUDOSY_AUTH_PASSWORD` is set |

## API Endpoints

All endpoints match the legacy Node.js wrapper exactly (so the frontend works unchanged):

```
GET  /api/config                    — read user config (cookie redacted — see hasCookie/cookiePreview)
PUT  /api/config                    — merge+validate user config (empty cookie keeps existing; 422 on invalid)
GET  /api/settings                  — read scheduler/delay settings
PUT  /api/settings                  — write settings + reschedule
GET  /api/sport-types               — list of Strava sport types
GET  /api/sport-categories          — active sport types grouped into the 5 Strava categories
GET  /api/athletes/search?q=<name>  — search athletes by name (requires cookie)
GET  /api/athletes/{id}             — lookup athlete name by ID (requires cookie; id must be numeric)
GET  /api/athlete-labels            — all cached athlete names  {id → name}
GET  /api/athlete-avatars           — all cached athlete avatar URLs  {id → url}
GET  /api/feed                      — current following feed with give_kudos/reason
POST /api/kudos/{activity_id}       — send kudos for a specific activity (activity_id must be numeric)
POST /api/run                       — trigger a run (409 if already running)
GET  /api/status                    — running state, lastRun, nextRunAt, version, authOk
GET  /api/history?limit=            — last N run-history entries (max 500, newest first)
GET  /api/export                    — download config+settings as JSON (cookie excluded)
POST /api/import                    — restore config+settings from backup JSON
GET  /api/log                       — last-run.log as text/plain
GET  /api/log/stream                — live log via Server-Sent Events
GET  /api/auth-status               — {authRequired, authenticated} — always reachable, no session needed
POST /api/login                     — {password} → sets session cookie (401 wrong password, 429 lockout)
POST /api/logout                    — clears the session cookie
```

**Brittleness note:** `GET /api/athletes/search` and `GET /api/feed` depend on Strava's
undocumented web session endpoints. The JSON feed format (`GET /dashboard/feed?feed_type=following&athlete_id=<id>`)
is isolated in `feed.py` (`StructuredFeedParser`) and `strava_client.py`.
`GET /api/athletes/search` HTML parsing is isolated in `strava_client.py` (`_extract_search_results`).
If Strava changes their response format, only these two modules need updating.

**Auth note:** all `/api/*` routes except `/api/auth-status`, `/api/login`, and `/api/logout`
(plus `GET /`, serving the frontend shell) go through `auth.require_auth` — a no-op unless
`KUDOSY_AUTH_PASSWORD` is set (see README "Access Control"). Enforced via two `APIRouter`s in
`routes.py`: `public_router` (no dependency) and `router` (`dependencies=[Depends(require_auth)]`).

## Security Notes

- **Never commit `/data/`**: it contains the real `_strava4_session` cookie, the session-signing
  secret, and real athlete names. `.gitignore` and `.dockerignore` both exclude it.
- **Cookie masking**: logs show only the first ~8 characters (e.g., `r2i8rfkf…`); `GET /api/config`
  never returns the raw cookie (only `hasCookie`/`cookiePreview`).
- **ToS grey area**: Kudosy uses the Strava web session (not the official API). Use it for personal,
  non-commercial purposes only. Keep the interval generous and dry-run frequently.
- **No auth by default**: see README "Access Control" — set `KUDOSY_AUTH_PASSWORD` before exposing
  Kudosy beyond your local machine.

## Git Conventions

> **GPG signing gotcha:** this repo's commits are GPG-signed (`commit.gpgsign=true`
> locally). Never wrap `git commit` in `timeout ...`, `bash -c "..."`, or other
> subshell/process-wrapping constructs — pinentry loses its controlling TTY in that
> case and `gpg-agent` hangs indefinitely waiting for a passphrase prompt that can
> never appear, instead of failing fast. Invoke `git commit` as a direct, top-level
> command. If it still hangs, the fix is restarting the agent (`gpgconf --kill
> gpg-agent`) outside the hung command, not adding `--no-gpg-sign`.

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
