#!/usr/bin/env python3
# -*- coding: utf-8 -*-

from __future__ import annotations

# Backward-compatible entrypoint. Preferred module: app_gui_horizon.py
from app_gui_horizon import HorizonGUI, main as _horizon_main

__all__ = ["HorizonGUI", "main"]


def main() -> int:
    return int(_horizon_main())


if __name__ == "__main__":
    raise SystemExit(main())
