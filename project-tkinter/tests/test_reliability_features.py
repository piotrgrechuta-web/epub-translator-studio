from __future__ import annotations

import sys
import time
from pathlib import Path

from lxml import etree

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from runtime_core import RunOptions, build_run_command  # noqa: E402
from text_preserve import set_text_preserving_inline  # noqa: E402
from translation_engine import SegmentLedger  # noqa: E402


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
