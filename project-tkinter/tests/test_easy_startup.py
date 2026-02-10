from __future__ import annotations

import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from easy_startup import (  # noqa: E402
    discover_input_epubs,
    match_projects_by_input_and_langs,
    parse_ambiguous_choice,
    resume_eligibility,
    suggest_paths_for_step,
)


def test_discover_input_epubs_sorts_candidates(tmp_path: Path) -> None:
    (tmp_path / "b.epub").write_text("x", encoding="utf-8")
    (tmp_path / "a.epub").write_text("x", encoding="utf-8")
    (tmp_path / "note.txt").write_text("x", encoding="utf-8")
    out = discover_input_epubs(tmp_path)
    assert [p.name for p in out] == ["a.epub", "b.epub"]


def test_suggest_paths_for_step_resolves_output_conflict(tmp_path: Path) -> None:
    inp = tmp_path / "book.epub"
    inp.write_text("x", encoding="utf-8")
    first = suggest_paths_for_step(inp, target_lang="pl", step="translate")
    assert first.output_epub.name == "book_pl.epub"
    assert first.cache_path.name == "cache_book.jsonl"
    assert first.conflict_resolved is False

    (tmp_path / "book_pl.epub").write_text("existing", encoding="utf-8")
    second = suggest_paths_for_step(inp, target_lang="pl", step="translate")
    assert second.output_epub.name == "book_pl_new.epub"
    assert second.conflict_resolved is True


def test_match_projects_by_input_and_langs_handles_unique_and_ambiguous(tmp_path: Path) -> None:
    inp = tmp_path / "novel.epub"
    inp.write_text("x", encoding="utf-8")
    rows = [
        {"id": 11, "input_epub": str(inp), "source_lang": "en", "target_lang": "pl", "updated_at": 10},
        {"id": 12, "input_epub": str(inp), "source_lang": "en", "target_lang": "de", "updated_at": 20},
        {"id": 13, "input_epub": str(inp), "source_lang": "en", "target_lang": "pl", "updated_at": 30},
    ]
    pl = match_projects_by_input_and_langs(rows, input_epub=str(inp), source_lang="en", target_lang="pl")
    assert [int(r["id"]) for r in pl] == [13, 11]
    de = match_projects_by_input_and_langs(rows, input_epub=str(inp), source_lang="en", target_lang="de")
    assert [int(r["id"]) for r in de] == [12]


def test_resume_eligibility_fresh_and_resume_paths() -> None:
    fresh, reason_fresh = resume_eligibility(
        project_status="idle",
        stage_status="none",
        stage_done=0,
        stage_total=0,
        cache_exists=False,
        ledger_counts={"PENDING": 0, "PROCESSING": 0, "COMPLETED": 0, "ERROR": 0},
    )
    assert fresh is False
    assert reason_fresh == "fresh_state"

    resumed, reason_resume = resume_eligibility(
        project_status="pending",
        stage_status="running",
        stage_done=3,
        stage_total=10,
        cache_exists=True,
        ledger_counts={"PENDING": 7, "PROCESSING": 1, "COMPLETED": 2, "ERROR": 0},
    )
    assert resumed is True
    assert reason_resume.startswith("project_status:")


def test_parse_ambiguous_choice_supports_lightweight_picker(tmp_path: Path) -> None:
    cands = [tmp_path / "a.epub", tmp_path / "b.epub", tmp_path / "c.epub"]
    assert parse_ambiguous_choice(cands, "") == cands[0]
    assert parse_ambiguous_choice(cands, "2") == cands[1]
    assert parse_ambiguous_choice(cands, "0") is None
    assert parse_ambiguous_choice(cands, "abc") is None
