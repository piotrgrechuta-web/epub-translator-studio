# Release Draft (PL)

Tytul:
```text
Sponsors + Community Setup Update
```

Opis:
```markdown
## Zmiany
- domkniete materialy sponsors (profil + outreach pack + szybkie checklisty),
- dodane szablony community: Bug report, Feature request, Pull Request,
- uporzadkowane sekcje wsparcia w dokumentacji (README/README PL/SUPPORT/MANUAL).

## Ryzyka
- brak znanych regresji funkcjonalnych po smoke testach i py_compile,
- przy zmianach UI sprawdz kompatybilnosc profili projektu po aktualizacji.

## Migracja
- nie wymaga migracji danych od uzytkownika,
- dla pluginow providerow: po aktualizacji wykonaj "Rebuild manifest" i "Validate all".

## Testy
- `python -m pytest -q project-tkinter/tests`,
- `python project-tkinter/scripts/smoke_gui.py`,
- CI: lint, syntax smoke, PR description check, security scans.

## Support
Jesli projekt oszczedza Ci czas, wesprzyj dalszy rozwoj:
https://github.com/sponsors/Piotr-Grechuta
```

## Krotki post po publikacji release (copy-paste)

```text
Opublikowalem aktualizacje EPUB Translator Studio.
Dodalem gotowe szablony zgloszen, porzadek wsparcia i materialy sponsors.
Jesli narzedzie pomaga Ci w pracy, wesprzyj projekt:
https://github.com/sponsors/Piotr-Grechuta
```
