from __future__ import annotations

import sqlite3
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from project_db import (  # noqa: E402
    PROVIDER_HEALTH_RETENTION_PER_PROVIDER,
    ProjectDB,
    SCHEMA_META_ALIAS_KEY,
    SCHEMA_META_KEY,
)
from studio_repository import SQLiteStudioRepository  # noqa: E402


def test_schema_version_alias_is_set_for_new_db(tmp_path: Path) -> None:
    db = ProjectDB(tmp_path / "studio.db")
    try:
        raw_schema = db._meta_get(SCHEMA_META_KEY)  # noqa: SLF001
        raw_alias = db._meta_get(SCHEMA_META_ALIAS_KEY)  # noqa: SLF001
        assert raw_schema is not None
        assert raw_alias is not None
        assert str(raw_schema) == str(raw_alias)
    finally:
        db.close()


def test_schema_version_alias_recovers_legacy_alias_only_db(tmp_path: Path) -> None:
    db_path = tmp_path / "legacy_alias.db"
    raw = sqlite3.connect(str(db_path))
    raw.execute("CREATE TABLE IF NOT EXISTS meta (key TEXT PRIMARY KEY, value TEXT NOT NULL)")
    raw.execute(
        "INSERT OR REPLACE INTO meta(key, value) VALUES(?, ?)",
        (SCHEMA_META_ALIAS_KEY, "8"),
    )
    raw.commit()
    raw.close()

    db = ProjectDB(db_path, run_migrations=False)
    try:
        assert db._schema_version() == 8  # noqa: SLF001
        assert str(db._meta_get(SCHEMA_META_KEY)) == "8"  # noqa: SLF001
        assert str(db._meta_get(SCHEMA_META_ALIAS_KEY)) == "8"  # noqa: SLF001
    finally:
        db.close()


def test_sqlite_repository_queue_and_qa_counts(tmp_path: Path) -> None:
    db = ProjectDB(tmp_path / "studio.db")
    repo = SQLiteStudioRepository(db)
    try:
        sid = db.ensure_series("Repo Saga", source="manual")
        pid = db.create_project(
            "Repo Book 1",
            {
                "series_id": sid,
                "volume_no": 1.0,
                "input_epub": str(tmp_path / "book.epub"),
                "output_translate_epub": str(tmp_path / "book_pl.epub"),
                "output_edit_epub": str(tmp_path / "book_pl_edit.epub"),
            },
        )

        series_projects = repo.list_projects_for_series(sid)
        assert len(series_projects) == 1
        assert int(series_projects[0]["id"]) == pid

        repo.mark_project_pending(pid, "translate")
        nxt = repo.get_next_pending_project()
        assert nxt is not None
        assert int(nxt["id"]) == pid

        assert repo.count_open_qa_findings(pid) == 0
        inserted = db.replace_qa_findings(
            project_id=pid,
            step="translate",
            findings=[
                {
                    "chapter_path": "OPS/ch1.xhtml",
                    "segment_index": 1,
                    "segment_id": "OPS/ch1.xhtml#1",
                    "severity": "error",
                    "rule_code": "TEST",
                    "message": "example",
                }
            ],
        )
        assert inserted == 1
        assert repo.count_open_qa_findings(pid) == 1
    finally:
        db.close()


def test_provider_health_checks_record_and_summary(tmp_path: Path) -> None:
    db = ProjectDB(tmp_path / "studio.db")
    try:
        inserted = db.record_provider_health_checks(
            [
                {"provider": "ollama", "state": "fail", "latency_ms": 42, "model_count": 0, "detail": "timeout"},
                {"provider": "ollama", "state": "fail", "latency_ms": 35, "model_count": 0, "detail": "timeout"},
                {"provider": "ollama", "state": "ok", "latency_ms": 18, "model_count": 12, "detail": "ok"},
                {"provider": "google", "state": "skip", "latency_ms": 0, "model_count": 0, "detail": "missing key"},
            ]
        )
        assert inserted == 4

        rows = db.list_provider_health_checks("ollama", limit=10)
        assert len(rows) == 3
        summary = db.provider_health_summary("ollama", window=10)
        assert summary["provider"] == "ollama"
        assert summary["total"] == 3
        assert summary["ok"] == 1
        assert summary["fail"] == 2
        assert summary["skip"] == 0
        assert summary["latest_state"] == "ok"
        assert summary["failure_streak"] == 0
    finally:
        db.close()


def test_provider_health_retention_keeps_last_rows_per_provider(tmp_path: Path) -> None:
    db = ProjectDB(tmp_path / "studio.db")
    try:
        payload = [
            {
                "provider": "ollama",
                "state": "ok" if idx % 2 else "fail",
                "latency_ms": idx,
                "model_count": 1,
                "detail": "",
            }
            for idx in range(PROVIDER_HEALTH_RETENTION_PER_PROVIDER + 35)
        ]
        inserted = db.record_provider_health_checks(payload)
        assert inserted == len(payload)

        rows = db.list_provider_health_checks("ollama", limit=PROVIDER_HEALTH_RETENTION_PER_PROVIDER + 100)
        assert len(rows) == PROVIDER_HEALTH_RETENTION_PER_PROVIDER
        newest_latency = int(rows[0]["latency_ms"])
        oldest_latency = int(rows[-1]["latency_ms"])
        assert newest_latency == len(payload) - 1
        assert oldest_latency == 35
    finally:
        db.close()
