#!/usr/bin/env python3
# -*- coding: utf-8 -*-

from __future__ import annotations

import json
from pathlib import Path

import pytest

from prompt_presets import DEFAULT_PROMPT_PRESETS, filter_prompt_presets, load_prompt_presets


def test_load_prompt_presets_falls_back_to_defaults_when_file_missing(tmp_path: Path) -> None:
    presets = load_prompt_presets(tmp_path / "missing.json")
    assert presets
    assert len(presets) == len(DEFAULT_PROMPT_PRESETS)


def test_load_prompt_presets_ignores_invalid_and_duplicate_rows(tmp_path: Path) -> None:
    path = tmp_path / "prompt_presets.json"
    payload = {
        "version": 1,
        "presets": [
            {
                "id": "ok_1",
                "provider": "google",
                "mode": "translate",
                "label": "OK",
                "description": "",
                "prompt": "Translate exactly.",
            },
            {
                "id": "ok_1",
                "provider": "google",
                "mode": "translate",
                "label": "Duplicate",
                "prompt": "Ignored duplicate id.",
            },
            {
                "id": "broken",
                "provider": "google",
                "mode": "translate",
                "label": "Missing prompt",
            },
        ],
    }
    path.write_text(json.dumps(payload), encoding="utf-8")

    presets = load_prompt_presets(path)

    assert len(presets) == 1
    assert presets[0]["id"] == "ok_1"


@pytest.mark.parametrize(
    "provider,mode,expected_ids",
    [
        ("google", "translate", {"g_t", "any_any", "any_t"}),
        ("google", "edit", {"g_e", "any_any"}),
        ("ollama", "translate", {"any_any", "any_t"}),
    ],
)
def test_filter_prompt_presets_respects_provider_and_mode(provider: str, mode: str, expected_ids: set[str]) -> None:
    presets = [
        {"id": "g_t", "provider": "google", "mode": "translate", "label": "", "description": "", "prompt": ""},
        {"id": "g_e", "provider": "google", "mode": "edit", "label": "", "description": "", "prompt": ""},
        {"id": "any_t", "provider": "any", "mode": "translate", "label": "", "description": "", "prompt": ""},
        {"id": "any_any", "provider": "any", "mode": "any", "label": "", "description": "", "prompt": ""},
    ]

    out = filter_prompt_presets(presets, provider=provider, mode=mode)

    assert {item["id"] for item in out} == expected_ids
