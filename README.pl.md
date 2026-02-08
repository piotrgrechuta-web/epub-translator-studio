# EPUB Translator Studio

Jezyk: [English](README.md) | **Polski** | [Deutsch](README.de.md) | [Espanol](README.es.md) | [Francais](README.fr.md) | [Portugues](README.pt.md)

Desktopowy zestaw narzedzi do tlumaczenia i redakcji plikow EPUB z AI.

KEYWORDS: `tlumacz EPUB`, `narzedzie do tlumaczenia EPUB`, `tlumaczenie AI`, `tlumacz ebookow`, `Ollama`, `Google Gemini`, `Translation Memory`, `QA gate`, `Tkinter`, `Python`.


## Co to robi
- tlumaczenie EPUB (`translate`) i redakcja (`edit`)
- walidacja EPUB
- Translation Memory (TM) i cache segmentow
- workflow findings QA i QA gate
- operacje EPUB: wizytowka, usuwanie okladki/grafik, edytor segmentow
- praca kolejka projektow (`pending`, `run all`)

## Warianty aplikacji
- `project-tkinter/`
  - glowna aplikacja desktop w Python + Tkinter
  - najpelniejszy zestaw funkcji
- `legacy/`
  - zarchiwizowane skrypty z dawnego ukladu (`legacy/start.py`, `legacy/tlumacz_ollama.py`)
  - nie jest to zalecana sciezka uruchamiania

## Szybki start

### Tkinter (glowny)
```powershell
cd project-tkinter
python app_main.py --variant classic
```

Aliasy kompatybilnosci nadal dzialaja:
- `python start.py`
- `python start_horizon.py`

## Pierwsze uruchomienie
- Potrzebujesz jednej z drog:
  - AI lokalnie: zainstalowana Ollama + co najmniej jeden model,
  - AI online: poprawny klucz API (`GOOGLE_API_KEY`) + internet.

### Komendy instalacji Ollama
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

### Klucz API dla providera online
Windows (PowerShell):
```powershell
setx GOOGLE_API_KEY "<TWOJ_KLUCZ>"
```

Linux/macOS:
```bash
export GOOGLE_API_KEY="<TWOJ_KLUCZ>"
```

## Wymagania
- Lokalny AI (Ollama): zainstalowana Ollama oraz pobrany co najmniej jeden model (np. `ollama pull llama3.1:8b`).
- AI online (np. Google Gemini): ustawiony poprawny klucz API (`GOOGLE_API_KEY` lub pole w GUI).
- Dla providerow online potrzebny jest internet.

## Architektura (Tkinter core)
- wspolna logika runtime jest w `project-tkinter/runtime_core.py`
- kanoniczny translator: `project-tkinter/tlumacz_ollama.py`
- oba warianty UI (`classic`, `horizon`) korzystaja z tej samej logiki runtime

## Dokumentacja
- manual uzytkownika Tkinter (PL): `project-tkinter/MANUAL_PL.md`
- workflow Git na wielu komputerach: `project-tkinter/GIT_WORKFLOW_PL.md`
- informacje o wsparciu: `SUPPORT_PL.md`
- portal dokumentacji online: `https://piotr-grechuta.github.io/epub-translator-studio/`
- gdzie widac postep/UI/Wiki: `docs/08-Status-UI-i-Wiki.md`

## Wsparcie
- Sponsor: https://github.com/sponsors/Piotr-Grechuta
- link wsparcia jest tez bezposrednio w UI aplikacji Tkinter (`Wesprzyj projekt`)
- gotowy szablon PL do uzupelnienia GitHub Sponsors: `.github/SPONSORS_PROFILE_TEMPLATE_PL.md`
- gotowy pakiet PL do promocji (posty/CTA do release): `.github/SPONSORS_OUTREACH_PACK_PL.md`
- szablony community (zgloszenia i PR): `.github/ISSUE_TEMPLATE/`, `.github/PULL_REQUEST_TEMPLATE.md`
- pakiet ustawien strony repo (description/website/topics): `.github/REPO_PROFILE_SETUP_PL.md`
- gotowy szkic pierwszego release (PL): `.github/RELEASE_DRAFT_PL.md`

## Licencja
- Licencja: `EPUB Translator Studio Personal Use License v1.0` (`LICENSE`)
- Ten projekt jest source-available i nie jest open source (OSI/FSF).
- Darmowe jest prywatne uzycie niezmienionej wersji.
- Kazda modyfikacja, redystrybucja lub uzycie komercyjne wymaga pisemnej zgody (`COMMERCIAL_LICENSE.md`).
- Proste przyklady:
  - EN: `LICENSE_GUIDE_EN.md`
  - PL: `LICENSE_GUIDE_PL.md`
  - DE: `LICENSE_GUIDE_DE.md`
  - ES: `LICENSE_GUIDE_ES.md`
  - FR: `LICENSE_GUIDE_FR.md`
  - PT: `LICENSE_GUIDE_PT.md`



