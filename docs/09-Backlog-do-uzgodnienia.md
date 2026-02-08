# 09. Backlog do uzgodnienia

Status:
- `M1 wdrozone` w kodzie i dokumentacji (2026-02-08),
- `M2 wdrozone` w kodzie i CI (2026-02-08),
- `M3 w toku`: Issue 8 i 9 `zrealizowane`, Issue 7 `do domkniecia` (inicjalizacja Wiki backend),
- `M4 plan zatwierdzony`: kontekst tlumaczenia + spojnosc postaci,
- `M5 plan zatwierdzony`: ochrona tekstu (`&shy;`) + diff-aware retranslation,
- `M6 plan zatwierdzony`: QA polszczyzny + tryb czytaj/tlumacz/wroc,
- `M7 plan zatwierdzony`: batch library + pamiec stylu serii.

## Cel

Zamienic roadmape na konkretne, mierzalne zadania z jasnym zakresem i kryteriami akceptacji.

## Aktywne milestone'y

1. `M3: Workflow + Docs + Wiki (domkniecie)`
2. `M4: Context-Aware Translation`
3. `M5: Text Integrity + Diff-Retranslation`
4. `M6: Polish QA + Live Reading Loop`
5. `M7: Batch Library + Style Memory`

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

## M4: Context-Aware Translation

Status M4: `plan`.

### Issue 10: Kontekst poza segmentem
- Zakres:
  - przekazywanie okna kontekstu (poprzedni/nastepny segment, tytul rozdzialu) do promptu,
  - konfiguracja dlugosci kontekstu per run.
- Done:
  - mniej bledow typu "kim jest she/he" w dialogach bez znacznikow speakera,
  - testy parsera potwierdzaja brak regresji tagow inline.

### Issue 11: Pamiec encji i spojnosci postaci
- Zakres:
  - lekka pamiec encji (imiona, aliasy, relacje) na poziomie ksiazki,
  - automatyczne flagi QA przy zmianie nazwy postaci bez uzasadnienia.
- Done:
  - raport niespojnosci nazw po runie,
  - mozliwosc zatwierdzenia kanonicznej formy w UI.

## M5: Text Integrity + Diff-Retranslation

Status M5: `plan`.

### Issue 12: Ochrona hyphenation i `&shy;`
- Zakres:
  - zachowanie `&shy;`/nbsp i krytycznych encji typograficznych podczas translacji i redakcji,
  - walidator integralnosci znakow specjalnych.
- Done:
  - brak utraty `&shy;` po translacji,
  - testy automatyczne porownuja liczbe i pozycje kluczowych encji.

### Issue 13: Diff-aware retranslation
- Zakres:
  - retranslacja tylko zmienionych segmentow po poprawce zrodla,
  - opcjonalna retranslacja sasiedztwa (N segmentow) dla spojnosci.
- Done:
  - raport: `changed/reused/retranslated`,
  - brak potrzeby pelnej retranslacji po drobnych poprawkach.

## M6: Polish QA + Live Reading Loop

Status M6: `plan`.

### Issue 14: Walidacja polszczyzny specyficznej
- Zakres:
  - zestaw regulek QA (liczebniki, przypadki, kolokacje stylu literackiego),
  - klasyfikacja findings: `info/warn/error`.
- Done:
  - lista findings z podpowiedzia korekty,
  - eksport raportu QA dla redakcji.

### Issue 15: Tryb "tlumaczenie na zywo podczas czytania"
- Zakres:
  - workflow: tlumacz fragment -> czytaj na czytniku -> wznow od punktu,
  - checkpointy per rozdzial i per run.
- Done:
  - wznowienie bez utraty historii i cache,
  - w UI widac, ktore fragmenty sa "po lekturze" i "do poprawy".

## M7: Batch Library + Style Memory

Status M7: `plan`.

### Issue 16: Profile stylu serii
- Zakres:
  - profile stylu i tonu reuzywalne miedzy ksiazkami,
  - mapowanie projektu do profilu stylu.
- Done:
  - profil stylu mozna przypisac i eksportowac/importowac,
  - nowy projekt moze dziedziczyc styl poprzednich tomow.

### Issue 17: Batch library z pamiecia stylu
- Zakres:
  - kolejkowanie wielu ksiazek ze wspolnym stylem i pamiecia encji,
  - globalny panel postepu biblioteki + postep per ksiazka.
- Done:
  - uruchomienie wsadowe wielu EPUB w jednym runie,
  - raport koncowy porownuje jakosc i spojnosc miedzy tomami.

## Kolejnosc realizacji (zaktualizowana)

1. Domkniecie `M3 / Issue 7` (Wiki backend + Home + sidebar).
2. `M5` (najszybszy zysk produkcyjny: `&shy;` + diff-aware).
3. `M4` (kontekst i spojnosc postaci).
4. `M6` (QA jezykowe + loop czytelniczy).
5. `M7` (tryb serii i batch library).

## Definicja publikacji milestone

Milestone publikujemy jako "gotowy do realizacji", gdy:
1. kazde issue ma zakres + kryteria `Done`,
2. kazde issue ma etykiete i priorytet,
3. jest podana kolejnosc wdrozenia (co first, co later),
4. zespol zna zaleznosci miedzy issue.
