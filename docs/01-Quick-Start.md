# 01. Quick Start

## Cel

Ta sekcja daje minimalna sciezke uruchomienia aplikacji Tkinter (glowna aplikacja desktop).

## Wymagania bazowe

- Git
- Python 3.11+
- VS Code (opcjonalnie, ale zalecane)
- Dla lokalnego AI: Ollama + model
- Dla online AI: klucz API (np. Google)

## Szybki start: klon i branch

```powershell
git clone https://github.com/Piotr-Grechuta/epub-translator-studio.git
cd epub-translator-studio
git checkout main
git pull
```

## Tkinter (main app)

```powershell
cd project-tkinter
python -m venv .venv
. .\.venv\Scripts\Activate.ps1
python app_main.py --variant classic
```

## Minimalna weryfikacja po starcie

1. Aplikacja uruchamia sie bez tracebackow.
2. Da sie zaladowac projekt i plik EPUB.
3. Da sie wybrac provider i model.
4. Da sie uruchomic co najmniej jedna operacje testowa.

## Rekomendowany rytm pracy

- Start dnia:
  - `git pull --rebase`
- Koniec dnia:
  - commit + `git push`

To ogranicza konflikty przy pracy na wielu komputerach.
