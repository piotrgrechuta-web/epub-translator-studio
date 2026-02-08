#!/usr/bin/env python3
# -*- coding: utf-8 -*-
from __future__ import annotations

import json
import re
import sqlite3
import subprocess
import time
import zipfile
from pathlib import Path
from typing import Any, Dict, Iterator, List, Optional, Tuple

import tkinter as tk
from tkinter import filedialog, messagebox, ttk
from tkinter.scrolledtext import ScrolledText
from lxml import etree

from epub_enhancer import list_chapters, load_chapter_segments, save_chapter_changes
from provider_runtime import load_plugins, render_command, plugin_health_check, rebuild_provider_manifest, validate_plugins_integrity
from qa_assignment import choose_assignee, build_load_map
from alerts import build_overdue_payload, send_webhook
from gui_tooltips import install_tooltips


EN_HINTS = {"the", "and", "of", "to", "in", "for", "with", "that", "this", "is", "are"}


def _txt(el: etree._Element) -> str:
    return etree.tostring(el, encoding="unicode", method="text").strip()


def _qa_scan_iter(epub: Path, segment_mode: str = "auto") -> Iterator[Dict[str, Any]]:
    for _, ch in list_chapters(epub):
        try:
            _, segs, seg_ids, _ = load_chapter_segments(epub, ch, segment_mode=segment_mode)
        except Exception:
            continue
        for i, s in enumerate(segs):
            t = _txt(s)
            low = t.lower()
            if "  " in t:
                yield {
                    "chapter_path": ch,
                    "segment_index": i,
                    "segment_id": seg_ids[i] if i < len(seg_ids) else "",
                    "severity": "warn",
                    "rule_code": "DOUBLE_SPACE",
                    "message": "double-space",
                }
            words = re.findall(r"[a-zA-Z]{2,}", low)
            if len(words) >= 8 and sum(1 for w in words if w in EN_HINTS) >= 2:
                yield {
                    "chapter_path": ch,
                    "segment_index": i,
                    "segment_id": seg_ids[i] if i < len(seg_ids) else "",
                    "severity": "error",
                    "rule_code": "EN_LEAK",
                    "message": "EN leak",
                }


class StudioSuiteWindow:
    def __init__(self, gui: Any) -> None:
        self.gui = gui
        self.win = tk.Toplevel(gui.root)
        self.win.title(self.gui.tr("studio.title", "Studio Tools"))
        self.gui._configure_window_bounds(self.win, preferred_w=1200, preferred_h=820, min_w=760, min_h=520, maximize=True)
        self.db_path = gui.workdir / "translator_studio.db"
        self._tooltips: List[Any] = []
        seg_mode = str(self.gui.db.get_setting("studio_segment_mode", "auto") or "auto").strip().lower()
        if seg_mode not in {"auto", "legacy"}:
            seg_mode = "auto"
        self.segment_mode_var = tk.StringVar(value=seg_mode)

        nb = ttk.Notebook(self.win)
        nb.pack(fill="both", expand=True, padx=10, pady=10)
        self._build_qa_tab(nb)
        self._build_editor_tab(nb)
        self._build_search_tab(nb)
        self._build_tm_tab(nb)
        self._build_snap_tab(nb)
        self._build_check_tab(nb)
        self._build_ill_tab(nb)
        self._build_pipeline_tab(nb)
        self._build_dashboard_tab(nb)
        self._build_plugins_tab(nb)
        self._install_tooltips()

    def _target(self) -> Optional[Path]:
        p = self.gui.output_epub_var.get().strip() or self.gui.input_epub_var.get().strip()
        return Path(p) if p and Path(p).exists() else None

    def _msg_info(self, message: str, title: Optional[str] = None) -> None:
        self.gui._msg_info(message, title=title)

    def _msg_error(self, message: str, title: Optional[str] = None) -> None:
        self.gui._msg_error(message, title=title)

    def _ask_yes_no(self, message: str, title: Optional[str] = None) -> bool:
        return self.gui._ask_yes_no(message, title=title)

    def _widget_opt(self, widget: tk.Misc, key: str) -> str:
        try:
            return str(widget.cget(key))
        except Exception:
            return ""

    def _install_tooltips(self) -> None:
        mode = str(self.gui.db.get_setting("tooltip_mode", "hybrid") or "hybrid").strip().lower()
        tt = self.gui.tr

        def tip(short: str, long: str = "", risky: bool = False) -> str:
            s = (short or "").strip()
            l = (long or "").strip()
            if mode == "short":
                return s
            if mode == "expert":
                return f"{s} {l}".strip() if l else s
            if risky and l:
                return f"{s} {l}".strip()
            return s

        text_tip = {
            self.gui.tr("button.choose", "Wybierz"): tip("Wybór pliku EPUB do analiz QA."),
            "Scan": tip("Skanuje EPUB i wykrywa błędy jakości.", "Wykrywa m.in. EN leak i podwójne spacje.", risky=True),
            "Save findings": tip("Zapisuje findings QA do bazy."),
            "Load open": tip("Ładuje otwarte findings QA."),
            "Mark resolved": tip("Oznacza zaznaczone findings jako resolved."),
            "Mark in_progress": tip("Oznacza zaznaczone findings jako in_progress."),
            "Approve QA": tip("Ustawia QA review = approved.", "Gate przechodzi tylko gdy brak open findings.", risky=True),
            "Reject QA": tip("Ustawia QA review = rejected.", "Gate zostaje zablokowany do czasu poprawy.", risky=True),
            "Assign selected": tip("Przypisuje zaznaczone findings do osoby/SLA."),
            "Assign all open": tip("Masowe przypisanie wszystkich otwartych findings."),
            "Escalate overdue": tip("Eskalacja przeterminowanych findings."),
            "Auto-assign rules": tip("Auto-przydział wg reguł JSON.", "Błędne reguły mogą przypisać zadania do złych osób.", risky=True),
            "Alert overdue": tip("Wysyła webhook z listą overdue."),
            "Load": tip("Ładuje rozdziały i segmenty do edycji."),
            "Save Segment": tip("Zapisuje zmiany segmentu."),
            "Save EPUB": tip("Zapisuje rozdział do EPUB i backup."),
            "Preview": tip("Podgląd trafień search/replace."),
            "Apply": tip("Wykonuje search/replace.", "Operacja zmienia treść EPUB.", risky=True),
            "Search": tip("Wyszukiwanie wpisów TM."),
            "Delete selected": tip("Usuwa wpisy TM.", "Operacja nieodwracalna.", risky=True),
            "Create": tip("Tworzy snapshot ZIP projektu."),
            "Restore": tip("Przywraca stan ze snapshotu.", "Nadpisuje obecne pliki.", risky=True),
            "Run epubcheck": tip("Uruchamia walidację epubcheck."),
            "Queue current project": tip("Ustawia projekt jako pending."),
            "Refresh": tip("Odświeża dane sekcji."),
            "Create template": tip("Tworzy przykładowy plugin JSON."),
            "Validate all": tip("Waliduje wszystkie pluginy providerów."),
            "Health check selected": tip("Uruchamia health-check wybranego pluginu."),
        }
        var_tip = {
            str(self.qa_epub._name): tip("Plik EPUB do skanowania QA."),
            str(self.qa_assignee_var._name): tip("Domyślny assignee dla przypisywania findings."),
            str(self.qa_due_days_var._name): tip("SLA w dniach.", "0 oznacza brak terminu i brak automatycznej eskalacji.", risky=True),
            str(self.qa_webhook_var._name): tip("URL webhooka dla alertów overdue.", "Błędny URL spowoduje brak powiadomień.", risky=True),
            str(self.qa_rules_var._name): tip("Reguły auto-przydziału JSON.", "Mapują rule_code/severity na assignee.", risky=True),
            str(self.src_epub._name): tip("EPUB źródłowy do porównania."),
            str(self.tgt_epub._name): tip("EPUB docelowy do edycji."),
            str(self.s_find._name): tip("Fraza szukana."),
            str(self.s_rep._name): tip("Fraza zamienna."),
            str(self.tm_q._name): tip("Filtr wyszukiwania TM."),
            str(self.chk_epub._name): tip("EPUB do walidacji epubcheck."),
            str(self.ill_epub._name): tip("EPUB dla reguł ilustracji."),
            str(self.ill_dir._name): tip("Katalog z ilustracjami."),
            str(self.ill_tag._name): tip("Tag rozdziału dla reguły ilustracji."),
        }
        object_tip = {
            id(self.qa_list): "Lista findings QA wraz ze statusem, assignee i SLA.",
            id(self.ch_list): "Lista rozdziałów dla edytora side-by-side.",
            id(self.seg_list): "Lista segmentów wybranego rozdziału.",
            id(self.src_txt): "Podgląd tekstu źródłowego (read-only).",
            id(self.tgt_txt): "Edytowalny tekst docelowy segmentu.",
            id(self.s_list): "Wyniki wyszukiwania/trafienia replace.",
            id(self.tm_list): "Wyniki Translation Memory.",
            id(self.snap_list): "Lista dostępnych snapshotów.",
            id(self.chk_log): "Log wyników EPUBCheck.",
            id(self.ill_log): "Log operacji ilustracji.",
            id(self.dash): "Dashboard metryk runów, QA i TM.",
            id(self.pl_list): "Lista pluginów providerów i wpisów invalid.",
            id(self.pl_log): "Log walidacji i health-check pluginów.",
        }

        def fallback(widget: tk.Misc) -> Optional[str]:
            cls = str(widget.winfo_class())
            if cls in {"TEntry", "Entry"}:
                return tt("tip.fallback.entry", "Configuration input field affecting current pipeline step.")
            if cls in {"Listbox"}:
                return "Lista elementów tej sekcji."
            if cls in {"TButton"}:
                return "Akcja uruchamiająca operację tej sekcji."
            if cls in {"Text"}:
                return "Pole tekstowe z logiem/podglądem/edycją."
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

        self._tooltips = install_tooltips(self.win, resolver)

    def _build_qa_tab(self, nb: ttk.Notebook) -> None:
        tab = ttk.Frame(nb, padding=8)
        nb.add(tab, text=self.gui.tr("studio.tab.qa", "QA"))
        self.qa_epub = tk.StringVar(value=str(self._target() or ""))
        top = ttk.Frame(tab)
        top.pack(fill="x")
        ttk.Entry(top, textvariable=self.qa_epub).pack(side="left", fill="x", expand=True)
        ttk.Button(top, text="Wybierz", command=self._pick_qa).pack(side="left", padx=(8, 0))
        ttk.Button(top, text="Scan", command=self._scan_qa).pack(side="left", padx=(8, 0))
        ttk.Button(top, text="Save findings", command=self._qa_save_findings).pack(side="left", padx=(8, 0))
        ttk.Button(top, text="Load open", command=self._qa_load_open).pack(side="left", padx=(8, 0))
        ttk.Button(top, text="Mark resolved", command=self._qa_mark_resolved).pack(side="left", padx=(8, 0))
        ttk.Button(top, text="Mark in_progress", command=self._qa_mark_in_progress).pack(side="left", padx=(8, 0))
        ttk.Button(top, text="Approve QA", command=self._qa_approve).pack(side="left", padx=(8, 0))
        ttk.Button(top, text="Reject QA", command=self._qa_reject).pack(side="left", padx=(8, 0))
        self.qa_assignee_var = tk.StringVar(value=str(self.gui.db.get_setting("qa_reviewer_name", "reviewer")))
        self.qa_due_days_var = tk.StringVar(value="2")
        ttk.Entry(top, textvariable=self.qa_assignee_var, width=14).pack(side="left", padx=(8, 0))
        ttk.Entry(top, textvariable=self.qa_due_days_var, width=4).pack(side="left", padx=(4, 0))
        ttk.Button(top, text="Assign selected", command=self._qa_assign_selected).pack(side="left", padx=(8, 0))
        ttk.Button(top, text="Assign all open", command=self._qa_assign_all_open).pack(side="left", padx=(8, 0))
        ttk.Button(top, text="Escalate overdue", command=self._qa_escalate_overdue).pack(side="left", padx=(8, 0))
        ttk.Button(top, text="Auto-assign rules", command=self._qa_auto_assign_rules).pack(side="left", padx=(8, 0))
        ttk.Button(top, text="Alert overdue", command=self._qa_alert_overdue).pack(side="left", padx=(8, 0))
        ttk.Label(top, text="Seg mode").pack(side="left", padx=(12, 0))
        seg_combo = ttk.Combobox(top, textvariable=self.segment_mode_var, state="readonly", width=8, values=("auto", "legacy"))
        seg_combo.pack(side="left", padx=(4, 0))
        seg_combo.bind("<<ComboboxSelected>>", lambda _: self._on_segment_mode_change())
        self.qa_list = tk.Listbox(tab)
        self.qa_list.pack(fill="both", expand=True, pady=(8, 0))
        self.qa_gate_var = tk.StringVar(value="Gate: n/a")
        ttk.Label(tab, textvariable=self.qa_gate_var, style="Sub.TLabel").pack(anchor="w", pady=(6, 0))
        cfg = ttk.Frame(tab); cfg.pack(fill="x", pady=(6, 0))
        self.qa_webhook_var = tk.StringVar(value=str(self.gui.db.get_setting("qa_webhook_url", "")))
        self.qa_rules_var = tk.StringVar(
            value=json.dumps(
                self.gui.db.get_setting(
                    "qa_assignment_rules",
                    {
                        "default": "reviewer",
                        "severity": {"error": "senior_qa", "warn": "qa"},
                        "rule_code": {"EN_LEAK": "linguist"},
                        "max_open_per_assignee": 100,
                    },
                ),
                ensure_ascii=False,
            )
        )
        ttk.Label(cfg, text="Webhook").pack(side="left")
        ttk.Entry(cfg, textvariable=self.qa_webhook_var, width=40).pack(side="left", padx=(6, 0))
        ttk.Label(cfg, text="Rules JSON").pack(side="left", padx=(10, 0))
        ttk.Entry(cfg, textvariable=self.qa_rules_var, width=70).pack(side="left", padx=(6, 0))
        self.qa_rows: List[Dict[str, Any]] = []

    def _fmt_ts(self, ts: Any) -> str:
        try:
            if ts is None:
                return "-"
            return time.strftime("%Y-%m-%d", time.localtime(int(ts)))
        except Exception:
            return "-"

    def _pick_qa(self) -> None:
        p = filedialog.askopenfilename(filetypes=[("EPUB", "*.epub")], initialdir=str(self.gui.workdir))
        if p:
            self.qa_epub.set(p)

    def _scan_qa(self) -> None:
        self.qa_list.delete(0, "end")
        p = Path(self.qa_epub.get().strip())
        if not p.exists():
            return
        self.qa_rows = []
        for x in _qa_scan_iter(p, segment_mode=self._segment_mode()):
            self.qa_rows.append(x)
            marker = str(x.get("segment_id", "") or x.get("segment_index", ""))
            self.qa_list.insert("end", f"[{x['severity']}] {x['chapter_path']}#{marker} {x['rule_code']} {x['message']}")
        if not self.qa_rows:
            self.qa_list.insert("end", "No issues.")
        self._qa_refresh_gate()

    def _qa_project_id(self) -> Optional[int]:
        return self.gui.current_project_id

    def _qa_step(self) -> str:
        return self.gui.mode_var.get().strip() or "translate"

    def _qa_save_findings(self) -> None:
        pid = self._qa_project_id()
        if pid is None:
            self._msg_info(self.gui.tr("studio.info.select_project", "Select project first."))
            return
        count = self.gui.db.replace_qa_findings(pid, self._qa_step(), self.qa_rows)
        # New scan invalidates previous approvals for this step.
        self.gui.db.set_qa_review(pid, self._qa_step(), status="pending", approver="", notes="new findings scan")
        self.gui._refresh_projects(select_current=True)
        self._qa_refresh_gate()
        self._msg_info(
            self.gui.tr("studio.info.saved_findings", "Saved findings: {count}", count=count),
            title=self.gui.tr("mb.ok", "OK"),
        )

    def _qa_load_open(self) -> None:
        pid = self._qa_project_id()
        if pid is None:
            return
        rows = self.gui.db.list_qa_findings(pid, step=self._qa_step(), status=None)
        self.qa_list.delete(0, "end")
        self.qa_rows = []
        for r in rows:
            rec = dict(r)
            if rec.get("status") not in ("open", "in_progress"):
                continue
            self.qa_rows.append(rec)
            due = self._fmt_ts(rec.get("due_at"))
            ass = str(rec.get("assignee", "") or "-")
            esc = str(rec.get("escalation_status", "none") or "none")
            self.qa_list.insert(
                "end",
                f"[{rec['severity']}/{rec['status']}/{esc}] #{rec['id']} {rec['chapter_path']}#{(rec.get('segment_id') or rec['segment_index'])} "
                f"{rec['rule_code']} {rec['message']} | assignee={ass} due={due}",
            )
        self._qa_refresh_gate()

    def _qa_mark_resolved(self) -> None:
        self._qa_mark("resolved")

    def _qa_mark_in_progress(self) -> None:
        self._qa_mark("in_progress")

    def _qa_mark(self, status: str) -> None:
        sel = list(self.qa_list.curselection())
        if not sel:
            return
        for i in sel:
            if i >= len(self.qa_rows):
                continue
            rec = self.qa_rows[i]
            fid = rec.get("id")
            if fid is None:
                continue
            self.gui.db.update_qa_finding_status(int(fid), status)
        self._qa_load_open()
        self._qa_refresh_gate()

    def _qa_due_ts(self) -> Optional[int]:
        try:
            days = int((self.qa_due_days_var.get() or "0").strip())
        except Exception:
            days = 0
        if days <= 0:
            return None
        return int(time.time()) + (days * 24 * 3600)

    def _qa_assign_selected(self) -> None:
        sels = list(self.qa_list.curselection())
        if not sels:
            return
        assignee = (self.qa_assignee_var.get() or "").strip()
        self.gui.db.set_setting("qa_reviewer_name", assignee)
        due_ts = self._qa_due_ts()
        for i in sels:
            if i >= len(self.qa_rows):
                continue
            rec = self.qa_rows[i]
            fid = rec.get("id")
            if fid is None:
                continue
            self.gui.db.assign_qa_finding(int(fid), assignee, due_ts)
        self._qa_load_open()

    def _qa_assign_all_open(self) -> None:
        pid = self._qa_project_id()
        if pid is None:
            return
        assignee = (self.qa_assignee_var.get() or "").strip()
        self.gui.db.set_setting("qa_reviewer_name", assignee)
        due_ts = self._qa_due_ts()
        n = self.gui.db.assign_open_findings(pid, self._qa_step(), assignee, due_ts)
        self._qa_load_open()
        self.qa_list.insert("end", f"--- assigned open findings: {n} ---")

    def _qa_escalate_overdue(self) -> None:
        pid = self._qa_project_id()
        if pid is None:
            return
        n = self.gui.db.escalate_overdue_findings(project_id=pid)
        self._qa_load_open()
        self.qa_list.insert("end", f"--- escalated overdue: {n} ---")

    def _qa_auto_assign_rules(self) -> None:
        pid = self._qa_project_id()
        if pid is None:
            return
        step = self._qa_step()
        try:
            rules = json.loads(self.qa_rules_var.get().strip() or "{}")
            if not isinstance(rules, dict):
                raise ValueError("rules must be object")
        except Exception as e:
            self._msg_error(
                self.gui.tr("studio.err.rules_json", "Invalid rules JSON: {err}", err=e),
                title=self.gui.tr("studio.title.rules_json", "Rules JSON"),
            )
            return
        self.gui.db.set_setting("qa_assignment_rules", rules)
        self.gui.db.set_setting("qa_reviewer_name", self.qa_assignee_var.get().strip())
        self.gui.db.set_setting("qa_webhook_url", self.qa_webhook_var.get().strip())

        rows = [dict(r) for r in self.gui.db.list_qa_findings(pid, step=step, status=None) if str(r["status"]) in ("open", "in_progress")]
        load = build_load_map(rows)
        due_ts = self._qa_due_ts()
        assigned = 0
        for r in rows:
            fid = int(r["id"])
            ass = choose_assignee(
                rule_code=str(r.get("rule_code", "")),
                severity=str(r.get("severity", "warn")),
                rules=rules,
                current_load=load,
            )
            self.gui.db.assign_qa_finding(fid, ass, due_ts)
            load[ass] = load.get(ass, 0) + 1
            assigned += 1
        self._qa_load_open()
        self.qa_list.insert("end", f"--- auto-assigned: {assigned} ---")

    def _qa_alert_overdue(self) -> None:
        pid = self._qa_project_id()
        if pid is None:
            return
        self.gui.db.set_setting("qa_webhook_url", self.qa_webhook_var.get().strip())
        webhook = self.qa_webhook_var.get().strip()
        project = self.gui.db.get_project(pid)
        pname = str(project["name"]) if project else f"project-{pid}"
        overdue = [dict(r) for r in self.gui.db.list_overdue_findings(project_id=pid)]
        payload = build_overdue_payload(pname, overdue)
        ok, msg = send_webhook(webhook, payload)
        self.qa_list.insert("end", f"--- alert sent: {'OK' if ok else 'FAIL'} | {msg} ---")

    def _qa_approve(self) -> None:
        pid = self._qa_project_id()
        if pid is None:
            return
        who = (self.gui.db.get_setting("qa_reviewer_name", "") or "").strip()
        if not who:
            who = "reviewer"
        self.gui.db.set_qa_review(pid, self._qa_step(), status="approved", approver=who, notes="approved in Studio Tools")
        self._qa_refresh_gate()

    def _qa_reject(self) -> None:
        pid = self._qa_project_id()
        if pid is None:
            return
        who = (self.gui.db.get_setting("qa_reviewer_name", "") or "").strip()
        if not who:
            who = "reviewer"
        self.gui.db.set_qa_review(pid, self._qa_step(), status="rejected", approver=who, notes="rejected in Studio Tools")
        self._qa_refresh_gate()

    def _qa_refresh_gate(self) -> None:
        pid = self._qa_project_id()
        if pid is None:
            self.qa_gate_var.set("Gate: n/a")
            return
        ok, msg = self.gui.db.qa_gate_status(pid, self._qa_step())
        self.qa_gate_var.set(f"Gate: {'PASS' if ok else 'BLOCK'} | {msg}")

    def _build_editor_tab(self, nb: ttk.Notebook) -> None:
        tab = ttk.Frame(nb, padding=8)
        nb.add(tab, text=self.gui.tr("studio.tab.editor", "Side-by-side + Hotkeys"))
        self.src_epub = tk.StringVar(value=self.gui.input_epub_var.get().strip())
        self.tgt_epub = tk.StringVar(value=self.gui.output_epub_var.get().strip() or self.gui.input_epub_var.get().strip())
        top = ttk.Frame(tab)
        top.pack(fill="x")
        ttk.Label(top, text="Source").pack(side="left")
        ttk.Entry(top, textvariable=self.src_epub, width=42).pack(side="left", padx=(6, 0))
        ttk.Label(top, text="Target").pack(side="left", padx=(8, 0))
        ttk.Entry(top, textvariable=self.tgt_epub, width=42).pack(side="left", padx=(6, 0))
        ttk.Label(top, text="Seg mode").pack(side="left", padx=(8, 0))
        seg_combo = ttk.Combobox(top, textvariable=self.segment_mode_var, state="readonly", width=8, values=("auto", "legacy"))
        seg_combo.pack(side="left", padx=(4, 0))
        seg_combo.bind("<<ComboboxSelected>>", lambda _: self._on_segment_mode_change())
        ttk.Button(top, text="Load", command=self._load_editor).pack(side="left", padx=(8, 0))
        self.ch_list = tk.Listbox(tab, width=46, height=12)
        self.ch_list.pack(fill="x", pady=(8, 0))
        self.ch_list.bind("<<ListboxSelect>>", lambda _: self._load_segments())
        self.seg_list = tk.Listbox(tab, height=8)
        self.seg_list.pack(fill="x", pady=(8, 0))
        self.seg_list.bind("<<ListboxSelect>>", lambda _: self._show_seg())
        pan = ttk.Panedwindow(tab, orient=tk.HORIZONTAL)
        pan.pack(fill="both", expand=True, pady=(8, 0))
        lf = ttk.Frame(pan); rf = ttk.Frame(pan)
        pan.add(lf, weight=1); pan.add(rf, weight=1)
        self.src_txt = ScrolledText(lf, font=("Consolas", 10)); self.src_txt.pack(fill="both", expand=True)
        self.src_txt.configure(state="disabled")
        self.tgt_txt = ScrolledText(rf, font=("Consolas", 10)); self.tgt_txt.pack(fill="both", expand=True)
        btn = ttk.Frame(tab); btn.pack(fill="x", pady=(8, 0))
        ttk.Button(btn, text="Save Segment", command=self._save_seg).pack(side="left")
        ttk.Button(btn, text="Save EPUB", command=self._save_epub).pack(side="left", padx=(8, 0))
        ttk.Label(btn, text="Alt+Down/Alt+Up, Ctrl+S").pack(side="right")
        self._chapters: List[str] = []; self._src=[]; self._tgt=[]; self._root=None; self._ch=None
        self.win.bind("<Control-s>", lambda _: self._save_seg())
        self.win.bind("<Alt-Down>", lambda _: self._next_seg())
        self.win.bind("<Alt-Up>", lambda _: self._prev_seg())

    def _load_editor(self) -> None:
        self.ch_list.delete(0, "end")
        src = Path(self.src_epub.get().strip())
        if not src.exists():
            return
        self._chapters = [c for _, c in list_chapters(src)]
        for c in self._chapters:
            self.ch_list.insert("end", c)

    def _load_segments(self) -> None:
        sel = self.ch_list.curselection()
        if not sel:
            return
        ch = self._chapters[int(sel[0])]
        src = Path(self.src_epub.get().strip()); tgt = Path(self.tgt_epub.get().strip())
        mode = self._segment_mode()
        sr, self._src, _, _ = load_chapter_segments(src, ch, segment_mode=mode)
        self._root, self._tgt, _, _ = load_chapter_segments(tgt, ch, segment_mode=mode)
        _ = sr
        self._ch = ch
        self.seg_list.delete(0, "end")
        for i in range(min(len(self._src), len(self._tgt))):
            s = _txt(self._src[i]).replace("\n", " ")
            self.seg_list.insert("end", f"{i:04d} {s[:100]}")

    def _show_seg(self) -> None:
        sel = self.seg_list.curselection()
        if not sel:
            return
        i = int(sel[0])
        if i >= len(self._src) or i >= len(self._tgt):
            return
        self.src_txt.configure(state="normal"); self.src_txt.delete("1.0", "end"); self.src_txt.insert("1.0", _txt(self._src[i])); self.src_txt.configure(state="disabled")
        self.tgt_txt.delete("1.0", "end"); self.tgt_txt.insert("1.0", _txt(self._tgt[i]))

    def _save_seg(self) -> None:
        sel = self.seg_list.curselection()
        if not sel:
            return
        i = int(sel[0]); txt = self.tgt_txt.get("1.0", "end").strip()
        el = self._tgt[i]
        for c in list(el):
            el.remove(c)
        el.text = txt

    def _save_epub(self) -> None:
        if self._root is None or self._ch is None:
            return
        tgt = Path(self.tgt_epub.get().strip())
        out, bak = save_chapter_changes(tgt, self._ch, self._root)
        self.gui._push_operation({"type": "backup_restore", "target": str(out), "backup": str(bak)})
        self._msg_info(
            self.gui.tr("studio.info.saved_backup", "Saved.\nBackup: {name}", name=bak.name),
            title=self.gui.tr("mb.ok", "OK"),
        )

    def _next_seg(self) -> None:
        sel = self.seg_list.curselection()
        if not sel:
            return
        i = int(sel[0]) + 1
        if i < self.seg_list.size():
            self.seg_list.selection_clear(0, "end"); self.seg_list.selection_set(i); self._show_seg()

    def _prev_seg(self) -> None:
        sel = self.seg_list.curselection()
        if not sel:
            return
        i = int(sel[0]) - 1
        if i >= 0:
            self.seg_list.selection_clear(0, "end"); self.seg_list.selection_set(i); self._show_seg()

    def _build_search_tab(self, nb: ttk.Notebook) -> None:
        tab = ttk.Frame(nb, padding=8); nb.add(tab, text=self.gui.tr("studio.tab.search", "Search/Replace"))
        self.s_find = tk.StringVar(); self.s_rep = tk.StringVar(); self.s_hits: List[Tuple[str, int]] = []
        top = ttk.Frame(tab); top.pack(fill="x")
        ttk.Entry(top, textvariable=self.s_find, width=36).pack(side="left")
        ttk.Entry(top, textvariable=self.s_rep, width=36).pack(side="left", padx=(8, 0))
        ttk.Button(top, text="Preview", command=self._s_preview).pack(side="left", padx=(8, 0))
        ttk.Button(top, text="Apply", command=self._s_apply).pack(side="left", padx=(8, 0))
        self.s_list = tk.Listbox(tab); self.s_list.pack(fill="both", expand=True, pady=(8, 0))

    def _s_preview(self) -> None:
        self.s_list.delete(0, "end"); self.s_hits = []
        f = self.s_find.get(); tgt = self._target()
        if not f or not tgt:
            return
        for _, ch in list_chapters(tgt):
            try:
                _, segs, _, _ = load_chapter_segments(tgt, ch, segment_mode=self._segment_mode())
            except Exception:
                continue
            for i, s in enumerate(segs):
                t = _txt(s)
                if f in t:
                    self.s_hits.append((ch, i)); self.s_list.insert("end", f"{ch}#{i}: {t[:90]}")
        self.s_list.insert("end", f"hits={len(self.s_hits)}")

    def _s_apply(self) -> None:
        tgt = self._target(); f = self.s_find.get(); r = self.s_rep.get()
        if not tgt or not f:
            return
        if not self._ask_yes_no(
            self.gui.tr("studio.confirm.apply_replace", "Apply replace '{f}' -> '{r}'?", f=f, r=r),
            title=self.gui.tr("mb.confirm", "Confirm"),
        ):
            return
        hits_by_ch: Dict[str, List[int]] = {}
        for ch, i in self.s_hits:
            hits_by_ch.setdefault(ch, []).append(i)
        last_bak = None
        for ch, indices in hits_by_ch.items():
            try:
                root, segs, _, _ = load_chapter_segments(tgt, ch, segment_mode=self._segment_mode())
            except Exception:
                continue
            for i in indices:
                if i < len(segs):
                    el = segs[i]
                    txt = _txt(el).replace(f, r)
                    for c in list(el):
                        el.remove(c)
                    el.text = txt
            _, bak = save_chapter_changes(tgt, ch, root)
            last_bak = bak
        if last_bak:
            self.gui._push_operation({"type": "backup_restore", "target": str(tgt), "backup": str(last_bak)})

    def _segment_mode(self) -> str:
        mode = (self.segment_mode_var.get() or "auto").strip().lower()
        return mode if mode in {"auto", "legacy"} else "auto"

    def _on_segment_mode_change(self) -> None:
        mode = self._segment_mode()
        self.segment_mode_var.set(mode)
        try:
            self.gui.db.set_setting("studio_segment_mode", mode)
        except Exception:
            pass

    def _build_tm_tab(self, nb: ttk.Notebook) -> None:
        tab = ttk.Frame(nb, padding=8); nb.add(tab, text=self.gui.tr("studio.tab.tm", "TM Manager"))
        self.tm_q = tk.StringVar()
        top = ttk.Frame(tab); top.pack(fill="x")
        ttk.Entry(top, textvariable=self.tm_q).pack(side="left", fill="x", expand=True)
        ttk.Button(top, text="Search", command=self._tm_refresh).pack(side="left", padx=(8, 0))
        ttk.Button(top, text="Delete selected", command=self._tm_delete).pack(side="left", padx=(8, 0))
        self.tm_list = tk.Listbox(tab); self.tm_list.pack(fill="both", expand=True, pady=(8, 0))
        self.tm_ids: List[int] = []
        self._tm_refresh()

    def _tm_refresh(self) -> None:
        self.tm_list.delete(0, "end"); self.tm_ids = []
        q = self.tm_q.get().strip().lower()
        con = sqlite3.connect(str(self.db_path)); con.row_factory = sqlite3.Row
        try:
            if q:
                rows = con.execute("SELECT id,source_text,target_text FROM tm_segments WHERE lower(source_text) LIKE ? OR lower(target_text) LIKE ? ORDER BY id DESC LIMIT 500", (f"%{q}%", f"%{q}%")).fetchall()
            else:
                rows = con.execute("SELECT id,source_text,target_text FROM tm_segments ORDER BY id DESC LIMIT 500").fetchall()
            for r in rows:
                self.tm_ids.append(int(r["id"])); self.tm_list.insert("end", f"#{r['id']} {str(r['source_text'])[:60]} => {str(r['target_text'])[:60]}")
        finally:
            con.close()

    def _tm_delete(self) -> None:
        sel = list(self.tm_list.curselection()); ids = [self.tm_ids[int(i)] for i in sel if int(i) < len(self.tm_ids)]
        if not ids:
            return
        con = sqlite3.connect(str(self.db_path))
        try:
            con.executemany("DELETE FROM tm_segments WHERE id = ?", [(i,) for i in ids]); con.commit()
        finally:
            con.close()
        self._tm_refresh()

    def _build_snap_tab(self, nb: ttk.Notebook) -> None:
        tab = ttk.Frame(nb, padding=8); nb.add(tab, text=self.gui.tr("studio.tab.snapshots", "Snapshots"))
        top = ttk.Frame(tab); top.pack(fill="x")
        ttk.Button(top, text="Create", command=self._snap_create).pack(side="left")
        ttk.Button(top, text="Restore", command=self._snap_restore).pack(side="left", padx=(8, 0))
        self.snap_list = tk.Listbox(tab); self.snap_list.pack(fill="both", expand=True, pady=(8, 0))
        self._snap_refresh()

    def _snap_dir(self) -> Path:
        d = self.gui.workdir / "snapshots"; d.mkdir(parents=True, exist_ok=True); return d

    def _snap_refresh(self) -> None:
        self.snap_list.delete(0, "end")
        for p in sorted(self._snap_dir().glob("*.zip"), reverse=True):
            self.snap_list.insert("end", p.name)

    def _snap_create(self) -> None:
        p = self._snap_dir() / f"snapshot_{time.strftime('%Y%m%d_%H%M%S')}.zip"
        with zipfile.ZipFile(p, "w") as z:
            for n in [
                "app_main.py",
                "app_gui_classic.py",
                "app_gui_horizon.py",
                "start.py",
                "start_horizon.py",
                "tlumacz_ollama.py",
                "project_db.py",
                "epub_enhancer.py",
                "studio_suite.py",
                "translator_studio.db",
            ]:
                f = self.gui.workdir / n
                if f.exists(): z.write(f, arcname=f.name)
        self._snap_refresh()

    def _snap_restore(self) -> None:
        sel = self.snap_list.curselection()
        if not sel:
            return
        p = self._snap_dir() / self.snap_list.get(int(sel[0]))
        if not p.exists():
            return
        if not self._ask_yes_no(
            self.gui.tr("studio.confirm.restore_snapshot", "Restore {name}?", name=p.name),
            title=self.gui.tr("studio.title.restore", "Restore"),
        ):
            return
        with zipfile.ZipFile(p, "r") as z:
            z.extractall(self.gui.workdir)
        self._msg_info(self.gui.tr("studio.info.restored", "Restored."), title=self.gui.tr("mb.ok", "OK"))

    def _build_check_tab(self, nb: ttk.Notebook) -> None:
        tab = ttk.Frame(nb, padding=8); nb.add(tab, text=self.gui.tr("studio.tab.epubcheck", "EPUBCheck"))
        self.chk_epub = tk.StringVar(value=str(self._target() or ""))
        top = ttk.Frame(tab); top.pack(fill="x")
        ttk.Entry(top, textvariable=self.chk_epub).pack(side="left", fill="x", expand=True)
        ttk.Button(top, text="Run epubcheck", command=self._run_chk).pack(side="left", padx=(8, 0))
        self.chk_log = ScrolledText(tab, font=("Consolas", 10)); self.chk_log.pack(fill="both", expand=True, pady=(8, 0))

    def _run_chk(self) -> None:
        e = self.chk_epub.get().strip()
        if not e:
            return
        try:
            p = subprocess.run(["epubcheck", e], capture_output=True, text=True, encoding="utf-8", errors="replace")
            out = (p.stdout or "") + "\n" + (p.stderr or "")
        except Exception as ex:
            out = f"epubcheck unavailable: {ex}"
        self.chk_log.delete("1.0", "end"); self.chk_log.insert("1.0", out)

    def _build_ill_tab(self, nb: ttk.Notebook) -> None:
        tab = ttk.Frame(nb, padding=8); nb.add(tab, text=self.gui.tr("studio.tab.illustration", "Illustration Rule"))
        self.ill_epub = tk.StringVar(value=str(self._target() or ""))
        self.ill_dir = tk.StringVar(value=str(self.gui.workdir))
        self.ill_tag = tk.StringVar(value="h2")
        top = ttk.Frame(tab); top.pack(fill="x")
        ttk.Entry(top, textvariable=self.ill_epub, width=40).pack(side="left")
        ttk.Entry(top, textvariable=self.ill_dir, width=40).pack(side="left", padx=(8, 0))
        ttk.Entry(top, textvariable=self.ill_tag, width=8).pack(side="left", padx=(8, 0))
        ttk.Button(top, text="Apply", command=self._ill_apply).pack(side="left", padx=(8, 0))
        self.ill_log = tk.Listbox(tab); self.ill_log.pack(fill="both", expand=True, pady=(8, 0))

    def _ill_apply(self) -> None:
        self.ill_log.insert("end", "MVP: użyj przycisków z panelu Uładnianie EPUB (wizard ilustracji jest next step).")

    def _build_pipeline_tab(self, nb: ttk.Notebook) -> None:
        tab = ttk.Frame(nb, padding=8); nb.add(tab, text=self.gui.tr("studio.tab.pipeline", "Pipeline"))
        ttk.Label(tab, text="Queue translate -> edit z istniejącym auto-przejściem.").pack(anchor="w")
        ttk.Button(tab, text="Queue current project", command=self._pipe_queue).pack(anchor="w", pady=(8, 0))

    def _pipe_queue(self) -> None:
        if self.gui.current_project_id is None:
            self._msg_info(self.gui.tr("studio.info.select_project", "Select project first."))
            return
        self.gui.db.mark_project_pending(self.gui.current_project_id, "translate")
        self.gui._refresh_projects(select_current=True)

    def _build_dashboard_tab(self, nb: ttk.Notebook) -> None:
        tab = ttk.Frame(nb, padding=8); nb.add(tab, text=self.gui.tr("studio.tab.dashboard", "Dashboard"))
        ttk.Button(tab, text="Refresh", command=self._dash_refresh).pack(anchor="w")
        self.dash = ScrolledText(tab, font=("Consolas", 10)); self.dash.pack(fill="both", expand=True, pady=(8, 0))
        self._dash_refresh()

    def _dash_refresh(self) -> None:
        con = sqlite3.connect(str(self.db_path)); con.row_factory = sqlite3.Row
        try:
            runs = con.execute("SELECT status,global_done,global_total FROM runs ORDER BY id DESC LIMIT 5000").fetchall()
            tm = con.execute("SELECT COUNT(*) c FROM tm_segments").fetchone()["c"]
            qa_open = con.execute("SELECT COUNT(*) c FROM qa_findings WHERE status IN ('open','in_progress')").fetchone()["c"]
            qa_overdue = con.execute("SELECT COUNT(*) c FROM qa_findings WHERE escalation_status = 'overdue' AND status IN ('open','in_progress')").fetchone()["c"]
            qa_load_rows = con.execute(
                "SELECT COALESCE(NULLIF(assignee,''),'unassigned') a, COUNT(*) c FROM qa_findings WHERE status IN ('open','in_progress') GROUP BY a ORDER BY c DESC LIMIT 20"
            ).fetchall()
        finally:
            con.close()
        ok = sum(1 for r in runs if str(r["status"]) == "ok"); err = len(runs) - ok
        done = sum(int(r["global_done"] or 0) for r in runs); total = sum(int(r["global_total"] or 0) for r in runs)
        tok = int(done * 55)
        self.dash.delete("1.0", "end")
        self.dash.insert(
            "1.0",
            f"runs={len(runs)} ok={ok} err={err}\n"
            f"done={done} total={total}\n"
            f"TM={tm}\n"
            f"QA open={qa_open} overdue={qa_overdue}\n"
            f"~tokens={tok}\n~M-tokens={tok/1_000_000:.3f}\n\nQA load by assignee:\n",
        )
        for r in qa_load_rows:
            self.dash.insert("end", f"- {r['a']}: {r['c']}\n")

    def _build_plugins_tab(self, nb: ttk.Notebook) -> None:
        tab = ttk.Frame(nb, padding=8); nb.add(tab, text=self.gui.tr("studio.tab.plugins", "Provider Plugins"))
        bar = ttk.Frame(tab); bar.pack(fill="x")
        ttk.Button(bar, text="Refresh", command=self._plugins_refresh).pack(side="left")
        ttk.Button(bar, text="Create template", command=self._plugins_template).pack(side="left", padx=(8, 0))
        ttk.Button(bar, text="Rebuild manifest", command=self._plugins_rebuild_manifest).pack(side="left", padx=(8, 0))
        ttk.Button(bar, text="Validate all", command=self._plugins_validate).pack(side="left", padx=(8, 0))
        ttk.Button(bar, text="Health check selected", command=self._plugins_health_check).pack(side="left", padx=(8, 0))
        self.pl_list = tk.Listbox(tab); self.pl_list.pack(fill="both", expand=True, pady=(8, 0))
        self.pl_log = ScrolledText(tab, height=8, font=("Consolas", 9)); self.pl_log.pack(fill="x")
        self._plugins_refresh()

    def _plugins_dir(self) -> Path:
        d = self.gui.workdir / "providers"; d.mkdir(parents=True, exist_ok=True); return d

    def _plugins_refresh(self) -> None:
        self.pl_list.delete(0, "end")
        plugins, errors = load_plugins(self._plugins_dir())
        for pl in plugins:
            self.pl_list.insert("end", f"{pl.path.name} | {pl.name} | {pl.command_template}")
        for e in errors:
            self.pl_list.insert("end", f"INVALID | {e}")

    def _plugins_template(self) -> None:
        p = self._plugins_dir() / "example_provider.json"
        if not p.exists():
            p.write_text(
                json.dumps(
                    {
                        "name": "MyProvider",
                        "command_template": "python providers/my_provider.py --health --model {model} --prompt-file {prompt_file}",
                    },
                    ensure_ascii=False,
                    indent=2,
                ),
                encoding="utf-8",
            )
        self._plugins_refresh()

    def _plugins_validate(self) -> None:
        self.pl_log.delete("1.0", "end")
        plugins, errors = load_plugins(self._plugins_dir())
        integrity_errors = validate_plugins_integrity(plugins, cwd=self.gui.workdir)
        if errors:
            self.pl_log.insert("end", "Validation errors:\n")
            for e in errors:
                self.pl_log.insert("end", f"- {e}\n")
            self.pl_log.insert("end", "\n")
            self.pl_log.insert("end", self._plugins_policy_help() + "\n")
        else:
            self.pl_log.insert("end", "All plugin specs valid.\n")
        if integrity_errors:
            self.pl_log.insert("end", "Integrity errors:\n")
            for e in integrity_errors:
                self.pl_log.insert("end", f"- {e}\n")
            self.pl_log.insert("end", "\n")
            self.pl_log.insert("end", "Generate/update providers/manifest.json and retry.\n")
        else:
            self.pl_log.insert("end", "Integrity check passed.\n")
        self.pl_log.insert("end", f"Loaded plugins: {len(plugins)}\n")

    def _plugins_rebuild_manifest(self) -> None:
        try:
            mf = rebuild_provider_manifest(self._plugins_dir())
            self.pl_log.delete("1.0", "end")
            self.pl_log.insert("end", f"Manifest rebuilt: {mf}\n")
        except Exception as e:
            self.pl_log.delete("1.0", "end")
            self.pl_log.insert("end", f"Manifest rebuild error: {e}\n")

    def _plugins_health_check(self) -> None:
        sel = self.pl_list.curselection()
        if not sel:
            return
        line = self.pl_list.get(int(sel[0]))
        name = line.split("|", 1)[0].strip()
        p = self._plugins_dir() / name
        if not p.exists():
            return
        try:
            data = json.loads(p.read_text(encoding="utf-8"))
            cmd_tpl = str(data.get("command_template", ""))
            cmd = render_command(
                cmd_tpl,
                {
                    "model": self.gui.model_var.get().strip() or "model",
                    "prompt_file": self.gui.prompt_var.get().strip() or "prompt.txt",
                },
            )
            ok, out = plugin_health_check(cmd, cwd=self.gui.workdir, timeout_s=15)
            self.pl_log.delete("1.0", "end")
            self.pl_log.insert("end", f"Command: {cmd}\n")
            self.pl_log.insert("end", f"Result: {'OK' if ok else 'FAIL'}\n\n{out}")
        except Exception as e:
            self.pl_log.delete("1.0", "end")
            self.pl_log.insert("end", f"Health check error: {e}\n\n")
            self.pl_log.insert("end", self._plugins_policy_help())

    def _plugins_policy_help(self) -> str:
        return (
            "Allowed plugin command_template policy:\n"
            "- launcher: python|python.exe|py|py.exe\n"
            "- arg #2 must be relative .py script under providers/\n"
            "- absolute paths and '..' are blocked\n"
            "- supported placeholders: {model}, {prompt_file}, {input_file}, {output_file}\n"
            "- script must match SHA-256 in providers/manifest.json\n"
            "Example: python providers/my_provider.py --health --model {model} --prompt-file {prompt_file}"
        )

