# Plan modernizacji Tkinter UI

## Status wdrozenia (2026-02-08)

## Etap 1: Design tokens
- [x] Zdefiniowac jedna palete kolorow i skale spacingu.
- [x] Zastapic rozproszone style jednym modulem stylu.

Zrobione:
- dodano wspolny modul stylu `project-tkinter/ui_style.py`,
- `app_gui_classic.py` i `app_gui_horizon.py` korzystaja ze wspolnych tokenow i stylow.

## Etap 2: Layout
- [x] Ujednolicic grid i marginesy kart.
- [x] Ograniczyc gestosc formularzy (wiecej odstepow, logiczne grupy).

Zrobione:
- spojne odstepy sekcji i kart (`space_*` tokens),
- helper-labelki objasniajace sekcje,
- ujednolicone style kart (`Card.TLabelframe`).

## Etap 3: Komponenty
- [x] Spojne style przyciskow: primary/secondary/danger.
- [x] Spojne pola wejsciowe i etykiety pomocnicze.

Zrobione:
- przyciski maja role (`Primary.TButton`, `Secondary.TButton`, `Danger.TButton`),
- wejscia i comboboxy maja wspolne tokeny kolorow/kontrastu,
- dodano styl etykiet pomocniczych (`Helper.TLabel`).

## Etap 4: UX
- [x] Lepsze komunikaty statusow i bledow.
- [x] Mniej modalnych popupow, wiecej informacji inline.

Zrobione:
- dodano inline-notice (`InlineInfo/Warn/Err.TLabel`),
- `info` przelaczono na komunikaty inline + pasek statusu,
- bledy pokazuje inline + modal (dla krytycznych sytuacji).

## Etap 5: Dostepnosc
- [x] Skroty klawiaturowe.
- [x] Kontrasty i czytelnosc fontow.

Zrobione:
- skroty: `Ctrl+S` (zapis), `Ctrl+R` (start), `Ctrl+Q` (kolejka), `F5` (modele),
- poprawione kontrasty list/logow i pol tekstowych.

## Proponowany kolejny etap

## Etap 6: Spojnosc komunikatow i telemetry UX
- standaryzacja slownictwa statusow (`ok/warn/error`) miedzy Tkinter i web-desktop,
- panel "ostatnie akcje" (inline timeline) zamiast czesci popupow,
- licznik czasu operacji i mini-metryki (czas runu, hit-rate cache/TM) bez wchodzenia do logu.
