# Repo Layout

- project-tkinter/          # Desktop app in Python + Tkinter (pelny projekt)
- project-web-desktop/      # Wariant Electron + Python API

Kazdy projekt jest odseparowany i ma wlasne pliki potrzebne do dzialania.

## Variant 0 (shared core)
- Wspolna logika runtime (budowa komendy, walidacja, listing modeli) jest w `project-tkinter/runtime_core.py`.
- Backend webowy (`project-web-desktop/backend/app.py`) importuje ten sam core.
- Kanoniczny translator to `project-tkinter/tlumacz_ollama.py` (web ma fallback do lokalnej kopii engine).
