# EPUB Translator Studio

Desktop toolkit do tlumaczenia i redakcji plikow EPUB z uzyciem AI.

Keywords: `EPUB translator`, `AI translation`, `Ollama`, `Google Gemini`, `Translation Memory`, `QA`, `Tkinter`, `Electron`, `FastAPI`, `Python`.

## Co to robi
- tlumaczenie EPUB (`translate`) i redakcja (`edit`),
- walidacja EPUB po obrobce,
- Translation Memory (TM) i cache segmentow,
- QA findings + QA gate,
- operacje na EPUB: wizytowka, usuwanie okladki/grafik, edycja segmentow,
- praca kolejkowa (`pending`, `run all`).

## Warianty aplikacji
- `project-tkinter/`
  - glowna wersja desktop w Python + Tkinter,
  - najpelniejszy zestaw funkcji.
- `project-web-desktop/`
  - wariant Electron + FastAPI,
  - webowy interfejs desktopowy.

## Szybki start

### Tkinter (glowny)
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

## Architektura (Variant 0: shared core)
- wspolna logika runtime jest w `project-tkinter/runtime_core.py`,
- backend web (`project-web-desktop/backend/app.py`) korzysta z tego samego core,
- kanoniczny translator: `project-tkinter/tlumacz_ollama.py`,
- fallback dla web: `project-web-desktop/backend/engine/tlumacz_ollama.py`.

Dzieki temu poprawki logiki uruchamiania i komend sa wspolne dla obu wariantow.

## Dokumentacja
- manual użytkownika (PL): `project-tkinter/MANUAL_PL.md`
- workflow Git (multi-device): `project-tkinter/GIT_WORKFLOW_PL.md`
- wsparcie projektu: `SUPPORT_PL.md`

## Wsparcie projektu
- Sponsor: https://github.com/sponsors/piotrgrechuta-web
- link do wsparcia jest tez w UI aplikacji (`Wesprzyj projekt`).
