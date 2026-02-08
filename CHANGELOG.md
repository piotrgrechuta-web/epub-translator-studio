# Changelog

All notable changes to this project are documented in this file.

## Unreleased

### Added
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
- New documentation page:
  - `docs/10-Series-Style-Memory.md`.
- Reliability/quality features:
  - segment-state ledger in SQLite (`segment_ledger`) with statuses `PENDING/PROCESSING/COMPLETED/ERROR`,
  - run-step scoping for ledger (`--run-step`),
  - hard-gate `EPUBCheck` option in Tkinter run panel.

### Changed
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
  - segment editor save now preserves inline tags/attributes (non-flattening text update).

### Fixed
- Self-healing DB schema integrity for drifted local databases
  (including case: `schema_version=8` but missing `projects.series_id`/`volume_no`).
- `smoke_gui` startup regression caused by missing `series_id` column on old DB files.

### Security
- TODO
