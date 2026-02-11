#!/usr/bin/env python3
# -*- coding: utf-8 -*-

from __future__ import annotations

from typing import Any, Dict, Optional

from tkinter import ttk

try:
    import customtkinter as ctk
except Exception:  # pragma: no cover - optional dependency fallback
    ctk = None


if ctk is not None:
    try:
        ctk.set_appearance_mode("Dark")
        ctk.set_default_color_theme("blue")
    except Exception:
        pass


def _palette_for_style(style: Optional[str]) -> Dict[str, str]:
    key = str(style or "").strip().lower()
    if "danger" in key:
        return {"fg": "#B91C1C", "hover": "#991B1B", "text": "#FFFFFF"}
    if "accent" in key:
        return {"fg": "#1D4ED8", "hover": "#1E40AF", "text": "#FFFFFF"}
    if "primary" in key:
        return {"fg": "#0F766E", "hover": "#115E59", "text": "#FFFFFF"}
    return {"fg": "#475569", "hover": "#334155", "text": "#FFFFFF"}


def ui_button(
    parent: Any,
    *,
    text: str = "",
    command: Any = None,
    style: Optional[str] = None,
    state: Optional[str] = None,
    width: Optional[int] = None,
    **kwargs: Any,
):
    if ctk is None or kwargs:
        return ttk.Button(
            parent,
            text=text,
            command=command,
            style=style,
            state=state,
            width=width,
            **kwargs,
        )

    palette = _palette_for_style(style)
    button_kwargs: Dict[str, Any] = {
        "text": str(text or ""),
        "command": command,
        "corner_radius": 10,
        "height": 36,
        "fg_color": palette["fg"],
        "hover_color": palette["hover"],
        "text_color": palette["text"],
        "border_width": 0,
    }
    if width is not None:
        button_kwargs["width"] = width

    btn = ctk.CTkButton(
        parent,
        **button_kwargs,
    )
    if state:
        try:
            btn.configure(state=state)
        except Exception:
            pass
    return btn
