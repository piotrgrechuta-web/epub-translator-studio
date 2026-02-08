# 08. Status UI i Wiki/Pages

## Cel

Ta sekcja odpowiada na 3 praktyczne pytania:
1. gdzie na ekranie widac postep projektu,
2. gdzie jest dokumentacja (Wiki/Pages),
3. jakie poprawki UX zostaly wdrozone.

## Gdzie widac postep projektu (Tkinter)

Ekran: sekcja `Projekt i profile` (lewy panel, u gory).

Najwazniejsze elementy:
- licznik statusow wszystkich projektow: `idle/pending/running/error`,
- lista statusu projektow z podsumowaniem ksiazki i etapow,
- statusy etapow `T/R` sa ujednolicone miedzy wariantami Tkinter (`classic`/`horizon`): `none/pending/running/ok/error`,
- format wpisu:
  - `ks=<book> | T:<done>/<total> <status> | R:<done>/<total> <status> | -> <next_action>`.

Dodatkowo:
- panel `Ostatnie akcje (timeline projektu)` pokazuje ostatnie uruchomienia aktywnego projektu,
- linia `Metryki runu` pokazuje czas, segmenty, cache/TM i reuse-rate dla ostatniego runu,
- sekcja `Uruchomienie` pokazuje biezacy status procesu i postep.

## Poprawki UX wdrozone w aplikacji

Wariant Tkinter (`app_gui_classic.py`, `app_gui_horizon.py`, `studio_suite.py`):
- glowne okno i okna narzedzi startuja w trybie maksymalnym (z dynamicznymi granicami),
- po zmniejszeniu okna dostepne sa paski przewijania (pion/poziom),
- menu kontekstowe pod prawym przyciskiem myszy w polach edycyjnych:
  - `Cofnij`, `Ponow`, `Wytnij`, `Kopiuj`, `Wklej`, `Usun`,
  - `Zaznacz wszystko`, `Wyczysc pole`.
- wdrozono design tokens i role komponentow:
  - przyciski `Primary/Secondary/Danger`,
  - wspolne style kart (`Card.TLabelframe`) i helper-labelki.
- dodano komunikaty inline (mniej popupow dla informacji) + skroty klawiaturowe:
  - `Ctrl+S` zapis projektu,
  - `Ctrl+R` start runu,
  - `Ctrl+Q` kolejkowanie projektu,
  - `F5` odswiezenie modeli.

## Gdzie jest Wiki / Pages

Aktualny punkt wejscia dokumentacji:
- GitHub Pages: `https://piotr-grechuta.github.io/epub-translator-studio/`
- Repo docs: `docs/`

Wiki GitHub (`/wiki`) moze wymagac inicjalizacji backendu.
Jesli `/wiki` przekierowuje na strone repo, patrz:
- `06-Troubleshooting.md`, sekcja `6.8`.
