# 03. Praca na 2 komputerach

## Model pracy

Najprostszy i najbezpieczniejszy model:
- jedna aktywna galaz robocza: `main`,
- zawsze `pull` przed praca,
- zawsze `push` po zakonczonej sesji.

## Checklist start/stop

### Start sesji

```powershell
git checkout main
git pull --rebase
```

### Koniec sesji

```powershell
git add -A
git commit -m "krotki opis"
git push
```

## Co robic przy konflikcie

1. `git status`
2. rozwiaz konflikt lokalnie
3. `git add ...`
4. `git rebase --continue` albo commit po merge
5. `git push`

## Co najczesciej psuje synchronizacje

- lokalne pliki binarne (db/lock/cache)
- `node_modules` i duze artefakty
- praca na roznych branchach bez swiadomosci

## Dobre praktyki

- male, czeste commity
- jeden temat na commit
- opis PR z powodem zmiany i testami

## START/STOP scripts (opcjonalnie)

Mozesz zautomatyzowac rytm 2 skryptami:
- `START.ps1`: checkout + pull + open code
- `STOP.ps1`: add + commit + push

To ogranicza ryzyko "zapomnialem push".

## Recovery gdy lokalnie jest chaos

Jesli chcesz wyrownac lokalne repo do zdalnego i zachowac kopie zmian:

```powershell
git stash push -u -m "backup"
git fetch origin
git reset --hard origin/main
git clean -fd
```

Potem ewentualnie przywroc fragmenty:

```powershell
git stash list
git stash pop
```

## Recovery po awarii runtime (db/cache/lock)

Szybki playbook, gdy aplikacja padla w trakcie runu:

1. Zrob kopie stanu:
```powershell
$stamp = Get-Date -Format "yyyyMMdd-HHmmss"
New-Item -ItemType Directory -Force ".\backup\$stamp" | Out-Null
Copy-Item "project-tkinter\translator_studio.db" ".\backup\$stamp\translator_studio.db" -ErrorAction SilentlyContinue
Copy-Item "project-tkinter\output\*.jsonl" ".\backup\$stamp\" -ErrorAction SilentlyContinue
```
2. Wyczysc tylko stale locki:
```powershell
Remove-Item "project-tkinter\translator_studio.db.lock" -Force -ErrorAction SilentlyContinue
cmd /c if exist .git\index.lock del /f /q .git\index.lock
```
3. Gdy cache jest uszkodzony, odsun go i uruchom ponownie:
```powershell
if (Test-Path "project-tkinter\output\cache_book.jsonl") {
  Rename-Item "project-tkinter\output\cache_book.jsonl" "cache_book.broken.jsonl.$stamp"
}
```
4. Sprawdz integralnosc DB:
```powershell
python -c "import sqlite3; c=sqlite3.connect(r'project-tkinter\\translator_studio.db'); print(c.execute('pragma integrity_check').fetchone()[0]); c.close()"
```
5. Potwierdz start aplikacji:
```powershell
python project-tkinter\scripts\smoke_gui.py
```
