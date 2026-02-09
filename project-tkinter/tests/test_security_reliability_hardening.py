from __future__ import annotations

import sys
import sqlite3
import zipfile
from pathlib import Path

import pytest

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from project_db import ProjectDB  # noqa: E402
from studio_suite import _safe_extract_zip  # noqa: E402


def test_recover_interrupted_runtime_state_marks_running_as_recoverable(tmp_path: Path) -> None:
    db_path = tmp_path / "studio.db"
    db = ProjectDB(db_path)
    try:
        pid = db.create_project("Recovery test")
        _ = db.start_run(pid, "translate", "python -u translation_engine.py ...")
    finally:
        db.close()

    db2 = ProjectDB(db_path, recover_runtime_state=True)
    try:
        row = db2.recent_runs(pid, limit=1)[0]
        assert str(row["status"]) == "error"
        assert int(row["finished_at"] or 0) > 0
        assert "interrupted recovery on startup" in str(row["message"] or "")

        project = db2.get_project(pid)
        assert project is not None
        assert str(project["status"]) == "pending"
    finally:
        db2.close()


def test_safe_extract_zip_allows_regular_entries(tmp_path: Path) -> None:
    archive = tmp_path / "ok.zip"
    dest = tmp_path / "dest"
    with zipfile.ZipFile(archive, "w", compression=zipfile.ZIP_DEFLATED) as zf:
        zf.writestr("folder/file.txt", "ok")

    with zipfile.ZipFile(archive, "r") as zf:
        _safe_extract_zip(zf, dest)

    assert (dest / "folder" / "file.txt").read_text(encoding="utf-8") == "ok"


def test_safe_extract_zip_blocks_path_traversal(tmp_path: Path) -> None:
    archive = tmp_path / "bad.zip"
    dest = tmp_path / "dest"
    outside = tmp_path / "outside.txt"
    with zipfile.ZipFile(archive, "w", compression=zipfile.ZIP_DEFLATED) as zf:
        zf.writestr("../outside.txt", "owned")

    with zipfile.ZipFile(archive, "r") as zf:
        with pytest.raises(ValueError, match="Unsafe zip entry path"):
            _safe_extract_zip(zf, dest)

    assert not outside.exists()


def test_managed_schema_migration_creates_backup_and_tracking_row(tmp_path: Path) -> None:
    db_path = tmp_path / "legacy_v7.db"
    raw = sqlite3.connect(str(db_path))
    raw.execute("CREATE TABLE IF NOT EXISTS meta (key TEXT PRIMARY KEY, value TEXT NOT NULL)")
    raw.execute("INSERT OR REPLACE INTO meta(key, value) VALUES('schema_version', '7')")
    raw.execute(
        """
        CREATE TABLE IF NOT EXISTS profiles (
          id INTEGER PRIMARY KEY AUTOINCREMENT,
          name TEXT NOT NULL UNIQUE,
          is_builtin INTEGER NOT NULL DEFAULT 0,
          settings_json TEXT NOT NULL,
          created_at INTEGER NOT NULL,
          updated_at INTEGER NOT NULL
        )
        """
    )
    raw.execute(
        """
        CREATE TABLE IF NOT EXISTS projects (
          id INTEGER PRIMARY KEY AUTOINCREMENT,
          name TEXT NOT NULL UNIQUE,
          input_epub TEXT NOT NULL DEFAULT '',
          output_translate_epub TEXT NOT NULL DEFAULT '',
          output_edit_epub TEXT NOT NULL DEFAULT '',
          prompt_translate TEXT NOT NULL DEFAULT '',
          prompt_edit TEXT NOT NULL DEFAULT '',
          glossary_path TEXT NOT NULL DEFAULT '',
          cache_translate_path TEXT NOT NULL DEFAULT '',
          cache_edit_path TEXT NOT NULL DEFAULT '',
          profile_translate_id INTEGER,
          profile_edit_id INTEGER,
          source_lang TEXT NOT NULL DEFAULT 'en',
          target_lang TEXT NOT NULL DEFAULT 'pl',
          active_step TEXT NOT NULL DEFAULT 'translate',
          status TEXT NOT NULL DEFAULT 'idle',
          notes TEXT NOT NULL DEFAULT '',
          created_at INTEGER NOT NULL,
          updated_at INTEGER NOT NULL
        )
        """
    )
    raw.execute(
        """
        CREATE TABLE IF NOT EXISTS runs (
          id INTEGER PRIMARY KEY AUTOINCREMENT,
          project_id INTEGER NOT NULL,
          step TEXT NOT NULL,
          status TEXT NOT NULL,
          command_text TEXT NOT NULL DEFAULT '',
          started_at INTEGER NOT NULL,
          finished_at INTEGER,
          global_done INTEGER NOT NULL DEFAULT 0,
          global_total INTEGER NOT NULL DEFAULT 0,
          message TEXT NOT NULL DEFAULT ''
        )
        """
    )
    raw.execute(
        """
        INSERT INTO projects(name, input_epub, output_translate_epub, output_edit_epub, created_at, updated_at)
        VALUES('Legacy project', '', '', '', 1, 1)
        """
    )
    raw.commit()
    raw.close()

    series_dir = tmp_path / "series_data"
    series_dir.mkdir(parents=True, exist_ok=True)
    (series_dir / "README.txt").write_text("series placeholder", encoding="utf-8")

    db = ProjectDB(db_path, backup_paths=[series_dir])
    try:
        assert db.last_migration_summary is not None
        assert int(db.last_migration_summary["from_schema"]) == 7
        assert int(db.last_migration_summary["to_schema"]) == 8
        backup_dir = Path(str(db.last_migration_summary["backup_dir"]))
        assert backup_dir.exists()
        assert (backup_dir / db_path.name).exists()

        mig = db.conn.execute(
            "SELECT status, from_schema, to_schema FROM migration_runs ORDER BY id DESC LIMIT 1"
        ).fetchone()
        assert mig is not None
        assert str(mig["status"]) == "ok"
        assert int(mig["from_schema"]) == 7
        assert int(mig["to_schema"]) == 8

        cols = {str(r["name"]) for r in db.conn.execute("PRAGMA table_info(projects)").fetchall()}
        assert "series_id" in cols
        assert "volume_no" in cols
    finally:
        db.close()
