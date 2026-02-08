# EPUB Translator Studio

Sprache: [English](README.md) | [Polski](README.pl.md) | **Deutsch** | [Espanol](README.es.md) | [Francais](README.fr.md) | [Portugues](README.pt.md)

Desktop-Toolkit fuer Uebersetzung und Bearbeitung von EPUB-Dateien mit KI.

KEYWORDS: `EPUB Uebersetzer`, `EPUB Uebersetzungswerkzeug`, `KI Uebersetzung`, `ebook Uebersetzer`, `Ollama`, `Google Gemini`, `Translation Memory`, `QA Gate`, `Tkinter`, `Electron`, `FastAPI`, `Python`.

## Funktionen
- EPUB Uebersetzung (`translate`) und Nachbearbeitung (`edit`)
- EPUB Validierung
- Translation Memory (TM) und Segment-Cache
- QA Findings Workflow und QA Gate
- EPUB Operationen: Front Card, Cover/Bild-Entfernung, Segment-Editor
- Projektwarteschlange (`pending`, `run all`)

## Varianten
- `project-tkinter/` (Hauptvariante, Python + Tkinter)
- `project-web-desktop/` (Electron + FastAPI)
- `legacy/` (archivierte Root-Skripte, nicht empfohlen)

## Schnellstart

### Tkinter
```powershell
cd project-tkinter
python app_main.py --variant classic
```

### Web Desktop
```powershell
cd project-web-desktop
.\run-backend.ps1
.\run-desktop.ps1
```

## Voraussetzungen
- Lokale KI mit Ollama: Ollama installieren und mindestens ein Modell laden (z. B. `ollama pull llama3.1:8b`).
- Online-KI (z. B. Google Gemini): gueltigen API-Key setzen (`GOOGLE_API_KEY` oder GUI-Feld).
- Fuer Online-Provider ist Internetzugang erforderlich.

## Dokumentation
- Benutzerhandbuch (PL): `project-tkinter/MANUAL_PL.md`
- Git Workflow (PL): `project-tkinter/GIT_WORKFLOW_PL.md`
- Support Info (PL): `SUPPORT_PL.md`

## Lizenz
- Lizenz: `EPUB Translator Studio Personal Use License v1.0` (`LICENSE`)
- Dieses Projekt ist source-available und kein OSI/FSF Open Source.
- Kostenfrei ist nur private Nutzung unveraenderter Kopien.
- Jede Aenderung, Weitergabe oder kommerzielle Nutzung braucht eine vorherige schriftliche Genehmigung (`COMMERCIAL_LICENSE.md`).
- Praxisbeispiele (DE): `LICENSE_GUIDE_DE.md`
