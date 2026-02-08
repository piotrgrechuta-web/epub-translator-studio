# 06. Troubleshooting

## 6.1. "cannot pull with rebase: You have unstaged changes"

Powod: lokalne zmiany blokuja `pull --rebase`.

Rozwiazanie:
```powershell
git stash push -u -m "tmp"
git pull --rebase
git stash pop
```

## 6.2. "index.lock exists"

Powod: przerwany proces git.

Rozwiazanie:
```powershell
cmd /c if exist .git\index.lock del /f /q .git\index.lock
```

## 6.3. Push odrzucony przez GitHub (plik >100MB)

Powod: limit GitHub dla pojedynczego pliku.

Rozwiazanie:
- usun plik z indeksu,
- dodaj do `.gitignore`,
- popraw commit i push.

## 6.4. `gh` po instalacji "not recognized"

Powod: stara sesja terminala i nieodswiezony PATH.

Rozwiazanie:
- otworz nowy terminal, albo
- uzyj pelnej sciezki:
```powershell
& "C:\Program Files\GitHub CLI\gh.exe" --version
```

## 6.5. Workflow CI czerwony przez opis PR

Powod: puste sekcje lub placeholder w PR template.

Rozwiazanie:
- uzupelnij wszystkie sekcje,
- zaznacz wymagane checkboxy,
- usun `<uzupelnij>` / `TODO`.

## 6.6. Aplikacja nie widzi modeli

Sprawdz:
1. provider (`ollama` vs `google`),
2. host Ollama,
3. API key,
4. dostep do sieci,
5. czy model jest pobrany lokalnie.

## 6.7. Co zrobic zanim zglosisz bug

1. zapisz kroki reprodukcji,
2. podaj branch i commit,
3. dolacz log/trace,
4. opisz oczekiwane vs rzeczywiste zachowanie.

To radykalnie skraca czas diagnozy.

## 6.8. Wiki przekierowuje na strone repo (302)

Objaw:
- `https://github.com/<owner>/<repo>/wiki` wraca do strony glownej repo,
- `git ls-remote https://github.com/<owner>/<repo>.wiki.git` zwraca blad.

Co zrobic:
1. Wejdz w `Settings -> General -> Features` i potwierdz, ze `Wiki` jest wlaczone.
2. Wylacz i wlacz `Wiki` ponownie (czasem backend nie inicjalizuje sie poprawnie za pierwszym razem).
3. Otworz zakladke `Wiki` i utworz pierwsza strone (np. `Home`) - to inicjalizuje repozytorium `*.wiki.git`.
4. Po inicjalizacji sprawdz:

```powershell
gh api repos/<owner>/<repo> --jq "{has_wiki,default_branch:.default_branch}"
git ls-remote https://github.com/<owner>/<repo>.wiki.git
```
5. Opublikuj przygotowany pakiet Wiki:

```powershell
powershell -ExecutionPolicy Bypass -File project-tkinter/scripts/publish_wiki.ps1
```

Fallback:
- jezeli backend Wiki nadal nie odpowiada, trzymaj dokumentacje w `docs/` i publikuj przez GitHub Pages:
  - `https://piotr-grechuta.github.io/epub-translator-studio/`

## 6.9. Crash w trakcie runu (db/cache)

Objaw:
- aplikacja zamknela sie podczas translacji,
- kolejny start pokazuje niespojny stan lub blad odczytu cache.

Szybka naprawa:
1. Zrob backup `project-tkinter/translator_studio.db`.
2. Usun stale locki:
```powershell
Remove-Item "project-tkinter\translator_studio.db.lock" -Force -ErrorAction SilentlyContinue
```
3. Odsun uszkodzony cache:
```powershell
if (Test-Path "project-tkinter\output\cache_book.jsonl") {
  Rename-Item "project-tkinter\output\cache_book.jsonl" "cache_book.broken.jsonl"
}
```
4. Sprawdz DB:
```powershell
python -c "import sqlite3; c=sqlite3.connect(r'project-tkinter\\translator_studio.db'); print(c.execute('pragma integrity_check').fetchone()[0]); c.close()"
```
5. Uruchom smoke:
```powershell
python project-tkinter\scripts\smoke_gui.py
```
