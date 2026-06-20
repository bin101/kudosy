# Changelog

All notable changes to Kudosy will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [0.1.0] — 2026-06-20

### Added

- Initial release of Kudosy — a clean-room Python reimplementation independent of any upstream image
- FastAPI web UI with four tabs: Config, Defaults, Settings, Status & Log
- Human-like timing: configurable interval jitter and per-kudos random delays
- Test-driven development: pytest + respx + pytest-asyncio, ≥85% coverage
- TDD-first pure modules: parsers, effective_config, decision, humanizer
- Brittleness-firewall FeedParser protocol isolating Strava scraping from engine logic
- SemVer versioning with Conventional Commits and release-please automation
- GitHub Actions: CI (ruff, mypy, pytest) and release (GHCR multi-arch Docker image)
- MIT license
