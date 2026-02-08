#!/usr/bin/env python3
# -*- coding: utf-8 -*-

from __future__ import annotations

import json
import re
import sqlite3
import time
import unicodedata
import zipfile
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional, Sequence, Tuple

from lxml import etree

SERIES_DB_FILE = "series.db"
APPROVED_GLOSSARY_FILE = "approved_glossary.txt"
GENERATED_DIR = "generated"


def _now_ts() -> int:
    return int(time.time())


def slugify(value: str) -> str:
    text = unicodedata.normalize("NFKD", str(value or "")).encode("ascii", "ignore").decode("ascii")
    text = text.lower().strip()
    text = re.sub(r"[^a-z0-9]+", "-", text)
    text = text.strip("-")
    return text or "series"


@dataclass(frozen=True)
class SeriesHint:
    name: str
    volume_no: Optional[float]
    source: str
    confidence: float


def _parse_float(value: str) -> Optional[float]:
    try:
        return float(str(value).replace(",", ".").strip())
    except Exception:
        return None


def _extract_title_fallback(title: str) -> Optional[SeriesHint]:
    raw = str(title or "").strip()
    if not raw:
        return None
    m = re.match(
        r"^(.*?)(?:\s*[-:,(]\s*(?:tom|t\.|vol\.?|volume|book)\s*([0-9]+(?:[.,][0-9]+)?).*)$",
        raw,
        flags=re.IGNORECASE,
    )
    if not m:
        return None
    series_name = m.group(1).strip(" -:,()")
    if not series_name:
        return None
    return SeriesHint(
        name=series_name,
        volume_no=_parse_float(m.group(2)),
        source="title-pattern",
        confidence=0.45,
    )


def detect_series_hint(epub_path: Path) -> Optional[SeriesHint]:
    if not epub_path.exists():
        return None
    try:
        with zipfile.ZipFile(epub_path, "r") as zf:
            container = etree.fromstring(zf.read("META-INF/container.xml"))
            rootfile = container.find(".//{*}rootfile")
            if rootfile is None:
                return None
            opf_path = str(rootfile.get("full-path") or "").replace("\\", "/")
            if not opf_path:
                return None
            opf_root = etree.fromstring(zf.read(opf_path))
    except Exception:
        return None

    metadata = opf_root.find(".//{*}metadata")
    if metadata is None:
        return None

    title = ""
    title_el = metadata.find(".//{*}title")
    if title_el is not None:
        title = (title_el.text or "").strip()

    best_name = ""
    best_source = ""
    best_conf = 0.0
    volume_no: Optional[float] = None

    for meta in metadata.findall(".//{*}meta"):
        name_attr = (meta.get("name") or "").strip().lower()
        prop_attr = (meta.get("property") or "").strip().lower()
        content_attr = (meta.get("content") or "").strip()
        text_value = (meta.text or "").strip()
        value = content_attr or text_value
        if not value:
            continue
        if name_attr in {"calibre:series", "series"}:
            best_name = value
            best_source = f"meta:{name_attr}"
            best_conf = 0.95
        elif prop_attr == "belongs-to-collection" and best_conf < 0.9:
            best_name = value
            best_source = "meta:belongs-to-collection"
            best_conf = 0.85
        elif name_attr in {"calibre:series_index", "series_index"} and volume_no is None:
            volume_no = _parse_float(value)
        elif prop_attr in {"group-position", "series-index"} and volume_no is None:
            volume_no = _parse_float(value)

    if best_name:
        return SeriesHint(name=best_name, volume_no=volume_no, source=best_source, confidence=best_conf)

    fallback = _extract_title_fallback(title)
    if fallback is not None:
        return fallback
    return None


class SeriesStore:
    def __init__(self, root_dir: Path):
        self.root_dir = Path(root_dir)
        self.root_dir.mkdir(parents=True, exist_ok=True)

    def series_dir(self, slug: str) -> Path:
        return self.root_dir / slugify(slug)

    def series_db_path(self, slug: str) -> Path:
        return self.series_dir(slug) / SERIES_DB_FILE

    def _connect(self, slug: str) -> sqlite3.Connection:
        series_dir = self.series_dir(slug)
        series_dir.mkdir(parents=True, exist_ok=True)
        conn = sqlite3.connect(str(series_dir / SERIES_DB_FILE), timeout=30.0)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA journal_mode = WAL")
        conn.execute("PRAGMA busy_timeout = 5000")
        self._init_schema(conn)
        return conn

    def _init_schema(self, conn: sqlite3.Connection) -> None:
        cur = conn.cursor()
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
            CREATE TABLE IF NOT EXISTS terms (
              id INTEGER PRIMARY KEY AUTOINCREMENT,
              source_term TEXT NOT NULL,
              target_term TEXT NOT NULL,
              status TEXT NOT NULL DEFAULT 'proposed',
              confidence REAL NOT NULL DEFAULT 0.0,
              origin TEXT NOT NULL DEFAULT '',
              project_id INTEGER,
              source_hash TEXT NOT NULL DEFAULT '',
              source_example TEXT NOT NULL DEFAULT '',
              target_example TEXT NOT NULL DEFAULT '',
              notes TEXT NOT NULL DEFAULT '',
              created_at INTEGER NOT NULL,
              updated_at INTEGER NOT NULL,
              approved_at INTEGER
            )
            """
        )
        cur.execute("CREATE UNIQUE INDEX IF NOT EXISTS idx_terms_pair ON terms(source_term, target_term)")
        cur.execute("CREATE INDEX IF NOT EXISTS idx_terms_status ON terms(status, updated_at DESC)")
        cur.execute("CREATE INDEX IF NOT EXISTS idx_terms_source ON terms(source_term)")
        cur.execute(
            """
            CREATE TABLE IF NOT EXISTS decisions (
              id INTEGER PRIMARY KEY AUTOINCREMENT,
              segment_hash TEXT NOT NULL UNIQUE,
              project_id INTEGER,
              chapter_path TEXT NOT NULL DEFAULT '',
              segment_id TEXT NOT NULL DEFAULT '',
              source_excerpt TEXT NOT NULL DEFAULT '',
              approved_translation TEXT NOT NULL DEFAULT '',
              created_at INTEGER NOT NULL,
              updated_at INTEGER NOT NULL
            )
            """
        )
        cur.execute("CREATE INDEX IF NOT EXISTS idx_decisions_project ON decisions(project_id, updated_at DESC)")
        cur.execute(
            """
            CREATE TABLE IF NOT EXISTS lore_entries (
              id INTEGER PRIMARY KEY AUTOINCREMENT,
              entry_key TEXT NOT NULL,
              title TEXT NOT NULL DEFAULT '',
              content TEXT NOT NULL DEFAULT '',
              tags_json TEXT NOT NULL DEFAULT '[]',
              status TEXT NOT NULL DEFAULT 'draft',
              created_at INTEGER NOT NULL,
              updated_at INTEGER NOT NULL
            )
            """
        )
        cur.execute("CREATE UNIQUE INDEX IF NOT EXISTS idx_lore_entry_key ON lore_entries(entry_key)")
        cur.execute(
            """
            CREATE TABLE IF NOT EXISTS style_rules (
              id INTEGER PRIMARY KEY AUTOINCREMENT,
              rule_key TEXT NOT NULL UNIQUE,
              value_json TEXT NOT NULL DEFAULT '{}',
              created_at INTEGER NOT NULL,
              updated_at INTEGER NOT NULL
            )
            """
        )
        conn.commit()

    def ensure_series_db(self, slug: str, *, display_name: str = "") -> Path:
        clean_slug = slugify(slug)
        with self._connect(clean_slug) as conn:
            now = _now_ts()
            conn.execute(
                "INSERT INTO meta(key, value) VALUES(?, ?) ON CONFLICT(key) DO UPDATE SET value = excluded.value",
                ("series_slug", clean_slug),
            )
            if display_name.strip():
                conn.execute(
                    "INSERT INTO meta(key, value) VALUES(?, ?) ON CONFLICT(key) DO UPDATE SET value = excluded.value",
                    ("series_name", display_name.strip()),
                )
            conn.execute(
                "INSERT INTO meta(key, value) VALUES(?, ?) ON CONFLICT(key) DO UPDATE SET value = excluded.value",
                ("updated_at", str(now)),
            )
            conn.commit()
        return self.series_db_path(clean_slug)

    def add_or_update_term(
        self,
        slug: str,
        *,
        source_term: str,
        target_term: str,
        status: str = "proposed",
        confidence: float = 0.0,
        origin: str = "",
        project_id: Optional[int] = None,
        source_example: str = "",
        target_example: str = "",
        notes: str = "",
    ) -> Tuple[int, bool]:
        src = str(source_term or "").strip()
        dst = str(target_term or "").strip()
        if not src or not dst:
            raise ValueError("source_term and target_term are required")
        now = _now_ts()
        with self._connect(slug) as conn:
            row = conn.execute(
                "SELECT id, status, confidence FROM terms WHERE source_term = ? AND target_term = ?",
                (src, dst),
            ).fetchone()
            if row is None:
                approved_at = now if status == "approved" else None
                cur = conn.execute(
                    """
                    INSERT INTO terms(
                      source_term, target_term, status, confidence, origin, project_id, source_hash,
                      source_example, target_example, notes, created_at, updated_at, approved_at
                    ) VALUES(?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        src,
                        dst,
                        status,
                        float(confidence),
                        str(origin or ""),
                        project_id,
                        "",
                        str(source_example or ""),
                        str(target_example or ""),
                        str(notes or ""),
                        now,
                        now,
                        approved_at,
                    ),
                )
                conn.commit()
                return int(cur.lastrowid), True

            current_status = str(row["status"] or "proposed")
            final_status = current_status
            if status == "approved":
                final_status = "approved"
            elif current_status not in {"approved", "rejected"}:
                final_status = status
            approved_at = now if final_status == "approved" else None
            final_conf = max(float(row["confidence"] or 0.0), float(confidence))
            conn.execute(
                """
                UPDATE terms
                SET status = ?, confidence = ?, origin = CASE WHEN ? <> '' THEN ? ELSE origin END,
                    project_id = COALESCE(?, project_id),
                    source_example = CASE WHEN ? <> '' THEN ? ELSE source_example END,
                    target_example = CASE WHEN ? <> '' THEN ? ELSE target_example END,
                    notes = CASE WHEN ? <> '' THEN ? ELSE notes END,
                    updated_at = ?, approved_at = COALESCE(?, approved_at)
                WHERE id = ?
                """,
                (
                    final_status,
                    final_conf,
                    str(origin or ""),
                    str(origin or ""),
                    project_id,
                    str(source_example or ""),
                    str(source_example or ""),
                    str(target_example or ""),
                    str(target_example or ""),
                    str(notes or ""),
                    str(notes or ""),
                    now,
                    approved_at,
                    int(row["id"]),
                ),
            )
            conn.commit()
            return int(row["id"]), False

    def set_term_status(self, slug: str, term_id: int, status: str, *, notes: str = "") -> None:
        now = _now_ts()
        approved_at = now if status == "approved" else None
        with self._connect(slug) as conn:
            conn.execute(
                """
                UPDATE terms
                SET status = ?, notes = CASE WHEN ? <> '' THEN ? ELSE notes END,
                    updated_at = ?, approved_at = COALESCE(?, approved_at)
                WHERE id = ?
                """,
                (status, str(notes or ""), str(notes or ""), now, approved_at, int(term_id)),
            )
            conn.commit()

    def list_terms(self, slug: str, *, status: Optional[str] = None, limit: int = 300) -> List[sqlite3.Row]:
        with self._connect(slug) as conn:
            if status is None:
                return list(conn.execute("SELECT * FROM terms ORDER BY updated_at DESC LIMIT ?", (int(limit),)))
            return list(
                conn.execute(
                    "SELECT * FROM terms WHERE status = ? ORDER BY updated_at DESC LIMIT ?",
                    (status, int(limit)),
                )
            )

    def list_approved_terms(self, slug: str, limit: int = 5000) -> List[Tuple[str, str]]:
        with self._connect(slug) as conn:
            rows = conn.execute(
                """
                SELECT source_term, target_term
                FROM terms
                WHERE status = 'approved'
                ORDER BY source_term COLLATE NOCASE, target_term COLLATE NOCASE
                LIMIT ?
                """,
                (int(limit),),
            ).fetchall()
            return [(str(r["source_term"]), str(r["target_term"])) for r in rows]

    def add_decision(
        self,
        slug: str,
        *,
        segment_hash: str,
        approved_translation: str,
        source_excerpt: str = "",
        project_id: Optional[int] = None,
        chapter_path: str = "",
        segment_id: str = "",
    ) -> None:
        key = str(segment_hash or "").strip()
        if not key:
            return
        now = _now_ts()
        with self._connect(slug) as conn:
            conn.execute(
                """
                INSERT INTO decisions(
                  segment_hash, project_id, chapter_path, segment_id, source_excerpt, approved_translation, created_at, updated_at
                ) VALUES(?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(segment_hash) DO UPDATE SET
                  project_id = COALESCE(excluded.project_id, decisions.project_id),
                  chapter_path = excluded.chapter_path,
                  segment_id = excluded.segment_id,
                  source_excerpt = excluded.source_excerpt,
                  approved_translation = excluded.approved_translation,
                  updated_at = excluded.updated_at
                """,
                (
                    key,
                    project_id,
                    str(chapter_path or ""),
                    str(segment_id or ""),
                    str(source_excerpt or ""),
                    str(approved_translation or ""),
                    now,
                    now,
                ),
            )
            conn.commit()

    def export_approved_glossary(self, slug: str, *, output_path: Optional[Path] = None) -> Path:
        terms = self.list_approved_terms(slug)
        out = output_path or (self.series_dir(slug) / GENERATED_DIR / APPROVED_GLOSSARY_FILE)
        out.parent.mkdir(parents=True, exist_ok=True)
        lines = [f"{src} => {dst}" for src, dst in terms]
        out.write_text("\n".join(lines) + ("\n" if lines else ""), encoding="utf-8")
        return out

    def build_merged_glossary(
        self,
        slug: str,
        *,
        project_glossary: Optional[Path],
        output_path: Optional[Path] = None,
    ) -> Path:
        out = output_path or (self.series_dir(slug) / GENERATED_DIR / "merged_glossary.txt")
        out.parent.mkdir(parents=True, exist_ok=True)
        merged: List[str] = []
        seen: set[str] = set()

        approved_lines = [f"{src} => {dst}" for src, dst in self.list_approved_terms(slug)]
        for line in approved_lines:
            key = line.strip().lower()
            if key and key not in seen:
                seen.add(key)
                merged.append(line)

        if project_glossary is not None and project_glossary.exists():
            for raw in project_glossary.read_text(encoding="utf-8", errors="replace").splitlines():
                line = raw.strip()
                if not line:
                    continue
                key = line.lower()
                if key in seen:
                    continue
                seen.add(key)
                merged.append(line)

        out.write_text("\n".join(merged) + ("\n" if merged else ""), encoding="utf-8")
        return out

    def learn_terms_from_tm(
        self,
        slug: str,
        tm_rows: Sequence[Dict[str, Any]],
        *,
        project_id: Optional[int] = None,
        max_rows: int = 2000,
    ) -> int:
        count = 0
        for row in tm_rows[: max(0, int(max_rows))]:
            src = str(row.get("source_text", "")).strip()
            dst = str(row.get("target_text", "")).strip()
            if not src or not dst:
                continue
            pairs = _extract_term_pairs(src, dst)
            for source_term, target_term, confidence, origin in pairs:
                _, created = self.add_or_update_term(
                    slug,
                    source_term=source_term,
                    target_term=target_term,
                    status="proposed",
                    confidence=confidence,
                    origin=origin,
                    project_id=project_id,
                    source_example=src[:240],
                    target_example=dst[:240],
                )
                if created:
                    count += 1
        return count


_QUOTED_RE = re.compile(r"[\"“”„']([^\"“”„']{2,80})[\"“”„']")
_TITLECASE_RE = re.compile(r"\b[A-ZĄĆĘŁŃÓŚŹŻ][A-Za-z0-9ĄĆĘŁŃÓŚŹŻąćęłńóśźż'’_-]{1,}(?:\s+[A-ZĄĆĘŁŃÓŚŹŻ][A-Za-z0-9ĄĆĘŁŃÓŚŹŻąćęłńóśźż'’_-]{1,}){0,2}\b")


def _looks_term_like(text: str) -> bool:
    val = str(text or "").strip()
    if not val:
        return False
    if len(val) > 80:
        return False
    if re.search(r"[.!?]\s*$", val):
        return False
    words = re.findall(r"[A-Za-zĄĆĘŁŃÓŚŹŻąćęłńóśźż0-9'’_-]+", val)
    return 1 <= len(words) <= 6


def _extract_term_pairs(source_text: str, target_text: str) -> List[Tuple[str, str, float, str]]:
    out: List[Tuple[str, str, float, str]] = []
    seen: set[Tuple[str, str]] = set()

    src_quotes = [s.strip() for s in _QUOTED_RE.findall(source_text)]
    dst_quotes = [s.strip() for s in _QUOTED_RE.findall(target_text)]
    for src, dst in zip(src_quotes, dst_quotes):
        if _looks_term_like(src) and _looks_term_like(dst):
            key = (src.lower(), dst.lower())
            if key not in seen:
                seen.add(key)
                out.append((src, dst, 0.85, "tm-quoted"))

    src_titles = [s.strip() for s in _TITLECASE_RE.findall(source_text)]
    dst_titles = [s.strip() for s in _TITLECASE_RE.findall(target_text)]
    for src, dst in zip(src_titles, dst_titles):
        if _looks_term_like(src) and _looks_term_like(dst):
            key = (src.lower(), dst.lower())
            if key not in seen:
                seen.add(key)
                out.append((src, dst, 0.65, "tm-titlecase"))

    if _looks_term_like(source_text) and _looks_term_like(target_text):
        src = source_text.strip()
        dst = target_text.strip()
        key = (src.lower(), dst.lower())
        if key not in seen:
            out.append((src, dst, 0.55, "tm-short-segment"))
    return out
