from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable, Dict, Iterable, List, Mapping, Optional, Sequence, Tuple


@dataclass(frozen=True)
class StartupPathSuggestion:
    output_epub: Path
    cache_path: Path
    conflict_resolved: bool


def _norm_path(value: str) -> str:
    raw = str(value or "").strip()
    if not raw:
        return ""
    try:
        return str(Path(raw).resolve()).lower()
    except Exception:
        return str(Path(raw)).lower()


def discover_input_epubs(workdir: Path) -> List[Path]:
    base = Path(workdir)
    cands = [p for p in base.glob("*.epub") if p.is_file()]
    return sorted(cands, key=lambda p: p.name.lower())


def _first_free_path(base_path: Path, exists_fn: Callable[[Path], bool]) -> Path:
    if not exists_fn(base_path):
        return base_path
    stem = base_path.stem
    suffix = base_path.suffix
    parent = base_path.parent
    first = parent / f"{stem}_new{suffix}"
    if not exists_fn(first):
        return first
    idx = 2
    while True:
        cand = parent / f"{stem}_new{idx}{suffix}"
        if not exists_fn(cand):
            return cand
        idx += 1


def suggest_paths_for_step(
    input_epub: Path,
    *,
    target_lang: str,
    step: str,
    exists_fn: Optional[Callable[[Path], bool]] = None,
) -> StartupPathSuggestion:
    exists = exists_fn or (lambda p: p.exists())
    src = Path(input_epub)
    stem = src.stem
    tgt = (target_lang or "pl").strip().lower() or "pl"
    run_step = (step or "translate").strip().lower() or "translate"
    if run_step == "edit":
        output_name = f"{stem}_{tgt}_redakcja.epub"
        cache_name = f"cache_{stem}_redakcja.jsonl"
    else:
        output_name = f"{stem}_{tgt}.epub"
        cache_name = f"cache_{stem}.jsonl"
    output_base = src.with_name(output_name)
    output_final = _first_free_path(output_base, exists)
    cache_final = src.with_name(cache_name)
    return StartupPathSuggestion(
        output_epub=output_final,
        cache_path=cache_final,
        conflict_resolved=(output_final != output_base),
    )


def match_projects_by_input_and_langs(
    projects: Iterable[Mapping[str, Any]],
    *,
    input_epub: str,
    source_lang: str,
    target_lang: str,
) -> List[Dict[str, Any]]:
    in_norm = _norm_path(input_epub)
    src_lang = (source_lang or "en").strip().lower() or "en"
    tgt_lang = (target_lang or "pl").strip().lower() or "pl"
    out: List[Dict[str, Any]] = []
    for row in projects:
        p_input = _norm_path(str(row.get("input_epub") or ""))
        if not in_norm or p_input != in_norm:
            continue
        p_src = (str(row.get("source_lang") or "en").strip().lower() or "en")
        p_tgt = (str(row.get("target_lang") or "pl").strip().lower() or "pl")
        if p_src == src_lang and p_tgt == tgt_lang:
            out.append(dict(row))
    out.sort(key=lambda r: int(r.get("updated_at", 0) or 0), reverse=True)
    return out


def resume_eligibility(
    *,
    project_status: str,
    stage_status: str,
    stage_done: int,
    stage_total: int,
    cache_exists: bool,
    ledger_counts: Optional[Mapping[str, int]] = None,
) -> Tuple[bool, str]:
    p_status = (project_status or "idle").strip().lower() or "idle"
    s_status = (stage_status or "none").strip().lower() or "none"
    done = max(0, int(stage_done or 0))
    total = max(0, int(stage_total or 0))
    if s_status == "ok" and (total == 0 or done >= total):
        return False, "stage_completed"
    if p_status in {"pending", "running", "error", "needs_review"}:
        return True, f"project_status:{p_status}"
    if s_status in {"running", "error", "pending"}:
        return True, f"stage_status:{s_status}"
    if done > 0 and (total == 0 or done < total):
        return True, "stage_partial_progress"
    if cache_exists:
        return True, "cache_present"
    if ledger_counts:
        pending = max(0, int(ledger_counts.get("PENDING", 0) or 0))
        processing = max(0, int(ledger_counts.get("PROCESSING", 0) or 0))
        completed = max(0, int(ledger_counts.get("COMPLETED", 0) or 0))
        if pending > 0 or processing > 0 or completed > 0:
            return True, "ledger_present"
    return False, "fresh_state"


def parse_ambiguous_choice(candidates: Sequence[Path], selected_index: str) -> Optional[Path]:
    text = str(selected_index or "").strip()
    if not text:
        return candidates[0] if candidates else None
    try:
        idx = int(text)
    except Exception:
        return None
    if idx < 1 or idx > len(candidates):
        return None
    return candidates[idx - 1]
