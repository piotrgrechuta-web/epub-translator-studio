# 04. Architektura i struktura repo

## 4.1. Widok ogolny

Repo koncentruje sie na jednym aktywnie rozwijanym wariancie aplikacji:
- `project-tkinter/` (UI desktop Python),
- `legacy/` (starsze punkty startowe),
- `.github/` (workflow i szablony community).

## 4.2. Tkinter

Kluczowe obszary:
- `app_main.py` - launcher wariantow GUI (`classic`/`horizon`),
- `app_gui_classic.py` - glowny UI i orchestracja,
- `app_gui_horizon.py` - wariant Horizon,
- `runtime_core.py` - wspolna logika runtime,
- `translation_engine.py` - mechanika tlumaczenia,
- `project_db.py` - baza i metadane projektowe,
- `series_store.py` - per-seria magazyn terminow/decyzji i generowanie slownikow serii.

## 4.3. Przeplyw danych

Typowy przeplyw:
1. Uzytkownik wybiera pliki i profil.
2. Runtime buduje polecenie dla silnika.
3. Silnik wykonuje translacje/edycje.
4. QA i walidacja raportuja wynik.
5. Artefakty trafiaja do output/debug.

Nowy przeplyw serii:
1. Projekt moze miec `series_id` i `volume_no`.
2. UI laduje/zapisuje serie z `project_db.py`.
3. Dla aktywnej serii `series_store.py` buduje scalony slownik runu.
4. Po udanym runie terminy z TM projektu moga byc dopisane jako `proposed` w bazie serii.
5. Operator zatwierdza terminy w panelu `Slownik serii`.

## 4.4. Warstwy odpowiedzialnosci

- UI: input, konfiguracja, status.
- Runtime: walidacja opcji i budowanie komend.
- Engine: wykonanie translacji.
- QA: kontrole jakosci i bramki.
- Series memory: terminologia i decyzje serii (`data/series/<slug>/series.db`).

## 4.5. Co zmieniac ostroznie

- format argumentow CLI miedzy UI a engine,
- sciezki i nazwy plikow cache/glossary,
- operacje na lokalnych bazach i lockach,
- zachowanie retry/backoff.
- migracje schematu SQLite (w tym samonaprawa brakujacych kolumn).

## 4.6. Miejsca do rozwoju

- testy integracyjne runtime,
- mocniejsze typowanie i walidacja kontraktow,
- automatyzacja release notes,
- telemetryjny health-check offline/online providerow.
- rozszerzenie `series_store.py` o lorebook i reguly stylu per seria.
