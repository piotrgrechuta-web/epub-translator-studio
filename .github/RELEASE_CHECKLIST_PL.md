# Release checklist (PL)

## 1) Przed tagiem

- [ ] `git pull --rebase` na `main` i brak lokalnych konfliktow.
- [ ] CI zielone: `python-checks`, `validate-pr-body`, `security-scans`.
- [ ] Lokalnie uruchomione:
  - [ ] `python -m pytest -q project-tkinter/tests`
  - [ ] `python project-tkinter/scripts/smoke_gui.py`
- [ ] Brak kluczy/secrets w zmianach (potwierdzone skanem).

## 2) Changelog discipline

- [ ] `CHANGELOG.md` uzupelniony w sekcji `Unreleased`.
- [ ] Wpisy sa krotkie, mierzalne i podaja scope zmiany.
- [ ] Przy zmianach breaking dopisano notke migracyjna.

## 3) Release notes (obowiazkowe sekcje)

- [ ] Wygenerowano draft release notes komenda:
  - [ ] `python project-tkinter/scripts/generate_release_notes.py --output artifacts/release_notes.md --from-ref <prev_tag> --to-ref HEAD`
- [ ] Workflow CI `Release Draft` opublikowal artefakt `release-notes-draft`.
- [ ] `## Zmiany`
- [ ] `## Ryzyka`
- [ ] `## Migracja`
- [ ] `## Testy`
- [ ] `## Support`

## 4) Po publikacji

- [ ] Link do release dodany/przypiety w komunikacji (README/profil/post).
- [ ] Sprawdzona dostepnosc Pages i podstawowych linkow repo.
- [ ] Otwarty kolejny backlog / milestone na nastepny sprint.
