# Changelog

All notable changes to Kudosy will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [1.9.4](https://github.com/bin101/kudosy/compare/v1.9.3...v1.9.4) (2026-07-24)


### Bug Fixes

* **auth:** apply static translations before the login-overlay gate ([42f56e8](https://github.com/bin101/kudosy/commit/42f56e8dee79eb83910b8d13fdeff16a6c9bc37a))
* harden backend security/robustness and add optional login screen ([36a5d5b](https://github.com/bin101/kudosy/commit/36a5d5b99c9cd1b50dc730f73ca1a577b3ebfc76))
* **security:** escape Strava-derived strings before HTML interpolation ([17c2b4c](https://github.com/bin101/kudosy/commit/17c2b4c3e51381c352c9552b81829782840755a5))


### Documentation

* document agent-browser as the isolated UI-verification tool ([076d6a4](https://github.com/bin101/kudosy/commit/076d6a42584a8afeea8cbc0a029919447930eccf))
* **i18n:** use English section heading (docs must be English, not German), fill missing STRAVA_UNREACHABLE translation ([9413a0a](https://github.com/bin101/kudosy/commit/9413a0aa2f44422ef691c15b63d9ab63c0a65f36))

## [1.9.3](https://github.com/bin101/kudosy/compare/v1.9.2...v1.9.3) (2026-07-15)


### Bug Fixes

* **digest:** count only newly appeared activities in daily digest ([#58](https://github.com/bin101/kudosy/issues/58)) ([8b9e6db](https://github.com/bin101/kudosy/commit/8b9e6db99345cc5b0c60011f0e129729e73d7359))

## [1.9.2](https://github.com/bin101/kudosy/compare/v1.9.1...v1.9.2) (2026-07-09)


### Bug Fixes

* keep [hidden] elements hidden regardless of later display rules ([#55](https://github.com/bin101/kudosy/issues/55)) ([a11c022](https://github.com/bin101/kudosy/commit/a11c022d46cf9acb2204a8f67e1d94f4feefd5a1))


### Documentation

* never drive the user's live browser for UI verification ([#56](https://github.com/bin101/kudosy/issues/56)) ([d6dd401](https://github.com/bin101/kudosy/commit/d6dd40184cb9f3e2df4150a268f992d98b6e1e0c))

## [1.9.1](https://github.com/bin101/kudosy/compare/v1.9.0...v1.9.1) (2026-07-09)


### Bug Fixes

* dedupe activities in daily digest instead of summing per run ([b72728d](https://github.com/bin101/kudosy/commit/b72728d480791508652611c0670308503b472766))
* dedupe activities in daily digest instead of summing per run ([c8be8c7](https://github.com/bin101/kudosy/commit/c8be8c736c6273661b1c001441a6d573f9405383))

## [1.9.0](https://github.com/bin101/kudosy/compare/v1.8.0...v1.9.0) (2026-07-04)


### Features

* check GitHub releases for a newer Kudosy version ([6abf22a](https://github.com/bin101/kudosy/commit/6abf22a55539c53d5918a20cfd9e8f314f17f5d5))
* check GitHub releases for a newer Kudosy version ([527d4d0](https://github.com/bin101/kudosy/commit/527d4d01a6be46be522ec025af3f887ab70f3279))
* stream the run log live via Server-Sent Events ([27332a6](https://github.com/bin101/kudosy/commit/27332a68839da21ed05bdd19cb7a90975a4a2def))
* stream the run log live via Server-Sent Events ([c5be261](https://github.com/bin101/kudosy/commit/c5be2618810664797d0102511bffdd48df954a70))


### Bug Fixes

* back off on Strava rate limit and repeated kudo failures ([6523c9a](https://github.com/bin101/kudosy/commit/6523c9a9e8dfc9449dcbb5e2aa48d25718900f38))
* back off on Strava rate limit and repeated kudo failures ([f6e3117](https://github.com/bin101/kudosy/commit/f6e3117fd7b86fa3e56aeb1d1469577dd33cbaee))
* propagate AuthError from engine so auth banner and webhook fire ([ec80b35](https://github.com/bin101/kudosy/commit/ec80b35b843d7c3bd64834c323741a2e4f8a29d7))
* propagate AuthError from engine so auth banner and webhook fire ([063da14](https://github.com/bin101/kudosy/commit/063da14304c31f5828e3659a8ceaef3b1f2a9af7))


### Documentation

* refresh README to match the current feature set ([4c9dae0](https://github.com/bin101/kudosy/commit/4c9dae0d073b1d86545efea8425f83e5686818a0))
* refresh README to match the current feature set ([116f1a9](https://github.com/bin101/kudosy/commit/116f1a936afe4fc168215fcf1079e341a1b546f0))

## [1.8.0](https://github.com/bin101/kudosy/compare/v1.7.0...v1.8.0) (2026-07-02)


### Features

* add daily digest notification mode ([d58e242](https://github.com/bin101/kudosy/commit/d58e242e980b3edaa9a96a169a3a93f46ead27eb))
* add daily digest notification mode ([8222a57](https://github.com/bin101/kudosy/commit/8222a578752ce3a4848909d187c43ad0d5a0f406))
* add dark mode with system-theme default and user override ([07ce6f8](https://github.com/bin101/kudosy/commit/07ce6f8ab01c4b89d6aa7325bc61305ac14671a5))
* config backup & restore (export/import) ([85a85fd](https://github.com/bin101/kudosy/commit/85a85fdedde96e6286d8b0afee99f8f29f124d20))
* config backup & restore (export/import) ([17b6d27](https://github.com/bin101/kudosy/commit/17b6d27c679bc9e87707ab2f45337b2488454dd4))
* dark mode with system-theme default and user override ([ea583f4](https://github.com/bin101/kudosy/commit/ea583f49ec5ad8e46945287f6cc8251891c0e487))
* notifications & cookie-health monitoring ([b1599a6](https://github.com/bin101/kudosy/commit/b1599a60d4dda6d3cdc7419b46f2f36c3f515e39))
* notifications & cookie-health monitoring ([d356dfa](https://github.com/bin101/kudosy/commit/d356dfa0035aeef80a8b6abfb53c3904c3c03341))
* replace webhook auto-detection with explicit system selector ([badc88a](https://github.com/bin101/kudosy/commit/badc88a9311beea03d575be8115c3c107a92cd10))
* run history & statistics dashboard ([e91d32a](https://github.com/bin101/kudosy/commit/e91d32a2557a1f1cf7fd121834c3eb464b25e850))
* run history & statistics dashboard ([5886d96](https://github.com/bin101/kudosy/commit/5886d96ce3dcd1ab504c9f562fc1c451bc86bdd9))


### Bug Fixes

* format notification messages for ntfy, Slack, Discord, Gotify ([1284ece](https://github.com/bin101/kudosy/commit/1284ece1a8ec8efc6d9e200b9fd7310cf24b5ade))
* format notification messages for ntfy, Slack, Discord, Gotify ([1284ece](https://github.com/bin101/kudosy/commit/1284ece1a8ec8efc6d9e200b9fd7310cf24b5ade))
* format notification messages for ntfy, Slack, Discord, Gotify ([9e1558a](https://github.com/bin101/kudosy/commit/9e1558adfc7c28a95471e52bec449fcda1e53452))
* make app footer sticky at viewport bottom ([3ebd9cf](https://github.com/bin101/kudosy/commit/3ebd9cf3eb0a025aaf0bce3c986e100a0a22da73))
* make app footer sticky at viewport bottom ([bad816a](https://github.com/bin101/kudosy/commit/bad816ad27b161e41b516fc1c44d4cc26f450407))
* send ntfy headers as UTF-8 bytes to preserve non-ASCII characters ([b8e7cdd](https://github.com/bin101/kudosy/commit/b8e7cddfb33dff11c68121e88f8440c2faacf74a))
* URL-encode X-Title header to avoid ASCII encoding error ([4f8861d](https://github.com/bin101/kudosy/commit/4f8861dc48d07079e4c306d1c1c1570481e0c302))
* use ntfy headers API instead of JSON body ([b6951ee](https://github.com/bin101/kudosy/commit/b6951ee2073a1c0ceed0d15cbdd4f1e5f96f20cf))

## [1.7.0](https://github.com/bin101/kudosy/compare/v1.6.1...v1.7.0) (2026-07-01)


### Features

* merge Automation into Configuration tab with category dividers ([5e9b589](https://github.com/bin101/kudosy/commit/5e9b58983c68e32fbcf17c1ab52e7b9017dc9498))
* paginate Strava following feed for 50–100 activities ([e5056e3](https://github.com/bin101/kudosy/commit/e5056e3b2a476b15d08b598f9d1a8634088e96a9))
* paginate Strava following feed for 50–100 activities ([e5056e3](https://github.com/bin101/kudosy/commit/e5056e3b2a476b15d08b598f9d1a8634088e96a9))
* paginate Strava following feed for 50–100 activities ([4841b3e](https://github.com/bin101/kudosy/commit/4841b3e488ecb3a3d389c69f6a22fe1d4ac06b99))
* reorder tabs and persist active tab via URL hash ([fc7187b](https://github.com/bin101/kudosy/commit/fc7187b9b42308073878654c7c8fa4dcda114359))
* reorder tabs and persist active tab via URL hash ([aefc32f](https://github.com/bin101/kudosy/commit/aefc32fca56b1aec0e1c637eafe4dd2eb3e3b4c3))
* reorder tabs, merge Automation into Configuration tab, persist active tab via URL hash ([fc7187b](https://github.com/bin101/kudosy/commit/fc7187b9b42308073878654c7c8fa4dcda114359))
* replace save buttons with debounced auto-save ([9358b7b](https://github.com/bin101/kudosy/commit/9358b7b8f5d3b08a6255d4f780a7c2c8644a7b53))
* replace save buttons with debounced auto-save ([9358b7b](https://github.com/bin101/kudosy/commit/9358b7b8f5d3b08a6255d4f780a7c2c8644a7b53))
* replace save buttons with debounced auto-save ([f5bd846](https://github.com/bin101/kudosy/commit/f5bd846c35d88d103ea2b251ef9e3bdca0270d35))
* swap Configuration and Automation tab order ([0c834a6](https://github.com/bin101/kudosy/commit/0c834a69743dcfe690e0666b82074d6a330b564b))


### Bug Fixes

* add missing config.rules.title i18n key for all 5 languages ([604755b](https://github.com/bin101/kudosy/commit/604755b3c72a62fdf55a94f2ec0785833ba6d859))

## [1.6.1](https://github.com/bin101/kudosy/compare/v1.6.0...v1.6.1) (2026-07-01)


### Bug Fixes

* use model_dump(mode="json") so datetime fields are JSON-serializable in activity cache ([452bf61](https://github.com/bin101/kudosy/commit/452bf612a299cfe3d938dd62256872b2875a714f))
* use model_dump(mode="json") so datetime fields are JSON-serializable in activity cache ([114eb62](https://github.com/bin101/kudosy/commit/114eb624fed09deaf1901b742e607adbdec2d8a7))

## [1.6.0](https://github.com/bin101/kudosy/compare/v1.5.0...v1.6.0) (2026-06-30)


### Features

* rebuild Strava feed parsing from scratch with structured ActivityStats ([d0e23ee](https://github.com/bin101/kudosy/commit/d0e23ee8a709c9b46e5f762d2f8f58baf5116938))
* rebuild Strava feed parsing from scratch with structured ActivityStats ([1bcfb83](https://github.com/bin101/kudosy/commit/1bcfb831802d40db729e178b35084004b96810e7))
* rule-gating and Strava sport categories ([1ea7cc7](https://github.com/bin101/kudosy/commit/1ea7cc7e523ace92f3bc34d88f44745a36db2650))
* rule-gating and Strava sport categories ([0aac58f](https://github.com/bin101/kudosy/commit/0aac58f35dd189a3bb1de5d63cddfe8c1a223161))


### Bug Fixes

* localize feed stat labels (DE/EN/FR/ES/IT) ([4df7751](https://github.com/bin101/kudosy/commit/4df7751c71c10268fb9f83c304923522002cf5b1))
* localize feed stat labels using canonical key + i18n ([ec221b6](https://github.com/bin101/kudosy/commit/ec221b6c395eead3f75ef44b56adea384a4e545a))
* reformat import blocks to satisfy ruff 0.15.20 isort rules ([def703a](https://github.com/bin101/kudosy/commit/def703a407337538be6a5ae2215485b4b63578b5))

## [1.5.0](https://github.com/bin101/kudosy/compare/v1.4.0...v1.5.0) (2026-06-23)


### Features

* cache-bust static JS/CSS assets via versioned URLs ([#24](https://github.com/bin101/kudosy/issues/24)) ([a8def55](https://github.com/bin101/kudosy/commit/a8def550984214921b71d0cdd6ec2d7a7c3fb897))

## [1.4.0](https://github.com/bin101/kudosy/compare/v1.3.0...v1.4.0) (2026-06-23)


### Features

* show last-updated timestamp on feed page ([#22](https://github.com/bin101/kudosy/issues/22)) ([8c027d6](https://github.com/bin101/kudosy/commit/8c027d6b4791cd6d6ee50d4b9b739859ace10584))

## [1.3.0](https://github.com/bin101/kudosy/compare/v1.2.0...v1.3.0) (2026-06-22)


### Features

* transpose schedule matrix to portrait layout on narrow screens ([2df7a1b](https://github.com/bin101/kudosy/commit/2df7a1b2c153d4820caef55767e73cdd5c20640c))
* transpose schedule matrix to portrait layout on narrow screens ([5e8748a](https://github.com/bin101/kudosy/commit/5e8748afcb56377f8f675d6cb1a56dd309137052))


### Bug Fixes

* prevent horizontal body scroll from schedule matrix and tabs ([1ca173b](https://github.com/bin101/kudosy/commit/1ca173b3706f4833b4f41ffe1136132e75a3104a))
* responsive design for all UI elements ([9514134](https://github.com/bin101/kudosy/commit/951413481b0ae4d06a98220fcc54428fee85071b))
* responsive design for all UI elements across phone breakpoints ([ec8d3b3](https://github.com/bin101/kudosy/commit/ec8d3b39a9e937f419b03698a1ceb8f235fea071))
* use container width measurement for portrait matrix layout ([36310b0](https://github.com/bin101/kudosy/commit/36310b080992d19965752c674974aa6925cdc6bc))
* use container width measurement for portrait schedule matrix ([cc00384](https://github.com/bin101/kudosy/commit/cc003844c9d69cdbe63839eccb517cbeffd1f058))

## [1.2.0](https://github.com/bin101/kudosy/compare/v1.1.0...v1.2.0) (2026-06-21)


### Features

* feed spinner/cache, button loading states, drag-to-paint schedule matrix ([89ca144](https://github.com/bin101/kudosy/commit/89ca144a9384c32de95c3e58f9230160c775cc9c))
* feed spinner/cache, button loading states, drag-to-paint schedule matrix ([b27d271](https://github.com/bin101/kudosy/commit/b27d2716e3983d49941c0806d3ac9377eacf5645))
* merge config/defaults/settings tabs and unify kudo rules ([fef283b](https://github.com/bin101/kudosy/commit/fef283bca6272d11b44b34e703f8dd58e45b4028))
* merge config/defaults/settings tabs and unify kudo rules ([019af96](https://github.com/bin101/kudosy/commit/019af96bcddf061728a63ceb1b607638d05e9608))
* merge config/defaults/settings tabs and unify kudo rules ([#14](https://github.com/bin101/kudosy/issues/14)) ([fef283b](https://github.com/bin101/kudosy/commit/fef283bca6272d11b44b34e703f8dd58e45b4028))
* persist activity cache across restarts and background runs ([90a6831](https://github.com/bin101/kudosy/commit/90a6831d5b2b914d0ce7e8f1d4c1849e6aad8a42))
* persist activity cache across restarts and background runs ([388a514](https://github.com/bin101/kudosy/commit/388a5143c42d4e064f611da55062128349cb6594))
* remove Dry-Run button, default dryRun=true, hint on manual run ([5b542ee](https://github.com/bin101/kudosy/commit/5b542eef106cc97897657cfa15fc99e642dcd8bf))


### Bug Fixes

* button spinner via innerHTML-swap, matrix rectangle selection ([1bd9eb6](https://github.com/bin101/kudosy/commit/1bd9eb6152d3f32f099377ec582de91fdef8e978))
* display midnight (0) after 23:00 in schedule matrix ([e465062](https://github.com/bin101/kudosy/commit/e4650624e22c6bb35795fb748a81a5e893192006))
* keep Run/DryRun spinner until background job finishes ([0b037e0](https://github.com/bin101/kudosy/commit/0b037e0b7cfd65206b080034cfb200be007093b4))
* Run-Now button respects global dryRun setting ([e3521fa](https://github.com/bin101/kudosy/commit/e3521fabe89bb615bf87ac9506dbd5389d226736))

## [1.1.0](https://github.com/bin101/kudosy/compare/v1.0.0...v1.1.0) (2026-06-21)


### Features

* add feed filter bar and visual activity state indicators ([8b97d0f](https://github.com/bin101/kudosy/commit/8b97d0f29459bbf744ad241269e9e7f72e9f93f1))
* feed filter bar and visual activity state indicators ([ae0961a](https://github.com/bin101/kudosy/commit/ae0961a1124bc1e4b20023bc4eb45955b598e654))

## [1.0.0](https://github.com/bin101/kudosy/compare/v0.4.0...v1.0.0) (2026-06-21)


### Miscellaneous Chores

* release prep for 1.0.0 ([b40657b](https://github.com/bin101/kudosy/commit/b40657bfa85891229c05e818cd34e82d7ce6fb70))

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
