#!/usr/bin/env python3
# -*- coding: utf-8 -*-

from __future__ import annotations

import tkinter as tk
from tkinter import ttk

import app_gui_classic as base
from ui_style import apply_app_theme


base.APP_TITLE = "Translator Studio Horizon"


class HorizonGUI(base.TranslatorGUI):
    def _setup_theme(self) -> None:
        self.ui_tokens = apply_app_theme(self.root, variant="horizon")
        style = ttk.Style(self.root)
        style.configure("Title.TLabel", font=("Segoe UI Semibold", 24))
        style.configure("Sub.TLabel", font=("Segoe UI", 11))

    def _build_ui(self) -> None:
        self.root.title("Translator Studio Horizon")
        outer = self._create_scrollable_root(padding=18)

        header = ttk.Frame(outer, style="Card.TFrame", padding=(18, 14))
        header.pack(fill="x")
        ttk.Label(header, text="Translator Studio", style="Title.TLabel").pack(anchor="w")
        ttk.Label(
            header,
            text="Desktop UI w stylu web: czytelniejszy układ, większe sekcje i spójna typografia.",
            style="Sub.TLabel",
        ).pack(anchor="w", pady=(4, 0))

        tabs_wrap = ttk.Frame(outer, style="Card.TFrame", padding=10)
        tabs_wrap.pack(fill="both", expand=True, pady=(14, 0))
        tabs = ttk.Notebook(tabs_wrap)
        tabs.pack(fill="both", expand=True)

        files_tab = ttk.Frame(tabs, padding=8)
        engine_tab = ttk.Frame(tabs, padding=8)
        log_tab = ttk.Frame(tabs, padding=8)
        layout_tab = ttk.Frame(tabs, padding=8)

        tabs.add(files_tab, text="Pliki i Tryb")
        tabs.add(engine_tab, text="Silnik i Model")
        tabs.add(log_tab, text="Log")
        tabs.add(layout_tab, text="Układanie EPUB")

        self._build_project_card(files_tab)
        self._build_files_card(files_tab)
        self._build_run_card(files_tab)

        self._build_engine_card(engine_tab)
        self._build_model_card(engine_tab)
        self._build_advanced_card(engine_tab)

        self._build_log_card(log_tab)
        # Własna zakładka dla sekcji układania EPUB.
        old_tr = self.tr
        self.tr = lambda key, default, **fmt: old_tr(key, "Układanie EPUB" if key == "section.enhance" else default, **fmt)
        try:
            self._build_enhance_card(layout_tab)
        finally:
            self.tr = old_tr

        self._inline_notice_label = ttk.Label(outer, textvariable=self.inline_notice_var, style="InlineInfo.TLabel")
        self._inline_notice_label.pack(fill="x", pady=(10, 0))
        self.status_label = ttk.Label(outer, textvariable=self.status_var, style="StatusReady.TLabel")
        self.status_label.pack(anchor="w", pady=(8, 0))


def main() -> int:
    root = tk.Tk()
    HorizonGUI(root)
    root.mainloop()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
