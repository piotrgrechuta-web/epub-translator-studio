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
import sqlite3
import subprocess
import sys
import threading
import time
import webbrowser
import zipfile
import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

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
from studio_repository import SQLiteStudioRepository
from app_events import flush_event_log, log_event_jsonl
from prompt_presets import filter_prompt_presets, load_prompt_presets, save_default_prompt_presets
from runtime_core import (
    RunOptions as CoreRunOptions,
    build_run_command as core_build_run_command,
    build_validation_command as core_build_validation_command,
    gather_provider_health as core_gather_provider_health,
    list_google_models as core_list_google_models,
    list_ollama_models as core_list_ollama_models,
    validate_run_options as core_validate_run_options,
)
from series_store import SeriesStore, detect_series_hint
from text_preserve import set_text_preserving_inline, tokenize_inline_markup, apply_tokenized_inline_markup
from ui_style import apply_app_theme
from easy_startup import (
    discover_input_epubs,
    match_projects_by_input_and_langs,
    parse_ambiguous_choice,
    resume_eligibility,
    suggest_paths_for_step,
)

APP_TITLE = "EPUB Translator Studio"
SETTINGS_FILE = Path(__file__).resolve().with_name(".gui_settings.json")
SQLITE_FILE = Path(__file__).resolve().with_name(DB_FILE)
LOCALES_DIR = Path(__file__).resolve().with_name("locales")
OLLAMA_HOST_DEFAULT = os.environ.get("OLLAMA_HOST", "http://127.0.0.1:11434")
GOOGLE_API_KEY_ENV = "GOOGLE_API_KEY"
SUPPORT_URL = "https://github.com/sponsors/Piotr-Grechuta"
REPO_URL = "https://github.com/Piotr-Grechuta/epub-translator-studio"
SERIES_DATA_DIR = Path(__file__).resolve().with_name("data").joinpath("series")
PROMPT_PRESETS_FILE = Path(__file__).resolve().with_name("prompt_presets.json")
GOOGLE_KEYRING_SERVICE = "epub-translator-studio"
GOOGLE_KEYRING_USER = "google_api_key"
EPUBCHECK_TIMEOUT_S = 120
APP_RUNTIME_VERSION = "0.6.1"
GLOBAL_PROGRESS_RE = re.compile(r"GLOBAL\s+(\d+)\s*/\s*(\d+)\s*\(([^)]*)\)\s*\|\s*(.*)")
TOTAL_SEGMENTS_RE = re.compile(r"Segmenty\s+(?:łącznie|lacznie)\s*:\s*(\d+)", re.IGNORECASE)
CACHE_SEGMENTS_RE = re.compile(r"Segmenty\s+z\s+cache\s*:\s*(\d+)", re.IGNORECASE)
CHAPTER_CACHE_TM_RE = re.compile(r"\(cache:\s*(\d+)\s*,\s*tm:\s*(\d+)\)", re.IGNORECASE)
METRICS_BLOB_RE = re.compile(r"metrics\[(.*?)\]", re.IGNORECASE)
METRICS_KV_RE = re.compile(r"([a-zA-Z_]+)\s*=\s*([^;]+)")
EPUBCHECK_SEVERITY_RE = re.compile(r"\b(FATAL|ERROR|WARNING)\b", re.IGNORECASE)
INLINE_TOKEN_RE = re.compile(r"\[\[TAG\d{3}\]\]")
GOOGLE_HTTP_RETRY_RE = re.compile(r"\[Google\]\s+HTTP\s+\d+.*(?:pr[oó]ba|attempt)\s+(\d+)\s*/\s*(\d+)", re.IGNORECASE)
GOOGLE_TIMEOUT_RE = re.compile(r"\[Google\]\s+timeout/conn error.*(?:pr[oó]ba|attempt)\s+(\d+)\s*/\s*(\d+)", re.IGNORECASE)
OLLAMA_TIMEOUT_RE = re.compile(r"\[Ollama\]\s+timeout/conn error.*(?:pr[oó]ba|attempt)\s+(\d+)\s*/\s*(\d+)", re.IGNORECASE)
LEDGER_ERROR_ALERT_THRESHOLD = 5
LOG = logging.getLogger(__name__)


def parse_epubcheck_findings(raw_output: str) -> Dict[str, int]:
    counts = {"fatal": 0, "error": 0, "warning": 0}
    for line in str(raw_output or "").splitlines():
        m = EPUBCHECK_SEVERITY_RE.search(line)
        if not m:
            continue
        sev = str(m.group(1) or "").strip().lower()
        if sev in counts:
            counts[sev] += 1
    return counts


def list_ollama_models(host: str, timeout_s: int = 20) -> List[str]:
    return core_list_ollama_models(host=host, timeout_s=timeout_s)


def list_google_models(api_key: str, timeout_s: int = 20) -> List[str]:
    return core_list_google_models(api_key=api_key, timeout_s=timeout_s)


def gather_provider_health(
    *,
    ollama_host: str,
    google_api_key: str,
    timeout_s: int = 10,
    include_ollama: bool = True,
    include_google: bool = True,
) -> Dict[str, Any]:
    return core_gather_provider_health(
        ollama_host=ollama_host,
        google_api_key=google_api_key,
        timeout_s=timeout_s,
        include_ollama=include_ollama,
        include_google=include_google,
    )


def quote_arg(arg: str) -> str:
    if platform.system().lower().startswith("win"):
        if any(ch in arg for ch in [" ", "\t", '"']):
            return '"' + arg.replace('"', '\\"') + '"'
        return arg
    return arg


def simple_prompt(root: tk.Tk, title: str, label: str, *, default_value: str = "") -> Optional[str]:
    win = tk.Toplevel(root)
    win.title(title)
    win.transient(root)
    win.grab_set()
    out: Dict[str, Optional[str]] = {"value": None}

    frm = ttk.Frame(win, padding=12)
    frm.pack(fill="both", expand=True)
    ttk.Label(frm, text=label).pack(anchor="w")
    var = tk.StringVar(value=str(default_value or ""))
    entry = ttk.Entry(frm, textvariable=var, width=40)
    entry.pack(fill="x", pady=(6, 10))
    entry.focus_set()
    entry.selection_range(0, "end")

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


def multiline_prompt(
    root: tk.Tk,
    title: str,
    label: str,
    *,
    default_value: str = "",
    width: int = 90,
    height: int = 14,
) -> Optional[str]:
    win = tk.Toplevel(root)
    win.title(title)
    win.transient(root)
    win.grab_set()
    out: Dict[str, Optional[str]] = {"value": None}

    frm = ttk.Frame(win, padding=12)
    frm.pack(fill="both", expand=True)
    frm.rowconfigure(1, weight=1)
    frm.columnconfigure(0, weight=1)

    ttk.Label(frm, text=label).grid(row=0, column=0, sticky="w")
    editor = ScrolledText(frm, width=width, height=height, wrap="word")
    editor.grid(row=1, column=0, sticky="nsew", pady=(6, 10))
    if default_value:
        editor.insert("1.0", str(default_value))
    editor.focus_set()

    btn = ttk.Frame(frm)
    btn.grid(row=2, column=0, sticky="w")

    def accept() -> None:
        out["value"] = editor.get("1.0", "end-1c")
        win.destroy()

    def cancel() -> None:
        out["value"] = None
        win.destroy()

    ttk.Button(btn, text="OK", command=accept).pack(side="left")
    ttk.Button(btn, text="Anuluj", command=cancel).pack(side="left", padx=(8, 0))
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
        self.db = ProjectDB(
            SQLITE_FILE,
            recover_runtime_state=True,
            backup_paths=[SERIES_DATA_DIR],
        )
        self.repo = SQLiteStudioRepository(self.db)
        self._startup_notices: List[str] = []
        if self.db.last_migration_summary:
            m = self.db.last_migration_summary
            self._startup_notices.append(
                "Wykryto zmiane struktury danych. "
                f"Przeprowadzono konwersje schema {m.get('from_schema')} -> {m.get('to_schema')}. "
                f"Backup: {m.get('backup_dir')}"
            )
        self.series_store = SeriesStore(SERIES_DATA_DIR)
        ui_lang = str(self.db.get_setting("ui_language", "pl") or "pl").strip().lower()
        self.i18n = I18NManager(LOCALES_DIR, ui_lang)
        prev_runtime_version = str(self.db.get_setting("app_runtime_version", "") or "").strip()
        if prev_runtime_version and prev_runtime_version != APP_RUNTIME_VERSION:
            self._startup_notices.append(
                f"Uzywales wersji {prev_runtime_version}, teraz uruchomiona jest {APP_RUNTIME_VERSION}. "
                "Sprawdz notatki aktualizacji i log konwersji danych."
            )
        self.db.set_setting("app_runtime_version", APP_RUNTIME_VERSION)
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
        self.series_name_to_id: Dict[str, int] = {}
        self.series_id_to_slug: Dict[int, str] = {}
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
        self._runtime_retry_lines: set[str] = set()
        self.prompt_presets: List[Dict[str, str]] = []
        self.prompt_preset_by_label: Dict[str, Dict[str, str]] = {}
        self._ledger_counts: Dict[str, int] = {"PENDING": 0, "PROCESSING": 0, "COMPLETED": 0, "ERROR": 0}
        self._ledger_alert_key: Optional[Tuple[int, str, int]] = None
        self.series_batch_context: Optional[Dict[str, Any]] = None
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
        self._load_prompt_presets_catalog()
        self._refresh_prompt_preset_options()
        self._refresh_profiles()
        self._refresh_series()
        self._refresh_projects(select_current=True)
        self._update_command_preview()
        self._refresh_ledger_status()
        self._poll_log_queue()
        self._show_startup_notices()
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
            "google_retries": 0,
            "google_timeouts": 0,
            "ollama_retries": 0,
            "ollama_timeouts": 0,
        }
        self._runtime_metric_lines.clear()
        self._runtime_retry_lines.clear()

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
        g_retry = int(self._runtime_metrics.get("google_retries", 0) or 0)
        g_timeout = int(self._runtime_metrics.get("google_timeouts", 0) or 0)
        o_retry = int(self._runtime_metrics.get("ollama_retries", 0) or 0)
        o_timeout = int(self._runtime_metrics.get("ollama_timeouts", 0) or 0)
        dur_s = int(max(0.0, time.time() - self.run_started_at)) if self.run_started_at is not None else 0
        return (
            f"metrics[dur_s={dur_s};done={done};total={total};cache_hits={cache_hits};"
            f"tm_hits={tm_hits};reuse_hits={reuse_hits};reuse_rate={reuse_rate:.1f};"
            f"google_retries={g_retry};google_timeouts={g_timeout};"
            f"ollama_retries={o_retry};ollama_timeouts={o_timeout}]"
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
        g_retry = int(self._runtime_metrics.get("google_retries", 0) or 0)
        g_timeout = int(self._runtime_metrics.get("google_timeouts", 0) or 0)
        o_retry = int(self._runtime_metrics.get("ollama_retries", 0) or 0)
        o_timeout = int(self._runtime_metrics.get("ollama_timeouts", 0) or 0)
        dur_s = int(max(0.0, time.time() - self.run_started_at))
        self.run_metrics_var.set(
            f"Metryki runu: czas={self._format_duration(dur_s)} | seg={done}/{total} | "
            f"cache={cache_hits} | tm={tm_hits} | reuse={reuse_rate:.1f}% | "
            f"G(r={g_retry},t={g_timeout}) O(r={o_retry},t={o_timeout})"
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
        if s not in self._runtime_retry_lines:
            self._runtime_retry_lines.add(s)
            m_g_http = GOOGLE_HTTP_RETRY_RE.search(s)
            if m_g_http:
                try:
                    attempt = int(m_g_http.group(1))
                    max_attempts = int(m_g_http.group(2))
                    if attempt < max_attempts:
                        self._runtime_metrics["google_retries"] += 1
                except Exception:
                    pass
            m_g_timeout = GOOGLE_TIMEOUT_RE.search(s)
            if m_g_timeout:
                self._runtime_metrics["google_timeouts"] += 1
                try:
                    attempt = int(m_g_timeout.group(1))
                    max_attempts = int(m_g_timeout.group(2))
                    if attempt < max_attempts:
                        self._runtime_metrics["google_retries"] += 1
                except Exception:
                    pass
            m_o_timeout = OLLAMA_TIMEOUT_RE.search(s)
            if m_o_timeout:
                self._runtime_metrics["ollama_timeouts"] += 1
                try:
                    attempt = int(m_o_timeout.group(1))
                    max_attempts = int(m_o_timeout.group(2))
                    if attempt < max_attempts:
                        self._runtime_metrics["ollama_retries"] += 1
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

    def _show_startup_notices(self) -> None:
        if not self._startup_notices:
            return
        msg = " | ".join([str(x).strip() for x in self._startup_notices if str(x).strip()])
        if not msg:
            return
        self._append_log("[UPDATE] " + msg + "\n")
        self._set_inline_notice(msg, level="warn", timeout_ms=18000)

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
        self.series_var = tk.StringVar()
        self.volume_no_var = tk.StringVar()
        self.input_epub_var = tk.StringVar()
        self.output_epub_var = tk.StringVar()
        self.prompt_var = tk.StringVar()
        self.prompt_preset_var = tk.StringVar()
        self.prompt_preset_desc_var = tk.StringVar(value=self.tr("status.prompt_preset.none", "Prompt preset: custom/manual"))
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
        self.hard_gate_epubcheck_var = tk.BooleanVar(value=True)
        self.checkpoint_var = tk.StringVar(value="0")
        self.context_window_var = tk.StringVar(value="0")
        self.context_neighbor_max_chars_var = tk.StringVar(value="180")
        self.context_segment_max_chars_var = tk.StringVar(value="1200")
        self.io_concurrency_var = tk.StringVar(value="1")
        self.language_guard_config_var = tk.StringVar()
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
        self.progress_text_var = tk.StringVar(value=self.tr("status.progress.zero", "PostĂ„â„˘p: 0 / 0"))
        self.phase_var = tk.StringVar(value=self.tr("status.phase.wait", "Etap: oczekiwanie"))
        self.ledger_status_var = tk.StringVar(value=self.tr("status.ledger.none", "Ledger: no data"))
        self.run_metrics_var = tk.StringVar(value=self.tr("status.metrics.none", "Metryki runu: brak"))
        self.health_trend_var = tk.StringVar(value=self.tr("status.health_trend.none", "Health trend: brak danych"))
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
            self.tr("button.delete", "UsuÄąâ€ž"): tt("tip.button.delete", "Soft-delete project: hidden from active list, history remains."),
            self.tr("button.delete_hard", "UsuÄąâ€ž hard"): tt("tip.button.delete_hard", "Deletes project permanently with run history and QA."),
            self.tr("button.save_as_profile", "Zapisz jako profil"): tt("tip.button.save_as_profile", "Creates profile from current step parameters."),
            self.tr("button.export", "Eksport"): tt("tip.button.export", "Exports project configuration to JSON."),
            self.tr("button.import", "Import"): tt("tip.button.import", "Imports project/profile from JSON."),
            self.tr("provider.ollama", "Ollama (lokalnie)"): tt("tip.provider.ollama", "Local provider, no API cost, depends on machine resources."),
            self.tr("provider.google", "Google Gemini API"): tt("tip.provider.google", "Cloud provider, often faster on big batches, paid API."),
            self.tr("button.refresh_models", "OdÄąâ€şwieÄąÄ˝ listĂ„â„˘ modeli"): tt("tip.button.refresh_models", "Fetches model list from selected provider."),
            self.tr("button.start", "Start translacji"): tt("tip.button.start", "Starts current step for active project."),
            self.tr("button.stop", "Stop"): tt("tip.button.stop", "Stops currently running process."),
            self.tr("button.validate_epub", "Waliduj EPUB"): tt("tip.button.validate_epub", "Runs EPUB validation after processing."),
            self.tr("button.estimate", "Estymacja"): tt("tip.button.estimate", "Calculates segments/time/cost estimate before start."),
            self.tr("button.queue", "Kolejkuj"): tt("tip.button.queue", "Marks project as pending."),
            self.tr("button.run_next", "Uruchom nastĂ„â„˘pny"): tt("tip.button.run_next", "Runs next pending project."),
            self.tr("button.run_all_pending", "Run all pending"): tt("tip.button.run_all_pending", "Runs all pending projects sequentially."),
            self.tr("button.stop_run_all", "Stop run-all"): tt("tip.button.stop_run_all", "Stops run-all after current task."),
            self.tr("button.open_output", "OtwÄ‚Ĺ‚rz output"): tt("tip.button.open_output", "Opens output file/folder in system explorer."),
            self.tr("button.open_cache", "OtwÄ‚Ĺ‚rz cache"): tt("tip.button.open_cache", "Opens cache file location."),
            self.tr("button.clear_debug", "WyczyÄąâ€şĂ„â€ˇ debug"): tt("tip.button.clear_debug", "Clears debug folder artifacts."),
            self.tr("button.add_card_single", "Dodaj wizytÄ‚Ĺ‚wkĂ„â„˘ (1 EPUB)"): tt("tip.button.add_card_single", "Adds business-card page to one EPUB."),
            self.tr("button.add_card_batch", "Dodaj wizytÄ‚Ĺ‚wkĂ„â„˘ (folder)"): tt("tip.button.add_card_batch", "Adds business-card page to all EPUB in folder."),
            self.tr("button.remove_cover", "UsuÄąâ€ž okÄąâ€šadkĂ„â„˘"): tt("tip.button.remove_cover", "Removes cover image/resources from EPUB."),
            self.tr("button.remove_graphics_pattern", "UsuÄąâ€ž grafiki (pattern)"): tt("tip.button.remove_graphics_pattern", "Removes images by path/name pattern."),
            self.tr("button.open_text_editor", "Edytor tekstu EPUB"): tt("tip.button.open_text_editor", "Opens chapter/segment text editor."),
            self.tr("button.undo_last_operation", "Cofnij ostatniĂ„â€¦ operacjĂ„â„˘"): tt("tip.button.undo_last_operation", "Restores from latest operation backup."),
            self.tr("button.open_studio", "Studio Tools (12)"): tt("tip.button.open_studio", "Opens extended QA/TM/pipeline/plugin tools."),
            self.tr("button.choose", "Wybierz"): tt("tip.button.choose", "Opens file chooser dialog."),
            self.tr("tab.basic", "Podstawowe"): tt("tip.tab.basic", "Tab with core files and engine setup."),
            self.tr("tab.advanced", "Zaawansowane"): tt("tip.tab.advanced", "Tab with quality/retry/checkpoint settings."),
            self.tr("label.tooltip_mode", "Tooltip mode:"): tt("tip.label.tooltip_mode", "Select tooltip verbosity style: short/hybrid/expert."),
            self.tr("label.ui_language", "UI language:"): tt("tip.label.ui_language", "Choose interface language (pl/en/de/fr/es/pt)."),
            self.tr("button.ai_translate_gui", "AI: szkic tÄąâ€šumaczenia GUI"): tt("tip.button.ai_translate_gui", "Generates AI draft translation for GUI labels."),
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
            self._msg_error(self.tr("err.ui_lang_invalid", "Wybierz poprawny jĂ„â„˘zyk UI."), title="AI")
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
            self._msg_error(f"{self.tr('err.ai_draft_failed', 'Nie udaÄąâ€šo siĂ„â„˘ wygenerowaĂ„â€ˇ szkicu:')}\n{msg}", title="AI")
            return
        draft_path = self.i18n.save_draft(lang, out)
        apply_now = self._ask_yes_no(
            self.tr("confirm.ai_merge_draft", "Zapisano szkic: {name}\n\nScaliĂ„â€ˇ od razu do locales/{lang}.json?", name=draft_path.name, lang=lang),
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
        ttk.Button(pbtn, text=self.tr("button.delete", "UsuÄąâ€ž"), command=self._delete_project, style="Danger.TButton").pack(side="left", padx=(self._theme_space("space_sm", 8), 0))
        ttk.Button(
            pbtn,
            text=self.tr("button.delete_hard", "UsuÄąâ€ž hard"),
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

        ttk.Label(card, text=self.tr("label.series", "Seria:")).grid(row=2, column=0, sticky="w", pady=(8, 0))
        series_wrap = ttk.Frame(card)
        series_wrap.grid(row=2, column=1, sticky="ew", pady=(8, 0))
        series_wrap.columnconfigure(0, weight=1)
        self.series_combo = ttk.Combobox(series_wrap, textvariable=self.series_var, state="readonly", style="TCombobox")
        self.series_combo.grid(row=0, column=0, sticky="ew")
        self.series_combo.bind("<<ComboboxSelected>>", lambda _: self._on_series_selected())
        ttk.Label(series_wrap, text=self.tr("label.volume_no", "Tom:")).grid(row=0, column=1, padx=(8, 4), sticky="w")
        self.series_volume_entry = ttk.Entry(series_wrap, textvariable=self.volume_no_var, width=8)
        self.series_volume_entry.grid(row=0, column=2, sticky="w")
        self.series_volume_entry.bind("<FocusOut>", lambda _: self._save_project())

        serbtn = ttk.Frame(card)
        serbtn.grid(row=2, column=2, padx=(self._theme_space("space_sm", 8), 0), pady=(8, 0), sticky="w")
        ttk.Button(serbtn, text=self.tr("button.new_series", "Nowa seria"), command=self._create_series, style="Secondary.TButton").pack(side="left")
        ttk.Button(serbtn, text=self.tr("button.edit_series", "Edytuj serie"), command=self._edit_series, style="Secondary.TButton").pack(side="left", padx=(self._theme_space("space_sm", 8), 0))
        ttk.Button(serbtn, text=self.tr("button.delete_series", "Usun serie"), command=self._delete_series, style="Danger.TButton").pack(side="left", padx=(self._theme_space("space_sm", 8), 0))
        ttk.Button(serbtn, text=self.tr("button.detect_series", "Auto z EPUB"), command=self._detect_series_for_input, style="Secondary.TButton").pack(side="left", padx=(self._theme_space("space_sm", 8), 0))
        ttk.Button(serbtn, text=self.tr("button.series_terms", "Slownik serii"), command=self._open_series_terms_manager, style="Secondary.TButton").pack(side="left", padx=(self._theme_space("space_sm", 8), 0))

        stats = ttk.Frame(card)
        stats.grid(row=3, column=0, columnspan=3, sticky="ew", pady=(8, 0))
        ttk.Label(stats, textvariable=self.status_counts_var, style="Sub.TLabel").pack(anchor="w")
        ttk.Label(
            stats,
            text=self.tr("ui.hint.statuses", "Statusy: T=tlumaczenie, R=redakcja, strzalka pokazuje nastĂ„â„˘pny krok."),
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
            text=self.tr("ui.hint.files", "Najpierw wybierz input/output, potem tryb i jĂ„â„˘zyki."),
            style="Helper.TLabel",
        ).grid(row=0, column=0, columnspan=4, sticky="w", pady=(0, self._theme_space("space_sm", 8)))

        self._row_file(card, 1, self.tr("file.input_epub", "WejÄąâ€şciowy EPUB"), self.input_epub_var, [("EPUB", "*.epub")], self._on_input_selected)
        self._row_file(card, 2, self.tr("file.output_epub", "WyjÄąâ€şciowy EPUB"), self.output_epub_var, [("EPUB", "*.epub")])
        self._row_file(card, 3, self.tr("file.prompt", "Prompt"), self.prompt_var, [("TXT", "*.txt")], self._on_prompt_changed)
        self._row_file(card, 4, self.tr("file.glossary", "Słownik"), self.glossary_var, [("TXT", "*.txt")])
        self._row_file(card, 5, self.tr("file.cache", "Cache"), self.cache_var, [("JSONL", "*.jsonl"), ("All", "*.*")])

        ttk.Label(card, text=self.tr("label.mode", "Tryb:")).grid(row=6, column=0, sticky="w", pady=(8, 0))
        mode_box = ttk.Frame(card)
        mode_box.grid(row=6, column=1, sticky="w", pady=(8, 0))
        ttk.Radiobutton(mode_box, text=self.tr("mode.translate", "TÄąâ€šumaczenie"), value="translate", variable=self.mode_var, command=self._on_mode_change).pack(side="left", padx=(0, 12))
        ttk.Radiobutton(mode_box, text=self.tr("mode.edit", "Redakcja"), value="edit", variable=self.mode_var, command=self._on_mode_change).pack(side="left")

        ttk.Label(card, text=self.tr("label.src_lang", "JĂ„â„˘zyk ÄąĹźrÄ‚Ĺ‚dÄąâ€šowy:")).grid(row=7, column=0, sticky="w", pady=(8, 0))
        src_combo = ttk.Combobox(card, textvariable=self.source_lang_var, state="readonly", width=12)
        src_combo["values"] = list(SUPPORTED_TEXT_LANGS.keys())
        src_combo.grid(row=7, column=1, sticky="w", pady=(8, 0))
        src_combo.bind("<<ComboboxSelected>>", lambda _: self._on_lang_pair_change())

        ttk.Label(card, text=self.tr("label.tgt_lang", "JĂ„â„˘zyk docelowy:")).grid(row=7, column=2, sticky="w", padx=(12, 0), pady=(8, 0))
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
            text=self.tr("ui.hint.engine", "Ustaw provider i model. Parametry batch kontrolujĂ„â€¦ stabilnoÄąâ€şĂ„â€ˇ i szybkoÄąâ€şĂ„â€ˇ."),
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

        ttk.Label(card, text=self.tr("label.prompt_preset", "Prompt preset:")).grid(row=20, column=0, sticky="w", pady=(8, 0))
        preset_row = ttk.Frame(card)
        preset_row.grid(row=20, column=1, sticky="ew", pady=(8, 0))
        self.prompt_preset_combo = ttk.Combobox(preset_row, textvariable=self.prompt_preset_var, state="readonly")
        self.prompt_preset_combo.pack(side="left", fill="x", expand=True)
        self.prompt_preset_combo.bind("<<ComboboxSelected>>", lambda _: self._on_prompt_preset_selected())
        ttk.Button(
            preset_row,
            text=self.tr("button.apply_preset", "Apply preset"),
            command=self._apply_selected_prompt_preset,
            style="Secondary.TButton",
        ).pack(side="left", padx=(8, 0))
        ttk.Button(
            preset_row,
            text=self.tr("button.reload_presets", "Reload"),
            command=self._reload_prompt_presets,
            style="Secondary.TButton",
        ).pack(side="left", padx=(8, 0))
        ttk.Label(card, textvariable=self.prompt_preset_desc_var, style="Helper.TLabel").grid(row=21, column=0, columnspan=2, sticky="w", pady=(4, 0))

        ttk.Label(card, text=self.tr("label.max_segs", "Max segs / request:")).grid(row=4, column=0, sticky="w", pady=(8, 0))
        ttk.Entry(card, textvariable=self.batch_max_segs_var, width=14).grid(row=4, column=1, sticky="w", pady=(8, 0))

        ttk.Label(card, text=self.tr("label.max_chars", "Max chars / request:")).grid(row=5, column=0, sticky="w", pady=(8, 0))
        ttk.Entry(card, textvariable=self.batch_max_chars_var, width=14).grid(row=5, column=1, sticky="w", pady=(8, 0))

        ttk.Label(card, text=self.tr("label.sleep", "Pauza miĂ„â„˘dzy requestami:")).grid(row=6, column=0, sticky="w", pady=(8, 0))
        ttk.Entry(card, textvariable=self.sleep_var, width=14).grid(row=6, column=1, sticky="w", pady=(8, 0))

        card.columnconfigure(1, weight=1)

    def _build_advanced_card(self, parent: ttk.Frame) -> None:
        card = ttk.LabelFrame(parent, text=self.tr("section.advanced_settings", "Ustawienia zaawansowane"), padding=12, style="Card.TLabelframe")
        card.pack(fill="x")

        ttk.Label(
            card,
            text=self.tr("ui.hint.advanced", "Zmieniaj te pola tylko gdy potrzebujesz strojenia jakoÄąâ€şci/stabilnoÄąâ€şci."),
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

        ttk.Label(card, text=self.tr("label.checkpoint", "Checkpoint co N plikÄ‚Ĺ‚w:")).grid(row=3, column=0, sticky="w", pady=(8, 0))
        ttk.Entry(card, textvariable=self.checkpoint_var, width=12).grid(row=3, column=1, sticky="w", pady=(8, 0))

        ttk.Label(card, text=self.tr("label.debug_dir", "Debug dir:")).grid(row=3, column=2, sticky="w", padx=(12, 0), pady=(8, 0))
        ttk.Entry(card, textvariable=self.debug_dir_var, width=24).grid(row=3, column=3, columnspan=3, sticky="ew", pady=(8, 0))

        ttk.Label(card, text=self.tr("label.tags", "Tagi:")).grid(row=4, column=0, sticky="w", pady=(8, 0))
        ttk.Entry(card, textvariable=self.tags_var).grid(row=4, column=1, columnspan=5, sticky="ew", pady=(8, 0))

        ttk.Checkbutton(card, text="UÄąÄ˝yj cache", variable=self.use_cache_var, command=self._update_command_preview).grid(row=5, column=0, sticky="w", pady=(8, 0))
        ttk.Checkbutton(card, text="UÄąÄ˝yj sÄąâ€šownika", variable=self.use_glossary_var, command=self._update_command_preview).grid(row=5, column=1, columnspan=2, sticky="w", pady=(8, 0))

        ttk.Label(card, text=self.tr("label.context_window", "Smart context window:")).grid(row=6, column=0, sticky="w", pady=(8, 0))
        ttk.Entry(card, textvariable=self.context_window_var, width=12).grid(row=6, column=1, sticky="w", pady=(8, 0))
        ttk.Label(card, text=self.tr("label.context_neighbor_max_chars", "Context max chars (neighbor):")).grid(row=6, column=2, sticky="w", padx=(12, 0), pady=(8, 0))
        ttk.Entry(card, textvariable=self.context_neighbor_max_chars_var, width=12).grid(row=6, column=3, sticky="w", pady=(8, 0))
        ttk.Label(card, text=self.tr("label.context_segment_max_chars", "Context max chars (segment):")).grid(row=6, column=4, sticky="w", padx=(12, 0), pady=(8, 0))
        ttk.Entry(card, textvariable=self.context_segment_max_chars_var, width=12).grid(row=6, column=5, sticky="w", pady=(8, 0))

        ttk.Label(card, text=self.tr("label.io_concurrency", "I/O concurrency:")).grid(row=7, column=0, sticky="w", pady=(8, 0))
        ttk.Entry(card, textvariable=self.io_concurrency_var, width=12).grid(row=7, column=1, sticky="w", pady=(8, 0))

        ttk.Label(card, text=self.tr("label.language_guard_config", "Language guard config (JSON):")).grid(row=8, column=0, sticky="w", pady=(8, 0))
        ttk.Entry(card, textvariable=self.language_guard_config_var).grid(row=8, column=1, columnspan=4, sticky="ew", pady=(8, 0))

        def pick_guard_cfg() -> None:
            path = filedialog.askopenfilename(
                title=self.tr("label.language_guard_config", "Language guard config (JSON):"),
                initialdir=str(self.workdir),
                filetypes=[("JSON", "*.json"), ("All", "*.*")],
            )
            if path:
                self.language_guard_config_var.set(path)
                self._update_command_preview()

        ttk.Button(card, text=self.tr("button.choose", "Wybierz"), command=pick_guard_cfg, style="Secondary.TButton").grid(
            row=8, column=5, sticky="w", padx=(8, 0), pady=(8, 0)
        )

        ttk.Label(card, text=self.tr("label.tooltip_mode", "Tooltip mode:")).grid(row=9, column=0, sticky="w", pady=(8, 0))
        tip_combo = ttk.Combobox(card, textvariable=self.tooltip_mode_var, state="readonly", width=14)
        tip_combo["values"] = ["hybrid", "short", "expert"]
        tip_combo.grid(row=9, column=1, sticky="w", pady=(8, 0))
        tip_combo.bind("<<ComboboxSelected>>", lambda _: self._on_tooltip_mode_change())

        ttk.Label(card, text=self.tr("label.ui_language", "Jezyk UI:")).grid(row=9, column=2, sticky="w", padx=(12, 0), pady=(8, 0))
        ui_combo = ttk.Combobox(card, textvariable=self.ui_language_var, state="readonly", width=14)
        ui_combo["values"] = list(SUPPORTED_UI_LANGS.keys())
        ui_combo.grid(row=9, column=3, sticky="w", pady=(8, 0))
        ui_combo.bind("<<ComboboxSelected>>", lambda _: self._on_ui_language_change())
        ttk.Button(
            card,
            text=self.tr("button.ai_translate_gui", "AI: szkic tlumaczenia GUI"),
            command=self._ai_translate_ui_language,
            style="Secondary.TButton",
        ).grid(row=9, column=4, columnspan=2, sticky="w", padx=(12, 0), pady=(8, 0))

        for i in range(6):
            card.columnconfigure(i, weight=1)

    def _build_model_card(self, parent: ttk.Frame) -> None:
        card = ttk.LabelFrame(parent, text=self.tr("section.model", "Model AI"), padding=12, style="Card.TLabelframe")
        card.pack(fill="x", pady=(0, self._theme_space("space_sm", 8)))

        self.model_combo = ttk.Combobox(card, textvariable=self.model_var, state="readonly")
        self.model_combo.grid(row=0, column=0, sticky="ew")
        ttk.Button(card, text="Health check I/O", command=self._health_check_providers, style="Secondary.TButton").grid(row=0, column=2, padx=(8, 0))
        ttk.Button(card, text=self.tr("button.refresh_models", "OdÄąâ€şwieÄąÄ˝ listĂ„â„˘ modeli"), command=self._refresh_models, style="Secondary.TButton").grid(row=0, column=1, padx=(8, 0))

        self.model_status = ttk.Label(card, text="", style="Sub.TLabel")
        self.model_status.grid(row=1, column=0, columnspan=3, sticky="w", pady=(6, 0))
        ttk.Label(card, textvariable=self.health_trend_var, style="Helper.TLabel").grid(row=2, column=0, columnspan=3, sticky="w", pady=(2, 0))

        card.columnconfigure(0, weight=1)

    def _build_run_card(self, parent: ttk.Frame) -> None:
        card = ttk.LabelFrame(parent, text=self.tr("section.run", "Uruchomienie"), padding=12, style="Card.TLabelframe")
        card.pack(fill="x", pady=(0, self._theme_space("space_sm", 8)))

        ttk.Label(card, text=self.tr("run.command_preview", "PodglĂ„â€¦d komendy:")).pack(anchor="w")
        ttk.Entry(card, textvariable=self.command_preview_var, state="readonly").pack(fill="x", pady=(4, 8))
        ttk.Label(
            card,
            text=self.tr("ui.hint.shortcuts", "SkrÄ‚Ĺ‚ty: Ctrl+S zapisz, Ctrl+R start, Ctrl+Q kolejkuj, F5 modele."),
            style="Helper.TLabel",
        ).pack(anchor="w", pady=(0, self._theme_space("space_sm", 8)))
        ttk.Checkbutton(
            card,
            text=self.tr("label.hard_gate_epubcheck", "Hard gate EPUBCheck (blokuj finalizacje przy bledzie EPUBCheck)"),
            variable=self.hard_gate_epubcheck_var,
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
        ttk.Button(btns, text=self.tr("button.run_next", "Uruchom nastĂ„â„˘pny"), command=self._run_next_pending, style="Secondary.TButton").pack(side="left", padx=(8, 0))
        self.run_all_btn = ttk.Button(btns, text=self.tr("button.run_all_pending", "Run all pending"), command=self._start_run_all_pending, style="Secondary.TButton")
        self.run_all_btn.pack(side="left", padx=(8, 0))
        self.stop_run_all_btn = ttk.Button(btns, text=self.tr("button.stop_run_all", "Stop run-all"), command=self._stop_run_all_pending, state="disabled", style="Danger.TButton")
        self.stop_run_all_btn.pack(side="left", padx=(8, 0))

        quick = ttk.Frame(card)
        quick.pack(fill="x", pady=(8, 0))
        ttk.Button(quick, text=self.tr("button.open_output", "OtwÄ‚Ĺ‚rz output"), command=self._open_output, style="Secondary.TButton").pack(side="left")
        ttk.Button(quick, text=self.tr("button.open_cache", "OtwÄ‚Ĺ‚rz cache"), command=self._open_cache, style="Secondary.TButton").pack(side="left", padx=(8, 0))
        ttk.Button(quick, text=self.tr("button.clear_debug", "WyczyÄąâ€şĂ„â€ˇ debug"), command=self._clear_debug, style="Secondary.TButton").pack(side="left", padx=(8, 0))
        ttk.Label(quick, textvariable=self.estimate_var, style="Sub.TLabel").pack(side="right")
        ttk.Label(quick, textvariable=self.queue_status_var, style="Sub.TLabel").pack(side="right", padx=(0, 12))

        progress_wrap = ttk.Frame(card)
        progress_wrap.pack(fill="x", pady=(10, 0))
        ttk.Label(progress_wrap, textvariable=self.progress_text_var, style="Sub.TLabel").pack(anchor="w")
        self.progress_bar = ttk.Progressbar(progress_wrap, mode="determinate", variable=self.progress_value_var, maximum=100.0)
        self.progress_bar.pack(fill="x", pady=(4, 0))
        ttk.Label(progress_wrap, textvariable=self.ledger_status_var, style="Sub.TLabel").pack(anchor="w", pady=(6, 0))
        self.ledger_canvas = tk.Canvas(
            progress_wrap,
            height=10,
            highlightthickness=0,
            bd=0,
            bg=self._theme_color("surface_bg", "#f8fafc"),
        )
        self.ledger_canvas.pack(fill="x", pady=(4, 0))
        self.ledger_canvas.bind("<Configure>", lambda _: self._draw_ledger_bar())
        ttk.Label(progress_wrap, textvariable=self.phase_var, style="Sub.TLabel").pack(anchor="w", pady=(4, 0))

    def _build_enhance_card(self, parent: ttk.Frame) -> None:
        card = ttk.LabelFrame(parent, text=self.tr("section.enhance", "UÄąâ€šadnianie EPUB"), padding=12, style="Card.TLabelframe")
        card.pack(fill="x", pady=(0, self._theme_space("space_sm", 8)))

        row1 = ttk.Frame(card)
        row1.pack(fill="x")
        ttk.Button(row1, text=self.tr("button.add_card_single", "Dodaj wizytÄ‚Ĺ‚wkĂ„â„˘ (1 EPUB)"), command=self._add_card_single, style="Secondary.TButton").pack(side="left")
        ttk.Button(row1, text=self.tr("button.add_card_batch", "Dodaj wizytÄ‚Ĺ‚wkĂ„â„˘ (folder)"), command=self._add_card_batch, style="Secondary.TButton").pack(side="left", padx=(8, 0))

        row2 = ttk.Frame(card)
        row2.pack(fill="x", pady=(8, 0))
        ttk.Button(row2, text=self.tr("button.remove_cover", "UsuÄąâ€ž okÄąâ€šadkĂ„â„˘"), command=self._remove_cover, style="Danger.TButton").pack(side="left")
        ttk.Button(row2, text=self.tr("button.remove_graphics_pattern", "UsuÄąâ€ž grafiki (pattern)"), command=self._remove_graphics_pattern, style="Danger.TButton").pack(side="left", padx=(8, 0))

        row3 = ttk.Frame(card)
        row3.pack(fill="x", pady=(8, 0))
        ttk.Button(row3, text=self.tr("button.open_text_editor", "Edytor tekstu EPUB"), command=self._open_text_editor, style="Secondary.TButton").pack(side="left")
        ttk.Button(row3, text=self.tr("button.undo_last_operation", "Cofnij ostatniĂ„â€¦ operacjĂ„â„˘"), command=self._undo_last_operation, style="Secondary.TButton").pack(side="left", padx=(8, 0))
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
            self._refresh_ledger_status()
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
            series_name = str(r.get("series") or "").strip()
            name_short = self._short_text(name, 34)
            book_short = self._short_text(book, 44)
            series_short = self._short_text(series_name, 28) if series_name else ""
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
                f"{name_short} | {st}/{step} | ks={book_short}"
                f"{(' | ser=' + series_short) if series_short else ''} | "
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

    def _series_none_label(self) -> str:
        return self.tr("series.none", "(brak serii)")

    def _refresh_series(self) -> None:
        rows = self.db.list_series()
        self.series_name_to_id = {}
        self.series_id_to_slug = {}
        names: List[str] = [self._series_none_label()]
        for r in rows:
            name = str(r["name"] or "").strip()
            if not name:
                continue
            names.append(name)
            self.series_name_to_id[name] = int(r["id"])
            self.series_id_to_slug[int(r["id"])] = str(r["slug"] or "")
        if hasattr(self, "series_combo"):
            self.series_combo["values"] = names
        current = self.series_var.get().strip()
        if not current or (current not in self.series_name_to_id and current != self._series_none_label()):
            self.series_var.set(self._series_none_label())

    def _selected_series_id(self) -> Optional[int]:
        name = self.series_var.get().strip()
        if not name or name == self._series_none_label():
            return None
        return self.series_name_to_id.get(name)

    def _set_series_by_id(self, series_id: Optional[int]) -> None:
        if series_id is None:
            self.series_var.set(self._series_none_label())
            return
        row = self.db.get_series(int(series_id))
        if row is None:
            self.series_var.set(self._series_none_label())
            return
        self.series_var.set(str(row["name"] or self._series_none_label()))

    def _parse_volume_no(self) -> Optional[float]:
        raw = (self.volume_no_var.get() or "").strip()
        if not raw:
            return None
        try:
            return float(raw.replace(",", "."))
        except Exception:
            return None

    def _on_series_selected(self) -> None:
        if self._selected_series_id() is None:
            self.volume_no_var.set("")
        self._save_project()

    def _create_series(self) -> None:
        name = simple_prompt(self.root, "Nowa seria", "Nazwa serii:")
        if not name:
            return
        name = name.strip()
        if not name:
            return
        try:
            sid = self.db.ensure_series(name, source="manual")
            row = self.db.get_series(sid)
            slug = str(row["slug"] or "") if row else ""
            if slug:
                self.series_store.ensure_series_db(slug, display_name=name)
        except Exception as e:
            self._msg_error(f"Nie udalo sie utworzyc serii:\n{e}")
            return
        self._refresh_series()
        self._set_series_by_id(sid)
        self._save_project()
        self._set_status(self.tr("status.series_created", "Series created: {name}", name=name), "ready")

    def _edit_series(self) -> None:
        series_id = self._selected_series_id()
        if series_id is None:
            self._msg_info("Wybierz serie do edycji.")
            return
        row = self.db.get_series(series_id)
        if row is None:
            self._refresh_series()
            self._msg_error("Nie znaleziono danych serii.")
            return
        current_name = str(row["name"] or "").strip()
        new_name = simple_prompt(
            self.root,
            "Edytuj serie",
            "Nazwa serii:",
            default_value=current_name,
        )
        if new_name is None:
            return
        new_name = new_name.strip()
        if not new_name:
            self._msg_info("Nazwa serii nie moze byc pusta.")
            return
        if new_name == current_name:
            return
        try:
            self.db.update_series(
                series_id,
                name=new_name,
                source=str(row["source"] or "manual"),
                notes=str(row["notes"] or ""),
                regenerate_slug=False,
            )
            slug = str(row["slug"] or "").strip()
            if slug:
                self.series_store.ensure_series_db(slug, display_name=new_name)
        except Exception as e:
            self._msg_error(f"Nie udalo sie zaktualizowac serii:\n{e}")
            return
        self._refresh_series()
        self._set_series_by_id(series_id)
        self._save_project()
        self._refresh_projects(select_current=True)
        self._refresh_status_panel()
        self._set_status(self.tr("status.series_updated", "Series updated: {name}", name=new_name), "ready")

    def _delete_series(self) -> None:
        series_id = self._selected_series_id()
        if series_id is None:
            self._msg_info("Wybierz serie do usuniecia.")
            return
        row = self.db.get_series(series_id)
        if row is None:
            self._refresh_series()
            self._msg_error("Nie znaleziono danych serii.")
            return
        series_name = str(row["name"] or "").strip() or f"#{series_id}"
        series_slug = str(row["slug"] or "").strip()
        project_count = self.db.count_projects_for_series(series_id)
        msg = (
            f"Usunac serie '{series_name}'?\n\n"
            f"Powiazane projekty: {project_count}\n"
            f"Po usunieciu projekty zostana odpiete od tej serii."
        )
        if not self._ask_yes_no(msg, title="Usun serie"):
            return

        series_dir = self.series_store.series_dir(series_slug) if series_slug else None
        delete_local_data = False
        if series_dir is not None and series_dir.exists():
            delete_local_data = self._ask_yes_no(
                f"Czy usunac tez lokalne dane serii?\n{series_dir}",
                title="Usun dane serii",
            )

        try:
            deleted = self.db.delete_series(series_id)
            if deleted <= 0:
                self._msg_error("Nie udalo sie usunac serii.")
                return
        except Exception as e:
            self._msg_error(f"Nie udalo sie usunac serii:\n{e}")
            return

        local_err = ""
        if delete_local_data and series_dir is not None and series_dir.exists():
            try:
                shutil.rmtree(series_dir)
            except Exception as e:
                local_err = str(e)

        self.volume_no_var.set("")
        self._refresh_series()
        self._refresh_projects(select_current=True)
        self._refresh_status_panel()
        self._save_project()
        self._set_status(self.tr("status.series_deleted", "Series deleted: {name}", name=series_name), "ready")
        if local_err:
            self._msg_error(f"Seria usunieta, ale nie udalo sie usunac danych lokalnych:\n{local_err}")

    def _detect_series_for_input(self) -> None:
        in_path = Path((self.input_epub_var.get() or "").strip())
        if not in_path.exists():
            self._msg_info("Najpierw wskaz plik EPUB.")
            return
        hint = detect_series_hint(in_path)
        if hint is None:
            self._msg_info("Nie wykryto serii w metadanych EPUB.")
            return
        vol_text = f" | tom={hint.volume_no}" if hint.volume_no is not None else ""
        msg = (
            f"Wykryto serie:\n"
            f"- nazwa: {hint.name}\n"
            f"- zrodlo: {hint.source}\n"
            f"- pewnosc: {hint.confidence:.2f}{vol_text}\n\n"
            f"Przypisac do projektu?"
        )
        if not self._ask_yes_no(msg, title="Autodetekcja serii"):
            return
        try:
            sid = self.db.ensure_series(hint.name, source=f"epub:{hint.source}")
            row = self.db.get_series(sid)
            slug = str(row["slug"] or "") if row else ""
            if slug:
                self.series_store.ensure_series_db(slug, display_name=hint.name)
        except Exception as e:
            self._msg_error(f"Nie udalo sie przypisac serii:\n{e}")
            return
        self._refresh_series()
        self._set_series_by_id(sid)
        if hint.volume_no is not None:
            self.volume_no_var.set(str(hint.volume_no))
        self._save_project()
        self._set_status(self.tr("status.series_detected", "Series detected and assigned"), "ready")

    def _open_series_terms_manager(self) -> None:
        series_id = self._selected_series_id()
        if series_id is None and self.current_project_id is not None:
            row = self.db.get_project(self.current_project_id)
            if row is not None:
                raw = row["series_id"]
                if raw is not None:
                    series_id = int(raw)
        if series_id is None:
            self._msg_info("Wybierz serie projektu.")
            return
        series_row = self.db.get_series(series_id)
        if series_row is None:
            self._msg_error("Nie znaleziono danych serii.")
            return
        series_name = str(series_row["name"] or "")
        series_slug = str(series_row["slug"] or "")
        if not series_slug:
            self._msg_error("Seria nie ma poprawnego slug.")
            return
        self.series_store.ensure_series_db(series_slug, display_name=series_name)

        win = tk.Toplevel(self.root)
        win.title(f"Series manager: {series_name}")
        win.transient(self.root)
        win.geometry("1180x700")

        wrap = ttk.Frame(win, padding=12)
        wrap.pack(fill="both", expand=True)
        wrap.rowconfigure(2, weight=1)
        wrap.columnconfigure(0, weight=1)

        info_var = tk.StringVar(value="Status: gotowe")
        ttk.Label(
            wrap,
            text="Series manager: termy, style rules, lorebook, historia zmian i batch serii.",
            style="Sub.TLabel",
        ).grid(row=0, column=0, sticky="w")

        top_actions = ttk.Frame(wrap)
        top_actions.grid(row=1, column=0, sticky="w", pady=(8, 6))

        def queue_series_for_current_step() -> None:
            step = (self.mode_var.get().strip().lower() or "translate")
            queued = self._queue_series_projects(series_id, step)
            self._refresh_projects(select_current=True)
            info_var.set(f"Status: kolejka serii ({step}) -> dodano {queued} projektow")

        def run_series_batch() -> None:
            step = (self.mode_var.get().strip().lower() or "translate")
            msg = (
                f"Uruchomic batch serii '{series_name}' dla kroku '{step}'?\n\n"
                "Aplikacja doda brakujace projekty do kolejki i uruchomi run-all."
            )
            if not self._ask_yes_no(msg, title="Series batch"):
                return
            self._start_series_batch_run(series_id, series_slug, series_name)
            info_var.set(f"Status: uruchomiono batch serii ({step})")

        def export_series_report() -> None:
            report = self._write_series_batch_report(
                series_id=series_id,
                series_slug=series_slug,
                series_name=series_name,
                step=(self.mode_var.get().strip().lower() or "translate"),
                outcome="manual-export",
            )
            if report is not None:
                self._open_path(report)
                info_var.set(f"Status: raport serii -> {report.name}")

        ttk.Button(top_actions, text="Queue series (current step)", command=queue_series_for_current_step, style="Secondary.TButton").pack(side="left")
        ttk.Button(top_actions, text="Run series batch", command=run_series_batch, style="Primary.TButton").pack(side="left", padx=(8, 0))
        ttk.Button(top_actions, text="Export series report", command=export_series_report, style="Secondary.TButton").pack(side="left", padx=(8, 0))

        tabs = ttk.Notebook(wrap)
        tabs.grid(row=2, column=0, sticky="nsew")

        terms_tab = ttk.Frame(tabs, padding=8)
        style_tab = ttk.Frame(tabs, padding=8)
        lore_tab = ttk.Frame(tabs, padding=8)
        history_tab = ttk.Frame(tabs, padding=8)

        tabs.add(terms_tab, text="Termy")
        tabs.add(style_tab, text="Style rules")
        tabs.add(lore_tab, text="Lorebook")
        tabs.add(history_tab, text="Historia")

        terms_tab.rowconfigure(0, weight=1)
        terms_tab.columnconfigure(0, weight=1)
        style_tab.rowconfigure(0, weight=1)
        style_tab.columnconfigure(0, weight=1)
        lore_tab.rowconfigure(0, weight=1)
        lore_tab.columnconfigure(0, weight=1)
        history_tab.rowconfigure(0, weight=1)
        history_tab.columnconfigure(0, weight=1)

        term_cols = ("id", "source", "target", "status", "confidence", "origin", "updated")
        term_tree = ttk.Treeview(terms_tab, columns=term_cols, show="headings", height=14)
        term_tree.grid(row=0, column=0, sticky="nsew")
        for c, label, width in [
            ("id", "ID", 60),
            ("source", "Source term", 220),
            ("target", "Target term", 240),
            ("status", "Status", 90),
            ("confidence", "Conf.", 70),
            ("origin", "Origin", 130),
            ("updated", "Updated", 120),
        ]:
            term_tree.heading(c, text=label)
            term_tree.column(c, width=width, anchor="w")
        term_ybar = ttk.Scrollbar(terms_tab, orient="vertical", command=term_tree.yview)
        term_ybar.grid(row=0, column=1, sticky="ns")
        term_tree.configure(yscrollcommand=term_ybar.set)

        style_cols = ("id", "rule_key", "instruction", "updated")
        style_tree = ttk.Treeview(style_tab, columns=style_cols, show="headings", height=14)
        style_tree.grid(row=0, column=0, sticky="nsew")
        for c, label, width in [
            ("id", "ID", 60),
            ("rule_key", "Rule key", 220),
            ("instruction", "Instruction", 620),
            ("updated", "Updated", 120),
        ]:
            style_tree.heading(c, text=label)
            style_tree.column(c, width=width, anchor="w")
        style_ybar = ttk.Scrollbar(style_tab, orient="vertical", command=style_tree.yview)
        style_ybar.grid(row=0, column=1, sticky="ns")
        style_tree.configure(yscrollcommand=style_ybar.set)

        lore_cols = ("id", "entry_key", "title", "status", "tags", "updated")
        lore_tree = ttk.Treeview(lore_tab, columns=lore_cols, show="headings", height=14)
        lore_tree.grid(row=0, column=0, sticky="nsew")
        for c, label, width in [
            ("id", "ID", 60),
            ("entry_key", "Entry key", 180),
            ("title", "Title", 300),
            ("status", "Status", 100),
            ("tags", "Tags", 260),
            ("updated", "Updated", 120),
        ]:
            lore_tree.heading(c, text=label)
            lore_tree.column(c, width=width, anchor="w")
        lore_ybar = ttk.Scrollbar(lore_tab, orient="vertical", command=lore_tree.yview)
        lore_ybar.grid(row=0, column=1, sticky="ns")
        lore_tree.configure(yscrollcommand=lore_ybar.set)

        history_cols = ("id", "entity_type", "entity_key", "action", "created", "payload")
        history_tree = ttk.Treeview(history_tab, columns=history_cols, show="headings", height=14)
        history_tree.grid(row=0, column=0, sticky="nsew")
        for c, label, width in [
            ("id", "ID", 60),
            ("entity_type", "Type", 100),
            ("entity_key", "Key", 220),
            ("action", "Action", 100),
            ("created", "Created", 120),
            ("payload", "Payload", 500),
        ]:
            history_tree.heading(c, text=label)
            history_tree.column(c, width=width, anchor="w")
        history_ybar = ttk.Scrollbar(history_tab, orient="vertical", command=history_tree.yview)
        history_ybar.grid(row=0, column=1, sticky="ns")
        history_tree.configure(yscrollcommand=history_ybar.set)

        style_cache: Dict[int, Dict[str, Any]] = {}
        lore_cache: Dict[int, Dict[str, Any]] = {}

        def _selected_id(tree: ttk.Treeview) -> Optional[int]:
            sel = tree.selection()
            if not sel:
                return None
            values = tree.item(sel[0], "values")
            if not values:
                return None
            try:
                return int(values[0])
            except Exception:
                return None

        def refresh_terms(status: Optional[str] = None) -> None:
            for item in term_tree.get_children():
                term_tree.delete(item)
            rows = self.series_store.list_terms(series_slug, status=status, limit=2000)
            for row in rows:
                term_tree.insert(
                    "",
                    "end",
                    values=(
                        int(row["id"]),
                        str(row["source_term"] or ""),
                        str(row["target_term"] or ""),
                        str(row["status"] or ""),
                        f"{float(row['confidence'] or 0.0):.2f}",
                        str(row["origin"] or ""),
                        str(row["updated_at"] or ""),
                    ),
                )
            info_var.set(f"Status: termy={len(rows)}")

        def refresh_style() -> None:
            style_cache.clear()
            for item in style_tree.get_children():
                style_tree.delete(item)
            rows = self.series_store.list_style_rules(series_slug, limit=2000)
            for row in rows:
                rid = int(row["id"])
                payload = self.series_store._json_loads(str(row["value_json"] or "{}"), {})
                style_cache[rid] = {
                    "rule_key": str(row["rule_key"] or ""),
                    "payload": payload,
                    "updated_at": int(row["updated_at"] or 0),
                }
                if isinstance(payload, dict):
                    text = str(payload.get("instruction") or payload.get("value") or payload.get("text") or "").strip()
                    if not text:
                        text = json.dumps(payload, ensure_ascii=False)
                else:
                    text = str(payload).strip()
                style_tree.insert(
                    "",
                    "end",
                    values=(rid, str(row["rule_key"] or ""), text, str(row["updated_at"] or "")),
                )
            info_var.set(f"Status: style_rules={len(rows)}")

        def refresh_lore(status: Optional[str] = None) -> None:
            lore_cache.clear()
            for item in lore_tree.get_children():
                lore_tree.delete(item)
            rows = self.series_store.list_lore_entries(series_slug, status=status, limit=3000)
            for row in rows:
                lid = int(row["id"])
                tags = self.series_store._json_loads(str(row["tags_json"] or "[]"), [])
                if not isinstance(tags, list):
                    tags = []
                clean_tags = [str(t).strip() for t in tags if str(t).strip()]
                lore_cache[lid] = {
                    "entry_key": str(row["entry_key"] or ""),
                    "title": str(row["title"] or ""),
                    "content": str(row["content"] or ""),
                    "status": str(row["status"] or "draft"),
                    "tags": clean_tags,
                    "updated_at": int(row["updated_at"] or 0),
                }
                lore_tree.insert(
                    "",
                    "end",
                    values=(
                        lid,
                        str(row["entry_key"] or ""),
                        str(row["title"] or ""),
                        str(row["status"] or ""),
                        ", ".join(clean_tags),
                        str(row["updated_at"] or ""),
                    ),
                )
            info_var.set(f"Status: lore_entries={len(rows)}")

        def refresh_history(entity_type: Optional[str] = None) -> None:
            for item in history_tree.get_children():
                history_tree.delete(item)
            rows = self.series_store.list_change_log(series_slug, entity_type=entity_type, limit=1000)
            for row in rows:
                payload = str(row["payload_json"] or "")
                payload_short = payload if len(payload) <= 180 else payload[:177] + "..."
                history_tree.insert(
                    "",
                    "end",
                    values=(
                        int(row["id"]),
                        str(row["entity_type"] or ""),
                        str(row["entity_key"] or ""),
                        str(row["action"] or ""),
                        str(row["created_at"] or ""),
                        payload_short,
                    ),
                )
            info_var.set(f"Status: historia={len(rows)} wpisow")

        def refresh_all() -> None:
            refresh_terms()
            refresh_style()
            refresh_lore()
            refresh_history()

        def set_term_status(status: str) -> None:
            tid = _selected_id(term_tree)
            if tid is None:
                return
            self.series_store.set_term_status(series_slug, tid, status=status)
            refresh_terms()
            refresh_history("term")

        def add_manual_term() -> None:
            src = simple_prompt(win, "Nowy termin", "Source term:")
            if not src:
                return
            tgt = simple_prompt(win, "Nowy termin", "Target term:")
            if not tgt:
                return
            self.series_store.add_or_update_term(
                series_slug,
                source_term=src.strip(),
                target_term=tgt.strip(),
                status="approved",
                confidence=1.0,
                origin="manual",
                project_id=self.current_project_id,
            )
            refresh_terms()
            refresh_history("term")

        def learn_from_project_tm() -> None:
            if self.current_project_id is None:
                self._msg_info("Wybierz projekt przypisany do serii.")
                return
            rows = [dict(r) for r in self.db.list_tm_segments(project_id=self.current_project_id, limit=2500)]
            added = self.series_store.learn_terms_from_tm(series_slug, rows, project_id=self.current_project_id)
            info_var.set(f"Status: dodano {added} propozycji z TM")
            refresh_terms()
            refresh_history("term")

        def export_glossary() -> None:
            out = self.series_store.export_approved_glossary(series_slug)
            self._open_path(out)
            info_var.set(f"Status: export -> {out.name}")

        def add_or_edit_style(default_key: str = "", default_instr: str = "") -> None:
            rule_key = simple_prompt(win, "Style rule", "Rule key:", default_value=default_key)
            if not rule_key:
                return
            instruction = multiline_prompt(
                win,
                "Style rule",
                "Instruction (applied to series prompt):",
                default_value=default_instr,
                width=95,
                height=10,
            )
            if instruction is None:
                return
            self.series_store.upsert_style_rule(
                series_slug,
                rule_key=rule_key.strip(),
                value={"instruction": instruction.strip(), "source": "manual"},
            )
            refresh_style()
            refresh_history("style_rule")

        def edit_selected_style() -> None:
            rid = _selected_id(style_tree)
            if rid is None:
                return
            row = style_cache.get(rid)
            if not row:
                return
            payload = row.get("payload") if isinstance(row.get("payload"), dict) else {}
            add_or_edit_style(
                default_key=str(row.get("rule_key") or ""),
                default_instr=str((payload or {}).get("instruction") or ""),
            )

        def delete_selected_style() -> None:
            rid = _selected_id(style_tree)
            if rid is None:
                return
            if not self._ask_yes_no("Usunac wybrana style rule?", title="Style rule"):
                return
            self.series_store.delete_style_rule(series_slug, rid)
            refresh_style()
            refresh_history("style_rule")

        def add_or_edit_lore(default: Optional[Dict[str, Any]] = None) -> None:
            default = default or {}
            title = simple_prompt(win, "Lore entry", "Title:", default_value=str(default.get("title") or ""))
            if not title:
                return
            key = simple_prompt(
                win,
                "Lore entry",
                "Entry key (slug, optional):",
                default_value=str(default.get("entry_key") or ""),
            )
            content = multiline_prompt(
                win,
                "Lore entry",
                "Content:",
                default_value=str(default.get("content") or ""),
                width=95,
                height=12,
            )
            if content is None or not content.strip():
                return
            tags_raw = simple_prompt(
                win,
                "Lore entry",
                "Tags (comma separated):",
                default_value=", ".join([str(t) for t in (default.get("tags") or [])]),
            )
            status = simple_prompt(
                win,
                "Lore entry",
                "Status (draft/active/archived):",
                default_value=str(default.get("status") or "draft"),
            )
            tags = [x.strip() for x in str(tags_raw or "").split(",") if x.strip()]
            self.series_store.upsert_lore_entry(
                series_slug,
                entry_key=str(key or "").strip() or str(default.get("entry_key") or ""),
                title=title.strip(),
                content=content.strip(),
                tags=tags,
                status=str(status or "draft"),
            )
            refresh_lore()
            refresh_history("lore")

        def edit_selected_lore() -> None:
            lid = _selected_id(lore_tree)
            if lid is None:
                return
            row = lore_cache.get(lid)
            if not row:
                return
            add_or_edit_lore(default=row)

        def set_selected_lore_status(status: str) -> None:
            lid = _selected_id(lore_tree)
            if lid is None:
                return
            self.series_store.set_lore_status(series_slug, lid, status)
            refresh_lore()
            refresh_history("lore")

        def delete_selected_lore() -> None:
            lid = _selected_id(lore_tree)
            if lid is None:
                return
            if not self._ask_yes_no("Usunac wpis lore?", title="Lorebook"):
                return
            self.series_store.delete_lore_entry(series_slug, lid)
            refresh_lore()
            refresh_history("lore")

        def export_series_profile() -> None:
            out = self.series_store.export_series_profile(series_slug)
            self._open_path(out)
            info_var.set(f"Status: export profile -> {out.name}")

        def import_series_profile() -> None:
            picked = filedialog.askopenfilename(
                title="Import profile JSON",
                initialdir=str(self.workdir),
                filetypes=[("JSON", "*.json"), ("All", "*.*")],
            )
            if not picked:
                return
            try:
                stats = self.series_store.import_series_profile(series_slug, Path(picked))
            except Exception as e:
                self._msg_error(f"Import profile failed:\n{e}")
                return
            refresh_all()
            info_var.set(
                "Status: import profile -> "
                f"style+{int(stats.get('style_added', 0))}, "
                f"lore+{int(stats.get('lore_added', 0))}, "
                f"terms+{int(stats.get('terms_added', 0))}"
            )

        term_btn = ttk.Frame(terms_tab)
        term_btn.grid(row=1, column=0, sticky="w", pady=(8, 0))
        ttk.Button(term_btn, text="Refresh", command=refresh_terms).pack(side="left")
        ttk.Button(term_btn, text="Only proposed", command=lambda: refresh_terms("proposed"), style="Secondary.TButton").pack(side="left", padx=(8, 0))
        ttk.Button(term_btn, text="Approve", command=lambda: set_term_status("approved"), style="Primary.TButton").pack(side="left", padx=(8, 0))
        ttk.Button(term_btn, text="Reject", command=lambda: set_term_status("rejected"), style="Danger.TButton").pack(side="left", padx=(8, 0))
        ttk.Button(term_btn, text="Add manual", command=add_manual_term, style="Secondary.TButton").pack(side="left", padx=(8, 0))
        ttk.Button(term_btn, text="Learn from TM", command=learn_from_project_tm, style="Secondary.TButton").pack(side="left", padx=(8, 0))
        ttk.Button(term_btn, text="Export glossary", command=export_glossary, style="Secondary.TButton").pack(side="left", padx=(8, 0))

        style_btn = ttk.Frame(style_tab)
        style_btn.grid(row=1, column=0, sticky="w", pady=(8, 0))
        ttk.Button(style_btn, text="Refresh", command=refresh_style).pack(side="left")
        ttk.Button(style_btn, text="Add style rule", command=lambda: add_or_edit_style(), style="Secondary.TButton").pack(side="left", padx=(8, 0))
        ttk.Button(style_btn, text="Edit selected", command=edit_selected_style, style="Secondary.TButton").pack(side="left", padx=(8, 0))
        ttk.Button(style_btn, text="Delete selected", command=delete_selected_style, style="Danger.TButton").pack(side="left", padx=(8, 0))
        ttk.Button(style_btn, text="Export series profile", command=export_series_profile, style="Secondary.TButton").pack(side="left", padx=(8, 0))
        ttk.Button(style_btn, text="Import series profile", command=import_series_profile, style="Secondary.TButton").pack(side="left", padx=(8, 0))

        lore_btn = ttk.Frame(lore_tab)
        lore_btn.grid(row=1, column=0, sticky="w", pady=(8, 0))
        ttk.Button(lore_btn, text="Refresh", command=lambda: refresh_lore()).pack(side="left")
        ttk.Button(lore_btn, text="Only active", command=lambda: refresh_lore("active"), style="Secondary.TButton").pack(side="left", padx=(8, 0))
        ttk.Button(lore_btn, text="Add entry", command=lambda: add_or_edit_lore(), style="Secondary.TButton").pack(side="left", padx=(8, 0))
        ttk.Button(lore_btn, text="Edit selected", command=edit_selected_lore, style="Secondary.TButton").pack(side="left", padx=(8, 0))
        ttk.Button(lore_btn, text="Set active", command=lambda: set_selected_lore_status("active"), style="Primary.TButton").pack(side="left", padx=(8, 0))
        ttk.Button(lore_btn, text="Archive", command=lambda: set_selected_lore_status("archived"), style="Danger.TButton").pack(side="left", padx=(8, 0))
        ttk.Button(lore_btn, text="Delete selected", command=delete_selected_lore, style="Danger.TButton").pack(side="left", padx=(8, 0))

        hist_btn = ttk.Frame(history_tab)
        hist_btn.grid(row=1, column=0, sticky="w", pady=(8, 0))
        ttk.Button(hist_btn, text="Refresh", command=lambda: refresh_history()).pack(side="left")
        ttk.Button(hist_btn, text="Only terms", command=lambda: refresh_history("term"), style="Secondary.TButton").pack(side="left", padx=(8, 0))
        ttk.Button(hist_btn, text="Only style", command=lambda: refresh_history("style_rule"), style="Secondary.TButton").pack(side="left", padx=(8, 0))
        ttk.Button(hist_btn, text="Only lore", command=lambda: refresh_history("lore"), style="Secondary.TButton").pack(side="left", padx=(8, 0))

        ttk.Label(wrap, textvariable=info_var, style="Sub.TLabel").grid(row=3, column=0, sticky="w", pady=(8, 0))
        refresh_all()

    def _default_project_values(self, source_epub: Path) -> Dict[str, Any]:
        src_lang = (self.source_lang_var.get() or "en").strip().lower()
        tgt_lang = (self.target_lang_var.get() or "pl").strip().lower()
        prompt_translate = str((self.workdir / "prompt.txt")) if (self.workdir / "prompt.txt").exists() else ""
        prompt_edit = str((self.workdir / "prompt_redakcja.txt")) if (self.workdir / "prompt_redakcja.txt").exists() else ""
        out_translate = suggest_paths_for_step(source_epub, target_lang=tgt_lang, step="translate")
        out_edit = suggest_paths_for_step(source_epub, target_lang=tgt_lang, step="edit")
        gloss = self._find_glossary(self.workdir)
        profiles = self.db.list_profiles()
        profile_translate = None
        profile_edit = None
        for p in profiles:
            if p["name"] == "Google-fast":
                profile_translate = int(p["id"])
            if p["name"] == "Ollama-quality":
                profile_edit = int(p["id"])
        series_id = self._selected_series_id()
        volume_no = self._parse_volume_no()
        return {
            "series_id": series_id,
            "volume_no": volume_no,
            "input_epub": str(source_epub),
            "output_translate_epub": str(out_translate.output_epub),
            "output_edit_epub": str(out_edit.output_epub),
            "prompt_translate": prompt_translate,
            "prompt_edit": prompt_edit or prompt_translate,
            "glossary_path": str(gloss) if gloss else "",
            "cache_translate_path": str(out_translate.cache_path),
            "cache_edit_path": str(out_edit.cache_path),
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
        if vals.get("series_id") is None and src.exists():
            hint = detect_series_hint(src)
            if hint is not None:
                vol_text = f" | tom={hint.volume_no}" if hint.volume_no is not None else ""
                msg = (
                    f"Wykryto serie dla nowego projektu:\n"
                    f"- {hint.name}\n"
                    f"- zrodlo: {hint.source}\n"
                    f"- pewnosc: {hint.confidence:.2f}{vol_text}\n\n"
                    f"Przypisac automatycznie?"
                )
                if self._ask_yes_no(msg, title="Autodetekcja serii"):
                    sid = self.db.ensure_series(hint.name, source=f"epub:{hint.source}")
                    vals["series_id"] = sid
                    if hint.volume_no is not None:
                        vals["volume_no"] = hint.volume_no
        try:
            pid = self.db.create_project(name, vals)
        except Exception as e:
            self._msg_error(f"{self.tr('err.project_create', 'Nie udalo sie utworzyc projektu:')}\n{e}")
            return

        if vals.get("series_id") is not None:
            series_row = self.db.get_series(int(vals["series_id"]))
            if series_row is not None:
                slug = str(series_row["slug"] or "")
                if slug:
                    self.series_store.ensure_series_db(slug, display_name=str(series_row["name"] or ""))
        self.current_project_id = pid
        self.db.set_setting("active_project_id", pid)
        self._refresh_series()
        self._refresh_projects(select_current=True)
        self._set_status(self.tr("status.project_created", "Project created: {name}", name=name), "ready")

    def _delete_project(self) -> None:
        if self.current_project_id is None:
            return
        answer = self._ask_yes_no(
            self.tr("confirm.project_delete_soft", "UsunĂ„â€¦Ă„â€ˇ projekt z listy? (historia zostanie zachowana)"),
            title=self.tr("title.project_delete", "UsuÄąâ€ž projekt"),
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
            self.tr("confirm.project_delete_hard", "UsunĂ„â€¦Ă„â€ˇ projekt trwale razem z historiĂ„â€¦ i TM powiĂ„â€¦zanym z projektem?"),
            title=self.tr("title.project_delete_hard", "UsuÄąâ€ž hard"),
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
        self.repo.mark_project_pending(self.current_project_id, step)
        self._refresh_projects(select_current=True)
        self._set_status(self.tr("status.project_queued", "Project queued ({step})", step=step), "ready")

    def _queue_series_projects(self, series_id: int, step: str) -> int:
        sid = int(series_id)
        want_step = (step or "translate").strip().lower()
        if want_step not in {"translate", "edit"}:
            want_step = "translate"
        summaries = self.repo.list_projects_with_stage_summary()
        summary_by_id = {int(r["id"]): r for r in summaries}
        queued = 0
        for project in self.repo.list_projects_for_series(sid, include_deleted=False):
            pid = int(project["id"])
            status = str(project["status"] or "idle").strip().lower()
            if status == "running":
                continue
            summary = summary_by_id.get(pid)
            if summary is None:
                continue
            tr_done = bool((summary.get("translate") or {}).get("is_complete"))
            ed_done = bool((summary.get("edit") or {}).get("is_complete"))
            if want_step == "translate":
                should_queue = not tr_done
            else:
                should_queue = tr_done and not ed_done
            if not should_queue:
                continue
            self.repo.mark_project_pending(pid, want_step)
            queued += 1
        return queued

    def _write_series_batch_report(
        self,
        *,
        series_id: int,
        series_slug: str,
        series_name: str,
        step: str,
        outcome: str,
    ) -> Optional[Path]:
        clean_slug = str(series_slug or "").strip()
        if not clean_slug:
            return None
        ts = datetime.datetime.now().strftime("%Y%m%d_%H%M%S")
        summaries = self.repo.list_projects_with_stage_summary()
        summary_by_id = {int(r["id"]): r for r in summaries}
        projects_payload: List[Dict[str, Any]] = []
        for project in self.repo.list_projects_for_series(int(series_id), include_deleted=False):
            pid = int(project["id"])
            summary = summary_by_id.get(pid)
            if summary is None:
                continue
            qa_open = self.repo.count_open_qa_findings(pid)
            projects_payload.append(
                {
                    "project_id": pid,
                    "name": str(project["name"] or ""),
                    "volume_no": project["volume_no"],
                    "status": str(project["status"] or ""),
                    "next_action": str(summary.get("next_action") or ""),
                    "translate": summary.get("translate") or {},
                    "edit": summary.get("edit") or {},
                    "qa_open": qa_open,
                }
            )

        counts = {"idle": 0, "pending": 0, "running": 0, "error": 0, "done": 0}
        for item in projects_payload:
            st = str(item.get("status") or "idle").strip().lower() or "idle"
            if st in counts:
                counts[st] += 1
            if bool((item.get("edit") or {}).get("is_complete")):
                counts["done"] += 1

        payload = {
            "series_id": int(series_id),
            "series_slug": clean_slug,
            "series_name": str(series_name or clean_slug),
            "step": str(step or "translate"),
            "outcome": str(outcome or "finished"),
            "generated_at": int(time.time()),
            "counts": counts,
            "projects": projects_payload,
        }
        out_dir = SERIES_DATA_DIR / clean_slug / "generated"
        out_dir.mkdir(parents=True, exist_ok=True)
        out_json = out_dir / f"series_batch_report_{ts}.json"
        out_md = out_dir / f"series_batch_report_{ts}.md"
        out_json.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")

        md_lines: List[str] = [
            f"# Series Batch Report: {str(series_name or clean_slug)}",
            "",
            f"- generated_at: {ts}",
            f"- step: {str(step or 'translate')}",
            f"- outcome: {str(outcome or 'finished')}",
            f"- counts: idle={counts['idle']} pending={counts['pending']} running={counts['running']} error={counts['error']} done={counts['done']}",
            "",
            "## Projects",
            "",
            "| ID | Volume | Name | Status | Next | Tr done/total | Edit done/total | QA open |",
            "|---:|---:|---|---|---|---:|---:|---:|",
        ]
        for item in projects_payload:
            tr = item.get("translate") or {}
            ed = item.get("edit") or {}
            md_lines.append(
                "| {pid} | {vol} | {name} | {status} | {next} | {tr_done}/{tr_total} | {ed_done}/{ed_total} | {qa} |".format(
                    pid=int(item.get("project_id") or 0),
                    vol=str(item.get("volume_no") if item.get("volume_no") is not None else "-"),
                    name=str(item.get("name") or "").replace("|", "/"),
                    status=str(item.get("status") or ""),
                    next=str(item.get("next_action") or ""),
                    tr_done=int((tr.get("done") or 0)),
                    tr_total=int((tr.get("total") or 0)),
                    ed_done=int((ed.get("done") or 0)),
                    ed_total=int((ed.get("total") or 0)),
                    qa=int(item.get("qa_open") or 0),
                )
            )
        out_md.write_text("\n".join(md_lines) + "\n", encoding="utf-8")
        return out_json

    def _run_next_pending(self) -> None:
        self._run_next_pending_internal(show_messages=True)

    def _run_next_pending_internal(self, show_messages: bool) -> bool:
        if self.proc is not None:
            if show_messages:
                self._msg_info(self.tr("info.process_running", "Proces juÄąÄ˝ dziaÄąâ€ša."))
            return False
        nxt = self.repo.get_next_pending_project()
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

    def _start_series_batch_run(self, series_id: int, series_slug: str, series_name: str) -> None:
        step = (self.mode_var.get().strip().lower() or "translate")
        queued = self._queue_series_projects(int(series_id), step)
        if queued <= 0:
            self._msg_info(f"Brak projektow serii do kolejkowania dla kroku '{step}'.")
            return
        self._refresh_projects(select_current=True)
        self.series_batch_context = {
            "series_id": int(series_id),
            "series_slug": str(series_slug or ""),
            "series_name": str(series_name or ""),
            "step": step,
            "started_at": int(time.time()),
            "queued_count": int(queued),
            "stopped": False,
        }
        self._set_status(f"Series batch queued: {queued} ({step})", "ready")
        self._start_run_all_pending()

    def _finalize_series_batch(self, outcome: str) -> None:
        ctx = self.series_batch_context
        if not ctx:
            return
        self.series_batch_context = None
        try:
            report = self._write_series_batch_report(
                series_id=int(ctx.get("series_id") or 0),
                series_slug=str(ctx.get("series_slug") or ""),
                series_name=str(ctx.get("series_name") or ""),
                step=str(ctx.get("step") or "translate"),
                outcome=str(outcome or "finished"),
            )
            if report is not None:
                self.log_queue.put(f"[SERIES-BATCH] Report: {report}\n")
        except Exception as e:
            self.log_queue.put(f"[SERIES-BATCH] Report failed: {e}\n")

    def _stop_run_all_pending(self) -> None:
        self.run_all_active = False
        if self.series_batch_context is not None:
            self.series_batch_context["stopped"] = True
        self.queue_status_var.set(self.tr("status.queue.stopping", "Queue: stopping after current task"))
        self.run_all_btn.configure(state="normal")
        self.stop_run_all_btn.configure(state="disabled")

    def _continue_run_all(self) -> None:
        if not self.run_all_active:
            self.queue_status_var.set(self.tr("status.queue.idle", "Queue: idle"))
            if self.series_batch_context is not None:
                outcome = "stopped" if bool(self.series_batch_context.get("stopped")) else "finished"
                self._finalize_series_batch(outcome)
            return
        started = self._run_next_pending_internal(show_messages=False)
        if not started:
            self.run_all_active = False
            self.queue_status_var.set(self.tr("status.queue.finished", "Queue: finished"))
            self.run_all_btn.configure(state="normal")
            self.stop_run_all_btn.configure(state="disabled")
            if self.series_batch_context is not None:
                self._finalize_series_batch("finished")

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
        google_retries = int(parsed.get("google_retries", 0) or 0)
        google_timeouts = int(parsed.get("google_timeouts", 0) or 0)
        ollama_retries = int(parsed.get("ollama_retries", 0) or 0)
        ollama_timeouts = int(parsed.get("ollama_timeouts", 0) or 0)
        if total > 0 and reuse_rate <= 0.0 and reuse_hits > 0:
            reuse_rate = (reuse_hits / total) * 100.0
        status = self._normalize_stage_status(str(last["status"] or "none"))
        step = str(last["step"] or "-")
        self.run_metrics_var.set(
            f"Ostatni run: {step}/{status} | czas={self._format_duration(duration_s)} | "
            f"seg={done}/{total} | cache={cache_hits} | tm={tm_hits} | reuse={reuse_rate:.1f}% | "
            f"G(r={google_retries},t={google_timeouts}) O(r={ollama_retries},t={ollama_timeouts})"
        )

    def _export_project(self) -> None:
        if self.current_project_id is None:
            self._msg_info(self.tr("info.select_project", "Wybierz projekt."))
            return
        payload = self.db.export_project(self.current_project_id)
        if payload is None:
            self._msg_error(self.tr("err.project_export", "Nie udaÄąâ€šo siĂ„â„˘ wyeksportowaĂ„â€ˇ projektu."))
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
        self._refresh_series()
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
        raw_series_id = row["series_id"]
        self._set_series_by_id(int(raw_series_id)) if raw_series_id is not None else self._set_series_by_id(None)
        raw_volume_no = row["volume_no"]
        self.volume_no_var.set("" if raw_volume_no is None else str(raw_volume_no))

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
        self._refresh_prompt_preset_options()
        self._update_command_preview()
        self._refresh_run_history()
        self._refresh_status_panel()
        self._refresh_ledger_status()
        self._set_status(self.tr("status.project_loaded", "Project loaded: {name}", name=name), "ready")

    def _save_project(self, notify_missing: bool = False) -> None:
        if self.current_project_id is None:
            if notify_missing:
                self._msg_info("Najpierw wybierz lub utwÄ‚Ĺ‚rz projekt.")
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
        series_id = self._selected_series_id()
        volume_no = self._parse_volume_no() if series_id is not None else None
        vals = {
            "series_id": series_id,
            "volume_no": volume_no,
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
            self._msg_error(f"{self.tr('err.profile_save', 'Nie udaÄąâ€šo siĂ„â„˘ zapisaĂ„â€ˇ profilu:')}\n{e}")
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
            "io_concurrency": self.io_concurrency_var.get(),
            "language_guard_config": self.language_guard_config_var.get(),
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
            self._msg_error(f"{self.tr('err.open_failed', 'Nie udaÄąâ€šo siĂ„â„˘ otworzyĂ„â€ˇ:')}\n{e}")

    def _open_url(self, url: str) -> None:
        u = (url or "").strip()
        if not u:
            return
        try:
            webbrowser.open(u, new=2)
        except Exception as e:
            self._msg_error(f"{self.tr('err.open_failed', 'Nie udaÄąâ€šo siĂ„â„˘ otworzyĂ„â€ˇ:')}\n{e}")

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
            body += f"\n... (+{len(lines)-30} wiĂ„â„˘cej)"
        return self._ask_yes_no(body + "\n\n" + self.tr("confirm.execute_operation", "WykonaĂ„â€ˇ tĂ„â„˘ operacjĂ„â„˘?"), title=title)

    def _push_operation(self, op: Dict[str, Any]) -> None:
        self.op_history.append(op)
        if len(self.op_history) > 200:
            self.op_history = self.op_history[-200:]

    def _undo_last_operation(self) -> None:
        if not self.op_history:
            self._msg_info("Brak operacji do cofniĂ„â„˘cia.")
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
            title="Wybierz obraz wizytÄ‚Ĺ‚wki",
            initialdir=str(self.workdir),
            filetypes=[("Obrazy", "*.png;*.jpg;*.jpeg;*.webp;*.gif"), ("All", "*.*")],
        )
        if not img:
            return
        title = simple_prompt(self.root, "WizytÄ‚Ĺ‚wka", "TytuÄąâ€š wizytÄ‚Ĺ‚wki:") or "Wizytowka"
        out = target.with_name(f"{target.stem}_wizytowka{target.suffix}")
        prev_out = self.output_epub_var.get().strip()
        try:
            prev = preview_add_front_matter(target, Path(img), title=title)
            ok = self._preview_and_confirm(
                "PodglĂ„â€¦d: wizytÄ‚Ĺ‚wka",
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
            self._msg_error(f"{self.tr('err.card_add_failed', 'Nie udaÄąâ€šo siĂ„â„˘ dodaĂ„â€ˇ wizytÄ‚Ĺ‚wki:')}\n{e}")

    def _add_card_batch(self) -> None:
        folder = filedialog.askdirectory(title="Folder z EPUB", initialdir=str(self.workdir))
        if not folder:
            return
        img = filedialog.askopenfilename(
            title="Wybierz obraz wizytÄ‚Ĺ‚wki",
            initialdir=str(self.workdir),
            filetypes=[("Obrazy", "*.png;*.jpg;*.jpeg;*.webp;*.gif"), ("All", "*.*")],
        )
        if not img:
            return
        title = simple_prompt(self.root, "WizytÄ‚Ĺ‚wka", "TytuÄąâ€š wizytÄ‚Ĺ‚wki (batch):") or "Wizytowka"
        epubs = sorted(Path(folder).glob("*.epub"))
        if not epubs:
            self._msg_info(self.tr("info.no_epubs_in_folder", "No EPUB files in folder."))
            return
        ok = self._preview_and_confirm(
            "PodglĂ„â€¦d: batch wizytÄ‚Ĺ‚wka",
            [f"Folder: {folder}", f"Liczba EPUB: {len(epubs)}", f"Obraz: {img}", f"TytuÄąâ€š: {title}"]
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
                "PodglĂ„â€¦d: usuÄąâ€ž okÄąâ€šadkĂ„â„˘",
                [
                    f"EPUB: {prev['epub']}",
                    f"Usuwane zasoby obrazÄ‚Ĺ‚w: {prev['remove_paths_count']}",
                    f"RozdziaÄąâ€šy dotkniĂ„â„˘te: {prev['affected_chapters_count']}",
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
            self._msg_error(f"{self.tr('err.cover_remove_failed', 'Nie udaÄąâ€šo siĂ„â„˘ usunĂ„â€¦Ă„â€ˇ okÄąâ€šadki:')}\n{e}")

    def _remove_graphics_pattern(self) -> None:
        target = self._pick_target_epub()
        if target is None:
            return
        pattern = simple_prompt(self.root, "UsuÄąâ€ž grafiki", "Regex dla nazw grafik/href:")
        if not pattern:
            return
        out = target.with_name(f"{target.stem}_bez_grafik{target.suffix}")
        prev_out = self.output_epub_var.get().strip()
        try:
            prev = preview_remove_images(target, remove_cover=False, pattern=pattern)
            ok = self._preview_and_confirm(
                "PodglĂ„â€¦d: usuÄąâ€ž grafiki",
                [
                    f"EPUB: {prev['epub']}",
                    f"Pattern: {pattern}",
                    f"Usuwane zasoby obrazÄ‚Ĺ‚w: {prev['remove_paths_count']}",
                    f"RozdziaÄąâ€šy dotkniĂ„â„˘te: {prev['affected_chapters_count']}",
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
            self._msg_error(f"{self.tr('err.graphics_remove_failed', 'Nie udaÄąâ€šo siĂ„â„˘ usunĂ„â€¦Ă„â€ˇ grafik:')}\n{e}")

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
        guard_default = self.workdir / "language_guards.json"
        if guard_default.exists() and not self.language_guard_config_var.get().strip():
            self.language_guard_config_var.set(str(guard_default))

        gloss = self._find_glossary(self.workdir)
        if gloss:
            self.glossary_var.set(str(gloss))

        saved_active = self.db.get_setting("active_project_id", None)
        if not isinstance(saved_active, int):
            self._apply_easy_startup_defaults()

        self._on_provider_change()

    def _pick_input_candidate(self, candidates: List[Path]) -> Optional[Path]:
        if not candidates:
            return None
        if len(candidates) == 1:
            return candidates[0]
        lines = [f"{idx + 1}. {p.name}" for idx, p in enumerate(candidates)]
        choice = simple_prompt(
            self.root,
            "Easy Startup",
            "Wykryto wiele plikow EPUB. Wpisz numer (domyslnie 1):\n" + "\n".join(lines),
            default_value="1",
        )
        if choice is None:
            return None
        return parse_ambiguous_choice(candidates, choice)

    def _pick_project_match(self, matches: List[Dict[str, Any]]) -> Optional[int]:
        if not matches:
            return None
        if len(matches) == 1:
            return int(matches[0]["id"])
        lines: List[str] = []
        for idx, row in enumerate(matches):
            name = str(row.get("name") or f"Project-{idx + 1}")
            updated = int(row.get("updated_at", 0) or 0)
            lines.append(f"{idx + 1}. {name} (updated_at={updated})")
        choice = simple_prompt(
            self.root,
            "Easy Startup",
            "Znaleziono kilka projektow pasujacych do wejscia i jezykow.\nWybierz numer:\n" + "\n".join(lines),
            default_value="1",
        )
        if choice is None:
            return None
        text = str(choice).strip()
        if not text:
            return int(matches[0]["id"])
        try:
            idx = int(text)
        except Exception:
            return None
        if idx < 1 or idx > len(matches):
            return None
        return int(matches[idx - 1]["id"])

    def _next_project_name(self, base_name: str) -> str:
        base = str(base_name or "project").strip() or "project"
        existing = {str(r["name"]).strip().lower() for r in self.db.list_projects()}
        if base.lower() not in existing:
            return base
        idx = 2
        while True:
            cand = f"{base}_{idx}"
            if cand.lower() not in existing:
                return cand
            idx += 1

    def _apply_easy_startup_defaults(self) -> None:
        current_input = self.input_epub_var.get().strip()
        selected_input: Optional[Path] = None
        if current_input and Path(current_input).exists():
            selected_input = Path(current_input)
        else:
            candidates = discover_input_epubs(self.workdir)
            selected_input = self._pick_input_candidate(candidates)
        if selected_input is None:
            return

        self.input_epub_var.set(str(selected_input))
        self._on_input_selected()

        projects = [dict(r) for r in self.db.list_projects() if str(r.get("status") or "") != "deleted"]
        matches = match_projects_by_input_and_langs(
            projects,
            input_epub=str(selected_input),
            source_lang=self.source_lang_var.get().strip().lower(),
            target_lang=self.target_lang_var.get().strip().lower(),
        )
        picked_project_id = self._pick_project_match(matches)
        if picked_project_id is not None:
            self.current_project_id = int(picked_project_id)
            self.db.set_setting("active_project_id", self.current_project_id)
        else:
            vals = self._default_project_values(selected_input)
            project_name = self._next_project_name(selected_input.stem)
            try:
                self.current_project_id = int(self.db.create_project(project_name, vals))
                self.db.set_setting("active_project_id", self.current_project_id)
            except Exception as e:
                self._startup_notices.append(f"Easy startup create failed: {e}")
                return

        summary = self.db.get_project_with_stage_summary(int(self.current_project_id))
        if summary is None:
            self._startup_notices.append("Easy startup: fresh run context selected.")
            return
        active_step = str(summary.get("active_step") or "translate").strip().lower() or "translate"
        stage = summary.get(active_step) if isinstance(summary.get(active_step), dict) else {}
        stage_status = str((stage or {}).get("status", "none"))
        stage_done = int((stage or {}).get("done", 0) or 0)
        stage_total = int((stage or {}).get("total", 0) or 0)
        cache_key = "cache_translate_path" if active_step == "translate" else "cache_edit_path"
        cache_path = str(summary.get(cache_key) or "").strip()
        _, ledger = self._ledger_counts_for_scope(int(self.current_project_id), active_step)
        can_resume, reason = resume_eligibility(
            project_status=str(summary.get("status") or "idle"),
            stage_status=stage_status,
            stage_done=stage_done,
            stage_total=stage_total,
            cache_exists=bool(cache_path and Path(cache_path).exists()),
            ledger_counts=ledger,
        )
        if can_resume:
            self._startup_notices.append(f"Easy startup: resumed run context ({active_step}, {reason}).")
        else:
            self._startup_notices.append("Easy startup: fresh run context selected.")

    def _find_translator(self) -> Path:
        candidates = [
            self.workdir / "translation_engine.exe",
            self.workdir / "translation_engine.py",
        ]
        for c in candidates:
            if c.exists():
                return c
        raise SystemExit("Nie znaleziono pliku silnika translacji: translation_engine(.exe/.py).")

    def _translator_cmd_prefix(self) -> List[str]:
        # In packaged mode run bundled translator EXE, in dev mode run Python script.
        if self.translator_path.suffix.lower() == ".exe":
            return [self.translator_path.name]
        py = "python"
        if getattr(sys, "frozen", False):
            py = sys.executable
        return [py, "-u", self.translator_path.name]

    def _find_glossary(self, workdir: Path) -> Optional[Path]:
        for name in ["SLOWNIK.txt", "slownik.txt", "Slownik.txt", "SŁOWNIK.txt", "Słownik.txt", "słownik.txt"]:
            p = workdir / name
            if p.exists():
                return p
        cands = sorted(
            [
                p
                for p in workdir.glob("*.txt")
                if "slownik" in p.name.lower() or "słownik" in p.name.lower()
            ]
        )
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
        self._refresh_prompt_preset_options()
        self._save_project()
        self._refresh_ledger_status()
        self._update_command_preview()

    def _on_provider_change(self) -> None:
        provider = self.provider_var.get()
        if provider == "ollama":
            self.ollama_host_entry.configure(state="normal")
            self.google_key_entry.configure(state="disabled")
        else:
            self.ollama_host_entry.configure(state="disabled")
            self.google_key_entry.configure(state="normal")
        self._refresh_prompt_preset_options()
        self._update_command_preview()

    def _load_prompt_presets_catalog(self) -> None:
        try:
            _ = save_default_prompt_presets(PROMPT_PRESETS_FILE)
        except Exception:
            pass
        self.prompt_presets = load_prompt_presets(PROMPT_PRESETS_FILE)

    def _refresh_prompt_preset_options(self) -> None:
        if not hasattr(self, "prompt_preset_combo"):
            return
        provider = self.provider_var.get().strip().lower() or "any"
        mode = self.mode_var.get().strip().lower() or "translate"
        available = filter_prompt_presets(self.prompt_presets, provider=provider, mode=mode)
        labels = [str(x.get("label") or x.get("id") or "") for x in available]
        self.prompt_preset_by_label = {}
        for item in available:
            label = str(item.get("label") or item.get("id") or "").strip()
            if label and label not in self.prompt_preset_by_label:
                self.prompt_preset_by_label[label] = item
        self.prompt_preset_combo["values"] = labels
        current = self.prompt_preset_var.get().strip()
        if current not in self.prompt_preset_by_label:
            self.prompt_preset_var.set(labels[0] if labels else "")
        self._on_prompt_preset_selected()

    def _on_prompt_preset_selected(self) -> None:
        label = self.prompt_preset_var.get().strip()
        preset = self.prompt_preset_by_label.get(label)
        if not preset:
            self.prompt_preset_desc_var.set(self.tr("status.prompt_preset.none", "Prompt preset: custom/manual"))
            return
        desc = str(preset.get("description") or "").strip()
        provider = str(preset.get("provider") or "any").strip().lower()
        mode = str(preset.get("mode") or "any").strip().lower()
        suffix = f"[provider={provider}, mode={mode}]"
        self.prompt_preset_desc_var.set(f"{desc} {suffix}".strip())

    def _reload_prompt_presets(self) -> None:
        self._load_prompt_presets_catalog()
        self._refresh_prompt_preset_options()
        self._set_status(self.tr("status.prompt_presets.reloaded", "Prompt presets reloaded"), "ready")

    def _resolve_prompt_preset_target_path(self, mode: str) -> Path:
        raw = self.prompt_var.get().strip()
        allowed_names = {
            "prompt.txt",
            "prompt_redakcja.txt",
            "prompt_translate_preset.txt",
            "prompt_edit_preset.txt",
        }
        if raw:
            current = Path(raw)
            if current.name.lower() in allowed_names:
                return current
        filename = "prompt_translate_preset.txt" if mode == "translate" else "prompt_edit_preset.txt"
        return self.workdir / filename

    def _apply_selected_prompt_preset(self) -> None:
        label = self.prompt_preset_var.get().strip()
        preset = self.prompt_preset_by_label.get(label)
        if not preset:
            self._msg_info(self.tr("info.prompt_preset.none", "No prompt preset selected for current provider/mode."))
            return
        mode = self.mode_var.get().strip().lower() or "translate"
        target_path = self._resolve_prompt_preset_target_path(mode)
        text = str(preset.get("prompt") or "").strip()
        if not text:
            self._msg_error(self.tr("err.prompt_preset.empty", "Selected prompt preset is empty."))
            return
        try:
            target_path.parent.mkdir(parents=True, exist_ok=True)
            target_path.write_text(text + "\n", encoding="utf-8")
        except Exception as e:
            self._msg_error(f"{self.tr('err.prompt_preset.write', 'Failed to write prompt preset file:')}\n{e}")
            return
        self.prompt_var.set(str(target_path))
        self._on_prompt_changed()
        self._save_project()
        self._set_status(
            self.tr("status.prompt_preset.applied", "Prompt preset applied: {name}", name=label),
            "ready",
        )

    def _suggest_output_and_cache(self) -> None:
        in_path = self.input_epub_var.get().strip()
        if not in_path:
            return
        p = Path(in_path)
        if not p.exists():
            return

        mode = (self.mode_var.get() or "translate").strip().lower() or "translate"
        tgt = (self.target_lang_var.get() or "pl").strip().lower()
        suggested = suggest_paths_for_step(p, target_lang=tgt, step=mode)
        self.output_epub_var.set(str(suggested.output_epub))
        self.cache_var.set(str(suggested.cache_path))
        if suggested.conflict_resolved:
            self._set_inline_notice(
                f"Easy startup: output already existed, using {suggested.output_epub.name}.",
                level="warn",
                timeout_ms=9000,
            )
        step = self.mode_var.get().strip() or "translate"
        self._save_step_values(step)

    def _health_state_badge(self, state: str) -> str:
        s = str(state or "").strip().lower()
        if s == "ok":
            return "OK"
        if s == "skip":
            return "SKIP"
        return "FAIL"

    def _health_check_providers(self) -> None:
        self.model_status.configure(text="Sprawdzam provider health (async I/O)...")
        self.health_trend_var.set(self.tr("status.health_trend.pending", "Health trend: odswiezanie..."))
        ollama_host = self.ollama_host_var.get().strip() or OLLAMA_HOST_DEFAULT
        google_key = self._google_api_key()

        def worker() -> None:
            try:
                timeout_s = max(6, min(30, int(float(self.timeout_var.get().strip() or "20"))))
            except Exception:
                timeout_s = 20
            try:
                status_map = gather_provider_health(
                    ollama_host=ollama_host,
                    google_api_key=google_key,
                    timeout_s=timeout_s,
                    include_ollama=True,
                    include_google=True,
                )
            except Exception as e:
                err = str(e)
                self.root.after(0, lambda msg=err: self.model_status.configure(text=f"Health check fail: {msg}"))
                return

            lines: List[str] = []
            details: List[str] = []
            payload_rows: List[Dict[str, Any]] = []
            for key in ("ollama", "google"):
                st = status_map.get(key)
                if st is None:
                    continue
                badge = self._health_state_badge(getattr(st, "state", "fail"))
                latency = int(getattr(st, "latency_ms", 0) or 0)
                model_count = int(getattr(st, "model_count", 0) or 0)
                lines.append(f"{key.upper()}={badge} {latency}ms m={model_count}")
                detail = str(getattr(st, "detail", "") or "").strip()
                if detail and badge != "OK":
                    details.append(f"{key}: {detail}")
                payload_rows.append(
                    {
                        "provider": str(getattr(st, "provider", key) or key).strip().lower(),
                        "state": str(getattr(st, "state", "fail") or "fail").strip().lower(),
                        "latency_ms": latency,
                        "model_count": model_count,
                        "detail": detail,
                    }
                )
            summary = " | ".join(lines) if lines else "Brak danych health check."
            trend_lines: List[str] = []
            alerts: List[str] = []
            if payload_rows:
                health_db: Optional[ProjectDB] = None
                try:
                    health_db = ProjectDB(SQLITE_FILE)
                    health_db.record_provider_health_checks(payload_rows)
                    for row in payload_rows:
                        provider_key = str(row.get("provider", "")).strip().lower()
                        if not provider_key:
                            continue
                        snap = health_db.provider_health_summary(provider_key, window=20)
                        total = int(snap.get("total", 0) or 0)
                        fail_streak = int(snap.get("failure_streak", 0) or 0)
                        avg_latency = int(snap.get("avg_latency_ms", 0) or 0)
                        latest = str(snap.get("latest_state", "n/a") or "n/a").upper()
                        trend_lines.append(f"{provider_key.upper()}: latest={latest} streak={fail_streak} avg={avg_latency}ms n={total}")
                        if fail_streak >= 3:
                            alerts.append(f"{provider_key.upper()} failure streak={fail_streak} (window=20)")
                except Exception as e:
                    details.append(f"health telemetry persist failed: {e}")
                finally:
                    if health_db is not None:
                        try:
                            health_db.close()
                        except Exception:
                            pass
            trend_summary = " | ".join(trend_lines) if trend_lines else self.tr("status.health_trend.none", "Health trend: brak danych")

            def apply_summary() -> None:
                self.model_status.configure(text=summary)
                self.health_trend_var.set(trend_summary)
                self.log_queue.put(f"[HEALTH] {summary}\n")
                if trend_lines:
                    self.log_queue.put(f"[HEALTH] trend: {trend_summary}\n")
                for item in details:
                    self.log_queue.put(f"[HEALTH] {item}\n")
                if alerts:
                    for item in alerts:
                        self.log_queue.put(f"[HEALTH][ALERT] {item}\n")
                    self._set_inline_notice(
                        "Health alert: wykryto serie nieudanych probe providera.",
                        level="warn",
                        timeout_ms=9000,
                    )

            self.root.after(0, apply_summary)

        threading.Thread(target=worker, daemon=True).start()

    def _refresh_models(self) -> None:
        self.model_status.configure(text="Pobieram listĂ„â„˘ modeli...")
        provider = self.provider_var.get().strip()
        ollama_host = self.ollama_host_var.get().strip() or OLLAMA_HOST_DEFAULT
        google_key = self._google_api_key() if provider == "google" else ""

        def worker() -> None:
            try:
                if provider == "ollama":
                    models = list_ollama_models(ollama_host)
                else:
                    if not google_key:
                        raise ValueError(f"Podaj Google API key lub ustaw zmiennĂ„â€¦ Äąâ€şrodowiskowĂ„â€¦ {GOOGLE_API_KEY_ENV}.")
                    models = list_google_models(google_key)

                if not models:
                    raise ValueError("Brak modeli do wyboru.")

                self.root.after(0, lambda: self._set_models(models))
            except Exception as e:
                err_text = str(e)
                self.root.after(0, lambda msg=err_text: self.model_status.configure(text=f"BÄąâ€šĂ„â€¦d: {msg}"))

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
        self.model_status.configure(text=f"ZaÄąâ€šadowano {len(models)} modeli")
        self._update_command_preview()

    def _google_api_key(self) -> str:
        ui = self.google_api_key_var.get().strip()
        if ui:
            return ui
        kr = load_google_api_key_from_keyring()
        if kr:
            return kr
        return os.environ.get(GOOGLE_API_KEY_ENV, "").strip()

    def _current_series_context(self) -> Tuple[Optional[str], Optional[str]]:
        series_id = self._selected_series_id()
        if series_id is None and self.current_project_id is not None:
            row = self.db.get_project(self.current_project_id)
            if row is not None and row["series_id"] is not None:
                series_id = int(row["series_id"])
        if series_id is None:
            return None, None
        series_row = self.db.get_series(series_id)
        if series_row is None:
            return None, None
        return str(series_row["slug"] or ""), str(series_row["name"] or "")

    def _current_series_id(self) -> Optional[int]:
        series_id = self._selected_series_id()
        if series_id is not None:
            return series_id
        if self.current_project_id is None:
            return None
        row = self.db.get_project(self.current_project_id)
        if row is None or row["series_id"] is None:
            return None
        return int(row["series_id"])

    def _effective_prompt_for_run(self) -> str:
        base_prompt_raw = self.prompt_var.get().strip()
        if not base_prompt_raw:
            return base_prompt_raw
        base_prompt = Path(base_prompt_raw)
        if not base_prompt.exists():
            return base_prompt_raw

        series_slug, series_name = self._current_series_context()
        if not series_slug:
            return base_prompt_raw
        step = (self.mode_var.get().strip().lower() or "translate")
        self.series_store.ensure_series_db(series_slug, display_name=series_name or "")
        out_path = SERIES_DATA_DIR / series_slug / "generated" / f"prompt_{step}_project_{self.current_project_id or 0}.txt"
        try:
            out = self.series_store.build_augmented_prompt(
                series_slug,
                base_prompt_path=base_prompt,
                output_path=out_path,
                run_step=step,
            )
            return str(out)
        except Exception:
            return base_prompt_raw

    def _effective_glossary_for_run(self) -> str:
        project_glossary_raw = self.glossary_var.get().strip()
        project_glossary = Path(project_glossary_raw) if project_glossary_raw else None
        series_slug, series_name = self._current_series_context()
        if not series_slug:
            return project_glossary_raw
        self.series_store.ensure_series_db(series_slug, display_name=series_name or "")
        out_path = self.series_store.build_merged_glossary(
            series_slug,
            project_glossary=project_glossary if project_glossary and project_glossary.exists() else None,
            output_path=SERIES_DATA_DIR / series_slug / "generated" / f"merged_glossary_project_{self.current_project_id or 0}.txt",
        )
        return str(out_path)

    def _sync_series_terms_after_run(self, runner_db: ProjectDB, project_id: int) -> None:
        project = runner_db.get_project(project_id)
        if project is None:
            return
        raw_series_id = project["series_id"]
        if raw_series_id is None:
            return
        series_row = runner_db.get_series(int(raw_series_id))
        if series_row is None:
            return
        series_slug = str(series_row["slug"] or "").strip()
        series_name = str(series_row["name"] or "").strip()
        if not series_slug:
            return
        self.series_store.ensure_series_db(series_slug, display_name=series_name)
        tm_rows = [dict(r) for r in runner_db.list_tm_segments(project_id=project_id, limit=2500)]
        added = self.series_store.learn_terms_from_tm(series_slug, tm_rows, project_id=project_id, max_rows=2500)
        if added > 0:
            self.log_queue.put(f"[SERIES] Dodano {added} proponowanych terminow do serii '{series_name}'.\n")

    def _runtime_options(self) -> CoreRunOptions:
        effective_prompt = self._effective_prompt_for_run()
        effective_glossary = self._effective_glossary_for_run() if bool(self.use_glossary_var.get()) else self.glossary_var.get().strip()
        return CoreRunOptions(
            provider=self.provider_var.get().strip(),
            input_epub=self.input_epub_var.get().strip(),
            output_epub=self.output_epub_var.get().strip(),
            prompt=effective_prompt,
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
            glossary=effective_glossary,
            use_glossary=bool(self.use_glossary_var.get()),
            tm_db=str(SQLITE_FILE),
            tm_project_id=self.current_project_id,
            run_step=(self.mode_var.get().strip().lower() or "translate"),
            context_window=self.context_window_var.get().strip(),
            context_neighbor_max_chars=self.context_neighbor_max_chars_var.get().strip(),
            context_segment_max_chars=self.context_segment_max_chars_var.get().strip(),
            io_concurrency=self.io_concurrency_var.get().strip(),
            language_guard_config=self.language_guard_config_var.get().strip(),
        )
    
    def _build_command(self) -> List[str]:
        opts = self._runtime_options()
        return core_build_run_command(self._translator_cmd_prefix(), opts, tm_fuzzy_threshold="0.92")

    def _build_validation_command(self, epub_path: str) -> List[str]:
        return core_build_validation_command(self._translator_cmd_prefix(), epub_path, self.tags_var.get().strip())

    def _run_epubcheck_gate(self, epub_path: Path) -> Tuple[bool, str]:
        target = Path(epub_path)
        if not target.exists():
            return False, f"[EPUBCHECK-GATE] FAIL: output EPUB missing: {target}"
        try:
            proc = subprocess.run(
                ["epubcheck", str(target)],
                capture_output=True,
                text=True,
                encoding="utf-8",
                errors="replace",
                timeout=EPUBCHECK_TIMEOUT_S,
            )
        except subprocess.TimeoutExpired:
            return False, f"[EPUBCHECK-GATE] FAIL: epubcheck timed out after {EPUBCHECK_TIMEOUT_S}s"
        except Exception as e:
            return False, f"[EPUBCHECK-GATE] FAIL: epubcheck unavailable: {e}"

        raw = ((proc.stdout or "") + "\n" + (proc.stderr or "")).strip()
        sev = parse_epubcheck_findings(raw)
        fatal_or_error = int(sev.get("fatal", 0) or 0) + int(sev.get("error", 0) or 0)
        if proc.returncode == 0 and fatal_or_error == 0:
            return True, f"[EPUBCHECK-GATE] PASS (warning={int(sev.get('warning', 0) or 0)})"
        tail = "\n".join(raw.splitlines()[-40:]).strip()
        msg = (
            f"[EPUBCHECK-GATE] FAIL: exit={proc.returncode} "
            f"fatal={int(sev.get('fatal', 0) or 0)} "
            f"error={int(sev.get('error', 0) or 0)} "
            f"warning={int(sev.get('warning', 0) or 0)}"
        )
        if tail:
            msg += "\n" + tail
        return False, msg

    def _validate(self) -> Optional[str]:
        required = [
            ("WejÄąâ€şciowy EPUB", self.input_epub_var.get().strip()),
            ("WyjÄąâ€şciowy EPUB", self.output_epub_var.get().strip()),
            ("Prompt", self.prompt_var.get().strip()),
            ("Model", self.model_var.get().strip()),
        ]
        for label, val in required:
            if not val:
                return f"Brak pola: {label}"

        in_file = Path(self.input_epub_var.get().strip())
        if not in_file.exists():
            return f"Nie istnieje plik wejÄąâ€şciowy: {in_file}"

        prompt_file = Path(self.prompt_var.get().strip())
        if not prompt_file.exists():
            return f"Nie istnieje plik prompt: {prompt_file}"

        if self.provider_var.get() == "google" and not self._google_api_key():
            return f"Dla Google podaj API key albo ustaw zmiennĂ„â€¦ Äąâ€şrodowiskowĂ„â€¦ {GOOGLE_API_KEY_ENV}."

        if (self.source_lang_var.get().strip().lower() or "") not in SUPPORTED_TEXT_LANGS:
            return "NieprawidÄąâ€šowy jĂ„â„˘zyk ÄąĹźrÄ‚Ĺ‚dÄąâ€šowy."
        if (self.target_lang_var.get().strip().lower() or "") not in SUPPORTED_TEXT_LANGS:
            return "NieprawidÄąâ€šowy jĂ„â„˘zyk docelowy."

        for num_label, v in [
            ("batch-max-segs", self.batch_max_segs_var.get().strip()),
            ("batch-max-chars", self.batch_max_chars_var.get().strip()),
            ("timeout", self.timeout_var.get().strip()),
            ("attempts", self.attempts_var.get().strip()),
            ("checkpoint", self.checkpoint_var.get().strip()),
            ("io-concurrency", self.io_concurrency_var.get().strip()),
            ("context-window", self.context_window_var.get().strip()),
            ("context-neighbor-max-chars", self.context_neighbor_max_chars_var.get().strip()),
            ("context-segment-max-chars", self.context_segment_max_chars_var.get().strip()),
        ]:
            try:
                int(v)
            except Exception:
                return f"Pole {num_label} musi byĂ„â€ˇ liczbĂ„â€¦ caÄąâ€škowitĂ„â€¦."

        for num_label, v in [
            ("sleep", self.sleep_var.get().strip()),
            ("temperature", self.temperature_var.get().strip()),
        ]:
            try:
                float(v.replace(",", "."))
            except Exception:
                return f"Pole {num_label} musi byĂ„â€ˇ liczbĂ„â€¦."

        runtime_err = core_validate_run_options(
            self._runtime_options(),
            google_api_key=self._google_api_key(),
            supported_text_langs=set(SUPPORTED_TEXT_LANGS.keys()),
        )
        if runtime_err:
            return f"Runtime contract: {runtime_err}"

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
        if "[RETRY]" in s and "state=waiting_retry" in s:
            self.phase_var.set(self.tr("status.phase.retry_wait", "Phase: working, waiting for provider window"))
            self._set_status(self.tr("status.translation.running", "Translation in progress..."), "running")
            self._update_live_run_metrics()
            return
        if "[RETRY]" in s and "state=recovered" in s:
            self.phase_var.set(self.tr("status.phase.retry_recovered", "Phase: provider recovered"))
            self._set_status(self.tr("status.translation.running", "Translation in progress..."), "running")
            self._update_live_run_metrics()
            return

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

    def _ledger_counts_for_scope(self, project_id: Optional[int], step: str) -> Tuple[bool, Dict[str, int]]:
        counts = {"PENDING": 0, "PROCESSING": 0, "COMPLETED": 0, "ERROR": 0}
        if project_id is None:
            return True, counts
        con = sqlite3.connect(str(SQLITE_FILE), timeout=1.0)
        con.row_factory = sqlite3.Row
        try:
            exists = con.execute(
                "SELECT 1 FROM sqlite_master WHERE type = 'table' AND name = 'segment_ledger'"
            ).fetchone() is not None
            if not exists:
                return False, counts
            rows = con.execute(
                """
                SELECT status, COUNT(*) c
                FROM segment_ledger
                WHERE project_id = ? AND run_step = ?
                GROUP BY status
                """,
                (int(project_id), str(step or "translate")),
            ).fetchall()
            for row in rows:
                st = str(row["status"] or "").strip().upper()
                if st in counts:
                    counts[st] = int(row["c"] or 0)
            return True, counts
        finally:
            con.close()

    def _draw_ledger_bar(self) -> None:
        if not hasattr(self, "ledger_canvas"):
            return
        canvas = self.ledger_canvas
        width = max(1, int(canvas.winfo_width() or 1))
        height = max(1, int(canvas.winfo_height() or int(canvas.cget("height") or 10)))
        canvas.delete("all")
        total = max(0, sum(int(v or 0) for v in self._ledger_counts.values()))
        colors = {
            "COMPLETED": "#16a34a",
            "PROCESSING": "#f59e0b",
            "ERROR": "#dc2626",
            "PENDING": "#94a3b8",
        }
        if total <= 0:
            canvas.create_rectangle(0, 0, width, height, fill="#cbd5e1", outline="")
            canvas.create_rectangle(0, 0, width - 1, height - 1, outline="#64748b")
            return
        order = ["COMPLETED", "PROCESSING", "ERROR", "PENDING"]
        x = 0.0
        for idx, status in enumerate(order):
            value = max(0, int(self._ledger_counts.get(status, 0)))
            if value <= 0:
                continue
            if idx == len(order) - 1:
                x2 = float(width)
            else:
                x2 = min(float(width), x + (float(width) * float(value) / float(total)))
            if x2 > x:
                canvas.create_rectangle(int(x), 0, int(round(x2)), height, fill=colors[status], outline="")
            x = x2
        canvas.create_rectangle(0, 0, width - 1, height - 1, outline="#64748b")

    def _refresh_ledger_status(self) -> None:
        step = self.mode_var.get().strip().lower() or "translate"
        project_id = self.current_project_id
        try:
            available, counts = self._ledger_counts_for_scope(project_id, step)
        except Exception:
            available, counts = True, {"PENDING": 0, "PROCESSING": 0, "COMPLETED": 0, "ERROR": 0}
        self._ledger_counts = counts
        total = sum(counts.values())
        if project_id is None:
            self.ledger_status_var.set(self.tr("status.ledger.no_project", "Ledger: select project"))
            self._ledger_alert_key = None
        elif not available:
            self.ledger_status_var.set(self.tr("status.ledger.unavailable", "Ledger: unavailable (run translation once)"))
            self._ledger_alert_key = None
        elif total <= 0:
            self.ledger_status_var.set(self.tr("status.ledger.empty", "Ledger: no segments yet"))
            self._ledger_alert_key = None
        else:
            err_count = int(counts["ERROR"] or 0)
            alert_suffix = ""
            if err_count > LEDGER_ERROR_ALERT_THRESHOLD:
                alert_suffix = f" | ALERT: error>{LEDGER_ERROR_ALERT_THRESHOLD}"
                alert_key = (int(project_id), str(step), err_count)
                if self._ledger_alert_key != alert_key:
                    self._ledger_alert_key = alert_key
                    self._set_inline_notice(
                        f"Ledger alert: errors={err_count} (threshold>{LEDGER_ERROR_ALERT_THRESHOLD}).",
                        level="warn",
                        timeout_ms=9000,
                    )
            else:
                self._ledger_alert_key = None
            self.ledger_status_var.set(
                self.tr(
                    "status.ledger.summary",
                    "Ledger: done={done} processing={processing} error={error} pending={pending} total={total}",
                    done=counts["COMPLETED"],
                    processing=counts["PROCESSING"],
                    error=counts["ERROR"],
                    pending=counts["PENDING"],
                    total=total,
                )
                + alert_suffix
            )
        self._draw_ledger_bar()

    def _tick_activity(self) -> None:
        if self.proc is None:
            return
        now = time.time()
        if self.last_log_at is not None:
            quiet_for = int(now - self.last_log_at)
            if quiet_for >= 5:
                self.phase_var.set(self.tr("status.phase.waiting_response", "Phase: waiting for response ({sec}s without log)", sec=quiet_for))
        self._refresh_ledger_status()
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
        self._refresh_ledger_status()
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
                env = {
                    **os.environ,
                    "PYTHONUNBUFFERED": "1",
                    "PYTHONIOENCODING": "utf-8",
                    "PYTHONUTF8": "1",
                }
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
                if code == 0 and bool(self.hard_gate_epubcheck_var.get()):
                    self.log_queue.put("[EPUBCHECK-GATE] Running epubcheck...\n")
                    gate_ok, gate_msg = self._run_epubcheck_gate(Path(self.output_epub_var.get().strip()))
                    self.log_queue.put(gate_msg + "\n")
                    if not gate_ok:
                        self.log_queue.put("\n=== EPUBCHECK GATE BLOCKED ===\n")
                        code = 86
                if code == 0 and self.current_project_id is not None and runner_db is not None:
                    qa_sev_ok, qa_sev_msg = runner_db.qa_severity_gate_status(
                        self.current_project_id,
                        run_step,
                        severities=("fatal", "error"),
                    )
                    self.log_queue.put(f"[QA-SEVERITY-GATE] {qa_sev_msg}\n")
                    if not qa_sev_ok:
                        self.log_queue.put("\n=== QA SEVERITY GATE BLOCKED ===\n")
                        code = 87
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
                    if runner_db and self.current_project_id is not None and run_step in {"translate", "edit"}:
                        try:
                            self._sync_series_terms_after_run(runner_db, self.current_project_id)
                        except Exception as e:
                            self.log_queue.put(f"[SERIES] PominiÄ™to sync sĹ‚ownika serii: {e}\n")
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
                self.root.after(0, self._refresh_ledger_status)
                self.root.after(0, lambda: self.start_btn.configure(state="normal"))
                self.root.after(0, lambda: self.validate_btn.configure(state="normal"))
                self.root.after(0, lambda: self.stop_btn.configure(state="disabled"))
                if self.run_all_active:
                    self.root.after(200, self._continue_run_all)
                elif self.series_batch_context is not None and bool(self.series_batch_context.get("stopped")):
                    self.root.after(200, lambda: self._finalize_series_batch("stopped"))

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
        self._refresh_ledger_status()
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
                    env={
                        **os.environ,
                        "PYTHONUNBUFFERED": "1",
                        "PYTHONIOENCODING": "utf-8",
                        "PYTHONUTF8": "1",
                    },
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
                self.root.after(0, self._refresh_ledger_status)
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
            "prompt_preset": self.prompt_preset_var.get(),
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
            "hard_gate_epubcheck": self.hard_gate_epubcheck_var.get(),
            "checkpoint": self.checkpoint_var.get(),
            "io_concurrency": self.io_concurrency_var.get(),
            "context_window": self.context_window_var.get(),
            "context_neighbor_max_chars": self.context_neighbor_max_chars_var.get(),
            "context_segment_max_chars": self.context_segment_max_chars_var.get(),
            "language_guard_config": self.language_guard_config_var.get(),
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
        self.prompt_preset_var.set(str(data.get("prompt_preset", self.prompt_preset_var.get() or "")))
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
        self.hard_gate_epubcheck_var.set(bool(data.get("hard_gate_epubcheck", self.hard_gate_epubcheck_var.get())))
        self.checkpoint_var.set(data.get("checkpoint", self.checkpoint_var.get()))
        self.io_concurrency_var.set(str(data.get("io_concurrency", self.io_concurrency_var.get() or "1")))
        self.context_window_var.set(str(data.get("context_window", self.context_window_var.get() or "0")))
        self.context_neighbor_max_chars_var.set(
            str(data.get("context_neighbor_max_chars", self.context_neighbor_max_chars_var.get() or "180"))
        )
        self.context_segment_max_chars_var.set(
            str(data.get("context_segment_max_chars", self.context_segment_max_chars_var.get() or "1200"))
        )
        self.language_guard_config_var.set(str(data.get("language_guard_config", self.language_guard_config_var.get() or "")))
        self.tooltip_mode_var.set(str(data.get("tooltip_mode", self.tooltip_mode_var.get() or "hybrid")))
        self.source_lang_var.set(str(data.get("source_lang", self.source_lang_var.get() or "en")))
        self.target_lang_var.set(str(data.get("target_lang", self.target_lang_var.get() or "pl")))
        self.ui_language_var.set(str(data.get("ui_language", self.ui_language_var.get() or self.i18n.lang)))
        self._on_tooltip_mode_change()
        if self.ui_language_var.get().strip().lower() != self.i18n.lang:
            self._on_ui_language_change()
        self._on_provider_change()
        self._refresh_prompt_preset_options()
        self._refresh_ledger_status()
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
                self._msg_error(f"Nie udaÄąâ€šo siĂ„â„˘ zapisaĂ„â€ˇ ustawieÄąâ€ž:\n{e}")

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
                self._msg_error(f"Nie udaÄąâ€šo siĂ„â„˘ wczytaĂ„â€ˇ ustawieÄąâ€ž:\n{e}")

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
    try:
        TranslatorGUI(root)
    except Exception as e:
        try:
            messagebox.showerror(
                "Migration Error",
                "Nie udalo sie uruchomic aplikacji po aktualizacji.\n\n"
                f"Szczegoly:\n{e}\n\n"
                "Sprawdz folder backupow migracji i sproboj ponownie.",
            )
        finally:
            root.destroy()
        return 2
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
        self.active_segment_idx: Optional[int] = None
        self.active_token_map: Dict[str, str] = {}
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
        self.editor.tag_configure("InlineToken", background="#f1e5c5", foreground="#5e3f00")
        self.editor.bind("<KeyPress>", self._on_editor_keypress, add="+")
        self.editor.bind("<<Paste>>", self._on_editor_paste, add="+")
        right.rowconfigure(2, weight=2)

        btn = ttk.Frame(right)
        btn.grid(row=3, column=0, sticky="ew", pady=(8, 0))
        ttk.Button(btn, text=self.gui.tr("editor.save_segment", "Save segment"), command=self._save_segment).pack(side="left")
        ttk.Button(btn, text=self.gui.tr("editor.save_epub", "Save EPUB"), command=self._save_epub).pack(side="left", padx=(8, 0))
        self._install_tooltips()

    def _msg_info(self, message: str, title: Optional[str] = None) -> None:
        self.gui._msg_info(message, title=title)

    def _msg_error(self, message: str, title: Optional[str] = None) -> None:
        self.gui._msg_error(message, title=title)

    def _install_tooltips(self) -> None:
        text_tip = {
            self.gui.tr("editor.chapters", "Chapters:"): self.gui.tr("tip.editor.chapters", "List of chapter files in EPUB. Selection loads chapter segments."),
            self.gui.tr("editor.segments", "Segments:"): self.gui.tr("tip.editor.segments", "List of text segments in selected chapter."),
            self.gui.tr("editor.save_segment", "Save segment"): self.gui.tr("tip.editor.save_segment", "Saves changes only in current selected segment (in memory)."),
            self.gui.tr("editor.save_epub", "Save EPUB"): self.gui.tr("tip.editor.save_epub", "Saves chapter changes to EPUB and creates backup."),
        }
        object_tip = {
            id(self.chapter_box): "WybÄ‚Ĺ‚r rozdziaÄąâ€šu do edycji.",
            id(self.segment_box): "WybÄ‚Ĺ‚r segmentu do podglĂ„â€¦du/edycji.",
            id(self.editor): "Edytor treÄąâ€şci segmentu. To pole modyfikuje docelowy tekst.",
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
                return "Pole wejÄąâ€şciowe w edytorze."
            return None

        self._tooltips = install_tooltips(self.win, resolver)

    def _tokenize_inline_segment(self, el: etree._Element) -> Tuple[str, Dict[str, str]]:
        return tokenize_inline_markup(el)

    def _render_editor_text(self, text: str) -> None:
        self.editor.delete("1.0", "end")
        self.editor.mark_set("insert", "1.0")
        cursor = 0
        for m in INLINE_TOKEN_RE.finditer(text):
            if m.start() > cursor:
                self.editor.insert("insert", text[cursor:m.start()])
            token = m.group(0)
            start = self.editor.index("insert")
            self.editor.insert("insert", token)
            end = self.editor.index("insert")
            self.editor.tag_add("InlineToken", start, end)
            cursor = m.end()
        if cursor < len(text):
            self.editor.insert("insert", text[cursor:])
        self.editor.mark_set("insert", "1.0")

    def _selection_overlaps_token(self) -> bool:
        try:
            sel_start = self.editor.index("sel.first")
            sel_end = self.editor.index("sel.last")
        except tk.TclError:
            return False
        ranges = self.editor.tag_ranges("InlineToken")
        for i in range(0, len(ranges), 2):
            r_start = str(ranges[i])
            r_end = str(ranges[i + 1])
            if self.editor.compare(sel_start, "<", r_end) and self.editor.compare(sel_end, ">", r_start):
                return True
        return False

    def _cursor_touches_token(self, *, backspace: bool = False) -> bool:
        idx = "insert-1c" if backspace else "insert"
        try:
            return "InlineToken" in self.editor.tag_names(idx)
        except tk.TclError:
            return False

    def _on_editor_keypress(self, event: tk.Event[Any]) -> Optional[str]:
        keysym = str(getattr(event, "keysym", "") or "")
        char = str(getattr(event, "char", "") or "")
        state = int(getattr(event, "state", 0) or 0)
        ctrl = bool(state & 0x4)

        if keysym in {"Left", "Right", "Up", "Down", "Home", "End", "Prior", "Next", "Tab"}:
            return None
        if ctrl and keysym.lower() in {"a", "c", "z", "y"}:
            return None
        if self._selection_overlaps_token():
            self.win.bell()
            return "break"
        if keysym == "BackSpace" and self._cursor_touches_token(backspace=True):
            self.win.bell()
            return "break"
        if keysym == "Delete" and self._cursor_touches_token(backspace=False):
            self.win.bell()
            return "break"
        if char and self._cursor_touches_token(backspace=False):
            self.win.bell()
            return "break"
        return None

    def _on_editor_paste(self, _event: tk.Event[Any]) -> Optional[str]:
        if self._selection_overlaps_token() or self._cursor_touches_token(backspace=False):
            self.win.bell()
            return "break"
        return None

    def _assert_tokens_intact(self, text: str, token_map: Dict[str, str]) -> Tuple[bool, str]:
        _ = text
        expected = list(token_map.keys())
        ranges = self.editor.tag_ranges("InlineToken")
        found: List[str] = []
        for i in range(0, len(ranges), 2):
            start = str(ranges[i])
            end = str(ranges[i + 1])
            found.append(self.editor.get(start, end))
        if found == expected:
            return True, ""
        return False, self.gui.tr(
            "err.editor_inline_tokens_modified",
            "Inline tags were modified. Keep token markers unchanged (e.g. [[TAG001]]).",
        )

    def _apply_tokenized_segment_text(self, el: etree._Element, text: str, token_map: Dict[str, str]) -> None:
        apply_tokenized_inline_markup(el, text, token_map)

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
        self.active_segment_idx = None
        self.active_token_map = {}
        self.segment_box.delete(0, "end")
        for i, el in enumerate(segments):
            txt = etree.tostring(el, encoding="unicode", method="text").strip().replace("\n", " ")
            if len(txt) > 90:
                txt = txt[:90] + "..."
            self.segment_box.insert("end", f"{i:04d}: <{etree.QName(el).localname}> {txt}")
        self.editor.delete("1.0", "end")

    def _on_segment_selected(self) -> None:
        sel = self.segment_box.curselection()
        if not sel:
            return
        idx = int(sel[0])
        if idx < 0 or idx >= len(self.current_segments):
            return
        el = self.current_segments[idx]
        text, token_map = self._tokenize_inline_segment(el)
        self.active_segment_idx = idx
        self.active_token_map = token_map
        self._render_editor_text(text)

    def _save_segment(self) -> None:
        sel = self.segment_box.curselection()
        if not sel:
            return
        idx = int(sel[0])
        if idx < 0 or idx >= len(self.current_segments):
            return
        new_text = self.editor.get("1.0", "end-1c")
        el = self.current_segments[idx]
        token_map: Dict[str, str] = self.active_token_map if self.active_segment_idx == idx else {}
        if token_map:
            ok, msg = self._assert_tokens_intact(new_text, token_map)
            if not ok:
                self._msg_error(msg)
                return
            try:
                self._apply_tokenized_segment_text(el, new_text, token_map)
            except Exception as e:
                self._msg_error(f"{self.gui.tr('err.editor_save_segment', 'Failed to save segment:')}\n{e}")
                return
        else:
            set_text_preserving_inline(el, new_text)
        preview = etree.tostring(el, encoding="unicode", method="text").strip().replace("\n", " ")
        if len(preview) > 90:
            preview = preview[:90] + "..."
        self.segment_box.delete(idx)
        self.segment_box.insert(idx, f"{idx:04d}: <{etree.QName(el).localname}> {preview}")
        self.segment_box.selection_clear(0, "end")
        self.segment_box.selection_set(idx)
        self._on_segment_selected()

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
