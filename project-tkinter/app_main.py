#!/usr/bin/env python3
# -*- coding: utf-8 -*-

from __future__ import annotations

import argparse


def main() -> int:
    parser = argparse.ArgumentParser(description="EPUB Translator Studio launcher")
    parser.add_argument(
        "--variant",
        choices=("classic", "horizon"),
        default="classic",
        help="UI variant to launch",
    )
    args = parser.parse_args()

    if args.variant == "horizon":
        from app_gui_horizon import main as run_main
    else:
        from app_gui_classic import main as run_main

    return int(run_main())


if __name__ == "__main__":
    raise SystemExit(main())
