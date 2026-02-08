# 07. Roadmapa i kontrybucje

## 7.1. Priorytety techniczne

1. Stabilnosc runtime i redukcja edge-case crashy.
2. Lepsze testy automatyczne backend + UI smoke.
3. Lepsza ergonomia pracy na dwoch komputerach.
4. Uporzadkowanie danych lokalnych (cache/db/lock).

## 7.2. Priorytety produktowe

1. Przejrzystosc workflow translacja -> QA -> publish.
2. Lepsza konfiguracja providerow i modeli.
3. Silniejsza dokumentacja onboardingowa.
4. Bardziej czytelne komunikaty bledow.

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
