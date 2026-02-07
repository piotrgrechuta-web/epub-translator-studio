from __future__ import annotations

import json
import os
import subprocess
import sys
import threading
import time
from pathlib import Path
from typing import Any, Dict, List, Optional

from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel

BASE_DIR = Path(__file__).resolve().parent
REPO_ROOT = BASE_DIR.parents[1]
TKINTER_DIR = REPO_ROOT / "project-tkinter"
if str(TKINTER_DIR) not in sys.path:
    sys.path.insert(0, str(TKINTER_DIR))

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

SUPPORTED_TEXT_LANGS = set(DEFAULT_SUPPORTED_TEXT_LANGS)
ENGINE_DIR = BASE_DIR / "engine"
CANONICAL_TRANSLATOR = TKINTER_DIR / "tlumacz_ollama.py"
TRANSLATOR = CANONICAL_TRANSLATOR if CANONICAL_TRANSLATOR.exists() else (ENGINE_DIR / "tlumacz_ollama.py")
STATE_FILE = BASE_DIR / "ui_state.json"
DEFAULT_DB = BASE_DIR / "translator_studio.db"

app = FastAPI(title="Translator Studio API", version="0.2.0")
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


class UiState(BaseModel):
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


class RunManager:
    def __init__(self) -> None:
        self._lock = threading.Lock()
        self.proc: Optional[subprocess.Popen[str]] = None
        self.mode: str = "idle"
        self.started_at: Optional[float] = None
        self.exit_code: Optional[int] = None
        self.log: List[str] = []
        self.max_log = 8000

    def _append(self, line: str) -> None:
        with self._lock:
            self.log.append(line)
            if len(self.log) > self.max_log:
                del self.log[: len(self.log) - self.max_log]

    def is_running(self) -> bool:
        with self._lock:
            return self.proc is not None

    def start(self, cmd: List[str], env: Dict[str, str], mode: str) -> None:
        with self._lock:
            if self.proc is not None:
                raise RuntimeError("Process already running")
            self.mode = mode
            self.started_at = time.time()
            self.exit_code = None
            self.log.clear()
            self.log.append("=== START ===\n")
            self.log.append("Command: " + " ".join(cmd) + "\n\n")
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
        p: Optional[subprocess.Popen[str]] = None
        with self._lock:
            p = self.proc
        if p is None or p.stdout is None:
            return
        try:
            for line in p.stdout:
                self._append(line)
            code = p.wait()
            self._append(f"\n=== FINISH (exit={code}) ===\n")
            with self._lock:
                self.exit_code = code
                self.proc = None
                self.mode = "idle"
        except Exception as e:
            self._append(f"\n[runner-error] {e}\n")
            with self._lock:
                self.exit_code = -1
                self.proc = None
                self.mode = "idle"

    def stop(self) -> bool:
        with self._lock:
            p = self.proc
        if p is None:
            return False
        try:
            p.terminate()
            self._append("\n[stop] terminate sent\n")
            return True
        except Exception as e:
            self._append(f"\n[stop-error] {e}\n")
            return False

    def snapshot(self, tail: int = 400) -> Dict[str, Any]:
        with self._lock:
            lines = self.log[-tail:]
            return {
                "running": self.proc is not None,
                "mode": self.mode,
                "started_at": self.started_at,
                "exit_code": self.exit_code,
                "log": "".join(lines),
                "log_lines": len(self.log),
            }


RUNNER = RunManager()


def _load_state() -> UiState:
    if not STATE_FILE.exists():
        d = UiState()
        for p in [TKINTER_DIR / "prompt.txt", ENGINE_DIR / "prompt.txt"]:
            if p.exists():
                d.prompt = str(p)
                break
        return d
    try:
        raw = json.loads(STATE_FILE.read_text(encoding="utf-8"))
        if isinstance(raw, dict):
            return UiState(**raw)
    except Exception:
        pass
    return UiState()


def _save_state(state: UiState) -> None:
    STATE_FILE.write_text(json.dumps(state.model_dump(), ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def _translator_prefix() -> List[str]:
    if not TRANSLATOR.exists():
        raise RuntimeError(f"Missing translator script: {TRANSLATOR}")
    return ["python", "-u", str(TRANSLATOR)]


def _to_run_options(s: UiState) -> RunOptions:
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
        tm_db=s.tm_db.strip() or str(DEFAULT_DB),
        tm_project_id=s.tm_project_id,
    )


def _validate_state(s: UiState, google_api_key: str = "") -> None:
    err = validate_run_options(
        _to_run_options(s),
        google_api_key=google_api_key,
        supported_text_langs=SUPPORTED_TEXT_LANGS,
    )
    if err:
        raise ValueError(err)


def _build_run_cmd(s: UiState) -> List[str]:
    return build_run_command(_translator_prefix(), _to_run_options(s), tm_fuzzy_threshold="0.92")


@app.get("/health")
def health() -> Dict[str, Any]:
    return {"status": "ok", "running": RUNNER.is_running()}


@app.get("/config")
def get_config() -> Dict[str, Any]:
    return _load_state().model_dump()


@app.post("/config")
def set_config(state: UiState) -> Dict[str, Any]:
    _save_state(state)
    return {"ok": True}


@app.post("/run/start")
def run_start(req: RunRequest) -> Dict[str, Any]:
    key = ""
    if req.state.provider == "google":
        key = req.state.google_api_key.strip() or os.environ.get(GOOGLE_API_KEY_ENV, "").strip()
    try:
        _validate_state(req.state, google_api_key=key)
    except Exception as e:
        raise HTTPException(status_code=400, detail=str(e))
    _save_state(req.state)
    cmd = _build_run_cmd(req.state)
    env = {**os.environ}
    if req.state.provider == "google":
        if not key:
            raise HTTPException(status_code=400, detail="Google API key is missing")
        env[GOOGLE_API_KEY_ENV] = key
    try:
        RUNNER.start(cmd, env=env, mode="translate")
    except Exception as e:
        raise HTTPException(status_code=409, detail=str(e))
    return {"ok": True}


@app.post("/run/validate")
def run_validate(req: ValidateRequest) -> Dict[str, Any]:
    p = Path(req.epub_path.strip()) if req.epub_path.strip() else None
    if p is None or not p.exists():
        raise HTTPException(status_code=400, detail="epub_path must exist")
    cmd = build_validation_command(_translator_prefix(), str(p), req.tags.strip())
    try:
        RUNNER.start(cmd, env={**os.environ}, mode="validate")
    except Exception as e:
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
