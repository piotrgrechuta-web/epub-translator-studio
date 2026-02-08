# 01. Quick Start

## Cel

Ta sekcja daje minimalna sciezke uruchomienia obu wariantow aplikacji:
- Tkinter (gowna aplikacja desktop),
- Electron + FastAPI (wariant web-desktop).

## Wymagania bazowe

- Git
- Python 3.11+
- Node.js LTS + npm
- VS Code (opcjonalnie, ale zalecane)
- Dla lokalnego AI: Ollama + model
- Dla online AI: klucz API (np. Google)

## Szybki start: klon i branch

```powershell
git clone https://github.com/piotrgrechuta-web/epu2pl.git
cd epu2pl
git checkout ep2pl
git pull
```

## Tkinter (main app)

```powershell
cd project-tkinter
python -m venv .venv
. .\.venv\Scripts\Activate.ps1
python app_main.py --variant classic
```

## Web desktop (Electron + FastAPI)

```powershell
cd project-web-desktop\backend
python -m venv .venv
. .\.venv\Scripts\Activate.ps1
pip install -r requirements.txt

cd ..\desktop
npm ci

cd ..
.\run-backend.ps1
.\run-desktop.ps1
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
