# Changelog

All notable changes to this project are documented in this file.

## Unreleased

### Added
- Easy Startup core helpers for no-config flow:
  - `project-tkinter/easy_startup.py` (input discovery, safe output conflict resolution, project auto-match, resume eligibility),
  - tests: `project-tkinter/tests/test_easy_startup.py`.
- Reliability retry UX helpers:
  - `project-tkinter/retry_ux.py` (retry state model, adaptive backoff with jitter, structured telemetry formatter),
  - tests: `project-tkinter/tests/test_retry_ux.py`.
- Prompt router helpers for segment-aware strategy selection:
  - deterministic segment/batch classifier (`dialogue`, `narrative`, `mixed`, `other`),
  - strategy contracts (`default`, `dialogue`, `narrative`) with fallback to default,
  - tests: `project-tkinter/tests/test_prompt_router.py`.
- Security hardening assets:
  - Dependabot config: `.github/dependabot.yml`,
  - CodeQL workflow: `.github/workflows/codeql.yml`,
  - CVE threshold gate for pip-audit: `project-tkinter/scripts/pip_audit_cve_gate.py`.
- Series technical skeleton for Tkinter:
  - project-to-series assignment (`projects.series_id`, `projects.volume_no`),
  - `series` table in main DB,
  - new module `project-tkinter/series_store.py` (per-series SQLite store),
  - series autodetection from EPUB metadata (OPF/container),
  - "Slownik serii" manager in GUI (`proposed/approved/rejected`, manual add, export),
  - merged glossary generation (series approved terms + project glossary),
  - post-run learning from TM into series proposed terms.
- Tests for series workflow and metadata detection:
  - `project-tkinter/tests/test_series_support.py`.
- Reliability regression tests extended:
  - ledger seeding lifecycle,
  - EPUBCheck severity parsing,
  - QA severity gate,
  - nested inline-tag preservation.
- New documentation page:
  - `docs/10-Series-Style-Memory.md`.
- Wiki bootstrap package:
  - `docs/wiki/Home.md`,
  - `docs/wiki/_Sidebar.md`,
  - `docs/wiki/Workflow-and-Recovery.md`,
  - `project-tkinter/scripts/publish_wiki.ps1` (automated wiki publish after wiki backend init).
- Reliability/quality features:
  - segment-state ledger in SQLite (`segment_ledger`) with statuses `PENDING/PROCESSING/COMPLETED/ERROR`,
  - run-step scoping for ledger (`--run-step`),
  - hard-gate `EPUBCheck` option in Tkinter run panel.
  - ledger pre-seeding (all project segments are initialized upfront as `PENDING`),
  - scope pruning for ledger rows no longer present in current EPUB source.
- Tkinter UX additions:
  - always-visible ledger status strip in `Uruchomienie` section (`done/processing/error/pending` + color bar),
  - model-specific prompt presets in GUI with one-click apply (`Gemini` presets),
  - new prompt preset catalog files: `project-tkinter/prompt_presets.py`, `project-tkinter/prompt_presets.json`,
  - unit tests for preset loading/filtering: `project-tkinter/tests/test_prompt_presets.py`.
- Security/reliability hardening tests:
  - `project-tkinter/tests/test_security_reliability_hardening.py`,
  - snapshot restore path traversal guard (`Zip Slip`) regression test,
  - interrupted-run startup recovery regression test.
- Async I/O health-check features:
  - provider preflight telemetry in runtime core (`project-tkinter/runtime_core.py`),
  - GUI button `Health check I/O` in model card (`project-tkinter/app_gui_classic.py`, Horizon via inheritance),
  - async multi-plugin health checks in Studio Tools (`Health check all (async)`).
- Optional async translation batch dispatch:
  - new CLI/runtime option `--io-concurrency` for bounded parallel batch I/O,
  - provider-aware semaphore + paced dispatch interval (rate-limit-aware),
  - ledger idempotency preserved (`PROCESSING/COMPLETED/ERROR`) under concurrent dispatch.
- Tests for async health checks:
  - `project-tkinter/tests/test_async_health_checks.py`.

### Changed
- Security CI hardening:
  - `security-scans` Trivy gate now fails on `HIGH,CRITICAL`,
  - `pip-audit` report is followed by blocking CVE threshold gate (`PIP_AUDIT_CVE_THRESHOLD`),
  - README and wiki entries now include explicit security posture section.
- Milestone status alignment:
  - `M10` marked as closed in roadmap/backlog/wiki entries after completing `#53`, `#54`, `#55`.
- `project-tkinter/app_gui_classic.py`:
  - startup defaults now support no-config auto-pathing and project auto-bind/create for single-click entry,
  - ambiguous startup cases use lightweight chooser prompts instead of hard-fail,
  - startup status now reports fresh context vs resumed context.
- `project-tkinter/translation_engine.py`:
  - provider retry loop emits structured retry telemetry (`[RETRY] ... state=waiting_retry/recovered`),
  - adaptive backoff respects `Retry-After` plus jitter,
  - terminal retry failures are summarized once when retry budget is exhausted.
- `project-tkinter/translation_engine.py`:
  - prompt router now selects segment-aware strategy before request build,
  - runtime logs include selected strategy id and classifier confidence,
  - strategy id is persisted in ledger model field for auditability (`model|strategy=<id>`).
- `project-tkinter/app_gui_classic.py`:
  - run phase now shows friendly waiting/recovered states from retry telemetry without switching to error state.
- Roadmap/repository alignment (GitHub + docs):
  - closed umbrella issue `#51` (M9) and moved active delivery tracks to milestone `M10` (`#53`, `#54`, `#55`),
  - synchronized status in `docs/07-Roadmapa-i-kontrybucje.md` and `docs/09-Backlog-do-uzgodnienia.md`.
- README update:
  - added bilingual quick section (EN/PL) to `README.md`.
- Naming cleanup (repo alignment):
  - `project-tkinter/tlumacz_ollama.py` renamed to `project-tkinter/translation_engine.py`,
  - `project-tkinter/start.py` renamed to `project-tkinter/launcher_classic.py`,
  - `project-tkinter/start_horizon.py` renamed to `project-tkinter/launcher_horizon.py`,
  - archived legacy names aligned in `legacy/`.
- `project-tkinter/app_gui_classic.py`:
  - added series controls in project panel,
  - project create/save/import flow now supports series,
  - run command uses effective merged glossary for series-enabled projects.
- `project-tkinter/project_db.py`:
  - schema version bumped to `8`,
  - series CRUD and project queries extended with series metadata.
- Documentation updates:
  - `README.md`,
  - `project-tkinter/README.md`,
  - `project-tkinter/MANUAL_PL.md`,
  - `docs/04-Architektura-i-struktura.md`,
  - `docs/07-Roadmapa-i-kontrybucje.md`,
  - `docs/09-Backlog-do-uzgodnienia.md`,
  - `docs/README.md`,
  - `docs/index.md`.
- `project-tkinter/studio_suite.py`:
  - segment editor save now preserves inline tags/attributes (non-flattening text update),
  - search/replace apply now preserves inline tags instead of flattening segment XML.
- `project-tkinter/app_gui_classic.py`:
  - EPUBCheck gate now parses `FATAL/ERROR/WARNING` findings and blocks finalization on any `FATAL/ERROR`,
  - added QA severity gate (`fatal/error`) before final run success,
  - Text Editor now uses immutable inline-tag tokens (`[[TAG001]]`) and blocks destructive edits inside tag tokens,
  - `epubcheck` gate now has explicit timeout fail-fast behavior,
  - QA severity gate is now independent from EPUBCheck hard-gate toggle.
- `project-tkinter/project_db.py`:
  - startup runtime recovery for stale `running` states after abrupt app/process interruption
    (runs finalized as `error`, projects moved back to `pending`).
- `project-tkinter/studio_suite.py`:
  - `epubcheck` in Studio Tools now has timeout fail-fast behavior.
- `project-tkinter/studio_suite.py`:
  - dashboard now shows `segment_ledger` status breakdown (`PENDING/PROCESSING/COMPLETED/ERROR`) for active project/step,
  - dashboard reports latest-run provider split and estimated API token usage from ledger (`source_len` + translated length).
- Documentation synchronized for new UI/runtime features:
  - `README*.md`, `project-tkinter/README.md`,
  - `project-tkinter/MANUAL_PL.md`,
  - `docs/04-Architektura-i-struktura.md`,
  - `docs/07-Roadmapa-i-kontrybucje.md`,
  - `docs/08-Status-UI-i-Wiki.md`,
  - `docs/09-Backlog-do-uzgodnienia.md`,
  - `docs/wiki/Home.md`, `docs/wiki/Workflow-and-Recovery.md`, `docs/wiki/_Sidebar.md`.

### Fixed
- Self-healing DB schema integrity for drifted local databases
  (including case: `schema_version=8` but missing `projects.series_id`/`volume_no`).
- `smoke_gui` startup regression caused by missing `series_id` column on old DB files.
- Classic text editor no longer flattens inline XHTML tags on save; segment updates preserve markup structure.

### Security
- Snapshot restore in Studio Tools now blocks unsafe ZIP paths before extraction
  (prevents path traversal / `Zip Slip` outside project directory).
