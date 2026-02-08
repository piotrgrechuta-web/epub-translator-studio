#!/usr/bin/env python3
# -*- coding: utf-8 -*-

from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Dict, List

Preset = Dict[str, str]

DEFAULT_PROMPT_PRESETS: List[Preset] = [
    {
        "id": "gemini_book_balanced",
        "provider": "google",
        "mode": "translate",
        "label": "Gemini: Book Balanced",
        "description": "Balanced literary translation for general fiction and nonfiction.",
        "prompt": (
            "You are a professional book translator. Translate from source language to target language "
            "faithfully and naturally. Preserve EPUB inline tags and entities exactly. Keep paragraph "
            "boundaries and punctuation style. Avoid adding explanations, notes, or summaries. Return only "
            "translated content."
        ),
    },
    {
        "id": "gemini_lovecraft_tone",
        "provider": "google",
        "mode": "translate",
        "label": "Gemini: Lovecraft Tone",
        "description": "Atmospheric translation for gothic or cosmic-horror prose.",
        "prompt": (
            "You are a literary translator focused on gothic and cosmic-horror style. Translate with formal, "
            "atmospheric cadence and controlled archaic flavor. Preserve meaning, chronology, and speaker "
            "identity. Keep EPUB inline tags and entities unchanged. Do not output comments or analysis."
        ),
    },
    {
        "id": "gemini_technical_manual",
        "provider": "google",
        "mode": "translate",
        "label": "Gemini: Technical Manual",
        "description": "Terminology-first translation for documentation and manuals.",
        "prompt": (
            "You are a technical translator. Prioritize precision, consistency, and unambiguous terminology. "
            "Keep units, commands, identifiers, and markup unchanged where required. Prefer concise, neutral "
            "phrasing. Preserve EPUB inline tags and entities exactly. Return only translated text."
        ),
    },
    {
        "id": "gemini_polish_copyedit",
        "provider": "google",
        "mode": "edit",
        "label": "Gemini: Polish Copyedit",
        "description": "Polish copyedit preset for rhythm, clarity, and punctuation consistency.",
        "prompt": (
            "You are a Polish copy editor. Improve fluency, punctuation, and readability while preserving "
            "meaning, facts, and style intent. Keep EPUB inline tags and entities unchanged. Do not rewrite the "
            "structure beyond what is needed for quality editing. Return only edited content."
        ),
    },
]


def _normalize_token(value: Any, default: str = "any") -> str:
    token = str(value or "").strip().lower()
    return token or default


def _sanitize_preset(raw: Any) -> Preset:
    if not isinstance(raw, dict):
        raise ValueError("Preset entry must be an object.")

    preset_id = str(raw.get("id", "")).strip()
    if not preset_id:
        raise ValueError("Preset id is required.")

    label = str(raw.get("label", "")).strip()
    if not label:
        raise ValueError(f"Preset '{preset_id}' missing label.")

    prompt = str(raw.get("prompt", "")).strip()
    if not prompt:
        raise ValueError(f"Preset '{preset_id}' missing prompt text.")

    return {
        "id": preset_id,
        "provider": _normalize_token(raw.get("provider", "any"), "any"),
        "mode": _normalize_token(raw.get("mode", "any"), "any"),
        "label": label,
        "description": str(raw.get("description", "")).strip(),
        "prompt": prompt,
    }


def _payload_to_rows(payload: Any) -> List[Any]:
    if isinstance(payload, list):
        return payload
    if isinstance(payload, dict):
        rows = payload.get("presets")
        if isinstance(rows, list):
            return rows
    return []


def load_prompt_presets(path: Path) -> List[Preset]:
    rows: List[Any] = []
    if path.exists():
        try:
            payload = json.loads(path.read_text(encoding="utf-8"))
            rows = _payload_to_rows(payload)
        except Exception:
            rows = []

    presets: List[Preset] = []
    seen_ids: set[str] = set()
    for raw in rows:
        try:
            item = _sanitize_preset(raw)
        except Exception:
            continue
        if item["id"] in seen_ids:
            continue
        seen_ids.add(item["id"])
        presets.append(item)

    if presets:
        return presets
    return [dict(x) for x in DEFAULT_PROMPT_PRESETS]


def save_default_prompt_presets(path: Path) -> bool:
    if path.exists():
        return False
    path.write_text(
        json.dumps({"version": 1, "presets": DEFAULT_PROMPT_PRESETS}, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    return True


def filter_prompt_presets(presets: List[Preset], provider: str, mode: str) -> List[Preset]:
    provider_key = _normalize_token(provider, "any")
    mode_key = _normalize_token(mode, "any")
    out: List[Preset] = []
    for p in presets:
        p_provider = _normalize_token(p.get("provider", "any"), "any")
        p_mode = _normalize_token(p.get("mode", "any"), "any")
        provider_ok = p_provider in {"any", provider_key}
        mode_ok = p_mode in {"any", mode_key}
        if provider_ok and mode_ok:
            out.append(p)
    return out
