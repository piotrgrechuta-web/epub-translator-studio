#!/usr/bin/env python3
# -*- coding: utf-8 -*-

from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path
from typing import List, Optional, Sequence, Set

import requests

GOOGLE_API_KEY_ENV = "GOOGLE_API_KEY"
OLLAMA_HOST_DEFAULT = os.environ.get("OLLAMA_HOST", "http://127.0.0.1:11434")
DEFAULT_SUPPORTED_TEXT_LANGS: Set[str] = {"en", "pl", "de", "fr", "es", "pt"}


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
    return cmd


def build_validation_command(translator_prefix: Sequence[str], epub_path: str, tags: str) -> List[str]:
    return list(translator_prefix) + ["--validate-epub", epub_path, "--tags", tags.strip()]
