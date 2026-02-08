# 09. Backlog do uzgodnienia

Status:
- `M1 wdrozone` w kodzie i dokumentacji (2026-02-08),
- `M2 wdrozone` w kodzie i CI (2026-02-08),
- `M3 w toku`: Issue 8 i 9 `zrealizowane`, Issue 7 `do domkniecia` (inicjalizacja Wiki backend),
- `M4 plan zatwierdzony`: memory-first translation (cache + decision memory + adaptive prompting),
- `M5 plan zatwierdzony`: EPUB-aware segmentacja i integralnosc markup (`&shy;`, inline tags),
- `M6 plan zatwierdzony`: diff-aware retranslation + semantic diff gate do recenzji,
- `M7 w realizacji`: wdrozony szkielet serii (project->series, baza serii, manager terminow, merge glosariusza).

## Cel

Zamienic roadmape na konkretne, mierzalne zadania z jasnym zakresem i kryteriami akceptacji.

## Aktywne milestone'y

1. `M3: Workflow + Docs + Wiki (domkniecie)`
2. `M4: Memory-First Translation Engine`
3. `M5: EPUB-Aware Segmentation + Markup Integrity`
4. `M6: Smart Retranslation + Semantic Diff QA`
5. `M7: Series Style Memory + Batch Library`

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

## M4: Memory-First Translation Engine

Status M4: `plan`.

### Issue #26: Segment cache + hash reuse (book memory)
- Zakres:
  - zapis `hash(segment) -> translation` na poziomie ksiazki,
  - reuse juz przetlumaczonych segmentow bez ponownego kosztu API,
  - raport cache hit/miss po runie.
- Done:
  - ponowny run tej samej ksiazki reuzywa gotowe segmenty,
  - cache jest odporny na restart aplikacji,
  - metryki cache sa widoczne w podsumowaniu runu.

### Issue #27: Human-in-the-loop decision memory + adaptive few-shot
- Zakres:
  - zapamietywanie zatwierdzonych decyzji redaktora (`segment_hash -> approved_translation`),
  - automatyczne budowanie few-shot kontekstu dla kolejnych segmentow tej samej ksiazki,
  - priorytet decyzji redaktora nad surowym wynikiem modelu.
- Done:
  - narzedzie podpowiada kolejne tlumaczenia na bazie zatwierdzonych fragmentow,
  - decyzje redaktora sa trwale i wersjonowane,
  - wzrost spojnosci terminow bez recznego glosariusza.

## M5: EPUB-Aware Segmentation + Markup Integrity

Status M5: `plan`.

### Issue #28: EPUB-aware segmentacja (dialogi, cytaty, inline tags)
- Zakres:
  - segmentacja respektuje granice logiczne EPUB (dialogi, cytaty, naglowki),
  - nie rozcina krytycznych struktur inline (`<i>`, `<b>`, `<a>`),
  - testy regresji na trudnych fragmentach dialogowych.
- Done:
  - brak rozcietych dialogow i uszkodzen struktury XHTML po segmentacji,
  - testy parsera przechodza dla przypadkow dialog/cytat/inline,
  - output zachowuje poprawnosc renderingu.

### Issue #33: Ochrona `&shy;` i encji typograficznych
- Zakres:
  - zachowanie `&shy;`, `&nbsp;` i kluczowych encji podczas translacji/redakcji,
  - walidator integralnosci encji przed/po runie,
  - raport roznic encji do szybkiej kontroli.
- Done:
  - brak utraty `&shy;` po runie,
  - automatyczny test integralnosci encji przechodzi,
  - brak regresji czytelnosci na malych ekranach czytnikow.

## M6: Smart Retranslation + Semantic Diff QA

Status M6: `plan`.

### Issue #29: Diff-aware retranslation po zmianie zrodla
- Zakres:
  - wykrywanie zmienionych segmentow po edycji EPUB zrodlowego,
  - retranslacja tylko zmienionych (plus opcjonalne sasiedztwo N),
  - reuse cache/TM dla niezmienionych fragmentow.
- Done:
  - raport `changed/reused/retranslated`,
  - brak potrzeby pelnej retranslacji po drobnych poprawkach,
  - skrocony czas runu dla malych zmian.

### Issue #30: Semantic diff gate (embedding) dla recenzji
- Zakres:
  - porownanie semantyczne wersji tlumaczenia (embedding-based),
  - oznaczanie "zmiana sensu" vs "zmiana kosmetyczna",
  - priorytetyzacja segmentow do recenzji manualnej.
- Done:
  - segmenty o niskiej roznicy semantycznej moga byc auto-accepted,
  - segmenty o wysokiej roznicy trafiaja na liste recenzji,
  - raport QA pokazuje progi i decyzje bramki semantycznej.

## M7: Series Style Memory + Batch Library

Status M7: `w realizacji` (foundation deployed).

### Issue #31: Profile stylu serii (tone memory)
- Zakres:
  - profile stylu/tonu reuzywalne miedzy tomami,
  - przypisanie projektu do profilu stylu,
  - import/eksport i wersjonowanie profili.
- Done:
  - ten sam profil mozna stosowac w wielu ksiazkach serii,
  - profile sa latwe do backupu i przenoszenia,
  - widoczna poprawa spojnosci stylu miedzy tomami.

Status:
- `szkielet wdrozony`:
1. projekty maja `series_id` i `volume_no`,
2. autodetekcja serii z metadanych EPUB (`OPF`),
3. osobna baza serii (`data/series/<slug>/series.db`),
4. panel `Slownik serii` (approve/reject/manual add),
5. merge slownika serii z glosariuszem projektu na etapie runu.
- `do domkniecia`:
1. UI/DB dla jawnych "style rules" i "lorebook" per seria,
2. wersjonowanie profili stylu (diff + historia zmian).

### Issue #32: Batch library + opcjonalny tor LoRA/QLoRA
- Zakres:
  - batch processing wielu EPUB z jednym profilem stylu,
  - zbiorczy raport jakosci/spojnosci dla calej serii,
  - eksperymentalny tor eksportu danych pod lokalny fine-tuning (LoRA/QLoRA).
- Done:
  - mozliwe uruchomienie wsadowe wielu ksiazek,
  - raport koncowy jest czytelny per ksiazka i globalnie,
  - dokumentacja oddziela tryb produkcyjny od eksperymentalnego fine-tuning.

Status:
- `plan` (brak wdrozenia wsadowego orchestratora biblioteki serii).

## Kolejnosc realizacji (zaktualizowana)

1. Domkniecie `M3 / Issue 7` (Wiki backend + Home + sidebar).
2. Domkniecie `M7 / Issue 31` (style rules + lorebook + versioning).
3. `M4` (memory-first: cache + decision memory + adaptive few-shot).
4. `M5` (segmentacja EPUB + integralnosc markup).
5. `M6` (diff-aware + semantic diff gate).
6. `M7 / Issue 32` (skalowanie batch + opcjonalny fine-tuning).

## Definicja publikacji milestone

Milestone publikujemy jako "gotowy do realizacji", gdy:
1. kazde issue ma zakres + kryteria `Done`,
2. kazde issue ma etykiete i priorytet,
3. jest podana kolejnosc wdrozenia (co first, co later),
4. zespol zna zaleznosci miedzy issue.
