from __future__ import annotations

import json
import os
import re
import sqlite3
import subprocess
import sys
import threading
import time
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel, Field

BASE_DIR = Path(__file__).resolve().parent
REPO_ROOT = BASE_DIR.parents[1]
TK_DIR = REPO_ROOT / "project-tkinter"
if str(TK_DIR) not in sys.path:
    sys.path.insert(0, str(TK_DIR))

from project_db import DB_FILE, ProjectDB  # noqa: E402
from runtime_core import (  # noqa: E402
    DEFAULT_SUPPORTED_TEXT_LANGS,
    GOOGLE_API_KEY_ENV,
    OLLAMA_HOST_DEFAULT,
    RunOptions,
    build_run_command,
    build_validation_command,
    list_google_models,
    list_ollama_models,
    validate_run_options,
)

STATE_FILE = BASE_DIR / "ui_state.json"
DEFAULT_DB = BASE_DIR / DB_FILE
VERSION_FILE = BASE_DIR.parent / "VERSION"
TRANSLATOR = (TK_DIR / "tlumacz_ollama.py") if (TK_DIR / "tlumacz_ollama.py").exists() else (BASE_DIR / "engine" / "tlumacz_ollama.py")
STEP_MODES = {"translate", "edit"}
SUPPORTED_TEXT_LANGS = set(DEFAULT_SUPPORTED_TEXT_LANGS)
PROFILE_KEYS = {
    "provider",
    "model",
    "debug_dir",
    "ollama_host",
    "batch_max_segs",
    "batch_max_chars",
    "sleep",
    "timeout",
    "attempts",
    "backoff",
    "temperature",
    "num_ctx",
    "num_predict",
    "tags",
    "use_cache",
    "use_glossary",
    "checkpoint",
    "source_lang",
    "target_lang",
}
PROJECT_SAVE_KEYS = {
    "input_epub",
    "output_translate_epub",
    "output_edit_epub",
    "prompt_translate",
    "prompt_edit",
    "glossary_path",
    "cache_translate_path",
    "cache_edit_path",
    "profile_translate_id",
    "profile_edit_id",
    "source_lang",
    "target_lang",
    "active_step",
    "notes",
}


def _read_version() -> str:
    try:
        raw = VERSION_FILE.read_text(encoding="utf-8").strip()
    except Exception:
        raw = ""
    return raw or "0.0.0"


APP_VERSION = _read_version()
GLOBAL_PROGRESS_RE = re.compile(r"\bGLOBAL\s+(\d+)\s*/\s*(\d+)\b")
TOTAL_SEGMENTS_RE = re.compile(r"Segmenty\s+(?:łącznie|lacznie)\s*:\s*(\d+)", re.IGNORECASE)
CACHE_SEGMENTS_RE = re.compile(r"Segmenty\s+z\s+cache\s*:\s*(\d+)", re.IGNORECASE)
CHAPTER_CACHE_TM_RE = re.compile(r"\(cache:\s*(\d+)\s*,\s*tm:\s*(\d+)\)", re.IGNORECASE)
METRICS_BLOB_RE = re.compile(r"metrics\[(.*?)\]", re.IGNORECASE)
METRICS_KV_RE = re.compile(r"([a-zA-Z_]+)\s*=\s*([^;]+)")


app = FastAPI(title="Translator Studio API", version=APP_VERSION)
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


class UiState(BaseModel):
    mode: str = "translate"
    provider: str = "ollama"
    input_epub: str = ""
    output_epub: str = ""
    prompt: str = ""
    glossary: str = ""
    cache: str = ""
    debug_dir: str = "debug"
    ollama_host: str = OLLAMA_HOST_DEFAULT
    google_api_key: str = ""
    model: str = ""
    batch_max_segs: str = "6"
    batch_max_chars: str = "12000"
    sleep: str = "0"
    timeout: str = "300"
    attempts: str = "3"
    backoff: str = "5,15,30"
    temperature: str = "0.1"
    num_ctx: str = "8192"
    num_predict: str = "2048"
    tags: str = "p,li,h1,h2,h3,h4,h5,h6,blockquote,dd,dt,figcaption,caption"
    use_cache: bool = True
    use_glossary: bool = True
    checkpoint: str = "0"
    source_lang: str = "en"
    target_lang: str = "pl"
    tm_db: str = str(DEFAULT_DB)
    tm_project_id: Optional[int] = None


class RunRequest(BaseModel):
    state: UiState


class ValidateRequest(BaseModel):
    epub_path: str
    tags: str = "p,li,h1,h2,h3,h4,h5,h6,blockquote,dd,dt,figcaption,caption"
    project_id: Optional[int] = None
    tm_db: str = str(DEFAULT_DB)


class ProjectCreateRequest(BaseModel):
    name: str
    source_epub: str = ""
    source_lang: str = "en"
    target_lang: str = "pl"


class ProjectSaveRequest(BaseModel):
    values: Dict[str, Any] = Field(default_factory=dict)


class ProjectDeleteRequest(BaseModel):
    hard: bool = False


class ProjectSelectRequest(BaseModel):
    project_id: int
    mode: Optional[str] = None


class ProfileCreateRequest(BaseModel):
    name: str
    settings: Optional[Dict[str, Any]] = None
    state: Optional[UiState] = None
    is_builtin: int = 0


class QueueMarkRequest(BaseModel):
    project_id: int
    step: str = "translate"


class QueueRunNextRequest(BaseModel):
    state: Optional[UiState] = None


def _step(v: str) -> str:
    s = str(v or "translate").strip().lower()
    return s if s in STEP_MODES else "translate"


def _db_path(raw: Optional[str]) -> Path:
    p = Path((raw or str(DEFAULT_DB)).strip()).expanduser()
    if not p.is_absolute():
        p = (BASE_DIR / p).resolve()
    elif os.name == "nt":
        drive = str(p.drive or "").strip()
        if drive and not Path(drive + "\\").exists():
            p = DEFAULT_DB
    return p


def _state_path_prompt(mode: str) -> str:
    names = ["prompt_redakcja.txt", "prompt.txt"] if _step(mode) == "edit" else ["prompt.txt"]
    for n in names:
        for base in [TK_DIR, BASE_DIR / "engine"]:
            f = base / n
            if f.exists():
                return str(f)
    return ""


def _load_state() -> UiState:
    if not STATE_FILE.exists():
        s = UiState()
        s.prompt = _state_path_prompt("translate")
        return s
    try:
        raw = json.loads(STATE_FILE.read_text(encoding="utf-8"))
        if isinstance(raw, dict):
            s = UiState(**raw)
            s.mode = _step(s.mode)
            return s
    except Exception:
        pass
    s = UiState()
    s.prompt = _state_path_prompt("translate")
    return s


def _save_state(s: UiState) -> None:
    s.mode = _step(s.mode)
    if not s.tm_db.strip():
        s.tm_db = str(DEFAULT_DB)
    STATE_FILE.write_text(json.dumps(s.model_dump(), ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def _open_db(state: Optional[UiState] = None) -> Tuple[ProjectDB, Path]:
    st = state or _load_state()
    path = _db_path(st.tm_db)
    try:
        return ProjectDB(path), path
    except OSError:
        fallback = DEFAULT_DB
        return ProjectDB(fallback), fallback


def _run_opts(s: UiState) -> RunOptions:
    return RunOptions(
        provider=s.provider,
        input_epub=s.input_epub.strip(),
        output_epub=s.output_epub.strip(),
        prompt=s.prompt.strip(),
        model=s.model.strip(),
        batch_max_segs=s.batch_max_segs.strip(),
        batch_max_chars=s.batch_max_chars.strip(),
        sleep=s.sleep.strip(),
        timeout=s.timeout.strip(),
        attempts=s.attempts.strip(),
        backoff=s.backoff.strip(),
        temperature=s.temperature.strip(),
        num_ctx=s.num_ctx.strip(),
        num_predict=s.num_predict.strip(),
        tags=s.tags.strip(),
        checkpoint=s.checkpoint.strip(),
        debug_dir=s.debug_dir.strip() or "debug",
        source_lang=s.source_lang.strip().lower(),
        target_lang=s.target_lang.strip().lower(),
        ollama_host=s.ollama_host.strip() or OLLAMA_HOST_DEFAULT,
        cache=s.cache.strip(),
        use_cache=s.use_cache,
        glossary=s.glossary.strip(),
        use_glossary=s.use_glossary,
        tm_db=str(_db_path(s.tm_db)),
        tm_project_id=s.tm_project_id,
    )


def _validate_state(s: UiState, google_key: str = "") -> None:
    err = validate_run_options(_run_opts(s), google_api_key=google_key, supported_text_langs=SUPPORTED_TEXT_LANGS)
    if err:
        raise ValueError(err)


def _cmd_run(s: UiState) -> List[str]:
    if not TRANSLATOR.exists():
        raise RuntimeError(f"Missing translator: {TRANSLATOR}")
    return build_run_command(["python", "-u", str(TRANSLATOR)], _run_opts(s), tm_fuzzy_threshold="0.92")


def _cmd_validate(epub: str, tags: str) -> List[str]:
    if not TRANSLATOR.exists():
        raise RuntimeError(f"Missing translator: {TRANSLATOR}")
    return build_validation_command(["python", "-u", str(TRANSLATOR)], epub, tags)


def _normalize_project_status(value: str) -> str:
    key = str(value or "idle").strip().lower() or "idle"
    aliases = {
        "none": "idle",
        "ready": "idle",
        "queued": "pending",
        "queue": "pending",
        "needs_review": "error",
        "failed": "error",
        "fail": "error",
        "done": "ok",
        "success": "ok",
    }
    if key in {"idle", "pending", "running", "error", "ok"}:
        return key
    return aliases.get(key, "idle")


def _normalize_stage_status(value: str) -> str:
    key = str(value or "none").strip().lower() or "none"
    aliases = {
        "queued": "pending",
        "queue": "pending",
        "in_progress": "running",
        "done": "ok",
        "success": "ok",
        "fail": "error",
        "failed": "error",
    }
    if key in {"none", "idle", "pending", "running", "ok", "error"}:
        return key
    return aliases.get(key, "none")


def _new_runtime_stats() -> Dict[str, Any]:
    return {"done": 0, "total": 0, "cache_hits": 0, "tm_hits": 0}


def _consume_runtime_log_line(stats: Dict[str, Any], line: str, seen_tm_lines: set[str]) -> None:
    s = str(line or "").strip()
    if not s:
        return
    m_progress = GLOBAL_PROGRESS_RE.search(s)
    if m_progress:
        try:
            stats["done"] = max(0, int(m_progress.group(1)))
            stats["total"] = max(0, int(m_progress.group(2)))
        except Exception:
            pass
    m_total = TOTAL_SEGMENTS_RE.search(s)
    if m_total:
        try:
            stats["total"] = max(int(stats.get("total", 0) or 0), int(m_total.group(1)))
        except Exception:
            pass
    m_cache = CACHE_SEGMENTS_RE.search(s)
    if m_cache:
        try:
            stats["cache_hits"] = max(0, int(m_cache.group(1)))
        except Exception:
            pass
    m_tm = CHAPTER_CACHE_TM_RE.search(s)
    if m_tm and s not in seen_tm_lines:
        seen_tm_lines.add(s)
        try:
            stats["tm_hits"] = int(stats.get("tm_hits", 0) or 0) + max(0, int(m_tm.group(2)))
        except Exception:
            pass


def _finalize_runtime_stats(stats: Dict[str, Any], started_at: Optional[float]) -> Dict[str, Any]:
    out = dict(stats)
    done = max(0, int(out.get("done", 0) or 0))
    total = max(0, int(out.get("total", 0) or 0))
    cache_hits = max(0, int(out.get("cache_hits", 0) or 0))
    tm_hits = max(0, int(out.get("tm_hits", 0) or 0))
    reuse_hits = cache_hits + tm_hits
    reuse_rate = (reuse_hits / total) * 100.0 if total > 0 else 0.0
    if started_at is not None:
        dur_s = int(max(0.0, time.time() - started_at))
    else:
        dur_s = max(0, int(out.get("dur_s", 0) or 0))
    out.update(
        {
            "done": done,
            "total": total,
            "cache_hits": cache_hits,
            "tm_hits": tm_hits,
            "reuse_hits": reuse_hits,
            "reuse_rate": reuse_rate,
            "dur_s": dur_s,
        }
    )
    return out


def _metrics_blob(stats: Dict[str, Any]) -> str:
    done = max(0, int(stats.get("done", 0) or 0))
    total = max(0, int(stats.get("total", 0) or 0))
    cache_hits = max(0, int(stats.get("cache_hits", 0) or 0))
    tm_hits = max(0, int(stats.get("tm_hits", 0) or 0))
    reuse_hits = max(0, int(stats.get("reuse_hits", cache_hits + tm_hits) or 0))
    reuse_rate = float(stats.get("reuse_rate", 0.0) or 0.0)
    dur_s = max(0, int(stats.get("dur_s", 0) or 0))
    return (
        f"metrics[dur_s={dur_s};done={done};total={total};cache_hits={cache_hits};"
        f"tm_hits={tm_hits};reuse_hits={reuse_hits};reuse_rate={reuse_rate:.1f}]"
    )


def _parse_metrics_blob(message: str) -> Dict[str, float]:
    out: Dict[str, float] = {}
    text = str(message or "")
    m = METRICS_BLOB_RE.search(text)
    if not m:
        return out
    for key, raw in METRICS_KV_RE.findall(m.group(1)):
        k = str(key).strip()
        v = str(raw).strip().rstrip("%")
        if not k:
            continue
        try:
            if "." in v:
                out[k] = float(v)
            else:
                out[k] = float(int(v))
        except Exception:
            continue
    return out


def _run_metrics_from_row(row: Dict[str, Any]) -> Dict[str, Any]:
    started = int(row.get("started_at", 0) or 0)
    finished = int(row.get("finished_at", 0) or 0) if row.get("finished_at") is not None else 0
    duration_s = max(0, finished - started) if started and finished else None
    parsed = _parse_metrics_blob(str(row.get("message") or ""))
    done = max(0, int(row.get("global_done", 0) or int(parsed.get("done", 0) or 0)))
    total = max(0, int(row.get("global_total", 0) or int(parsed.get("total", 0) or 0)))
    cache_hits = max(0, int(parsed.get("cache_hits", 0) or 0))
    tm_hits = max(0, int(parsed.get("tm_hits", 0) or 0))
    reuse_hits = max(0, int(parsed.get("reuse_hits", cache_hits + tm_hits) or 0))
    reuse_rate = float(parsed.get("reuse_rate", 0.0) or 0.0)
    if total > 0 and reuse_rate <= 0.0 and reuse_hits > 0:
        reuse_rate = (reuse_hits / total) * 100.0
    if duration_s is None:
        dur_alt = int(parsed.get("dur_s", 0) or 0)
        duration_s = dur_alt if dur_alt > 0 else None
    return {
        "duration_s": duration_s,
        "done": done,
        "total": total,
        "cache_hits": cache_hits,
        "tm_hits": tm_hits,
        "reuse_hits": reuse_hits,
        "reuse_rate": round(reuse_rate, 1),
    }


def _serialize_run(row: Any) -> Dict[str, Any]:
    r = dict(row)
    out = {
        "id": int(r.get("id", 0) or 0),
        "project_id": int(r.get("project_id", 0) or 0),
        "step": str(r.get("step") or "-"),
        "status": _normalize_stage_status(str(r.get("status") or "none")),
        "command_text": str(r.get("command_text") or ""),
        "started_at": int(r.get("started_at", 0) or 0),
        "finished_at": int(r.get("finished_at", 0) or 0) if r.get("finished_at") is not None else None,
        "global_done": int(r.get("global_done", 0) or 0),
        "global_total": int(r.get("global_total", 0) or 0),
        "message": str(r.get("message") or ""),
    }
    out["metrics"] = _run_metrics_from_row(out)
    return out


def _counts(rows: List[Any]) -> Dict[str, int]:
    c = {"idle": 0, "pending": 0, "running": 0, "error": 0}
    for r in rows:
        raw = str(r["status"] or "idle")
        if raw == "deleted":
            continue
        st = _normalize_project_status(raw)
        if st == "ok":
            st = "idle"
        c[st] = c.get(st, 0) + 1
    return c


def _profile_settings(row: Optional[Any]) -> Dict[str, Any]:
    if row is None:
        return {}
    try:
        raw = json.loads(str(row["settings_json"]))
        return raw if isinstance(raw, dict) else {}
    except Exception:
        return {}


def _stage_payload(stage: Any) -> Dict[str, Any]:
    if not isinstance(stage, dict):
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
    return {
        "status": _normalize_stage_status(str(stage.get("status") or "none")),
        "done": int(stage.get("done", 0) or 0),
        "total": int(stage.get("total", 0) or 0),
        "message": str(stage.get("message") or ""),
        "started_at": int(stage.get("started_at", 0) or 0),
        "finished_at": int(stage.get("finished_at", 0) or 0),
        "updated_at": int(stage.get("updated_at", 0) or 0),
        "is_complete": bool(stage.get("is_complete", False)),
    }


def _project_payload(db: ProjectDB, row: Any) -> Dict[str, Any]:
    data = dict(row)
    data["status"] = _normalize_project_status(str(row["status"] or "idle"))
    pt = int(row["profile_translate_id"]) if row["profile_translate_id"] is not None else None
    pe = int(row["profile_edit_id"]) if row["profile_edit_id"] is not None else None
    rt = db.get_profile(pt) if pt is not None else None
    re = db.get_profile(pe) if pe is not None else None
    data["profile_translate_name"] = str(rt["name"]) if rt else ""
    data["profile_edit_name"] = str(re["name"]) if re else ""
    data["step_values"] = {
        "translate": {
            "output": str(row["output_translate_epub"] or ""),
            "prompt": str(row["prompt_translate"] or ""),
            "cache": str(row["cache_translate_path"] or ""),
            "profile_id": pt,
            "profile_name": data["profile_translate_name"],
        },
        "edit": {
            "output": str(row["output_edit_epub"] or ""),
            "prompt": str(row["prompt_edit"] or ""),
            "cache": str(row["cache_edit_path"] or ""),
            "profile_id": pe,
            "profile_name": data["profile_edit_name"],
        },
    }
    summary = None
    if isinstance(row, dict) and {"book", "translate", "edit", "next_action"} <= set(row.keys()):
        summary = row
    else:
        rid = int(row["id"])
        summary = db.get_project_with_stage_summary(rid)
    if summary is not None:
        data["book"] = str(summary.get("book") or "-")
        data["translate"] = _stage_payload(summary.get("translate"))
        data["edit"] = _stage_payload(summary.get("edit"))
        data["next_action"] = str(summary.get("next_action") or "translate")
    else:
        data["book"] = "-"
        data["translate"] = _stage_payload(None)
        data["edit"] = _stage_payload(None)
        data["next_action"] = "translate"
    return data


def _apply_profile_to_state(base: UiState, settings: Dict[str, Any]) -> UiState:
    out = base.model_dump()
    for k in PROFILE_KEYS:
        if k in settings:
            out[k] = settings[k]
    return UiState(**out)


def _state_from_project(db: ProjectDB, row: Any, base: UiState, mode_override: Optional[str] = None) -> UiState:
    m = _step(mode_override or str(row["active_step"] or "translate"))
    s = UiState(**base.model_dump())
    s.mode = m
    s.tm_project_id = int(row["id"])
    s.input_epub = str(row["input_epub"] or "")
    s.glossary = str(row["glossary_path"] or "")
    s.source_lang = str(row["source_lang"] or s.source_lang or "en").strip().lower()
    s.target_lang = str(row["target_lang"] or s.target_lang or "pl").strip().lower()
    if m == "edit":
        s.output_epub = str(row["output_edit_epub"] or "")
        s.prompt = str(row["prompt_edit"] or "")
        s.cache = str(row["cache_edit_path"] or "")
        pid = int(row["profile_edit_id"]) if row["profile_edit_id"] is not None else None
    else:
        s.output_epub = str(row["output_translate_epub"] or "")
        s.prompt = str(row["prompt_translate"] or "")
        s.cache = str(row["cache_translate_path"] or "")
        pid = int(row["profile_translate_id"]) if row["profile_translate_id"] is not None else None
    if pid is not None:
        p = db.get_profile(pid)
        if p is not None:
            s = _apply_profile_to_state(s, _profile_settings(p))
            s.mode = m
            s.tm_project_id = int(row["id"])
            s.input_epub = str(row["input_epub"] or "")
            s.glossary = str(row["glossary_path"] or "")
            s.source_lang = str(row["source_lang"] or s.source_lang or "en").strip().lower()
            s.target_lang = str(row["target_lang"] or s.target_lang or "pl").strip().lower()
            if m == "edit":
                s.output_epub = str(row["output_edit_epub"] or "")
                s.prompt = str(row["prompt_edit"] or "")
                s.cache = str(row["cache_edit_path"] or "")
            else:
                s.output_epub = str(row["output_translate_epub"] or "")
                s.prompt = str(row["prompt_translate"] or "")
                s.cache = str(row["cache_translate_path"] or "")
    if not s.prompt.strip():
        s.prompt = _state_path_prompt(m)
    return s


def _sanitize_project_values(values: Dict[str, Any]) -> Dict[str, Any]:
    out: Dict[str, Any] = {}
    for k, v in values.items():
        if k not in PROJECT_SAVE_KEYS:
            continue
        if k in {"profile_translate_id", "profile_edit_id"}:
            if v in ("", None, "null"):
                out[k] = None
            else:
                out[k] = int(v)
        elif k in {"source_lang", "target_lang"}:
            out[k] = str(v or "").strip().lower()
        elif k == "active_step":
            out[k] = _step(str(v))
        else:
            out[k] = str(v or "")
    return out


def _serialize_profile(state: UiState) -> Dict[str, Any]:
    return {k: state.model_dump().get(k) for k in PROFILE_KEYS}


def _find_source_epub(name: str, preferred: str) -> Path:
    if preferred.strip():
        return Path(preferred.strip())
    for d in [BASE_DIR, TK_DIR]:
        hits = sorted(d.glob("*.epub"))
        if hits:
            return hits[0]
    return BASE_DIR / f"{name}.epub"


def _default_project_values(db: ProjectDB, source: Path, src_lang: str, tgt_lang: str) -> Dict[str, Any]:
    stem = source.stem or "book"
    src = (src_lang or "en").strip().lower()
    tgt = (tgt_lang or "pl").strip().lower()
    prompt_t = _state_path_prompt("translate")
    prompt_e = _state_path_prompt("edit") or prompt_t
    profile_t = None
    profile_e = None
    for p in db.list_profiles():
        if p["name"] == "Google-fast":
            profile_t = int(p["id"])
        if p["name"] == "Ollama-quality":
            profile_e = int(p["id"])
    return {
        "input_epub": str(source),
        "output_translate_epub": str(source.with_name(f"{stem}_{tgt}.epub")),
        "output_edit_epub": str(source.with_name(f"{stem}_{tgt}_redakcja.epub")),
        "prompt_translate": prompt_t,
        "prompt_edit": prompt_e,
        "glossary_path": "",
        "cache_translate_path": str(source.with_name(f"cache_{stem}.jsonl")),
        "cache_edit_path": str(source.with_name(f"cache_{stem}_redakcja.jsonl")),
        "profile_translate_id": profile_t,
        "profile_edit_id": profile_e or profile_t,
        "active_step": "translate",
        "status": "idle",
        "source_lang": src,
        "target_lang": tgt,
    }


def _finish_db_run(meta: Optional[Dict[str, Any]], code: int, run_stats: Optional[Dict[str, Any]] = None) -> None:
    if not meta:
        return
    if meta.get("run_id") is None or meta.get("db_path") is None:
        return
    db = ProjectDB(Path(str(meta["db_path"])))
    try:
        status = "ok" if int(code) == 0 else "error"
        stats = _finalize_runtime_stats(run_stats or _new_runtime_stats(), None)
        msg_prefix = "RUN OK" if status == "ok" else f"RUN ERROR (exit={code})"
        msg = f"{msg_prefix} | {_metrics_blob(stats)}"
        db.finish_run(
            int(meta["run_id"]),
            status=status,
            message=msg,
            global_done=int(stats.get("done", 0) or 0),
            global_total=int(stats.get("total", 0) or 0),
        )
    finally:
        db.close()


class RunManager:
    def __init__(self) -> None:
        self.lock = threading.Lock()
        self.proc: Optional[subprocess.Popen[str]] = None
        self.mode = "idle"
        self.started_at: Optional[float] = None
        self.exit_code: Optional[int] = None
        self.log: List[str] = []
        self.max_log = 8000
        self.meta: Optional[Dict[str, Any]] = None
        self.run_stats: Dict[str, Any] = _new_runtime_stats()
        self._tm_metric_lines: set[str] = set()

    def append(self, line: str) -> None:
        with self.lock:
            self.log.append(line)
            if len(self.log) > self.max_log:
                del self.log[: len(self.log) - self.max_log]

    def is_running(self) -> bool:
        with self.lock:
            return self.proc is not None

    def start(self, cmd: List[str], env: Dict[str, str], mode: str, meta: Optional[Dict[str, Any]]) -> None:
        with self.lock:
            if self.proc is not None:
                raise RuntimeError("Process already running")
            self.mode = mode
            self.started_at = time.time()
            self.exit_code = None
            self.log.clear()
            self.log.append("=== START ===\n")
            self.log.append("Command: " + " ".join(cmd) + "\n\n")
            self.meta = dict(meta) if meta else None
            self.run_stats = _new_runtime_stats()
            self._tm_metric_lines.clear()
            self.proc = subprocess.Popen(
                cmd,
                cwd=str(BASE_DIR),
                env=env,
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
                text=True,
                encoding="utf-8",
                errors="replace",
                bufsize=1,
            )
        threading.Thread(target=self._reader, daemon=True).start()

    def _reader(self) -> None:
        with self.lock:
            p = self.proc
        if p is None or p.stdout is None:
            return
        local_meta: Optional[Dict[str, Any]] = None
        local_stats: Dict[str, Any] = _new_runtime_stats()
        local_started_at: Optional[float] = None
        try:
            for line in p.stdout:
                self.append(line)
                with self.lock:
                    _consume_runtime_log_line(self.run_stats, line, self._tm_metric_lines)
            code = p.wait()
            self.append(f"\n=== FINISH (exit={code}) ===\n")
            with self.lock:
                self.exit_code = code
                self.proc = None
                self.mode = "idle"
                local_meta = dict(self.meta) if self.meta else None
                local_stats = dict(self.run_stats)
                local_started_at = self.started_at
                self.started_at = None
                self.run_stats = _new_runtime_stats()
                self._tm_metric_lines.clear()
                self.meta = None
            _finish_db_run(local_meta, code, _finalize_runtime_stats(local_stats, local_started_at))
        except Exception as e:
            self.append(f"\n[runner-error] {e}\n")
            with self.lock:
                self.exit_code = -1
                self.proc = None
                self.mode = "idle"
                local_meta = dict(self.meta) if self.meta else None
                local_stats = dict(self.run_stats)
                local_started_at = self.started_at
                self.started_at = None
                self.run_stats = _new_runtime_stats()
                self._tm_metric_lines.clear()
                self.meta = None
            _finish_db_run(local_meta, -1, _finalize_runtime_stats(local_stats, local_started_at))

    def stop(self) -> bool:
        with self.lock:
            p = self.proc
        if p is None:
            return False
        try:
            p.terminate()
            self.append("\n[stop] terminate sent\n")
            return True
        except Exception as e:
            self.append(f"\n[stop-error] {e}\n")
            return False

    def snapshot(self, tail: int = 400) -> Dict[str, Any]:
        with self.lock:
            stats = _finalize_runtime_stats(self.run_stats, self.started_at)
            return {
                "running": self.proc is not None,
                "mode": self.mode,
                "started_at": self.started_at,
                "exit_code": self.exit_code,
                "log": "".join(self.log[-tail:]),
                "log_lines": len(self.log),
                "run_meta": dict(self.meta) if self.meta else None,
                "run_stats": stats,
            }


RUNNER = RunManager()


def _start_run(state: UiState) -> Dict[str, Any]:
    s = UiState(**state.model_dump())
    s.mode = _step(s.mode)
    if RUNNER.is_running():
        raise HTTPException(status_code=409, detail="Process already running")
    key = s.google_api_key.strip() or os.environ.get(GOOGLE_API_KEY_ENV, "").strip() if s.provider == "google" else ""
    try:
        _validate_state(s, google_key=key)
    except Exception as e:
        raise HTTPException(status_code=400, detail=str(e))
    _save_state(s)
    cmd = _cmd_run(s)
    env = {**os.environ}
    if s.provider == "google":
        if not key:
            raise HTTPException(status_code=400, detail="Google API key is missing")
        env[GOOGLE_API_KEY_ENV] = key
    meta: Optional[Dict[str, Any]] = None
    run_id: Optional[int] = None
    if s.tm_project_id is not None:
        path = _db_path(s.tm_db)
        db = ProjectDB(path)
        try:
            run_id = db.start_run(int(s.tm_project_id), s.mode, " ".join(cmd))
        except Exception as e:
            db.close()
            raise HTTPException(status_code=400, detail=f"Cannot start DB run tracking: {e}")
        db.close()
        meta = {"db_path": str(path), "run_id": int(run_id), "project_id": int(s.tm_project_id), "mode": s.mode}
    try:
        RUNNER.start(cmd, env, s.mode, meta)
    except Exception as e:
        if meta:
            _finish_db_run(meta, -1)
        raise HTTPException(status_code=409, detail=str(e))
    return {"ok": True, "mode": s.mode, "project_id": s.tm_project_id, "run_id": run_id}


@app.get("/health")
def health() -> Dict[str, Any]:
    st = _load_state()
    path = _db_path(st.tm_db)
    active = None
    try:
        db = ProjectDB(path)
        active = db.get_setting("active_project_id", None)
        db.close()
    except Exception:
        pass
    return {"status": "ok", "running": RUNNER.is_running(), "db_path": str(path), "active_project_id": active}


@app.get("/version")
def version() -> Dict[str, Any]:
    return {"version": APP_VERSION}


@app.get("/config")
def get_config() -> Dict[str, Any]:
    return _load_state().model_dump()


@app.post("/config")
def set_config(state: UiState) -> Dict[str, Any]:
    _save_state(state)
    return {"ok": True}


@app.get("/projects")
def projects_list() -> Dict[str, Any]:
    db, _ = _open_db()
    try:
        rows = db.list_projects_with_stage_summary()
        out = []
        for r in rows:
            if str(r["status"] or "idle") == "deleted":
                continue
            out.append(
                {
                    "id": int(r["id"]),
                    "name": str(r["name"] or ""),
                    "status": _normalize_project_status(str(r["status"] or "idle")),
                    "active_step": _step(str(r["active_step"] or "translate")),
                    "input_epub": str(r["input_epub"] or ""),
                    "source_lang": str(r["source_lang"] or "en"),
                    "target_lang": str(r["target_lang"] or "pl"),
                    "updated_at": int(r["updated_at"] or 0),
                    "book": str(r.get("book") or "-"),
                    "translate": _stage_payload(r.get("translate")),
                    "edit": _stage_payload(r.get("edit")),
                    "next_action": str(r.get("next_action") or "translate"),
                }
            )
        return {"projects": out, "counts": _counts(rows), "active_project_id": db.get_setting("active_project_id", None)}
    finally:
        db.close()


@app.post("/projects/create")
def projects_create(req: ProjectCreateRequest) -> Dict[str, Any]:
    name = req.name.strip()
    if not name:
        raise HTTPException(status_code=400, detail="Project name is required")
    db, _ = _open_db()
    try:
        vals = _default_project_values(db, _find_source_epub(name, req.source_epub), req.source_lang, req.target_lang)
        try:
            pid = db.create_project(name, vals)
        except sqlite3.IntegrityError:
            raise HTTPException(status_code=409, detail=f"Project '{name}' already exists")
        db.set_setting("active_project_id", int(pid))
        row = db.get_project(int(pid))
        if row is None:
            raise HTTPException(status_code=500, detail="Project created but cannot be loaded")
        st = _state_from_project(db, row, _load_state(), mode_override="translate")
        _save_state(st)
        return {
            "ok": True,
            "project": _project_payload(db, row),
            "state": st.model_dump(),
            "runs": [_serialize_run(r) for r in db.recent_runs(int(pid), limit=20)],
            "counts": _counts(db.list_projects()),
        }
    finally:
        db.close()


@app.post("/projects/select")
def projects_select(req: ProjectSelectRequest) -> Dict[str, Any]:
    db, _ = _open_db()
    try:
        row = db.get_project(int(req.project_id))
        if row is None or str(row["status"] or "") == "deleted":
            raise HTTPException(status_code=404, detail="Project not found")
        m = _step(req.mode or str(row["active_step"] or "translate"))
        if m != str(row["active_step"] or "translate"):
            db.update_project(int(req.project_id), {"active_step": m})
            row = db.get_project(int(req.project_id))
            if row is None:
                raise HTTPException(status_code=404, detail="Project not found")
        st = _state_from_project(db, row, _load_state(), mode_override=m)
        db.set_setting("active_project_id", int(req.project_id))
        _save_state(st)
        return {
            "ok": True,
            "project": _project_payload(db, row),
            "state": st.model_dump(),
            "runs": [_serialize_run(r) for r in db.recent_runs(int(req.project_id), limit=20)],
            "counts": _counts(db.list_projects()),
        }
    finally:
        db.close()


@app.post("/projects/{project_id}/save")
def projects_save(project_id: int, req: ProjectSaveRequest) -> Dict[str, Any]:
    try:
        vals = _sanitize_project_values(req.values)
    except Exception as e:
        raise HTTPException(status_code=400, detail=str(e))
    if not vals:
        raise HTTPException(status_code=400, detail="No valid fields to save")
    db, _ = _open_db()
    try:
        row = db.get_project(int(project_id))
        if row is None or str(row["status"] or "") == "deleted":
            raise HTTPException(status_code=404, detail="Project not found")
        db.update_project(int(project_id), vals)
        saved = db.get_project(int(project_id))
        if saved is None:
            raise HTTPException(status_code=404, detail="Project not found")
        return {"ok": True, "project": _project_payload(db, saved)}
    finally:
        db.close()


@app.post("/projects/{project_id}/delete")
def projects_delete(project_id: int, req: ProjectDeleteRequest) -> Dict[str, Any]:
    db, _ = _open_db()
    try:
        row = db.get_project(int(project_id))
        if row is None:
            raise HTTPException(status_code=404, detail="Project not found")
        db.delete_project(int(project_id), hard=bool(req.hard))
        active = db.get_setting("active_project_id", None)
        if isinstance(active, int) and active == int(project_id):
            db.set_setting("active_project_id", None)
        return {"ok": True, "counts": _counts(db.list_projects())}
    finally:
        db.close()


@app.get("/profiles")
def profiles_list() -> Dict[str, Any]:
    db, _ = _open_db()
    try:
        return {
            "profiles": [
                {
                    "id": int(r["id"]),
                    "name": str(r["name"] or ""),
                    "is_builtin": int(r["is_builtin"] or 0),
                    "updated_at": int(r["updated_at"] or 0),
                }
                for r in db.list_profiles()
            ]
        }
    finally:
        db.close()


@app.post("/profiles/create")
def profiles_create(req: ProfileCreateRequest) -> Dict[str, Any]:
    name = req.name.strip()
    if not name:
        raise HTTPException(status_code=400, detail="Profile name is required")
    settings = req.settings if isinstance(req.settings, dict) else _serialize_profile(req.state or _load_state())
    db, _ = _open_db()
    try:
        try:
            pid = db.create_profile(name, settings, is_builtin=int(req.is_builtin))
        except sqlite3.IntegrityError:
            raise HTTPException(status_code=409, detail=f"Profile '{name}' already exists")
        row = db.get_profile(int(pid))
        if row is None:
            raise HTTPException(status_code=500, detail="Profile created but cannot be loaded")
        return {
            "ok": True,
            "profile": {
                "id": int(row["id"]),
                "name": str(row["name"] or ""),
                "is_builtin": int(row["is_builtin"] or 0),
                "settings": _profile_settings(row),
            },
        }
    finally:
        db.close()


@app.get("/profiles/{profile_id}")
def profiles_get(profile_id: int) -> Dict[str, Any]:
    db, _ = _open_db()
    try:
        row = db.get_profile(int(profile_id))
        if row is None:
            raise HTTPException(status_code=404, detail="Profile not found")
        return {
            "profile": {
                "id": int(row["id"]),
                "name": str(row["name"] or ""),
                "is_builtin": int(row["is_builtin"] or 0),
                "settings": _profile_settings(row),
            }
        }
    finally:
        db.close()


@app.get("/runs/recent")
def runs_recent(project_id: int, limit: int = 20) -> Dict[str, Any]:
    db, _ = _open_db()
    try:
        lim = max(1, min(int(limit), 200))
        return {"runs": [_serialize_run(r) for r in db.recent_runs(int(project_id), limit=lim)]}
    finally:
        db.close()


@app.get("/queue/counts")
def queue_counts() -> Dict[str, Any]:
    db, _ = _open_db()
    try:
        return {"counts": _counts(db.list_projects())}
    finally:
        db.close()


@app.get("/queue/next")
def queue_next() -> Dict[str, Any]:
    db, _ = _open_db()
    try:
        row = db.get_next_pending_project()
        return {"project": None if row is None else _project_payload(db, row)}
    finally:
        db.close()


@app.post("/queue/mark")
def queue_mark(req: QueueMarkRequest) -> Dict[str, Any]:
    db, _ = _open_db()
    try:
        row = db.get_project(int(req.project_id))
        if row is None or str(row["status"] or "") == "deleted":
            raise HTTPException(status_code=404, detail="Project not found")
        db.mark_project_pending(int(req.project_id), _step(req.step))
        upd = db.get_project(int(req.project_id))
        if upd is None:
            raise HTTPException(status_code=404, detail="Project not found")
        return {"ok": True, "project": _project_payload(db, upd), "counts": _counts(db.list_projects())}
    finally:
        db.close()


@app.post("/queue/run-next")
def queue_run_next(req: QueueRunNextRequest) -> Dict[str, Any]:
    base = req.state or _load_state()
    db = ProjectDB(_db_path(base.tm_db))
    try:
        nxt = db.get_next_pending_project()
        if nxt is None:
            return {"ok": False, "message": "Queue empty"}
        state = _state_from_project(db, nxt, base)
        db.set_setting("active_project_id", int(nxt["id"]))
        payload = _project_payload(db, nxt)
    finally:
        db.close()
    started = _start_run(state)
    started["project"] = payload
    return started


@app.post("/run/start")
def run_start(req: RunRequest) -> Dict[str, Any]:
    return _start_run(req.state)


@app.post("/run/validate")
def run_validate(req: ValidateRequest) -> Dict[str, Any]:
    if RUNNER.is_running():
        raise HTTPException(status_code=409, detail="Process already running")
    p = Path(req.epub_path.strip()) if req.epub_path.strip() else None
    if p is None or not p.exists():
        raise HTTPException(status_code=400, detail="epub_path must exist")
    cmd = _cmd_validate(str(p), req.tags.strip())
    meta: Optional[Dict[str, Any]] = None
    if req.project_id is not None:
        dbp = _db_path(req.tm_db)
        db = ProjectDB(dbp)
        try:
            rid = db.start_run(int(req.project_id), "validate", " ".join(cmd))
        except Exception as e:
            db.close()
            raise HTTPException(status_code=400, detail=f"Cannot start validation tracking: {e}")
        db.close()
        meta = {"db_path": str(dbp), "run_id": int(rid), "project_id": int(req.project_id), "mode": "validate"}
    try:
        RUNNER.start(cmd, {**os.environ}, "validate", meta)
    except Exception as e:
        if meta:
            _finish_db_run(meta, -1)
        raise HTTPException(status_code=409, detail=str(e))
    return {"ok": True}


@app.get("/run/status")
def run_status() -> Dict[str, Any]:
    return RUNNER.snapshot(tail=600)


@app.post("/run/stop")
def run_stop() -> Dict[str, Any]:
    return {"ok": RUNNER.stop()}


@app.get("/models/ollama")
def models_ollama(host: str = OLLAMA_HOST_DEFAULT) -> Dict[str, Any]:
    return {"models": list_ollama_models(host=host, timeout_s=20)}


@app.get("/models/google")
def models_google(api_key: str) -> Dict[str, Any]:
    try:
        return {"models": list_google_models(api_key=api_key, timeout_s=20)}
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
