# EPUB Translator Studio (Tkinter) - Manual praktyczny dla poczatkujacego

Ten dokument tlumaczy program w stylu:
- co dana opcja robi,
- po co jej uzywac,
- jak jej uzyc krok po kroku,
- co zmienia w plikach i bazie danych.

Manual dotyczy aplikacji z folderu `project-tkinter`.

## 1. Co to jest i jak dziala (prosto)

Program sluzy do pracy z EPUB:
1. tlumaczenie (`translate`),
2. redakcja po tlumaczeniu (`edit`),
3. QA (kontrola jakosci),
4. walidacja EPUB,
5. operacje techniczne (okladka, grafiki, wizytowka, edycja segmentow).

Przeplyw pracy (najczesciej):
1. wybierasz `input.epub`,
2. uruchamiasz `translate`,
3. sprawdzasz QA,
4. uruchamiasz `edit` (jesli potrzebne),
5. robisz walidacje EPUB.

Interfejs ma 2 poziomy:
- glowny panel (`app_gui_classic.py` uruchamiany przez `app_main.py`),
- panel rozszerzony `Studio Tools (12)` (faktycznie 10 zakladek).

## 2. Co program zapisuje i gdzie

Najwazniejsze elementy danych:
- `translator_studio.db` - baza SQLite z projektami, historiami runow, QA, TM.
- `data/series/<series-slug>/series.db` - lokalna baza serii (terminy, decyzje, lore/styl).
- `data/series/<series-slug>/generated/approved_glossary.txt` - eksport zatwierdzonego slownika serii.
- `data/series/<series-slug>/generated/merged_glossary_project_<id>.txt` - slownik uzyty w konkretnym runie (seria + projekt).
- `events/app_events.jsonl` - dziennik zdarzen aplikacji.
- pliki wynikowe EPUB - np. `book_pl.epub`, `book_pl_redakcja.epub`.
- cache segmentow - np. `cache_book.jsonl`.
- pliki debug - folder z pola `Debug dir`.
- snapshoty - `snapshots/snapshot_YYYYMMDD_HHMMSS.zip`.
- pluginy providerow - `providers/*.json`, `providers/*.py`, `providers/manifest.json`.

Co jest bezpieczne:
- samo klikniecie `Zapisz`, `Kolejkuj`, `Refresh` nie modyfikuje EPUB.

Co modyfikuje EPUB:
- `Start translacji` (zapis output),
- `Dodaj wizytowke`, `Usun okladke`, `Usun grafiki`,
- `Save EPUB` w edytorze segmentow,
- `Search/Replace -> Apply`.

## 3. Szybki start (pierwsze 10 minut)

1. Wejdz do folderu:
```powershell
cd C:\Users\Public\epub-translator-studio\project-tkinter
```

2. Uruchom GUI:
```powershell
python app_main.py --variant classic
```

3. W panelu:
- kliknij `Nowy` i podaj nazwe projektu,
- ustaw `Wejsciowy EPUB`,
- sprawdz `Wyjsciowy EPUB` i `Prompt`,
- wybierz provider + model (`Odswiez liste modeli`),
- kliknij `Start translacji`.

4. Po zakonczeniu:
- kliknij `Waliduj EPUB`,
- opcjonalnie otworz `Studio Tools -> QA` i zrob `Scan`.

## 3A. Wymagania AI (konieczne)

Do uruchamiania translacji potrzebujesz co najmniej jednego providera AI:

1. Provider lokalny (`Ollama`)
- zainstalowana usluga Ollama,
- pobrany co najmniej jeden model, np.:
```powershell
ollama pull llama3.1:8b
```
- w GUI poprawny `Ollama host` (domyslnie `http://127.0.0.1:11434`).

2. Provider online (np. `Google Gemini`)
- poprawny klucz API (`Google API key` / zmienna `GOOGLE_API_KEY`),
- polaczenie z internetem.

Bez modelu w Ollama albo bez poprawnego API key run nie wystartuje.

## 4. Kluczowe pojecia

### 4.1 Projekt
Projekt to "teczka logiczna" w bazie:
- pamieta sciezki plikow,
- pamieta ustawienia dla `translate` i `edit`,
- ma historie runow, QA findings i wpisy TM powiazane z projektem.

### 4.2 Profil kroku
Profil to zapis ustawien silnika AI (provider, timeout, batch, itd.).
Mozesz miec osobny profil do szybkiego tlumaczenia i osobny do redakcji.

### 4.3 Tryb (`translate` vs `edit`)
Program trzyma osobno dla kazdego trybu:
- output EPUB,
- prompt,
- cache,
- nazwe profilu.

To znaczy: przelaczenie trybu zmienia zestaw pol, ale nie kasuje danych drugiego trybu.

### 4.4 QA Gate
Po `translate` program moze automatycznie ustawic projekt do `edit`.
Gate decyduje:
- `PASS` -> wolno przejsc dalej,
- `BLOCK` -> blokada przejscia (np. sa otwarte findings QA).

### 4.5 TM (Translation Memory)
TM to baza segmentow zrodlo->cel.
Wplywa na powtarzalne fragmenty i spojnosc tlumaczenia.

### 4.6 Seria i slownik serii
Seria to warstwa nad pojedynczym projektem:
- projekt mozna przypisac do serii recznie lub przez autodetekcje metadanych EPUB,
- seria ma osobny slownik terminow (statusy: `proposed`, `approved`, `rejected`),
- przy wlaczonym `Uzyj slownika` run korzysta ze scalonego slownika:
1. zatwierdzone terminy serii,
2. lokalny slownik projektu (jesli podany).

Po udanym runie aplikacja moze dopisac propozycje terminow serii na podstawie TM projektu.

## 5. Glowny panel: co, po co, jak, wplyw

## 5.1 Sekcja "Projekt i profile"

### `Nowy`
- Po co: zalozenie nowego projektu.
- Jak: klik `Nowy`, wpisz nazwe.
- Wplyw: dodaje rekord w tabeli `projects` w `translator_studio.db`.

### `Zapisz`
- Po co: utrwalenie zmian w polach GUI do bazy.
- Jak: po zmianie sciezek/modelu/jezykow kliknij `Zapisz`.
- Wplyw: aktualizuje rekord `projects`; nie rusza plikow EPUB.

### `Usun`
- Po co: ukrycie projektu z listy aktywnych bez twardego kasowania.
- Jak: klik `Usun` i potwierdz.
- Wplyw: ustawia status projektu na `deleted`.

### `Usun hard`
- Po co: trwale usuniecie projektu.
- Jak: klik `Usun hard` i potwierdz.
- Wplyw:
1. usuwa rekord projektu,
2. usuwa TM przypisane do projektu,
3. powiazane runy i QA sa usuwane kaskadowo.
- Uwaga: tej operacji nie cofniesz przyciskiem `Cofnij ostatnia operacje`.

### `Zapisz jako profil`
- Po co: zapis aktualnej konfiguracji AI jako profil wielokrotnego uzycia.
- Jak: ustaw parametry, klik `Zapisz jako profil`, podaj nazwe.
- Wplyw: dodaje rekord w tabeli `profiles`.

### `Eksport`
- Po co: przeniesienie projektu do pliku JSON.
- Jak: wybierz projekt, klik `Eksport`, zapisz plik.
- Wplyw: tworzy JSON zawierajacy projekt + runy + TM + QA.

### `Import`
- Po co: odtworzenie projektu z JSON.
- Jak: klik `Import`, wskaz JSON.
- Wplyw:
1. tworzy nowy projekt (nazwa z sufiksem, jesli kolizja),
2. importuje runy, QA i TM do bazy.

### `Seria` + `Tom`
- Po co: utrzymanie spojnosci terminow i stylu miedzy ksiazkami tej samej serii.
- Jak:
1. wybierz serie z listy albo zostaw `brak serii`,
2. opcjonalnie ustaw numer tomu (`Tom`).
- Wplyw: zapisuje `series_id` i `volume_no` w tabeli `projects`.

### `Nowa seria`
- Po co: szybkie utworzenie serii bez wychodzenia z glownego panelu.
- Jak: klik `Nowa seria`, wpisz nazwe.
- Wplyw:
1. tworzy rekord w tabeli `series` (`translator_studio.db`),
2. inicjalizuje lokalny magazyn `data/series/<slug>/series.db`.

### `Auto z EPUB`
- Po co: automatyczne podpowiedzenie serii na podstawie metadanych EPUB (`OPF`).
- Jak: po ustawieniu `Wejsciowy EPUB` kliknij `Auto z EPUB` i potwierdz przypisanie.
- Wplyw: przypisuje serie do projektu i opcjonalnie ustawia `Tom`.

### `Slownik serii`
- Po co: zarzadzanie terminami serii i eksport zatwierdzonego glosariusza.
- Jak:
1. wybierz serie,
2. klik `Slownik serii`,
3. zatwierdzaj/odrzucaj terminy lub dodawaj recznie.
- Wplyw:
1. aktualizuje `data/series/<slug>/series.db`,
2. moze wyeksportowac `approved_glossary.txt`.

## 5.2 Sekcja "Pliki i tryb"

### `Wejsciowy EPUB`
- Po co: zrodlo tlumaczenia/redakcji.
- Jak: wybierz plik `.epub`.
- Wplyw: sluzy jako wejscie do procesu; program nie modyfikuje go bezposrednio przy starcie runu.

### `Wyjsciowy EPUB`
- Po co: plik, do ktorego zapisze sie wynik.
- Jak: ustaw recznie lub przyjmij podpowiedz.
- Wplyw: to ten plik bedzie nadpisany/utworzony przez proces tlumaczenia.

### `Prompt`
- Po co: instrukcje dla modelu.
- Jak: wskaz plik `.txt`.
- Wplyw: bez poprawnego promptu start runu zostanie zablokowany.

### `Slownik`
- Po co: dodatkowe terminy.
- Jak: wskaz plik `.txt`.
- Wplyw: dziala tylko gdy zaznaczone `Uzyj slownika`.

### `Cache`
- Po co: przyspieszenie i wznowienia.
- Jak: wskaz plik `.jsonl`.
- Wplyw: dziala tylko gdy zaznaczone `Uzyj cache`.

### `Tryb` (`Tlumaczenie` / `Redakcja`)
- Po co: wybor kroku pipeline.
- Jak: przelacz radiobutton.
- Wplyw:
1. laduje osobny zestaw `output/prompt/cache/profile`,
2. zmienia `active_step` projektu.

### `Jezyk zrodlowy` i `Jezyk docelowy`
- Po co: jawna para jezykowa dla modelu.
- Wplyw: trafia do komendy runu i do danych projektu.

## 5.3 Sekcja "Silnik i parametry batch"

### `Provider`
- `Ollama`: model lokalny.
- `Google Gemini API`: model przez API.

### `Ollama host`
- Po co: adres lokalnej uslugi Ollama.
- Wplyw: dodawany jako `--host` w komendzie.

### `Google API key`
- Po co: autoryzacja dla Google.
- Wplyw: bez klucza run dla Google sie nie uruchomi.

### `Max segs / request`, `Max chars / request`, `Pauza miedzy requestami`
- Po co: kontrola wielkosci batchy i tempa zapytan.
- Wplyw: bezposrednio zmienia argumenty procesu tlumacza.

## 5.4 Sekcja "Model AI"

### `Odswiez liste modeli`
- Po co: pobranie aktualnych modeli od aktywnego providera.
- Jak: ustaw provider, kliknij przycisk, wybierz model.
- Wplyw: aktualizuje liste wyboru modelu (UI), nie zmienia EPUB.

## 5.5 Sekcja "Ustawienia zaawansowane"

Najwazniejsze pola i ich sens:
- `Timeout`: ile sekund czekac na odpowiedz.
- `Attempts` + `Backoff`: ile i jak ponawiac nieudane requesty.
- `Temperature`: kreatywnosc modelu.
- `Num ctx`, `Num predict`: limity kontekstu i generacji.
- `Checkpoint`: co ile plikow zapisywac punkt kontrolny.
- `Debug dir`: gdzie zapisywac materialy debug.
- `Tagi`: jakie tagi HTML sa segmentowane do tlumaczenia.
- `Uzyj cache`, `Uzyj slownika`: wlaczanie/wylaczanie obu mechanizmow.
- `Tooltip mode`: tryb podpowiedzi interfejsu.
- `Jezyk UI`: jezyk interfejsu.

Praktyczna rada:
- jesli nie wiesz co zmieniasz, zostaw domyslne.

## 5.6 Sekcja "Uruchomienie"

### `Start translacji`
- Po co: uruchomienie procesu tlumaczenia/redakcji.
- Jak:
1. upewnij sie, ze pola wymagane sa ustawione,
2. kliknij `Start translacji`.
- Wplyw:
1. zapisuje ustawienia i projekt do bazy,
2. tworzy wpis `runs` ze statusem `running`,
3. uruchamia proces tlumacza,
4. po sukcesie ustawia status projektu (`idle` lub `pending`),
5. po bledzie ustawia status `error`.

Wazne:
- po sukcesie `translate` program moze automatycznie ustawic krok `edit` jako `pending`,
- ale tylko gdy QA Gate nie blokuje i pola `edit` sa uzupelnione.

### `Stop`
- Po co: zatrzymanie aktualnego procesu.
- Wplyw: wysyla `terminate` do procesu i zatrzymuje run-all kolejki.

### `Waliduj EPUB`
- Po co: sprawdzenie poprawnosci EPUB po obrobce.
- Wplyw:
1. uruchamia tryb walidacji,
2. zapisuje osobny run `validate` w bazie.

### `Estymacja`
- Po co: szybka prognoza rozmiaru pracy.
- Wplyw: oblicza liczbe segmentow, cache, token hint; nie modyfikuje plikow.

### `Kolejkuj`
- Po co: ustawienie projektu do pozniejszego uruchomienia.
- Wplyw: status projektu -> `pending`, `active_step` = aktualny tryb.

### `Uruchom nastepny`
- Po co: uruchomienie najstarszego projektu `pending`.

### `Run all pending`
- Po co: uruchamianie calej kolejki po kolei.

### `Stop run-all`
- Po co: zakonczenie automatu po aktualnym zadaniu.

### `Otworz output` / `Otworz cache`
- Po co: szybkie otwarcie plikow w systemie.
- Wplyw: tylko otwiera plik, nic nie zapisuje.

### `Wyczysc debug`
- Po co: usuniecie plikow z folderu debug.
- Wplyw: kasuje zawartosc folderu `Debug dir`.

## 5.7 Sekcja "Uladnianie EPUB"

### `Dodaj wizytowke (1 EPUB)`
- Po co: dodanie strony tytulowej z obrazem.
- Jak:
1. wybierz EPUB,
2. wybierz obraz,
3. podaj tytul,
4. zaakceptuj podglad.
- Wplyw:
1. tworzy nowy plik `*_wizytowka.epub`,
2. ustawia go jako aktualny `Wyjsciowy EPUB`,
3. dodaje operacje do historii cofania.

### `Dodaj wizytowke (folder)`
- Po co: to samo, ale dla wielu EPUB naraz.
- Wplyw: tworzy wiele `*_wizytowka.epub`.

### `Usun okladke`
- Po co: usuniecie zasobow cover.
- Wplyw:
1. tworzy nowy plik `*_bez_okladki.epub`,
2. usuwa wpisy cover z manifestu/spine i obrazy.

### `Usun grafiki (pattern)`
- Po co: masowe usuwanie obrazow po regexie.
- Jak: wpisz regex, np. `(?i)cover|banner|promo`.
- Wplyw:
1. tworzy nowy plik `*_bez_grafik.epub`,
2. usuwa obrazy i referencje z rozdzialow, ktore pasuja do regex.

### `Edytor tekstu EPUB`
- Po co: reczna edycja segmentow tekstu.
- Wplyw: po `Save EPUB` zapisuje zmiany i tworzy backup `.bak-edit-...`.

### `Cofnij ostatnia operacje`
- Po co: szybki rollback ostatniej operacji z historii.
- Co potrafi:
1. usunac ostatni wygenerowany plik EPUB,
2. odtworzyc plik z backupu,
3. usunac pliki z batcha.
- Czego nie potrafi: nie cofnie np. `Usun hard` ani kasowania TM z `TM Manager`.

### `Studio Tools (12)`
- Po co: otwarcie panelu rozszerzonego.
- Uwaga: etykieta mowi `12`, ale aktualnie sa 10 zakladek.

## 5.8 Sekcja "Log"

Zawiera:
- historie ostatnich uruchomien projektu,
- log live z procesu,
- postep globalny i aktualna faze.

Po co laikowi:
- to jest pierwsze miejsce do diagnozy, gdy cos "stoi" albo konczy sie bledem.

## 6. Studio Tools: wszystkie zakladki praktycznie

## 6.1 QA

Po co:
- wykrywanie i obsluga bledow QA per segment.

Najwazniejsze przyciski:
- `Scan`: skanuje EPUB i pokazuje findings.
- `Save findings`: zapisuje findings do bazy (`qa_findings`) i resetuje review na `pending`.
- `Load open`: laduje tylko `open`/`in_progress`.
- `Mark resolved` / `Mark in_progress`: zmienia status znalezionych pozycji.
- `Approve QA` / `Reject QA`: zapisuje decyzje w `qa_reviews`.
- `Assign selected` / `Assign all open`: przypisuje assignee i due date.
- `Escalate overdue`: oznacza przeterminowane jako `overdue`.
- `Auto-assign rules`: automatyczne przypisanie wg JSON rules.
- `Alert overdue`: wysyla webhook POST z lista overdue.

Pole `Gate`:
- `PASS` -> mozna przechodzic dalej,
- `BLOCK` -> blokada (otwarte findings, brak review albo reject).

Przyklad `Rules JSON` do auto-przypisania:
```json
{
  "default": "reviewer",
  "severity": { "error": "senior_qa", "warn": "qa" },
  "rule_code": { "EN_LEAK": "linguist" },
  "max_open_per_assignee": 100
}
```

Przyklad dla poczatkujacego:
1. `Scan`
2. `Save findings`
3. `Load open`
4. `Assign all open` (np. reviewer, 2 dni)
5. po poprawkach `Mark resolved`
6. `Approve QA`
7. sprawdz czy `Gate: PASS`

## 6.2 Side-by-side + Hotkeys

Po co:
- porownanie Source (oryginal) i Target (tlumaczenie) segment po segmencie.

Jak:
1. ustaw Source EPUB i Target EPUB,
2. klik `Load`,
3. wybierz chapter i segment,
4. edytuj prawa kolumne (Target),
5. `Save Segment`,
6. `Save EPUB`.

Skroty:
- `Alt+Down`: nastepny segment,
- `Alt+Up`: poprzedni segment,
- `Ctrl+S`: zapis segmentu.

Wplyw:
- `Save Segment` zmienia tylko dane w pamieci okna,
- dopiero `Save EPUB` zapisuje plik i robi backup.

## 6.3 Search/Replace

Po co:
- masowe podmiany tekstu w EPUB.

Jak bezpiecznie:
1. wpisz `Find` i `Replace`,
2. kliknij `Preview`,
3. sprawdz liste trafien,
4. kliknij `Apply` i potwierdz.

Wplyw:
- zapisuje zmiany do rozdzialow EPUB,
- tworzy backup (ostatni zapisany backup mozna cofnac przez `Cofnij`).

Uwaga:
- `Apply` dziala na trafienia z ostatniego `Preview`.

## 6.4 TM Manager

Po co:
- przeglad i czyszczenie pamieci tlumaczen.

Jak:
1. wpisz fraze,
2. `Search`,
3. zaznacz rekordy,
4. `Delete selected`.

Wplyw:
- kasuje wpisy z `tm_segments` w bazie.
- to jest operacja nieodwracalna z GUI.

## 6.5 Snapshots

Po co:
- "punkt przywracania" przed ryzykownymi zmianami.

`Create`:
- tworzy ZIP z kluczowymi plikami:
  - `app_main.py`
  - `app_gui_classic.py`
  - `app_gui_horizon.py`
  - `start.py` (alias kompatybilnosci)
  - `start_horizon.py` (alias kompatybilnosci)
  - `tlumacz_ollama.py`
  - `project_db.py`
  - `epub_enhancer.py`
  - `studio_suite.py`
  - `translator_studio.db`

`Restore`:
- rozpakowuje wybrany ZIP do katalogu projektu (nadpisuje pliki).

## 6.6 EPUBCheck

Po co:
- uruchamia zewnetrzne narzedzie `epubcheck`.

Jak:
1. podaj EPUB,
2. kliknij `Run epubcheck`,
3. czytaj log.

Wplyw:
- nie modyfikuje EPUB, tylko raportuje.

## 6.7 Illustration Rule

Stan:
- funkcja MVP/placeholder.
- obecnie wyswietla komunikat, zeby uzyc narzedzi z `Uladnianie EPUB`.

## 6.8 Pipeline

Po co:
- szybkie ustawienie biezacego projektu jako `pending` dla kroku `translate`.

Wplyw:
- status projektu -> `pending`,
- potem uruchamiasz go z panelu glownego (`Run all pending` albo `Uruchom nastepny`).

## 6.9 Dashboard

Po co:
- szybki wglad w stan systemu:
  - liczba runow,
  - ok vs error,
  - done/total,
  - rozmiar TM,
  - QA open/overdue,
  - obciazenie per assignee.

Wplyw:
- tylko odczyt danych.

## 6.10 Provider Plugins

Po co:
- rozszerzenie providerow przez pluginy JSON + skrypty Python.

Bezpieczenstwo pluginow:
- launcher tylko `python|python.exe|py|py.exe`,
- drugi argument musi byc relatywny `.py` pod `providers/`,
- blokowane sa sciezki absolutne i `..`,
- skrypt musi pasowac do hash SHA-256 z `providers/manifest.json`.

Przyciski:
- `Create template`: tworzy `providers/example_provider.json`.
- `Rebuild manifest`: buduje `providers/manifest.json` z hashami wszystkich `providers/*.py`.
- `Validate all`: waliduje specyfikacje i integralnosc.
- `Health check selected`: odpala komende pluginu testowo.

Minimalny plugin JSON:
```json
{
  "name": "MyProvider",
  "command_template": "python providers/my_provider.py --health --model {model} --prompt-file {prompt_file}"
}
```

Typowy flow:
1. `Create template`
2. dodaj `providers/my_provider.py`
3. `Rebuild manifest`
4. `Validate all`
5. `Health check selected`

## 7. Mapa wplywu: akcja -> co sie zmienia

| Akcja | Co zmienia w plikach | Co zmienia w bazie |
|---|---|---|
| `Zapisz` | nic | `projects` update |
| `Nowy` | nic | nowy rekord `projects` |
| `Nowa seria` | tworzy `data/series/<slug>/series.db` | nowy rekord `series` |
| `Auto z EPUB` | nic | przypisuje `projects.series_id` i opcjonalnie `projects.volume_no` |
| `Slownik serii` (approve/reject/add) | aktualizuje pliki pod `data/series/<slug>/` | zapis terminow/decydji w bazie serii (osobny SQLite) |
| `Kolejkuj` | nic | status `projects` -> `pending` |
| `Start translacji` | zapis output EPUB/cache (wg procesu) | nowy `runs`, status projektu |
| `Waliduj EPUB` | nic (raport w logu) | nowy `runs` (step=`validate`) |
| `Usun` | nic | `projects.status='deleted'` |
| `Usun hard` | nic na dysku EPUB | usuwa `projects` + TM projektu + powiazane runy/QA |
| `Dodaj wizytowke` | nowy `*_wizytowka.epub` | historia cofania w pamieci GUI |
| `Usun okladke` | nowy `*_bez_okladki.epub` | historia cofania w pamieci GUI |
| `Usun grafiki` | nowy `*_bez_grafik.epub` | historia cofania w pamieci GUI |
| `Save EPUB` (edytor) | zapis EPUB + backup `.bak-edit-*` | historia cofania w pamieci GUI |
| `Search/Replace -> Apply` | modyfikuje EPUB + backup | historia cofania w pamieci GUI |
| `TM Delete selected` | nic | kasuje rekordy `tm_segments` |
| `QA Save findings` | nic | podmienia `qa_findings`, review=`pending` |
| `QA Approve/Reject` | nic | nowy rekord `qa_reviews` |
| `Snapshot Create` | nowy zip w `snapshots/` | nic |
| `Snapshot Restore` | nadpisuje pliki z archiwum | posrednio (bo podmienia tez DB plik) |

## 8. Gotowe scenariusze (dla laika)

## 8.1 Scenariusz A: pierwsze tlumaczenie 1 ksiazki

1. `Nowy` -> nazwa np. `book1`.
2. `Wejsciowy EPUB` -> wybierz ksiazke.
3. Sprawdz `Wyjsciowy EPUB` (np. `book1_pl.epub`).
4. Provider + model.
5. `Start translacji`.
6. `Waliduj EPUB`.
7. `Otworz output`.

Efekt:
- masz wynikowy EPUB i wpis historii runu.

## 8.2 Scenariusz B: tlumaczenie + QA gate

1. Zrob `translate`.
2. `Studio Tools -> QA` -> `Scan`.
3. `Save findings`.
4. Popraw bledy.
5. `Mark resolved`.
6. `Approve QA`.
7. sprawdz `Gate: PASS`.

Efekt:
- projekt gotowy do bezpiecznego przejscia na kolejny etap.

## 8.3 Scenariusz C: bezpieczna operacja masowa

1. `Studio Tools -> Snapshots -> Create`.
2. `Studio Tools -> Search/Replace -> Preview`.
3. `Apply`.
4. Jesli efekt zly: `Snapshots -> Restore`.

Efekt:
- masowa podmiana z planem awaryjnym.

## 9. Typowe problemy i szybkie naprawy

1. `Brak modeli` po refresh:
- sprawdz `Ollama host` lub `Google API key`.

2. `Process is already running`:
- zatrzymaj poprzedni run (`Stop`) albo poczekaj do konca.

3. `Brak pola: ...`:
- uzupelnij brakujace pole (input/output/prompt/model).

4. `No EPUB for validation`:
- ustaw poprawny output albo input EPUB.

5. `epubcheck unavailable`:
- zainstaluj `epubcheck` i dodaj do PATH.

6. `Studio Tools (12)` ale mniej zakladek:
- normalne; aktualnie jest 10 zakladek.

## 10. Dobre praktyki pracy

1. Jeden projekt = jedna ksiazka.
2. Przed operacjami masowymi najpierw `Snapshot`.
3. `Usun hard` tylko gdy masz pewnosc.
4. W QA zawsze zapisuj findings (`Save findings`) zanim oceniasz gate.
5. W pluginach zawsze sekwencja: `Rebuild manifest` -> `Validate all`.
6. Jesli nie jestes pewny parametru AI, zostaw domyslny.

## 11. Przydatne komendy serwisowe

Preflight:
```powershell
powershell -ExecutionPolicy Bypass -File scripts/preflight.ps1
```

Czyszczenie artefaktow (podglad):
```powershell
powershell -ExecutionPolicy Bypass -File scripts/cleanup_project.ps1
```

Czyszczenie artefaktow (wykonanie):
```powershell
powershell -ExecutionPolicy Bypass -File scripts/cleanup_project.ps1 -Apply
```

Benchmark TM:
```powershell
python scripts/benchmark_tm.py --rows 20000 --lookups 300
```

## 12. Praca na wielu komputerach (Git)

W repo jest gotowa automatyzacja:
- skrypt: `scripts/git_workflow.py`
- instrukcja: `GIT_WORKFLOW_PL.md`

Najkrotsza wersja:
1. raz na komputer: `python scripts/git_workflow.py setup`
2. start dnia: `python scripts/git_workflow.py start --branch main`
3. publikacja: `python scripts/git_workflow.py publish --branch main -m "opis zmian"`

## 13. Wsparcie projektu

W aplikacji sa szybkie przyciski:
1. `Wesprzyj projekt`
2. `Repo online`

Link sponsora:
- `https://github.com/sponsors/Piotr-Grechuta`

Po aktywacji konta sponsors:
1. Uzupelnij tresci profilu wg `.github/SPONSORS_PROFILE_TEMPLATE_PL.md`.
2. Uzyj gotowych postow i CTA z `.github/SPONSORS_OUTREACH_PACK_PL.md`.
3. Raz w tygodniu opublikuj krotki update + link wsparcia.
