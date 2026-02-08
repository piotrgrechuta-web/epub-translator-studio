# 10. Series Style Memory - szkielet techniczny

Dokument opisuje wdrozony fundament pod spojna prace na wielu ksiazkach jednej serii.

## 10.1. Co zostalo wdrozone

1. Przypisanie projektu do serii:
- tabela `series` w `translator_studio.db`,
- pola `projects.series_id` i `projects.volume_no`.

2. Autodetekcja serii z EPUB:
- parser metadanych OPF (`calibre:series`, `belongs-to-collection`, indeks tomu),
- fallback po tytule (`Book/Vol/Tom`).

3. Per-seria magazyn danych:
- `project-tkinter/data/series/<slug>/series.db`,
- tabele: `terms`, `decisions`, `lore_entries`, `style_rules`.

4. UI:
- wybor serii i tomu na karcie projektu,
- przyciski: `Nowa seria`, `Auto z EPUB`, `Slownik serii`,
- manager terminow (approve/reject/manual add/export).

5. Runtime:
- przy runie budowany jest scalony glosariusz:
  - zatwierdzone terminy serii,
  - lokalny glosariusz projektu.
- po udanym runie aplikacja uczy serie z TM projektu (status `proposed`).

6. Stabilnosc migracji:
- samonaprawa schematu `project_db.py` dla baz z dryfem wersji
  (np. `schema_version=8`, ale brak kolumn `series_id/volume_no`).

## 10.2. Dane i pliki

- GLOWNA baza: `project-tkinter/translator_studio.db`
- Baza serii: `project-tkinter/data/series/<slug>/series.db`
- Eksport serii: `project-tkinter/data/series/<slug>/generated/approved_glossary.txt`
- Run-specific merge: `project-tkinter/data/series/<slug>/generated/merged_glossary_project_<id>.txt`

## 10.3. Co dalej (kolejne incrementy)

1. Jawny edytor `style_rules` i `lore_entries` w UI (M7/Issue 31).
2. Versioning zmian slownika/stylu serii (audit + diff).
3. Batch orchestrator dla wielu ksiazek jednej serii (M7/Issue 32).
4. Integracja z M4: decision memory jako dynamic few-shot kontekst.
