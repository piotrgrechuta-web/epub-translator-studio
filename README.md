# EPUB Translator Studio

[![PR checks](https://github.com/Piotr-Grechuta/epub-translator-studio/actions/workflows/pr-checks.yml/badge.svg?branch=main)](https://github.com/Piotr-Grechuta/epub-translator-studio/actions/workflows/pr-checks.yml)
[![Release](https://img.shields.io/github/v/release/Piotr-Grechuta/epub-translator-studio?display_name=tag)](https://github.com/Piotr-Grechuta/epub-translator-studio/releases)
[![License: Personal Use Only](https://img.shields.io/badge/license-Personal%20Use%20Only-red.svg)](LICENSE)
[![Python 3.11+](https://img.shields.io/badge/python-3.11%2B-blue.svg)](project-tkinter/app_main.py)

Language: **English** | [Polski](README.pl.md) | [Deutsch](README.de.md) | [Espanol](README.es.md) | [Francais](README.fr.md) | [Portugues](README.pt.md)

EPUB translator desktop app for AI-powered translation, post-editing, and QA of EPUB files.

KEYWORDS: `EPUB translator`, `EPUB translator desktop app`, `EPUB translation tool`, `AI translation`, `ebook translator`, `Ollama translator`, `Google Gemini translation`, `Translation Memory`, `QA gate`, `Tkinter`, `Python`.

## Bilingual quick read (EN/PL)

### English
- Desktop app for EPUB translation and post-editing with AI providers (Ollama/Google).
- Focus on safe resume, ledger idempotency, QA gates, and practical workflow for long books.
- Full Polish version: `README.pl.md`.

### Polski
- Aplikacja desktop do tlumaczenia i redakcji EPUB z providerami AI (Ollama/Google).
- Nacisk na bezpieczne wznawianie, idempotentny ledger, bramki QA i praktyczny workflow dla dlugich ksiazek.
- Pelna wersja PL: `README.pl.md`.

## Unique strengths (not common in most EPUB tools)
- idempotent processing with segment ledger (`done/processing/error/pending`) and safe resume after interruption
- managed DB migrations with backup + rollback (`migration_runs`, startup recovery notice, DB Update panel)
- security-first runtime gates (EPUBCheck hard gate + QA severity gate)
- Smart Context window for neighboring segments (better pronouns/gender consistency)
- async provider preflight (Ollama + Google) with telemetry (`status/latency/model count`) and non-blocking UI checks
- optional async batch dispatch (`--io-concurrency`) with bounded parallelism and ledger-safe resume
- Series Memory engine: per-series terms, style rules, lorebook, change history, series profile import/export
- one-click series batch orchestration with aggregated series report (`series_batch_report_*.json/.md`)

## Core capabilities you also get (industry-standard set)
- EPUB translation (`translate`) and post-editing (`edit`)
- EPUB validation
- Translation Memory (TM) and segment cache
- model-specific prompt presets in GUI
- QA findings workflow and QA gate
- EPUB operations: front card, cover/image removal, segment editor
- project queue workflow (`pending`, `run all`)

## App variants
- `project-tkinter/`
  - main desktop app in Python + Tkinter
  - fullest feature set
- `legacy/`
  - archived root scripts from older layout (`legacy/launcher_classic.py`, `legacy/translation_engine.py`)
  - not the recommended runtime path

## Quick start

### Tkinter (main)
```powershell
cd project-tkinter
python app_main.py --variant classic
```

Direct launchers are also available:
- `python launcher_classic.py`
- `python launcher_horizon.py`

## First Run
- You need one of these paths:
  - local AI: Ollama installed + at least one model,
  - online AI: valid API key (`GOOGLE_API_KEY`) + internet access.

### Ollama install commands
Windows (PowerShell):
```powershell
winget install Ollama.Ollama
ollama pull llama3.1:8b
```

Linux:
```bash
curl -fsSL https://ollama.com/install.sh | sh
ollama pull llama3.1:8b
```

macOS:
```bash
brew install ollama
ollama pull llama3.1:8b
```

### Online provider API key
Windows (PowerShell):
```powershell
setx GOOGLE_API_KEY "<YOUR_KEY>"
```

Linux/macOS:
```bash
export GOOGLE_API_KEY="<YOUR_KEY>"
```

## Requirements
- Local AI with Ollama: install Ollama and pull at least one model (example: `ollama pull llama3.1:8b`).
- Online AI (for example Google Gemini): set a valid API key (`GOOGLE_API_KEY` or GUI field).
- Internet access is required for online providers.

## Architecture (Tkinter core)
- shared runtime logic lives in `project-tkinter/runtime_core.py`
- canonical translator: `project-tkinter/translation_engine.py`
- both UI variants (`classic`, `horizon`) run on the same core/runtime contracts
- prompt preset catalog: `project-tkinter/prompt_presets.json`
- state-store abstraction layer (Repository step): `project-tkinter/studio_repository.py`

## Documentation
- Tkinter user manual (PL): `project-tkinter/MANUAL_PL.md`
- multi-device Git workflow: `project-tkinter/GIT_WORKFLOW_PL.md`
- support info: `SUPPORT_PL.md`
- docs index (Wiki/Pages ready): `docs/README.md`
- online docs portal: `https://piotr-grechuta.github.io/epub-translator-studio/`
- where progress/UI/Wiki are visible: `docs/08-Status-UI-i-Wiki.md`
- series memory technical skeleton: `docs/10-Series-Style-Memory.md`

## Security
- Branch protection on `main` enforces required checks and required review.
- CI security workflow (`.github/workflows/security-scans.yml`) runs:
  - `gitleaks` for secret detection,
  - `pip-audit` JSON report + blocking CVE threshold gate (`project-tkinter/scripts/pip_audit_cve_gate.py`),
  - `trivy` filesystem scan with `HIGH,CRITICAL` fail gate.
- `CodeQL` workflow is enabled in `.github/workflows/codeql.yml`.
- Dependabot updates are configured in `.github/dependabot.yml`.
- Recommendation: enable repository-level GitHub security features (`Dependabot alerts`, `Secret scanning`, `Secret scanning push protection`) in Settings.

## Support
- Sponsor: https://github.com/sponsors/Piotr-Grechuta
- a support link is also available directly in Tkinter app UI (`Support the project`)
- ready PL template for GitHub Sponsors profile: `.github/SPONSORS_PROFILE_TEMPLATE_PL.md`
- ready PL outreach pack (posts/release CTA): `.github/SPONSORS_OUTREACH_PACK_PL.md`
- community templates for feedback/contributions: `.github/ISSUE_TEMPLATE/`, `.github/PULL_REQUEST_TEMPLATE.md`
- repo profile setup pack (description/website/topics): `.github/REPO_PROFILE_SETUP_PL.md`
- ready first release draft (PL): `.github/RELEASE_DRAFT_PL.md`

## License
- License: `EPUB Translator Studio Personal Use License v1.0` (`LICENSE`)
- This project is source-available, not OSI/FSF open source.
- Free for personal private use of unmodified copies.
- Any modification, redistribution, or commercial use requires prior written agreement (`COMMERCIAL_LICENSE.md`).
- Practical examples:
  - EN: `LICENSE_GUIDE_EN.md`
  - PL: `LICENSE_GUIDE_PL.md`
  - DE: `LICENSE_GUIDE_DE.md`
  - ES: `LICENSE_GUIDE_ES.md`
  - FR: `LICENSE_GUIDE_FR.md`
  - PT: `LICENSE_GUIDE_PT.md`
