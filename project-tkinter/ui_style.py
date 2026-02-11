#!/usr/bin/env python3
# -*- coding: utf-8 -*-

from __future__ import annotations

from typing import Any, Dict
import tkinter as tk
from tkinter import ttk


BASE_TOKENS: Dict[str, Any] = {
    "app_bg": "#0b1220",
    "card_bg": "#111827",
    "surface_bg": "#0f172a",
    "border": "#334155",
    "text": "#e5e7eb",
    "muted": "#94a3b8",
    "title": "#f8fafc",
    "btn_primary_bg": "#0f766e",
    "btn_primary_active": "#115e59",
    "btn_primary_fg": "#ffffff",
    "btn_secondary_bg": "#475569",
    "btn_secondary_active": "#334155",
    "btn_secondary_fg": "#ffffff",
    "btn_accent_bg": "#1d4ed8",
    "btn_accent_active": "#1e40af",
    "btn_accent_fg": "#ffffff",
    "btn_danger_bg": "#b91c1c",
    "btn_danger_active": "#991b1b",
    "btn_danger_fg": "#ffffff",
    "status_ready": "#93a6bd",
    "status_run": "#f59e0b",
    "status_ok": "#22c55e",
    "status_err": "#ef4444",
    "inline_info_bg": "#0b2f4d",
    "inline_info_fg": "#bfdbfe",
    "inline_warn_bg": "#3a2a06",
    "inline_warn_fg": "#fde68a",
    "inline_err_bg": "#3f1313",
    "inline_err_fg": "#fecaca",
    "font": "Segoe UI",
    "font_semi": "Segoe UI Semibold",
    "title_size": 18,
}

HORIZON_PATCH: Dict[str, Any] = {
    "app_bg": "#0a1020",
    "text": "#e6edf6",
    "muted": "#9fb0c7",
    "title": "#f8fafc",
    "btn_primary_bg": "#0f766e",
    "btn_primary_active": "#115e59",
}

SPACING: Dict[str, int] = {
    "space_xs": 4,
    "space_sm": 8,
    "space_md": 12,
    "space_lg": 16,
    "space_xl": 20,
}


def _theme_tokens(variant: str) -> Dict[str, Any]:
    out = dict(BASE_TOKENS)
    if (variant or "").strip().lower() == "horizon":
        out.update(HORIZON_PATCH)
    out.update(SPACING)
    return out


def apply_app_theme(root: tk.Misc, *, variant: str = "base") -> Dict[str, Any]:
    tokens = _theme_tokens(variant)
    style = ttk.Style(root)
    try:
        style.theme_use("clam")
    except Exception:
        pass

    root.configure(bg=tokens["app_bg"])

    style.configure("TFrame", background=tokens["app_bg"])
    style.configure("Card.TFrame", background=tokens["card_bg"], relief="flat")

    style.configure("TLabel", background=tokens["app_bg"], foreground=tokens["text"], font=(tokens["font"], 10))
    style.configure(
        "Title.TLabel",
        background=tokens["app_bg"],
        foreground=tokens["title"],
        font=(tokens["font_semi"], int(tokens["title_size"])),
    )
    style.configure("Sub.TLabel", background=tokens["app_bg"], foreground=tokens["muted"], font=(tokens["font"], 10))
    style.configure("Helper.TLabel", background=tokens["app_bg"], foreground=tokens["muted"], font=(tokens["font"], 9))

    style.configure(
        "InlineInfo.TLabel",
        background=tokens["inline_info_bg"],
        foreground=tokens["inline_info_fg"],
        padding=(10, 6),
        font=(tokens["font_semi"], 10),
    )
    style.configure(
        "InlineWarn.TLabel",
        background=tokens["inline_warn_bg"],
        foreground=tokens["inline_warn_fg"],
        padding=(10, 6),
        font=(tokens["font_semi"], 10),
    )
    style.configure(
        "InlineErr.TLabel",
        background=tokens["inline_err_bg"],
        foreground=tokens["inline_err_fg"],
        padding=(10, 6),
        font=(tokens["font_semi"], 10),
    )

    style.configure(
        "TButton",
        font=(tokens["font_semi"], 10),
        padding=(16, 9),
        background=tokens["btn_secondary_bg"],
        foreground=tokens["btn_secondary_fg"],
    )
    style.map(
        "TButton",
        background=[("active", tokens["btn_secondary_active"]), ("pressed", tokens["btn_secondary_active"])],
        foreground=[("disabled", "#9ca3af"), ("!disabled", tokens["btn_secondary_fg"])],
    )
    style.configure("Primary.TButton", background=tokens["btn_primary_bg"], foreground=tokens["btn_primary_fg"])
    style.map(
        "Primary.TButton",
        background=[("active", tokens["btn_primary_active"]), ("pressed", tokens["btn_primary_active"])],
        foreground=[("disabled", "#d1fae5"), ("!disabled", tokens["btn_primary_fg"])],
    )
    style.configure("Secondary.TButton", background=tokens["btn_secondary_bg"], foreground=tokens["btn_secondary_fg"])
    style.map(
        "Secondary.TButton",
        background=[("active", tokens["btn_secondary_active"]), ("pressed", tokens["btn_secondary_active"])],
        foreground=[("disabled", "#cbd5e1"), ("!disabled", tokens["btn_secondary_fg"])],
    )
    style.configure("Accent.TButton", background=tokens["btn_accent_bg"], foreground=tokens["btn_accent_fg"])
    style.map(
        "Accent.TButton",
        background=[("active", tokens["btn_accent_active"]), ("pressed", tokens["btn_accent_active"])],
        foreground=[("disabled", "#dbeafe"), ("!disabled", tokens["btn_accent_fg"])],
    )
    style.configure("Danger.TButton", background=tokens["btn_danger_bg"], foreground=tokens["btn_danger_fg"])
    style.map(
        "Danger.TButton",
        background=[("active", tokens["btn_danger_active"]), ("pressed", tokens["btn_danger_active"])],
        foreground=[("disabled", "#fecaca"), ("!disabled", tokens["btn_danger_fg"])],
    )

    style.configure(
        "TEntry",
        padding=7,
        fieldbackground=tokens["surface_bg"],
        foreground=tokens["text"],
        bordercolor=tokens["border"],
        insertcolor=tokens["text"],
    )
    style.configure(
        "TCombobox",
        padding=7,
        fieldbackground=tokens["surface_bg"],
        foreground=tokens["text"],
        bordercolor=tokens["border"],
        arrowsize=14,
    )
    style.map("TCombobox", fieldbackground=[("readonly", tokens["surface_bg"])], foreground=[("readonly", tokens["text"])])

    style.configure("Card.TLabelframe", background=tokens["card_bg"], borderwidth=1, relief="solid")
    style.configure(
        "Card.TLabelframe.Label",
        background=tokens["card_bg"],
        foreground=tokens["title"],
        font=(tokens["font_semi"], 10),
    )
    style.configure("TLabelframe", background=tokens["card_bg"], borderwidth=1, relief="solid")
    style.configure(
        "TLabelframe.Label",
        background=tokens["card_bg"],
        foreground=tokens["title"],
        font=(tokens["font_semi"], 10),
    )

    style.configure("StatusReady.TLabel", background=tokens["app_bg"], foreground=tokens["status_ready"], font=(tokens["font"], 10))
    style.configure("StatusRun.TLabel", background=tokens["app_bg"], foreground=tokens["status_run"], font=(tokens["font_semi"], 10))
    style.configure("StatusOk.TLabel", background=tokens["app_bg"], foreground=tokens["status_ok"], font=(tokens["font_semi"], 10))
    style.configure("StatusErr.TLabel", background=tokens["app_bg"], foreground=tokens["status_err"], font=(tokens["font_semi"], 10))

    style.configure("TNotebook", background=tokens["app_bg"], borderwidth=0)
    style.configure("TNotebook.Tab", padding=(14, 8), font=(tokens["font_semi"], 10))
    style.map(
        "TNotebook.Tab",
        background=[("selected", tokens["card_bg"]), ("!selected", "#0f172a")],
        foreground=[("selected", tokens["text"]), ("!selected", tokens["muted"])],
    )

    style.configure(
        "Treeview",
        background=tokens["surface_bg"],
        fieldbackground=tokens["surface_bg"],
        foreground=tokens["text"],
        bordercolor=tokens["border"],
    )
    style.configure(
        "Treeview.Heading",
        background=tokens["card_bg"],
        foreground=tokens["text"],
        relief="flat",
        font=(tokens["font_semi"], 10),
    )
    style.map("Treeview", background=[("selected", "#1d4ed8")], foreground=[("selected", "#ffffff")])

    root.option_add("*Listbox.Background", tokens["surface_bg"])
    root.option_add("*Listbox.Foreground", tokens["text"])
    root.option_add("*Listbox.selectBackground", "#1d4ed8")
    root.option_add("*Listbox.selectForeground", "#ffffff")
    root.option_add("*Text.Background", tokens["surface_bg"])
    root.option_add("*Text.Foreground", tokens["text"])
    root.option_add("*Text.insertBackground", tokens["text"])
    root.option_add("*Menu.background", tokens["card_bg"])
    root.option_add("*Menu.foreground", tokens["text"])
    root.option_add("*Menu.activeBackground", "#1f2937")
    root.option_add("*Menu.activeForeground", "#ffffff")

    return tokens

