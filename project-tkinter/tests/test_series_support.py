from __future__ import annotations

import sqlite3
import sys
import zipfile
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from project_db import ProjectDB  # noqa: E402
from series_store import SeriesStore, detect_series_hint  # noqa: E402


def _write_epub_with_series(epub_path: Path) -> None:
    container = """<?xml version="1.0" encoding="utf-8"?>
<container version="1.0" xmlns="urn:oasis:names:tc:opendocument:xmlns:container">
  <rootfiles>
    <rootfile full-path="OPS/content.opf" media-type="application/oebps-package+xml"/>
  </rootfiles>
</container>
"""
    opf = """<?xml version="1.0" encoding="utf-8"?>
<package xmlns="http://www.idpf.org/2007/opf" version="3.0">
  <metadata xmlns:dc="http://purl.org/dc/elements/1.1/">
    <dc:title>The Expanse - Tom 1</dc:title>
    <meta name="calibre:series" content="The Expanse"/>
    <meta name="calibre:series_index" content="1"/>
  </metadata>
  <manifest>
    <item id="chap1" href="Text/ch1.xhtml" media-type="application/xhtml+xml"/>
  </manifest>
  <spine>
    <itemref idref="chap1"/>
  </spine>
</package>
"""
    with zipfile.ZipFile(epub_path, "w", compression=zipfile.ZIP_DEFLATED) as zf:
        zf.writestr("META-INF/container.xml", container)
        zf.writestr("OPS/content.opf", opf)
        zf.writestr("OPS/Text/ch1.xhtml", "<html xmlns='http://www.w3.org/1999/xhtml'><body><p>Hello</p></body></html>")


def test_project_db_series_assignment(tmp_path: Path) -> None:
    db_path = tmp_path / "studio.db"
    db = ProjectDB(db_path)
    sid = db.ensure_series("The Expanse", source="manual")
    pid = db.create_project(
        "Leviathan Wakes",
        {
            "series_id": sid,
            "volume_no": 1.0,
            "input_epub": str(tmp_path / "book.epub"),
            "output_translate_epub": str(tmp_path / "book_pl.epub"),
            "output_edit_epub": str(tmp_path / "book_pl_edit.epub"),
        },
    )
    row = db.get_project(pid)
    assert row is not None
    assert int(row["series_id"]) == sid
    assert str(row["series_name"]) == "The Expanse"
    assert float(row["volume_no"]) == 1.0
    db.close()


def test_detect_series_hint_from_epub_metadata(tmp_path: Path) -> None:
    epub_path = tmp_path / "expanse.epub"
    _write_epub_with_series(epub_path)
    hint = detect_series_hint(epub_path)
    assert hint is not None
    assert hint.name == "The Expanse"
    assert hint.volume_no == 1.0
    assert hint.source.startswith("meta:")


def test_series_store_terms_and_export(tmp_path: Path) -> None:
    store = SeriesStore(tmp_path / "series")
    store.ensure_series_db("the-expanse", display_name="The Expanse")
    term_id, created = store.add_or_update_term(
        "the-expanse",
        source_term="Ring Gate",
        target_term="Brama Pierscienia",
        status="proposed",
        confidence=0.8,
        origin="tm-quoted",
        project_id=123,
    )
    assert created is True
    assert term_id > 0

    rows = store.list_terms("the-expanse", status="proposed")
    assert len(rows) == 1

    store.set_term_status("the-expanse", term_id, "approved")
    approved = store.list_approved_terms("the-expanse")
    assert ("Ring Gate", "Brama Pierscienia") in approved

    out = store.export_approved_glossary("the-expanse")
    content = out.read_text(encoding="utf-8")
    assert "Ring Gate => Brama Pierscienia" in content


def test_series_store_learns_from_tm(tmp_path: Path) -> None:
    store = SeriesStore(tmp_path / "series")
    store.ensure_series_db("my-series", display_name="My Series")
    rows = [
        {
            "source_text": 'He crossed the "Ring Gate" and met High Consul Duarte.',
            "target_text": 'Przeszedl przez "Brame Pierscienia" i spotkal Wysokiego Konsula Duarte.',
        }
    ]
    added = store.learn_terms_from_tm("my-series", rows, project_id=77)
    assert added >= 1
    all_rows = store.list_terms("my-series")
    assert len(all_rows) >= 1


def test_project_db_repairs_schema_drift_on_existing_db(tmp_path: Path) -> None:
    db_path = tmp_path / "drift.db"
    raw = sqlite3.connect(str(db_path))
    raw.execute("CREATE TABLE IF NOT EXISTS meta (key TEXT PRIMARY KEY, value TEXT NOT NULL)")
    raw.execute("INSERT OR REPLACE INTO meta(key, value) VALUES('schema_version', '8')")
    raw.execute(
        """
        CREATE TABLE projects (
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
          active_step TEXT NOT NULL DEFAULT 'translate',
          status TEXT NOT NULL DEFAULT 'idle',
          notes TEXT NOT NULL DEFAULT '',
          created_at INTEGER NOT NULL,
          updated_at INTEGER NOT NULL
        )
        """
    )
    raw.commit()
    raw.close()

    db = ProjectDB(db_path)
    cols = {str(r["name"]) for r in db.conn.execute("PRAGMA table_info(projects)").fetchall()}
    assert "series_id" in cols
    assert "volume_no" in cols
    assert "source_lang" in cols
    assert "target_lang" in cols
    db.close()
