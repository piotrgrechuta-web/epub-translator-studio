# EPUB Translator Studio (Tkinter)

Glowny wariant aplikacji desktop do pracy z EPUB.

Keywords: `EPUB`, `translator`, `AI`, `Ollama`, `Google Gemini`, `QA`, `TM`, `Tkinter`.

## Funkcje
- tlumaczenie EPUB i redakcja (`translate` / `edit`),
- walidacja EPUB,
- Translation Memory (SQLite),
- QA findings, workflow statusow i QA gate,
- kolejka projektow (`pending`, `run all`),
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

Aliasy kompatybilnosci (legacy):
- `python start.py`
- `python start_horizon.py`

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
- `start.py` - alias kompatybilnosci (classic),
- `start_horizon.py` - alias kompatybilnosci (horizon),
- `studio_suite.py` - Studio Tools,
- `project_db.py` - baza projektu, runy, QA, TM,
- `runtime_core.py` - wspolna logika runtime (uzywana tez przez web backend),
- `tlumacz_ollama.py` - silnik tlumaczenia.

## Dokumentacja
- pelny manual uzytkownika: `MANUAL_PL.md`
- workflow Git na wielu komputerach: `GIT_WORKFLOW_PL.md`

## Wymagania AI (konieczne)
- Lokalnie: zainstalowana Ollama + co najmniej jeden model (np. `ollama pull llama3.1:8b`).
- Online (np. Google Gemini): poprawny klucz API (`GOOGLE_API_KEY` lub pole w GUI).
- Dla providerow online wymagany jest internet.
