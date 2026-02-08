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
- format wpisu:
  - `ks=<book> | T:<done>/<total> <status> | R:<done>/<total> <status> | -> <next_action>`.

Dodatkowo:
- `Historia runow` pokazuje ostatnie uruchomienia aktywnego projektu,
- sekcja `Uruchomienie` pokazuje biezacy status procesu i postep.

## Gdzie widac postep projektu (Web Desktop)

Ekran: gora aplikacji web-desktop (`project-web-desktop`):
- rozwijana lista projektu zawiera skrot statusu i podsumowanie etapow,
- pole `Podsumowanie projektu` pokazuje ksiazke + T/R + nastepna akcje.

Format jest spojny z wariantem Tkinter:
- `ks=<book> | T:<done>/<total> <status> | R:<done>/<total> <status> | -> <next_action>`.

## Poprawki UX wdrozone w aplikacjach

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

Wariant Web Desktop (`desktop/main.js`, `desktop/renderer/styles.css`):
- okno Electron startuje na rozmiarze dopasowanym do ekranu i maksymalizuje sie po starcie,
- layout ma minimalne szerokosci + `overflow`, wiec po pomniejszeniu sa paski przewijania,
- menu kontekstowe pod prawym klawiszem (undo/redo/cut/copy/paste/delete/select all + link actions).

## Gdzie jest Wiki / Pages

Aktualny punkt wejscia dokumentacji:
- GitHub Pages: `https://piotrgrechuta-web.github.io/epu2pl/`
- Repo docs: `docs/`

Wiki GitHub (`/wiki`) moze wymagac inicjalizacji backendu.
Jesli `/wiki` przekierowuje na strone repo, patrz:
- `06-Troubleshooting.md`, sekcja `6.8`.
