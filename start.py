#!/usr/bin/env python3
# -*- coding: utf-8 -*-

from __future__ import annotations

import json
import os
import platform
import queue
import re
import subprocess
import threading
from pathlib import Path
from typing import List, Optional

import requests
import tkinter as tk
from tkinter import filedialog, messagebox, ttk
from tkinter.scrolledtext import ScrolledText

APP_TITLE = "EPUB Translator Studio"
SETTINGS_FILE = Path(__file__).resolve().with_name(".gui_settings.json")
OLLAMA_HOST_DEFAULT = os.environ.get("OLLAMA_HOST", "http://127.0.0.1:11434")
GLOBAL_PROGRESS_RE = re.compile(r"GLOBAL\s+(\d+)\s*/\s*(\d+)\s*\(([^)]*)\)\s*\|\s*(.*)")


def list_ollama_models(host: str, timeout_s: int = 20) -> List[str]:
    url = host.rstrip("/") + "/api/tags"
    r = requests.get(url, timeout=timeout_s)
    r.raise_for_status()
    data = r.json()
    out: List[str] = []
    for m in data.get("models", []) or []:
        name = m.get("name")
        if isinstance(name, str) and name.strip():
            out.append(name.strip())
    return sorted(set(out))


def list_google_models(api_key: str, timeout_s: int = 20) -> List[str]:
    url = "https://generativelanguage.googleapis.com/v1beta/models"
    headers = {"x-goog-api-key": api_key.strip()}
    r = requests.get(url, headers=headers, timeout=timeout_s)
    r.raise_for_status()
    data = r.json()

    out: List[str] = []
    for m in data.get("models", []) or []:
        name = m.get("name")
        if not isinstance(name, str) or not name.strip():
            continue
        methods = m.get("supportedGenerationMethods") or []
        ok = isinstance(methods, list) and any(str(x).lower() == "generatecontent" for x in methods)
        if ok:
            out.append(name.strip())
    return sorted(set(out))


def quote_arg(arg: str) -> str:
    if platform.system().lower().startswith("win"):
        if any(ch in arg for ch in [" ", "\t", '"']):
            return '"' + arg.replace('"', '\\"') + '"'
        return arg
    return arg


class TranslatorGUI:
    def __init__(self, root: tk.Tk) -> None:
        self.root = root
        self.root.title(APP_TITLE)
        self.root.geometry("1200x820")
        self.root.minsize(1000, 700)

        self.workdir = Path(__file__).resolve().parent
        self.translator_path = self._find_translator()
        self.proc: Optional[subprocess.Popen] = None
        self.log_queue: "queue.Queue[str]" = queue.Queue()

        self._setup_theme()
        self._build_vars()
        self._build_ui()
        self._load_defaults()
        self._load_settings(silent=True)
        self._update_command_preview()
        self._poll_log_queue()

    def _setup_theme(self) -> None:
        self.root.configure(bg="#eef3f7")
        style = ttk.Style(self.root)
        style.theme_use("clam")
        style.configure("TFrame", background="#eef3f7")
        style.configure("Card.TFrame", background="#ffffff", relief="flat")
        style.configure("TLabel", background="#eef3f7", foreground="#1f2937", font=("Segoe UI", 10))
        style.configure("Title.TLabel", background="#eef3f7", foreground="#0f172a", font=("Segoe UI Semibold", 18))
        style.configure("Sub.TLabel", background="#eef3f7", foreground="#334155", font=("Segoe UI", 10))
        style.configure("TButton", font=("Segoe UI", 10), padding=8)
        style.configure("Accent.TButton", background="#0ea5a3", foreground="#ffffff")
        style.map("Accent.TButton", background=[("active", "#0b8e8c")])
        style.configure("TEntry", padding=6)
        style.configure("TCombobox", padding=6)
        style.configure("TLabelframe", background="#eef3f7")
        style.configure("TLabelframe.Label", background="#eef3f7", foreground="#0f172a", font=("Segoe UI Semibold", 10))
        style.configure("StatusReady.TLabel", background="#eef3f7", foreground="#475569", font=("Segoe UI", 10))
        style.configure("StatusRun.TLabel", background="#eef3f7", foreground="#b45309", font=("Segoe UI Semibold", 10))
        style.configure("StatusOk.TLabel", background="#eef3f7", foreground="#166534", font=("Segoe UI Semibold", 10))
        style.configure("StatusErr.TLabel", background="#eef3f7", foreground="#b91c1c", font=("Segoe UI Semibold", 10))

    def _build_vars(self) -> None:
        self.mode_var = tk.StringVar(value="translate")
        self.provider_var = tk.StringVar(value="ollama")
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
        self.command_preview_var = tk.StringVar()
        self.status_var = tk.StringVar(value="Gotowe")
        self.progress_text_var = tk.StringVar(value="Postęp: 0 / 0")
        self.phase_var = tk.StringVar(value="Etap: oczekiwanie")
        self.progress_value_var = tk.DoubleVar(value=0.0)

    def _build_ui(self) -> None:
        outer = ttk.Frame(self.root, padding=16)
        outer.pack(fill="both", expand=True)

        ttk.Label(outer, text=APP_TITLE, style="Title.TLabel").pack(anchor="w")
        ttk.Label(
            outer,
            text="Nowoczesny panel do translacji EPUB (Ollama / Google) z zapisem ustawień i logiem na żywo.",
            style="Sub.TLabel",
        ).pack(anchor="w", pady=(0, 12))

        top = ttk.Frame(outer)
        top.pack(fill="both", expand=True)
        top.columnconfigure(0, weight=3)
        top.columnconfigure(1, weight=2)

        left = ttk.Frame(top)
        left.grid(row=0, column=0, sticky="nsew", padx=(0, 10))

        right = ttk.Frame(top)
        right.grid(row=0, column=1, sticky="nsew")

        self._build_files_card(left)
        self._build_engine_card(left)
        self._build_advanced_card(left)

        self._build_model_card(right)
        self._build_run_card(right)
        self._build_log_card(right)

        self.status_label = ttk.Label(outer, textvariable=self.status_var, style="StatusReady.TLabel")
        self.status_label.pack(anchor="w", pady=(10, 0))

    def _build_files_card(self, parent: ttk.Frame) -> None:
        card = ttk.LabelFrame(parent, text="Pliki i tryb", padding=12)
        card.pack(fill="x", pady=(0, 10))

        self._row_file(card, 0, "Wejściowy EPUB", self.input_epub_var, [("EPUB", "*.epub")], self._on_input_selected)
        self._row_file(card, 1, "Wyjściowy EPUB", self.output_epub_var, [("EPUB", "*.epub")])
        self._row_file(card, 2, "Prompt", self.prompt_var, [("TXT", "*.txt")], self._on_prompt_changed)
        self._row_file(card, 3, "Słownik", self.glossary_var, [("TXT", "*.txt")])
        self._row_file(card, 4, "Cache", self.cache_var, [("JSONL", "*.jsonl"), ("All", "*.*")])

        ttk.Label(card, text="Tryb:").grid(row=5, column=0, sticky="w", pady=(8, 0))
        mode_box = ttk.Frame(card)
        mode_box.grid(row=5, column=1, sticky="w", pady=(8, 0))
        ttk.Radiobutton(mode_box, text="Tłumaczenie EN -> PL", value="translate", variable=self.mode_var, command=self._on_mode_change).pack(side="left", padx=(0, 12))
        ttk.Radiobutton(mode_box, text="Redakcja PL -> PL", value="edit", variable=self.mode_var, command=self._on_mode_change).pack(side="left")

        card.columnconfigure(1, weight=1)

    def _build_engine_card(self, parent: ttk.Frame) -> None:
        card = ttk.LabelFrame(parent, text="Silnik i parametry batch", padding=12)
        card.pack(fill="x", pady=(0, 10))

        ttk.Label(card, text="Provider:").grid(row=0, column=0, sticky="w")
        pbox = ttk.Frame(card)
        pbox.grid(row=0, column=1, sticky="w")
        ttk.Radiobutton(pbox, text="Ollama (lokalnie)", value="ollama", variable=self.provider_var, command=self._on_provider_change).pack(side="left", padx=(0, 12))
        ttk.Radiobutton(pbox, text="Google Gemini API", value="google", variable=self.provider_var, command=self._on_provider_change).pack(side="left")

        ttk.Label(card, text="Ollama host:").grid(row=1, column=0, sticky="w", pady=(8, 0))
        self.ollama_host_entry = ttk.Entry(card, textvariable=self.ollama_host_var)
        self.ollama_host_entry.grid(row=1, column=1, sticky="ew", pady=(8, 0))

        ttk.Label(card, text="Google API key:").grid(row=2, column=0, sticky="w", pady=(8, 0))
        self.google_key_entry = ttk.Entry(card, textvariable=self.google_api_key_var, show="*")
        self.google_key_entry.grid(row=2, column=1, sticky="ew", pady=(8, 0))

        ttk.Label(card, text="Max segs / request:").grid(row=3, column=0, sticky="w", pady=(8, 0))
        ttk.Entry(card, textvariable=self.batch_max_segs_var, width=14).grid(row=3, column=1, sticky="w", pady=(8, 0))

        ttk.Label(card, text="Max chars / request:").grid(row=4, column=0, sticky="w", pady=(8, 0))
        ttk.Entry(card, textvariable=self.batch_max_chars_var, width=14).grid(row=4, column=1, sticky="w", pady=(8, 0))

        ttk.Label(card, text="Pauza między requestami:").grid(row=5, column=0, sticky="w", pady=(8, 0))
        ttk.Entry(card, textvariable=self.sleep_var, width=14).grid(row=5, column=1, sticky="w", pady=(8, 0))

        card.columnconfigure(1, weight=1)

    def _build_advanced_card(self, parent: ttk.Frame) -> None:
        card = ttk.LabelFrame(parent, text="Ustawienia zaawansowane", padding=12)
        card.pack(fill="x")

        ttk.Label(card, text="Timeout (s):").grid(row=0, column=0, sticky="w")
        ttk.Entry(card, textvariable=self.timeout_var, width=12).grid(row=0, column=1, sticky="w")

        ttk.Label(card, text="Attempts:").grid(row=0, column=2, sticky="w", padx=(12, 0))
        ttk.Entry(card, textvariable=self.attempts_var, width=8).grid(row=0, column=3, sticky="w")

        ttk.Label(card, text="Backoff:").grid(row=0, column=4, sticky="w", padx=(12, 0))
        ttk.Entry(card, textvariable=self.backoff_var, width=12).grid(row=0, column=5, sticky="w")

        ttk.Label(card, text="Temperature:").grid(row=1, column=0, sticky="w", pady=(8, 0))
        ttk.Entry(card, textvariable=self.temperature_var, width=12).grid(row=1, column=1, sticky="w", pady=(8, 0))

        ttk.Label(card, text="Num ctx:").grid(row=1, column=2, sticky="w", padx=(12, 0), pady=(8, 0))
        ttk.Entry(card, textvariable=self.num_ctx_var, width=10).grid(row=1, column=3, sticky="w", pady=(8, 0))

        ttk.Label(card, text="Num predict:").grid(row=1, column=4, sticky="w", padx=(12, 0), pady=(8, 0))
        ttk.Entry(card, textvariable=self.num_predict_var, width=10).grid(row=1, column=5, sticky="w", pady=(8, 0))

        ttk.Label(card, text="Checkpoint co N plików:").grid(row=2, column=0, sticky="w", pady=(8, 0))
        ttk.Entry(card, textvariable=self.checkpoint_var, width=12).grid(row=2, column=1, sticky="w", pady=(8, 0))

        ttk.Label(card, text="Debug dir:").grid(row=2, column=2, sticky="w", padx=(12, 0), pady=(8, 0))
        ttk.Entry(card, textvariable=self.debug_dir_var, width=24).grid(row=2, column=3, columnspan=3, sticky="ew", pady=(8, 0))

        ttk.Label(card, text="Tagi:").grid(row=3, column=0, sticky="w", pady=(8, 0))
        ttk.Entry(card, textvariable=self.tags_var).grid(row=3, column=1, columnspan=5, sticky="ew", pady=(8, 0))

        ttk.Checkbutton(card, text="Użyj cache", variable=self.use_cache_var, command=self._update_command_preview).grid(row=4, column=0, sticky="w", pady=(8, 0))
        ttk.Checkbutton(card, text="Użyj słownika", variable=self.use_glossary_var, command=self._update_command_preview).grid(row=4, column=1, columnspan=2, sticky="w", pady=(8, 0))

        for i in range(6):
            card.columnconfigure(i, weight=1)

    def _build_model_card(self, parent: ttk.Frame) -> None:
        card = ttk.LabelFrame(parent, text="Model AI", padding=12)
        card.pack(fill="x", pady=(0, 10))

        self.model_combo = ttk.Combobox(card, textvariable=self.model_var, state="readonly")
        self.model_combo.grid(row=0, column=0, sticky="ew")
        ttk.Button(card, text="Odśwież listę modeli", command=self._refresh_models).grid(row=0, column=1, padx=(8, 0))

        self.model_status = ttk.Label(card, text="", style="Sub.TLabel")
        self.model_status.grid(row=1, column=0, columnspan=2, sticky="w", pady=(6, 0))

        card.columnconfigure(0, weight=1)

    def _build_run_card(self, parent: ttk.Frame) -> None:
        card = ttk.LabelFrame(parent, text="Uruchomienie", padding=12)
        card.pack(fill="x", pady=(0, 10))

        ttk.Label(card, text="Podgląd komendy:").pack(anchor="w")
        ttk.Entry(card, textvariable=self.command_preview_var, state="readonly").pack(fill="x", pady=(4, 8))

        btns = ttk.Frame(card)
        btns.pack(fill="x")
        self.start_btn = ttk.Button(btns, text="Start translacji", style="Accent.TButton", command=self._start_process)
        self.start_btn.pack(side="left")
        self.stop_btn = ttk.Button(btns, text="Stop", command=self._stop_process, state="disabled")
        self.stop_btn.pack(side="left", padx=(8, 0))
        ttk.Button(btns, text="Zapisz ustawienia", command=self._save_settings).pack(side="left", padx=(16, 0))
        ttk.Button(btns, text="Wczytaj ustawienia", command=lambda: self._load_settings(silent=False)).pack(side="left", padx=(8, 0))

        progress_wrap = ttk.Frame(card)
        progress_wrap.pack(fill="x", pady=(10, 0))
        ttk.Label(progress_wrap, textvariable=self.progress_text_var, style="Sub.TLabel").pack(anchor="w")
        self.progress_bar = ttk.Progressbar(progress_wrap, mode="determinate", variable=self.progress_value_var, maximum=100.0)
        self.progress_bar.pack(fill="x", pady=(4, 0))
        ttk.Label(progress_wrap, textvariable=self.phase_var, style="Sub.TLabel").pack(anchor="w", pady=(4, 0))

    def _build_log_card(self, parent: ttk.Frame) -> None:
        card = ttk.LabelFrame(parent, text="Log", padding=12)
        card.pack(fill="both", expand=True)
        self.log_box = ScrolledText(card, height=20, font=("Consolas", 10), bg="#0f172a", fg="#e2e8f0", insertbackground="#e2e8f0")
        self.log_box.pack(fill="both", expand=True)
        self.log_box.configure(state="disabled")

    def _row_file(
        self,
        parent: ttk.LabelFrame,
        row: int,
        label: str,
        var: tk.StringVar,
        filetypes: List[tuple[str, str]],
        on_change=None,
    ) -> None:
        ttk.Label(parent, text=label + ":").grid(row=row, column=0, sticky="w", pady=(0, 6))
        entry = ttk.Entry(parent, textvariable=var)
        entry.grid(row=row, column=1, sticky="ew", pady=(0, 6))

        def pick() -> None:
            start_dir = str(self.workdir)
            path = filedialog.askopenfilename(title=label, initialdir=start_dir, filetypes=filetypes)
            if path:
                var.set(path)
                if on_change:
                    on_change()
                self._update_command_preview()

        ttk.Button(parent, text="Wybierz", command=pick).grid(row=row, column=2, padx=(8, 0), pady=(0, 6))

    def _load_defaults(self) -> None:
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

        self._on_provider_change()

    def _find_translator(self) -> Path:
        candidates = [
            self.workdir / "tlumacz_ollama_google_ollama.py",
            self.workdir / "tlumacz_ollama.py",
        ]
        for c in candidates:
            if c.exists():
                return c
        raise SystemExit("Nie znaleziono pliku tłumacza: tlumacz_ollama_google_ollama.py ani tlumacz_ollama.py")

    def _find_glossary(self, workdir: Path) -> Optional[Path]:
        for name in ["SLOWNIK.txt", "slownik.txt", "Slownik.txt", "Słownik.txt", "SŁOWNIK.txt"]:
            p = workdir / name
            if p.exists():
                return p
        cands = sorted([p for p in workdir.glob("*.txt") if "slownik" in p.name.lower() or "słownik" in p.name.lower()])
        return cands[0] if cands else None

    def _on_input_selected(self) -> None:
        self._suggest_output_and_cache()
        self._update_command_preview()

    def _on_prompt_changed(self) -> None:
        self._update_command_preview()

    def _on_mode_change(self) -> None:
        if self.mode_var.get() == "translate":
            p = self.workdir / "prompt.txt"
        else:
            p = self.workdir / "prompt_redakcja.txt"
        if p.exists():
            self.prompt_var.set(str(p))
        self._suggest_output_and_cache()
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
        if self.mode_var.get() == "translate":
            out_name = f"{stem}_pl.epub"
            cache_name = f"cache_{stem}.jsonl"
        else:
            out_name = f"{stem}_pl_redakcja.epub"
            cache_name = f"cache_{stem}_redakcja.jsonl"

        self.output_epub_var.set(str(p.with_name(out_name)))
        self.cache_var.set(str(p.with_name(cache_name)))

    def _refresh_models(self) -> None:
        self.model_status.configure(text="Pobieram listę modeli...")

        def worker() -> None:
            try:
                provider = self.provider_var.get()
                if provider == "ollama":
                    models = list_ollama_models(self.ollama_host_var.get().strip() or OLLAMA_HOST_DEFAULT)
                else:
                    key = self.google_api_key_var.get().strip()
                    if not key:
                        raise ValueError("Wpisz Google API key, żeby pobrać listę modeli.")
                    models = list_google_models(key)

                if not models:
                    raise ValueError("Brak modeli do wyboru.")

                self.root.after(0, lambda: self._set_models(models))
            except Exception as e:
                self.root.after(0, lambda: self.model_status.configure(text=f"Błąd: {e}"))

        threading.Thread(target=worker, daemon=True).start()

    def _set_models(self, models: List[str]) -> None:
        self.model_combo["values"] = models
        if self.model_var.get() not in models:
            self.model_var.set(models[0])
        self.model_status.configure(text=f"Załadowano {len(models)} modeli")
        self._update_command_preview()

    def _build_command(self) -> List[str]:
        provider = self.provider_var.get().strip()

        cmd = [
            "python",
            self.translator_path.name,
            self.input_epub_var.get().strip(),
            self.output_epub_var.get().strip(),
            "--prompt",
            self.prompt_var.get().strip(),
            "--provider",
            provider,
            "--model",
            self.model_var.get().strip(),
            "--batch-max-segs",
            self.batch_max_segs_var.get().strip(),
            "--batch-max-chars",
            self.batch_max_chars_var.get().strip(),
            "--sleep",
            self.sleep_var.get().strip(),
            "--timeout",
            self.timeout_var.get().strip(),
            "--attempts",
            self.attempts_var.get().strip(),
            "--backoff",
            self.backoff_var.get().strip(),
            "--temperature",
            self.temperature_var.get().strip(),
            "--num-ctx",
            self.num_ctx_var.get().strip(),
            "--num-predict",
            self.num_predict_var.get().strip(),
            "--tags",
            self.tags_var.get().strip(),
            "--checkpoint-every-files",
            self.checkpoint_var.get().strip(),
            "--debug-dir",
            self.debug_dir_var.get().strip(),
        ]

        if provider == "ollama":
            cmd += ["--host", self.ollama_host_var.get().strip() or OLLAMA_HOST_DEFAULT]
        else:
            cmd += ["--api-key", self.google_api_key_var.get().strip()]

        if self.use_cache_var.get() and self.cache_var.get().strip():
            cmd += ["--cache", self.cache_var.get().strip()]

        gloss = self.glossary_var.get().strip()
        if self.use_glossary_var.get() and gloss:
            cmd += ["--glossary", gloss]
        else:
            cmd += ["--no-glossary"]

        return cmd

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

        if self.provider_var.get() == "google" and not self.google_api_key_var.get().strip():
            return "Dla Google musisz podać API key."

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
            self.command_preview_var.set(" ".join(quote_arg(x) for x in cmd))
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

        m = GLOBAL_PROGRESS_RE.search(s)
        if m:
            done = int(m.group(1))
            total = int(m.group(2))
            pct_str = m.group(3).strip()
            detail = m.group(4).strip()
            pct = (done / total) * 100.0 if total > 0 else 0.0
            self.progress_value_var.set(pct)
            self.progress_text_var.set(f"Postęp: {done} / {total} ({pct_str})")
            self.phase_var.set(f"Etap: {detail}")
            self._set_status("Trwa translacja...", "running")
            return

        if "=== POST" in s and "GLOBAL" in s:
            self.phase_var.set("Etap: pre-skan projektu")
        elif "[CHECKPOINT]" in s:
            self.phase_var.set("Etap: checkpoint zapisu")
        elif "[Google]" in s:
            self.phase_var.set("Etap: żądania Google")
        elif "[Ollama]" in s:
            self.phase_var.set("Etap: żądania Ollama")
        elif "=== KONIEC ===" in s:
            self.phase_var.set("Etap: finalizacja")

    def _poll_log_queue(self) -> None:
        try:
            while True:
                line = self.log_queue.get_nowait()
                self._append_log(line)
                self._process_log_line(line)
        except queue.Empty:
            pass
        self.root.after(80, self._poll_log_queue)

    def _start_process(self) -> None:
        err = self._validate()
        if err:
            messagebox.showerror("Błąd walidacji", err)
            return

        if self.proc is not None:
            messagebox.showinfo("Informacja", "Proces już działa.")
            return

        self._save_settings(silent=True)
        cmd = self._build_command()
        redacted = self._redacted_cmd(cmd)
        self._append_log("\n=== START ===\n")
        self._append_log("Komenda: " + redacted + "\n\n")

        self.progress_value_var.set(0.0)
        self.progress_text_var.set("Postęp: 0 / 0")
        self.phase_var.set("Etap: uruchamianie")
        self.start_btn.configure(state="disabled")
        self.stop_btn.configure(state="normal")
        self._set_status("Trwa translacja...", "running")

        def runner() -> None:
            try:
                self.proc = subprocess.Popen(
                    cmd,
                    cwd=str(self.workdir),
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
                    self.log_queue.put("\n=== ZAKOŃCZONO OK ===\n")
                    self.root.after(0, lambda: self._set_status("Zakończono", "ok"))
                    self.root.after(0, lambda: self.phase_var.set("Etap: zakończono"))
                    self.root.after(0, lambda: self.progress_value_var.set(100.0 if self.progress_value_var.get() > 0 else self.progress_value_var.get()))
                else:
                    self.log_queue.put(f"\n=== BŁĄD (exit={code}) ===\n")
                    self.root.after(0, lambda: self._set_status("Błąd procesu", "error"))
                    self.root.after(0, lambda: self.phase_var.set("Etap: błąd"))
            except Exception as e:
                self.log_queue.put(f"\nBłąd uruchomienia: {e}\n")
                self.root.after(0, lambda: self._set_status("Błąd uruchomienia", "error"))
                self.root.after(0, lambda: self.phase_var.set("Etap: błąd uruchomienia"))
            finally:
                self.proc = None
                self.root.after(0, lambda: self.start_btn.configure(state="normal"))
                self.root.after(0, lambda: self.stop_btn.configure(state="disabled"))

        threading.Thread(target=runner, daemon=True).start()

    def _stop_process(self) -> None:
        if self.proc is None:
            return
        try:
            self.proc.terminate()
            self._set_status("Zatrzymuję proces...", "running")
            self.phase_var.set("Etap: zatrzymywanie")
            self.log_queue.put("\n[!] Wysłano terminate do procesu.\n")
        except Exception as e:
            self.log_queue.put(f"\nNie udało się zatrzymać procesu: {e}\n")

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
        return {
            "mode": self.mode_var.get(),
            "provider": self.provider_var.get(),
            "input_epub": self.input_epub_var.get(),
            "output_epub": self.output_epub_var.get(),
            "prompt": self.prompt_var.get(),
            "glossary": self.glossary_var.get(),
            "cache": self.cache_var.get(),
            "debug_dir": self.debug_dir_var.get(),
            "ollama_host": self.ollama_host_var.get(),
            "google_api_key": self.google_api_key_var.get(),
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
        }

    def _apply_settings(self, data: dict) -> None:
        self.mode_var.set(data.get("mode", self.mode_var.get()))
        self.provider_var.set(data.get("provider", self.provider_var.get()))
        self.input_epub_var.set(data.get("input_epub", self.input_epub_var.get()))
        self.output_epub_var.set(data.get("output_epub", self.output_epub_var.get()))
        self.prompt_var.set(data.get("prompt", self.prompt_var.get()))
        self.glossary_var.set(data.get("glossary", self.glossary_var.get()))
        self.cache_var.set(data.get("cache", self.cache_var.get()))
        self.debug_dir_var.set(data.get("debug_dir", self.debug_dir_var.get()))
        self.ollama_host_var.set(data.get("ollama_host", self.ollama_host_var.get()))
        self.google_api_key_var.set(data.get("google_api_key", self.google_api_key_var.get()))
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
        self._on_provider_change()
        self._update_command_preview()

    def _save_settings(self, silent: bool = False) -> None:
        try:
            SETTINGS_FILE.write_text(json.dumps(self._serialize(), ensure_ascii=False, indent=2), encoding="utf-8")
            if not silent:
                self._set_status(f"Zapisano ustawienia: {SETTINGS_FILE.name}", "ready")
        except Exception as e:
            if not silent:
                messagebox.showerror("Błąd", f"Nie udało się zapisać ustawień:\n{e}")

    def _load_settings(self, silent: bool = False) -> None:
        if not SETTINGS_FILE.exists():
            if not silent:
                messagebox.showinfo("Informacja", "Brak zapisanych ustawień.")
            return
        try:
            data = json.loads(SETTINGS_FILE.read_text(encoding="utf-8"))
            self._apply_settings(data)
            if not silent:
                self._set_status(f"Wczytano ustawienia: {SETTINGS_FILE.name}", "ready")
        except Exception as e:
            if not silent:
                messagebox.showerror("Błąd", f"Nie udało się wczytać ustawień:\n{e}")


def main() -> int:
    root = tk.Tk()
    TranslatorGUI(root)
    root.mainloop()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
