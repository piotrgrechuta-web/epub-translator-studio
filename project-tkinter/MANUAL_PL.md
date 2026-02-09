# EPUB Translator Studio (Tkinter) - Pelny manual dla poczatkujacego

Ten dokument jest napisany dla osoby, ktora:
- pierwszy raz uruchamia program,
- nie zna jeszcze terminologii technicznej,
- chce krok po kroku dojsc od pliku EPUB do gotowego wyniku,
- nie chce zgadywac co oznacza kazde pole w aplikacji.

Jesli chcesz po prostu uruchomic pierwsze tlumaczenie, przejdz od razu do sekcji `6. Pierwsze tlumaczenie krok po kroku`.

## 1. Co robi ten program

EPUB Translator Studio to aplikacja desktopowa do:
1. tlumaczenia ksiazek EPUB przy pomocy AI,
2. redakcji gotowego tlumaczenia,
3. kontroli jakosci (QA),
4. zarzadzania pamiecia tlumaczen (TM),
5. pracy seryjnej na wielu projektach.

Program nie zmienia oryginalnego pliku EPUB automatycznie. Zawsze pracujesz na wskazanych plikach wyjsciowych.

## 2. Czego potrzebujesz przed startem

Minimalnie:
1. System Windows/Linux/macOS.
2. Python 3.11 lub nowszy.
3. Plik EPUB do pracy.
4. Jedna z dwoch drog AI:
- lokalnie: Ollama + model,
- online: Google API key (Gemini).

## 3. Instalacja i uruchomienie

Przejdz do katalogu projektu:

```powershell
cd project-tkinter
```

Uruchom aplikacje (wariant classic, gdy jestes w `project-tkinter`):

```powershell
python app_main.py --variant classic
```

Wariant horizon (gdy jestes w `project-tkinter`):

```powershell
python app_main.py --variant horizon
```

Skroty startowe (gdy jestes w `project-tkinter`):

```powershell
python launcher_classic.py
python launcher_horizon.py
```

Jesli uruchamiasz z katalogu glownego repo (`epub-translator-studio`), uzyj:

```powershell
python project-tkinter/app_main.py --variant classic
python project-tkinter/app_main.py --variant horizon
```

## 4. Konfiguracja AI (konieczna)

### 4.1 Opcja A: Ollama lokalnie

Windows:

```powershell
winget install Ollama.Ollama
ollama pull llama3.1:8b
```

Po instalacji:
1. W aplikacji ustaw `Provider = ollama`.
2. Kliknij `Odswiez liste modeli`.
3. Wybierz model z listy.

### 4.2 Opcja B: Google Gemini

Ustaw klucz API (jedna z metod):

Windows:

```powershell
setx GOOGLE_API_KEY "<TWOJ_KLUCZ>"
```

Linux/macOS:

```bash
export GOOGLE_API_KEY="<TWOJ_KLUCZ>"
```

Albo wpisz klucz bezposrednio w polu `Google API key` w aplikacji.

Po konfiguracji:
1. Ustaw `Provider = google`.
2. Kliknij `Odswiez liste modeli`.
3. Wybierz model.

## 5. Jak myslec o pracy w programie

Najwazniejsze pojecia:

1. `Projekt`
- jeden tytul, zestaw plikow i ustawien,
- ma historie uruchomien, QA i dane TM.

2. `Tryb`
- `translate`: tlumaczenie,
- `edit`: redakcja gotowego tlumaczenia.

3. `Profil`
- zapisane ustawienia dla kroku `translate` albo `edit`.

4. `TM (Translation Memory)`
- lokalna baza par zrodlo -> tlumaczenie,
- obniza koszty i przyspiesza kolejne runy.

5. `Ledger`
- stan segmentow: `PENDING`, `PROCESSING`, `COMPLETED`, `ERROR`,
- pozwala wznowic prace po przerwaniu.

6. `QA gate`
- blokady jakosci przed uznaniem runu za zakonczony.

## 6. Pierwsze tlumaczenie krok po kroku

To jest najwazniejsza sekcja dla nowego uzytkownika.

### Krok 1: utworz projekt

1. Otworz aplikacje.
2. W sekcji `Projekt i profile` kliknij `Nowy`.
3. Podaj nazwe projektu, np. `Moja pierwsza ksiazka`.
4. Kliknij `Zapisz`.

### Krok 2: ustaw pliki

W sekcji `Pliki i tryb`:
1. `Wejsciowy EPUB`: wskaz oryginalna ksiazke.
2. `Wyjsciowy EPUB`: wskaz nowy plik, np. `book_pl.epub`.
3. `Prompt`: wybierz plik promptu (domyslnie moze byc `prompt.txt`).
4. `Tryb`: ustaw `translate`.
5. `Jezyk zrodlowy`: np. `en`.
6. `Jezyk docelowy`: np. `pl`.

### Krok 3: ustaw silnik

W sekcji `Silnik i parametry batch`:
1. `Provider`: `ollama` albo `google`.
2. Dla Google wpisz `Google API key` (jesli nie masz w env).
3. Kliknij `Odswiez liste modeli`.
4. Wybierz model.

### Krok 4: uruchom

W sekcji `Uruchomienie`:
1. Kliknij `Start translacji`.
2. Obserwuj log i pasek `Ledger status`.
3. Czekaj do komunikatu `RUN OK`.

### Krok 5: sprawdz wynik

1. Kliknij `Otworz output`.
2. Otworz plik EPUB w czytniku i sprawdz kilka rozdzialow.
3. Jesli chcesz dodatkowo walidacje techniczna, kliknij `Waliduj EPUB`.

To wszystko. Masz pierwszy kompletny przebieg.

## 7. Dokladny opis sekcji glownego okna

## 7.1 Projekt i profile

1. `Nowy`
- tworzy nowy projekt.

2. `Zapisz`
- zapisuje aktualne ustawienia projektu.

3. `Usun`
- usuwa projekt z listy (status logiczny), historia pozostaje.

4. `Usun hard`
- usuwa projekt trwale razem z danymi powiazanymi (TM projektu, historia).
- uzywaj ostroznie.

5. `Zapisz jako profil`
- zapisuje aktualna konfiguracje jako profil wielokrotnego uzycia.

6. `Eksport` / `Import`
- eksport/import konfiguracji i danych projektu.

7. `Seria` i `Tom`
- przypisanie projektu do serii wydawniczej.

## 7.2 Pliki i tryb

1. `Wejsciowy EPUB`
- plik zrodlowy.

2. `Wyjsciowy EPUB`
- plik docelowy dla aktualnego kroku.

3. `Prompt`
- instrukcja dla modelu AI.

4. `Slownik`
- opcjonalny glosariusz terminow.

5. `Cache`
- plik JSONL z pamiecia segmentow.

6. `Tryb`
- `translate` albo `edit`.

7. `Jezyk zrodlowy` i `Jezyk docelowy`
- para jezykowa wymuszana w runie.

## 7.3 Silnik i model

1. `Provider`
- `ollama` lokalnie,
- `google` online.

2. `Ollama host`
- adres uslugi ollama (domyslnie lokalny).

3. `Google API key`
- klucz dla Gemini.

4. `Prompt preset` + `Apply preset`
- gotowe style promptow, np. pod ksiazki lub redakcje.

5. `Odswiez liste modeli`
- pobiera modele dostepne dla wybranego providera.

6. `Health check I/O`
- uruchamia asynchroniczny preflight providerow (`ollama` i `google`) z telemetryka:
  status, opoznienie (ms) i liczba modeli.
- wynik trafia do statusu modelu i logu jako wpisy `[HEALTH]`.

## 7.4 Ustawienia zaawansowane

Najwazniejsze pola:
1. `Max segs / request`
- ile segmentow idzie na jedno zapytanie.

2. `Max chars / request`
- limit znakow na batch.

3. `Pauza miedzy requestami`
- opoznienie miedzy zapytaniami.

4. `Timeout`, `Attempts`, `Backoff`
- mechanizmy ponawiania przy bledach.

5. `Smart context window`
- liczba segmentow kontekstu przed i po aktualnym segmencie.
- przyklad: `5` oznacza `5 poprzednich + 5 nastepnych`.

6. `Context max chars (neighbor)` i `Context max chars (segment)`
- limity rozmiaru kontekstu (kontrola kosztu tokenow).
- im wyzsze, tym lepsza spojnosc, ale wiekszy koszt.

7. `I/O concurrency`
- liczba rownoleglych batchy translacji (AsyncIO) na provider.
- `1` = tryb sekwencyjny, `>1` = rownolegle dispatchowanie batchy.
- zwieksza przepustowosc dla providerow online, ale moze podniesc chwilowe zuzycie limitu API.

8. `Checkpoint co N plikow`
- zapis stanu wznowienia po rozdzialach.

9. `Hard gate EPUBCheck`
- blokuje finalizacje runu przy bledach struktury EPUB.

## 7.5 Uruchomienie

1. `Start translacji`
- uruchamia run dla aktywnego kroku.

2. `Stop`
- wysyla przerwanie procesu.

3. `Waliduj EPUB`
- uruchamia walidacje bez translacji.

4. `Ledger status`
- licznik segmentow `done/processing/error/pending`.

5. `Kolejkuj`, `Uruchom nastepny`, `Run all pending`
- sterowanie kolejka projektow.

6. `Otworz output`, `Otworz cache`, `Wyczysc debug`
- szybkie akcje operacyjne.

## 7.6 Uladnianie EPUB

1. `Dodaj wizytowke` (pojedynczo i folder)
- dokleja strone/karte poczatkowa.

2. `Usun okladke`
- usuwa elementy cover z EPUB.

3. `Usun grafiki (pattern)`
- usuwa grafiki pasujace do wzorca.

4. `Edytor tekstu EPUB`
- edycja segmentow z zachowaniem inline tagow.

5. `Cofnij ostatnia operacje`
- rollback ostatniej akcji narzedziowej.

## 8. Studio Tools - pelny przewodnik

Studio Tools to panel zaawansowany, ale nadal mozliwy do uzycia przez laika, jesli trzymasz sie kolejnosci.

## 8.1 Zakladka QA

Do czego sluzy:
- wykrywa problemy jakosci,
- zapisuje findings,
- pilnuje gate przed przejsciem dalej.

Praktyczny przebieg:
1. Wybierz EPUB.
2. Kliknij `Scan`.
3. Kliknij `Save findings`.
4. Przejrzyj liste i napraw problemy.
5. Oznacz poprawione jako `resolved`.
6. Dopiero potem `Approve QA`.

## 8.2 Side-by-side + Hotkeys

Do czego sluzy:
- reczna korekta segment po segmencie,
- porownanie zrodla i celu obok siebie.

Zasada:
- nie usuwaj znacznikow technicznych,
- zapisuj segment, potem zapis EPUB.

## 8.3 Search/Replace

Do czego sluzy:
- masowa zamiana tekstu.

Bezpieczny sposob:
1. Najpierw `Preview`.
2. Sprawdz trafienia.
3. Potem `Apply`.
4. Otworz wynik i szybko sprawdz 2-3 rozdzialy.

## 8.4 TM Manager

Do czego sluzy:
- przeglad i czyszczenie wpisow TM.

Uwaga:
- `Delete selected` jest operacja nieodwracalna.

## 8.5 Snapshots

Do czego sluzy:
- kopia stanu roboczego i przywrocenie.

Praktyka:
1. Przed duza zmiana: `Create`.
2. Jesli cos poszlo zle: `Restore`.

## 8.6 EPUBCheck

Do czego sluzy:
- walidacja techniczna EPUB.

Po nowej poprawce:
- narzedzie ma timeout fail-fast, wiec nie powinno wisiec bez konca.

## 8.7 Pipeline

Do czego sluzy:
- szybkie kolejkowanie procesu `translate -> edit`.

## 8.8 Dashboard

Do czego sluzy:
- podglad metryk runow, QA i TM,
- podzial ledgera i estymacje tokenow.

## 8.9 Provider Plugins

Do czego sluzy:
- testy i walidacja pluginow providerow.

Wazne:
- pluginy sa ograniczone polityka bezpieczenstwa,
- skrypt pluginu musi zgadzac sie z hash w `providers/manifest.json`.
- `Health check selected` testuje pojedynczy plugin.
- `Health check all (async)` uruchamia rownolegle testy wielu pluginow
  (z limitem wspolbieznosci i timeoutem), pokazuje czas i status per plugin.

## 9. Jak dzialaja gate'y jakosci

Masz trzy warstwy kontroli:

1. `EPUBCheck gate`
- sprawdza strukture EPUB,
- przy `fatal/error` blokuje finalizacje (gdy hard gate wlaczony).

2. `QA severity gate`
- blokuje sukces runu, jesli sa otwarte findings `fatal/error`.
- ten gate jest teraz niezalezny od przelacznika EPUBCheck.

3. `QA review gate` (workflow)
- steruje przejsciem do kolejnego kroku po review QA.

## 10. Praca z seria i slownikiem serii

Cel:
- utrzymac spojnosc nazewnictwa miedzy tomami.

Przebieg:
1. Przypisz projekt do serii.
2. Ustaw numer tomu.
3. Otworz `Slownik serii` (Series manager).
4. Zakladka `Termy`:
- approve/reject terminow,
- `Learn from TM` aby zasolic propozycje z pamieci tlumaczen,
- `Export glossary` dla zatwierdzonych terminow.
5. Zakladka `Style rules`:
- dodaj reguly stylu serii (tone, dialog, interpunkcja, narracja),
- reguly sa dolaczane do promptu runu jako kontekst serii.
6. Zakladka `Lorebook`:
- dodaj fakty swiata i postaci,
- status `active` oznacza, ze wpis idzie do kontekstu promptu.
7. Zakladka `Historia`:
- podglad audytu zmian (terms/style/lore),
- sluzy jako wersjonowanie i szybki diff operacyjny.
8. `Export/Import series profile`:
- przenoszenie stylu/lore/approved terms miedzy seriami lub komputerami.

## 11. Kolejka projektow i praca seryjna

Scenariusz:
1. Dla kazdego projektu ustaw dane i kliknij `Kolejkuj`.
2. Kliknij `Run all pending`.
3. Program wykonuje projekty po kolei.
4. `Stop run-all` zatrzyma po biezacym zadaniu.

Scenariusz seryjny (M7):
1. Wejdz w `Slownik serii`.
2. Kliknij `Queue series (current step)`.
3. Kliknij `Run series batch`.
4. Po zakonczeniu sprawdz `Export series report` albo plik `series_batch_report_*.md`.

Po nowej poprawce reliability:
- jesli aplikacja padnie w trakcie runu, przy nast. starcie statusy `running` sa automatycznie naprawiane do stanu odzyskiwalnego.

## 12. Kopie, logi i bezpieczenstwo danych

1. Uzywaj `Snapshots` przed masowymi zmianami.
2. Trzymaj osobno kopie EPUB zrodlowych.
3. Regularnie archiwizuj `translator_studio.db`.
4. Nie publikuj publicznie plikow z kluczami API.

Po nowej poprawce security:
- restore snapshotu blokuje niebezpieczne sciezki ZIP (ochrona przed path traversal).

## 13. Najczestsze problemy i rozwiazania

1. `Brak modeli`
- sprawdz provider,
- sprawdz klucz API lub czy ollama dziala,
- kliknij `Odswiez liste modeli`.

2. `Process error`
- sprawdz log,
- zmniejsz `Max chars / request`,
- zwieksz `Timeout` i `Attempts`.

3. `Run zatrzymuje sie na gate`
- popraw findings QA,
- uruchom EPUBCheck,
- dopiero potem ponow run.

4. `Brak postepu po wznowieniu`
- sprawdz czy wskazujesz ten sam projekt i te same sciezki plikow,
- sprawdz `Cache` i status `Ledger`.

## 14. Dobre praktyki dla laika

1. Jeden nowy parametr na raz.
2. Po kazdej duzej zmianie: test na jednym rozdziale.
3. Przed operacja masowa: snapshot.
4. Nie usuwaj recznie plikow DB i cache podczas aktywnego runu.
5. Utrzymuj porzadek nazw plikow (`book_src.epub`, `book_pl.epub`, `book_pl_edit.epub`).

## 15. Minimalna checklista przed publikacja gotowego EPUB

1. Run `translate` zakonczony bez bledow.
2. QA findings `fatal/error` zamkniete.
3. EPUBCheck bez bledow krytycznych.
4. Szybki przeglad 3-5 losowych rozdzialow.
5. Zapisana kopia finalna.

## 16. Gdzie szukac dalej

1. Dokumentacja portalowa: `docs/`
2. README: szybki przeglad projektu
3. Workflow Git: `project-tkinter/GIT_WORKFLOW_PL.md`
4. Support: `SUPPORT_PL.md`

---

Jesli chcesz, nastepny krok moge zrobic od razu: przygotowac druga wersje tego manuala jako
`MANUAL_PL_BEGINNER.md` z jeszcze bardziej szczegolowymi "zrzutami przebiegu" (co kliknac, co powinienes zobaczyc po kazdym kroku).
