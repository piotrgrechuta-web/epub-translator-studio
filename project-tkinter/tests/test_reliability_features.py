from __future__ import annotations

import re
import sys
import time
import zipfile
from pathlib import Path

from lxml import etree

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from runtime_core import RunOptions, build_run_command, validate_run_options  # noqa: E402
from app_gui_classic import parse_epubcheck_findings  # noqa: E402
from project_db import ProjectDB  # noqa: E402
from text_preserve import set_text_preserving_inline, tokenize_inline_markup, apply_tokenized_inline_markup  # noqa: E402
from translation_engine import (  # noqa: E402
    Segment,
    SegmentLedger,
    TranslationMemory,
    build_batch_payload,
    chunk_segments,
    seed_segment_ledger_from_epub,
    translate_epub,
    validate_entity_integrity,
    semantic_similarity_score,
    load_language_guard_profiles,
    looks_like_target_language,
    build_context_hints,
    normalize_quotes_and_apostrophes_inner_xml,
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


def test_async_io_dispatch_keeps_ledger_idempotent(tmp_path: Path) -> None:
    class FakeBatchLLM:
        def __init__(self) -> None:
            self.calls = 0

        def resolve_model(self) -> str:
            return "fake-model"

        def generate(self, prompt: str, model: str) -> str:
            _ = model
            self.calls += 1
            chunks = re.findall(r"(<batch\b[\s\S]*?</batch>)", prompt, flags=re.IGNORECASE)
            assert chunks
            parser = etree.XMLParser(recover=True, huge_tree=True)
            root = etree.fromstring(chunks[-1].encode("utf-8"), parser=parser)
            seg_items = []
            for seg in root.findall(".//{*}seg"):
                sid = str(seg.get("id") or "").strip()
                assert sid
                seg_items.append((sid, f"PL::{sid}"))
            return build_batch_payload(seg_items)

    input_epub = _make_epub(tmp_path)
    output_epub = tmp_path / "out.epub"
    cache_path = tmp_path / "cache.jsonl"
    db_path = tmp_path / "tm_ledger.db"
    tm = None
    ledger = None
    llm = FakeBatchLLM()
    try:
        tm = TranslationMemory(db_path, project_id=19)
        ledger = SegmentLedger(db_path, project_id=19, run_step="translate")
        translate_epub(
            input_epub=input_epub,
            output_epub=output_epub,
            base_prompt="Translate faithfully.",
            llm=llm,
            provider="google",
            cache_path=cache_path,
            block_tags=("p",),
            batch_max_chars=200,
            batch_max_segs=1,
            sleep_s=0.01,
            polish_guard=False,
            tm=tm,
            segment_ledger=ledger,
            semantic_gate_enabled=False,
            io_concurrency=2,
        )
        first_calls = llm.calls
        assert first_calls >= 1
        states = ledger.load_scope_states()
        assert len(states) == 2
        assert all(str(r["status"]) == "COMPLETED" for r in states.values())

        translate_epub(
            input_epub=input_epub,
            output_epub=output_epub,
            base_prompt="Translate faithfully.",
            llm=llm,
            provider="google",
            cache_path=cache_path,
            block_tags=("p",),
            batch_max_chars=200,
            batch_max_segs=1,
            sleep_s=0.01,
            polish_guard=False,
            tm=tm,
            segment_ledger=ledger,
            semantic_gate_enabled=False,
            io_concurrency=2,
        )
        assert llm.calls == first_calls
        states2 = ledger.load_scope_states()
        assert len(states2) == 2
        assert all(str(r["status"]) == "COMPLETED" for r in states2.values())
    finally:
        if ledger is not None:
            ledger.close()
        if tm is not None:
            tm.close()


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


def test_language_guard_profiles_support_custom_language(tmp_path: Path) -> None:
    cfg = tmp_path / "guards.json"
    cfg.write_text(
        """
{
  "ro": {
    "special_chars": "ăâîșț",
    "hint_words": ["si", "este", "nu", "un", "o", "cu", "pentru", "care"]
  }
}
""".strip(),
        encoding="utf-8",
    )
    profiles = load_language_guard_profiles(cfg)
    assert "ro" in profiles
    assert looks_like_target_language("Acesta este un test si merge bine.", "ro", profiles=profiles) is True
    assert (
        looks_like_target_language(
            "This is clearly english text with many words and no romanian markers at all.",
            "ro",
            profiles=profiles,
        )
        is False
    )


def test_quote_normalization_polish_nested_and_apostrophes() -> None:
    src = "\"To jest \"cytat <i>w srodku</i>\" i O'Connor.\""
    out = normalize_quotes_and_apostrophes_inner_xml(src, target_lang="pl")
    assert out.text == "\u201eTo jest \u00abcytat <i>w srodku</i>\u00bb i O\u2019Connor.\u201d"
    assert out.replacements >= 4
    assert out.quote_replacements >= 3
    assert out.apostrophe_replacements >= 1


def test_quote_normalization_english_uses_curly_quotes() -> None:
    src = "\"He said 'it's fine'.\""
    out = normalize_quotes_and_apostrophes_inner_xml(src, target_lang="en")
    assert out.text == "\u201cHe said \u2018it\u2019s fine\u2019.\u201d"


def test_translate_epub_reports_quote_normalization(tmp_path: Path, capsys) -> None:
    class FakeQuoteLLM:
        def resolve_model(self) -> str:
            return "fake-model"

        def generate(self, prompt: str, model: str) -> str:
            _ = model
            chunks = re.findall(r"(<batch\b[\s\S]*?</batch>)", prompt, flags=re.IGNORECASE)
            assert chunks
            parser = etree.XMLParser(recover=True, huge_tree=True)
            root = etree.fromstring(chunks[-1].encode("utf-8"), parser=parser)
            seg_items = []
            for seg in root.findall(".//{*}seg"):
                sid = str(seg.get("id") or "").strip()
                assert sid
                seg_items.append((sid, "\"To jest \"cytat <i>w srodku</i>\" i O'Connor.\""))
            return build_batch_payload(seg_items)

    inp = _make_entity_epub(tmp_path, chapter_text="Alpha", name="q_in.epub")
    outp = tmp_path / "q_out.epub"
    cache_path = tmp_path / "q_cache.jsonl"
    llm = FakeQuoteLLM()
    translate_epub(
        input_epub=inp,
        output_epub=outp,
        base_prompt="Translate faithfully.",
        llm=llm,
        provider="google",
        cache_path=cache_path,
        block_tags=("p",),
        batch_max_chars=200,
        batch_max_segs=1,
        sleep_s=0.0,
        polish_guard=False,
        semantic_gate_enabled=False,
    )

    with zipfile.ZipFile(outp, "r") as zf:
        text = zf.read("OPS/Text/ch1.xhtml").decode("utf-8", errors="replace")
    assert "\u201eTo jest \u00abcytat <i>w srodku</i>\u00bb i O\u2019Connor.\u201d" in text

    captured = capsys.readouterr()
    assert "[QUOTE-NORM]" in captured.out
    assert "segments_changed=" in captured.out
    assert "apostrophes=" in captured.out


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
        io_concurrency="3",
        context_window="5",
        context_neighbor_max_chars="200",
        context_segment_max_chars="1500",
        short_segment_max_chars="48",
        short_batch_target_chars="900",
        short_batch_max_segs="18",
    )
    cmd = build_run_command(["python", "-u", "translation_engine.py"], opts)
    assert "--run-step" in cmd
    idx = cmd.index("--run-step")
    assert idx + 1 < len(cmd)
    assert cmd[idx + 1] == "edit"
    assert "--context-window" in cmd
    assert cmd[cmd.index("--context-window") + 1] == "5"
    assert "--context-neighbor-max-chars" in cmd
    assert "--context-segment-max-chars" in cmd
    assert "--io-concurrency" in cmd
    assert cmd[cmd.index("--io-concurrency") + 1] == "3"
    assert "--short-segment-max-chars" in cmd
    assert cmd[cmd.index("--short-segment-max-chars") + 1] == "48"
    assert "--short-batch-target-chars" in cmd
    assert cmd[cmd.index("--short-batch-target-chars") + 1] == "900"
    assert "--short-batch-max-segs" in cmd
    assert cmd[cmd.index("--short-batch-max-segs") + 1] == "18"


def test_build_run_command_can_disable_short_merge() -> None:
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
        short_merge_enabled=False,
    )
    cmd = build_run_command(["python", "-u", "translation_engine.py"], opts)
    assert "--no-short-merge" in cmd


def test_build_run_command_includes_language_guard_config(tmp_path: Path) -> None:
    in_epub = tmp_path / "in.epub"
    out_epub = tmp_path / "out.epub"
    prompt = tmp_path / "prompt.txt"
    guard_cfg = tmp_path / "guards.json"
    in_epub.write_text("x", encoding="utf-8")
    prompt.write_text("prompt", encoding="utf-8")
    guard_cfg.write_text('{"ro":{"special_chars":"abc","hint_words":["si"]}}', encoding="utf-8")
    opts = RunOptions(
        provider="ollama",
        input_epub=str(in_epub),
        output_epub=str(out_epub),
        prompt=str(prompt),
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
        language_guard_config=str(guard_cfg),
    )
    cmd = build_run_command(["python", "-u", "translation_engine.py"], opts)
    assert "--language-guard-config" in cmd
    assert cmd[cmd.index("--language-guard-config") + 1] == str(guard_cfg)


def test_validate_run_options_rejects_invalid_runtime_contract(tmp_path: Path) -> None:
    in_epub = tmp_path / "in.epub"
    prompt = tmp_path / "prompt.txt"
    in_epub.write_text("x", encoding="utf-8")
    prompt.write_text("prompt", encoding="utf-8")
    opts = RunOptions(
        provider="ollama",
        input_epub=str(in_epub),
        output_epub=str(tmp_path / "out.epub"),
        prompt=str(prompt),
        model="m",
        batch_max_segs="0",
        batch_max_chars="12000",
        sleep="0",
        timeout="300",
        attempts="3",
        backoff="5,15,30",
        temperature="0.1",
        num_ctx="8192",
        num_predict="2048",
        tags="p",
        checkpoint="0",
        debug_dir="debug",
        source_lang="en",
        target_lang="pl",
        run_step="invalid",
    )
    err = validate_run_options(opts)
    assert err is not None
    assert "run_step" in err

    opts.run_step = "translate"
    err2 = validate_run_options(opts)
    assert err2 is not None
    assert "batch_max_segs" in err2


def test_validate_run_options_rejects_invalid_language_guard_config(tmp_path: Path) -> None:
    in_epub = tmp_path / "in.epub"
    prompt = tmp_path / "prompt.txt"
    cfg = tmp_path / "guards.json"
    in_epub.write_text("x", encoding="utf-8")
    prompt.write_text("prompt", encoding="utf-8")
    cfg.write_text("[1,2,3]", encoding="utf-8")
    opts = RunOptions(
        provider="ollama",
        input_epub=str(in_epub),
        output_epub=str(tmp_path / "out.epub"),
        prompt=str(prompt),
        model="m",
        batch_max_segs="1",
        batch_max_chars="12000",
        sleep="0",
        timeout="300",
        attempts="3",
        backoff="5,15,30",
        temperature="0.1",
        num_ctx="8192",
        num_predict="2048",
        tags="p",
        checkpoint="0",
        debug_dir="debug",
        source_lang="en",
        target_lang="pl",
        language_guard_config=str(cfg),
    )
    err = validate_run_options(opts)
    assert err is not None
    assert "root must be an object" in err


def test_build_context_hints_uses_neighbor_window() -> None:
    chapter_order = [
        ("s1", "Alpha one."),
        ("s2", "Beta two."),
        ("s3", "Gamma three."),
        ("s4", "Delta four."),
    ]
    hints = build_context_hints(
        chapter_order,
        {"s2", "s3"},
        window=1,
        neighbor_max_chars=80,
        per_segment_max_chars=300,
    )
    assert "s2" in hints and "s3" in hints
    assert "Alpha one." in hints["s2"]
    assert "Gamma three." in hints["s2"]
    assert "Beta two." in hints["s3"]
    assert "Delta four." in hints["s3"]


def _mk_segment(idx: int, text: str) -> Segment:
    el = etree.Element("p")
    el.text = text
    return Segment(idx=idx, el=el, seg_id=f"seg-{idx}", inner=text, plain=text)


def test_chunk_segments_soft_merge_short_segments() -> None:
    segs = [_mk_segment(i, "Hi.") for i in range(1, 9)]
    chunks = list(
        chunk_segments(
            segs,
            batch_max_chars=12000,
            batch_max_segs=2,
            short_merge_enabled=True,
            short_segment_max_chars=12,
            short_batch_target_chars=400,
            short_batch_max_segs=10,
        )
    )
    assert [len(ch) for ch in chunks] == [5, 3]


def test_chunk_segments_respects_classic_limit_when_short_merge_disabled() -> None:
    segs = [_mk_segment(i, "Hi.") for i in range(1, 9)]
    chunks = list(
        chunk_segments(
            segs,
            batch_max_chars=12000,
            batch_max_segs=2,
            short_merge_enabled=False,
            short_segment_max_chars=12,
            short_batch_target_chars=400,
            short_batch_max_segs=10,
        )
    )
    assert [len(ch) for ch in chunks] == [2, 2, 2, 2]


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
