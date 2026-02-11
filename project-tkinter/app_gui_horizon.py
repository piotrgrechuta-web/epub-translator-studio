#!/usr/bin/env python3
# -*- coding: utf-8 -*-

from __future__ import annotations

import tkinter as tk
from tkinter import ttk
from typing import Callable, Optional

try:
    import customtkinter as ctk
except Exception:  # pragma: no cover - optional dependency fallback
    ctk = None

import app_gui_classic as base
from ui_style import apply_app_theme


base.APP_TITLE = "Translator Studio Horizon"


class HorizonGUI(base.TranslatorGUI):
    def _setup_theme(self) -> None:
        self.ui_tokens = apply_app_theme(self.root, variant="horizon")
        style = ttk.Style(self.root)
        style.configure("Title.TLabel", font=("Segoe UI Semibold", 24))
        style.configure("Sub.TLabel", font=("Segoe UI", 11))
        style.configure("Card.TLabelframe", padding=14)

    def _safe_action(self, name: str) -> Optional[Callable[[], None]]:
        handler = getattr(self, name, None)
        if callable(handler):
            return handler
        return None

    def _build_action_bar(self, parent: tk.Misc) -> None:
        if ctk is None:
            return
        bar = ctk.CTkFrame(parent, corner_radius=12, fg_color=("#1f2937", "#111827"))
        bar.pack(fill="x", padx=16, pady=(0, 12))
        actions = [
            ("Uruchom", self._safe_action("_start_translation"), ("#0F766E", "#115E59")),
            ("Waliduj", self._safe_action("_start_validation"), ("#1D4ED8", "#1E40AF")),
            ("Zapisz", self._safe_action("_save_project"), ("#475569", "#334155")),
            ("Stop", self._safe_action("_stop_process"), ("#B91C1C", "#991B1B")),
        ]
        for idx, (label, command, color) in enumerate(actions):
            btn = ctk.CTkButton(
                bar,
                text=label,
                command=command,
                corner_radius=9,
                height=34,
                fg_color=color,
                hover_color=color[1],
                state="normal" if command else "disabled",
            )
            btn.grid(row=0, column=idx, padx=(0 if idx == 0 else 8, 0), pady=10, sticky="w")

    def _build_tab_shell(self, tab: tk.Misc, *, title: str, subtitle: str) -> tk.Misc:
        if ctk is None:
            host = ttk.Frame(tab, padding=10)
            host.pack(fill="both", expand=True)
            ttk.Label(host, text=title, style="Title.TLabel").pack(anchor="w")
            ttk.Label(host, text=subtitle, style="Sub.TLabel").pack(anchor="w", pady=(0, 8))
            return host

        scroll = ctk.CTkScrollableFrame(tab, corner_radius=10, fg_color=("#0f172a", "#111827"))
        scroll.pack(fill="both", expand=True, padx=10, pady=10)
        ctk.CTkLabel(
            scroll,
            text=title,
            font=("Segoe UI Semibold", 23),
            text_color=("#f8fafc", "#f8fafc"),
        ).pack(anchor="w", padx=12, pady=(8, 0))
        ctk.CTkLabel(
            scroll,
            text=subtitle,
            font=("Segoe UI", 12),
            text_color=("#cbd5e1", "#cbd5e1"),
        ).pack(anchor="w", padx=12, pady=(2, 10))

        surface = ctk.CTkFrame(scroll, corner_radius=12, fg_color=("#111827", "#0f172a"))
        surface.pack(fill="both", expand=True, padx=6, pady=(0, 8))
        host = ttk.Frame(surface, style="Card.TFrame", padding=12)
        host.pack(fill="both", expand=True)
        return host


    def _build_ui(self) -> None:
        self.root.title("Translator Studio Horizon")
        self.root.minsize(1180, 760)

        shell: tk.Misc
        if ctk is not None:
            shell = ctk.CTkFrame(self.root, corner_radius=0, fg_color=("#0b1220", "#0b1220"))
        else:
            shell = ttk.Frame(self.root)
        shell.pack(fill="both", expand=True)

        if ctk is not None:
            header = ctk.CTkFrame(shell, corner_radius=16, fg_color=("#111827", "#1f2937"))
            header.pack(fill="x", padx=16, pady=(16, 0))
            ctk.CTkLabel(
                header,
                text="Translator Studio Horizon",
                font=("Segoe UI Semibold", 30),
                text_color=("#f8fafc", "#f8fafc"),
            ).pack(anchor="w", padx=16, pady=(14, 2))
            ctk.CTkLabel(
                header,
                text="Wariant Horizon: zakladki i pasek akcji.",
                font=("Segoe UI", 13),
                text_color=("#cbd5e1", "#cbd5e1"),
            ).pack(anchor="w", padx=16, pady=(0, 8))
            self._build_action_bar(header)

            tabs_wrap = ctk.CTkFrame(shell, corner_radius=14, fg_color=("#111827", "#111827"))
            tabs_wrap.pack(fill="both", expand=True, padx=16, pady=(12, 0))
            tabs = ctk.CTkTabview(
                tabs_wrap,
                corner_radius=12,
                segmented_button_selected_color="#0F766E",
                segmented_button_selected_hover_color="#115E59",
            )
            tabs.pack(fill="both", expand=True, padx=12, pady=12)

            files_host = self._build_tab_shell(
                tabs.add("Pliki i Tryb"),
                title="Pliki i Tryb",
                subtitle="Konfiguracja projektu, wejscia/wyjscia i uruchamianie.",
            )
            engine_host = self._build_tab_shell(
                tabs.add("Silnik i Model"),
                title="Silnik i Model",
                subtitle="Provider, model i parametry.",
            )
            log_host = self._build_tab_shell(
                tabs.add("Log"),
                title="Log",
                subtitle="Przebieg pracy i metryki.",
            )
            layout_host = self._build_tab_shell(
                tabs.add("Ukladanie EPUB"),
                title="Ukladanie EPUB",
                subtitle="Operacje porzadkowania i edycji EPUB.",
            )
        else:
            outer = self._create_scrollable_root(padding=18)
            header = ttk.Frame(outer, style="Card.TFrame", padding=(18, 14))
            header.pack(fill="x")
            ttk.Label(header, text="Translator Studio Horizon", style="Title.TLabel").pack(anchor="w")

            tabs_wrap = ttk.Frame(outer, style="Card.TFrame", padding=10)
            tabs_wrap.pack(fill="both", expand=True, pady=(14, 0))
            tabs = ttk.Notebook(tabs_wrap)
            tabs.pack(fill="both", expand=True)

            files_host = ttk.Frame(tabs, padding=8)
            engine_host = ttk.Frame(tabs, padding=8)
            log_host = ttk.Frame(tabs, padding=8)
            layout_host = ttk.Frame(tabs, padding=8)
            tabs.add(files_host, text="Pliki i Tryb")
            tabs.add(engine_host, text="Silnik i Model")
            tabs.add(log_host, text="Log")
            tabs.add(layout_host, text="Ukladanie EPUB")

        self._build_project_card(files_host)
        self._build_files_card(files_host)
        self._build_run_card(files_host)

        self._build_engine_card(engine_host)
        self._build_model_card(engine_host)
        self._build_advanced_card(engine_host)

        self._build_log_card(log_host)

        old_tr = self.tr
        self.tr = lambda key, default, **fmt: old_tr(key, "Ukladanie EPUB" if key == "section.enhance" else default, **fmt)
        try:
            self._build_enhance_card(layout_host)
        finally:
            self.tr = old_tr

        status_row = ttk.Frame(shell, padding=(18, 10))
        status_row.pack(fill="x")
        self._inline_notice_label = ttk.Label(status_row, textvariable=self.inline_notice_var, style="InlineInfo.TLabel")
        self._inline_notice_label.pack(fill="x")
        self.status_label = ttk.Label(status_row, textvariable=self.status_var, style="StatusReady.TLabel")
        self.status_label.pack(anchor="w", pady=(6, 0))


def main() -> int:
    if ctk is not None:
        try:
            ctk.set_appearance_mode("Dark")
            ctk.set_default_color_theme("blue")
            root = ctk.CTk()
        except Exception:
            root = tk.Tk()
    else:
        root = tk.Tk()
    HorizonGUI(root)
    root.mainloop()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
