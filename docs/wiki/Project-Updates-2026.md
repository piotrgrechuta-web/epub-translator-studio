# Project Updates 2026

## English

This page tracks major updates that changed day-to-day workflow.

### Milestone status (as of 2026-02-10)

- `M8` closed (`#45-#49`).
- `M9` closed (umbrella `#51` closed).
- `M10` closed with focused delivery tracks delivered:
  - `#53` Prompt Router (segment-aware system prompt selection),
  - `#54` Easy Startup (auto-pathing + auto-resume),
  - `#55` Reliability UX (silent wait-and-retry).

### Runtime and UX additions

- Async provider health checks (`Health check I/O`) with telemetry storage.
- Optional bounded async dispatch (`--io-concurrency`) in runtime.
- Managed DB migrations with backup/rollback and startup recovery.
- Ledger-first idempotent processing with visible run strip (`done/processing/error/pending`).

### Security and governance additions

- CodeQL workflow enabled for repository code scanning.
- Dependabot updates configured for `pip` and GitHub Actions.
- Security gate raised to `HIGH,CRITICAL` in Trivy workflow.
- `pip-audit` gate now blocks by configurable CVE threshold.

### Editing and quality

- Prompt presets by provider/mode in GUI.
- EPUBCheck hard gate + QA severity gate before successful finalization.
- Inline-tag safe text editing (tokenized protection path in editor workflow).

### Series and repository operations

- Series Memory: terms, style rules, lorebook, history, profile import/export.
- Series batch orchestration with aggregated report output.
- Release draft automation workflow available in CI.

## Polski

Ta strona zbiera najwazniejsze aktualizacje projektu, ktore zmienily codzienny workflow.

### Status milestone'ow (na 2026-02-10)

- `M8` domkniety (`#45-#49`).
- `M9` domkniety (zamkniete issue-umbrella `#51`).
- `M10` domkniety po dowiezieniu strumieni:
  - `#53` Prompt Router (segment-aware wybor promptu systemowego),
  - `#54` Easy Startup (auto-pathing + auto-resume),
  - `#55` Reliability UX (silent wait-and-retry).

### Dodatki runtime i UX

- Asynchroniczne health-checki providerow (`Health check I/O`) z telemetryka.
- Opcjonalny async dispatch z limitem wspolbieznosci (`--io-concurrency`).
- Zarzadzane migracje DB z backupem/rollbackiem i recovery przy starcie.
- Idempotentny, ledger-first pipeline z widocznym paskiem statusu (`done/processing/error/pending`).

### Dodatki security i governance

- Wlaczony workflow CodeQL do code scanning.
- Skonfigurowane Dependabot updates dla `pip` i GitHub Actions.
- Podniesiona bramka security Trivy do `HIGH,CRITICAL`.
- `pip-audit` ma teraz blokujacy gate z konfigurowalnym progiem CVE.

### Edycja i jakosc

- Presety promptow zalezne od provider/mode.
- Twardy gate EPUBCheck i QA severity gate przed finalizacja runu.
- Bezpieczna edycja inline-tagow (tokenized protection w workflow edytora).

### Serie i operacje repo

- Series Memory: termy, style rules, lorebook, historia, import/export profilu.
- Orkiestracja batcha serii z raportem zbiorczym.
- Workflow CI do automatyzacji draftu release.

## Related docs

- [Roadmap](https://github.com/Piotr-Grechuta/epub-translator-studio/blob/main/docs/07-Roadmapa-i-kontrybucje.md)
- [Backlog](https://github.com/Piotr-Grechuta/epub-translator-studio/blob/main/docs/09-Backlog-do-uzgodnienia.md)
- [Series memory](https://github.com/Piotr-Grechuta/epub-translator-studio/blob/main/docs/10-Series-Style-Memory.md)
