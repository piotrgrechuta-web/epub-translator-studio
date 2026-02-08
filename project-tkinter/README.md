# EPUB Translator Studio (Tkinter)

Glowny wariant aplikacji desktop do pracy z EPUB.

Keywords: `EPUB`, `translator`, `AI`, `Ollama`, `Google Gemini`, `QA`, `TM`, `Tkinter`.

## Funkcje
- tlumaczenie EPUB i redakcja (`translate` / `edit`),
- walidacja EPUB,
- Translation Memory (SQLite),
- segment ledger w SQLite (`PENDING/PROCESSING/COMPLETED/ERROR`) dla idempotentnego resume,
- QA findings, workflow statusow i QA gate,
- opcjonalny hard gate `EPUBCheck` po runie (blokada finalizacji przy bledzie struktury),
- kolejka projektow (`pending`, `run all`),
- przypisanie projektu do serii (manualne i autodetekcja z metadanych EPUB),
- slownik serii (proposed/approved/rejected) + eksport glosariusza serii,
- scalanie glosariusza projektu z zatwierdzonym slownikiem serii podczas runu,
- narzedzia techniczne EPUB:
  - dodanie wizytowki,
  - usuniecie okladki lub grafik po regexie,
  - edycja tekstu segmentow.

## Uruchomienie
W katalogu `project-tkinter`:

```powershell
python app_main.py --variant classic
```

Wariant motywu:
```powershell
python app_main.py --variant horizon
```

Dodatkowe launchery:
- `python launcher_classic.py`
- `python launcher_horizon.py`

## Pierwsze uruchomienie (wymagane)
- Lokalnie (Ollama): zainstalowana Ollama + co najmniej jeden model.
- Online (np. Google Gemini): poprawny klucz API (`GOOGLE_API_KEY`) + internet.

Windows (PowerShell):
```powershell
winget install Ollama.Ollama
ollama pull llama3.1:8b
setx GOOGLE_API_KEY "<TWOJ_KLUCZ>"
```

Linux/macOS:
```bash
curl -fsSL https://ollama.com/install.sh | sh
ollama pull llama3.1:8b
export GOOGLE_API_KEY="<TWOJ_KLUCZ>"
```

## Najwazniejsze pliki
- `app_main.py` - launcher wariantow GUI (`classic`/`horizon`),
- `app_gui_classic.py` - glowne GUI,
- `app_gui_horizon.py` - wariant Horizon,
- `launcher_classic.py` - launcher classic,
- `launcher_horizon.py` - launcher horizon,
- `studio_suite.py` - Studio Tools,
- `project_db.py` - baza projektu, runy, QA, TM,
- `series_store.py` - baza serii, terminy i eksport/scalanie glosariusza serii,
- `runtime_core.py` - wspolna logika runtime (uzywana tez przez web backend),
- `translation_engine.py` - silnik tlumaczenia.

## Dane lokalne serii
- `project-tkinter/data/series/<series-slug>/series.db` - lokalna baza terminow i decyzji serii.
- `project-tkinter/data/series/<series-slug>/generated/approved_glossary.txt` - eksport zatwierdzonego slownika serii.

## Dokumentacja
- pelny manual uzytkownika: `MANUAL_PL.md`
- workflow Git na wielu komputerach: `GIT_WORKFLOW_PL.md`

## Wymagania AI (konieczne)
- Lokalnie: zainstalowana Ollama + co najmniej jeden model (np. `ollama pull llama3.1:8b`).
- Online (np. Google Gemini): poprawny klucz API (`GOOGLE_API_KEY` lub pole w GUI).
- Dla providerow online wymagany jest internet.
