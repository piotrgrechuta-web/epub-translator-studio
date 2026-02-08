# 09. Backlog do uzgodnienia

Status:
- `M1 wdrozone` w kodzie i dokumentacji (2026-02-08),
- `M2 wdrozone` w kodzie i CI (2026-02-08),
- `M3 czesciowo wdrozone`: Issue 8 i 9 `zrealizowane`, Issue 7 `w toku` (inicjalizacja Wiki backend).

## Cel

Zamienic roadmape na konkretne, mierzalne zadania z jasnym zakresem i kryteriami akceptacji.

## Proponowane milestone'y

1. `M1: UI Consistency + UX Telemetry`
2. `M2: CI Hardening + Test Coverage`
3. `M3: Workflow + Docs + Wiki`

## M1: UI Consistency + UX Telemetry

Status M1: `zrealizowane`.

### Issue 1: Ujednolicenie statusow etapow (Tkinter classic + horizon)
- Zakres:
  - jedno slownictwo i mapowanie statusow (`idle/pending/running/ok/error`) w obu interfejsach,
  - jeden format podsumowania projektu.
- Done:
  - te same statusy widoczne w obu wariantach Tkinter (`classic` i `horizon`),
  - test manualny: ten sam projekt pokazuje zgodne statusy po odswiezeniu UI.

### Issue 2: Panel "Ostatnie akcje" (inline timeline)
- Zakres:
  - timeline ostatnich zdarzen runu/projektu bez otwierania osobnego popupu,
  - stale miejsce na ekranie glownym.
- Done:
  - min. 20 ostatnich wpisow,
  - wpis zawiera czas + krok + status + skrot komunikatu.

### Issue 3: Mini-metryki runu
- Zakres:
  - czas runu,
  - segmenty przetworzone,
  - hit-rate cache/TM.
- Done:
  - metryki widoczne po zakonczeniu runu w obu wariantach Tkinter,
  - brak regresji aktualnego logowania.

## M2: CI Hardening + Test Coverage

Status M2: `zrealizowane`.

### Issue 4: Testy jednostkowe parsera EPUB
- Zakres:
  - testy OPF/spine/manifest,
  - testy bezpiecznej segmentacji XHTML (inline tags).
- Done:
  - testy uruchamiane w CI,
  - minimalne pokrycie dla krytycznych sciezek parsera.

### Issue 5: Smoke runtime/UI Tkinter
- Zakres:
  - smoke uruchomienia GUI i warstwy runtime (`project-tkinter/scripts/smoke_gui.py`),
  - szybka walidacja startu i podstawowych przejsc statusow projektu.
- Done:
  - zielony smoke w PR checks,
  - czytelny raport bledu przy regresji.

### Issue 6: Skan sekretow i zaleznosci
- Zakres:
  - skan sekretow w CI,
  - podstawowy audit zaleznosci.
- Done:
  - workflow blokuje merge przy krytycznych wynikach.

## M3: Workflow + Docs + Wiki

Status M3: `w toku` (2/3 issue zamkniete).

### Issue 7: Inicjalizacja i utrzymanie Wiki
- Zakres:
  - utworzenie pierwszej strony wiki (`Home`),
  - dodanie menu bocznego i linkow do `docs/`.
- Done:
  - `/wiki` dziala bez przekierowania na strone repo,
  - wiki ma minimum 1 strone i sidebar.
  
Status: `w toku` (backend Wiki wymaga inicjalizacji pierwszej strony `Home`).

### Issue 8: Release checklist i changelog discipline
- Zakres:
  - szablon release notes z sekcjami: zmiany, ryzyka, migracja, testy,
  - checklista przed tagiem/release.
- Done:
  - kazdy release ma jednolity opis i jasny scope.

Status: `zrealizowane`.

### Issue 9: Dokumentacja "2 komputery" + odzyskiwanie po awarii
- Zakres:
  - dopisanie scenariuszy odzyskiwania (db/cache/lock),
  - szybki playbook "co robic po crashu".
- Done:
  - instrukcja krok-po-kroku w `docs/03` lub nowym rozdziale.

Status: `zrealizowane`.

## Kolejnosc realizacji (propozycja)

1. M1 (widoczne efekty dla uzytkownika od razu)
2. M2 (stabilnosc i bezpieczenstwo procesu wydawniczego)
3. M3 (dokumentacja, wiki, release discipline)

## Pytania do zatwierdzenia przed publikacja Issues

1. Czy publikujemy wszystkie 9 issue od razu, czy tylko M1 jako sprint 1?
2. Czy chcesz etykiety (`ui`, `backend`, `ci`, `docs`, `priority-high`)?
3. Czy milestone'y ustawic na daty, czy bez dat (rolling)?
