#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import sqlite3
import subprocess
from pathlib import Path
from typing import Any, Dict, List, Optional


def _run_git(args: List[str], cwd: Path) -> str:
    out = subprocess.check_output(["git", *args], cwd=str(cwd), text=True, encoding="utf-8", errors="replace")
    return str(out or "").strip()


def _git_commits(repo_root: Path, from_ref: str, to_ref: str, limit: int = 25) -> List[str]:
    if from_ref.strip():
        rev_range = f"{from_ref.strip()}..{to_ref.strip()}"
        raw = _run_git(["log", "--pretty=format:%h %s", rev_range], repo_root)
    else:
        raw = _run_git(["log", "--pretty=format:%h %s", f"-n{max(1, int(limit))}", to_ref.strip()], repo_root)
    lines = [x.strip() for x in raw.splitlines() if x.strip()]
    return lines


def _extract_changelog_unreleased(changelog_path: Path) -> List[str]:
    if not changelog_path.exists():
        return []
    lines = changelog_path.read_text(encoding="utf-8", errors="replace").splitlines()
    in_unreleased = False
    out: List[str] = []
    for line in lines:
        low = line.strip().lower()
        if low.startswith("## ") and "unreleased" in low:
            in_unreleased = True
            continue
        if in_unreleased and line.startswith("## "):
            break
        if in_unreleased and line.strip():
            out.append(line.rstrip())
    return out


def _latest_runtime_metrics_from_db(db_path: Path) -> Dict[str, Any]:
    if not db_path.exists():
        return {}
    con = sqlite3.connect(str(db_path))
    con.row_factory = sqlite3.Row
    try:
        run = con.execute(
            """
            SELECT id, project_id, step, status, global_done, global_total, started_at, finished_at, message
            FROM runs
            ORDER BY started_at DESC, id DESC
            LIMIT 1
            """
        ).fetchone()
        if run is None:
            return {}
        out: Dict[str, Any] = {
            "run_id": int(run["id"] or 0),
            "project_id": int(run["project_id"] or 0),
            "step": str(run["step"] or ""),
            "status": str(run["status"] or ""),
            "global_done": int(run["global_done"] or 0),
            "global_total": int(run["global_total"] or 0),
        }
        pid = int(run["project_id"] or 0)
        step = str(run["step"] or "").strip().lower()
        if pid > 0 and step:
            has_ledger = con.execute(
                "SELECT 1 FROM sqlite_master WHERE type='table' AND name='segment_ledger'"
            ).fetchone()
            if has_ledger is not None:
                rows = con.execute(
                    """
                    SELECT status, COUNT(*) c
                    FROM segment_ledger
                    WHERE project_id = ? AND run_step = ?
                    GROUP BY status
                    """,
                    (pid, step),
                ).fetchall()
                ledger = {"PENDING": 0, "PROCESSING": 0, "COMPLETED": 0, "ERROR": 0}
                for row in rows:
                    status = str(row["status"] or "").strip().upper()
                    if status in ledger:
                        ledger[status] = int(row["c"] or 0)
                out["ledger"] = ledger
        return out
    finally:
        con.close()


def _read_metrics_json(path: Path) -> Dict[str, Any]:
    if not path.exists():
        return {}
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return {}
    return data if isinstance(data, dict) else {}


def build_release_notes(
    *,
    title: str,
    commits: List[str],
    changelog_unreleased: List[str],
    metrics: Dict[str, Any],
    from_ref: str,
    to_ref: str,
) -> str:
    lines: List[str] = [f"# {title}", ""]

    lines.append("## Zmiany")
    if from_ref.strip():
        lines.append(f"- Zakres commitow: `{from_ref.strip()}..{to_ref.strip()}`")
    else:
        lines.append(f"- Zakres commitow: ostatnie zmiany do `{to_ref.strip()}`")
    if commits:
        lines.append("- Commity:")
        lines.extend([f"  - {c}" for c in commits[:25]])
    else:
        lines.append("- Brak commitow w podanym zakresie.")
    if changelog_unreleased:
        lines.append("- CHANGELOG (`Unreleased`):")
        lines.extend([f"  {x}" for x in changelog_unreleased[:60]])
    else:
        lines.append("- CHANGELOG (`Unreleased`): brak wpisow lub sekcji.")
    lines.append("")

    lines.append("## Ryzyka")
    lines.append("- Ryzyko regresji runtime po zmianach w pipeline: sprawdzic smoke + testy end-to-end.")
    lines.append("- Ryzyko jakosci translacji: monitorowac retry/timeouts i findings QA po wydaniu.")
    lines.append("- Ryzyko migracji DB: weryfikacja backup/rollback dla aktualnej wersji schema.")
    lines.append("")

    lines.append("## Migracja")
    lines.append("- Sprawdzic czy aplikacja wykonuje migracje schema bez bledow.")
    lines.append("- Przy zmianach pluginow: uruchomic `Rebuild manifest` oraz `Validate all`.")
    lines.append("- Po aktualizacji zalecany szybki run kontrolny na jednym projekcie.")
    lines.append("")

    lines.append("## Testy")
    lines.append("- `python -m pytest -q project-tkinter/tests`")
    lines.append("- `python project-tkinter/scripts/smoke_gui.py`")
    lines.append("- CI: `pr-checks`, `pr-description-check`, `security-scans`")
    lines.append("")

    lines.append("## Runtime Metrics")
    if metrics:
        lines.append("```json")
        lines.append(json.dumps(metrics, ensure_ascii=False, indent=2))
        lines.append("```")
    else:
        lines.append("- Brak runtime metrics w CI (opcjonalnie podaj `--db-path` lub `--metrics-json`).")
    lines.append("")

    lines.append("## Support")
    lines.append("Jesli projekt oszczedza Ci czas, wesprzyj dalszy rozwoj:")
    lines.append("https://github.com/sponsors/Piotr-Grechuta")
    lines.append("")
    return "\n".join(lines)


def main() -> int:
    parser = argparse.ArgumentParser(description="Generuje draft release notes (CHANGELOG + runtime metrics).")
    parser.add_argument("--output", type=Path, required=True, help="Sciezka wyjsciowa .md")
    parser.add_argument("--repo-root", type=Path, default=Path(__file__).resolve().parents[2], help="Root repo")
    parser.add_argument("--changelog", type=Path, default=None, help="Sciezka do CHANGELOG.md")
    parser.add_argument("--db-path", type=Path, default=None, help="Sciezka do SQLite z tabela runs/segment_ledger")
    parser.add_argument("--metrics-json", type=Path, default=None, help="Opcjonalny JSON z runtime metrics")
    parser.add_argument("--from-ref", type=str, default="", help="Poczatek zakresu git (np. v0.6.0)")
    parser.add_argument("--to-ref", type=str, default="HEAD", help="Koniec zakresu git")
    parser.add_argument("--title", type=str, default="Release Draft", help="Tytul dokumentu")
    args = parser.parse_args()

    repo_root = args.repo_root.resolve()
    changelog_path = args.changelog.resolve() if args.changelog else (repo_root / "CHANGELOG.md")
    commits = _git_commits(repo_root, args.from_ref, args.to_ref)
    changelog_unreleased = _extract_changelog_unreleased(changelog_path)

    metrics: Dict[str, Any] = {}
    if args.metrics_json is not None:
        metrics = _read_metrics_json(args.metrics_json.resolve())
    if not metrics and args.db_path is not None:
        metrics = _latest_runtime_metrics_from_db(args.db_path.resolve())

    body = build_release_notes(
        title=args.title,
        commits=commits,
        changelog_unreleased=changelog_unreleased,
        metrics=metrics,
        from_ref=args.from_ref,
        to_ref=args.to_ref,
    )
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(body, encoding="utf-8")
    print(f"[release-notes] written: {args.output}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
