#!/usr/bin/env python3
# -*- coding: utf-8 -*-

from __future__ import annotations

import sys
from pathlib import Path


def main() -> int:
    root_dir = Path(__file__).resolve().parents[1]
    if str(root_dir) not in sys.path:
        sys.path.insert(0, str(root_dir))

    try:
        import tkinter as tk
    except Exception as e:
        print(f"SKIP tkinter unavailable: {e}")
        return 0

    try:
        from app_gui_classic import TranslatorGUI
    except Exception as e:
        print(f"FAIL import TranslatorGUI: {e}")
        return 2

    try:
        root = tk.Tk()
    except Exception as e:
        print(f"SKIP no display: {e}")
        return 0

    try:
        root.withdraw()
        gui = TranslatorGUI(root)
        gui._update_command_preview()
        gui._refresh_projects(select_current=False)
        gui._refresh_status_panel()
        root.update_idletasks()
        print("GUI_SMOKE_OK")
        return 0
    except Exception as e:
        print(f"GUI_SMOKE_FAIL: {e}")
        return 3
    finally:
        try:
            root.destroy()
        except Exception:
            pass


if __name__ == "__main__":
    raise SystemExit(main())
