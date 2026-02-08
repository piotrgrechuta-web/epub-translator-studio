from pathlib import Path
import runpy


def _find_project_root(anchor: Path) -> Path:
    # Szukamy katalogu projektu po markerach wymaganych do uruchomienia.
    required = ("app_main.py", "project_db.py", "tlumacz_ollama.py")
    for candidate in (anchor, *anchor.parents):
        if all((candidate / name).exists() for name in required):
            return candidate
    raise SystemExit(
        "Nie znaleziono katalogu projektu (brak markerow: app_main.py, project_db.py, tlumacz_ollama.py)."
    )


ROOT = _find_project_root(Path(__file__).resolve().parent)
START = ROOT / "app_main.py"
runpy.run_path(str(START), run_name="__main__")
