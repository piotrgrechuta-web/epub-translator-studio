# EPUB Translator Studio

Langue: [English](README.md) | [Polski](README.pl.md) | [Deutsch](README.de.md) | [Espanol](README.es.md) | **Francais** | [Portugues](README.pt.md)

Boite a outils desktop pour traduire et editer des fichiers EPUB avec IA.

KEYWORDS: `traducteur EPUB`, `outil de traduction EPUB`, `traduction IA`, `traducteur ebook`, `Ollama`, `Google Gemini`, `Translation Memory`, `QA gate`, `Tkinter`, `Electron`, `FastAPI`, `Python`.

## Fonctions
- Traduction EPUB (`translate`) et post-edition (`edit`)
- Validation EPUB
- Translation Memory (TM) et cache de segments
- Workflow QA findings et QA gate
- Operations EPUB: front card, suppression couverture/images, editeur de segments
- File de projets (`pending`, `run all`)

## Variantes
- `project-tkinter/` (variante principale, Python + Tkinter)
- `project-web-desktop/` (Electron + FastAPI)
- `legacy/` (scripts racine archives, non recommande)

## Demarrage rapide

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

## Prerequis
- IA locale avec Ollama: installer Ollama et recuperer au moins un modele (exemple: `ollama pull llama3.1:8b`).
- IA en ligne (exemple Google Gemini): definir une API key valide (`GOOGLE_API_KEY` ou champ GUI).
- Un acces internet est requis pour les providers en ligne.

## Documentation
- Manuel utilisateur (PL): `project-tkinter/MANUAL_PL.md`
- Workflow Git (PL): `project-tkinter/GIT_WORKFLOW_PL.md`
- Infos support (PL): `SUPPORT_PL.md`

## Licence
- Licence: `EPUB Translator Studio Personal Use License v1.0` (`LICENSE`)
- Ce projet est source-available et n'est pas open source OSI/FSF.
- L'usage prive de copies non modifiees est gratuit.
- Toute modification, redistribution ou usage commercial exige un accord ecrit prealable (`COMMERCIAL_LICENSE.md`).
- Exemples pratiques (FR): `LICENSE_GUIDE_FR.md`
