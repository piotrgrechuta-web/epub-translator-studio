# EPUB Translator Studio (Tkinter)

Główny wariant aplikacji desktop do pracy z EPUB.

Keywords: `EPUB`, `translator`, `AI`, `Ollama`, `Google Gemini`, `QA`, `TM`, `Tkinter`.

## Funkcje
- tłumaczenie EPUB i redakcja (`translate` / `edit`),
- walidacja EPUB,
- Translation Memory (SQLite),
- QA findings, workflow statusów i QA gate,
- kolejka projektów (`pending`, `run all`),
- narzędzia techniczne EPUB:
  - dodanie wizytówki,
  - usunięcie okładki lub grafik po regexie,
  - edycja tekstu segmentów.

## Uruchomienie
W katalogu `project-tkinter`:

```powershell
python start.py
```

Wariant motywu:
```powershell
python start_horizon.py
```

## Najważniejsze pliki
- `start.py` - główne GUI,
- `studio_suite.py` - Studio Tools,
- `project_db.py` - baza projektu, runy, QA, TM,
- `runtime_core.py` - wspólna logika runtime (używana też przez web backend),
- `tlumacz_ollama.py` - silnik tłumaczenia.

## Dokumentacja
- pełny manual użytkownika: `MANUAL_PL.md`
- workflow Git na wielu komputerach: `GIT_WORKFLOW_PL.md`
