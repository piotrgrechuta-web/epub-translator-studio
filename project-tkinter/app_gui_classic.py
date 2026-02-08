#!/usr/bin/env python3
# -*- coding: utf-8 -*-

from __future__ import annotations

import json
import logging
import os
import platform
import queue
import re
import shutil
import subprocess
import sys
import threading
import time
import webbrowser
import zipfile
import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional

import tkinter as tk
from tkinter import filedialog, messagebox, ttk
from tkinter.scrolledtext import ScrolledText
from lxml import etree

from project_db import DB_FILE, ProjectDB
from gui_tooltips import install_tooltips
from i18n import I18NManager, SUPPORTED_TEXT_LANGS, SUPPORTED_UI_LANGS, ai_translate_gui_labels
from epub_enhancer import (
    add_front_matter_card,
    batch_add_front_matter,
    remove_images,
    preview_add_front_matter,
    preview_remove_images,
    list_chapters,
    load_chapter_segments,
    save_chapter_changes,
)
from studio_suite import StudioSuiteWindow
from app_events import flush_event_log, log_event_jsonl
from runtime_core import (
    RunOptions as CoreRunOptions,
    build_run_command as core_build_run_command,
    build_validation_command as core_build_validation_command,
    list_google_models as core_list_google_models,
    list_ollama_models as core_list_ollama_models,
)
from ui_style import apply_app_theme

APP_TITLE = "EPUB Translator Studio"
SETTINGS_FILE = Path(__file__).resolve().with_name(".gui_settings.json")
SQLITE_FILE = Path(__file__).resolve().with_name(DB_FILE)
LOCALES_DIR = Path(__file__).resolve().with_name("locales")
OLLAMA_HOST_DEFAULT = os.environ.get("OLLAMA_HOST", "http://127.0.0.1:11434")
GOOGLE_API_KEY_ENV = "GOOGLE_API_KEY"
SUPPORT_URL = "https://github.com/sponsors/piotrgrechuta-web"
REPO_URL = "https://github.com/piotrgrechuta-web/epu2pl"
GOOGLE_KEYRING_SERVICE = "epub-translator-studio"
GOOGLE_KEYRING_USER = "google_api_key"
GLOBAL_PROGRESS_RE = re.compile(r"GLOBAL\s+(\d+)\s*/\s*(\d+)\s*\(([^)]*)\)\s*\|\s*(.*)")
TOTAL_SEGMENTS_RE = re.compile(r"Segmenty\s+(?:łącznie|lacznie)\s*:\s*(\d+)", re.IGNORECASE)
CACHE_SEGMENTS_RE = re.compile(r"Segmenty\s+z\s+cache\s*:\s*(\d+)", re.IGNORECASE)
CHAPTER_CACHE_TM_RE = re.compile(r"\(cache:\s*(\d+)\s*,\s*tm:\s*(\d+)\)", re.IGNORECASE)
METRICS_BLOB_RE = re.compile(r"metrics\[(.*?)\]", re.IGNORECASE)
METRICS_KV_RE = re.compile(r"([a-zA-Z_]+)\s*=\s*([^;]+)")
LOG = logging.getLogger(__name__)


def list_ollama_models(host: str, timeout_s: int = 20) -> List[str]:
    return core_list_ollama_models(host=host, timeout_s=timeout_s)


def list_google_models(api_key: str, timeout_s: int = 20) -> List[str]:
    return core_list_google_models(api_key=api_key, timeout_s=timeout_s)


def quote_arg(arg: str) -> str:
    if platform.system().lower().startswith("win"):
        if any(ch in arg for ch in [" ", "\t", '"']):
            return '"' + arg.replace('"', '\\"') + '"'
        return arg
    return arg


def simple_prompt(root: tk.Tk, title: str, label: str) -> Optional[str]:
    win = tk.Toplevel(root)
    win.title(title)
    win.transient(root)
    win.grab_set()
    out: Dict[str, Optional[str]] = {"value": None}

    frm = ttk.Frame(win, padding=12)
    frm.pack(fill="both", expand=True)
    ttk.Label(frm, text=label).pack(anchor="w")
    var = tk.StringVar()
    entry = ttk.Entry(frm, textvariable=var, width=40)
    entry.pack(fill="x", pady=(6, 10))
    entry.focus_set()

    btn = ttk.Frame(frm)
    btn.pack(fill="x")

    def accept() -> None:
        out["value"] = var.get()
        win.destroy()

    def cancel() -> None:
        out["value"] = None
        win.destroy()

    ttk.Button(btn, text="OK", command=accept).pack(side="left")
    ttk.Button(btn, text="Anuluj", command=cancel).pack(side="left", padx=(8, 0))
    win.bind("<Return>", lambda _: accept())
    win.bind("<Escape>", lambda _: cancel())
    root.wait_window(win)
    return out["value"]


def load_google_api_key_from_keyring() -> str:
    try:
        import keyring  # type: ignore

        v = keyring.get_password(GOOGLE_KEYRING_SERVICE, GOOGLE_KEYRING_USER)
        return (v or "").strip()
    except Exception:
        return ""


def save_google_api_key_to_keyring(value: str) -> bool:
    try:
        import keyring  # type: ignore

        v = (value or "").strip()
        if v:
            keyring.set_password(GOOGLE_KEYRING_SERVICE, GOOGLE_KEYRING_USER, v)
        else:
            try:
                keyring.delete_password(GOOGLE_KEYRING_SERVICE, GOOGLE_KEYRING_USER)
            except Exception:
                pass
        return True
    except Exception:
        return False


class TranslatorGUI:
    def __init__(self, root: tk.Tk) -> None:
        self.root = root
        self.root.title(APP_TITLE)

        self.workdir = Path(__file__).resolve().parent
        self.events_log_path = self.workdir / "events" / "app_events.jsonl"
        self.translator_path = self._find_translator()
        self.db = ProjectDB(SQLITE_FILE)
        ui_lang = str(self.db.get_setting("ui_language", "pl") or "pl").strip().lower()
        self.i18n = I18NManager(LOCALES_DIR, ui_lang)
        mode_raw = str(self.db.get_setting("tooltip_mode", "hybrid") or "hybrid").strip().lower()
        if mode_raw not in {"short", "expert", "hybrid"}:
            mode_raw = "hybrid"
        if self.db.get_setting("tooltip_mode", None) is None:
            self.db.set_setting("tooltip_mode", mode_raw)
        self.proc: Optional[subprocess.Popen] = None
        self.run_all_active = False
        self.current_project_id: Optional[int] = None
        self.current_run_id: Optional[int] = None
        self.op_history: List[Dict[str, Any]] = []
        self.project_name_to_id: Dict[str, int] = {}
        self.profile_name_to_id: Dict[str, int] = {}
        self.step_values: Dict[str, Dict[str, str]] = {
            "translate": {"output": "", "prompt": "", "cache": "", "profile_name": ""},
            "edit": {"output": "", "prompt": "", "cache": "", "profile_name": ""},
        }
        self.last_mode = "translate"
        self.log_queue: "queue.Queue[str]" = queue.Queue()
        self.run_started_at: Optional[float] = None
        self.last_log_at: Optional[float] = None
        self._tooltips: List[Any] = []
        self.tooltip_mode = mode_raw
        self._projects_refresh_seq = 0
        self._root_scroll_canvas: Optional[tk.Canvas] = None
        self._root_scroll_window: Optional[int] = None
        self._root_scroll_frame: Optional[ttk.Frame] = None
        self._context_menu: Optional[tk.Menu] = None
        self._context_target: Optional[tk.Misc] = None
        self._inline_notice_after_id: Optional[str] = None
        self._inline_notice_label: Optional[ttk.Label] = None
        self.ui_tokens: Dict[str, Any] = {}
        self._runtime_metrics: Dict[str, int] = {}
        self._runtime_metric_lines: set[str] = set()
        self._reset_runtime_metrics()

        self._configure_main_window()
        self._setup_theme()
        self._build_vars()
        self._build_ui()
        self._install_context_menu()
        self._install_keyboard_shortcuts()
        self._install_tooltips()
        self.db.import_legacy_gui_settings(SETTINGS_FILE)
        self._load_defaults()
        self._load_settings(silent=True)
        self._refresh_profiles()
        self._refresh_projects(select_current=True)
        self._update_command_preview()
        self._poll_log_queue()
        self.root.protocol("WM_DELETE_WINDOW", self._on_close)

    def _setup_theme(self) -> None:
        self.ui_tokens = apply_app_theme(self.root, variant="base")

    def _theme_color(self, key: str, default: str) -> str:
        val = self.ui_tokens.get(key, default)
        return str(val) if isinstance(val, str) else default

    def _theme_space(self, key: str, default: int) -> int:
        val = self.ui_tokens.get(key, default)
        try:
            return int(val)
        except Exception:
            return int(default)

    def _configure_main_window(self) -> None:
        self._configure_window_bounds(self.root, preferred_w=1200, preferred_h=820, min_w=760, min_h=520, maximize=True)

    def _reset_runtime_metrics(self) -> None:
        self._runtime_metrics = {
            "total_segments": 0,
            "cache_hits": 0,
            "tm_hits": 0,
        }
        self._runtime_metric_lines.clear()

    def _format_duration(self, seconds: Optional[int]) -> str:
        if seconds is None:
            return "-"
        sec = max(0, int(seconds))
        h, rem = divmod(sec, 3600)
        m, s = divmod(rem, 60)
        if h > 0:
            return f"{h:02d}:{m:02d}:{s:02d}"
        return f"{m:02d}:{s:02d}"

    def _runtime_metrics_blob(self) -> str:
        total = int(self.global_total or self._runtime_metrics.get("total_segments", 0) or 0)
        done = int(self.global_done or 0)
        cache_hits = int(self._runtime_metrics.get("cache_hits", 0) or 0)
        tm_hits = int(self._runtime_metrics.get("tm_hits", 0) or 0)
        reuse_hits = cache_hits + tm_hits
        reuse_rate = (reuse_hits / total) * 100.0 if total > 0 else 0.0
        dur_s = int(max(0.0, time.time() - self.run_started_at)) if self.run_started_at is not None else 0
        return (
            f"metrics[dur_s={dur_s};done={done};total={total};cache_hits={cache_hits};"
            f"tm_hits={tm_hits};reuse_hits={reuse_hits};reuse_rate={reuse_rate:.1f}]"
        )

    def _parse_metrics_blob(self, message: str) -> Dict[str, float]:
        out: Dict[str, float] = {}
        text = str(message or "")
        m = METRICS_BLOB_RE.search(text)
        if not m:
            return out
        for key, raw in METRICS_KV_RE.findall(m.group(1)):
            k = str(key).strip()
            v = str(raw).strip().rstrip("%")
            if not k:
                continue
            try:
                if "." in v:
                    out[k] = float(v)
                else:
                    out[k] = float(int(v))
            except Exception:
                continue
        return out

    def _update_live_run_metrics(self) -> None:
        if self.run_started_at is None:
            return
        total = int(self.global_total or self._runtime_metrics.get("total_segments", 0) or 0)
        done = int(self.global_done or 0)
        cache_hits = int(self._runtime_metrics.get("cache_hits", 0) or 0)
        tm_hits = int(self._runtime_metrics.get("tm_hits", 0) or 0)
        reuse_hits = cache_hits + tm_hits
        reuse_rate = (reuse_hits / total) * 100.0 if total > 0 else 0.0
        dur_s = int(max(0.0, time.time() - self.run_started_at))
        self.run_metrics_var.set(
            f"Metryki runu: czas={self._format_duration(dur_s)} | seg={done}/{total} | "
            f"cache={cache_hits} | tm={tm_hits} | reuse={reuse_rate:.1f}%"
        )

    def _collect_runtime_metrics_from_log(self, line: str) -> None:
        s = str(line or "").strip()
        if not s:
            return
        m_total = TOTAL_SEGMENTS_RE.search(s)
        if m_total:
            try:
                self._runtime_metrics["total_segments"] = max(0, int(m_total.group(1)))
            except Exception:
                pass
        m_cache = CACHE_SEGMENTS_RE.search(s)
        if m_cache:
            try:
                self._runtime_metrics["cache_hits"] = max(0, int(m_cache.group(1)))
            except Exception:
                pass
        m_tm = CHAPTER_CACHE_TM_RE.search(s)
        if m_tm and s not in self._runtime_metric_lines:
            self._runtime_metric_lines.add(s)
            try:
                self._runtime_metrics["tm_hits"] += max(0, int(m_tm.group(2)))
            except Exception:
                pass

    def _configure_window_bounds(
        self,
        win: tk.Misc,
        *,
        preferred_w: int,
        preferred_h: int,
        min_w: int,
        min_h: int,
        maximize: bool = False,
    ) -> None:
        screen_w = max(1024, int(self.root.winfo_screenwidth() or 1200))
        screen_h = max(720, int(self.root.winfo_screenheight() or 820))

        eff_min_w = min(max(520, int(screen_w - 120)), max(480, int(min_w)))
        eff_min_h = min(max(400, int(screen_h - 140)), max(360, int(min_h)))
        pref_w = min(max(eff_min_w, int(preferred_w)), max(900, screen_w - 40))
        pref_h = min(max(eff_min_h, int(preferred_h)), max(650, screen_h - 80))
        x = max(0, (screen_w - pref_w) // 2)
        y = max(0, (screen_h - pref_h) // 2)

        try:
            win.geometry(f"{pref_w}x{pref_h}+{x}+{y}")  # type: ignore[attr-defined]
        except Exception:
            return
        try:
            win.minsize(eff_min_w, eff_min_h)  # type: ignore[attr-defined]
        except Exception:
            pass
        if not maximize:
            return
        try:
            win.state("zoomed")  # type: ignore[attr-defined]
            return
        except Exception:
            pass
        try:
            win.attributes("-zoomed", True)  # type: ignore[attr-defined]
        except Exception:
            pass

    def _create_scrollable_root(self, *, padding: int = 16) -> ttk.Frame:
        shell = ttk.Frame(self.root)
        shell.pack(fill="both", expand=True)
        shell.columnconfigure(0, weight=1)
        shell.rowconfigure(0, weight=1)

        bg = self._theme_color("app_bg", str(self.root.cget("bg") or "#eef3f7"))
        canvas = tk.Canvas(shell, highlightthickness=0, borderwidth=0, background=bg)
        vbar = ttk.Scrollbar(shell, orient="vertical", command=canvas.yview)
        hbar = ttk.Scrollbar(shell, orient="horizontal", command=canvas.xview)
        canvas.configure(yscrollcommand=vbar.set, xscrollcommand=hbar.set)

        canvas.grid(row=0, column=0, sticky="nsew")
        vbar.grid(row=0, column=1, sticky="ns")
        hbar.grid(row=1, column=0, sticky="ew")

        frame = ttk.Frame(canvas, padding=padding)
        window_id = canvas.create_window((0, 0), window=frame, anchor="nw")

        def _sync_layout(_: Optional[tk.Event] = None) -> None:
            canvas.configure(scrollregion=canvas.bbox("all"))
            req_w = max(1, int(frame.winfo_reqwidth()))
            can_w = max(1, int(canvas.winfo_width()))
            # Keep full-width layout when there is space; allow horizontal scroll when window is too narrow.
            canvas.itemconfigure(window_id, width=can_w if req_w <= can_w else req_w)

        frame.bind("<Configure>", _sync_layout)
        canvas.bind("<Configure>", _sync_layout)

        self._root_scroll_canvas = canvas
        self._root_scroll_window = int(window_id)
        self._root_scroll_frame = frame
        return frame

    def _install_context_menu(self) -> None:
        menu = tk.Menu(self.root, tearoff=0)
        menu.add_command(label="Cofnij", command=lambda: self._context_emit("<<Undo>>"))
        menu.add_command(label="Ponow", command=lambda: self._context_emit("<<Redo>>"))
        menu.add_separator()
        menu.add_command(label="Wytnij", command=lambda: self._context_emit("<<Cut>>"))
        menu.add_command(label="Kopiuj", command=lambda: self._context_emit("<<Copy>>"))
        menu.add_command(label="Wklej", command=lambda: self._context_emit("<<Paste>>"))
        menu.add_command(label="Usun", command=lambda: self._context_emit("<<Clear>>"))
        menu.add_separator()
        menu.add_command(label="Zaznacz wszystko", command=self._context_select_all)
        menu.add_command(label="Wyczysc pole", command=self._context_clear_field)

        self._context_menu = menu
        for cls in ("Entry", "TEntry", "Text", "TCombobox", "Spinbox", "TSpinbox", "Listbox"):
            self.root.bind_class(cls, "<Button-3>", self._show_context_menu, add="+")
            self.root.bind_class(cls, "<Shift-F10>", self._show_context_menu_keyboard, add="+")
            self.root.bind_class(cls, "<Control-a>", self._context_select_all_event, add="+")
            self.root.bind_class(cls, "<Control-A>", self._context_select_all_event, add="+")

    def _show_context_menu(self, event: tk.Event) -> str:
        if self._context_menu is None:
            return "break"
        widget = event.widget if isinstance(event.widget, tk.Misc) else None
        if widget is None:
            return "break"
        self._context_target = widget
        try:
            widget.focus_set()
        except Exception:
            pass
        try:
            self._context_menu.tk_popup(int(event.x_root), int(event.y_root))
        finally:
            self._context_menu.grab_release()
        return "break"

    def _show_context_menu_keyboard(self, event: tk.Event) -> str:
        widget = event.widget if isinstance(event.widget, tk.Misc) else None
        if widget is None:
            return "break"
        if self._context_menu is None:
            return "break"
        self._context_target = widget
        x = widget.winfo_rootx() + max(8, int(widget.winfo_width() * 0.2))
        y = widget.winfo_rooty() + max(8, int(widget.winfo_height() * 0.8))
        try:
            self._context_menu.tk_popup(x, y)
        finally:
            self._context_menu.grab_release()
        return "break"

    def _context_emit(self, sequence: str) -> None:
        widget = self._context_target
        if widget is None:
            return
        try:
            widget.event_generate(sequence)
        except Exception:
            pass

    def _context_select_all(self) -> None:
        widget = self._context_target
        if widget is None:
            return
        cls = str(widget.winfo_class())
        try:
            if cls in {"Entry", "TEntry", "TCombobox", "Spinbox", "TSpinbox"}:
                widget.selection_range(0, "end")  # type: ignore[attr-defined]
                widget.icursor("end")  # type: ignore[attr-defined]
            elif cls == "Text":
                widget.tag_add("sel", "1.0", "end-1c")  # type: ignore[attr-defined]
            elif cls == "Listbox":
                widget.selection_set(0, "end")  # type: ignore[attr-defined]
        except Exception:
            pass

    def _context_select_all_event(self, event: tk.Event) -> str:
        widget = event.widget if isinstance(event.widget, tk.Misc) else None
        if widget is None:
            return "break"
        self._context_target = widget
        self._context_select_all()
        return "break"

    def _context_clear_field(self) -> None:
        widget = self._context_target
        if widget is None:
            return
        cls = str(widget.winfo_class())
        try:
            if cls in {"Entry", "TEntry", "TCombobox", "Spinbox", "TSpinbox"}:
                widget.delete(0, "end")  # type: ignore[attr-defined]
            elif cls == "Text":
                widget.delete("1.0", "end")  # type: ignore[attr-defined]
        except Exception:
            pass

    def _install_keyboard_shortcuts(self) -> None:
        self.root.bind_all("<Control-s>", self._shortcut_save_project, add="+")
        self.root.bind_all("<Control-S>", self._shortcut_save_project, add="+")
        self.root.bind_all("<Control-r>", self._shortcut_start_run, add="+")
        self.root.bind_all("<Control-R>", self._shortcut_start_run, add="+")
        self.root.bind_all("<Control-q>", self._shortcut_queue_project, add="+")
        self.root.bind_all("<Control-Q>", self._shortcut_queue_project, add="+")
        self.root.bind_all("<F5>", self._shortcut_refresh_models, add="+")

    def _shortcut_save_project(self, _: tk.Event) -> str:
        self._save_project(notify_missing=True)
        self._set_inline_notice(self.tr("status.project_saved", "Project saved"), level="info")
        return "break"

    def _shortcut_start_run(self, _: tk.Event) -> str:
        if self.proc is not None:
            self._set_inline_notice(self.tr("info.process_running", "Process is already running."), level="warn")
            return "break"
        self._start_process()
        return "break"

    def _shortcut_queue_project(self, _: tk.Event) -> str:
        self._queue_current_project()
        return "break"

    def _shortcut_refresh_models(self, _: tk.Event) -> str:
        self._refresh_models()
        return "break"

    def _set_inline_notice(self, message: str, *, level: str = "info", timeout_ms: int = 7000) -> None:
        text = str(message or "").strip()
        if not text:
            return
        if self._inline_notice_label is None:
            return
        style_map = {
            "info": "InlineInfo.TLabel",
            "warn": "InlineWarn.TLabel",
            "error": "InlineErr.TLabel",
        }
        self.inline_notice_var.set(text)
        self._inline_notice_label.configure(style=style_map.get(level, "InlineInfo.TLabel"))
        if self._inline_notice_after_id is not None:
            try:
                self.root.after_cancel(self._inline_notice_after_id)
            except Exception:
                pass
            self._inline_notice_after_id = None
        if timeout_ms > 0:
            self._inline_notice_after_id = self.root.after(timeout_ms, self._clear_inline_notice)

    def _clear_inline_notice(self) -> None:
        self.inline_notice_var.set("")
        self._inline_notice_after_id = None

    def tr(self, key: str, default: str, **fmt: Any) -> str:
        return self.i18n.t(key, default, **fmt)

    def _msg_info(self, message: str, title: Optional[str] = None) -> None:
        _ = title
        text = str(message or "").strip()
        if not text:
            return
        self._set_inline_notice(text, level="info")
        self._set_status(text, "ready")

    def _msg_error(self, message: str, title: Optional[str] = None) -> None:
        t = title or self.tr("mb.error", "Error")
        text = str(message or "").strip()
        if text:
            self._set_inline_notice(text, level="error", timeout_ms=10000)
            self._set_status(text, "error")
        messagebox.showerror(t, message)

    def _ask_yes_no(self, message: str, title: Optional[str] = None) -> bool:
        t = title or self.tr("mb.confirm", "Confirm")
        return messagebox.askyesno(t, message)

    def _build_vars(self) -> None:
        self.mode_var = tk.StringVar(value="translate")
        self.provider_var = tk.StringVar(value="ollama")
        self.project_var = tk.StringVar()
        self.profile_var = tk.StringVar()
        self.input_epub_var = tk.StringVar()
        self.output_epub_var = tk.StringVar()
        self.prompt_var = tk.StringVar()
        self.glossary_var = tk.StringVar()
        self.cache_var = tk.StringVar()
        self.debug_dir_var = tk.StringVar(value="debug")
        self.ollama_host_var = tk.StringVar(value=OLLAMA_HOST_DEFAULT)
        self.google_api_key_var = tk.StringVar()
        self.model_var = tk.StringVar()
        self.batch_max_segs_var = tk.StringVar(value="6")
        self.batch_max_chars_var = tk.StringVar(value="12000")
        self.sleep_var = tk.StringVar(value="0")
        self.timeout_var = tk.StringVar(value="300")
        self.attempts_var = tk.StringVar(value="3")
        self.backoff_var = tk.StringVar(value="5,15,30")
        self.temperature_var = tk.StringVar(value="0.1")
        self.num_ctx_var = tk.StringVar(value="8192")
        self.num_predict_var = tk.StringVar(value="2048")
        self.tags_var = tk.StringVar(value="p,li,h1,h2,h3,h4,h5,h6,blockquote,dd,dt,figcaption,caption")
        self.use_cache_var = tk.BooleanVar(value=True)
        self.use_glossary_var = tk.BooleanVar(value=True)
        self.checkpoint_var = tk.StringVar(value="0")
        self.tooltip_mode_var = tk.StringVar(value=self.tooltip_mode)
        self.ui_language_var = tk.StringVar(value=self.i18n.lang)
        self.source_lang_var = tk.StringVar(value="en")
        self.target_lang_var = tk.StringVar(value="pl")
        self.command_preview_var = tk.StringVar()
        self.estimate_var = tk.StringVar(value=self.tr("status.estimate.none", "Estymacja: brak"))
        self.queue_status_var = tk.StringVar(value=self.tr("status.queue.idle", "Queue: idle"))
        self.status_counts_var = tk.StringVar(value="idle=0 | pending=0 | running=0 | error=0")
        self.status_var = tk.StringVar(value=self.tr("status.ready", "Gotowe"))
        self.inline_notice_var = tk.StringVar(value="")
        self.progress_text_var = tk.StringVar(value=self.tr("status.progress.zero", "Postęp: 0 / 0"))
        self.phase_var = tk.StringVar(value=self.tr("status.phase.wait", "Etap: oczekiwanie"))
        self.run_metrics_var = tk.StringVar(value=self.tr("status.metrics.none", "Metryki runu: brak"))
        self.progress_value_var = tk.DoubleVar(value=0.0)
        self.global_done = 0
        self.global_total = 0

    def _build_ui(self) -> None:
        self.root.title(self.tr("app.title", APP_TITLE))
        outer = self._create_scrollable_root(padding=self._theme_space("space_lg", 16))
        section_gap = self._theme_space("space_md", 12)
        card_gap = self._theme_space("space_sm", 8)

        ttk.Label(outer, text=self.tr("app.title", APP_TITLE), style="Title.TLabel").pack(anchor="w")
        ttk.Label(
            outer,
            text=self.tr("app.subtitle", "Nowoczesny panel do translacji EPUB (Ollama / Google) z zapisem ustawien i logiem na zywo."),
            style="Sub.TLabel",
        ).pack(anchor="w", pady=(0, section_gap))
        links = ttk.Frame(outer)
        links.pack(anchor="w", pady=(0, section_gap))
        ttk.Button(
            links,
            text=self.tr("button.support_project", "Wesprzyj projekt"),
            command=lambda: self._open_url(SUPPORT_URL),
            style="Primary.TButton",
        ).pack(side="left")
        ttk.Button(
            links,
            text=self.tr("button.repo_online", "Repo online"),
            command=lambda: self._open_url(REPO_URL),
            style="Secondary.TButton",
        ).pack(side="left", padx=(card_gap, 0))
        self._build_first_start_card(outer)

        top = ttk.Frame(outer)
        top.pack(fill="both", expand=True)
        top.columnconfigure(0, weight=3)
        top.columnconfigure(1, weight=2)

        left = ttk.Frame(top)
        left.grid(row=0, column=0, sticky="nsew", padx=(0, section_gap))

        right = ttk.Frame(top)
        right.grid(row=0, column=1, sticky="nsew")

        self._build_project_card(left)
        tabs = ttk.Notebook(left)
        tabs.pack(fill="both", expand=True, pady=(0, 10))
        basic_tab = ttk.Frame(tabs, padding=4)
        adv_tab = ttk.Frame(tabs, padding=4)
        tabs.add(basic_tab, text=self.tr("tab.basic", "Podstawowe"))
        tabs.add(adv_tab, text=self.tr("tab.advanced", "Zaawansowane"))
        self._build_files_card(basic_tab)
        self._build_engine_card(basic_tab)
        self._build_advanced_card(adv_tab)

        self._build_model_card(right)
        self._build_enhance_card(right)
        self._build_run_card(right)
        self._build_log_card(right)

        self._inline_notice_label = ttk.Label(outer, textvariable=self.inline_notice_var, style="InlineInfo.TLabel")
        self._inline_notice_label.pack(fill="x", pady=(section_gap, 0))
        self.status_label = ttk.Label(outer, textvariable=self.status_var, style="StatusReady.TLabel")
        self.status_label.pack(anchor="w", pady=(card_gap, 0))

    def _build_first_start_card(self, parent: ttk.Frame) -> None:
        card = ttk.LabelFrame(parent, text=self.tr("section.first_start", "Pierwsze uruchomienie (wymagane)"), padding=12, style="Card.TLabelframe")
        card.pack(fill="x", pady=(0, self._theme_space("space_md", 12)))

        ttk.Label(
            card,
            text=self.tr(
                "first_start.summary",
                "Aby uruchomic translacje: dla Ollama potrzebna jest instalacja + model, "
                "a dla providerow online poprawny API key i internet.",
            ),
            style="Sub.TLabel",
            justify="left",
            wraplength=1120,
        ).pack(anchor="w")

        self.first_start_box = tk.Text(
            card,
            height=12,
            wrap="word",
            font=("Consolas", 10),
            bg=self._theme_color("surface_bg", "#f8fafc"),
            fg=self._theme_color("text", "#0f172a"),
            insertbackground=self._theme_color("text", "#0f172a"),
            highlightbackground=self._theme_color("border", "#cbd5e1"),
            highlightcolor=self._theme_color("border", "#cbd5e1"),
            relief="solid",
            bd=1,
        )
        self.first_start_box.pack(fill="x", pady=(8, 0))
        self.first_start_box.insert("1.0", self._first_start_setup_text())
        self.first_start_box.configure(state="disabled")

        btns = ttk.Frame(card)
        btns.pack(anchor="w", pady=(8, 0))
        self.copy_setup_btn = ttk.Button(
            btns,
            text=self.tr("button.copy_first_start", "Kopiuj instrukcje pierwszego uruchomienia"),
            command=self._copy_first_start_setup,
            style="Secondary.TButton",
        )
        self.copy_setup_btn.pack(side="left")
        self.open_manual_btn = ttk.Button(
            btns,
            text=self.tr("button.open_manual", "Otworz manual"),
            command=lambda: self._open_path(self.workdir / "MANUAL_PL.md"),
            style="Secondary.TButton",
        )
        self.open_manual_btn.pack(side="left", padx=(self._theme_space("space_sm", 8), 0))

    def _current_platform_label(self) -> str:
        name = platform.system().lower()
        if name.startswith("win"):
            return "Windows"
        if name == "darwin":
            return "macOS"
        return "Linux"

    def _first_start_setup_text(self) -> str:
        lines: List[str] = [
            self.tr("first_start.current_os", "Wykryty system: {name}", name=self._current_platform_label()),
            "",
            self.tr("first_start.need_local", "Lokalny provider (Ollama) wymaga instalacji i modelu:"),
            "",
            "Windows (PowerShell):",
            "  winget install Ollama.Ollama",
            "  ollama pull llama3.1:8b",
            "",
            "Linux:",
            "  curl -fsSL https://ollama.com/install.sh | sh",
            "  ollama pull llama3.1:8b",
            "",
            "macOS:",
            "  brew install ollama",
            "  ollama pull llama3.1:8b",
            "",
            self.tr("first_start.need_online", "Provider online (np. Google Gemini) wymaga API key i internetu:"),
            "",
            "Windows (PowerShell):",
            '  setx GOOGLE_API_KEY "<TWOJ_KLUCZ>"',
            "",
            "Linux / macOS:",
            '  export GOOGLE_API_KEY="<TWOJ_KLUCZ>"',
        ]
        return "\n".join(lines)

    def _copy_first_start_setup(self) -> None:
        try:
            txt = self._first_start_setup_text()
            self.root.clipboard_clear()
            self.root.clipboard_append(txt)
            self._set_status(
                self.tr("status.first_start_copied", "Skopiowano instrukcje pierwszego uruchomienia"),
                "ready",
            )
        except Exception as e:
            self._msg_error(f"{self.tr('err.copy_failed', 'Nie udalo sie skopiowac instrukcji:')}\n{e}")

    def _widget_opt(self, widget: tk.Misc, key: str) -> str:
        try:
            return str(widget.cget(key))
        except Exception:
            return ""

    def _install_tooltips(self) -> None:
        def tip(short: str, long: str = "", risky: bool = False) -> str:
            mode = self.tooltip_mode
            s = (short or "").strip()
            l = (long or "").strip()
            if mode == "short":
                return s
            if mode == "expert":
                return f"{s} {l}".strip() if l else s
            if risky and l:
                return f"{s} {l}".strip()
            return s
        tt = self.tr

        var_tip = {
            str(self.project_var._name): tip(tt("tip.project.short", "Active project."), tt("tip.project.long", "Changing project switches paths, profiles and statuses.")),
            str(self.profile_var._name): tip(tt("tip.profile.short", "Step profile."), tt("tip.profile.long", "Lets you quickly switch presets.")),
            str(self.input_epub_var._name): tip(tt("tip.input.short", "Input EPUB for translation/editing.")),
            str(self.output_epub_var._name): tip(tt("tip.output.short", "Output EPUB."), tt("tip.output.long", "In edit mode this file is modified.")),
            str(self.prompt_var._name): tip(tt("tip.prompt.short", "Prompt controlling translation style."), tt("tip.prompt.long", "Directly impacts tone and output quality."), risky=True),
            str(self.glossary_var._name): tip(tt("tip.glossary.short", "Term glossary for naming consistency.")),
            str(self.cache_var._name): tip(tt("tip.cache.short", "Segment cache JSONL."), tt("tip.cache.long", "Reduces cost and time on resume.")),
            str(self.mode_var._name): tip(tt("tip.mode.short", "Mode: translate or edit.")),
            str(self.provider_var._name): tip(tt("tip.provider.short", "Model provider: Ollama or Google."), tt("tip.provider.long", "Impacts cost, speed and required params."), risky=True),
            str(self.ollama_host_var._name): tip(tt("tip.ollama_host.short", "Ollama API host."), tt("tip.ollama_host.long", "Wrong host blocks model list and local translation."), risky=True),
            str(self.google_api_key_var._name): tip(tt("tip.google_key.short", "Google API key."), tt("tip.google_key.long", "Missing/invalid key prevents Google provider run."), risky=True),
            str(self.batch_max_segs_var._name): tip(tt("tip.batch_segs.short", "Max segments per request."), tt("tip.batch_segs.long", "Higher is faster but raises batch failure risk."), risky=True),
            str(self.batch_max_chars_var._name): tip(tt("tip.batch_chars.short", "Max chars per request."), tt("tip.batch_chars.long", "Controls batch size and stability."), risky=True),
            str(self.sleep_var._name): tip(tt("tip.sleep.short", "Pause between requests (s)."), tt("tip.sleep.long", "Helps avoid throttling/rate limits."), risky=True),
            str(self.timeout_var._name): tip(tt("tip.timeout.short", "Per-request timeout."), tt("tip.timeout.long", "Too low can interrupt large batches."), risky=True),
            str(self.attempts_var._name): tip(tt("tip.attempts.short", "Retry attempts on failure."), tt("tip.attempts.long", "More retries increase resilience but add latency."), risky=True),
            str(self.backoff_var._name): tip(tt("tip.backoff.short", "Retry backoff sequence, e.g. 5,15,30.")),
            str(self.temperature_var._name): tip(tt("tip.temperature.short", "Model temperature."), tt("tip.temperature.long", "Lower=more stable, higher=more creative."), risky=True),
            str(self.num_ctx_var._name): tip(tt("tip.num_ctx.short", "Max context window (mainly Ollama)."), tt("tip.num_ctx.long", "Too low truncates context, too high increases RAM."), risky=True),
            str(self.num_predict_var._name): tip(tt("tip.num_predict.short", "Max response tokens (mainly Ollama)."), tt("tip.num_predict.long", "Too low may truncate output."), risky=True),
            str(self.checkpoint_var._name): tip(tt("tip.checkpoint.short", "Checkpoint every N files."), tt("tip.checkpoint.long", "Enables safe resume after interruption."), risky=True),
            str(self.debug_dir_var._name): tip(tt("tip.debug_dir.short", "Debug logs/artifacts directory.")),
            str(self.tags_var._name): tip(tt("tip.tags.short", "HTML tags used for segmentation."), tt("tip.tags.long", "Changing tags changes what gets translated."), risky=True),
            str(self.source_lang_var._name): tip(tt("tip.source_lang.short", "Source language."), tt("tip.source_lang.long", "Affects translation instructions and TM lookup."), risky=True),
            str(self.target_lang_var._name): tip(tt("tip.target_lang.short", "Target language."), tt("tip.target_lang.long", "Affects prompt, output filename and language guard."), risky=True),
            str(self.use_cache_var._name): tip(tt("tip.use_cache.short", "Enable segment cache.")),
            str(self.use_glossary_var._name): tip(tt("tip.use_glossary.short", "Enable glossary usage.")),
            str(self.tooltip_mode_var._name): tip(tt("tip.tooltip_mode.short", "Tooltip verbosity mode."), tt("tip.tooltip_mode.long", "hybrid: short + details for risky fields.")),
            str(self.ui_language_var._name): tip(tt("tip.ui_language.short", "Application UI language.")),
            str(self.command_preview_var._name): tip(tt("tip.command_preview.short", "Execution command preview.")),
            str(self.estimate_var._name): tip(tt("tip.estimate.short", "Segments/time/cost estimate.")),
            str(self.queue_status_var._name): tip(tt("tip.queue_status.short", "Project queue status.")),
            str(self.progress_text_var._name): tip(tt("tip.progress.short", "Global process progress.")),
            str(self.phase_var._name): tip(tt("tip.phase.short", "Current pipeline phase.")),
            str(self.status_counts_var._name): tip(tt("tip.status_counts.short", "Aggregate project statuses.")),
            str(self.status_var._name): tip(tt("tip.status.short", "Current app status.")),
        }
        text_tip = {
            self.tr("button.support_project", "Wesprzyj projekt"): tt("tip.button.support_project", "Opens voluntary donation page (GitHub Sponsors)."),
            self.tr("button.repo_online", "Repo online"): tt("tip.button.repo_online", "Opens project repository in browser."),
            self.tr("button.copy_first_start", "Kopiuj instrukcje pierwszego uruchomienia"): tt("tip.button.copy_first_start", "Copies first-run setup commands."),
            self.tr("button.open_manual", "Otworz manual"): tt("tip.button.open_manual", "Opens user manual."),
            self.tr("button.new", "Nowy"): tt("tip.button.new", "Creates a new project in SQLite."),
            self.tr("button.save", "Zapisz"): tt("tip.button.save", "Saves project changes and current paths/settings."),
            self.tr("button.delete", "Usuń"): tt("tip.button.delete", "Soft-delete project: hidden from active list, history remains."),
            self.tr("button.delete_hard", "Usuń hard"): tt("tip.button.delete_hard", "Deletes project permanently with run history and QA."),
            self.tr("button.save_as_profile", "Zapisz jako profil"): tt("tip.button.save_as_profile", "Creates profile from current step parameters."),
            self.tr("button.export", "Eksport"): tt("tip.button.export", "Exports project configuration to JSON."),
            self.tr("button.import", "Import"): tt("tip.button.import", "Imports project/profile from JSON."),
            self.tr("provider.ollama", "Ollama (lokalnie)"): tt("tip.provider.ollama", "Local provider, no API cost, depends on machine resources."),
            self.tr("provider.google", "Google Gemini API"): tt("tip.provider.google", "Cloud provider, often faster on big batches, paid API."),
            self.tr("button.refresh_models", "Odśwież listę modeli"): tt("tip.button.refresh_models", "Fetches model list from selected provider."),
            self.tr("button.start", "Start translacji"): tt("tip.button.start", "Starts current step for active project."),
            self.tr("button.stop", "Stop"): tt("tip.button.stop", "Stops currently running process."),
            self.tr("button.validate_epub", "Waliduj EPUB"): tt("tip.button.validate_epub", "Runs EPUB validation after processing."),
            self.tr("button.estimate", "Estymacja"): tt("tip.button.estimate", "Calculates segments/time/cost estimate before start."),
            self.tr("button.queue", "Kolejkuj"): tt("tip.button.queue", "Marks project as pending."),
            self.tr("button.run_next", "Uruchom następny"): tt("tip.button.run_next", "Runs next pending project."),
            self.tr("button.run_all_pending", "Run all pending"): tt("tip.button.run_all_pending", "Runs all pending projects sequentially."),
            self.tr("button.stop_run_all", "Stop run-all"): tt("tip.button.stop_run_all", "Stops run-all after current task."),
            self.tr("button.open_output", "Otwórz output"): tt("tip.button.open_output", "Opens output file/folder in system explorer."),
            self.tr("button.open_cache", "Otwórz cache"): tt("tip.button.open_cache", "Opens cache file location."),
            self.tr("button.clear_debug", "Wyczyść debug"): tt("tip.button.clear_debug", "Clears debug folder artifacts."),
            self.tr("button.add_card_single", "Dodaj wizytówkę (1 EPUB)"): tt("tip.button.add_card_single", "Adds business-card page to one EPUB."),
            self.tr("button.add_card_batch", "Dodaj wizytówkę (folder)"): tt("tip.button.add_card_batch", "Adds business-card page to all EPUB in folder."),
            self.tr("button.remove_cover", "Usuń okładkę"): tt("tip.button.remove_cover", "Removes cover image/resources from EPUB."),
            self.tr("button.remove_graphics_pattern", "Usuń grafiki (pattern)"): tt("tip.button.remove_graphics_pattern", "Removes images by path/name pattern."),
            self.tr("button.open_text_editor", "Edytor tekstu EPUB"): tt("tip.button.open_text_editor", "Opens chapter/segment text editor."),
            self.tr("button.undo_last_operation", "Cofnij ostatnią operację"): tt("tip.button.undo_last_operation", "Restores from latest operation backup."),
            self.tr("button.open_studio", "Studio Tools (12)"): tt("tip.button.open_studio", "Opens extended QA/TM/pipeline/plugin tools."),
            self.tr("button.choose", "Wybierz"): tt("tip.button.choose", "Opens file chooser dialog."),
            self.tr("tab.basic", "Podstawowe"): tt("tip.tab.basic", "Tab with core files and engine setup."),
            self.tr("tab.advanced", "Zaawansowane"): tt("tip.tab.advanced", "Tab with quality/retry/checkpoint settings."),
            self.tr("label.tooltip_mode", "Tooltip mode:"): tt("tip.label.tooltip_mode", "Select tooltip verbosity style: short/hybrid/expert."),
            self.tr("label.ui_language", "UI language:"): tt("tip.label.ui_language", "Choose interface language (pl/en/de/fr/es/pt)."),
            self.tr("button.ai_translate_gui", "AI: szkic tłumaczenia GUI"): tt("tip.button.ai_translate_gui", "Generates AI draft translation for GUI labels."),
        }
        object_tip: Dict[int, str] = {
            id(self.status_list): tt("tip.obj.status_list", "List of all projects with their execution status."),
            id(self.history_box): tt("tip.obj.history_box", "Run history for active project (status/progress/message)."),
            id(self.log_box): tt("tip.obj.log_box", "Live process log for diagnostics and progress."),
            id(self.progress_bar): tt("tip.obj.progress_bar", "Global progress bar reported by pipeline."),
            id(self.project_combo): tt("tip.obj.project_combo", "Current project selector."),
            id(self.profile_combo): tt("tip.obj.profile_combo", "Current step profile selector."),
            id(self.model_combo): tt("tip.obj.model_combo", "Available models for selected provider."),
            id(self.status_label): tt("tip.obj.status_label", "Current app status line."),
        }

        def fallback(widget: tk.Misc) -> Optional[str]:
            cls = str(widget.winfo_class())
            if cls in {"TEntry", "Entry"}:
                return tt("tip.fallback.entry", "Configuration input field affecting current pipeline step.")
            if cls in {"TCombobox"}:
                return tt("tip.fallback.combo", "Selection list. Changing option updates step/project configuration.")
            if cls in {"Listbox"}:
                return tt("tip.fallback.listbox", "List of items related to current section.")
            if cls in {"Text"}:
                return tt("tip.fallback.text", "Text area for preview/edit.")
            if cls in {"TRadiobutton", "TCheckbutton"}:
                return tt("tip.fallback.toggle", "Option toggle affecting translation/edit flow.")
            if cls in {"TButton"}:
                return tt("tip.fallback.button", "Action that runs operation for current section.")
            return None

        def resolver(widget: tk.Misc) -> Optional[str]:
            by_obj = object_tip.get(id(widget))
            if by_obj:
                return by_obj
            txt = self._widget_opt(widget, "text").strip()
            if txt and txt in text_tip:
                return text_tip[txt]
            tvar = self._widget_opt(widget, "textvariable").strip()
            if tvar and tvar in var_tip:
                return var_tip[tvar]
            return fallback(widget)

        self._tooltips = install_tooltips(self.root, resolver)

    def _on_tooltip_mode_change(self) -> None:
        mode = str(self.tooltip_mode_var.get() or "hybrid").strip().lower()
        if mode not in {"short", "expert", "hybrid"}:
            mode = "hybrid"
        self.tooltip_mode = mode
        self.tooltip_mode_var.set(mode)
        try:
            self.db.set_setting("tooltip_mode", mode)
        except Exception:
            pass
        self._set_status(self.tr("status.tooltip_mode", "Tooltip mode: {mode}", mode=mode), "ready")

    def _on_ui_language_change(self) -> None:
        code = str(self.ui_language_var.get() or "pl").strip().lower()
        if code not in SUPPORTED_UI_LANGS:
            code = "pl"
        self.ui_language_var.set(code)
        self.i18n.clear_cache()
        self.i18n.set_lang(code)
        try:
            self.db.set_setting("ui_language", code)
        except Exception:
            pass
        for w in list(self.root.winfo_children()):
            try:
                w.destroy()
            except Exception:
                pass
        self._build_ui()
        self._install_tooltips()
        self._refresh_profiles()
        self._refresh_projects(select_current=True)
        self._refresh_status_panel()
        self._refresh_run_history()
        self._set_status(self.tr("status.ui_language", "UI language: {code}", code=code), "ready")

    def _ai_translate_ui_language(self) -> None:
        lang = str(self.ui_language_var.get() or "").strip().lower()
        if lang not in SUPPORTED_UI_LANGS:
            self._msg_error(self.tr("err.ui_lang_invalid", "Wybierz poprawny język UI."), title="AI")
            return
        base = self.i18n.english_map()
        if not base:
            self._msg_error(self.tr("err.locale_base_missing", "Brak bazowego pliku locales/en.json."), title="AI")
            return
        self._set_status(self.tr("status.ai_draft_running", "AI: generating GUI translation draft..."), "running")
        self.root.update_idletasks()
        ok, out, msg = ai_translate_gui_labels(
            base_map=base,
            target_lang_code=lang,
            provider=self.provider_var.get().strip() or "ollama",
            model=self.model_var.get().strip(),
            ollama_host=self.ollama_host_var.get().strip() or OLLAMA_HOST_DEFAULT,
            google_api_key=self._google_api_key(),
            timeout_s=max(20, int(float(self.timeout_var.get().strip() or "60"))),
        )
        if not ok:
            self._set_status(self.tr("status.ai_draft_failed", "AI translation failed"), "error")
            self._msg_error(f"{self.tr('err.ai_draft_failed', 'Nie udało się wygenerować szkicu:')}\n{msg}", title="AI")
            return
        draft_path = self.i18n.save_draft(lang, out)
        apply_now = self._ask_yes_no(
            self.tr("confirm.ai_merge_draft", "Zapisano szkic: {name}\n\nScalić od razu do locales/{lang}.json?", name=draft_path.name, lang=lang),
            title="AI draft",
        )
        if apply_now:
            current = self.i18n.locale_map(lang)
            current.update(out)
            self.i18n.save_locale(lang, current)
            self.i18n.set_lang(lang)
            self._on_ui_language_change()
        self._set_status(self.tr("status.ai_draft_ready", "AI draft ready: {name}", name=draft_path.name), "ok")

    def _on_lang_pair_change(self) -> None:
        src = (self.source_lang_var.get() or "").strip().lower()
        tgt = (self.target_lang_var.get() or "").strip().lower()
        if src not in SUPPORTED_TEXT_LANGS:
            src = "en"
            self.source_lang_var.set(src)
        if tgt not in SUPPORTED_TEXT_LANGS:
            tgt = "pl"
            self.target_lang_var.set(tgt)
        if src == tgt:
            self._set_status(self.tr("status.same_lang_hint", "Source and target are the same - consider edit mode."), "ready")
        self._save_project()
        self._update_command_preview()

    def _build_project_card(self, parent: ttk.Frame) -> None:
        card = ttk.LabelFrame(parent, text=self.tr("section.project_profiles", "Projekt i profile"), padding=12, style="Card.TLabelframe")
        card.pack(fill="x", pady=(0, self._theme_space("space_sm", 8)))

        ttk.Label(card, text=self.tr("label.project", "Projekt:")).grid(row=0, column=0, sticky="w")
        self.project_combo = ttk.Combobox(card, textvariable=self.project_var, state="readonly", style="TCombobox")
        self.project_combo.grid(row=0, column=1, sticky="ew")
        self.project_combo.bind("<<ComboboxSelected>>", lambda _: self._on_project_selected())

        pbtn = ttk.Frame(card)
        pbtn.grid(row=0, column=2, padx=(self._theme_space("space_sm", 8), 0), sticky="w")
        ttk.Button(pbtn, text=self.tr("button.new", "Nowy"), command=self._create_project, style="Secondary.TButton").pack(side="left")
        ttk.Button(
            pbtn,
            text=self.tr("button.save", "Zapisz"),
            command=lambda: self._save_project(notify_missing=True),
            style="Primary.TButton",
        ).pack(side="left", padx=(self._theme_space("space_sm", 8), 0))
        ttk.Button(pbtn, text=self.tr("button.delete", "Usuń"), command=self._delete_project, style="Danger.TButton").pack(side="left", padx=(self._theme_space("space_sm", 8), 0))
        ttk.Button(
            pbtn,
            text=self.tr("button.delete_hard", "Usuń hard"),
            command=self._delete_project_hard,
            style="Danger.TButton",
        ).pack(side="left", padx=(self._theme_space("space_sm", 8), 0))

        ttk.Label(card, text=self.tr("label.step_profile", "Profil kroku:")).grid(row=1, column=0, sticky="w", pady=(8, 0))
        self.profile_combo = ttk.Combobox(card, textvariable=self.profile_var, state="readonly")
        self.profile_combo.grid(row=1, column=1, sticky="ew", pady=(8, 0))
        self.profile_combo.bind("<<ComboboxSelected>>", lambda _: self._on_profile_selected())
        prbtn = ttk.Frame(card)
        prbtn.grid(row=1, column=2, padx=(self._theme_space("space_sm", 8), 0), pady=(8, 0), sticky="w")
        ttk.Button(prbtn, text=self.tr("button.save_as_profile", "Zapisz jako profil"), command=self._create_profile_from_current, style="Secondary.TButton").pack(side="left")
        ttk.Button(prbtn, text=self.tr("button.export", "Eksport"), command=self._export_project, style="Secondary.TButton").pack(side="left", padx=(self._theme_space("space_sm", 8), 0))
        ttk.Button(prbtn, text=self.tr("button.import", "Import"), command=self._import_project, style="Secondary.TButton").pack(side="left", padx=(self._theme_space("space_sm", 8), 0))

        stats = ttk.Frame(card)
        stats.grid(row=2, column=0, columnspan=3, sticky="ew", pady=(8, 0))
        ttk.Label(stats, textvariable=self.status_counts_var, style="Sub.TLabel").pack(anchor="w")
        ttk.Label(
            stats,
            text=self.tr("ui.hint.statuses", "Statusy: T=tlumaczenie, R=redakcja, strzalka pokazuje następny krok."),
            style="Helper.TLabel",
        ).pack(anchor="w", pady=(2, 0))
        self.status_list = tk.Listbox(stats, height=4)
        self.status_list.pack(fill="x", pady=(4, 0))
        self.status_list.configure(
            bg=self._theme_color("surface_bg", "#f8fafc"),
            fg=self._theme_color("text", "#0f172a"),
            highlightbackground=self._theme_color("border", "#cbd5e1"),
            highlightcolor=self._theme_color("border", "#cbd5e1"),
            selectbackground=self._theme_color("btn_secondary_bg", "#e2e8f0"),
            selectforeground=self._theme_color("text", "#0f172a"),
        )

        card.columnconfigure(1, weight=1)

    def _build_files_card(self, parent: ttk.Frame) -> None:
        card = ttk.LabelFrame(parent, text=self.tr("section.files_mode", "Pliki i tryb"), padding=12, style="Card.TLabelframe")
        card.pack(fill="x", pady=(0, self._theme_space("space_sm", 8)))

        ttk.Label(
            card,
            text=self.tr("ui.hint.files", "Najpierw wybierz input/output, potem tryb i języki."),
            style="Helper.TLabel",
        ).grid(row=0, column=0, columnspan=4, sticky="w", pady=(0, self._theme_space("space_sm", 8)))

        self._row_file(card, 1, self.tr("file.input_epub", "Wejściowy EPUB"), self.input_epub_var, [("EPUB", "*.epub")], self._on_input_selected)
        self._row_file(card, 2, self.tr("file.output_epub", "Wyjściowy EPUB"), self.output_epub_var, [("EPUB", "*.epub")])
        self._row_file(card, 3, self.tr("file.prompt", "Prompt"), self.prompt_var, [("TXT", "*.txt")], self._on_prompt_changed)
        self._row_file(card, 4, self.tr("file.glossary", "Słownik"), self.glossary_var, [("TXT", "*.txt")])
        self._row_file(card, 5, self.tr("file.cache", "Cache"), self.cache_var, [("JSONL", "*.jsonl"), ("All", "*.*")])

        ttk.Label(card, text=self.tr("label.mode", "Tryb:")).grid(row=6, column=0, sticky="w", pady=(8, 0))
        mode_box = ttk.Frame(card)
        mode_box.grid(row=6, column=1, sticky="w", pady=(8, 0))
        ttk.Radiobutton(mode_box, text=self.tr("mode.translate", "Tłumaczenie"), value="translate", variable=self.mode_var, command=self._on_mode_change).pack(side="left", padx=(0, 12))
        ttk.Radiobutton(mode_box, text=self.tr("mode.edit", "Redakcja"), value="edit", variable=self.mode_var, command=self._on_mode_change).pack(side="left")

        ttk.Label(card, text=self.tr("label.src_lang", "Język źródłowy:")).grid(row=7, column=0, sticky="w", pady=(8, 0))
        src_combo = ttk.Combobox(card, textvariable=self.source_lang_var, state="readonly", width=12)
        src_combo["values"] = list(SUPPORTED_TEXT_LANGS.keys())
        src_combo.grid(row=7, column=1, sticky="w", pady=(8, 0))
        src_combo.bind("<<ComboboxSelected>>", lambda _: self._on_lang_pair_change())

        ttk.Label(card, text=self.tr("label.tgt_lang", "Język docelowy:")).grid(row=7, column=2, sticky="w", padx=(12, 0), pady=(8, 0))
        tgt_combo = ttk.Combobox(card, textvariable=self.target_lang_var, state="readonly", width=12)
        tgt_combo["values"] = list(SUPPORTED_TEXT_LANGS.keys())
        tgt_combo.grid(row=7, column=3, sticky="w", pady=(8, 0))
        tgt_combo.bind("<<ComboboxSelected>>", lambda _: self._on_lang_pair_change())

        card.columnconfigure(1, weight=1)

    def _build_engine_card(self, parent: ttk.Frame) -> None:
        card = ttk.LabelFrame(parent, text=self.tr("section.engine_batch", "Silnik i parametry batch"), padding=12, style="Card.TLabelframe")
        card.pack(fill="x", pady=(0, self._theme_space("space_sm", 8)))

        ttk.Label(
            card,
            text=self.tr("ui.hint.engine", "Ustaw provider i model. Parametry batch kontrolują stabilność i szybkość."),
            style="Helper.TLabel",
        ).grid(row=0, column=0, columnspan=2, sticky="w", pady=(0, self._theme_space("space_sm", 8)))

        ttk.Label(card, text=self.tr("label.provider", "Provider:")).grid(row=1, column=0, sticky="w")
        pbox = ttk.Frame(card)
        pbox.grid(row=1, column=1, sticky="w")
        ttk.Radiobutton(pbox, text=self.tr("provider.ollama", "Ollama (lokalnie)"), value="ollama", variable=self.provider_var, command=self._on_provider_change).pack(side="left", padx=(0, 12))
        ttk.Radiobutton(pbox, text=self.tr("provider.google", "Google Gemini API"), value="google", variable=self.provider_var, command=self._on_provider_change).pack(side="left")

        ttk.Label(card, text=self.tr("label.ollama_host", "Ollama host:")).grid(row=2, column=0, sticky="w", pady=(8, 0))
        self.ollama_host_entry = ttk.Entry(card, textvariable=self.ollama_host_var)
        self.ollama_host_entry.grid(row=2, column=1, sticky="ew", pady=(8, 0))

        ttk.Label(card, text=self.tr("label.google_api_key", "Google API key (lub env {env_name}):", env_name=GOOGLE_API_KEY_ENV)).grid(row=3, column=0, sticky="w", pady=(8, 0))
        self.google_key_entry = ttk.Entry(card, textvariable=self.google_api_key_var, show="*")
        self.google_key_entry.grid(row=3, column=1, sticky="ew", pady=(8, 0))

        ttk.Label(card, text=self.tr("label.max_segs", "Max segs / request:")).grid(row=4, column=0, sticky="w", pady=(8, 0))
        ttk.Entry(card, textvariable=self.batch_max_segs_var, width=14).grid(row=4, column=1, sticky="w", pady=(8, 0))

        ttk.Label(card, text=self.tr("label.max_chars", "Max chars / request:")).grid(row=5, column=0, sticky="w", pady=(8, 0))
        ttk.Entry(card, textvariable=self.batch_max_chars_var, width=14).grid(row=5, column=1, sticky="w", pady=(8, 0))

        ttk.Label(card, text=self.tr("label.sleep", "Pauza między requestami:")).grid(row=6, column=0, sticky="w", pady=(8, 0))
        ttk.Entry(card, textvariable=self.sleep_var, width=14).grid(row=6, column=1, sticky="w", pady=(8, 0))

        card.columnconfigure(1, weight=1)

    def _build_advanced_card(self, parent: ttk.Frame) -> None:
        card = ttk.LabelFrame(parent, text=self.tr("section.advanced_settings", "Ustawienia zaawansowane"), padding=12, style="Card.TLabelframe")
        card.pack(fill="x")

        ttk.Label(
            card,
            text=self.tr("ui.hint.advanced", "Zmieniaj te pola tylko gdy potrzebujesz strojenia jakości/stabilności."),
            style="Helper.TLabel",
        ).grid(row=0, column=0, columnspan=6, sticky="w", pady=(0, self._theme_space("space_sm", 8)))

        ttk.Label(card, text=self.tr("label.timeout", "Timeout (s):")).grid(row=1, column=0, sticky="w")
        ttk.Entry(card, textvariable=self.timeout_var, width=12).grid(row=1, column=1, sticky="w")

        ttk.Label(card, text=self.tr("label.attempts", "Attempts:")).grid(row=1, column=2, sticky="w", padx=(12, 0))
        ttk.Entry(card, textvariable=self.attempts_var, width=8).grid(row=1, column=3, sticky="w")

        ttk.Label(card, text=self.tr("label.backoff", "Backoff:")).grid(row=1, column=4, sticky="w", padx=(12, 0))
        ttk.Entry(card, textvariable=self.backoff_var, width=12).grid(row=1, column=5, sticky="w")

        ttk.Label(card, text=self.tr("label.temperature", "Temperature:")).grid(row=2, column=0, sticky="w", pady=(8, 0))
        ttk.Entry(card, textvariable=self.temperature_var, width=12).grid(row=2, column=1, sticky="w", pady=(8, 0))

        ttk.Label(card, text=self.tr("label.num_ctx", "Num ctx:")).grid(row=2, column=2, sticky="w", padx=(12, 0), pady=(8, 0))
        ttk.Entry(card, textvariable=self.num_ctx_var, width=10).grid(row=2, column=3, sticky="w", pady=(8, 0))

        ttk.Label(card, text=self.tr("label.num_predict", "Num predict:")).grid(row=2, column=4, sticky="w", padx=(12, 0), pady=(8, 0))
        ttk.Entry(card, textvariable=self.num_predict_var, width=10).grid(row=2, column=5, sticky="w", pady=(8, 0))

        ttk.Label(card, text=self.tr("label.checkpoint", "Checkpoint co N plików:")).grid(row=3, column=0, sticky="w", pady=(8, 0))
        ttk.Entry(card, textvariable=self.checkpoint_var, width=12).grid(row=3, column=1, sticky="w", pady=(8, 0))

        ttk.Label(card, text=self.tr("label.debug_dir", "Debug dir:")).grid(row=3, column=2, sticky="w", padx=(12, 0), pady=(8, 0))
        ttk.Entry(card, textvariable=self.debug_dir_var, width=24).grid(row=3, column=3, columnspan=3, sticky="ew", pady=(8, 0))

        ttk.Label(card, text=self.tr("label.tags", "Tagi:")).grid(row=4, column=0, sticky="w", pady=(8, 0))
        ttk.Entry(card, textvariable=self.tags_var).grid(row=4, column=1, columnspan=5, sticky="ew", pady=(8, 0))

        ttk.Checkbutton(card, text="Użyj cache", variable=self.use_cache_var, command=self._update_command_preview).grid(row=5, column=0, sticky="w", pady=(8, 0))
        ttk.Checkbutton(card, text="Użyj słownika", variable=self.use_glossary_var, command=self._update_command_preview).grid(row=5, column=1, columnspan=2, sticky="w", pady=(8, 0))

        ttk.Label(card, text=self.tr("label.tooltip_mode", "Tooltip mode:")).grid(row=6, column=0, sticky="w", pady=(8, 0))
        tip_combo = ttk.Combobox(card, textvariable=self.tooltip_mode_var, state="readonly", width=14)
        tip_combo["values"] = ["hybrid", "short", "expert"]
        tip_combo.grid(row=6, column=1, sticky="w", pady=(8, 0))
        tip_combo.bind("<<ComboboxSelected>>", lambda _: self._on_tooltip_mode_change())

        ttk.Label(card, text=self.tr("label.ui_language", "Jezyk UI:")).grid(row=6, column=2, sticky="w", padx=(12, 0), pady=(8, 0))
        ui_combo = ttk.Combobox(card, textvariable=self.ui_language_var, state="readonly", width=14)
        ui_combo["values"] = list(SUPPORTED_UI_LANGS.keys())
        ui_combo.grid(row=6, column=3, sticky="w", pady=(8, 0))
        ui_combo.bind("<<ComboboxSelected>>", lambda _: self._on_ui_language_change())
        ttk.Button(
            card,
            text=self.tr("button.ai_translate_gui", "AI: szkic tlumaczenia GUI"),
            command=self._ai_translate_ui_language,
            style="Secondary.TButton",
        ).grid(row=6, column=4, columnspan=2, sticky="w", padx=(12, 0), pady=(8, 0))

        for i in range(6):
            card.columnconfigure(i, weight=1)

    def _build_model_card(self, parent: ttk.Frame) -> None:
        card = ttk.LabelFrame(parent, text=self.tr("section.model", "Model AI"), padding=12, style="Card.TLabelframe")
        card.pack(fill="x", pady=(0, self._theme_space("space_sm", 8)))

        self.model_combo = ttk.Combobox(card, textvariable=self.model_var, state="readonly")
        self.model_combo.grid(row=0, column=0, sticky="ew")
        ttk.Button(card, text=self.tr("button.refresh_models", "Odśwież listę modeli"), command=self._refresh_models, style="Secondary.TButton").grid(row=0, column=1, padx=(8, 0))

        self.model_status = ttk.Label(card, text="", style="Sub.TLabel")
        self.model_status.grid(row=1, column=0, columnspan=2, sticky="w", pady=(6, 0))

        card.columnconfigure(0, weight=1)

    def _build_run_card(self, parent: ttk.Frame) -> None:
        card = ttk.LabelFrame(parent, text=self.tr("section.run", "Uruchomienie"), padding=12, style="Card.TLabelframe")
        card.pack(fill="x", pady=(0, self._theme_space("space_sm", 8)))

        ttk.Label(card, text=self.tr("run.command_preview", "Podgląd komendy:")).pack(anchor="w")
        ttk.Entry(card, textvariable=self.command_preview_var, state="readonly").pack(fill="x", pady=(4, 8))
        ttk.Label(
            card,
            text=self.tr("ui.hint.shortcuts", "Skróty: Ctrl+S zapisz, Ctrl+R start, Ctrl+Q kolejkuj, F5 modele."),
            style="Helper.TLabel",
        ).pack(anchor="w", pady=(0, self._theme_space("space_sm", 8)))

        btns = ttk.Frame(card)
        btns.pack(fill="x")
        self.start_btn = ttk.Button(btns, text=self.tr("button.start", "Start translacji"), style="Primary.TButton", command=self._start_process)
        self.start_btn.pack(side="left")
        self.stop_btn = ttk.Button(btns, text=self.tr("button.stop", "Stop"), command=self._stop_process, state="disabled", style="Danger.TButton")
        self.stop_btn.pack(side="left", padx=(8, 0))
        self.validate_btn = ttk.Button(btns, text=self.tr("button.validate_epub", "Waliduj EPUB"), command=self._start_validation, style="Secondary.TButton")
        self.validate_btn.pack(side="left", padx=(8, 0))
        ttk.Button(btns, text=self.tr("button.estimate", "Estymacja"), command=self._start_estimate, style="Secondary.TButton").pack(side="left", padx=(16, 0))
        ttk.Button(btns, text=self.tr("button.queue", "Kolejkuj"), command=self._queue_current_project, style="Secondary.TButton").pack(side="left", padx=(8, 0))
        ttk.Button(btns, text=self.tr("button.run_next", "Uruchom następny"), command=self._run_next_pending, style="Secondary.TButton").pack(side="left", padx=(8, 0))
        self.run_all_btn = ttk.Button(btns, text=self.tr("button.run_all_pending", "Run all pending"), command=self._start_run_all_pending, style="Secondary.TButton")
        self.run_all_btn.pack(side="left", padx=(8, 0))
        self.stop_run_all_btn = ttk.Button(btns, text=self.tr("button.stop_run_all", "Stop run-all"), command=self._stop_run_all_pending, state="disabled", style="Danger.TButton")
        self.stop_run_all_btn.pack(side="left", padx=(8, 0))

        quick = ttk.Frame(card)
        quick.pack(fill="x", pady=(8, 0))
        ttk.Button(quick, text=self.tr("button.open_output", "Otwórz output"), command=self._open_output, style="Secondary.TButton").pack(side="left")
        ttk.Button(quick, text=self.tr("button.open_cache", "Otwórz cache"), command=self._open_cache, style="Secondary.TButton").pack(side="left", padx=(8, 0))
        ttk.Button(quick, text=self.tr("button.clear_debug", "Wyczyść debug"), command=self._clear_debug, style="Secondary.TButton").pack(side="left", padx=(8, 0))
        ttk.Label(quick, textvariable=self.estimate_var, style="Sub.TLabel").pack(side="right")
        ttk.Label(quick, textvariable=self.queue_status_var, style="Sub.TLabel").pack(side="right", padx=(0, 12))

        progress_wrap = ttk.Frame(card)
        progress_wrap.pack(fill="x", pady=(10, 0))
        ttk.Label(progress_wrap, textvariable=self.progress_text_var, style="Sub.TLabel").pack(anchor="w")
        self.progress_bar = ttk.Progressbar(progress_wrap, mode="determinate", variable=self.progress_value_var, maximum=100.0)
        self.progress_bar.pack(fill="x", pady=(4, 0))
        ttk.Label(progress_wrap, textvariable=self.phase_var, style="Sub.TLabel").pack(anchor="w", pady=(4, 0))

    def _build_enhance_card(self, parent: ttk.Frame) -> None:
        card = ttk.LabelFrame(parent, text=self.tr("section.enhance", "Uładnianie EPUB"), padding=12, style="Card.TLabelframe")
        card.pack(fill="x", pady=(0, self._theme_space("space_sm", 8)))

        row1 = ttk.Frame(card)
        row1.pack(fill="x")
        ttk.Button(row1, text=self.tr("button.add_card_single", "Dodaj wizytówkę (1 EPUB)"), command=self._add_card_single, style="Secondary.TButton").pack(side="left")
        ttk.Button(row1, text=self.tr("button.add_card_batch", "Dodaj wizytówkę (folder)"), command=self._add_card_batch, style="Secondary.TButton").pack(side="left", padx=(8, 0))

        row2 = ttk.Frame(card)
        row2.pack(fill="x", pady=(8, 0))
        ttk.Button(row2, text=self.tr("button.remove_cover", "Usuń okładkę"), command=self._remove_cover, style="Danger.TButton").pack(side="left")
        ttk.Button(row2, text=self.tr("button.remove_graphics_pattern", "Usuń grafiki (pattern)"), command=self._remove_graphics_pattern, style="Danger.TButton").pack(side="left", padx=(8, 0))

        row3 = ttk.Frame(card)
        row3.pack(fill="x", pady=(8, 0))
        ttk.Button(row3, text=self.tr("button.open_text_editor", "Edytor tekstu EPUB"), command=self._open_text_editor, style="Secondary.TButton").pack(side="left")
        ttk.Button(row3, text=self.tr("button.undo_last_operation", "Cofnij ostatnią operację"), command=self._undo_last_operation, style="Secondary.TButton").pack(side="left", padx=(8, 0))
        ttk.Button(row3, text=self.tr("button.open_studio", "Studio Tools (12)"), command=self._open_studio_tools, style="Secondary.TButton").pack(side="left", padx=(8, 0))

    def _build_log_card(self, parent: ttk.Frame) -> None:
        card = ttk.LabelFrame(parent, text=self.tr("section.log", "Log"), padding=12, style="Card.TLabelframe")
        card.pack(fill="both", expand=True)
        hist = ttk.Frame(card)
        hist.pack(fill="x", pady=(0, 8))
        ttk.Label(hist, text=self.tr("history.title", "Ostatnie akcje (timeline projektu):"), style="Sub.TLabel").pack(anchor="w")
        ttk.Label(hist, textvariable=self.run_metrics_var, style="Sub.TLabel").pack(anchor="w", pady=(2, 4))
        self.history_box = tk.Listbox(hist, height=5)
        self.history_box.pack(fill="x")
        self.history_box.configure(
            bg=self._theme_color("surface_bg", "#f8fafc"),
            fg=self._theme_color("text", "#0f172a"),
            highlightbackground=self._theme_color("border", "#cbd5e1"),
            highlightcolor=self._theme_color("border", "#cbd5e1"),
            selectbackground=self._theme_color("btn_secondary_bg", "#e2e8f0"),
            selectforeground=self._theme_color("text", "#0f172a"),
        )
        self.log_box = ScrolledText(
            card,
            height=20,
            font=("Consolas", 10),
            bg=self._theme_color("surface_bg", "#f8fafc"),
            fg=self._theme_color("text", "#0f172a"),
            insertbackground=self._theme_color("text", "#0f172a"),
            relief="solid",
            bd=1,
            highlightbackground=self._theme_color("border", "#cbd5e1"),
            highlightcolor=self._theme_color("border", "#cbd5e1"),
        )
        self.log_box.pack(fill="both", expand=True)
        self.log_box.configure(state="disabled")

    def _refresh_projects(self, select_current: bool = False) -> None:
        self._projects_refresh_seq += 1
        seq = self._projects_refresh_seq

        def worker() -> None:
            rows: List[Any] = []
            escalated = 0
            try:
                db = ProjectDB(SQLITE_FILE)
                try:
                    escalated = db.escalate_overdue_findings()
                    rows = db.list_projects_with_stage_summary()
                finally:
                    db.close()
            except Exception:
                LOG.warning("Failed to refresh project list in background.", exc_info=True)
                rows = []
                escalated = 0
            self.root.after(0, lambda: self._apply_projects_refresh(seq, rows, escalated, select_current))

        threading.Thread(target=worker, daemon=True).start()

    def _apply_projects_refresh(self, seq: int, rows: List[Any], escalated: int, select_current: bool) -> None:
        if seq != self._projects_refresh_seq:
            return
        if escalated > 0:
            log_event_jsonl(self.events_log_path, "qa_escalation", {"count": escalated})
            self.db.log_audit_event("qa_escalation", {"count": escalated})
        self.project_name_to_id = {}
        names: List[str] = []
        for r in rows:
            if str(r["status"]) == "deleted":
                continue
            name = str(r["name"])
            names.append(name)
            self.project_name_to_id[name] = int(r["id"])
        self.project_combo["values"] = names
        if not names:
            self.project_var.set("")
            self.current_project_id = None
            self._refresh_status_panel(rows)
            return
        if select_current and self.current_project_id is not None:
            for n, pid in self.project_name_to_id.items():
                if pid == self.current_project_id:
                    self.project_var.set(n)
                    self._on_project_selected()
                    self._refresh_status_panel(rows)
                    return
        current = self.project_var.get().strip()
        if current not in self.project_name_to_id:
            self.project_var.set(names[0])
        self._on_project_selected()
        self._refresh_status_panel(rows)

    def _normalize_project_status(self, value: str) -> str:
        key = str(value or "idle").strip().lower() or "idle"
        aliases = {
            "none": "idle",
            "ready": "idle",
            "queued": "pending",
            "queue": "pending",
            "needs_review": "error",
            "failed": "error",
            "fail": "error",
            "done": "ok",
            "success": "ok",
        }
        if key in {"idle", "pending", "running", "error", "ok"}:
            return key
        return aliases.get(key, "idle")

    def _normalize_stage_status(self, value: str) -> str:
        key = str(value or "none").strip().lower() or "none"
        aliases = {
            "queued": "pending",
            "queue": "pending",
            "in_progress": "running",
            "done": "ok",
            "success": "ok",
            "fail": "error",
            "failed": "error",
        }
        if key in {"none", "idle", "pending", "running", "ok", "error"}:
            return key
        return aliases.get(key, "none")

    def _stage_status_label(self, value: str) -> str:
        return self._normalize_stage_status(value)

    def _next_action_label(self, value: str) -> str:
        m = {
            "done": "koniec",
            "translate": "T",
            "translate_retry": "T!",
            "edit": "R",
            "edit_retry": "R!",
            "running:translate": "run T",
            "running:edit": "run R",
            "pending:translate": "q T",
            "pending:edit": "q R",
        }
        key = str(value or "").strip().lower()
        return m.get(key, key or "-")

    def _short_text(self, value: str, max_len: int = 42) -> str:
        text = str(value or "").strip()
        if max_len <= 3 or len(text) <= max_len:
            return text
        return text[: max_len - 3] + "..."

    def _refresh_status_panel(self, rows: Optional[List[Any]] = None) -> None:
        if rows is None:
            rows = self.db.list_projects_with_stage_summary()
        counts = {"idle": 0, "pending": 0, "running": 0, "error": 0}
        self.status_list.delete(0, "end")
        for r in rows:
            raw_status = str(r.get("status") or "idle")
            if raw_status == "deleted":
                continue
            st = self._normalize_project_status(raw_status)
            counts[st] = counts.get(st, 0) + 1
            name = str(r.get("name") or "-")
            step = str(r.get("active_step") or "-").strip().lower() or "-"
            book = str(r.get("book") or "-")
            name_short = self._short_text(name, 34)
            book_short = self._short_text(book, 44)
            tr = r.get("translate") if isinstance(r.get("translate"), dict) else {}
            ed = r.get("edit") if isinstance(r.get("edit"), dict) else {}
            t_done = int(tr.get("done", 0) or 0)
            t_total = int(tr.get("total", 0) or 0)
            r_done = int(ed.get("done", 0) or 0)
            r_total = int(ed.get("total", 0) or 0)
            t_status = self._stage_status_label(str(tr.get("status", "none")))
            r_status = self._stage_status_label(str(ed.get("status", "none")))
            next_action = self._next_action_label(str(r.get("next_action") or ""))
            self.status_list.insert(
                "end",
                f"{name_short} | {st}/{step} | ks={book_short} | "
                f"T:{t_done}/{t_total} {t_status} | R:{r_done}/{r_total} {r_status} | -> {next_action}",
            )
        self.status_counts_var.set(
            f"idle={counts.get('idle',0)} | pending={counts.get('pending',0)} | "
            f"running={counts.get('running',0)} | error={counts.get('error',0)}"
        )

    def _refresh_profiles(self) -> None:
        rows = self.db.list_profiles()
        self.profile_name_to_id = {}
        names: List[str] = []
        for r in rows:
            name = str(r["name"])
            names.append(name)
            self.profile_name_to_id[name] = int(r["id"])
        self.profile_combo["values"] = names
        if not names:
            self.profile_var.set("")
            return
        current = self.profile_var.get().strip()
        if current not in self.profile_name_to_id:
            self.profile_var.set(names[0])

    def _default_project_values(self, source_epub: Path) -> Dict[str, Any]:
        stem = source_epub.stem
        src_lang = (self.source_lang_var.get() or "en").strip().lower()
        tgt_lang = (self.target_lang_var.get() or "pl").strip().lower()
        prompt_translate = str((self.workdir / "prompt.txt")) if (self.workdir / "prompt.txt").exists() else ""
        prompt_edit = str((self.workdir / "prompt_redakcja.txt")) if (self.workdir / "prompt_redakcja.txt").exists() else ""
        gloss = self._find_glossary(self.workdir)
        profiles = self.db.list_profiles()
        profile_translate = None
        profile_edit = None
        for p in profiles:
            if p["name"] == "Google-fast":
                profile_translate = int(p["id"])
            if p["name"] == "Ollama-quality":
                profile_edit = int(p["id"])
        return {
            "input_epub": str(source_epub),
            "output_translate_epub": str(source_epub.with_name(f"{stem}_{tgt_lang}.epub")),
            "output_edit_epub": str(source_epub.with_name(f"{stem}_{tgt_lang}_redakcja.epub")),
            "prompt_translate": prompt_translate,
            "prompt_edit": prompt_edit or prompt_translate,
            "glossary_path": str(gloss) if gloss else "",
            "cache_translate_path": str(source_epub.with_name(f"cache_{stem}.jsonl")),
            "cache_edit_path": str(source_epub.with_name(f"cache_{stem}_redakcja.jsonl")),
            "profile_translate_id": profile_translate,
            "profile_edit_id": profile_edit or profile_translate,
            "active_step": "translate",
            "status": "idle",
            "source_lang": src_lang,
            "target_lang": tgt_lang,
        }

    def _create_project(self) -> None:
        name = simple_prompt(self.root, "Nowy projekt", "Nazwa projektu:")
        if not name:
            return
        name = name.strip()
        if not name:
            return
        source = self.input_epub_var.get().strip()
        src = Path(source) if source else (next(iter(sorted(self.workdir.glob("*.epub"))), self.workdir / f"{name}.epub"))
        vals = self._default_project_values(src)
        try:
            pid = self.db.create_project(name, vals)
        except Exception as e:
            self._msg_error(f"{self.tr('err.project_create', 'Nie udało się utworzyć projektu:')}\n{e}")
            return
        self.current_project_id = pid
        self.db.set_setting("active_project_id", pid)
        self._refresh_projects(select_current=True)
        self._set_status(self.tr("status.project_created", "Project created: {name}", name=name), "ready")

    def _delete_project(self) -> None:
        if self.current_project_id is None:
            return
        answer = self._ask_yes_no(
            self.tr("confirm.project_delete_soft", "Usunąć projekt z listy? (historia zostanie zachowana)"),
            title=self.tr("title.project_delete", "Usuń projekt"),
        )
        if not answer:
            return
        self.db.delete_project(self.current_project_id, hard=False)
        self.current_project_id = None
        self._refresh_projects(select_current=False)
        self._set_status(self.tr("status.project_deleted_soft", "Project removed from list"), "ready")

    def _delete_project_hard(self) -> None:
        if self.current_project_id is None:
            return
        answer = self._ask_yes_no(
            self.tr("confirm.project_delete_hard", "Usunąć projekt trwale razem z historią i TM powiązanym z projektem?"),
            title=self.tr("title.project_delete_hard", "Usuń hard"),
        )
        if not answer:
            return
        self.db.delete_project(self.current_project_id, hard=True)
        self.current_project_id = None
        self._refresh_projects(select_current=False)
        self.history_box.delete(0, "end")
        self._set_status(self.tr("status.project_deleted_hard", "Project deleted permanently"), "ready")

    def _queue_current_project(self) -> None:
        if self.current_project_id is None:
            self._msg_info(self.tr("info.select_project", "Wybierz projekt."))
            return
        step = self.mode_var.get().strip() or "translate"
        self._save_project()
        self.db.mark_project_pending(self.current_project_id, step)
        self._refresh_projects(select_current=True)
        self._set_status(self.tr("status.project_queued", "Project queued ({step})", step=step), "ready")

    def _run_next_pending(self) -> None:
        self._run_next_pending_internal(show_messages=True)

    def _run_next_pending_internal(self, show_messages: bool) -> bool:
        if self.proc is not None:
            if show_messages:
                self._msg_info(self.tr("info.process_running", "Proces już działa."))
            return False
        nxt = self.db.get_next_pending_project()
        if nxt is None:
            self._set_status(self.tr("status.no_pending", "No pending projects"), "ready")
            self.queue_status_var.set(self.tr("status.queue.empty", "Queue: empty"))
            return False
        self.current_project_id = int(nxt["id"])
        self._refresh_projects(select_current=True)
        if self.run_all_active:
            self.queue_status_var.set(self.tr("status.queue.running", "Queue: running"))
        self._start_process()
        return True

    def _start_run_all_pending(self) -> None:
        if self.run_all_active:
            return
        self.run_all_active = True
        self.queue_status_var.set(self.tr("status.queue.running_all", "Queue: running all pending"))
        self.run_all_btn.configure(state="disabled")
        self.stop_run_all_btn.configure(state="normal")
        started = self._run_next_pending_internal(show_messages=False)
        if not started and self.proc is None:
            self.run_all_active = False
            self.queue_status_var.set(self.tr("status.queue.idle", "Queue: idle"))
            self.run_all_btn.configure(state="normal")
            self.stop_run_all_btn.configure(state="disabled")

    def _stop_run_all_pending(self) -> None:
        self.run_all_active = False
        self.queue_status_var.set(self.tr("status.queue.stopping", "Queue: stopping after current task"))
        self.run_all_btn.configure(state="normal")
        self.stop_run_all_btn.configure(state="disabled")

    def _continue_run_all(self) -> None:
        if not self.run_all_active:
            self.queue_status_var.set(self.tr("status.queue.idle", "Queue: idle"))
            return
        started = self._run_next_pending_internal(show_messages=False)
        if not started:
            self.run_all_active = False
            self.queue_status_var.set(self.tr("status.queue.finished", "Queue: finished"))
            self.run_all_btn.configure(state="normal")
            self.stop_run_all_btn.configure(state="disabled")

    def _format_ts(self, ts: Optional[int]) -> str:
        if ts is None:
            return "-"
        try:
            return datetime.datetime.fromtimestamp(int(ts)).strftime("%Y-%m-%d %H:%M:%S")
        except Exception:
            return str(ts)

    def _refresh_run_history(self) -> None:
        self.history_box.delete(0, "end")
        if self.current_project_id is None:
            self.run_metrics_var.set(self.tr("status.metrics.none", "Metryki runu: brak"))
            return
        rows = self.db.recent_runs(self.current_project_id, limit=20)
        for r in rows:
            step = str(r["step"] or "-")
            status = self._normalize_stage_status(str(r["status"] or "none"))
            done = int(r["global_done"] or 0)
            total = int(r["global_total"] or 0)
            msg = str(r["message"] or "")
            line = (
                f"[{self._format_ts(int(r['started_at']))}] "
                f"{step} | {status} | {done}/{total} | {msg}"
            )
            self.history_box.insert("end", line)
        if not rows:
            self.run_metrics_var.set(self.tr("status.metrics.none", "Metryki runu: brak"))
            return
        last = rows[0]
        started = int(last["started_at"] or 0)
        finished = int(last["finished_at"] or 0) if last["finished_at"] is not None else 0
        duration_s: Optional[int] = max(0, finished - started) if started and finished else None
        parsed = self._parse_metrics_blob(str(last["message"] or ""))
        done = int(last["global_done"] or int(parsed.get("done", 0) or 0))
        total = int(last["global_total"] or int(parsed.get("total", 0) or 0))
        cache_hits = int(parsed.get("cache_hits", 0) or 0)
        tm_hits = int(parsed.get("tm_hits", 0) or 0)
        reuse_hits = int(parsed.get("reuse_hits", cache_hits + tm_hits) or 0)
        reuse_rate = float(parsed.get("reuse_rate", 0.0) or 0.0)
        if total > 0 and reuse_rate <= 0.0 and reuse_hits > 0:
            reuse_rate = (reuse_hits / total) * 100.0
        status = self._normalize_stage_status(str(last["status"] or "none"))
        step = str(last["step"] or "-")
        self.run_metrics_var.set(
            f"Ostatni run: {step}/{status} | czas={self._format_duration(duration_s)} | "
            f"seg={done}/{total} | cache={cache_hits} | tm={tm_hits} | reuse={reuse_rate:.1f}%"
        )

    def _export_project(self) -> None:
        if self.current_project_id is None:
            self._msg_info(self.tr("info.select_project", "Wybierz projekt."))
            return
        payload = self.db.export_project(self.current_project_id)
        if payload is None:
            self._msg_error(self.tr("err.project_export", "Nie udało się wyeksportować projektu."))
            return
        path = filedialog.asksaveasfilename(
            title="Eksport projektu",
            initialdir=str(self.workdir),
            defaultextension=".json",
            filetypes=[("JSON", "*.json"), ("All", "*.*")],
        )
        if not path:
            return
        try:
            Path(path).write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
            self._set_status(self.tr("status.project_exported", "Project exported: {name}", name=Path(path).name), "ready")
        except Exception as e:
            self._msg_error(f"{self.tr('err.export_failed', 'Eksport nieudany:')}\n{e}")

    def _import_project(self) -> None:
        path = filedialog.askopenfilename(
            title="Import projektu",
            initialdir=str(self.workdir),
            filetypes=[("JSON", "*.json"), ("All", "*.*")],
        )
        if not path:
            return
        try:
            payload = json.loads(Path(path).read_text(encoding="utf-8"))
            pid = self.db.import_project(payload)
        except Exception as e:
            self._msg_error(f"{self.tr('err.import_failed', 'Import nieudany:')}\n{e}")
            return
        self.current_project_id = pid
        self.db.set_setting("active_project_id", pid)
        self._refresh_projects(select_current=True)
        self._set_status(self.tr("status.project_imported", "Project imported: {name}", name=Path(path).name), "ready")

    def _save_step_values(self, step: str) -> None:
        self.step_values.setdefault(step, {})
        self.step_values[step]["output"] = self.output_epub_var.get().strip()
        self.step_values[step]["prompt"] = self.prompt_var.get().strip()
        self.step_values[step]["cache"] = self.cache_var.get().strip()
        self.step_values[step]["profile_name"] = self.profile_var.get().strip()

    def _load_step_values(self, step: str) -> None:
        vals = self.step_values.get(step) or {}
        self.output_epub_var.set(vals.get("output", ""))
        self.prompt_var.set(vals.get("prompt", ""))
        self.cache_var.set(vals.get("cache", ""))
        profile_name = vals.get("profile_name", "")
        if profile_name and profile_name in self.profile_name_to_id:
            self.profile_var.set(profile_name)
            self._on_profile_selected()

    def _on_project_selected(self) -> None:
        name = self.project_var.get().strip()
        if not name or name not in self.project_name_to_id:
            return
        self.i18n.clear_cache()
        pid = self.project_name_to_id[name]
        row = self.db.get_project(pid)
        if row is None:
            return
        self.current_project_id = pid
        self.db.set_setting("active_project_id", pid)
        self.input_epub_var.set(str(row["input_epub"] or ""))
        self.glossary_var.set(str(row["glossary_path"] or ""))
        self.source_lang_var.set(str(row["source_lang"] or "en"))
        self.target_lang_var.set(str(row["target_lang"] or "pl"))
        self.mode_var.set(str(row["active_step"] or "translate"))
        self.last_mode = self.mode_var.get()

        p_trans = self.db.get_profile(int(row["profile_translate_id"])) if row["profile_translate_id"] is not None else None
        p_edit = self.db.get_profile(int(row["profile_edit_id"])) if row["profile_edit_id"] is not None else None
        self.step_values["translate"] = {
            "output": str(row["output_translate_epub"] or ""),
            "prompt": str(row["prompt_translate"] or ""),
            "cache": str(row["cache_translate_path"] or ""),
            "profile_name": str(p_trans["name"]) if p_trans else "",
        }
        self.step_values["edit"] = {
            "output": str(row["output_edit_epub"] or ""),
            "prompt": str(row["prompt_edit"] or ""),
            "cache": str(row["cache_edit_path"] or ""),
            "profile_name": str(p_edit["name"]) if p_edit else "",
        }
        self._load_step_values(self.mode_var.get())
        self._on_provider_change()
        self._update_command_preview()
        self._refresh_run_history()
        self._refresh_status_panel()
        self._set_status(self.tr("status.project_loaded", "Project loaded: {name}", name=name), "ready")

    def _save_project(self, notify_missing: bool = False) -> None:
        if self.current_project_id is None:
            if notify_missing:
                self._msg_info("Najpierw wybierz lub utwórz projekt.")
            return
        step = self.mode_var.get().strip() or "translate"
        self._save_step_values(step)

        pid_t = None
        pid_e = None
        pname_t = self.step_values.get("translate", {}).get("profile_name", "")
        pname_e = self.step_values.get("edit", {}).get("profile_name", "")
        if pname_t in self.profile_name_to_id:
            pid_t = self.profile_name_to_id[pname_t]
        if pname_e in self.profile_name_to_id:
            pid_e = self.profile_name_to_id[pname_e]
        vals = {
            "input_epub": self.input_epub_var.get().strip(),
            "glossary_path": self.glossary_var.get().strip(),
            "output_translate_epub": self.step_values.get("translate", {}).get("output", ""),
            "output_edit_epub": self.step_values.get("edit", {}).get("output", ""),
            "prompt_translate": self.step_values.get("translate", {}).get("prompt", ""),
            "prompt_edit": self.step_values.get("edit", {}).get("prompt", ""),
            "cache_translate_path": self.step_values.get("translate", {}).get("cache", ""),
            "cache_edit_path": self.step_values.get("edit", {}).get("cache", ""),
            "profile_translate_id": pid_t,
            "profile_edit_id": pid_e,
            "active_step": step,
            "source_lang": self.source_lang_var.get().strip().lower(),
            "target_lang": self.target_lang_var.get().strip().lower(),
        }
        self.db.update_project(self.current_project_id, vals)
        self._set_status(self.tr("status.project_saved", "Project saved"), "ready")

    def _on_profile_selected(self) -> None:
        name = self.profile_var.get().strip()
        profile_id = self.profile_name_to_id.get(name)
        if not profile_id:
            return
        row = self.db.get_profile(profile_id)
        if row is None:
            return
        try:
            settings = json.loads(str(row["settings_json"]))
        except Exception:
            settings = {}
        self._apply_settings(settings)
        step = self.mode_var.get().strip() or "translate"
        self.step_values.setdefault(step, {})
        self.step_values[step]["profile_name"] = name
        self._set_status(self.tr("status.profile_loaded", "Profile loaded: {name}", name=name), "ready")

    def _create_profile_from_current(self) -> None:
        name = simple_prompt(self.root, "Profil", "Nazwa nowego profilu:")
        if not name:
            return
        name = name.strip()
        if not name:
            return
        payload = self._serialize_profile()
        try:
            self.db.create_profile(name, payload, is_builtin=0)
        except Exception as e:
            self._msg_error(f"{self.tr('err.profile_save', 'Nie udało się zapisać profilu:')}\n{e}")
            return
        self._refresh_profiles()
        self.profile_var.set(name)
        self._on_profile_selected()

    def _serialize_profile(self) -> dict:
        return {
            "provider": self.provider_var.get(),
            "model": self.model_var.get(),
            "debug_dir": self.debug_dir_var.get(),
            "ollama_host": self.ollama_host_var.get(),
            "batch_max_segs": self.batch_max_segs_var.get(),
            "batch_max_chars": self.batch_max_chars_var.get(),
            "sleep": self.sleep_var.get(),
            "timeout": self.timeout_var.get(),
            "attempts": self.attempts_var.get(),
            "backoff": self.backoff_var.get(),
            "temperature": self.temperature_var.get(),
            "num_ctx": self.num_ctx_var.get(),
            "num_predict": self.num_predict_var.get(),
            "tags": self.tags_var.get(),
            "use_cache": self.use_cache_var.get(),
            "use_glossary": self.use_glossary_var.get(),
            "checkpoint": self.checkpoint_var.get(),
            "tooltip_mode": self.tooltip_mode_var.get(),
            "ui_language": self.ui_language_var.get(),
            "source_lang": self.source_lang_var.get(),
            "target_lang": self.target_lang_var.get(),
        }

    def _open_path(self, p: Path) -> None:
        if not p.exists():
            self._msg_info(f"Nie znaleziono:\n{p}")
            return
        try:
            if platform.system().lower().startswith("win"):
                os.startfile(str(p))  # type: ignore[attr-defined]
            elif platform.system().lower() == "darwin":
                subprocess.Popen(["open", str(p)])
            else:
                subprocess.Popen(["xdg-open", str(p)])
        except Exception as e:
            self._msg_error(f"{self.tr('err.open_failed', 'Nie udało się otworzyć:')}\n{e}")

    def _open_url(self, url: str) -> None:
        u = (url or "").strip()
        if not u:
            return
        try:
            webbrowser.open(u, new=2)
        except Exception as e:
            self._msg_error(f"{self.tr('err.open_failed', 'Nie udało się otworzyć:')}\n{e}")

    def _open_output(self) -> None:
        p = Path(self.output_epub_var.get().strip()) if self.output_epub_var.get().strip() else None
        if p is None:
            return
        self._open_path(p)

    def _open_cache(self) -> None:
        p = Path(self.cache_var.get().strip()) if self.cache_var.get().strip() else None
        if p is None:
            return
        self._open_path(p)

    def _clear_debug(self) -> None:
        d = Path(self.debug_dir_var.get().strip() or "debug")
        if not d.is_absolute():
            d = self.workdir / d
        if not d.exists():
            self._set_status(self.tr("status.debug_dir_missing", "Debug directory missing"), "ready")
            return
        count = 0
        for item in d.iterdir():
            try:
                if item.is_file():
                    item.unlink()
                    count += 1
                elif item.is_dir():
                    shutil.rmtree(item)
                    count += 1
            except Exception:
                continue
        self._set_status(self.tr("status.debug_cleared", "Debug cleared ({count} items)", count=count), "ready")

    def _pick_target_epub(self) -> Optional[Path]:
        cand = self.output_epub_var.get().strip() or self.input_epub_var.get().strip()
        if cand and Path(cand).exists():
            return Path(cand)
        path = filedialog.askopenfilename(
            title="Wybierz EPUB",
            initialdir=str(self.workdir),
            filetypes=[("EPUB", "*.epub")],
        )
        if not path:
            return None
        return Path(path)

    def _preview_and_confirm(self, title: str, lines: List[str]) -> bool:
        body = "\n".join(lines[:30])
        if len(lines) > 30:
            body += f"\n... (+{len(lines)-30} więcej)"
        return self._ask_yes_no(body + "\n\n" + self.tr("confirm.execute_operation", "Wykonać tę operację?"), title=title)

    def _push_operation(self, op: Dict[str, Any]) -> None:
        self.op_history.append(op)
        if len(self.op_history) > 200:
            self.op_history = self.op_history[-200:]

    def _undo_last_operation(self) -> None:
        if not self.op_history:
            self._msg_info("Brak operacji do cofnięcia.")
            return
        op = self.op_history.pop()
        typ = str(op.get("type", ""))
        try:
            if typ == "new_file":
                out = Path(str(op.get("output", "")))
                if out.exists():
                    out.unlink()
                prev_out = str(op.get("prev_output", "")).strip()
                if prev_out:
                    self.output_epub_var.set(prev_out)
                self._set_status(self.tr("status.undo_deleted_generated", "Undo: removed generated EPUB"), "ready")
            elif typ == "backup_restore":
                target = Path(str(op.get("target", "")))
                backup = Path(str(op.get("backup", "")))
                if backup.exists():
                    shutil.copy2(backup, target)
                    self._set_status(self.tr("status.undo_restored_backup", "Undo: restored EPUB backup"), "ready")
                else:
                    self._msg_error(f"Backup nie istnieje:\n{backup}")
            elif typ == "batch_new_files":
                files = op.get("files", [])
                removed = 0
                if isinstance(files, list):
                    for f in files:
                        p = Path(str(f))
                        if p.exists():
                            p.unlink()
                            removed += 1
                self._set_status(self.tr("status.undo_batch_removed", "Undo batch: removed {count} files", count=removed), "ready")
            else:
                self._msg_info("Ten typ operacji nie wspiera cofania.")
        except Exception as e:
            self._msg_error(f"Cofanie nieudane:\n{e}")

    def _add_card_single(self) -> None:
        target = self._pick_target_epub()
        if target is None:
            return
        img = filedialog.askopenfilename(
            title="Wybierz obraz wizytówki",
            initialdir=str(self.workdir),
            filetypes=[("Obrazy", "*.png;*.jpg;*.jpeg;*.webp;*.gif"), ("All", "*.*")],
        )
        if not img:
            return
        title = simple_prompt(self.root, "Wizytówka", "Tytuł wizytówki:") or "Wizytowka"
        out = target.with_name(f"{target.stem}_wizytowka{target.suffix}")
        prev_out = self.output_epub_var.get().strip()
        try:
            prev = preview_add_front_matter(target, Path(img), title=title)
            ok = self._preview_and_confirm(
                "Podgląd: wizytówka",
                [
                    f"EPUB: {prev['epub']}",
                    f"Obraz: {prev['image_file']}",
                    f"Dodane do manifest: {', '.join(prev['add_manifest_items'])}",
                    f"Dodane jako 1. w spine: {prev['add_spine_first']}",
                ],
            )
            if not ok:
                return
        except Exception as e:
            self._msg_error(f"{self.tr('err.dry_run_failed', 'Dry-run failed:')}\n{e}")
            return
        try:
            add_front_matter_card(target, out, Path(img), title=title)
            self.output_epub_var.set(str(out))
            self._push_operation({"type": "new_file", "output": str(out), "prev_output": prev_out})
            self._set_status(self.tr("status.card_added", "Card added: {name}", name=out.name), "ok")
        except Exception as e:
            self._msg_error(f"{self.tr('err.card_add_failed', 'Nie udało się dodać wizytówki:')}\n{e}")

    def _add_card_batch(self) -> None:
        folder = filedialog.askdirectory(title="Folder z EPUB", initialdir=str(self.workdir))
        if not folder:
            return
        img = filedialog.askopenfilename(
            title="Wybierz obraz wizytówki",
            initialdir=str(self.workdir),
            filetypes=[("Obrazy", "*.png;*.jpg;*.jpeg;*.webp;*.gif"), ("All", "*.*")],
        )
        if not img:
            return
        title = simple_prompt(self.root, "Wizytówka", "Tytuł wizytówki (batch):") or "Wizytowka"
        epubs = sorted(Path(folder).glob("*.epub"))
        if not epubs:
            self._msg_info(self.tr("info.no_epubs_in_folder", "No EPUB files in folder."))
            return
        ok = self._preview_and_confirm(
            "Podgląd: batch wizytówka",
            [f"Folder: {folder}", f"Liczba EPUB: {len(epubs)}", f"Obraz: {img}", f"Tytuł: {title}"]
            + [f"- {p.name}" for p in epubs[:10]],
        )
        if not ok:
            return
        results = batch_add_front_matter(Path(folder), Path(img), title=title)
        ok = sum(1 for _, err in results if err is None)
        bad = sum(1 for _, err in results if err is not None)
        created_files = [str(p) for p, err in results if err is None]
        if created_files:
            self._push_operation({"type": "batch_new_files", "files": created_files})
        self._append_log(f"\n[BATCH-WIZYTOWKA] OK={ok} ERR={bad}\n")
        for p, err in results:
            if err:
                self._append_log(f"  ERR: {p} -> {err}\n")
            else:
                self._append_log(f"  OK: {p}\n")
        self._set_status(self.tr("status.card_batch_done", "Card batch finished (OK={ok}, ERR={err})", ok=ok, err=bad), "ready")

    def _remove_cover(self) -> None:
        target = self._pick_target_epub()
        if target is None:
            return
        out = target.with_name(f"{target.stem}_bez_okladki{target.suffix}")
        prev_out = self.output_epub_var.get().strip()
        try:
            prev = preview_remove_images(target, remove_cover=True, pattern=None)
            ok = self._preview_and_confirm(
                "Podgląd: usuń okładkę",
                [
                    f"EPUB: {prev['epub']}",
                    f"Usuwane zasoby obrazów: {prev['remove_paths_count']}",
                    f"Rozdziały dotknięte: {prev['affected_chapters_count']}",
                ] + [f"- {x}" for x in prev["remove_paths"][:10]],
            )
            if not ok:
                return
        except Exception as e:
            self._msg_error(f"{self.tr('err.dry_run_failed', 'Dry-run failed:')}\n{e}")
            return
        try:
            remove_images(target, out, remove_cover=True, pattern=None)
            self.output_epub_var.set(str(out))
            self._push_operation({"type": "new_file", "output": str(out), "prev_output": prev_out})
            self._set_status(self.tr("status.cover_removed", "Cover removed: {name}", name=out.name), "ok")
        except Exception as e:
            self._msg_error(f"{self.tr('err.cover_remove_failed', 'Nie udało się usunąć okładki:')}\n{e}")

    def _remove_graphics_pattern(self) -> None:
        target = self._pick_target_epub()
        if target is None:
            return
        pattern = simple_prompt(self.root, "Usuń grafiki", "Regex dla nazw grafik/href:")
        if not pattern:
            return
        out = target.with_name(f"{target.stem}_bez_grafik{target.suffix}")
        prev_out = self.output_epub_var.get().strip()
        try:
            prev = preview_remove_images(target, remove_cover=False, pattern=pattern)
            ok = self._preview_and_confirm(
                "Podgląd: usuń grafiki",
                [
                    f"EPUB: {prev['epub']}",
                    f"Pattern: {pattern}",
                    f"Usuwane zasoby obrazów: {prev['remove_paths_count']}",
                    f"Rozdziały dotknięte: {prev['affected_chapters_count']}",
                ] + [f"- {x}" for x in prev["remove_paths"][:10]],
            )
            if not ok:
                return
        except Exception as e:
            self._msg_error(f"{self.tr('err.dry_run_failed', 'Dry-run failed:')}\n{e}")
            return
        try:
            remove_images(target, out, remove_cover=False, pattern=pattern)
            self.output_epub_var.set(str(out))
            self._push_operation({"type": "new_file", "output": str(out), "prev_output": prev_out})
            self._set_status(self.tr("status.graphics_removed", "Graphics removed (pattern): {name}", name=out.name), "ok")
        except Exception as e:
            self._msg_error(f"{self.tr('err.graphics_remove_failed', 'Nie udało się usunąć grafik:')}\n{e}")

    def _open_text_editor(self) -> None:
        target = self._pick_target_epub()
        if target is None:
            return
        TextEditorWindow(self, target)

    def _open_studio_tools(self) -> None:
        StudioSuiteWindow(self)

    def _estimate_from_project(self, input_epub: str, cache_p: str) -> str:
        input_epub = (input_epub or "").strip()
        if not input_epub:
            return self.tr("status.estimate.no_input", "Estimate: missing input EPUB")
        p = Path(input_epub)
        if not p.exists():
            return self.tr("status.estimate.input_missing", "Estimate: input EPUB does not exist")
        try:
            with zipfile.ZipFile(p, "r") as zin:
                names = [n for n in zin.namelist() if n.lower().endswith((".xhtml", ".html", ".htm"))]
                segs = 0
                chars = 0
                tag_rx = re.compile(r"<(p|li|h1|h2|h3|h4|h5|h6|blockquote|dd|dt|figcaption|caption)\b", re.IGNORECASE)
                for n in names:
                    raw = zin.read(n).decode("utf-8", errors="replace")
                    segs += len(tag_rx.findall(raw))
                    chars += len(raw)
        except Exception as e:
            return self.tr("status.estimate.epub_error", "Estimate: EPUB error ({err})", err=e)

        cached = 0
        cache_p = (cache_p or "").strip()
        if cache_p and Path(cache_p).exists():
            try:
                with Path(cache_p).open("r", encoding="utf-8", errors="replace") as f:
                    cached = sum(1 for _ in f if _.strip())
            except Exception:
                cached = 0
        todo = max(0, segs - cached)
        avg_seg_chars = max(50, chars // max(segs, 1))
        estimated_tokens = int((todo * avg_seg_chars) / 4)
        cost_hint = estimated_tokens / 1_000_000
        return self.tr(
            "status.estimate.summary",
            "Estimate: seg={segs}, cache={cached}, todo={todo}, ~tok={tok}, cost(M-tok)~{cost}",
            segs=segs,
            cached=cached,
            todo=todo,
            tok=estimated_tokens,
            cost=f"{cost_hint:.2f}",
        )

    def _start_estimate(self) -> None:
        self.estimate_var.set(self.tr("status.estimate.calculating", "Estimate: calculating..."))
        input_epub = self.input_epub_var.get().strip()
        cache_path = self.cache_var.get().strip()

        def worker() -> None:
            out = self._estimate_from_project(input_epub, cache_path)
            self.root.after(0, lambda: self.estimate_var.set(out))

        threading.Thread(target=worker, daemon=True).start()

    def _row_file(
        self,
        parent: ttk.Frame,
        row: int,
        label: str,
        var: tk.StringVar,
        filetypes: List[tuple[str, str]],
        on_change=None,
    ) -> None:
        row_gap = self._theme_space("space_sm", 8)
        ttk.Label(parent, text=label + ":").grid(row=row, column=0, sticky="w", pady=(0, row_gap))
        entry = ttk.Entry(parent, textvariable=var)
        entry.grid(row=row, column=1, sticky="ew", pady=(0, row_gap))

        def pick() -> None:
            start_dir = str(self.workdir)
            path = filedialog.askopenfilename(title=label, initialdir=start_dir, filetypes=filetypes)
            if path:
                var.set(path)
                if on_change:
                    on_change()
                self._update_command_preview()

        ttk.Button(parent, text=self.tr("button.choose", "Wybierz"), command=pick, style="Secondary.TButton").grid(
            row=row,
            column=2,
            padx=(self._theme_space("space_sm", 8), 0),
            pady=(0, row_gap),
        )

    def _load_defaults(self) -> None:
        kr = load_google_api_key_from_keyring()
        env_key = os.environ.get(GOOGLE_API_KEY_ENV, "").strip()
        self.google_api_key_var.set(kr or env_key)

        prompt_default = self.workdir / "prompt.txt"
        prompt_edit_default = self.workdir / "prompt_redakcja.txt"
        if prompt_default.exists():
            self.prompt_var.set(str(prompt_default))
        if prompt_edit_default.exists() and self.mode_var.get() == "edit":
            self.prompt_var.set(str(prompt_edit_default))

        gloss = self._find_glossary(self.workdir)
        if gloss:
            self.glossary_var.set(str(gloss))

        first_epub = sorted(self.workdir.glob("*.epub"))
        if first_epub:
            self.input_epub_var.set(str(first_epub[0]))
            self._on_input_selected()
            if not self.db.list_projects():
                vals = self._default_project_values(first_epub[0])
                try:
                    pid = self.db.create_project(first_epub[0].stem, vals)
                    self.db.set_setting("active_project_id", pid)
                except Exception:
                    pass

        self._on_provider_change()

    def _find_translator(self) -> Path:
        candidates = [
            self.workdir / "tlumacz_ollama_google_ollama.exe",
            self.workdir / "tlumacz_ollama.exe",
            self.workdir / "tlumacz_ollama_google_ollama.py",
            self.workdir / "tlumacz_ollama.py",
        ]
        for c in candidates:
            if c.exists():
                return c
        raise SystemExit("Nie znaleziono pliku tłumacza: tlumacz_ollama_google_ollama(.exe/.py) ani tlumacz_ollama(.exe/.py)")

    def _translator_cmd_prefix(self) -> List[str]:
        # In packaged mode run bundled translator EXE, in dev mode run Python script.
        if self.translator_path.suffix.lower() == ".exe":
            return [self.translator_path.name]
        py = "python"
        if getattr(sys, "frozen", False):
            py = sys.executable
        return [py, "-u", self.translator_path.name]

    def _find_glossary(self, workdir: Path) -> Optional[Path]:
        for name in ["SLOWNIK.txt", "slownik.txt", "Slownik.txt", "Słownik.txt", "SŁOWNIK.txt"]:
            p = workdir / name
            if p.exists():
                return p
        cands = sorted([p for p in workdir.glob("*.txt") if "slownik" in p.name.lower() or "słownik" in p.name.lower()])
        return cands[0] if cands else None

    def _on_input_selected(self) -> None:
        self._suggest_output_and_cache()
        self._save_project()
        self._update_command_preview()

    def _on_prompt_changed(self) -> None:
        step = self.mode_var.get().strip() or "translate"
        self._save_step_values(step)
        self._update_command_preview()

    def _on_mode_change(self) -> None:
        new_mode = self.mode_var.get().strip() or "translate"
        old_mode = self.last_mode
        if old_mode in ("translate", "edit"):
            self._save_step_values(old_mode)

        self._load_step_values(new_mode)
        if not self.prompt_var.get().strip():
            p = self.workdir / ("prompt.txt" if new_mode == "translate" else "prompt_redakcja.txt")
            if p.exists():
                self.prompt_var.set(str(p))
        if not self.output_epub_var.get().strip() or not self.cache_var.get().strip():
            self._suggest_output_and_cache()
        self.last_mode = new_mode
        self._save_project()
        self._update_command_preview()

    def _on_provider_change(self) -> None:
        provider = self.provider_var.get()
        if provider == "ollama":
            self.ollama_host_entry.configure(state="normal")
            self.google_key_entry.configure(state="disabled")
        else:
            self.ollama_host_entry.configure(state="disabled")
            self.google_key_entry.configure(state="normal")
        self._update_command_preview()

    def _suggest_output_and_cache(self) -> None:
        in_path = self.input_epub_var.get().strip()
        if not in_path:
            return
        p = Path(in_path)
        if not p.exists():
            return

        stem = p.stem
        tgt = (self.target_lang_var.get() or "pl").strip().lower()
        if self.mode_var.get() == "translate":
            out_name = f"{stem}_{tgt}.epub"
            cache_name = f"cache_{stem}.jsonl"
        else:
            out_name = f"{stem}_{tgt}_redakcja.epub"
            cache_name = f"cache_{stem}_redakcja.jsonl"

        self.output_epub_var.set(str(p.with_name(out_name)))
        self.cache_var.set(str(p.with_name(cache_name)))
        step = self.mode_var.get().strip() or "translate"
        self._save_step_values(step)

    def _refresh_models(self) -> None:
        self.model_status.configure(text="Pobieram listę modeli...")
        provider = self.provider_var.get().strip()
        ollama_host = self.ollama_host_var.get().strip() or OLLAMA_HOST_DEFAULT
        google_key = self._google_api_key() if provider == "google" else ""

        def worker() -> None:
            try:
                if provider == "ollama":
                    models = list_ollama_models(ollama_host)
                else:
                    if not google_key:
                        raise ValueError(f"Podaj Google API key lub ustaw zmienną środowiskową {GOOGLE_API_KEY_ENV}.")
                    models = list_google_models(google_key)

                if not models:
                    raise ValueError("Brak modeli do wyboru.")

                self.root.after(0, lambda: self._set_models(models))
            except Exception as e:
                err_text = str(e)
                self.root.after(0, lambda msg=err_text: self.model_status.configure(text=f"Błąd: {msg}"))

        threading.Thread(target=worker, daemon=True).start()

    def _set_models(self, models: List[str]) -> None:
        self.model_combo["values"] = models
        if not models:
            self.model_var.set("")
            self.model_status.configure(text="Brak modeli")
            self._update_command_preview()
            return
        if self.model_var.get() not in models:
            self.model_var.set(models[0])
        self.model_status.configure(text=f"Załadowano {len(models)} modeli")
        self._update_command_preview()

    def _google_api_key(self) -> str:
        ui = self.google_api_key_var.get().strip()
        if ui:
            return ui
        kr = load_google_api_key_from_keyring()
        if kr:
            return kr
        return os.environ.get(GOOGLE_API_KEY_ENV, "").strip()

    def _build_command(self) -> List[str]:
        opts = CoreRunOptions(
            provider=self.provider_var.get().strip(),
            input_epub=self.input_epub_var.get().strip(),
            output_epub=self.output_epub_var.get().strip(),
            prompt=self.prompt_var.get().strip(),
            model=self.model_var.get().strip(),
            batch_max_segs=self.batch_max_segs_var.get().strip(),
            batch_max_chars=self.batch_max_chars_var.get().strip(),
            sleep=self.sleep_var.get().strip(),
            timeout=self.timeout_var.get().strip(),
            attempts=self.attempts_var.get().strip(),
            backoff=self.backoff_var.get().strip(),
            temperature=self.temperature_var.get().strip(),
            num_ctx=self.num_ctx_var.get().strip(),
            num_predict=self.num_predict_var.get().strip(),
            tags=self.tags_var.get().strip(),
            checkpoint=self.checkpoint_var.get().strip(),
            debug_dir=self.debug_dir_var.get().strip(),
            source_lang=self.source_lang_var.get().strip().lower(),
            target_lang=self.target_lang_var.get().strip().lower(),
            ollama_host=self.ollama_host_var.get().strip() or OLLAMA_HOST_DEFAULT,
            cache=self.cache_var.get().strip(),
            use_cache=bool(self.use_cache_var.get()),
            glossary=self.glossary_var.get().strip(),
            use_glossary=bool(self.use_glossary_var.get()),
            tm_db=str(SQLITE_FILE),
            tm_project_id=self.current_project_id,
        )
        return core_build_run_command(self._translator_cmd_prefix(), opts, tm_fuzzy_threshold="0.92")

    def _build_validation_command(self, epub_path: str) -> List[str]:
        return core_build_validation_command(self._translator_cmd_prefix(), epub_path, self.tags_var.get().strip())

    def _validate(self) -> Optional[str]:
        required = [
            ("Wejściowy EPUB", self.input_epub_var.get().strip()),
            ("Wyjściowy EPUB", self.output_epub_var.get().strip()),
            ("Prompt", self.prompt_var.get().strip()),
            ("Model", self.model_var.get().strip()),
        ]
        for label, val in required:
            if not val:
                return f"Brak pola: {label}"

        in_file = Path(self.input_epub_var.get().strip())
        if not in_file.exists():
            return f"Nie istnieje plik wejściowy: {in_file}"

        prompt_file = Path(self.prompt_var.get().strip())
        if not prompt_file.exists():
            return f"Nie istnieje plik prompt: {prompt_file}"

        if self.provider_var.get() == "google" and not self._google_api_key():
            return f"Dla Google podaj API key albo ustaw zmienną środowiskową {GOOGLE_API_KEY_ENV}."

        if (self.source_lang_var.get().strip().lower() or "") not in SUPPORTED_TEXT_LANGS:
            return "Nieprawidłowy język źródłowy."
        if (self.target_lang_var.get().strip().lower() or "") not in SUPPORTED_TEXT_LANGS:
            return "Nieprawidłowy język docelowy."

        for num_label, v in [
            ("batch-max-segs", self.batch_max_segs_var.get().strip()),
            ("batch-max-chars", self.batch_max_chars_var.get().strip()),
            ("timeout", self.timeout_var.get().strip()),
            ("attempts", self.attempts_var.get().strip()),
            ("checkpoint", self.checkpoint_var.get().strip()),
        ]:
            try:
                int(v)
            except Exception:
                return f"Pole {num_label} musi być liczbą całkowitą."

        for num_label, v in [
            ("sleep", self.sleep_var.get().strip()),
            ("temperature", self.temperature_var.get().strip()),
        ]:
            try:
                float(v.replace(",", "."))
            except Exception:
                return f"Pole {num_label} musi być liczbą."

        return None

    def _update_command_preview(self) -> None:
        try:
            cmd = self._build_command()
            self.command_preview_var.set(self._redacted_cmd(cmd))
        except Exception:
            self.command_preview_var.set("-")

    def _set_status(self, text: str, state: str) -> None:
        style_map = {
            "ready": "StatusReady.TLabel",
            "running": "StatusRun.TLabel",
            "ok": "StatusOk.TLabel",
            "error": "StatusErr.TLabel",
        }
        self.status_var.set(text)
        self.status_label.configure(style=style_map.get(state, "StatusReady.TLabel"))

    def _append_log(self, text: str) -> None:
        self.log_box.configure(state="normal")
        self.log_box.insert("end", text)
        self.log_box.see("end")
        self.log_box.configure(state="disabled")

    def _process_log_line(self, line: str) -> None:
        s = line.strip()
        if not s:
            return
        self.last_log_at = time.time()
        self._collect_runtime_metrics_from_log(s)

        m = GLOBAL_PROGRESS_RE.search(s)
        if m:
            done = int(m.group(1))
            total = int(m.group(2))
            pct_str = m.group(3).strip()
            detail = m.group(4).strip()
            self.global_done = done
            self.global_total = total
            pct = (done / total) * 100.0 if total > 0 else 0.0
            self.progress_value_var.set(pct)
            self.progress_text_var.set(self.tr("status.progress.runtime", "Progress: {done} / {total} ({pct})", done=done, total=total, pct=pct_str))
            self.phase_var.set(self.tr("status.phase.detail", "Phase: {detail}", detail=detail))
            self._set_status(self.tr("status.translation.running", "Translation in progress..."), "running")
            self._update_live_run_metrics()
            return

        if "=== POST" in s and "GLOBAL" in s:
            self.phase_var.set(self.tr("status.phase.prescan", "Phase: project pre-scan"))
        elif "=== WALIDACJA EPUB ===" in s:
            self.phase_var.set(self.tr("status.phase.validation", "Phase: EPUB validation"))
        elif "[VAL-WARN]" in s:
            self.phase_var.set(self.tr("status.phase.validation_warn", "Phase: validation (warnings)"))
        elif "[VAL-ERR]" in s:
            self.phase_var.set(self.tr("status.phase.validation_err", "Phase: validation (errors)"))
        elif "VALIDATION RESULT: OK" in s:
            self.phase_var.set(self.tr("status.phase.validation_done", "Phase: validation complete"))
        elif "[CHECKPOINT]" in s:
            self.phase_var.set(self.tr("status.phase.checkpoint", "Phase: checkpoint write"))
        elif "[Google]" in s:
            self.phase_var.set(self.tr("status.phase.google", "Phase: Google requests"))
        elif "[Ollama]" in s:
            self.phase_var.set(self.tr("status.phase.ollama", "Phase: Ollama requests"))
        elif "=== KONIEC ===" in s:
            self.phase_var.set(self.tr("status.phase.finalizing", "Phase: finalizing"))
        self._update_live_run_metrics()

    def _poll_log_queue(self) -> None:
        try:
            while True:
                line = self.log_queue.get_nowait()
                self._append_log(line)
                self._process_log_line(line)
        except queue.Empty:
            pass
        self.root.after(80, self._poll_log_queue)

    def _tick_activity(self) -> None:
        if self.proc is None:
            return
        now = time.time()
        if self.last_log_at is not None:
            quiet_for = int(now - self.last_log_at)
            if quiet_for >= 5:
                self.phase_var.set(self.tr("status.phase.waiting_response", "Phase: waiting for response ({sec}s without log)", sec=quiet_for))
        self._update_live_run_metrics()
        self.root.after(1000, self._tick_activity)

    def _start_process(self) -> None:
        err = self._validate()
        if err:
            self._msg_error(err)
            return

        if self.proc is not None:
            self._msg_info(self.tr("info.process_running", "Process is already running."))
            return

        self._save_settings(silent=True)
        self._save_project()
        provider = self.provider_var.get().strip()
        google_api_key = self._google_api_key() if provider == "google" else ""
        run_step = self.mode_var.get().strip() or "translate"
        cmd = self._build_command()
        redacted = self._redacted_cmd(cmd)
        self.global_done = 0
        self.global_total = 0
        self._reset_runtime_metrics()
        self._append_log("\n=== START ===\n")
        self._append_log("Komenda: " + redacted + "\n\n")
        log_event_jsonl(
            self.events_log_path,
            "run_start",
            {"project_id": self.current_project_id, "mode": run_step, "command": redacted},
        )
        self.db.log_audit_event("run_start", {"project_id": self.current_project_id, "mode": run_step})
        if self.current_project_id is not None:
            try:
                self.current_run_id = self.db.start_run(self.current_project_id, run_step, redacted)
            except Exception:
                self.current_run_id = None

        self.progress_value_var.set(0.0)
        self.progress_text_var.set(self.tr("status.progress.zero", "Progress: 0 / 0"))
        self.phase_var.set(self.tr("status.phase.starting", "Phase: starting"))
        self.run_started_at = time.time()
        self.last_log_at = self.run_started_at
        self._update_live_run_metrics()
        self.start_btn.configure(state="disabled")
        self.validate_btn.configure(state="disabled")
        self.stop_btn.configure(state="normal")
        self._set_status(self.tr("status.translation.running", "Translation in progress..."), "running")
        self.root.after(1000, self._tick_activity)

        def runner() -> None:
            runner_db: Optional[ProjectDB] = None
            try:
                runner_db = ProjectDB(SQLITE_FILE)
                env = {**os.environ, "PYTHONUNBUFFERED": "1"}
                if provider == "google":
                    if google_api_key:
                        env[GOOGLE_API_KEY_ENV] = google_api_key
                self.proc = subprocess.Popen(
                    cmd,
                    cwd=str(self.workdir),
                    env=env,
                    stdout=subprocess.PIPE,
                    stderr=subprocess.STDOUT,
                    text=True,
                    encoding="utf-8",
                    errors="replace",
                    bufsize=1,
                )

                assert self.proc.stdout is not None
                for line in self.proc.stdout:
                    self.log_queue.put(line)

                code = self.proc.wait()
                if code == 0:
                    self.log_queue.put("\n=== " + self.tr("log.run_ok", "RUN OK") + " ===\n")
                    self.root.after(0, lambda: self._set_status(self.tr("status.done", "Finished"), "ok"))
                    self.root.after(0, lambda: self.phase_var.set(self.tr("status.phase.done", "Phase: finished")))
                    self.root.after(0, lambda: self.progress_value_var.set(100.0 if self.progress_value_var.get() > 0 else self.progress_value_var.get()))
                    metrics_blob = self._runtime_metrics_blob()
                    if self.current_project_id is not None and run_step == "translate":
                        edit_cfg = self.step_values.get("edit", {})
                        gate_ok, gate_msg = runner_db.qa_gate_status(self.current_project_id, step="translate") if runner_db else (True, "")
                        if not gate_ok:
                            if runner_db:
                                runner_db.update_project(self.current_project_id, {"status": "needs_review"})
                            self.log_queue.put(f"[QA-GATE] {self.tr('log.qa_gate_blocked', 'Auto transition to edit blocked.')}" + f" {gate_msg}\n")
                        elif (edit_cfg.get("output", "") or "").strip() and (edit_cfg.get("prompt", "") or "").strip():
                            if runner_db:
                                runner_db.mark_project_pending(self.current_project_id, "edit")
                                runner_db.update_project(self.current_project_id, {"status": "pending"})
                    if self.current_run_id is not None:
                        if runner_db:
                            runner_db.finish_run(
                                self.current_run_id,
                                status="ok",
                                message=f"Run finished | {metrics_blob}",
                                global_done=self.global_done,
                                global_total=self.global_total,
                            )
                    log_event_jsonl(
                        self.events_log_path,
                        "run_finish",
                        {"project_id": self.current_project_id, "status": "ok", "done": self.global_done, "total": self.global_total},
                    )
                    if runner_db:
                        runner_db.log_audit_event("run_finish", {"project_id": self.current_project_id, "status": "ok"})
                else:
                    self.log_queue.put("\n=== " + self.tr("log.run_error_exit", "RUN ERROR (exit={code})", code=code) + " ===\n")
                    self.root.after(0, lambda: self._set_status(self.tr("status.process_error", "Process error"), "error"))
                    self.root.after(0, lambda: self.phase_var.set(self.tr("status.phase.error", "Phase: error")))
                    metrics_blob = self._runtime_metrics_blob()
                    if self.current_run_id is not None:
                        if runner_db:
                            runner_db.finish_run(
                                self.current_run_id,
                                status="error",
                                message=f"exit={code} | {metrics_blob}",
                                global_done=self.global_done,
                                global_total=self.global_total,
                            )
                    log_event_jsonl(
                        self.events_log_path,
                        "run_finish",
                        {"project_id": self.current_project_id, "status": "error", "done": self.global_done, "total": self.global_total},
                    )
                    if runner_db:
                        runner_db.log_audit_event("run_finish", {"project_id": self.current_project_id, "status": "error"})
            except Exception as e:
                self.log_queue.put(f"\n{self.tr('log.start_error', 'Startup error')}: {e}\n")
                self.root.after(0, lambda: self._set_status(self.tr("status.start_error", "Startup error"), "error"))
                self.root.after(0, lambda: self.phase_var.set(self.tr("status.phase.start_error", "Phase: startup error")))
                metrics_blob = self._runtime_metrics_blob()
                if self.current_run_id is not None:
                    if runner_db:
                        runner_db.finish_run(
                            self.current_run_id,
                            status="error",
                            message=f"{e} | {metrics_blob}",
                            global_done=self.global_done,
                            global_total=self.global_total,
                        )
                log_event_jsonl(
                    self.events_log_path,
                    "run_finish",
                    {"project_id": self.current_project_id, "status": "exception", "error": str(e)},
                )
                if runner_db:
                    runner_db.log_audit_event("run_finish", {"project_id": self.current_project_id, "status": "exception"})
            finally:
                if runner_db is not None:
                    runner_db.close()
                self.current_run_id = None
                self.proc = None
                self.run_started_at = None
                self.last_log_at = None
                self.root.after(0, self._refresh_projects)
                self.root.after(0, self._refresh_run_history)
                self.root.after(0, lambda: self.start_btn.configure(state="normal"))
                self.root.after(0, lambda: self.validate_btn.configure(state="normal"))
                self.root.after(0, lambda: self.stop_btn.configure(state="disabled"))
                if self.run_all_active:
                    self.root.after(200, self._continue_run_all)

        threading.Thread(target=runner, daemon=True).start()

    def _start_validation(self) -> None:
        if self.proc is not None:
            self._msg_info(self.tr("info.process_running", "Process is already running."))
            return

        out_file = Path(self.output_epub_var.get().strip()) if self.output_epub_var.get().strip() else None
        in_file = Path(self.input_epub_var.get().strip()) if self.input_epub_var.get().strip() else None
        target: Optional[Path] = None

        if out_file and out_file.exists():
            target = out_file
        elif in_file and in_file.exists():
            target = in_file

        if target is None:
            self._msg_error(self.tr("err.validation_no_epub", "No EPUB for validation (output or input)."))
            return

        cmd = self._build_validation_command(str(target))
        self._append_log("\n=== START WALIDACJI ===\n")
        self._append_log("Komenda: " + " ".join(quote_arg(x) for x in cmd) + "\n\n")
        log_event_jsonl(self.events_log_path, "validation_start", {"project_id": self.current_project_id, "target": str(target)})
        self.db.log_audit_event("validation_start", {"project_id": self.current_project_id, "target": str(target)})
        if self.current_project_id is not None:
            try:
                self.current_run_id = self.db.start_run(self.current_project_id, "validate", " ".join(quote_arg(x) for x in cmd))
            except Exception:
                self.current_run_id = None

        self.run_started_at = time.time()
        self.last_log_at = self.run_started_at
        self._reset_runtime_metrics()
        self._update_live_run_metrics()
        self.progress_value_var.set(0.0)
        self.progress_text_var.set(self.tr("status.progress.validation", "Progress: validation"))
        self.phase_var.set(self.tr("status.phase.validation_starting", "Phase: starting validation"))
        self.start_btn.configure(state="disabled")
        self.validate_btn.configure(state="disabled")
        self.stop_btn.configure(state="normal")
        self._set_status(self.tr("status.validation.running", "Validation in progress..."), "running")
        self.root.after(1000, self._tick_activity)

        def runner() -> None:
            runner_db: Optional[ProjectDB] = None
            try:
                runner_db = ProjectDB(SQLITE_FILE)
                self.proc = subprocess.Popen(
                    cmd,
                    cwd=str(self.workdir),
                    env={**os.environ, "PYTHONUNBUFFERED": "1"},
                    stdout=subprocess.PIPE,
                    stderr=subprocess.STDOUT,
                    text=True,
                    encoding="utf-8",
                    errors="replace",
                    bufsize=1,
                )

                assert self.proc.stdout is not None
                for line in self.proc.stdout:
                    self.log_queue.put(line)

                code = self.proc.wait()
                if code == 0:
                    self.log_queue.put("\n=== " + self.tr("log.validation_ok", "VALIDATION OK") + " ===\n")
                    self.root.after(0, lambda: self._set_status(self.tr("status.validation.ok", "Validation OK"), "ok"))
                    self.root.after(0, lambda: self.phase_var.set(self.tr("status.phase.validation_done", "Phase: validation complete")))
                    metrics_blob = self._runtime_metrics_blob()
                    if self.current_run_id is not None:
                        if runner_db:
                            runner_db.finish_run(self.current_run_id, status="ok", message=f"Validation OK | {metrics_blob}")
                    log_event_jsonl(self.events_log_path, "validation_finish", {"project_id": self.current_project_id, "status": "ok"})
                    if runner_db:
                        runner_db.log_audit_event("validation_finish", {"project_id": self.current_project_id, "status": "ok"})
                else:
                    self.log_queue.put("\n=== " + self.tr("log.validation_fail_exit", "VALIDATION FAILED (exit={code})", code=code) + " ===\n")
                    self.root.after(0, lambda: self._set_status(self.tr("status.validation.error", "Validation error"), "error"))
                    self.root.after(0, lambda: self.phase_var.set(self.tr("status.phase.validation_error_done", "Phase: validation finished with errors")))
                    metrics_blob = self._runtime_metrics_blob()
                    if self.current_run_id is not None:
                        if runner_db:
                            runner_db.finish_run(self.current_run_id, status="error", message=f"Validation exit={code} | {metrics_blob}")
                    log_event_jsonl(self.events_log_path, "validation_finish", {"project_id": self.current_project_id, "status": "error", "exit": code})
                    if runner_db:
                        runner_db.log_audit_event("validation_finish", {"project_id": self.current_project_id, "status": "error"})
            except Exception as e:
                self.log_queue.put(f"\n{self.tr('log.validation_start_error', 'Validation startup error')}: {e}\n")
                self.root.after(0, lambda: self._set_status(self.tr("status.start_error", "Startup error"), "error"))
                metrics_blob = self._runtime_metrics_blob()
                if self.current_run_id is not None:
                    if runner_db:
                        runner_db.finish_run(self.current_run_id, status="error", message=f"{e} | {metrics_blob}")
                log_event_jsonl(self.events_log_path, "validation_finish", {"project_id": self.current_project_id, "status": "exception", "error": str(e)})
                if runner_db:
                    runner_db.log_audit_event("validation_finish", {"project_id": self.current_project_id, "status": "exception"})
            finally:
                if runner_db is not None:
                    runner_db.close()
                self.current_run_id = None
                self.proc = None
                self.run_started_at = None
                self.last_log_at = None
                self.root.after(0, self._refresh_projects)
                self.root.after(0, self._refresh_run_history)
                self.root.after(0, lambda: self.start_btn.configure(state="normal"))
                self.root.after(0, lambda: self.validate_btn.configure(state="normal"))
                self.root.after(0, lambda: self.stop_btn.configure(state="disabled"))

        threading.Thread(target=runner, daemon=True).start()

    def _stop_process(self) -> None:
        if self.proc is None:
            return
        self.run_all_active = False
        self.run_all_btn.configure(state="normal")
        self.stop_run_all_btn.configure(state="disabled")
        self.queue_status_var.set(self.tr("status.queue.interrupted", "Queue: interrupted by user"))
        try:
            self.proc.terminate()
            self._set_status(self.tr("status.stopping", "Stopping process..."), "running")
            self.phase_var.set(self.tr("status.phase.stopping", "Phase: stopping"))
            self.log_queue.put("\n[!] " + self.tr("log.terminate_sent", "Terminate sent to process.") + "\n")
        except Exception as e:
            self.log_queue.put(f"\n{self.tr('log.stop_failed', 'Failed to stop process')}: {e}\n")

    def _redacted_cmd(self, cmd: List[str]) -> str:
        out: List[str] = []
        redact_next = False
        for a in cmd:
            if redact_next:
                out.append("***")
                redact_next = False
                continue
            if a == "--api-key":
                out.append(a)
                redact_next = True
            else:
                out.append(quote_arg(a))
        return " ".join(out)

    def _serialize(self) -> dict:
        data = {
            "mode": self.mode_var.get(),
            "provider": self.provider_var.get(),
            "input_epub": self.input_epub_var.get(),
            "output_epub": self.output_epub_var.get(),
            "prompt": self.prompt_var.get(),
            "glossary": self.glossary_var.get(),
            "cache": self.cache_var.get(),
            "debug_dir": self.debug_dir_var.get(),
            "ollama_host": self.ollama_host_var.get(),
            "model": self.model_var.get(),
            "batch_max_segs": self.batch_max_segs_var.get(),
            "batch_max_chars": self.batch_max_chars_var.get(),
            "sleep": self.sleep_var.get(),
            "timeout": self.timeout_var.get(),
            "attempts": self.attempts_var.get(),
            "backoff": self.backoff_var.get(),
            "temperature": self.temperature_var.get(),
            "num_ctx": self.num_ctx_var.get(),
            "num_predict": self.num_predict_var.get(),
            "tags": self.tags_var.get(),
            "use_cache": self.use_cache_var.get(),
            "use_glossary": self.use_glossary_var.get(),
            "checkpoint": self.checkpoint_var.get(),
            "source_lang": self.source_lang_var.get(),
            "target_lang": self.target_lang_var.get(),
        }
        data.pop("google_api_key", None)
        return data

    def _apply_settings(self, data: dict) -> None:
        if isinstance(data, dict):
            legacy_key = str(data.get("google_api_key", "")).strip()
            if legacy_key:
                self.google_api_key_var.set(legacy_key)
                save_google_api_key_to_keyring(legacy_key)
        self.mode_var.set(data.get("mode", self.mode_var.get()))
        self.provider_var.set(data.get("provider", self.provider_var.get()))
        self.input_epub_var.set(data.get("input_epub", self.input_epub_var.get()))
        self.output_epub_var.set(data.get("output_epub", self.output_epub_var.get()))
        self.prompt_var.set(data.get("prompt", self.prompt_var.get()))
        self.glossary_var.set(data.get("glossary", self.glossary_var.get()))
        self.cache_var.set(data.get("cache", self.cache_var.get()))
        self.debug_dir_var.set(data.get("debug_dir", self.debug_dir_var.get()))
        self.ollama_host_var.set(data.get("ollama_host", self.ollama_host_var.get()))
        self.model_var.set(data.get("model", self.model_var.get()))
        self.batch_max_segs_var.set(data.get("batch_max_segs", self.batch_max_segs_var.get()))
        self.batch_max_chars_var.set(data.get("batch_max_chars", self.batch_max_chars_var.get()))
        self.sleep_var.set(data.get("sleep", self.sleep_var.get()))
        self.timeout_var.set(data.get("timeout", self.timeout_var.get()))
        self.attempts_var.set(data.get("attempts", self.attempts_var.get()))
        self.backoff_var.set(data.get("backoff", self.backoff_var.get()))
        self.temperature_var.set(data.get("temperature", self.temperature_var.get()))
        self.num_ctx_var.set(data.get("num_ctx", self.num_ctx_var.get()))
        self.num_predict_var.set(data.get("num_predict", self.num_predict_var.get()))
        self.tags_var.set(data.get("tags", self.tags_var.get()))
        self.use_cache_var.set(bool(data.get("use_cache", self.use_cache_var.get())))
        self.use_glossary_var.set(bool(data.get("use_glossary", self.use_glossary_var.get())))
        self.checkpoint_var.set(data.get("checkpoint", self.checkpoint_var.get()))
        self.tooltip_mode_var.set(str(data.get("tooltip_mode", self.tooltip_mode_var.get() or "hybrid")))
        self.source_lang_var.set(str(data.get("source_lang", self.source_lang_var.get() or "en")))
        self.target_lang_var.set(str(data.get("target_lang", self.target_lang_var.get() or "pl")))
        self.ui_language_var.set(str(data.get("ui_language", self.ui_language_var.get() or self.i18n.lang)))
        self._on_tooltip_mode_change()
        if self.ui_language_var.get().strip().lower() != self.i18n.lang:
            self._on_ui_language_change()
        self._on_provider_change()
        self._update_command_preview()

    def _save_settings(self, silent: bool = False) -> None:
        try:
            self.db.set_setting("ui_state", self._serialize())
            _ = save_google_api_key_to_keyring(self.google_api_key_var.get().strip())
            if self.current_project_id is not None:
                self.db.set_setting("active_project_id", self.current_project_id)
            if not silent:
                self._set_status(self.tr("status.settings_saved", "Settings saved (SQLite)"), "ready")
        except Exception as e:
            if not silent:
                self._msg_error(f"Nie udało się zapisać ustawień:\n{e}")

    def _load_settings(self, silent: bool = False) -> None:
        try:
            data = self.db.get_setting("ui_state", {})
            self._apply_settings(data)
            active_project_id = self.db.get_setting("active_project_id", None)
            if isinstance(active_project_id, int):
                self.current_project_id = active_project_id
            if not silent:
                self._set_status(self.tr("status.settings_loaded", "Settings loaded (SQLite)"), "ready")
        except Exception as e:
            if not silent:
                self._msg_error(f"Nie udało się wczytać ustawień:\n{e}")

    def _on_close(self) -> None:
        try:
            self._save_step_values(self.mode_var.get().strip() or "translate")
            self._save_project()
            self._save_settings(silent=True)
        except Exception:
            pass
        try:
            flush_event_log(self.events_log_path)
        except Exception:
            pass
        try:
            self.db.close()
        except Exception:
            pass
        if self._inline_notice_after_id is not None:
            try:
                self.root.after_cancel(self._inline_notice_after_id)
            except Exception:
                pass
            self._inline_notice_after_id = None
        self.root.destroy()


def main() -> int:
    root = tk.Tk()
    TranslatorGUI(root)
    root.mainloop()
    return 0


class TextEditorWindow:
    def __init__(self, gui: TranslatorGUI, epub_path: Path) -> None:
        self.gui = gui
        self.epub_path = epub_path
        self.win = tk.Toplevel(gui.root)
        self.win.title(self.gui.tr("editor.window_title", "EPUB text editor - {name}", name=epub_path.name))
        self.gui._configure_window_bounds(self.win, preferred_w=1200, preferred_h=760, min_w=760, min_h=520, maximize=True)

        self.chapter_entries = list_chapters(epub_path)
        self.current_chapter_path: Optional[str] = None
        self.current_root: Optional[etree._Element] = None
        self.current_segments: List[etree._Element] = []
        self._tooltips: List[Any] = []

        wrap = ttk.Frame(self.win, padding=12)
        wrap.pack(fill="both", expand=True)
        wrap.columnconfigure(1, weight=1)
        wrap.rowconfigure(1, weight=1)

        ttk.Label(wrap, text=f"Plik: {epub_path}", style="Sub.TLabel").grid(row=0, column=0, columnspan=2, sticky="w")

        left = ttk.Frame(wrap)
        left.grid(row=1, column=0, sticky="nsw", padx=(0, 10))
        right = ttk.Frame(wrap)
        right.grid(row=1, column=1, sticky="nsew")
        right.columnconfigure(0, weight=1)
        right.rowconfigure(1, weight=1)

        ttk.Label(left, text=self.gui.tr("editor.chapters", "Chapters:")).pack(anchor="w")
        self.chapter_box = tk.Listbox(left, width=48, height=30)
        self.chapter_box.pack(fill="both", expand=True)
        for rid, path in self.chapter_entries:
            self.chapter_box.insert("end", f"{rid} | {path}")
        self.chapter_box.bind("<<ListboxSelect>>", lambda _: self._on_chapter_selected())

        ttk.Label(right, text=self.gui.tr("editor.segments", "Segments:")).grid(row=0, column=0, sticky="w")
        self.segment_box = tk.Listbox(right, height=10)
        self.segment_box.grid(row=1, column=0, sticky="nsew")
        self.segment_box.bind("<<ListboxSelect>>", lambda _: self._on_segment_selected())

        self.editor = ScrolledText(right, height=18, font=("Consolas", 10))
        self.editor.grid(row=2, column=0, sticky="nsew", pady=(8, 0))
        right.rowconfigure(2, weight=2)

        btn = ttk.Frame(right)
        btn.grid(row=3, column=0, sticky="ew", pady=(8, 0))
        ttk.Button(btn, text=self.gui.tr("editor.save_segment", "Save segment"), command=self._save_segment).pack(side="left")
        ttk.Button(btn, text=self.gui.tr("editor.save_epub", "Save EPUB"), command=self._save_epub).pack(side="left", padx=(8, 0))
        self._install_tooltips()

    def _install_tooltips(self) -> None:
        text_tip = {
            self.gui.tr("editor.chapters", "Chapters:"): self.gui.tr("tip.editor.chapters", "List of chapter files in EPUB. Selection loads chapter segments."),
            self.gui.tr("editor.segments", "Segments:"): self.gui.tr("tip.editor.segments", "List of text segments in selected chapter."),
            self.gui.tr("editor.save_segment", "Save segment"): self.gui.tr("tip.editor.save_segment", "Saves changes only in current selected segment (in memory)."),
            self.gui.tr("editor.save_epub", "Save EPUB"): self.gui.tr("tip.editor.save_epub", "Saves chapter changes to EPUB and creates backup."),
        }
        object_tip = {
            id(self.chapter_box): "Wybór rozdziału do edycji.",
            id(self.segment_box): "Wybór segmentu do podglądu/edycji.",
            id(self.editor): "Edytor treści segmentu. To pole modyfikuje docelowy tekst.",
        }

        def resolver(widget: tk.Misc) -> Optional[str]:
            by_obj = object_tip.get(id(widget))
            if by_obj:
                return by_obj
            try:
                t = str(widget.cget("text")).strip()
            except Exception:
                t = ""
            if t and t in text_tip:
                return text_tip[t]
            cls = str(widget.winfo_class())
            if cls in {"TEntry", "Entry"}:
                return "Pole wejściowe w edytorze."
            return None

        self._tooltips = install_tooltips(self.win, resolver)

    def _on_chapter_selected(self) -> None:
        sel = self.chapter_box.curselection()
        if not sel:
            return
        idx = int(sel[0])
        _, chapter_path = self.chapter_entries[idx]
        try:
            root, segments, _, _ = load_chapter_segments(self.epub_path, chapter_path)
        except Exception as e:
            self._msg_error(f"{self.gui.tr('err.editor_load_chapter', 'Failed to load chapter:')}\n{e}")
            return
        self.current_chapter_path = chapter_path
        self.current_root = root
        self.current_segments = segments
        self.segment_box.delete(0, "end")
        for i, el in enumerate(segments):
            txt = (el.text or "").strip().replace("\n", " ")
            if len(txt) > 90:
                txt = txt[:90] + "..."
            self.segment_box.insert("end", f"{i:04d}: <{etree.QName(el).localname}> {txt}")

    def _on_segment_selected(self) -> None:
        sel = self.segment_box.curselection()
        if not sel:
            return
        idx = int(sel[0])
        if idx < 0 or idx >= len(self.current_segments):
            return
        el = self.current_segments[idx]
        txt = etree.tostring(el, encoding="unicode", method="text")
        self.editor.delete("1.0", "end")
        self.editor.insert("1.0", txt)

    def _save_segment(self) -> None:
        sel = self.segment_box.curselection()
        if not sel:
            return
        idx = int(sel[0])
        if idx < 0 or idx >= len(self.current_segments):
            return
        new_text = self.editor.get("1.0", "end").strip()
        el = self.current_segments[idx]
        for c in list(el):
            el.remove(c)
        el.text = new_text
        preview = new_text.replace("\n", " ")
        if len(preview) > 90:
            preview = preview[:90] + "..."
        self.segment_box.delete(idx)
        self.segment_box.insert(idx, f"{idx:04d}: <{etree.QName(el).localname}> {preview}")
        self.segment_box.selection_set(idx)

    def _save_epub(self) -> None:
        if self.current_root is None or not self.current_chapter_path:
            self._msg_info(self.gui.tr("info.editor_select_chapter", "Select chapter first."))
            return
        try:
            _, backup = save_chapter_changes(self.epub_path, self.current_chapter_path, self.current_root)
            self.gui._push_operation(
                {"type": "backup_restore", "target": str(self.epub_path), "backup": str(backup)}
            )
            self.gui._set_status(self.gui.tr("status.editor_epub_saved", "Saved changes in EPUB: {name}", name=self.epub_path.name), "ok")
            self.gui._msg_info(self.gui.tr("info.epub_saved_backup", "Changes saved. Backup .bak-edit-... created."), title=self.gui.tr("mb.ok", "OK"))
        except Exception as e:
            self._msg_error(f"{self.gui.tr('err.editor_save_epub', 'Failed to save EPUB:')}\n{e}")


if __name__ == "__main__":
    raise SystemExit(main())
