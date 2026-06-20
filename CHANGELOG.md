# Changelog

All notable changes to Kudosy will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [0.3.0](https://github.com/bin101/kudosy/compare/v0.2.0...v0.3.0) (2026-06-20)


### Features

* multilingual UI (DE/EN/FR/ES/IT) and activity cache ([9ad0fac](https://github.com/bin101/kudosy/commit/9ad0face80a849899a1df5e5336512cd096c8cc9))

## [0.2.0](https://github.com/bin101/kudosy/compare/v0.1.0...v0.2.0) (2026-06-20)


### Features

* fix feed parser, add Feed tab, remove legacy config ([10d1dfc](https://github.com/bin101/kudosy/commit/10d1dfc5f4e3edf230817cafe87dc3372a7f9b7a))
* initial Kudosy release v0.1.0 ([e96e760](https://github.com/bin101/kudosy/commit/e96e760b2d35afc2f23ec5ed7920381f622a2fe5))

## 0.1.0 (2026-06-20)


### Features

* fix feed parser, add Feed tab, remove legacy config ([10d1dfc](https://github.com/bin101/kudosy/commit/10d1dfc5f4e3edf230817cafe87dc3372a7f9b7a))
* initial Kudosy release v0.1.0 ([e96e760](https://github.com/bin101/kudosy/commit/e96e760b2d35afc2f23ec5ed7920381f622a2fe5))

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
