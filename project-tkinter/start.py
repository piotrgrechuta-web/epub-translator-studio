#!/usr/bin/env python3
# -*- coding: utf-8 -*-

from __future__ import annotations

# Backward-compatible entrypoint. Preferred module: app_gui_classic.py
from app_gui_classic import APP_TITLE, TextEditorWindow, TranslatorGUI, main as _classic_main

__all__ = ["APP_TITLE", "TranslatorGUI", "TextEditorWindow", "main"]


def main() -> int:
    return int(_classic_main())


if __name__ == "__main__":
    raise SystemExit(main())

