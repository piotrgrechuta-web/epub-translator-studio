# 04. Architektura i struktura repo

## 4.1. Widok ogolny

Repo laczy 2 warianty aplikacji:
- `project-tkinter/` (UI desktop Python),
- `project-web-desktop/` (Electron + FastAPI).

Dodatkowo:
- `legacy/` zawiera starsze punkty startowe,
- `.github/` zawiera workflow i szablony community.

## 4.2. Tkinter

Kluczowe obszary:
- `app_main.py` - launcher wariantow GUI (`classic`/`horizon`),
- `app_gui_classic.py` - glowny UI i orchestracja,
- `app_gui_horizon.py` - wariant Horizon,
- `runtime_core.py` - wspolna logika runtime,
- `tlumacz_ollama.py` - mechanika tlumaczenia,
- `project_db.py` - baza i metadane projektowe.

## 4.3. Web desktop

- `backend/app.py` - API FastAPI i logika backendu,
- `desktop/` - Electron shell + renderer,
- `run-backend.ps1` i `run-desktop.ps1` - lokalny bootstrap.

## 4.4. Przeplyw danych

Typowy przeplyw:
1. Uzytkownik wybiera pliki i profil.
2. Runtime buduje polecenie dla silnika.
3. Silnik wykonuje translacje/edycje.
4. QA i walidacja raportuja wynik.
5. Artefakty trafiaja do output/debug.

## 4.5. Warstwy odpowiedzialnosci

- UI: input, konfiguracja, status.
- Runtime: walidacja opcji i budowanie komend.
- Engine: wykonanie translacji.
- QA: kontrole jakosci i bramki.

## 4.6. Co zmieniac ostroznie

- format argumentow CLI miedzy UI a engine,
- sciezki i nazwy plikow cache/glossary,
- operacje na lokalnych bazach i lockach,
- zachowanie retry/backoff.

## 4.7. Miejsca do rozwoju

- testy integracyjne runtime,
- mocniejsze typowanie i walidacja kontraktow,
- automatyzacja release notes,
- telemetryjny health-check offline/online providerow.
