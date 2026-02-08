# 05. CI/CD i jakosc

## 5.1. Obecne workflow

### PR checks

Plik: `.github/workflows/pr-checks.yml`

Uruchamia sie na:
- `push` do `main`,
- `pull_request` do `main`,
- recznie (`workflow_dispatch`).

Sprawdza:
- Python lint (krytyczne bledy: E9/F63/F7/F82),
- syntax smoke (`py_compile`) dla entrypointow,
- testy jednostkowe parsera EPUB (`project-tkinter/tests`),
- smoke runtime/UI (`project-tkinter/scripts/smoke_gui.py`).

### PR description check

Plik: `.github/workflows/pr-description-check.yml`

Wymusza jakosc opisu PR:
- sekcje obowiazkowe,
- brak placeholderow,
- min. poziom wypelnienia checklisty.

### Security scans

Plik: `.github/workflows/security-scans.yml`

Sprawdza:
- sekrety (gitleaks),
- audit zaleznosci Python (`pip-audit` report),
- gate krytycznych podatnosci (Trivy, severity `CRITICAL`).

## 5.2. Ochrona galezi

Aktywna docelowo na `main`:
- PR wymagany,
- minimum 1 approval,
- status checks wymagane,
- force-push zablokowany,
- usuwanie galezi zablokowane,
- wymagane rozwiazanie rozmow.

## 5.3. Definicja "done"

Zmiana jest gotowa, gdy:
1. checki CI sa zielone,
2. PR ma sensowny opis,
3. jest review i approval,
4. brak konfliktu z branch protection.

## 5.4. Zalecane rozszerzenia CI

Kolejne sensowne kroki:
- testy integracyjne na zestawie przykladowych EPUB,
- raport pokrycia testami dla parsera i runtime,
- okresowy nightly scan zaleznosci z artefaktami raportow.

## 5.5. Dlaczego ten poziom jest dobry na teraz

To jest balans miedzy:
- szybkoscia developmentu,
- a kontrola regresji krytycznych sciezek.

Nie przeladowuje pipeline, ale lapie najczestsze awarie.
