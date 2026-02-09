# 07. Roadmapa i kontrybucje

## 7.0. Status wdrozenia (2026-02-09)

- `M1`: zrealizowane.
- `M2`: zrealizowane.
- `M3`: zamrozone (blokada po stronie GitHub Wiki; bez wpływu na runtime aplikacji).
- `M7`: uruchomiony szkielet techniczny (seria + slownik serii + auto-detekcja + merge glosariusza).
- `M4`: domkniete (ledger orchestration upfront + twardy gate EPUBCheck + tokenized inline editor + dashboard ledger metrics + stale widoczny pasek ledgera + presety promptow Gemini w GUI + telemetry retry/timeout + export metryk do release notes + alert progowy ledgera).
- `M5`: domkniete (nested-inline chips w edytorze + dodatkowe testy regresji + walidator integralnosci `&shy;/&nbsp;` z raportem po runie).
- `M6`: domkniete (diff-aware retranslation + semantic diff gate + raport changed/reused/retranslated + auto-findings QA).

## 7.1. Priorytety techniczne

1. Memory-first translation: cache segmentow + reuse po hashu.
2. Human-in-the-loop: pamiec zatwierdzonych decyzji redaktora.
3. EPUB-aware segmentacja i integralnosc markup (`&shy;`, inline tags).
4. Smart retranslation: diff-aware + semantic diff gate do recenzji.

## 7.2. Priorytety produktowe

1. Mniejszy koszt API i krotszy czas przez agresywny reuse cache.
2. Adaptacyjne podpowiedzi stylu/terminow z decyzji redaktora.
3. Recenzja tylko zmian o realnej roznicy semantycznej.
4. Spojnosc stylu miedzy tomami jednej serii (batch/library) - fundament techniczny juz dodany.

Aktualny increment M4 (wdrozony):
1. mini-dashboard ledgera (`done/processing/error/pending`) widoczny stale w sekcji `Uruchomienie`,
2. presety promptow pod provider/mode z gotowymi recepturami Gemini,
3. telemetry retry/timeout per provider (Google/Ollama) w runtime metrykach,
4. alert progowy `ERROR > N` przy pasku ledgera,
5. export metryk runu/ledgera do sekcji release notes (`Studio Tools -> Dashboard`),
6. testy jednostkowe logiki presetow.

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

## 7.8. Kolejne milestone'y (po M1-M2, M3 zamrozone)

1. `M4: Memory-First Translation Engine`
2. `M7: Series Style Memory + Batch Library` (foundation active, kolejne incrementy w backlogu)

Zakres i kryteria `Done` sa utrzymywane w:
- `docs/09-Backlog-do-uzgodnienia.md`
