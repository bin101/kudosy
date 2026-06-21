# Changelog

All notable changes to Kudosy will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [0.4.0](https://github.com/bin101/kudosy/compare/v0.3.2...v0.4.0) (2026-06-21)


### Features

* feed stats fix, clickable cards, quiet-hours matrix, kudos button & athlete list ([3fd1da1](https://github.com/bin101/kudosy/commit/3fd1da1b8321803cd0e33e315b8f44c634ecef77))
* feed stats fix, clickable cards, quiet-hours matrix, kudos button & athlete list ([c3f3a5c](https://github.com/bin101/kudosy/commit/c3f3a5c3b6348823c7a0563eda41c26cc8ab9573))
* persist and display athlete profile pictures in athlete management ([8f0f24b](https://github.com/bin101/kudosy/commit/8f0f24b507e03dd6094e2369623decb1ebcc9f8b))


### Bug Fixes

* reverse-engineer Strava athlete search from HAR capture ([12a03d0](https://github.com/bin101/kudosy/commit/12a03d0f96d71097b743d22f925d99a2875b8eb6))
* reverse-engineer Strava athlete search from HAR capture ([c16b9bb](https://github.com/bin101/kudosy/commit/c16b9bb884b5bd8617ef702f2a63b8b473cc1027))

## [0.3.2](https://github.com/bin101/kudosy/compare/v0.3.1...v0.3.2) (2026-06-20)


### Bug Fixes

* restore flex layout on settings toggles ([04cf7a4](https://github.com/bin101/kudosy/commit/04cf7a4b5328313cd6c645300056bd414fb754cc))
* restore flex layout on settings toggles inside form-group ([468d8d5](https://github.com/bin101/kudosy/commit/468d8d53cc9742a23a887af892b8c1e04a51fca4))

## [0.3.1](https://github.com/bin101/kudosy/compare/v0.3.0...v0.3.1) (2026-06-20)


### Bug Fixes

* make settings toggles visually distinct as on/off switches ([5e17dcf](https://github.com/bin101/kudosy/commit/5e17dcf8cbf6e5326b54ec913bce3550d9297465))

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
