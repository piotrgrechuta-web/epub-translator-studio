from __future__ import annotations

import sys
import time
import zipfile
from pathlib import Path

from lxml import etree

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from runtime_core import RunOptions, build_run_command  # noqa: E402
from app_gui_classic import parse_epubcheck_findings  # noqa: E402
from project_db import ProjectDB  # noqa: E402
from text_preserve import set_text_preserving_inline, tokenize_inline_markup, apply_tokenized_inline_markup  # noqa: E402
from translation_engine import (  # noqa: E402
    SegmentLedger,
    seed_segment_ledger_from_epub,
    validate_entity_integrity,
    semantic_similarity_score,
)


def _make_epub(tmp_path: Path) -> Path:
    epub_path = tmp_path / "book.epub"
    opf = """<?xml version="1.0" encoding="utf-8"?>
<package xmlns="http://www.idpf.org/2007/opf" version="3.0">
  <manifest>
    <item id="ch1" href="Text/ch1.xhtml" media-type="application/xhtml+xml"/>
  </manifest>
  <spine>
    <itemref idref="ch1"/>
  </spine>
</package>
"""
    xhtml = """<?xml version="1.0" encoding="utf-8"?>
<html xmlns="http://www.w3.org/1999/xhtml">
  <body>
    <p>Alpha</p>
    <p>Beta</p>
  </body>
</html>
"""
    container = """<?xml version="1.0" encoding="utf-8"?>
<container version="1.0" xmlns="urn:oasis:names:tc:opendocument:xmlns:container">
  <rootfiles>
    <rootfile full-path="OPS/content.opf" media-type="application/oebps-package+xml"/>
  </rootfiles>
</container>
"""
    with zipfile.ZipFile(epub_path, "w", compression=zipfile.ZIP_DEFLATED) as zf:
        zf.writestr("META-INF/container.xml", container)
        zf.writestr("OPS/content.opf", opf)
        zf.writestr("OPS/Text/ch1.xhtml", xhtml)
    return epub_path


def test_segment_ledger_lifecycle_and_stale_reset(tmp_path: Path) -> None:
    db_path = tmp_path / "ledger.db"
    ledger = SegmentLedger(db_path, project_id=7, run_step="translate")

    chapter = "OPS/Text/ch1.xhtml"
    seg_id = "OPS/Text/ch1.xhtml__000001__abc123"
    ledger.ensure_pending(chapter, seg_id, "Hello world")
    row = ledger.load_chapter_states(chapter)[seg_id]
    assert str(row["status"]) == "PENDING"

    ledger.mark_processing(chapter, seg_id, "Hello world", provider="google", model="gemini")
    row = ledger.load_chapter_states(chapter)[seg_id]
    assert str(row["status"]) == "PROCESSING"
    assert int(row["attempt_count"]) >= 1

    ledger.mark_completed(chapter, seg_id, "Hello world", "Witaj swiecie", provider="google", model="gemini")
    row = ledger.load_chapter_states(chapter)[seg_id]
    assert str(row["status"]) == "COMPLETED"
    assert str(row["translated_inner"]) == "Witaj swiecie"

    ledger.conn.execute(
        """
        UPDATE segment_ledger
        SET status = 'PROCESSING', updated_at = ?, error_message = ''
        WHERE project_id = ? AND run_step = ? AND segment_hash = ?
        """,
        (int(time.time()) - 9999, 7, "translate", seg_id),
    )
    ledger.conn.commit()
    reset = ledger.reset_stale_processing(max_age_s=60)
    assert reset >= 1
    row = ledger.load_chapter_states(chapter)[seg_id]
    assert str(row["status"]) == "PENDING"
    ledger.close()


def test_text_preserve_keeps_inline_tags() -> None:
    root = etree.fromstring(b"<p>Hello <i class='em'>World</i>!</p>")
    set_text_preserving_inline(root, "Hi Earth?")
    assert root.find(".//i") is not None
    italic = root.find(".//i")
    assert italic is not None
    assert str(italic.get("class")) == "em"
    as_text = etree.tostring(root, encoding="unicode", method="text")
    assert as_text == "Hi Earth?"


def test_text_preserve_keeps_nested_inline_tags() -> None:
    root = etree.fromstring(b"<p>A <i>very <b>deep</b></i> example.</p>")
    set_text_preserving_inline(root, "X Y Z")
    italic = root.find(".//i")
    bold = root.find(".//b")
    assert italic is not None
    assert bold is not None
    assert bold.getparent() is italic
    as_text = etree.tostring(root, encoding="unicode", method="text")
    assert as_text == "X Y Z"


def test_tokenize_inline_markup_supports_nested_chips_roundtrip() -> None:
    root = etree.fromstring(b"<p>A <i>very <b>deep</b></i> example.</p>")
    text, token_map = tokenize_inline_markup(root)
    assert "[[TAG001]]" in text
    assert len(token_map) >= 4
    updated = text.replace("very", "mega").replace("example", "sample")
    apply_tokenized_inline_markup(root, updated, token_map)
    out = etree.tostring(root, encoding="unicode", method="xml")
    assert "<i>" in out and "</i>" in out
    assert "<b>" in out and "</b>" in out
    assert "mega" in out
    assert "sample" in out


def _make_entity_epub(tmp_path: Path, *, chapter_text: str, name: str) -> Path:
    epub_path = tmp_path / name
    opf = """<?xml version="1.0" encoding="utf-8"?>
<package xmlns="http://www.idpf.org/2007/opf" version="3.0">
  <manifest>
    <item id="ch1" href="Text/ch1.xhtml" media-type="application/xhtml+xml"/>
  </manifest>
  <spine>
    <itemref idref="ch1"/>
  </spine>
</package>
"""
    xhtml = f"""<?xml version="1.0" encoding="utf-8"?>
<html xmlns="http://www.w3.org/1999/xhtml">
  <body>
    <p>{chapter_text}</p>
  </body>
</html>
"""
    container = """<?xml version="1.0" encoding="utf-8"?>
<container version="1.0" xmlns="urn:oasis:names:tc:opendocument:xmlns:container">
  <rootfiles>
    <rootfile full-path="OPS/content.opf" media-type="application/oebps-package+xml"/>
  </rootfiles>
</container>
"""
    with zipfile.ZipFile(epub_path, "w", compression=zipfile.ZIP_DEFLATED) as zf:
        zf.writestr("META-INF/container.xml", container)
        zf.writestr("OPS/content.opf", opf)
        zf.writestr("OPS/Text/ch1.xhtml", xhtml)
    return epub_path


def test_validate_entity_integrity_detects_entity_drop(tmp_path: Path) -> None:
    inp = _make_entity_epub(tmp_path, chapter_text="A&shy;B&nbsp;C", name="in.epub")
    out = _make_entity_epub(tmp_path, chapter_text="ABC", name="out.epub")
    ok, report, msg = validate_entity_integrity(inp, out)
    assert ok is False
    assert report["delta_soft_hyphen"] < 0 or report["delta_nbsp"] < 0
    assert "ENTITY-INTEGRITY" in msg


def test_semantic_similarity_score_distinguishes_close_and_far_texts() -> None:
    close = semantic_similarity_score("To jest bardzo krotkie zdanie.", "To jest krotkie zdanie.")
    far = semantic_similarity_score("Kot siedzi na kanapie.", "Samolot startuje z lotniska.")
    assert close > 0.55
    assert far < 0.55


def test_segment_ledger_semantic_findings_replace_previous_open_rows(tmp_path: Path) -> None:
    db_path = tmp_path / "semantic_findings.db"
    db = ProjectDB(db_path)
    try:
        pid = db.create_project("Semantic gate project")
    finally:
        db.close()

    ledger = SegmentLedger(db_path, project_id=pid, run_step="translate")
    try:
        inserted = ledger.replace_semantic_diff_findings(
            [
                {
                    "chapter_path": "OPS/Text/ch1.xhtml",
                    "segment_index": 1,
                    "segment_id": "sid-1",
                    "severity": "warn",
                    "message": "Semantic drift score=0.40",
                },
                {
                    "chapter_path": "OPS/Text/ch1.xhtml",
                    "segment_index": 2,
                    "segment_id": "sid-2",
                    "severity": "error",
                    "message": "Semantic drift score=0.20",
                },
            ]
        )
        assert inserted == 2
        inserted2 = ledger.replace_semantic_diff_findings(
            [
                {
                    "chapter_path": "OPS/Text/ch2.xhtml",
                    "segment_index": 4,
                    "segment_id": "sid-3",
                    "severity": "warn",
                    "message": "Semantic drift score=0.50",
                }
            ]
        )
        assert inserted2 == 1
    finally:
        ledger.close()

    db2 = ProjectDB(db_path)
    try:
        rows = db2.list_qa_findings(pid, step="translate", status=None)
        sem_rows = [r for r in rows if str(r["rule_code"]) == "SEMANTIC_DIFF" and str(r["status"]) in {"open", "in_progress"}]
        assert len(sem_rows) == 1
        assert str(sem_rows[0]["segment_id"]) == "sid-3"
    finally:
        db2.close()


def test_build_run_command_includes_run_step() -> None:
    opts = RunOptions(
        provider="ollama",
        input_epub="in.epub",
        output_epub="out.epub",
        prompt="prompt.txt",
        model="llama3.1:8b",
        batch_max_segs="6",
        batch_max_chars="12000",
        sleep="0",
        timeout="300",
        attempts="3",
        backoff="5,15,30",
        temperature="0.1",
        num_ctx="8192",
        num_predict="2048",
        tags="p,li",
        checkpoint="0",
        debug_dir="debug",
        source_lang="en",
        target_lang="pl",
        run_step="edit",
    )
    cmd = build_run_command(["python", "-u", "translation_engine.py"], opts)
    assert "--run-step" in cmd
    idx = cmd.index("--run-step")
    assert idx + 1 < len(cmd)
    assert cmd[idx + 1] == "edit"


def test_segment_ledger_seed_initializes_pending_and_tracks_completed(tmp_path: Path) -> None:
    epub_path = _make_epub(tmp_path)
    db_path = tmp_path / "seed.db"
    ledger = SegmentLedger(db_path, project_id=11, run_step="translate")
    try:
        summary = seed_segment_ledger_from_epub(epub_path, ("p",), ledger)
        assert summary.total_segments == 2
        assert summary.completed_segments == 0
        assert summary.upserted_segments == 2
        assert summary.pruned_segments == 0

        states = ledger.load_scope_states()
        assert len(states) == 2
        first_sid = sorted(states.keys())[0]
        first_row = states[first_sid]
        ledger.mark_completed(
            str(first_row["chapter_path"]),
            first_sid,
            "Alpha",
            "Alfa",
            provider="cache",
            model="seed-test",
        )

        summary2 = seed_segment_ledger_from_epub(epub_path, ("p",), ledger)
        assert summary2.total_segments == 2
        assert summary2.completed_segments == 1
    finally:
        ledger.close()


def test_parse_epubcheck_findings_counts_error_levels() -> None:
    raw = "\n".join(
        [
            "ERROR(RSC-005): bad XHTML",
            "WARNING(ACC-001): alt text missing",
            "FATAL(PKG-008): package invalid",
            "INFO: ignored",
        ]
    )
    counts = parse_epubcheck_findings(raw)
    assert counts["error"] == 1
    assert counts["warning"] == 1
    assert counts["fatal"] == 1


def test_qa_severity_gate_blocks_open_error_and_fatal(tmp_path: Path) -> None:
    db_path = tmp_path / "studio.db"
    db = ProjectDB(db_path)
    try:
        pid = db.create_project("QA gate test")
        db.replace_qa_findings(
            pid,
            "translate",
            [
                {
                    "chapter_path": "OPS/Text/ch1.xhtml",
                    "segment_index": 0,
                    "segment_id": "ch1#0",
                    "severity": "error",
                    "rule_code": "E1",
                    "message": "bad markup",
                },
                {
                    "chapter_path": "OPS/Text/ch1.xhtml",
                    "segment_index": 1,
                    "segment_id": "ch1#1",
                    "severity": "warn",
                    "rule_code": "W1",
                    "message": "style warning",
                },
            ],
        )
        ok, _ = db.qa_severity_gate_status(pid, "translate", severities=("fatal", "error"))
        assert ok is False

        rows = db.list_qa_findings(pid, step="translate", status=None)
        for row in rows:
            if str(row["severity"]).lower() == "error":
                db.update_qa_finding_status(int(row["id"]), "resolved")
        ok2, _ = db.qa_severity_gate_status(pid, "translate", severities=("fatal", "error"))
        assert ok2 is True
    finally:
        db.close()
