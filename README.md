# EPUB Translator Studio

Language: **English** | [Polski](README.pl.md) | [Deutsch](README.de.md) | [Espanol](README.es.md) | [Francais](README.fr.md) | [Portugues](README.pt.md)

Desktop toolkit for translating and editing EPUB files with AI.

KEYWORDS: `EPUB translator`, `EPUB translation tool`, `AI translation`, `ebook translator`, `Ollama translator`, `Google Gemini translation`, `Translation Memory`, `QA gate`, `Tkinter`, `Electron`, `FastAPI`, `Python`.

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
- `project-web-desktop/`
  - Electron + FastAPI variant
  - desktop web-style interface
- `legacy/`
  - archived root scripts from older layout (`legacy/start.py`, `legacy/tlumacz_ollama.py`)
  - not the recommended runtime path

## Quick start

### Tkinter (main)
```powershell
cd project-tkinter
python start.py
```

### Web desktop
```powershell
cd project-web-desktop
.\run-backend.ps1
.\run-desktop.ps1
```

## Requirements
- Local AI with Ollama: install Ollama and pull at least one model (example: `ollama pull llama3.1:8b`).
- Online AI (for example Google Gemini): set a valid API key (`GOOGLE_API_KEY` or GUI field).
- Internet access is required for online providers.

## Architecture (Variant 0: shared core)
- shared runtime logic lives in `project-tkinter/runtime_core.py`
- web backend (`project-web-desktop/backend/app.py`) imports the same core
- canonical translator: `project-tkinter/tlumacz_ollama.py`
- web fallback translator: `project-web-desktop/backend/engine/tlumacz_ollama.py`

This keeps core runtime behavior synchronized across both variants.

## Documentation
- Tkinter user manual (PL): `project-tkinter/MANUAL_PL.md`
- multi-device Git workflow: `project-tkinter/GIT_WORKFLOW_PL.md`
- support info: `SUPPORT_PL.md`

## Support
- Sponsor: https://github.com/sponsors/piotrgrechuta-web
- a support link is also available directly in both app UIs (`Wesprzyj projekt`)

## License
- License: `PolyForm Noncommercial 1.0.0` (`LICENSE`)
- You can copy and modify the code for noncommercial purposes.
- Keep creator attribution and required notices in redistributions (`NOTICE`, `AUTHORS`).
- Practical examples:
  - EN: `LICENSE_GUIDE_EN.md`
  - PL: `LICENSE_GUIDE_PL.md`
  - DE: `LICENSE_GUIDE_DE.md`
  - ES: `LICENSE_GUIDE_ES.md`
  - FR: `LICENSE_GUIDE_FR.md`
  - PT: `LICENSE_GUIDE_PT.md`
