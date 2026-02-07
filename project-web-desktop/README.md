# Translator Studio Desktop (Web)

Projekt web/desktop (Electron + FastAPI) z funkcjonalnością operacyjną zbliżoną do wersji Tkinter:
- konfiguracja parametrów runu,
- start tłumaczenia,
- start walidacji EPUB,
- stop procesu,
- status procesu i log live,
- zapis/odczyt konfiguracji,
- pobieranie list modeli (Ollama/Google).

## Struktura
- `backend/` API + runner procesu
- `backend/engine/` lokalna kopia `tlumacz_ollama.py`
- `desktop/` aplikacja Electron

## Szybki start
W katalogu `project-web-desktop`:

1. Backend:
```powershell
.\run-backend.ps1
```

2. Desktop:
```powershell
.\run-desktop.ps1
```

## Parametry
Frontend zapisuje config do `backend/ui_state.json`.
Domyślna baza TM: `backend/translator_studio.db`.

## Uwagi
To jest aktywnie rozwijany wariant webowy. Jeśli chcesz pełną 1:1 parytetową migrację wszystkich zakładek Studio/QA/TM z Tkintera, mogę kontynuować kolejne etapy bez zatrzymywania prac.

## Wariant 0 (wspolny core)
Backend webowy korzysta ze wspolnego modułu runtime z `project-tkinter/runtime_core.py`.
Priorytet translacji:
1. `project-tkinter/tlumacz_ollama.py` (kanoniczny),
2. fallback: `project-web-desktop/backend/engine/tlumacz_ollama.py`.

To oznacza, ze poprawki w logice uruchomienia/translacji z wariantu Tkinter są automatycznie widoczne w wariancie web-desktop.
