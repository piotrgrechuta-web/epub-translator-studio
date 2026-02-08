# Workflow and Recovery

This page summarizes the safe workflow for daily work and recovery after interruption.

## Normal Flow

1. Select project.
2. Run `translate`.
3. Review QA findings.
4. Approve QA gate.
5. Run `edit`.
6. Validate final EPUB (EPUBCheck gate).

## Safe Resume

- Segment progress is stored in SQLite (`segment_ledger`).
- Cache and ledger reuse avoid repeating paid API work.
- Interrupted runs can be restarted without losing completed segments.
- Run panel shows a live ledger strip (`done/processing/error/pending`) during processing.

## Prompt Presets (Gemini)

- GUI includes model/provider-specific prompt presets.
- Presets can be applied with one click (`Apply preset`) and are stored in UI state.
- Built-ins include: `Book Balanced`, `Lovecraft Tone`, `Technical Manual`, `Polish Copyedit`.

## If Run Fails

1. Open run history and check the last log.
2. Fix provider/network issue.
3. Restart the same project and step.
4. Verify QA/EPUBCheck gates before final export.

Detailed operational instructions:

- https://github.com/Piotr-Grechuta/epub-translator-studio/blob/main/docs/03-Praca-na-2-komputerach.md
- https://github.com/Piotr-Grechuta/epub-translator-studio/blob/main/docs/06-Troubleshooting.md
