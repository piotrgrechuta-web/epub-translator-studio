#!/usr/bin/env python3
# -*- coding: utf-8 -*-

from __future__ import annotations

import json
import hashlib
import logging
import os
import re
import sqlite3
import shutil
import time
import unicodedata
import zipfile
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

if os.name == "nt":
    import msvcrt  # type: ignore[attr-defined]
else:
    import fcntl  # type: ignore[import-not-found]


DB_FILE = "translator_studio.db"
SCHEMA_VERSION = 9
SCHEMA_META_KEY = "schema_version"
SCHEMA_META_ALIAS_KEY = "db_version"
PROVIDER_HEALTH_RETENTION_PER_PROVIDER = 200
LOG = logging.getLogger(__name__)


def _now_ts() -> int:
    return int(time.time())


def _slugify_name(value: str) -> str:
    text = unicodedata.normalize("NFKD", str(value or "")).encode("ascii", "ignore").decode("ascii")
    text = text.lower().strip()
    text = re.sub(r"[^a-z0-9]+", "-", text)
    text = text.strip("-")
    return text or "series"


def _acquire_init_lock(lock_path: Path, timeout_s: float = 30.0):
    lock_path.parent.mkdir(parents=True, exist_ok=True)
    fh = lock_path.open("a+b")
    deadline = time.time() + timeout_s
    while True:
        try:
            if os.name == "nt":
                fh.seek(0)
                msvcrt.locking(fh.fileno(), msvcrt.LK_NBLCK, 1)
            else:
                fcntl.flock(fh.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
            fh.seek(0)
            fh.truncate()
            fh.write(str(os.getpid()).encode("ascii", errors="ignore"))
            fh.flush()
            return fh
        except OSError:
            if time.time() >= deadline:
                fh.close()
                raise TimeoutError(f"DB init lock timeout: {lock_path}")
            time.sleep(0.1)


def _release_init_lock(fh) -> None:
    if fh is None:
        return
    try:
        if os.name == "nt":
            fh.seek(0)
            msvcrt.locking(fh.fileno(), msvcrt.LK_UNLCK, 1)
        else:
            fcntl.flock(fh.fileno(), fcntl.LOCK_UN)
    except Exception:
        LOG.debug("Failed to release DB init lock cleanly.", exc_info=True)
    try:
        fh.close()
    except Exception:
        LOG.debug("Failed to close DB init lock handle cleanly.", exc_info=True)


class ProjectDB:
    def __init__(
        self,
        path: Path,
        *,
        recover_runtime_state: bool = False,
        backup_paths: Optional[List[Path]] = None,
        run_migrations: bool = True,
    ) -> None:
        self.path = path
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._db_preexists = self.path.exists()
        self._backup_paths = [Path(p) for p in (backup_paths or [])]
        self.last_migration_summary: Optional[Dict[str, Any]] = None
        self.conn = sqlite3.connect(str(self.path), timeout=30.0)
        self.conn.row_factory = sqlite3.Row
        self.conn.execute("PRAGMA journal_mode = WAL")
        self.conn.execute("PRAGMA busy_timeout = 5000")
        self.conn.execute("PRAGMA foreign_keys = ON")
        lock_fh = _acquire_init_lock(self.path.with_suffix(self.path.suffix + ".init.lock"))
        try:
            self._init_schema()
            if run_migrations:
                current_schema = self._schema_version()
                if current_schema < SCHEMA_VERSION:
                    self.last_migration_summary = self._run_migrations_managed(
                        current_schema,
                        SCHEMA_VERSION,
                        backup_paths=self._backup_paths,
                    )
                else:
                    self._run_migrations()
            self._ensure_default_profiles()
            if recover_runtime_state:
                self.recover_interrupted_runtime_state()
        finally:
            _release_init_lock(lock_fh)

    def close(self) -> None:
        self.conn.close()

    def recover_interrupted_runtime_state(self) -> int:
        """Recover stale runtime rows left after hard app/process interruption."""
        now = _now_ts()
        interrupted_note = "interrupted recovery on startup"
        runs_cur = self.conn.execute(
            """
            UPDATE runs
            SET status = 'error',
                message = CASE
                    WHEN trim(message) = '' THEN ?
                    WHEN instr(message, ?) > 0 THEN message
                    ELSE message || ' | ' || ?
                END,
                finished_at = COALESCE(finished_at, ?)
            WHERE status = 'running'
            """,
            (interrupted_note, interrupted_note, interrupted_note, now),
        )
        projects_cur = self.conn.execute(
            """
            UPDATE projects
            SET status = 'pending',
                updated_at = ?
            WHERE status = 'running'
            """,
            (now,),
        )
        self.conn.commit()
        runs_changed = int(runs_cur.rowcount or 0)
        projects_changed = int(projects_cur.rowcount or 0)
        if runs_changed or projects_changed:
            LOG.info(
                "Recovered interrupted runtime state: runs=%s, projects=%s",
                runs_changed,
                projects_changed,
            )
        return runs_changed + projects_changed

    def _init_schema(self) -> None:
        cur = self.conn.cursor()
        cur.execute(
            """
            CREATE TABLE IF NOT EXISTS meta (
              key TEXT PRIMARY KEY,
              value TEXT NOT NULL
            )
            """
        )
        cur.execute(
            """
            CREATE TABLE IF NOT EXISTS app_settings (
              key TEXT PRIMARY KEY,
              value_json TEXT NOT NULL
            )
            """
        )
        cur.execute(
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
        cur.execute(
            """
            CREATE TABLE IF NOT EXISTS series (
              id INTEGER PRIMARY KEY AUTOINCREMENT,
              slug TEXT NOT NULL UNIQUE,
              name TEXT NOT NULL UNIQUE,
              source TEXT NOT NULL DEFAULT 'manual',
              notes TEXT NOT NULL DEFAULT '',
              created_at INTEGER NOT NULL,
              updated_at INTEGER NOT NULL
            )
            """
        )
        cur.execute(
            """
            CREATE TABLE IF NOT EXISTS projects (
              id INTEGER PRIMARY KEY AUTOINCREMENT,
              name TEXT NOT NULL UNIQUE,
              series_id INTEGER,
              volume_no REAL,
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
              updated_at INTEGER NOT NULL,
              FOREIGN KEY(series_id) REFERENCES series(id) ON DELETE SET NULL,
              FOREIGN KEY(profile_translate_id) REFERENCES profiles(id) ON DELETE SET NULL,
              FOREIGN KEY(profile_edit_id) REFERENCES profiles(id) ON DELETE SET NULL
            )
            """
        )
        cur.execute(
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
              message TEXT NOT NULL DEFAULT '',
              FOREIGN KEY(project_id) REFERENCES projects(id) ON DELETE CASCADE
            )
            """
        )
        cur.execute(
            """
            CREATE TABLE IF NOT EXISTS tm_segments (
              id INTEGER PRIMARY KEY AUTOINCREMENT,
              source_text TEXT NOT NULL,
              target_text TEXT NOT NULL,
              source_lang TEXT NOT NULL DEFAULT 'en',
              target_lang TEXT NOT NULL DEFAULT 'pl',
              source_hash TEXT NOT NULL,
              project_id INTEGER,
              score REAL NOT NULL DEFAULT 1.0,
              created_at INTEGER NOT NULL,
              FOREIGN KEY(project_id) REFERENCES projects(id) ON DELETE SET NULL
            )
            """
        )
        cur.execute(
            """
            CREATE TABLE IF NOT EXISTS provider_health_checks (
              id INTEGER PRIMARY KEY AUTOINCREMENT,
              provider TEXT NOT NULL,
              state TEXT NOT NULL,
              latency_ms INTEGER NOT NULL DEFAULT 0,
              model_count INTEGER NOT NULL DEFAULT 0,
              detail TEXT NOT NULL DEFAULT '',
              created_at INTEGER NOT NULL
            )
            """
        )
        cur.execute("CREATE INDEX IF NOT EXISTS idx_tm_source_hash ON tm_segments(source_hash)")
        cur.execute("CREATE INDEX IF NOT EXISTS idx_tm_src_len ON tm_segments(LENGTH(source_text))")
        cur.execute("CREATE INDEX IF NOT EXISTS idx_runs_project_started ON runs(project_id, started_at DESC)")
        cur.execute("CREATE INDEX IF NOT EXISTS idx_series_name ON series(name)")
        cur.execute("CREATE INDEX IF NOT EXISTS idx_health_provider_created ON provider_health_checks(provider, created_at DESC)")
        self._ensure_migration_tracking_table(cur)
        project_cols = {str(r["name"]) for r in self.conn.execute("PRAGMA table_info(projects)").fetchall()}
        if "series_id" in project_cols:
            cur.execute("CREATE INDEX IF NOT EXISTS idx_projects_series ON projects(series_id, updated_at DESC)")

        version = self._meta_get(SCHEMA_META_KEY)
        alias = self._meta_get(SCHEMA_META_ALIAS_KEY)
        if version is None and alias is None:
            self._set_schema_version_meta(1)
        elif version is None and alias is not None:
            self._meta_set(SCHEMA_META_KEY, str(alias).strip())
        elif version is not None and alias is None:
            self._meta_set(SCHEMA_META_ALIAS_KEY, str(version).strip())
        elif str(version).strip() != str(alias).strip():
            LOG.warning(
                "Schema metadata mismatch (%s=%r, %s=%r). Using %s.",
                SCHEMA_META_KEY,
                version,
                SCHEMA_META_ALIAS_KEY,
                alias,
                SCHEMA_META_KEY,
            )
            self._meta_set(SCHEMA_META_ALIAS_KEY, str(version).strip())
        self.conn.commit()

    def _ensure_migration_tracking_table(self, cur: sqlite3.Cursor) -> None:
        cur.execute(
            """
            CREATE TABLE IF NOT EXISTS migration_runs (
              id INTEGER PRIMARY KEY AUTOINCREMENT,
              from_schema INTEGER NOT NULL,
              to_schema INTEGER NOT NULL,
              status TEXT NOT NULL DEFAULT 'running',
              backup_dir TEXT NOT NULL DEFAULT '',
              error_message TEXT NOT NULL DEFAULT '',
              rollback_applied INTEGER NOT NULL DEFAULT 0,
              started_at INTEGER NOT NULL,
              finished_at INTEGER
            )
            """
        )
        cur.execute("CREATE INDEX IF NOT EXISTS idx_migration_runs_started ON migration_runs(started_at DESC)")

    def _start_migration_run(self, from_schema: int, to_schema: int, backup_dir: Path) -> int:
        now = _now_ts()
        cur = self.conn.execute(
            """
            INSERT INTO migration_runs(from_schema, to_schema, status, backup_dir, started_at)
            VALUES(?, ?, 'running', ?, ?)
            """,
            (int(from_schema), int(to_schema), str(backup_dir), now),
        )
        self.conn.commit()
        return int(cur.lastrowid)

    def _finish_migration_run(
        self,
        run_id: int,
        *,
        status: str,
        error_message: str = "",
        rollback_applied: bool = False,
    ) -> None:
        self.conn.execute(
            """
            UPDATE migration_runs
            SET status = ?,
                error_message = ?,
                rollback_applied = ?,
                finished_at = ?
            WHERE id = ?
            """,
            (str(status), str(error_message), 1 if rollback_applied else 0, _now_ts(), int(run_id)),
        )
        self.conn.commit()

    def _create_migration_backup(
        self,
        from_schema: int,
        to_schema: int,
        *,
        backup_paths: List[Path],
    ) -> Dict[str, Any]:
        ts = time.strftime("%Y%m%d_%H%M%S")
        backup_dir = self.path.parent / "migration_backups" / f"schema_{from_schema}_to_{to_schema}_{ts}"
        backup_dir.mkdir(parents=True, exist_ok=True)

        db_backup = backup_dir / self.path.name
        bconn = sqlite3.connect(str(db_backup))
        try:
            self.conn.backup(bconn)
        finally:
            bconn.close()

        wal_backup = backup_dir / f"{self.path.name}-wal"
        shm_backup = backup_dir / f"{self.path.name}-shm"
        src_wal = self.path.with_name(self.path.name + "-wal")
        src_shm = self.path.with_name(self.path.name + "-shm")
        if src_wal.exists():
            shutil.copy2(src_wal, wal_backup)
        if src_shm.exists():
            shutil.copy2(src_shm, shm_backup)

        extra_archives: List[Dict[str, str]] = []
        for idx, raw in enumerate(backup_paths):
            p = Path(raw)
            if not p.exists():
                continue
            zip_name = backup_dir / f"extra_{idx:02d}_{p.name}"
            zip_path = shutil.make_archive(str(zip_name), "zip", root_dir=str(p.parent), base_dir=p.name)
            extra_archives.append({"source": str(p), "zip": str(zip_path)})

        payload = {
            "backup_dir": str(backup_dir),
            "db_backup": str(db_backup),
            "wal_backup": str(wal_backup),
            "shm_backup": str(shm_backup),
            "extra_archives": extra_archives,
            "from_schema": int(from_schema),
            "to_schema": int(to_schema),
            "created_at": _now_ts(),
        }
        manifest_path = backup_dir / "backup_manifest.json"
        manifest_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
        payload["manifest_path"] = str(manifest_path)
        return payload

    def _load_backup_manifest(self, backup_dir: Path) -> Optional[Dict[str, Any]]:
        p = Path(backup_dir) / "backup_manifest.json"
        if not p.exists():
            return None
        try:
            data = json.loads(p.read_text(encoding="utf-8"))
        except Exception:
            return None
        if not isinstance(data, dict):
            return None
        return data

    def _restore_migration_backup(self, backup: Dict[str, Any]) -> bool:
        backup_db = Path(str(backup.get("db_backup", "")).strip())
        if not backup_db.exists():
            return False

        try:
            self.conn.close()
        except Exception:
            pass

        shutil.copy2(backup_db, self.path)

        db_wal = self.path.with_name(self.path.name + "-wal")
        db_shm = self.path.with_name(self.path.name + "-shm")
        wal_backup = Path(str(backup.get("wal_backup", "")).strip())
        shm_backup = Path(str(backup.get("shm_backup", "")).strip())
        if wal_backup.exists():
            shutil.copy2(wal_backup, db_wal)
        elif db_wal.exists():
            db_wal.unlink()
        if shm_backup.exists():
            shutil.copy2(shm_backup, db_shm)
        elif db_shm.exists():
            db_shm.unlink()

        for item in backup.get("extra_archives", []) or []:
            source = Path(str(item.get("source", "")).strip())
            zip_path = Path(str(item.get("zip", "")).strip())
            if not zip_path.exists():
                continue
            if source.exists():
                if source.is_dir():
                    shutil.rmtree(source)
                else:
                    source.unlink()
            with zipfile.ZipFile(zip_path, "r") as zf:
                zf.extractall(str(source.parent))
        self.conn = sqlite3.connect(str(self.path), timeout=30.0)
        self.conn.row_factory = sqlite3.Row
        self.conn.execute("PRAGMA journal_mode = WAL")
        self.conn.execute("PRAGMA busy_timeout = 5000")
        self.conn.execute("PRAGMA foreign_keys = ON")
        return True

    def _run_migrations_managed(
        self,
        from_schema: int,
        to_schema: int,
        *,
        backup_paths: List[Path],
    ) -> Dict[str, Any]:
        backup = self._create_migration_backup(from_schema, to_schema, backup_paths=backup_paths)
        backup_dir = Path(str(backup["backup_dir"]))
        run_id = self._start_migration_run(from_schema, to_schema, backup_dir)
        try:
            self._run_migrations()
            summary = {
                "from_schema": int(from_schema),
                "to_schema": int(self._schema_version()),
                "backup_dir": str(backup_dir),
                "status": "ok",
                "migration_run_id": int(run_id),
            }
            self._finish_migration_run(run_id, status="ok")
            return summary
        except Exception as e:
            err = f"{type(e).__name__}: {e}"
            try:
                self._finish_migration_run(run_id, status="error", error_message=err, rollback_applied=False)
            except Exception:
                pass
            rollback_ok = False
            try:
                rollback_ok = self._restore_migration_backup(backup)
            except Exception:
                rollback_ok = False
            raise RuntimeError(
                f"Schema migration failed ({from_schema} -> {to_schema}). "
                f"Backup: {backup_dir}. Rollback: {'ok' if rollback_ok else 'failed'}. "
                f"Original error: {err}"
            ) from e

    def list_migration_runs(self, limit: int = 20) -> List[sqlite3.Row]:
        return list(
            self.conn.execute(
                "SELECT * FROM migration_runs ORDER BY id DESC LIMIT ?",
                (max(1, int(limit)),),
            )
        )

    def latest_migration_run(self) -> Optional[sqlite3.Row]:
        return self.conn.execute(
            "SELECT * FROM migration_runs ORDER BY id DESC LIMIT 1"
        ).fetchone()

    def rollback_last_migration(self) -> Tuple[bool, str]:
        row = self.latest_migration_run()
        if row is None:
            return False, "Brak wpisow migracji do rollback."

        from_schema = int(row["from_schema"] or 0)
        to_schema = int(row["to_schema"] or 0)
        backup_dir = Path(str(row["backup_dir"] or "").strip())
        manifest = self._load_backup_manifest(backup_dir)
        if manifest is None:
            return False, f"Brak manifestu backupu: {backup_dir}"

        ok = self._restore_migration_backup(manifest)
        if not ok:
            return False, f"Nie udalo sie przywrocic backupu z: {backup_dir}"

        now = _now_ts()
        self.conn.execute(
            """
            INSERT INTO migration_runs(
                from_schema, to_schema, status, backup_dir, error_message, rollback_applied, started_at, finished_at
            ) VALUES(?, ?, 'rolled_back', ?, 'rollback applied manually', 1, ?, ?)
            """,
            (from_schema, to_schema, str(backup_dir), now, now),
        )
        self.conn.commit()
        return True, f"Rollback zakonczony powodzeniem. Backup: {backup_dir}"

    def build_migration_report(self, limit: int = 50) -> Dict[str, Any]:
        rows = [dict(r) for r in self.list_migration_runs(limit=limit)]
        return {
            "db_path": str(self.path),
            "schema_version": int(self._schema_version()),
            "generated_at": _now_ts(),
            "rows": rows,
        }

    def _set_schema_version_meta(self, version: int) -> None:
        raw = str(int(version))
        self._meta_set(SCHEMA_META_KEY, raw)
        self._meta_set(SCHEMA_META_ALIAS_KEY, raw)

    def _schema_version(self) -> int:
        raw = self._meta_get(SCHEMA_META_KEY)
        alias = self._meta_get(SCHEMA_META_ALIAS_KEY)
        if raw is None and alias is not None:
            raw = alias
            self._meta_set(SCHEMA_META_KEY, str(alias).strip())
            self.conn.commit()
        elif raw is not None and alias is None:
            self._meta_set(SCHEMA_META_ALIAS_KEY, str(raw).strip())
            self.conn.commit()
        elif raw is not None and alias is not None and str(raw).strip() != str(alias).strip():
            LOG.warning(
                "Schema metadata mismatch (%s=%r, %s=%r). Using %s.",
                SCHEMA_META_KEY,
                raw,
                SCHEMA_META_ALIAS_KEY,
                alias,
                SCHEMA_META_KEY,
            )
            self._meta_set(SCHEMA_META_ALIAS_KEY, str(raw).strip())
            self.conn.commit()
        if raw is None:
            return 0
        try:
            return int(str(raw).strip())
        except Exception:
            LOG.warning("Invalid schema version value in meta table: %r", raw)
            return 0

    def _backup_before_migration(self, from_version: int, to_version: int) -> Optional[Path]:
        if not self._db_preexists:
            return None
        ts = time.strftime("%Y%m%d_%H%M%S")
        backup = self.path.with_name(f"{self.path.name}.bak-v{from_version}-to-v{to_version}-{ts}")
        try:
            self.conn.commit()
            shutil.copy2(self.path, backup)
            return backup
        except Exception as e:
            LOG.warning("Failed to create DB migration backup '%s': %s", backup, e)
            return None

    def _run_migrations(self) -> None:
        current = self._schema_version()
        if current <= 0:
            current = 1
            self._set_schema_version_meta(1)
            self.conn.commit()
        if current >= SCHEMA_VERSION:
            self._ensure_schema_integrity()
            return
        _ = self._backup_before_migration(current, SCHEMA_VERSION)
        cur = self.conn.cursor()
        while current < SCHEMA_VERSION:
            if current == 1:
                cur.execute(
                    """
                    CREATE TABLE IF NOT EXISTS audit_events (
                      id INTEGER PRIMARY KEY AUTOINCREMENT,
                      event_type TEXT NOT NULL,
                      payload_json TEXT NOT NULL,
                      created_at INTEGER NOT NULL
                    )
                    """
                )
                cur.execute("CREATE INDEX IF NOT EXISTS idx_audit_events_created ON audit_events(created_at DESC)")
                current = 2
                self._set_schema_version_meta(current)
                self.conn.commit()
            elif current == 2:
                cur.execute(
                    """
                    CREATE TABLE IF NOT EXISTS qa_findings (
                      id INTEGER PRIMARY KEY AUTOINCREMENT,
                      project_id INTEGER NOT NULL,
                      step TEXT NOT NULL,
                      chapter_path TEXT NOT NULL,
                      segment_index INTEGER NOT NULL,
                      segment_id TEXT NOT NULL DEFAULT '',
                      severity TEXT NOT NULL,
                      rule_code TEXT NOT NULL,
                      message TEXT NOT NULL,
                      status TEXT NOT NULL DEFAULT 'open',
                      assignee TEXT NOT NULL DEFAULT '',
                      created_at INTEGER NOT NULL,
                      updated_at INTEGER NOT NULL,
                      FOREIGN KEY(project_id) REFERENCES projects(id) ON DELETE CASCADE
                    )
                    """
                )
                cur.execute("CREATE INDEX IF NOT EXISTS idx_qa_project_status ON qa_findings(project_id, status)")
                cur.execute("CREATE INDEX IF NOT EXISTS idx_qa_project_step ON qa_findings(project_id, step)")
                current = 3
                self._set_schema_version_meta(current)
                self.conn.commit()
            elif current == 3:
                cur.execute(
                    """
                    CREATE TABLE IF NOT EXISTS qa_reviews (
                      id INTEGER PRIMARY KEY AUTOINCREMENT,
                      project_id INTEGER NOT NULL,
                      step TEXT NOT NULL,
                      status TEXT NOT NULL DEFAULT 'pending',
                      approver TEXT NOT NULL DEFAULT '',
                      notes TEXT NOT NULL DEFAULT '',
                      created_at INTEGER NOT NULL,
                      updated_at INTEGER NOT NULL,
                      FOREIGN KEY(project_id) REFERENCES projects(id) ON DELETE CASCADE
                    )
                    """
                )
                cur.execute("CREATE INDEX IF NOT EXISTS idx_qa_reviews_project_step ON qa_reviews(project_id, step, updated_at DESC)")
                current = 4
                self._set_schema_version_meta(current)
                self.conn.commit()
            elif current == 4:
                # Assignment + SLA fields for QA findings.
                cols = {str(r["name"]) for r in self.conn.execute("PRAGMA table_info(qa_findings)").fetchall()}
                if "due_at" not in cols:
                    cur.execute("ALTER TABLE qa_findings ADD COLUMN due_at INTEGER")
                if "escalated_at" not in cols:
                    cur.execute("ALTER TABLE qa_findings ADD COLUMN escalated_at INTEGER")
                if "escalation_status" not in cols:
                    cur.execute("ALTER TABLE qa_findings ADD COLUMN escalation_status TEXT NOT NULL DEFAULT 'none'")
                cur.execute("CREATE INDEX IF NOT EXISTS idx_qa_due ON qa_findings(project_id, due_at)")
                current = 5
                self._set_schema_version_meta(current)
                self.conn.commit()
            elif current == 5:
                cols = {str(r["name"]) for r in self.conn.execute("PRAGMA table_info(projects)").fetchall()}
                if "source_lang" not in cols:
                    cur.execute("ALTER TABLE projects ADD COLUMN source_lang TEXT NOT NULL DEFAULT 'en'")
                if "target_lang" not in cols:
                    cur.execute("ALTER TABLE projects ADD COLUMN target_lang TEXT NOT NULL DEFAULT 'pl'")
                current = 6
                self._set_schema_version_meta(current)
                self.conn.commit()
            elif current == 6:
                cols = {str(r["name"]) for r in self.conn.execute("PRAGMA table_info(qa_findings)").fetchall()}
                if "segment_id" not in cols:
                    cur.execute("ALTER TABLE qa_findings ADD COLUMN segment_id TEXT NOT NULL DEFAULT ''")
                cur.execute("CREATE INDEX IF NOT EXISTS idx_qa_project_segment ON qa_findings(project_id, step, chapter_path, segment_id)")
                current = 7
                self._set_schema_version_meta(current)
                self.conn.commit()
            elif current == 7:
                cur.execute(
                    """
                    CREATE TABLE IF NOT EXISTS series (
                      id INTEGER PRIMARY KEY AUTOINCREMENT,
                      slug TEXT NOT NULL UNIQUE,
                      name TEXT NOT NULL UNIQUE,
                      source TEXT NOT NULL DEFAULT 'manual',
                      notes TEXT NOT NULL DEFAULT '',
                      created_at INTEGER NOT NULL,
                      updated_at INTEGER NOT NULL
                    )
                    """
                )
                cols = {str(r["name"]) for r in self.conn.execute("PRAGMA table_info(projects)").fetchall()}
                if "series_id" not in cols:
                    cur.execute("ALTER TABLE projects ADD COLUMN series_id INTEGER")
                if "volume_no" not in cols:
                    cur.execute("ALTER TABLE projects ADD COLUMN volume_no REAL")
                cur.execute("CREATE INDEX IF NOT EXISTS idx_series_name ON series(name)")
                cur.execute("CREATE INDEX IF NOT EXISTS idx_projects_series ON projects(series_id, updated_at DESC)")
                current = 8
                self._set_schema_version_meta(current)
                self.conn.commit()
            elif current == 8:
                cur.execute(
                    """
                    CREATE TABLE IF NOT EXISTS provider_health_checks (
                      id INTEGER PRIMARY KEY AUTOINCREMENT,
                      provider TEXT NOT NULL,
                      state TEXT NOT NULL,
                      latency_ms INTEGER NOT NULL DEFAULT 0,
                      model_count INTEGER NOT NULL DEFAULT 0,
                      detail TEXT NOT NULL DEFAULT '',
                      created_at INTEGER NOT NULL
                    )
                    """
                )
                cur.execute("CREATE INDEX IF NOT EXISTS idx_health_provider_created ON provider_health_checks(provider, created_at DESC)")
                current = 9
                self._set_schema_version_meta(current)
                self.conn.commit()
            else:
                raise RuntimeError(f"Nieznana sciezka migracji z wersji {current}")
        self._ensure_schema_integrity()

    def _ensure_schema_integrity(self) -> None:
        cur = self.conn.cursor()
        cur.execute(
            """
            CREATE TABLE IF NOT EXISTS audit_events (
              id INTEGER PRIMARY KEY AUTOINCREMENT,
              event_type TEXT NOT NULL,
              payload_json TEXT NOT NULL,
              created_at INTEGER NOT NULL
            )
            """
        )
        cur.execute(
            """
            CREATE TABLE IF NOT EXISTS qa_findings (
              id INTEGER PRIMARY KEY AUTOINCREMENT,
              project_id INTEGER NOT NULL,
              step TEXT NOT NULL,
              chapter_path TEXT NOT NULL,
              segment_index INTEGER NOT NULL,
              segment_id TEXT NOT NULL DEFAULT '',
              severity TEXT NOT NULL,
              rule_code TEXT NOT NULL,
              message TEXT NOT NULL,
              status TEXT NOT NULL DEFAULT 'open',
              assignee TEXT NOT NULL DEFAULT '',
              due_at INTEGER,
              escalated_at INTEGER,
              escalation_status TEXT NOT NULL DEFAULT 'none',
              created_at INTEGER NOT NULL,
              updated_at INTEGER NOT NULL,
              FOREIGN KEY(project_id) REFERENCES projects(id) ON DELETE CASCADE
            )
            """
        )
        cur.execute(
            """
            CREATE TABLE IF NOT EXISTS qa_reviews (
              id INTEGER PRIMARY KEY AUTOINCREMENT,
              project_id INTEGER NOT NULL,
              step TEXT NOT NULL,
              status TEXT NOT NULL DEFAULT 'pending',
              approver TEXT NOT NULL DEFAULT '',
              notes TEXT NOT NULL DEFAULT '',
              created_at INTEGER NOT NULL,
              updated_at INTEGER NOT NULL,
              FOREIGN KEY(project_id) REFERENCES projects(id) ON DELETE CASCADE
            )
            """
        )
        cur.execute(
            """
            CREATE TABLE IF NOT EXISTS series (
              id INTEGER PRIMARY KEY AUTOINCREMENT,
              slug TEXT NOT NULL UNIQUE,
              name TEXT NOT NULL UNIQUE,
              source TEXT NOT NULL DEFAULT 'manual',
              notes TEXT NOT NULL DEFAULT '',
              created_at INTEGER NOT NULL,
              updated_at INTEGER NOT NULL
            )
            """
        )
        cur.execute(
            """
            CREATE TABLE IF NOT EXISTS provider_health_checks (
              id INTEGER PRIMARY KEY AUTOINCREMENT,
              provider TEXT NOT NULL,
              state TEXT NOT NULL,
              latency_ms INTEGER NOT NULL DEFAULT 0,
              model_count INTEGER NOT NULL DEFAULT 0,
              detail TEXT NOT NULL DEFAULT '',
              created_at INTEGER NOT NULL
            )
            """
        )

        project_cols = {str(r["name"]) for r in self.conn.execute("PRAGMA table_info(projects)").fetchall()}
        if "source_lang" not in project_cols:
            cur.execute("ALTER TABLE projects ADD COLUMN source_lang TEXT NOT NULL DEFAULT 'en'")
        if "target_lang" not in project_cols:
            cur.execute("ALTER TABLE projects ADD COLUMN target_lang TEXT NOT NULL DEFAULT 'pl'")
        if "series_id" not in project_cols:
            cur.execute("ALTER TABLE projects ADD COLUMN series_id INTEGER")
        if "volume_no" not in project_cols:
            cur.execute("ALTER TABLE projects ADD COLUMN volume_no REAL")

        finding_cols = {str(r["name"]) for r in self.conn.execute("PRAGMA table_info(qa_findings)").fetchall()}
        if "segment_id" not in finding_cols:
            cur.execute("ALTER TABLE qa_findings ADD COLUMN segment_id TEXT NOT NULL DEFAULT ''")
        if "due_at" not in finding_cols:
            cur.execute("ALTER TABLE qa_findings ADD COLUMN due_at INTEGER")
        if "escalated_at" not in finding_cols:
            cur.execute("ALTER TABLE qa_findings ADD COLUMN escalated_at INTEGER")
        if "escalation_status" not in finding_cols:
            cur.execute("ALTER TABLE qa_findings ADD COLUMN escalation_status TEXT NOT NULL DEFAULT 'none'")

        cur.execute("CREATE INDEX IF NOT EXISTS idx_audit_events_created ON audit_events(created_at DESC)")
        cur.execute("CREATE INDEX IF NOT EXISTS idx_qa_project_status ON qa_findings(project_id, status)")
        cur.execute("CREATE INDEX IF NOT EXISTS idx_qa_project_step ON qa_findings(project_id, step)")
        cur.execute("CREATE INDEX IF NOT EXISTS idx_qa_project_segment ON qa_findings(project_id, step, chapter_path, segment_id)")
        cur.execute("CREATE INDEX IF NOT EXISTS idx_qa_due ON qa_findings(project_id, due_at)")
        cur.execute("CREATE INDEX IF NOT EXISTS idx_qa_reviews_project_step ON qa_reviews(project_id, step, updated_at DESC)")
        cur.execute("CREATE INDEX IF NOT EXISTS idx_series_name ON series(name)")
        cur.execute("CREATE INDEX IF NOT EXISTS idx_projects_series ON projects(series_id, updated_at DESC)")
        cur.execute("CREATE INDEX IF NOT EXISTS idx_health_provider_created ON provider_health_checks(provider, created_at DESC)")
        self._set_schema_version_meta(SCHEMA_VERSION)
        self.conn.commit()

    def log_audit_event(self, event_type: str, payload: Dict[str, Any]) -> None:
        try:
            self.conn.execute(
                "INSERT INTO audit_events(event_type, payload_json, created_at) VALUES(?, ?, ?)",
                (str(event_type), json.dumps(payload, ensure_ascii=False), _now_ts()),
            )
            self.conn.commit()
        except Exception as e:
            LOG.warning("Failed to write audit event '%s': %s", event_type, e)

    def replace_qa_findings(self, project_id: int, step: str, findings: List[Dict[str, Any]]) -> int:
        now = _now_ts()
        self.conn.execute(
            "DELETE FROM qa_findings WHERE project_id = ? AND step = ? AND status IN ('open','in_progress')",
            (project_id, step),
        )
        rows = []
        for f in findings:
            rows.append(
                (
                    project_id,
                    step,
                    str(f.get("chapter_path", "")),
                    int(f.get("segment_index", 0)),
                    str(f.get("segment_id", "") or f"{f.get('chapter_path', '')}#{int(f.get('segment_index', 0))}"),
                    str(f.get("severity", "warn")),
                    str(f.get("rule_code", "GENERIC")),
                    str(f.get("message", "")),
                    "open",
                    str(f.get("assignee", "")),
                    now,
                    now,
                )
            )
        if rows:
            self.conn.executemany(
                """
                INSERT INTO qa_findings(
                  project_id, step, chapter_path, segment_index, segment_id, severity, rule_code, message,
                  status, assignee, created_at, updated_at
                ) VALUES(?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                rows,
            )
        self.conn.commit()
        return len(rows)

    def list_qa_findings(self, project_id: int, step: Optional[str] = None, status: Optional[str] = None) -> List[sqlite3.Row]:
        q = "SELECT * FROM qa_findings WHERE project_id = ?"
        args: List[Any] = [project_id]
        if step is not None:
            q += " AND step = ?"
            args.append(step)
        if status is not None:
            q += " AND status = ?"
            args.append(status)
        q += " ORDER BY severity DESC, updated_at DESC, id DESC"
        return list(self.conn.execute(q, args))

    def update_qa_finding_status(self, finding_id: int, status: str, assignee: Optional[str] = None) -> None:
        now = _now_ts()
        if assignee is None:
            self.conn.execute(
                "UPDATE qa_findings SET status = ?, updated_at = ? WHERE id = ?",
                (status, now, finding_id),
            )
        else:
            self.conn.execute(
                "UPDATE qa_findings SET status = ?, assignee = ?, updated_at = ? WHERE id = ?",
                (status, assignee, now, finding_id),
            )
        self.conn.commit()

    def assign_qa_finding(self, finding_id: int, assignee: str, due_at: Optional[int]) -> None:
        now = _now_ts()
        self.conn.execute(
            "UPDATE qa_findings SET assignee = ?, due_at = ?, updated_at = ? WHERE id = ?",
            (assignee, due_at, now, finding_id),
        )
        self.conn.commit()

    def assign_open_findings(self, project_id: int, step: str, assignee: str, due_at: Optional[int]) -> int:
        now = _now_ts()
        cur = self.conn.execute(
            """
            UPDATE qa_findings
            SET assignee = ?, due_at = ?, updated_at = ?
            WHERE project_id = ? AND step = ? AND status IN ('open','in_progress')
            """,
            (assignee, due_at, now, project_id, step),
        )
        self.conn.commit()
        return int(cur.rowcount if cur.rowcount is not None else 0)

    def escalate_overdue_findings(self, project_id: Optional[int] = None, now_ts: Optional[int] = None) -> int:
        now = int(now_ts if now_ts is not None else _now_ts())
        if project_id is None:
            cur = self.conn.execute(
                """
                UPDATE qa_findings
                SET escalation_status = 'overdue', escalated_at = ?, updated_at = ?
                WHERE status IN ('open','in_progress') AND due_at IS NOT NULL AND due_at < ?
                  AND (escalation_status IS NULL OR escalation_status = 'none')
                """,
                (now, now, now),
            )
        else:
            cur = self.conn.execute(
                """
                UPDATE qa_findings
                SET escalation_status = 'overdue', escalated_at = ?, updated_at = ?
                WHERE project_id = ? AND status IN ('open','in_progress') AND due_at IS NOT NULL AND due_at < ?
                  AND (escalation_status IS NULL OR escalation_status = 'none')
                """,
                (now, now, project_id, now),
            )
        self.conn.commit()
        return int(cur.rowcount if cur.rowcount is not None else 0)

    def list_overdue_findings(self, project_id: Optional[int] = None) -> List[sqlite3.Row]:
        if project_id is None:
            return list(
                self.conn.execute(
                    """
                    SELECT * FROM qa_findings
                    WHERE escalation_status = 'overdue' AND status IN ('open','in_progress')
                    ORDER BY due_at ASC, updated_at DESC
                    """
                )
            )
        return list(
            self.conn.execute(
                """
                SELECT * FROM qa_findings
                WHERE project_id = ? AND escalation_status = 'overdue' AND status IN ('open','in_progress')
                ORDER BY due_at ASC, updated_at DESC
                """,
                (project_id,),
            )
        )

    def count_open_qa_findings(self, project_id: int, step: Optional[str] = None) -> int:
        if step is None:
            row = self.conn.execute(
                "SELECT COUNT(*) c FROM qa_findings WHERE project_id = ? AND status IN ('open','in_progress')",
                (project_id,),
            ).fetchone()
        else:
            row = self.conn.execute(
                "SELECT COUNT(*) c FROM qa_findings WHERE project_id = ? AND step = ? AND status IN ('open','in_progress')",
                (project_id, step),
            ).fetchone()
        return int(row["c"]) if row else 0

    def count_qa_findings(self, project_id: int, step: Optional[str] = None) -> int:
        if step is None:
            row = self.conn.execute(
                "SELECT COUNT(*) c FROM qa_findings WHERE project_id = ?",
                (project_id,),
            ).fetchone()
        else:
            row = self.conn.execute(
                "SELECT COUNT(*) c FROM qa_findings WHERE project_id = ? AND step = ?",
                (project_id, step),
            ).fetchone()
        return int(row["c"]) if row else 0

    def set_qa_review(self, project_id: int, step: str, status: str, approver: str = "", notes: str = "") -> int:
        now = _now_ts()
        cur = self.conn.execute(
            """
            INSERT INTO qa_reviews(project_id, step, status, approver, notes, created_at, updated_at)
            VALUES(?, ?, ?, ?, ?, ?, ?)
            """,
            (project_id, step, status, approver, notes, now, now),
        )
        self.conn.commit()
        return int(cur.lastrowid)

    def latest_qa_review(self, project_id: int, step: str) -> Optional[sqlite3.Row]:
        return self.conn.execute(
            "SELECT * FROM qa_reviews WHERE project_id = ? AND step = ? ORDER BY updated_at DESC, id DESC LIMIT 1",
            (project_id, step),
        ).fetchone()

    def qa_gate_status(self, project_id: int, step: str) -> Tuple[bool, str]:
        open_count = self.count_open_qa_findings(project_id, step=step)
        if open_count > 0:
            return False, f"Otwartych findings: {open_count}"
        total = self.count_qa_findings(project_id, step=step)
        if total == 0:
            return True, "Brak findings - gate pass"
        rev = self.latest_qa_review(project_id, step)
        if rev is None:
            return False, "Brak review QA (approve/reject)"
        status = str(rev["status"] or "").strip().lower()
        if status == "approved":
            return True, "QA approved"
        if status == "rejected":
            return False, "QA rejected"
        return False, f"QA review status: {status or 'pending'}"

    def qa_severity_gate_status(
        self,
        project_id: int,
        step: str,
        severities: Tuple[str, ...] = ("fatal", "error"),
    ) -> Tuple[bool, str]:
        normalized = [str(x or "").strip().lower() for x in severities if str(x or "").strip()]
        if not normalized:
            return True, "Brak severity do gate"
        placeholders = ",".join(["?"] * len(normalized))
        args: List[Any] = [project_id, step]
        args.extend(normalized)
        row = self.conn.execute(
            f"""
            SELECT COUNT(*) c
            FROM qa_findings
            WHERE project_id = ?
              AND step = ?
              AND status IN ('open','in_progress')
              AND lower(severity) IN ({placeholders})
            """,
            tuple(args),
        ).fetchone()
        count = int(row["c"]) if row else 0
        if count > 0:
            sev_label = "/".join(normalized)
            return False, f"Otwartych findings {sev_label}: {count}"
        return True, "Brak otwartych findings high-severity"

    def record_provider_health_checks(self, rows: List[Dict[str, Any]]) -> int:
        payload: List[Tuple[str, str, int, int, str, int]] = []
        providers: set[str] = set()
        now = _now_ts()
        for raw in rows:
            provider = str(raw.get("provider", "") or "").strip().lower()
            state = str(raw.get("state", "fail") or "fail").strip().lower()
            if not provider:
                continue
            if state not in {"ok", "fail", "skip"}:
                state = "fail"
            try:
                latency_ms = max(0, int(raw.get("latency_ms", 0) or 0))
            except Exception:
                latency_ms = 0
            try:
                model_count = max(0, int(raw.get("model_count", 0) or 0))
            except Exception:
                model_count = 0
            detail = str(raw.get("detail", "") or "").strip()
            payload.append((provider, state, latency_ms, model_count, detail, now))
            providers.add(provider)
        if not payload:
            return 0
        self.conn.executemany(
            """
            INSERT INTO provider_health_checks(provider, state, latency_ms, model_count, detail, created_at)
            VALUES(?, ?, ?, ?, ?, ?)
            """,
            payload,
        )
        for provider in providers:
            self._prune_provider_health_checks(
                provider,
                keep_last=PROVIDER_HEALTH_RETENTION_PER_PROVIDER,
            )
        self.conn.commit()
        return len(payload)

    def _prune_provider_health_checks(self, provider: str, *, keep_last: int) -> int:
        safe_provider = str(provider or "").strip().lower()
        if not safe_provider:
            return 0
        safe_keep = max(1, int(keep_last))
        rows = list(
            self.conn.execute(
                """
                SELECT id
                FROM provider_health_checks
                WHERE provider = ?
                ORDER BY id DESC
                LIMIT -1 OFFSET ?
                """,
                (safe_provider, safe_keep),
            )
        )
        if not rows:
            return 0
        self.conn.executemany(
            "DELETE FROM provider_health_checks WHERE id = ?",
            [(int(row["id"]),) for row in rows],
        )
        return len(rows)

    def list_provider_health_checks(self, provider: Optional[str] = None, limit: int = 50) -> List[sqlite3.Row]:
        safe_limit = max(1, int(limit))
        if provider:
            return list(
                self.conn.execute(
                    """
                    SELECT *
                    FROM provider_health_checks
                    WHERE provider = ?
                    ORDER BY id DESC
                    LIMIT ?
                    """,
                    (str(provider).strip().lower(), safe_limit),
                )
            )
        return list(
            self.conn.execute(
                """
                SELECT *
                FROM provider_health_checks
                ORDER BY id DESC
                LIMIT ?
                """,
                (safe_limit,),
            )
        )

    def provider_health_summary(self, provider: str, *, window: int = 20) -> Dict[str, Any]:
        safe_provider = str(provider or "").strip().lower()
        if not safe_provider:
            return {
                "provider": "",
                "window": 0,
                "total": 0,
                "ok": 0,
                "fail": 0,
                "skip": 0,
                "failure_streak": 0,
                "avg_latency_ms": 0,
                "latest_state": "n/a",
            }
        safe_window = max(1, int(window))
        rows = self.list_provider_health_checks(safe_provider, limit=safe_window)
        ok = 0
        fail = 0
        skip = 0
        latencies: List[int] = []
        streak = 0
        for idx, row in enumerate(rows):
            state = str(row["state"] or "").strip().lower()
            if state == "ok":
                ok += 1
            elif state == "skip":
                skip += 1
            else:
                fail += 1
            try:
                latencies.append(max(0, int(row["latency_ms"] or 0)))
            except Exception:
                pass
            if idx == 0:
                if state == "fail":
                    streak = 1
                elif state == "ok":
                    streak = 0
            elif streak > 0:
                if state == "fail":
                    streak += 1
                else:
                    break
        avg_latency = int(round(sum(latencies) / len(latencies))) if latencies else 0
        latest_state = str(rows[0]["state"] or "n/a") if rows else "n/a"
        return {
            "provider": safe_provider,
            "window": safe_window,
            "total": len(rows),
            "ok": ok,
            "fail": fail,
            "skip": skip,
            "failure_streak": streak,
            "avg_latency_ms": avg_latency,
            "latest_state": latest_state,
        }

    def _ensure_default_profiles(self) -> None:
        now = _now_ts()
        defaults = [
            {
                "name": "Google-fast",
                "is_builtin": 1,
                "settings": {
                    "provider": "google",
                    "batch_max_segs": "10",
                    "batch_max_chars": "10000",
                    "sleep": "2",
                    "timeout": "300",
                    "attempts": "3",
                    "backoff": "5,15,30",
                    "temperature": "0.1",
                    "num_ctx": "8192",
                    "num_predict": "2048",
                    "tags": "p,li,h1,h2,h3,h4,h5,h6,blockquote,dd,dt,figcaption,caption",
                    "use_cache": True,
                    "use_glossary": True,
                    "checkpoint": "0",
                    "debug_dir": "debug",
                    "ollama_host": "http://127.0.0.1:11434",
                },
            },
            {
                "name": "Ollama-quality",
                "is_builtin": 1,
                "settings": {
                    "provider": "ollama",
                    "batch_max_segs": "6",
                    "batch_max_chars": "12000",
                    "sleep": "0",
                    "timeout": "300",
                    "attempts": "3",
                    "backoff": "5,15,30",
                    "temperature": "0.05",
                    "num_ctx": "8192",
                    "num_predict": "2048",
                    "tags": "p,li,h1,h2,h3,h4,h5,h6,blockquote,dd,dt,figcaption,caption",
                    "use_cache": True,
                    "use_glossary": True,
                    "checkpoint": "0",
                    "debug_dir": "debug",
                    "ollama_host": "http://127.0.0.1:11434",
                },
            },
        ]
        for d in defaults:
            cur = self.conn.execute("SELECT id FROM profiles WHERE name = ?", (d["name"],))
            if cur.fetchone():
                continue
            self.conn.execute(
                """
                INSERT INTO profiles(name, is_builtin, settings_json, created_at, updated_at)
                VALUES(?, ?, ?, ?, ?)
                """,
                (d["name"], d["is_builtin"], json.dumps(d["settings"], ensure_ascii=False), now, now),
            )
        self.conn.commit()

    def _meta_get(self, key: str) -> Optional[str]:
        row = self.conn.execute("SELECT value FROM meta WHERE key = ?", (key,)).fetchone()
        return str(row["value"]) if row else None

    def _meta_set(self, key: str, value: str) -> None:
        self.conn.execute(
            "INSERT INTO meta(key, value) VALUES(?, ?) ON CONFLICT(key) DO UPDATE SET value = excluded.value",
            (key, value),
        )

    def get_setting(self, key: str, default: Any = None) -> Any:
        row = self.conn.execute("SELECT value_json FROM app_settings WHERE key = ?", (key,)).fetchone()
        if not row:
            return default
        try:
            return json.loads(str(row["value_json"]))
        except Exception as e:
            LOG.warning("Failed to decode app setting '%s': %s", key, e)
            return default

    def set_setting(self, key: str, value: Any) -> None:
        self.conn.execute(
            """
            INSERT INTO app_settings(key, value_json) VALUES(?, ?)
            ON CONFLICT(key) DO UPDATE SET value_json = excluded.value_json
            """,
            (key, json.dumps(value, ensure_ascii=False)),
        )
        self.conn.commit()

    def list_profiles(self) -> List[sqlite3.Row]:
        return list(self.conn.execute("SELECT * FROM profiles ORDER BY is_builtin DESC, name"))

    def get_profile(self, profile_id: int) -> Optional[sqlite3.Row]:
        return self.conn.execute("SELECT * FROM profiles WHERE id = ?", (profile_id,)).fetchone()

    def create_profile(self, name: str, settings: Dict[str, Any], is_builtin: int = 0) -> int:
        now = _now_ts()
        cur = self.conn.execute(
            """
            INSERT INTO profiles(name, is_builtin, settings_json, created_at, updated_at)
            VALUES(?, ?, ?, ?, ?)
            """,
            (name, int(is_builtin), json.dumps(settings, ensure_ascii=False), now, now),
        )
        self.conn.commit()
        return int(cur.lastrowid)

    def update_profile(self, profile_id: int, *, name: Optional[str], settings: Dict[str, Any]) -> None:
        now = _now_ts()
        if name is None:
            self.conn.execute(
                "UPDATE profiles SET settings_json = ?, updated_at = ? WHERE id = ?",
                (json.dumps(settings, ensure_ascii=False), now, profile_id),
            )
        else:
            self.conn.execute(
                "UPDATE profiles SET name = ?, settings_json = ?, updated_at = ? WHERE id = ?",
                (name, json.dumps(settings, ensure_ascii=False), now, profile_id),
            )
        self.conn.commit()

    def delete_profile(self, profile_id: int) -> None:
        self.conn.execute("DELETE FROM profiles WHERE id = ? AND is_builtin = 0", (profile_id,))
        self.conn.commit()

    def _series_slug_exists(self, slug: str) -> bool:
        row = self.conn.execute("SELECT 1 FROM series WHERE slug = ?", (slug,)).fetchone()
        return row is not None

    def _series_slug_exists_other(self, slug: str, series_id: int) -> bool:
        row = self.conn.execute("SELECT 1 FROM series WHERE slug = ? AND id <> ?", (slug, int(series_id))).fetchone()
        return row is not None

    def _next_series_slug(self, name: str) -> str:
        base = _slugify_name(name)
        slug = base
        i = 2
        while self._series_slug_exists(slug):
            slug = f"{base}-{i}"
            i += 1
        return slug

    def list_series(self) -> List[sqlite3.Row]:
        return list(self.conn.execute("SELECT * FROM series ORDER BY name COLLATE NOCASE"))

    def get_series(self, series_id: int) -> Optional[sqlite3.Row]:
        return self.conn.execute("SELECT * FROM series WHERE id = ?", (series_id,)).fetchone()

    def get_series_by_slug(self, slug: str) -> Optional[sqlite3.Row]:
        return self.conn.execute("SELECT * FROM series WHERE slug = ?", (slug,)).fetchone()

    def create_series(self, name: str, *, source: str = "manual", notes: str = "") -> int:
        clean_name = str(name or "").strip()
        if not clean_name:
            raise ValueError("Series name is required")
        now = _now_ts()
        slug = self._next_series_slug(clean_name)
        cur = self.conn.execute(
            """
            INSERT INTO series(slug, name, source, notes, created_at, updated_at)
            VALUES(?, ?, ?, ?, ?, ?)
            """,
            (slug, clean_name, str(source or "manual"), str(notes or ""), now, now),
        )
        self.conn.commit()
        return int(cur.lastrowid)

    def ensure_series(self, name: str, *, source: str = "manual", notes: str = "") -> int:
        clean_name = str(name or "").strip()
        if not clean_name:
            raise ValueError("Series name is required")
        row = self.conn.execute("SELECT id FROM series WHERE LOWER(name) = LOWER(?)", (clean_name,)).fetchone()
        if row:
            return int(row["id"])
        return self.create_series(clean_name, source=source, notes=notes)

    def count_projects_for_series(self, series_id: int) -> int:
        row = self.conn.execute("SELECT COUNT(*) AS c FROM projects WHERE series_id = ?", (int(series_id),)).fetchone()
        return int(row["c"] or 0) if row else 0

    def list_projects_for_series(self, series_id: int, *, include_deleted: bool = False) -> List[sqlite3.Row]:
        sid = int(series_id)
        where_extra = "" if include_deleted else "AND p.status <> 'deleted'"
        return list(
            self.conn.execute(
                f"""
                SELECT p.*, s.name AS series_name, s.slug AS series_slug
                FROM projects p
                LEFT JOIN series s ON s.id = p.series_id
                WHERE p.series_id = ? {where_extra}
                ORDER BY
                  CASE WHEN p.volume_no IS NULL THEN 1 ELSE 0 END ASC,
                  p.volume_no ASC,
                  p.updated_at DESC,
                  p.id DESC
                """,
                (sid,),
            )
        )

    def update_series(
        self,
        series_id: int,
        *,
        name: Optional[str] = None,
        notes: Optional[str] = None,
        source: Optional[str] = None,
        regenerate_slug: bool = False,
    ) -> None:
        row = self.get_series(int(series_id))
        if row is None:
            raise ValueError("Series not found")

        new_name = str(row["name"] or "").strip()
        if name is not None:
            new_name = str(name or "").strip()
            if not new_name:
                raise ValueError("Series name is required")

        new_notes = str(row["notes"] or "")
        if notes is not None:
            new_notes = str(notes or "")

        new_source = str(row["source"] or "manual")
        if source is not None and str(source).strip():
            new_source = str(source).strip()

        new_slug = str(row["slug"] or "")
        if regenerate_slug and new_name and new_name.lower() != str(row["name"] or "").strip().lower():
            base = _slugify_name(new_name)
            candidate = base
            i = 2
            while self._series_slug_exists_other(candidate, int(series_id)):
                candidate = f"{base}-{i}"
                i += 1
            new_slug = candidate

        now = _now_ts()
        self.conn.execute(
            """
            UPDATE series
            SET slug = ?, name = ?, source = ?, notes = ?, updated_at = ?
            WHERE id = ?
            """,
            (new_slug, new_name, new_source, new_notes, now, int(series_id)),
        )
        self.conn.commit()

    def delete_series(self, series_id: int) -> int:
        sid = int(series_id)
        self.conn.execute("UPDATE projects SET series_id = NULL, volume_no = NULL WHERE series_id = ?", (sid,))
        cur = self.conn.execute("DELETE FROM series WHERE id = ?", (sid,))
        self.conn.commit()
        return int(cur.rowcount or 0)

    def list_projects(self) -> List[sqlite3.Row]:
        return list(
            self.conn.execute(
                """
                SELECT p.*, s.name AS series_name, s.slug AS series_slug
                FROM projects p
                LEFT JOIN series s ON s.id = p.series_id
                ORDER BY p.updated_at DESC, p.id DESC
                """
            )
        )

    @staticmethod
    def _stage_record(run: Optional[sqlite3.Row]) -> Dict[str, Any]:
        if run is None:
            return {
                "status": "none",
                "done": 0,
                "total": 0,
                "message": "",
                "started_at": 0,
                "finished_at": 0,
                "updated_at": 0,
                "is_complete": False,
            }
        done = max(0, int(run["global_done"] or 0))
        total = max(0, int(run["global_total"] or 0))
        status = str(run["status"] or "none").strip().lower() or "none"
        started_at = int(run["started_at"] or 0)
        finished_at = int(run["finished_at"] or 0)
        updated_at = finished_at or started_at
        is_complete = status == "ok" and (total == 0 or done >= total)
        return {
            "status": status,
            "done": done,
            "total": total,
            "message": str(run["message"] or ""),
            "started_at": started_at,
            "finished_at": finished_at,
            "updated_at": int(updated_at),
            "is_complete": bool(is_complete),
        }

    @staticmethod
    def _next_action(project_status: str, active_step: str, translate: Dict[str, Any], edit: Dict[str, Any]) -> str:
        p_status = str(project_status or "idle").strip().lower() or "idle"
        step = str(active_step or "translate").strip().lower() or "translate"
        if p_status == "running":
            return f"running:{step}"
        if p_status == "pending":
            return f"pending:{step}"
        if bool(edit.get("is_complete")):
            return "done"
        if not bool(translate.get("is_complete")):
            return "translate_retry" if str(translate.get("status", "")) == "error" else "translate"
        return "edit_retry" if str(edit.get("status", "")) == "error" else "edit"

    def list_projects_with_stage_summary(self) -> List[Dict[str, Any]]:
        projects = [dict(r) for r in self.list_projects()]
        if not projects:
            return []
        project_ids = [int(p["id"]) for p in projects]
        placeholders = ",".join(["?"] * len(project_ids))
        rows = list(
            self.conn.execute(
                f"""
                SELECT project_id, step, status, global_done, global_total, message, started_at, finished_at, id
                FROM runs
                WHERE project_id IN ({placeholders}) AND step IN ('translate', 'edit')
                ORDER BY project_id ASC, step ASC, COALESCE(finished_at, started_at) DESC, id DESC
                """,
                project_ids,
            )
        )
        latest: Dict[Tuple[int, str], sqlite3.Row] = {}
        for row in rows:
            key = (int(row["project_id"]), str(row["step"]))
            if key not in latest:
                latest[key] = row
        out: List[Dict[str, Any]] = []
        for project in projects:
            pid = int(project["id"])
            input_epub = str(project.get("input_epub") or "").strip()
            book = Path(input_epub).name if input_epub else "-"
            tr = self._stage_record(latest.get((pid, "translate")))
            ed = self._stage_record(latest.get((pid, "edit")))
            next_action = self._next_action(str(project.get("status") or "idle"), str(project.get("active_step") or "translate"), tr, ed)
            item = dict(project)
            item["book"] = book
            item["series"] = str(project.get("series_name") or "")
            item["translate"] = tr
            item["edit"] = ed
            item["next_action"] = next_action
            out.append(item)
        return out

    def get_project_with_stage_summary(self, project_id: int) -> Optional[Dict[str, Any]]:
        pid = int(project_id)
        for row in self.list_projects_with_stage_summary():
            if int(row["id"]) == pid:
                return row
        return None

    def list_projects_by_status(self, statuses: List[str]) -> List[sqlite3.Row]:
        if not statuses:
            return []
        placeholders = ",".join(["?"] * len(statuses))
        return list(
            self.conn.execute(
                f"""
                SELECT p.*, s.name AS series_name, s.slug AS series_slug
                FROM projects p
                LEFT JOIN series s ON s.id = p.series_id
                WHERE p.status IN ({placeholders})
                ORDER BY p.updated_at DESC, p.id DESC
                """,
                statuses,
            )
        )

    def get_project(self, project_id: int) -> Optional[sqlite3.Row]:
        return self.conn.execute(
            """
            SELECT p.*, s.name AS series_name, s.slug AS series_slug
            FROM projects p
            LEFT JOIN series s ON s.id = p.series_id
            WHERE p.id = ?
            """,
            (project_id,),
        ).fetchone()

    def create_project(self, name: str, values: Optional[Dict[str, Any]] = None) -> int:
        values = values or {}
        now = _now_ts()
        cur = self.conn.execute(
            """
            INSERT INTO projects(
              name, series_id, volume_no, input_epub, output_translate_epub, output_edit_epub,
              prompt_translate, prompt_edit, glossary_path, cache_translate_path, cache_edit_path,
              profile_translate_id, profile_edit_id, source_lang, target_lang, active_step, status, notes, created_at, updated_at
            ) VALUES(?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                name,
                values.get("series_id"),
                values.get("volume_no"),
                str(values.get("input_epub", "")),
                str(values.get("output_translate_epub", "")),
                str(values.get("output_edit_epub", "")),
                str(values.get("prompt_translate", "")),
                str(values.get("prompt_edit", "")),
                str(values.get("glossary_path", "")),
                str(values.get("cache_translate_path", "")),
                str(values.get("cache_edit_path", "")),
                values.get("profile_translate_id"),
                values.get("profile_edit_id"),
                str(values.get("source_lang", "en")),
                str(values.get("target_lang", "pl")),
                str(values.get("active_step", "translate")),
                str(values.get("status", "idle")),
                str(values.get("notes", "")),
                now,
                now,
            ),
        )
        self.conn.commit()
        return int(cur.lastrowid)

    def update_project(self, project_id: int, values: Dict[str, Any]) -> None:
        if not values:
            return
        vals = dict(values)
        vals["updated_at"] = _now_ts()
        keys = sorted(vals.keys())
        set_clause = ", ".join([f"{k} = ?" for k in keys])
        args = [vals[k] for k in keys]
        args.append(project_id)
        self.conn.execute(f"UPDATE projects SET {set_clause} WHERE id = ?", args)
        self.conn.commit()

    def delete_project(self, project_id: int, hard: bool = False) -> None:
        if hard:
            self.conn.execute("DELETE FROM tm_segments WHERE project_id = ?", (project_id,))
            self.conn.execute("DELETE FROM projects WHERE id = ?", (project_id,))
        else:
            self.conn.execute(
                "UPDATE projects SET status = 'deleted', updated_at = ? WHERE id = ?",
                (_now_ts(), project_id),
            )
        self.conn.commit()

    def mark_project_pending(self, project_id: int, step: str) -> None:
        self.conn.execute(
            "UPDATE projects SET status = 'pending', active_step = ?, updated_at = ? WHERE id = ?",
            (step, _now_ts(), project_id),
        )
        self.conn.commit()

    def get_next_pending_project(self) -> Optional[sqlite3.Row]:
        return self.conn.execute(
            "SELECT * FROM projects WHERE status = 'pending' ORDER BY updated_at ASC, id ASC LIMIT 1"
        ).fetchone()

    def start_run(self, project_id: int, step: str, command_text: str) -> int:
        now = _now_ts()
        cur = self.conn.execute(
            """
            INSERT INTO runs(project_id, step, status, command_text, started_at)
            VALUES(?, ?, 'running', ?, ?)
            """,
            (project_id, step, command_text, now),
        )
        self.conn.execute(
            "UPDATE projects SET status = 'running', active_step = ?, updated_at = ? WHERE id = ?",
            (step, now, project_id),
        )
        self.conn.commit()
        return int(cur.lastrowid)

    def finish_run(
        self,
        run_id: int,
        *,
        status: str,
        message: str = "",
        global_done: int = 0,
        global_total: int = 0,
    ) -> None:
        now = _now_ts()
        run = self.conn.execute("SELECT project_id FROM runs WHERE id = ?", (run_id,)).fetchone()
        if not run:
            return
        project_id = int(run["project_id"])
        self.conn.execute(
            """
            UPDATE runs
            SET status = ?, message = ?, global_done = ?, global_total = ?, finished_at = ?
            WHERE id = ?
            """,
            (status, message, int(global_done), int(global_total), now, run_id),
        )
        if status == "ok":
            cur_status = self.conn.execute("SELECT status FROM projects WHERE id = ?", (project_id,)).fetchone()
            next_status = "pending" if cur_status and str(cur_status["status"]) == "pending" else "idle"
        else:
            next_status = "error"
        self.conn.execute(
            "UPDATE projects SET status = ?, updated_at = ? WHERE id = ?",
            (next_status, now, project_id),
        )
        self.conn.commit()

    def recent_runs(self, project_id: int, limit: int = 20) -> List[sqlite3.Row]:
        return list(
            self.conn.execute(
                "SELECT * FROM runs WHERE project_id = ? ORDER BY started_at DESC LIMIT ?",
                (project_id, int(limit)),
            )
        )

    def list_tm_segments(self, project_id: Optional[int] = None, limit: int = 5000) -> List[sqlite3.Row]:
        if project_id is None:
            return list(
                self.conn.execute(
                    "SELECT * FROM tm_segments ORDER BY created_at DESC LIMIT ?",
                    (int(limit),),
                )
            )
        return list(
            self.conn.execute(
                "SELECT * FROM tm_segments WHERE project_id = ? ORDER BY created_at DESC LIMIT ?",
                (project_id, int(limit)),
            )
        )

    def export_project(self, project_id: int) -> Optional[Dict[str, Any]]:
        row = self.get_project(project_id)
        if row is None:
            return None
        project = dict(row)
        runs = [dict(r) for r in self.recent_runs(project_id, limit=200)]
        tm = [
            dict(r)
            for r in self.conn.execute(
                "SELECT * FROM tm_segments WHERE project_id = ? ORDER BY created_at DESC LIMIT 5000",
                (project_id,),
            )
        ]
        qa = [
            dict(r)
            for r in self.conn.execute(
                "SELECT * FROM qa_findings WHERE project_id = ? ORDER BY updated_at DESC LIMIT 10000",
                (project_id,),
            )
        ]
        return {"project": project, "runs": runs, "tm_segments": tm, "qa_findings": qa}

    def import_project(self, payload: Dict[str, Any]) -> int:
        project = payload.get("project") if isinstance(payload, dict) else None
        if not isinstance(project, dict):
            raise ValueError("NieprawidĹ‚owy payload projektu.")
        base_name = str(project.get("name", "Imported project")).strip() or "Imported project"
        name = base_name
        i = 2
        while self.conn.execute("SELECT 1 FROM projects WHERE name = ?", (name,)).fetchone():
            name = f"{base_name} ({i})"
            i += 1

        series_id: Optional[int] = None
        series_name = str(project.get("series_name", "")).strip()
        series_slug = str(project.get("series_slug", "")).strip()
        if series_name:
            try:
                series_id = self.ensure_series(series_name, source="import")
            except Exception:
                series_id = None
        raw_series_id = project.get("series_id")
        if series_id is None and raw_series_id is not None:
            try:
                existing_series = self.get_series(int(raw_series_id))
                if existing_series is not None:
                    series_id = int(existing_series["id"])
                elif series_name:
                    series_id = self.ensure_series(series_name, source="import")
                elif series_slug:
                    row = self.get_series_by_slug(series_slug)
                    series_id = int(row["id"]) if row else None
            except Exception:
                series_id = None

        vals = {
            "series_id": series_id,
            "volume_no": project.get("volume_no"),
            "input_epub": str(project.get("input_epub", "")),
            "output_translate_epub": str(project.get("output_translate_epub", "")),
            "output_edit_epub": str(project.get("output_edit_epub", "")),
            "prompt_translate": str(project.get("prompt_translate", "")),
            "prompt_edit": str(project.get("prompt_edit", "")),
            "glossary_path": str(project.get("glossary_path", "")),
            "cache_translate_path": str(project.get("cache_translate_path", "")),
            "cache_edit_path": str(project.get("cache_edit_path", "")),
            "profile_translate_id": project.get("profile_translate_id"),
            "profile_edit_id": project.get("profile_edit_id"),
            "source_lang": str(project.get("source_lang", "en")),
            "target_lang": str(project.get("target_lang", "pl")),
            "active_step": str(project.get("active_step", "translate")),
            "status": "idle",
            "notes": str(project.get("notes", "")),
        }
        project_id = self.create_project(name, vals)

        runs = payload.get("runs")
        if isinstance(runs, list):
            for r in runs:
                if not isinstance(r, dict):
                    continue
                self.conn.execute(
                    """
                    INSERT INTO runs(project_id, step, status, command_text, started_at, finished_at, global_done, global_total, message)
                    VALUES(?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        project_id,
                        str(r.get("step", "")),
                        str(r.get("status", "ok")),
                        str(r.get("command_text", "")),
                        int(r.get("started_at", _now_ts())),
                        int(r.get("finished_at")) if r.get("finished_at") else None,
                        int(r.get("global_done", 0)),
                        int(r.get("global_total", 0)),
                        str(r.get("message", "")),
                    ),
                )
        tm = payload.get("tm_segments")
        if isinstance(tm, list):
            for r in tm:
                if not isinstance(r, dict):
                    continue
                self.conn.execute(
                    """
                    INSERT INTO tm_segments(source_text, target_text, source_lang, target_lang, source_hash, project_id, score, created_at)
                    VALUES(?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        str(r.get("source_text", "")),
                        str(r.get("target_text", "")),
                        str(r.get("source_lang", "en")),
                        str(r.get("target_lang", "pl")),
                        str(r.get("source_hash", "")),
                        project_id,
                        float(r.get("score", 1.0)),
                        int(r.get("created_at", _now_ts())),
                    ),
                )
        qa = payload.get("qa_findings")
        if isinstance(qa, list):
            for r in qa:
                if not isinstance(r, dict):
                    continue
                self.conn.execute(
                    """
                    INSERT INTO qa_findings(
                      project_id, step, chapter_path, segment_index, segment_id, severity, rule_code, message,
                      status, assignee, created_at, updated_at
                    ) VALUES(?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        project_id,
                        str(r.get("step", "translate")),
                        str(r.get("chapter_path", "")),
                        int(r.get("segment_index", 0)),
                        str(r.get("segment_id", "") or f"{str(r.get('chapter_path', ''))}#{int(r.get('segment_index', 0))}"),
                        str(r.get("severity", "warn")),
                        str(r.get("rule_code", "GENERIC")),
                        str(r.get("message", "")),
                        str(r.get("status", "open")),
                        str(r.get("assignee", "")),
                        int(r.get("created_at", _now_ts())),
                        int(r.get("updated_at", _now_ts())),
                    ),
                )
        self.conn.commit()
        return project_id

    def tm_add(self, source_text: str, target_text: str, project_id: Optional[int], score: float = 1.0) -> None:
        src = (source_text or "").strip()
        dst = (target_text or "").strip()
        if not src or not dst:
            return
        source_hash = hashlib.sha1(src.lower().encode("utf-8", errors="replace")).hexdigest()
        self.conn.execute(
            """
            INSERT INTO tm_segments(source_text, target_text, source_lang, target_lang, source_hash, project_id, score, created_at)
            VALUES(?, ?, 'en', 'pl', ?, ?, ?, ?)
            """,
            (src, dst, source_hash, project_id, float(score), _now_ts()),
        )
        self.conn.commit()

    def import_legacy_gui_settings(self, json_path: Path) -> Optional[int]:
        if not json_path.exists():
            return None
        if self.get_setting("legacy_imported_v1", False):
            return None

        try:
            raw = json.loads(json_path.read_text(encoding="utf-8"))
        except Exception as e:
            LOG.warning("Failed to import legacy GUI settings from '%s': %s", json_path, e)
            return None
        if not isinstance(raw, dict):
            return None

        profile_name = "Legacy profile"
        try:
            profile_id = self.create_profile(profile_name, raw, is_builtin=0)
        except sqlite3.IntegrityError:
            row = self.conn.execute("SELECT id FROM profiles WHERE name = ?", (profile_name,)).fetchone()
            profile_id = int(row["id"]) if row else None

        input_epub = str(raw.get("input_epub", "")).strip()
        if not input_epub:
            self.set_setting("legacy_imported_v1", True)
            return None

        name = Path(input_epub).stem or "Imported project"
        vals = {
            "input_epub": input_epub,
            "output_translate_epub": str(raw.get("output_epub", "")),
            "output_edit_epub": str(raw.get("output_epub", "")),
            "prompt_translate": str(raw.get("prompt", "")),
            "prompt_edit": str(raw.get("prompt", "")),
            "glossary_path": str(raw.get("glossary", "")),
            "cache_translate_path": str(raw.get("cache", "")),
            "cache_edit_path": str(raw.get("cache", "")),
            "profile_translate_id": profile_id,
            "profile_edit_id": profile_id,
            "source_lang": str(raw.get("source_lang", "en") or "en"),
            "target_lang": str(raw.get("target_lang", "pl") or "pl"),
            "active_step": str(raw.get("mode", "translate")),
            "status": "idle",
            "notes": "Imported from .gui_settings.json",
        }
        try:
            project_id = self.create_project(name, vals)
        except sqlite3.IntegrityError:
            row = self.conn.execute("SELECT id FROM projects WHERE name = ?", (name,)).fetchone()
            project_id = int(row["id"]) if row else None
        self.set_setting("active_project_id", project_id)
        self.set_setting("legacy_imported_v1", True)
        return project_id

