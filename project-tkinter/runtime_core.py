#!/usr/bin/env python3
# -*- coding: utf-8 -*-

from __future__ import annotations

import asyncio
import os
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Dict, List, Optional, Sequence, Set

import requests

GOOGLE_API_KEY_ENV = "GOOGLE_API_KEY"
OLLAMA_HOST_DEFAULT = os.environ.get("OLLAMA_HOST", "http://127.0.0.1:11434")
DEFAULT_SUPPORTED_TEXT_LANGS: Set[str] = {"en", "pl", "de", "fr", "es", "pt", "ro"}


@dataclass
class RunOptions:
    provider: str
    input_epub: str
    output_epub: str
    prompt: str
    model: str
    batch_max_segs: str
    batch_max_chars: str
    sleep: str
    timeout: str
    attempts: str
    backoff: str
    temperature: str
    num_ctx: str
    num_predict: str
    tags: str
    checkpoint: str
    debug_dir: str
    source_lang: str
    target_lang: str
    ollama_host: str = OLLAMA_HOST_DEFAULT
    cache: str = ""
    use_cache: bool = True
    glossary: str = ""
    use_glossary: bool = True
    tm_db: str = ""
    tm_project_id: Optional[int] = None
    run_step: str = "translate"
    context_window: str = "0"
    context_neighbor_max_chars: str = "180"
    context_segment_max_chars: str = "1200"
    io_concurrency: str = "1"


@dataclass
class ProviderHealthStatus:
    provider: str
    state: str  # ok | fail | skip
    latency_ms: int
    model_count: int
    detail: str


def list_ollama_models(host: str, timeout_s: int = 20) -> List[str]:
    url = host.rstrip("/") + "/api/tags"
    r = requests.get(url, timeout=timeout_s)
    r.raise_for_status()
    data = r.json()
    out: List[str] = []
    for m in data.get("models", []) or []:
        name = m.get("name")
        if isinstance(name, str) and name.strip():
            out.append(name.strip())
    return sorted(set(out))


def list_google_models(api_key: str, timeout_s: int = 20) -> List[str]:
    key = (api_key or "").strip()
    if not key:
        raise ValueError("api_key is required")
    url = "https://generativelanguage.googleapis.com/v1beta/models"
    headers = {"x-goog-api-key": key}
    r = requests.get(url, headers=headers, timeout=timeout_s)
    r.raise_for_status()
    data = r.json()

    out: List[str] = []
    for m in data.get("models", []) or []:
        name = m.get("name")
        methods = m.get("supportedGenerationMethods") or []
        ok = isinstance(name, str) and isinstance(methods, list) and any(
            str(x).lower() == "generatecontent" for x in methods
        )
        if ok and name.strip():
            out.append(name.strip())
    return sorted(set(out))


def _short_error(err: Exception, max_len: int = 240) -> str:
    msg = f"{type(err).__name__}: {err}".strip()
    if len(msg) <= max_len:
        return msg
    return msg[: max_len - 3] + "..."


def check_ollama_health(host: str, timeout_s: int = 10) -> ProviderHealthStatus:
    started = time.perf_counter()
    try:
        models = list_ollama_models(host, timeout_s=timeout_s)
        ms = int((time.perf_counter() - started) * 1000.0)
        return ProviderHealthStatus(
            provider="ollama",
            state="ok",
            latency_ms=ms,
            model_count=len(models),
            detail=f"host={host.rstrip('/')}/api/tags",
        )
    except Exception as e:
        ms = int((time.perf_counter() - started) * 1000.0)
        return ProviderHealthStatus(
            provider="ollama",
            state="fail",
            latency_ms=ms,
            model_count=0,
            detail=_short_error(e),
        )


def check_google_health(api_key: str, timeout_s: int = 10) -> ProviderHealthStatus:
    key = (api_key or "").strip()
    if not key:
        return ProviderHealthStatus(
            provider="google",
            state="skip",
            latency_ms=0,
            model_count=0,
            detail=f"missing API key ({GOOGLE_API_KEY_ENV})",
        )
    started = time.perf_counter()
    try:
        models = list_google_models(key, timeout_s=timeout_s)
        ms = int((time.perf_counter() - started) * 1000.0)
        return ProviderHealthStatus(
            provider="google",
            state="ok",
            latency_ms=ms,
            model_count=len(models),
            detail="models endpoint",
        )
    except Exception as e:
        ms = int((time.perf_counter() - started) * 1000.0)
        return ProviderHealthStatus(
            provider="google",
            state="fail",
            latency_ms=ms,
            model_count=0,
            detail=_short_error(e),
        )


async def gather_provider_health_async(
    *,
    ollama_host: str,
    google_api_key: str,
    timeout_s: int = 10,
    include_ollama: bool = True,
    include_google: bool = True,
) -> Dict[str, ProviderHealthStatus]:
    tasks: Dict[str, "asyncio.Task[ProviderHealthStatus]"] = {}
    if include_ollama:
        tasks["ollama"] = asyncio.create_task(
            asyncio.to_thread(check_ollama_health, ollama_host, timeout_s)
        )
    if include_google:
        tasks["google"] = asyncio.create_task(
            asyncio.to_thread(check_google_health, google_api_key, timeout_s)
        )
    out: Dict[str, ProviderHealthStatus] = {}
    for key, task in tasks.items():
        try:
            out[key] = await task
        except Exception as e:
            out[key] = ProviderHealthStatus(
                provider=key,
                state="fail",
                latency_ms=0,
                model_count=0,
                detail=_short_error(e),
            )
    return out


def gather_provider_health(
    *,
    ollama_host: str,
    google_api_key: str,
    timeout_s: int = 10,
    include_ollama: bool = True,
    include_google: bool = True,
) -> Dict[str, ProviderHealthStatus]:
    return asyncio.run(
        gather_provider_health_async(
            ollama_host=ollama_host,
            google_api_key=google_api_key,
            timeout_s=timeout_s,
            include_ollama=include_ollama,
            include_google=include_google,
        )
    )


def validate_run_options(
    opts: RunOptions,
    *,
    google_api_key: str = "",
    supported_text_langs: Optional[Set[str]] = None,
) -> Optional[str]:
    langs = supported_text_langs or DEFAULT_SUPPORTED_TEXT_LANGS
    if opts.provider not in {"ollama", "google"}:
        return "provider must be 'ollama' or 'google'"
    if not opts.input_epub.strip():
        return "input_epub is required"
    if not Path(opts.input_epub.strip()).exists():
        return f"input_epub does not exist: {opts.input_epub}"
    if not opts.output_epub.strip():
        return "output_epub is required"
    if not opts.prompt.strip():
        return "prompt is required"
    if not Path(opts.prompt.strip()).exists():
        return f"prompt file does not exist: {opts.prompt}"
    if not opts.model.strip():
        return "model is required"
    if opts.source_lang.strip().lower() not in langs:
        return "invalid source_lang"
    if opts.target_lang.strip().lower() not in langs:
        return "invalid target_lang"
    if opts.provider == "google" and not (google_api_key or "").strip():
        return f"google api key missing ({GOOGLE_API_KEY_ENV})"
    return None


def build_run_command(
    translator_prefix: Sequence[str],
    opts: RunOptions,
    *,
    tm_fuzzy_threshold: str = "0.92",
) -> List[str]:
    cmd = list(translator_prefix) + [
        opts.input_epub.strip(),
        opts.output_epub.strip(),
        "--prompt",
        opts.prompt.strip(),
        "--provider",
        opts.provider,
        "--model",
        opts.model.strip(),
        "--batch-max-segs",
        opts.batch_max_segs.strip(),
        "--batch-max-chars",
        opts.batch_max_chars.strip(),
        "--sleep",
        opts.sleep.strip().replace(",", "."),
        "--timeout",
        opts.timeout.strip(),
        "--attempts",
        opts.attempts.strip(),
        "--backoff",
        opts.backoff.strip(),
        "--temperature",
        opts.temperature.strip().replace(",", "."),
        "--num-ctx",
        opts.num_ctx.strip(),
        "--num-predict",
        opts.num_predict.strip(),
        "--tags",
        opts.tags.strip(),
        "--checkpoint-every-files",
        opts.checkpoint.strip(),
        "--debug-dir",
        opts.debug_dir.strip() or "debug",
        "--source-lang",
        opts.source_lang.strip().lower(),
        "--target-lang",
        opts.target_lang.strip().lower(),
    ]
    if opts.provider == "ollama":
        cmd += ["--host", (opts.ollama_host.strip() or OLLAMA_HOST_DEFAULT)]
    if opts.use_cache and opts.cache.strip():
        cmd += ["--cache", opts.cache.strip()]
    if opts.use_glossary and opts.glossary.strip():
        cmd += ["--glossary", opts.glossary.strip()]
    else:
        cmd += ["--no-glossary"]
    if opts.tm_db.strip():
        cmd += ["--tm-db", opts.tm_db.strip()]
    if opts.tm_project_id is not None:
        cmd += ["--tm-project-id", str(int(opts.tm_project_id))]
    cmd += ["--run-step", (opts.run_step.strip().lower() or "translate")]
    cmd += ["--tm-fuzzy-threshold", tm_fuzzy_threshold]
    try:
        io_concurrency = max(1, int(str(opts.io_concurrency or "").strip() or "1"))
    except Exception:
        io_concurrency = 1
    if io_concurrency > 1:
        cmd += ["--io-concurrency", str(io_concurrency)]
    try:
        ctx_window = max(0, int(str(opts.context_window or "").strip() or "0"))
    except Exception:
        ctx_window = 0
    if ctx_window > 0:
        cmd += ["--context-window", str(ctx_window)]
        try:
            c_n = max(24, int(str(opts.context_neighbor_max_chars or "").strip() or "180"))
        except Exception:
            c_n = 180
        try:
            c_s = max(80, int(str(opts.context_segment_max_chars or "").strip() or "1200"))
        except Exception:
            c_s = 1200
        cmd += ["--context-neighbor-max-chars", str(c_n)]
        cmd += ["--context-segment-max-chars", str(c_s)]
    return cmd


def build_validation_command(translator_prefix: Sequence[str], epub_path: str, tags: str) -> List[str]:
    return list(translator_prefix) + ["--validate-epub", epub_path, "--tags", tags.strip()]
