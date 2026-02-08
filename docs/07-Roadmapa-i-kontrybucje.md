# 07. Roadmapa i kontrybucje

## 7.1. Priorytety techniczne

1. Integralnosc EPUB po tlumaczeniu (tagi inline, encje, `&shy;`).
2. Diff-aware retranslation zamiast pelnego rerunu ksiazki.
3. Kontekst translacji i spojnosc encji/postaci.
4. QA jezykowe pod redakcje polszczyzny.

## 7.2. Priorytety produktowe

1. Workflow "tlumacz -> czytaj -> popraw -> wznow".
2. Widoczny status projektu i etapow bez watpliwosci "co dalej".
3. Spojnosc stylu miedzy tomami jednej serii.
4. Lepsza dokumentacja onboardingowa i recovery.

## 7.3. Jak zglaszac zmiany

- Bug: przez `Issue` (template bug_report)
- Feature: przez `Issue` (template feature_request)
- Kod: przez `Pull Request`

W PR podaj:
- co zmieniasz,
- dlaczego,
- jak testowales,
- czy dotyka to workflow krytycznych.

## 7.4. Standard PR

PR powinien byc:
- maly i skupiony,
- z jasnym celem,
- z testowalnym efektem,
- z dokumentacja gdy zmienia sie sposob uzycia.

## 7.5. Release discipline

Dla kazdego release:
1. podsumowanie zmian,
2. lista ryzyk,
3. instrukcja migracji (jesli potrzeba),
4. jasne CTA do feedbacku.

## 7.6. Sponsoring i utrzymanie

Jesli projekt oszczedza czas:
- wesprzyj: `https://github.com/sponsors/Piotr-Grechuta`
- zglaszaj regresje i pomysly,
- pomoz dopracowac dokumentacje i testy.

## 7.7. Definicja sukcesu roadmapy

- mniej regresji po merge,
- krotszy czas od bug report do fix,
- mniejsza liczba problemow z konfiguracja,
- szybszy onboarding nowego urzadzenia.

## 7.8. Kolejne milestone'y (po M1-M3)

1. `M4: Context-Aware Translation`
2. `M5: Text Integrity + Diff-Retranslation`
3. `M6: Polish QA + Live Reading Loop`
4. `M7: Batch Library + Style Memory`

Zakres i kryteria `Done` sa utrzymywane w:
- `docs/09-Backlog-do-uzgodnienia.md`
