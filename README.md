# EPUB Translator Studio

[![PR checks](https://github.com/Piotr-Grechuta/epub-translator-studio/actions/workflows/pr-checks.yml/badge.svg?branch=main)](https://github.com/Piotr-Grechuta/epub-translator-studio/actions/workflows/pr-checks.yml)
[![Release](https://img.shields.io/github/v/release/Piotr-Grechuta/epub-translator-studio?display_name=tag)](https://github.com/Piotr-Grechuta/epub-translator-studio/releases)
[![License: Personal Use Only](https://img.shields.io/badge/license-Personal%20Use%20Only-red.svg)](LICENSE)
[![Python 3.11+](https://img.shields.io/badge/python-3.11%2B-blue.svg)](project-tkinter/app_main.py)

Language: **English** | [Polski](README.pl.md) | [Deutsch](README.de.md) | [Espanol](README.es.md) | [Francais](README.fr.md) | [Portugues](README.pt.md)

EPUB translator desktop app for AI-powered translation, post-editing, and QA of EPUB files.

KEYWORDS: `EPUB translator`, `EPUB translator desktop app`, `EPUB translation tool`, `AI translation`, `ebook translator`, `Ollama translator`, `Google Gemini translation`, `Translation Memory`, `QA gate`, `Tkinter`, `Python`.

## What it does
- EPUB translation (`translate`) and post-editing (`edit`)
- EPUB validation
- Translation Memory (TM) and segment cache
- QA findings workflow and QA gate
- EPUB operations: front card, cover/image removal, segment editor
- project queue workflow (`pending`, `run all`)

## App variants
- `project-tkinter/`
  - main desktop app in Python + Tkinter
  - fullest feature set
- `legacy/`
  - archived root scripts from older layout (`legacy/start.py`, `legacy/tlumacz_ollama.py`)
  - not the recommended runtime path

## Quick start

### Tkinter (main)
```powershell
cd project-tkinter
python app_main.py --variant classic
```

Compatibility aliases still available:
- `python start.py`
- `python start_horizon.py`

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
- canonical translator: `project-tkinter/tlumacz_ollama.py`
- both UI variants (`classic`, `horizon`) run on the same core/runtime contracts

## Documentation
- Tkinter user manual (PL): `project-tkinter/MANUAL_PL.md`
- multi-device Git workflow: `project-tkinter/GIT_WORKFLOW_PL.md`
- support info: `SUPPORT_PL.md`
- docs index (Wiki/Pages ready): `docs/README.md`
- online docs portal: `https://piotr-grechuta.github.io/epub-translator-studio/`
- where progress/UI/Wiki are visible: `docs/08-Status-UI-i-Wiki.md`

## Support
- Sponsor: https://github.com/sponsors/Piotr-Grechuta
- a support link is also available directly in Tkinter app UI (`Wesprzyj projekt`)
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
