#!/usr/bin/env python3
# -*- coding: utf-8 -*-

"""
TŁUMACZ EPUB: Google vs Ollama — różne mechanizmy optymalizacji per provider

Wymagania użytkownika:
- Podział mechanizmów: osobna polityka pod Google i osobna pod Ollama
- Google: reaguj na błędy (nie tylko 429) i rób rozsądne fallbacki
- Ollama: działa lokalnie; host może być stały (starter nie pyta)
- Postęp GLOBALNY całego projektu (cały EPUB), a nie tylko pliku/segmentu

Zależności:
  pip install requests lxml
"""

from __future__ import annotations

import argparse
import datetime
import hashlib
import json
import os
import re
import shutil
import time
import zipfile
from dataclasses import dataclass
from html.entities import name2codepoint
from pathlib import Path
from typing import Dict, Iterable, List, Optional, Tuple, Protocol

import requests
from requests.exceptions import ReadTimeout, ConnectionError as ReqConnectionError, HTTPError
from lxml import etree


XHTML_NS = "http://www.w3.org/1999/xhtml"

DEFAULT_BLOCK_TAGS = (
    "p", "li",
    "h1", "h2", "h3", "h4", "h5", "h6",
    "blockquote", "dd", "dt",
    "figcaption", "caption",
)

EXCLUDED_ANCESTORS = ("head", "script", "style", "svg", "math")


# ----------------------------
# LLM client interface
# ----------------------------

class LLMClient(Protocol):
    def resolve_model(self) -> str: ...
    def generate(self, prompt: str, model: str) -> str: ...


# ----------------------------
# Cache (resume)
# ----------------------------

def _cache_prefix(seg_id: str) -> Optional[str]:
    parts = seg_id.split("__")
    if len(parts) >= 2:
        return "__".join(parts[:2])
    return None


class Cache:
    """Cache .jsonl (resume) + bezpiecznik: fuzzy match po prefiksie segmentu.

    Jeśli hash segmentu się zmieni (np. drobna modyfikacja HTML), a rozdział i idx zostają,
    odzyskujemy tłumaczenie z cache po prefiksie <chapter>__<idx>.
    """

    def __init__(self, path: Optional[Path]):
        self.path = path
        self.data: Dict[str, str] = {}
        self.prefix_map: Dict[str, str] = {}
        self._load()

    def _load(self) -> None:
        if not self.path or not self.path.exists():
            return
        try:
            with self.path.open("r", encoding="utf-8") as f:
                for line in f:
                    line = line.strip()
                    if not line:
                        continue
                    try:
                        obj = json.loads(line)
                        sid = obj.get("id")
                        tr = obj.get("translation")
                        if isinstance(sid, str) and isinstance(tr, str):
                            self.data[sid] = tr
                            p = _cache_prefix(sid)
                            if p and p not in self.prefix_map:
                                self.prefix_map[p] = tr
                    except Exception:
                        continue
        except Exception:
            return

    def get(self, seg_id: str) -> Optional[str]:
        if seg_id in self.data:
            return self.data[seg_id]
        p = _cache_prefix(seg_id)
        if p and p in self.prefix_map:
            return self.prefix_map[p]
        return None

    def __setitem__(self, seg_id: str, translation: str) -> None:
        self.data[seg_id] = translation
        p = _cache_prefix(seg_id)
        if p and p not in self.prefix_map:
            self.prefix_map[p] = translation

    def append(self, seg_id: str, translation: str) -> None:
        if not self.path:
            return
        self.path.parent.mkdir(parents=True, exist_ok=True)
        rec = {"id": seg_id, "translation": translation}
        with self.path.open("a", encoding="utf-8") as f:
            f.write(json.dumps(rec, ensure_ascii=False) + "\n")


def load_cache(path: Optional[Path]) -> Cache:
    return Cache(path)


def stable_id(chapter_path: str, idx: int, inner: str) -> str:
    h = hashlib.sha1(inner.encode("utf-8", errors="replace")).hexdigest()[:10]
    safe_ch = re.sub(r"[^a-zA-Z0-9_\-./]", "_", chapter_path)
    return f"{safe_ch}__{idx:06d}__{h}"


# ----------------------------
# Ollama client
# ----------------------------

@dataclass(frozen=True)
class OllamaConfig:
    host: str = "http://127.0.0.1:11434"
    model: Optional[str] = None
    temperature: float = 0.1
    num_ctx: int = 8192
    num_predict: int = 2048
    timeout_s: int = 300
    max_attempts: int = 3
    backoff_s: Tuple[int, ...] = (5, 15, 30)


class OllamaClient:
    def __init__(self, cfg: OllamaConfig):
        self.cfg = cfg
        self.session = requests.Session()
        self.session.headers.update({"Content-Type": "application/json"})

    def resolve_model(self) -> str:
        if self.cfg.model:
            return self.cfg.model
        url = f"{self.cfg.host.rstrip('/')}/api/tags"
        r = self.session.get(url, timeout=self.cfg.timeout_s)
        r.raise_for_status()
        data = r.json()
        models = [m.get("name") for m in data.get("models", []) if m.get("name")]
        if not models:
            raise RuntimeError("Ollama /api/tags nie zwróciło żadnych modeli. Zrób: ollama pull <nazwa>.")
        return models[0]

    def generate(self, prompt: str, model: str) -> str:
        url = f"{self.cfg.host.rstrip('/')}/api/generate"
        payload = {
            "model": model,
            "prompt": prompt,
            "stream": False,
            "options": {
                "temperature": self.cfg.temperature,
                "num_ctx": self.cfg.num_ctx,
                "num_predict": self.cfg.num_predict,
            },
        }

        # eskalowane timeouty
        timeouts = [self.cfg.timeout_s]
        if self.cfg.max_attempts >= 2:
            timeouts.append(int(self.cfg.timeout_s * 1.5))
        if self.cfg.max_attempts >= 3:
            timeouts.append(int(self.cfg.timeout_s * 2))
        while len(timeouts) < self.cfg.max_attempts:
            timeouts.append(timeouts[-1])

        last_err: Optional[Exception] = None
        for attempt in range(1, self.cfg.max_attempts + 1):
            tmo = timeouts[attempt - 1]
            try:
                r = self.session.post(url, json=payload, timeout=tmo)
                r.raise_for_status()
                data = r.json()
                out = data.get("response", "")
                return out if isinstance(out, str) else str(out)
            except (ReadTimeout, ReqConnectionError) as e:
                last_err = e
                sleep_s = self.cfg.backoff_s[min(attempt - 1, len(self.cfg.backoff_s) - 1)]
                print(f"  [Ollama] timeout/conn error (próba {attempt}/{self.cfg.max_attempts}; timeout={tmo}s). "
                      f"Czekam {sleep_s}s i ponawiam...")
                time.sleep(sleep_s)
            except Exception as e:
                last_err = e
                break

        if last_err:
            raise last_err
        raise RuntimeError("Nieznany błąd w OllamaClient.generate().")


# ----------------------------
# Google client + error handling
# ----------------------------

class GoogleHTTPError(RuntimeError):
    def __init__(self, status_code: int, message: str, *, retry_after: Optional[float] = None):
        super().__init__(message)
        self.status_code = status_code
        self.retry_after = retry_after


@dataclass(frozen=True)
class GoogleConfig:
    api_key: str
    model: Optional[str] = None  # 'models/..' lub bez prefixu
    temperature: float = 0.1
    max_output_tokens: int = 2048
    timeout_s: int = 300

    # base pacing
    min_interval_s: float = 0.0

    # retry
    max_attempts: int = 3
    backoff_s: Tuple[int, ...] = (5, 15, 30)

    # adaptive throttling (reaguje na błędy 429/5xx)
    max_extra_throttle_s: float = 10.0
    throttle_step_s: float = 0.5


class GoogleClient:
    """Minimalny klient Gemini generateContent (v1beta) + rozszerzona reakcja na błędy."""

    def __init__(self, cfg: GoogleConfig):
        if not cfg.api_key or not cfg.api_key.strip():
            raise ValueError("Brak Google API key (x-goog-api-key).")
        self.cfg = cfg
        self.session = requests.Session()
        self.session.headers.update({
            "Content-Type": "application/json",
            "x-goog-api-key": cfg.api_key.strip(),
        })
        self.base_url = "https://generativelanguage.googleapis.com"
        self._next_allowed_ts = 0.0
        self._extra_throttle = 0.0

    def _norm_model(self, name: str) -> str:
        name = (name or "").strip()
        return name if name.startswith("models/") else f"models/{name}"

    def list_models(self) -> List[dict]:
        url = self.base_url + "/v1beta/models"
        r = self.session.get(url, timeout=self.cfg.timeout_s)
        r.raise_for_status()
        data = r.json()
        return data.get("models", []) or []

    def resolve_model(self) -> str:
        models = self.list_models()
        available = {m.get("name", "") for m in models if isinstance(m.get("name"), str)}

        def supports_generate(m: dict) -> bool:
            methods = m.get("supportedGenerationMethods") or []
            return isinstance(methods, list) and any(str(x).lower() == "generatecontent" for x in methods)

        available_generate = {m.get("name", "") for m in models if supports_generate(m) and isinstance(m.get("name"), str)}

        if self.cfg.model:
            chosen = self._norm_model(self.cfg.model)
            if chosen in available_generate:
                return chosen
            no_prefix = chosen.replace("models/", "", 1)
            for x in available_generate:
                if x.endswith(no_prefix):
                    return x
            if chosen in available:
                raise RuntimeError(f"Model '{chosen}' jest widoczny dla klucza, ale nie wspiera generateContent.")
            raise RuntimeError(f"Model '{chosen}' nie jest dostępny dla tego klucza API.")
        # jeżeli user nie podał modelu, bierz pierwszy wspierający generateContent
        for m in models:
            if supports_generate(m):
                name = m.get("name")
                if isinstance(name, str) and name:
                    return name
        raise RuntimeError("Nie znaleziono żadnego modelu wspierającego generateContent dla tego klucza.")

    def _sleep_until_allowed(self) -> None:
        base = float(getattr(self.cfg, "min_interval_s", 0.0) or 0.0)
        now = time.time()
        wait = self._next_allowed_ts - now
        if wait > 0:
            time.sleep(wait)
        # dodatkowe throttling reagujące na błędy
        if self._extra_throttle > 0:
            time.sleep(self._extra_throttle)

    def _after_request(self) -> None:
        base = float(getattr(self.cfg, "min_interval_s", 0.0) or 0.0)
        self._next_allowed_ts = time.time() + base

    def _bump_throttle(self) -> None:
        # rośnie do max_extra_throttle_s, skok throttle_step_s
        step = float(self.cfg.throttle_step_s or 0.5)
        max_t = float(self.cfg.max_extra_throttle_s or 10.0)
        self._extra_throttle = min(max_t, self._extra_throttle + step)

    def _decay_throttle(self) -> None:
        # po sukcesie zmniejszamy throttling
        self._extra_throttle = max(0.0, self._extra_throttle - (self.cfg.throttle_step_s or 0.5))

    def generate(self, prompt: str, model: str) -> str:
        url = self.base_url + f"/v1beta/{self._norm_model(model)}:generateContent"
        payload = {
            "contents": [{"role": "user", "parts": [{"text": prompt}]}],
            "generationConfig": {
                "temperature": self.cfg.temperature,
                "maxOutputTokens": self.cfg.max_output_tokens,
            },
        }

        last_err: Optional[Exception] = None
        for attempt in range(1, self.cfg.max_attempts + 1):
            try:
                self._sleep_until_allowed()
                r = self.session.post(url, json=payload, timeout=self.cfg.timeout_s)

                # Błędy, na które reagujemy retry + backoff:
                # 429 (quota/rate limit), 408/409 (sporadycznie), 500-504 (chwilowe)
                if r.status_code in (408, 409, 429, 500, 502, 503, 504) and attempt < self.cfg.max_attempts:
                    self._bump_throttle()
                    base_sleep = self.cfg.backoff_s[min(attempt - 1, len(self.cfg.backoff_s) - 1)]
                    retry_after = r.headers.get("Retry-After")
                    sleep_s = float(base_sleep)
                    ra_val = None
                    if retry_after:
                        try:
                            ra_val = float(str(retry_after).strip())
                            sleep_s = max(sleep_s, ra_val)
                        except Exception:
                            pass
                    print(f"  [Google] HTTP {r.status_code} (próba {attempt}/{self.cfg.max_attempts}). "
                          f"Czekam {sleep_s:g}s i ponawiam...")
                    time.sleep(sleep_s)
                    self._after_request()
                    continue

                if r.status_code >= 400:
                    # Nie retry'ujemy w ciemno na inne 4xx; przekaż do warstwy wyżej (batch splitter/fallback)
                    retry_after = None
                    ra = r.headers.get("Retry-After")
                    if ra:
                        try:
                            retry_after = float(str(ra).strip())
                        except Exception:
                            pass
                    body = ""
                    try:
                        body = r.text[:800]
                    except Exception:
                        body = ""
                    raise GoogleHTTPError(
                        r.status_code,
                        f"Google API HTTP {r.status_code}: {body}",
                        retry_after=retry_after,
                    )

                self._after_request()
                data = r.json()
                cands = data.get("candidates") or []
                if not cands:
                    self._decay_throttle()
                    return ""
                content = (cands[0].get("content") or {})
                parts = content.get("parts") or []
                texts: List[str] = []
                for p in parts:
                    t = p.get("text")
                    if isinstance(t, str):
                        texts.append(t)
                self._decay_throttle()
                return "".join(texts).strip()

            except (ReadTimeout, ReqConnectionError) as e:
                last_err = e
                if attempt >= self.cfg.max_attempts:
                    break
                self._bump_throttle()
                sleep_s = self.cfg.backoff_s[min(attempt - 1, len(self.cfg.backoff_s) - 1)]
                print(f"  [Google] timeout/conn error (próba {attempt}/{self.cfg.max_attempts}). "
                      f"Czekam {sleep_s}s i ponawiam...")
                time.sleep(sleep_s)
                self._after_request()
            except GoogleHTTPError as e:
                last_err = e
                # dla 4xx (poza 408/409/429) nie robimy retry tutaj; warstwa batch może podzielić payload
                break
            except Exception as e:
                last_err = e
                break

        if last_err:
            raise last_err
        raise RuntimeError("Nieznany błąd w GoogleClient.generate().")


# ----------------------------
# Glossary slicing (opcjonalne)
# ----------------------------

@dataclass
class GlossaryEntry:
    canonical: str
    variants: List[str]
    note: str


def _split_variants(v: str) -> List[str]:
    out: List[str] = []
    for part in re.split(r"[;,/]\s*", v.strip()):
        p = part.strip()
        if p:
            out.append(p)
    return out


def load_glossary(path: Path) -> Dict[str, List[GlossaryEntry]]:
    text = path.read_text(encoding="utf-8", errors="replace")
    entry_re = re.compile(r"^\s*([^(\n]{2,}?)\s*\(EN:\s*([^)]+)\)\s*(.*)$", re.UNICODE)

    entries: List[GlossaryEntry] = []
    for line in text.splitlines():
        m = entry_re.match(line)
        if not m:
            continue
        canonical = m.group(1).strip()
        variants_raw = m.group(2).strip()
        tail = m.group(3).strip()
        variants = _split_variants(variants_raw)
        if canonical and variants:
            entries.append(GlossaryEntry(canonical=canonical, variants=variants, note=tail))

    index: Dict[str, List[GlossaryEntry]] = {}
    for e in entries:
        for v in e.variants:
            fw = v.split()[0].lower()
            index.setdefault(fw, []).append(e)
    return index


def pick_glossary_snippet(text: str, index: Dict[str, List[GlossaryEntry]], max_entries: int = 30) -> str:
    seg_l = text.lower()
    tokens = set(re.findall(r"[a-zA-Z][a-zA-Z'\-]{2,}", seg_l))

    chosen: List[GlossaryEntry] = []
    seen_can = set()

    for t in tokens:
        cand = index.get(t)
        if not cand:
            continue
        for e in cand:
            if e.canonical in seen_can:
                continue
            if any(v.lower() in seg_l for v in e.variants):
                chosen.append(e)
                seen_can.add(e.canonical)
                if len(chosen) >= max_entries:
                    break
        if len(chosen) >= max_entries:
            break

    if not chosen:
        return ""

    lines = ["Terminologia wiążąca (użyj dokładnie tych form):"]
    for e in chosen:
        v = "; ".join(e.variants[:6])
        if e.note:
            lines.append(f"- {e.canonical} (EN: {v}) — {e.note}")
        else:
            lines.append(f"- {e.canonical} (EN: {v})")
    return "\n".join(lines).strip()


# ----------------------------
# EPUB parsing utilities
# ----------------------------

def decode_bytes(b: bytes) -> str:
    for enc in ("utf-8", "utf-8-sig", "utf-16", "cp1250", "latin-1"):
        try:
            return b.decode(enc)
        except UnicodeDecodeError:
            pass
    return b.decode("utf-8", errors="replace")


def find_opf_path(zf: zipfile.ZipFile) -> str:
    container_xml = zf.read("META-INF/container.xml")
    root = etree.fromstring(container_xml)
    rootfile = root.find(".//{*}rootfile")
    if rootfile is None:
        raise ValueError("Nie znaleziono rootfile w META-INF/container.xml.")
    opf_path = rootfile.get("full-path")
    if not opf_path:
        raise ValueError("Brak atrybutu full-path w container.xml.")
    return opf_path.replace("\\", "/")


def parse_spine_and_manifest(zf: zipfile.ZipFile, opf_path: str) -> Tuple[Dict[str, Tuple[str, str]], List[str]]:
    opf_txt = decode_bytes(zf.read(opf_path))
    root = etree.fromstring(opf_txt.encode("utf-8"))

    manifest: Dict[str, Tuple[str, str]] = {}
    for item in root.findall(".//{*}manifest/{*}item"):
        item_id = item.get("id")
        href = item.get("href")
        media_type = item.get("media-type", "")
        if item_id and href:
            manifest[item_id] = (href, media_type)

    spine: List[str] = []
    for itemref in root.findall(".//{*}spine/{*}itemref"):
        idref = itemref.get("idref")
        if idref:
            spine.append(idref)

    if not manifest or not spine:
        raise ValueError("Nie udało się odczytać manifest/spine z OPF.")
    return manifest, spine


def normalize_epub_path(opf_path: str, href: str) -> str:
    href = href.split("#", 1)[0].replace("\\", "/")
    base_dir = opf_path.rsplit("/", 1)[0] if "/" in opf_path else ""
    if base_dir:
        return f"{base_dir}/{href}".replace("//", "/")
    return href


# ----------------------------
# XHTML helpers
# ----------------------------

def _xpath_translatable(block_tags: Iterable[str]) -> str:
    tags_clause = " or ".join([f'local-name()="{t}"' for t in block_tags])
    excl_clause = " or ".join([f'local-name()="{t}"' for t in EXCLUDED_ANCESTORS])
    return f'//*[( {tags_clause} ) and not(ancestor::*[( {excl_clause} )])]'


def inner_xml(el: etree._Element) -> str:
    s = etree.tostring(el, encoding="unicode", method="xml")
    m = re.match(r"^<[^>]+>(.*)</[^>]+>\s*$", s, flags=re.DOTALL)
    return m.group(1) if m else ""


def has_translatable_text(el: etree._Element) -> bool:
    txt = "".join(el.itertext()).strip()
    return bool(re.search(r"[A-Za-zĄĆĘŁŃÓŚŹŻąćęłńóśźż]", txt))


def html_entities_to_numeric(s: str) -> str:
    def repl(m: re.Match) -> str:
        name = m.group(1)
        cp = name2codepoint.get(name)
        return f"&#{cp};" if cp is not None else m.group(0)
    return re.sub(r"&([A-Za-z][A-Za-z0-9]+);", repl, s)


def replace_inner_xml(el: etree._Element, new_inner: str) -> None:
    for c in list(el):
        el.remove(c)
    el.text = None

    frag = new_inner.strip()
    try:
        wrapper = etree.fromstring(
            f'<div xmlns="{XHTML_NS}">{html_entities_to_numeric(frag)}</div>'.encode("utf-8"),
            parser=etree.XMLParser(recover=True),
        )
    except Exception:
        el.text = frag
        return

    el.text = wrapper.text
    for c in list(wrapper):
        wrapper.remove(c)
        el.append(c)


# ----------------------------
# Prompt + parsing output (HYBRYDA)
# ----------------------------

def sanitize_model_output(s: str) -> str:
    out = (s or "").strip()
    if out.startswith("```"):
        out = re.sub(r"^```[a-zA-Z0-9_-]*\s*", "", out)
        out = re.sub(r"\s*```$", "", out)
    out = re.sub(r"^\s*(Tłumaczenie|Translation)\s*:\s*", "", out, flags=re.IGNORECASE)
    return out.strip()


def build_batch_payload(seg_items: List[Tuple[str, str]]) -> str:
    parts = [f'<batch xmlns="{XHTML_NS}">']
    for sid, inner in seg_items:
        inner_norm = html_entities_to_numeric(inner)
        parts.append(f'<seg id="{sid}">{inner_norm}</seg>')
    parts.append("</batch>")
    return "\n".join(parts)


def build_batch_prompt(base_prompt: str, glossary_snippet: str, batch_xml: str) -> str:
    parts = [base_prompt.strip()]
    if glossary_snippet.strip():
        parts.append(glossary_snippet.strip())
    parts.append(
        "Zadanie:\n"
        "Przetłumacz na język polski PONIŻSZY XML (XHTML).\n"
        "Wewnątrz <seg> znajdują się fragmenty (wnętrza akapitów). Każdy <seg> tłumacz jako całość.\n"
        "Wymagania krytyczne:\n"
        "- ZACHOWAJ DOKŁADNIE strukturę i tagi: <batch>, <seg id=\"...\"> oraz WSZYSTKIE tagi XHTML wewnątrz.\n"
        "- Nie zmieniaj ani nie usuwaj atrybutów, w tym id w <seg>.\n"
        "- Nie dodawaj żadnego komentarza/metatekstu.\n"
        "- Zwróć WYŁĄCZNIE wynikowy XML <batch>...</batch>.\n"
        "\nWEJŚCIE:\n"
        f"{batch_xml}\n"
    )
    return "\n\n".join(parts).strip() + "\n"


def debug_dump(debug_dir: Optional[Path], prefix: str, prompt: str, response: str) -> None:
    if debug_dir is None:
        return
    debug_dir.mkdir(parents=True, exist_ok=True)
    (debug_dir / f"{prefix}_prompt.txt").write_text(prompt, encoding="utf-8", errors="replace")
    (debug_dir / f"{prefix}_response.txt").write_text(response or "", encoding="utf-8", errors="replace")


def parse_batch_response(xml_text: str) -> Dict[str, str]:
    raw = sanitize_model_output(xml_text).strip()
    if not raw:
        raise RuntimeError("Pusta odpowiedź z modelu (response=='' po sanitize).")

    m = re.search(r"(<batch\b[\s\S]*?</batch>)", raw, flags=re.IGNORECASE)
    if m:
        raw = m.group(1).strip()

    raw = html_entities_to_numeric(raw)
    parser = etree.XMLParser(recover=True, huge_tree=True)
    root = etree.fromstring(raw.encode("utf-8", errors="replace"), parser=parser)
    if root is None:
        raise RuntimeError("Nie udało się sparsować odpowiedzi modelu jako XML (root=None).")

    if etree.QName(root).localname.lower() != "batch":
        batch = root.find(".//{*}batch")
        if batch is None:
            raise RuntimeError("Odpowiedź nie zawiera elementu <batch>.")
        root = batch

    out: Dict[str, str] = {}
    for seg in root.findall(".//{*}seg"):
        sid = seg.get("id")
        if not sid:
            continue
        out[sid] = inner_xml(seg)

    if not out:
        raise RuntimeError("Nie znaleziono żadnych <seg id=...> w <batch>.")
    return out


# ----------------------------
# HYBRID chunking
# ----------------------------

@dataclass
class Segment:
    idx: int
    el: etree._Element
    seg_id: str
    inner: str
    plain: str


def chunk_segments(segments: List[Segment], batch_max_chars: int, batch_max_segs: int) -> Iterable[List[Segment]]:
    batch: List[Segment] = []
    size = 0
    for seg in segments:
        seg_size = len(seg.inner) + 64
        if batch and ((size + seg_size) > batch_max_chars or len(batch) >= batch_max_segs):
            yield batch
            batch = []
            size = 0

        batch.append(seg)
        size += seg_size

        if len(batch) == 1 and seg_size > batch_max_chars:
            yield batch
            batch = []
            size = 0
    if batch:
        yield batch


# ----------------------------
# File writing (atomic)
# ----------------------------

def write_epub_atomic(
    input_epub: Path,
    output_epub: Path,
    modified: Dict[str, bytes],
    *,
    make_backup: bool = True,
    backup_keep: int = 5,
) -> Path:
    output_epub.parent.mkdir(parents=True, exist_ok=True)
    tmp = output_epub.with_name(output_epub.name + ".tmp")

    def _write(to_path: Path) -> None:
        with zipfile.ZipFile(input_epub, "r") as zin, zipfile.ZipFile(to_path, "w") as zout:
            try:
                mimetype_bytes = zin.read("mimetype")
                zinfo = zipfile.ZipInfo("mimetype")
                zinfo.compress_type = zipfile.ZIP_STORED
                zout.writestr(zinfo, mimetype_bytes)
            except KeyError:
                pass

            for info in zin.infolist():
                name = info.filename
                if name == "mimetype":
                    continue
                data = modified.get(name)
                if data is None:
                    data = zin.read(name)
                zi = zipfile.ZipInfo(name)
                zi.date_time = info.date_time
                zi.external_attr = info.external_attr
                zi.compress_type = zipfile.ZIP_DEFLATED
                zout.writestr(zi, data)

    try:
        _write(tmp)

        if make_backup and output_epub.exists():
            ts = datetime.datetime.now().strftime("%Y%m%d-%H%M%S")
            backup = output_epub.with_name(f"{output_epub.stem}.bak-{ts}{output_epub.suffix}")
            try:
                shutil.copy2(output_epub, backup)
                backups = sorted(output_epub.parent.glob(f"{output_epub.stem}.bak-*{output_epub.suffix}"))
                if backup_keep > 0 and len(backups) > backup_keep:
                    for old in backups[: len(backups) - backup_keep]:
                        try:
                            old.unlink()
                        except Exception:
                            pass
            except Exception:
                pass

        os.replace(tmp, output_epub)
        return output_epub
    except PermissionError:
        partial = output_epub.with_name(output_epub.stem + ".partial" + output_epub.suffix)
        _write(partial)
        try:
            if tmp.exists():
                tmp.unlink()
        except Exception:
            pass
        return partial
    finally:
        try:
            if tmp.exists():
                tmp.unlink()
        except Exception:
            pass


# ----------------------------
# Provider-specific helpers
# ----------------------------

def is_google_retriable_error(e: Exception) -> bool:
    # GoogleClient już retry'uje 408/409/429/5xx; tu decydujemy o fallbackach i splitach.
    if isinstance(e, GoogleHTTPError):
        return e.status_code in (408, 409, 429, 500, 502, 503, 504)
    if isinstance(e, (ReadTimeout, ReqConnectionError)):
        return True
    return False


def is_google_too_large(e: Exception) -> bool:
    # Zbyt duże żądanie / payload / model odrzuca:
    if isinstance(e, GoogleHTTPError):
        return e.status_code in (400, 413)
    # czasem API zwraca 400 z message o przekroczeniu limitu; to łapiemy heurystycznie
    s = str(e).lower()
    return ("request entity too large" in s) or ("payload" in s and "too large" in s) or ("exceeds" in s and "limit" in s)


# ----------------------------
# Translation routines
# ----------------------------

def translate_single_segment(
    llm: LLMClient,
    model: str,
    base_prompt: str,
    seg: Segment,
    glossary_index: Optional[Dict[str, List[GlossaryEntry]]],
    debug_dir: Optional[Path],
    debug_prefix: str,
) -> str:
    glossary_snip = ""
    if glossary_index is not None:
        glossary_snip = pick_glossary_snippet(seg.plain, glossary_index)

    batch_xml = build_batch_payload([(seg.seg_id, seg.inner)])
    prompt = build_batch_prompt(base_prompt, glossary_snip, batch_xml)

    resp = llm.generate(prompt, model=model)
    try:
        mapping = parse_batch_response(resp)
    except Exception:
        debug_dump(debug_dir, debug_prefix, prompt, resp)
        raise

    tr = (mapping.get(seg.seg_id) or "").strip()
    if not tr:
        debug_dump(debug_dir, debug_prefix, prompt, resp)
        raise RuntimeError(f"Pusty wynik tłumaczenia (single) dla segmentu: {seg.seg_id}")
    return tr


def translate_batch_with_google_strategy(
    llm: LLMClient,
    model: str,
    base_prompt: str,
    batch: List[Segment],
    glossary_index: Optional[Dict[str, List[GlossaryEntry]]],
    debug_dir: Optional[Path],
    debug_prefix: str,
    *,
    sleep_s: float,
    max_split_depth: int = 6,
) -> Dict[str, str]:
    """
    Strategia pod Google:
    - Spróbuj batch
    - Jeśli błąd "too large" (400/413) lub parsing/kompletność padnie -> dziel batch na pół i próbuj dalej
    - Jeśli 429/5xx/timeout -> retry klienta; jeśli nadal błąd -> podziel batch (mniejsze requesty)
    - Ostatecznie fallback per-segment
    """
    if not batch:
        return {}

    def _attempt_translate(batch_local: List[Segment], depth: int) -> Dict[str, str]:
        seg_items = [(s.seg_id, s.inner) for s in batch_local]
        batch_xml = build_batch_payload(seg_items)

        glossary_snip = ""
        if glossary_index is not None:
            all_plain = "\n".join(s.plain for s in batch_local)
            glossary_snip = pick_glossary_snippet(all_plain, glossary_index)

        prompt = build_batch_prompt(base_prompt, glossary_snip, batch_xml)

        resp = ""
        try:
            resp = llm.generate(prompt, model=model)
            mapping = parse_batch_response(resp)

            # brakujące segmenty -> per-seg retry
            missing = [s for s in batch_local if s.seg_id not in mapping or not (mapping[s.seg_id] or "").strip()]
            if missing:
                debug_dump(debug_dir, f"{debug_prefix}_missing_d{depth}", prompt, resp)
                for s in missing:
                    if sleep_s > 0:
                        time.sleep(sleep_s)
                    mapping[s.seg_id] = translate_single_segment(
                        llm=llm, model=model, base_prompt=base_prompt, seg=s,
                        glossary_index=glossary_index, debug_dir=debug_dir,
                        debug_prefix=f"{debug_prefix}__retry_{s.idx:06d}",
                    )
            return mapping

        except Exception as e:
            debug_dump(debug_dir, f"{debug_prefix}_err_d{depth}", prompt, resp)

            # Jeśli za duże: dziel
            if is_google_too_large(e) and len(batch_local) > 1 and depth < max_split_depth:
                mid = len(batch_local) // 2
                left = batch_local[:mid]
                right = batch_local[mid:]
                print(f"  [Google] batch too large / 400/413 -> split {len(batch_local)} => {len(left)} + {len(right)}")
                out = {}
                out.update(_attempt_translate(left, depth + 1))
                if sleep_s > 0:
                    time.sleep(sleep_s)
                out.update(_attempt_translate(right, depth + 1))
                return out

            # Błędy chwilowe albo parsing: jeśli da się dzielić, dziel; inaczej per-segment
            if len(batch_local) > 1 and depth < max_split_depth and (is_google_retriable_error(e) or True):
                mid = len(batch_local) // 2
                left = batch_local[:mid]
                right = batch_local[mid:]
                print(f"  [Google] batch error -> split {len(batch_local)} => {len(left)} + {len(right)} (err={type(e).__name__})")
                out = {}
                out.update(_attempt_translate(left, depth + 1))
                if sleep_s > 0:
                    time.sleep(sleep_s)
                out.update(_attempt_translate(right, depth + 1))
                return out

            # per-segment fallback
            print(f"  [Google] fallback per-segment dla batch {len(batch_local)} (err={type(e).__name__})")
            out = {}
            for s in batch_local:
                if sleep_s > 0:
                    time.sleep(sleep_s)
                out[s.seg_id] = translate_single_segment(
                    llm=llm, model=model, base_prompt=base_prompt, seg=s,
                    glossary_index=glossary_index, debug_dir=debug_dir,
                    debug_prefix=f"{debug_prefix}__single_{s.idx:06d}",
                )
            return out

    return _attempt_translate(batch, depth=0)


def translate_batch_with_ollama_strategy(
    llm: LLMClient,
    model: str,
    base_prompt: str,
    batch: List[Segment],
    glossary_index: Optional[Dict[str, List[GlossaryEntry]]],
    debug_dir: Optional[Path],
    debug_prefix: str,
    *,
    sleep_s: float,
) -> Dict[str, str]:
    """
    Strategia pod Ollama:
    - Spróbuj batch
    - Przy timeout/conn/parsing -> fallback per-segment (lokalnie zwykle szybkie i stabilne)
    - Retry na poziomie klienta (OllamaClient) już istnieje
    """
    seg_items = [(s.seg_id, s.inner) for s in batch]
    batch_xml = build_batch_payload(seg_items)

    glossary_snip = ""
    if glossary_index is not None:
        all_plain = "\n".join(s.plain for s in batch)
        glossary_snip = pick_glossary_snippet(all_plain, glossary_index)

    prompt = build_batch_prompt(base_prompt, glossary_snip, batch_xml)
    resp = ""
    try:
        resp = llm.generate(prompt, model=model)
        mapping = parse_batch_response(resp)
    except Exception as e:
        debug_dump(debug_dir, f"{debug_prefix}_batch_error", prompt, resp)
        print(f"  [Ollama] batch error ({type(e).__name__}) -> per-segment")
        mapping = {}
        for s in batch:
            if sleep_s > 0:
                time.sleep(sleep_s)
            mapping[s.seg_id] = translate_single_segment(
                llm=llm, model=model, base_prompt=base_prompt, seg=s,
                glossary_index=glossary_index, debug_dir=debug_dir,
                debug_prefix=f"{debug_prefix}__single_{s.idx:06d}",
            )

    missing = [s for s in batch if s.seg_id not in mapping or not (mapping[s.seg_id] or "").strip()]
    if missing:
        debug_dump(debug_dir, f"{debug_prefix}_missing", prompt, resp)
        print(f"  [Ollama] brak {len(missing)} segmentów -> per-segment retry")
        for s in missing:
            if sleep_s > 0:
                time.sleep(sleep_s)
            mapping[s.seg_id] = translate_single_segment(
                llm=llm, model=model, base_prompt=base_prompt, seg=s,
                glossary_index=glossary_index, debug_dir=debug_dir,
                debug_prefix=f"{debug_prefix}__retry_{s.idx:06d}",
            )
    return mapping


# ----------------------------
# Prepass: GLOBAL progress counts
# ----------------------------

@dataclass
class ProjectTotals:
    total_segments: int
    cached_segments: int
    to_translate_segments: int
    spine_total_files: int


def compute_project_totals(
    input_epub: Path,
    cache: Cache,
    block_tags: Tuple[str, ...],
) -> ProjectTotals:
    total = 0
    cached = 0
    with zipfile.ZipFile(input_epub, "r") as zin:
        opf_path = find_opf_path(zin)
        manifest, spine = parse_spine_and_manifest(zin, opf_path)
        for item_id in spine:
            href, media_type = manifest.get(item_id, ("", ""))
            if not href:
                continue
            if "xhtml" not in media_type and "html" not in media_type:
                continue
            chapter_path = normalize_epub_path(opf_path, href)
            try:
                raw = zin.read(chapter_path)
            except KeyError:
                continue

            parser = etree.XMLParser(recover=True, resolve_entities=False, huge_tree=True)
            try:
                root = etree.fromstring(raw, parser=parser)
            except Exception:
                continue

            xpath = _xpath_translatable(block_tags)
            elements = root.xpath(xpath)

            for i, el in enumerate(elements):
                if not has_translatable_text(el):
                    continue
                seg_inner = inner_xml(el).strip()
                if not seg_inner:
                    continue
                sid = stable_id(chapter_path, i, seg_inner)
                total += 1
                if cache.get(sid) is not None:
                    cached += 1

        return ProjectTotals(
            total_segments=total,
            cached_segments=cached,
            to_translate_segments=max(0, total - cached),
            spine_total_files=len(spine),
        )


# ----------------------------
# Main translation routine
# ----------------------------

def translate_epub(
    input_epub: Path,
    output_epub: Path,
    base_prompt: str,
    llm: LLMClient,
    provider: str,
    glossary_index: Optional[Dict[str, List[GlossaryEntry]]] = None,
    cache_path: Optional[Path] = None,
    block_tags: Tuple[str, ...] = DEFAULT_BLOCK_TAGS,
    batch_max_chars: int = 12000,
    batch_max_segs: int = 6,
    sleep_s: float = 0.0,
    debug_dir: Optional[Path] = None,
    checkpoint_every_files: int = 0,
) -> None:
    model = llm.resolve_model()
    cache = load_cache(cache_path)
    modified: Dict[str, bytes] = {}

    totals = compute_project_totals(input_epub, cache, block_tags)
    global_total = totals.total_segments
    global_cached = totals.cached_segments
    global_to_translate = totals.to_translate_segments

    # Liczniki postępu globalnego:
    global_done = global_cached  # cache "zrobione" od razu
    global_new = 0

    print("\n=== POSTĘP GLOBALNY (CAŁY EPUB) ===")
    print(f"  Segmenty łącznie:     {global_total}")
    print(f"  Segmenty z cache:     {global_cached}")
    print(f"  Segmenty do tłumacz.: {global_to_translate}")
    if global_total > 0:
        print(f"  Start progress:       {global_done}/{global_total} ({(global_done/global_total)*100:.1f}%)")
    print("===================================\n")

    def _print_global_progress(chapter_path: str, extra: str = "") -> None:
        if global_total <= 0:
            return
        pct = (global_done / global_total) * 100.0
        msg = f"GLOBAL {global_done}/{global_total} ({pct:.1f}%) | {chapter_path}"
        if extra:
            msg += f" | {extra}"
        print(msg)

    with zipfile.ZipFile(input_epub, "r") as zin:
        opf_path = find_opf_path(zin)
        manifest, spine = parse_spine_and_manifest(zin, opf_path)

        spine_total = len(spine)

        for spine_idx, item_id in enumerate(spine, 1):
            href, media_type = manifest.get(item_id, ("", ""))
            if not href:
                continue
            if "xhtml" not in media_type and "html" not in media_type:
                continue

            chapter_path = normalize_epub_path(opf_path, href)
            try:
                raw = zin.read(chapter_path)
            except KeyError:
                continue

            parser = etree.XMLParser(recover=True, resolve_entities=False, huge_tree=True)
            try:
                root = etree.fromstring(raw, parser=parser)
            except Exception:
                continue

            xpath = _xpath_translatable(block_tags)
            elements = root.xpath(xpath)

            segs: List[Segment] = []
            chapter_cache = 0

            # cache + lista do tłumaczenia
            for i, el in enumerate(elements):
                if not has_translatable_text(el):
                    continue
                seg_inner = inner_xml(el).strip()
                if not seg_inner:
                    continue

                seg_plain = etree.tostring(el, encoding="unicode", method="text")
                sid = stable_id(chapter_path, i, seg_inner)

                tr_cached = cache.get(sid)
                if tr_cached is not None:
                    replace_inner_xml(el, tr_cached)
                    chapter_cache += 1
                else:
                    segs.append(Segment(idx=i, el=el, seg_id=sid, inner=seg_inner, plain=seg_plain))

            chapter_new_total = len(segs)

            if chapter_cache > 0:
                # global_done nie zwiększamy tutaj, bo cache policzyliśmy w prepass jako global_cached.
                _print_global_progress(chapter_path, extra=f"spine {spine_idx}/{spine_total} | cache w pliku: {chapter_cache}")

            if chapter_new_total == 0:
                # jeśli cache zmienił DOM, zapisujemy ten plik
                if chapter_cache > 0:
                    out_bytes = etree.tostring(root, encoding="utf-8", xml_declaration=True, pretty_print=False)
                    modified[chapter_path] = out_bytes
                continue

            print(f"\n[{spine_idx}/{spine_total}] {chapter_path}: do przetłumaczenia {chapter_new_total} segmentów (cache w pliku: {chapter_cache})")

            changed = False
            chapter_new_done = 0

            for batch_no, batch in enumerate(chunk_segments(segs, batch_max_chars, batch_max_segs), 1):
                debug_prefix = f"{Path(chapter_path).stem}_b{batch_no:04d}"

                if provider == "google":
                    mapping = translate_batch_with_google_strategy(
                        llm=llm, model=model, base_prompt=base_prompt,
                        batch=batch, glossary_index=glossary_index,
                        debug_dir=debug_dir, debug_prefix=debug_prefix,
                        sleep_s=sleep_s,
                    )
                else:
                    mapping = translate_batch_with_ollama_strategy(
                        llm=llm, model=model, base_prompt=base_prompt,
                        batch=batch, glossary_index=glossary_index,
                        debug_dir=debug_dir, debug_prefix=debug_prefix,
                        sleep_s=sleep_s,
                    )

                # wstrzyknięcie + cache
                for s in batch:
                    tr_inner = (mapping.get(s.seg_id) or "").strip()
                    if not tr_inner:
                        raise RuntimeError(f"Pusty wynik tłumaczenia po fallbacku dla segmentu: {s.seg_id}")
                    replace_inner_xml(s.el, tr_inner)
                    cache[s.seg_id] = tr_inner
                    cache.append(s.seg_id, tr_inner)
                    global_new += 1
                    global_done += 1
                    chapter_new_done += 1
                    changed = True

                _print_global_progress(
                    chapter_path,
                    extra=f"spine {spine_idx}/{spine_total} | batch {batch_no} | nowe w pliku: {chapter_new_done}/{chapter_new_total}"
                )

                if sleep_s > 0:
                    time.sleep(sleep_s)

            if changed:
                out_bytes = etree.tostring(root, encoding="utf-8", xml_declaration=True, pretty_print=False)
                modified[chapter_path] = out_bytes

            if checkpoint_every_files and (spine_idx % checkpoint_every_files == 0):
                wip_out = output_epub.with_name(output_epub.stem + ".wip" + output_epub.suffix)
                written_to = write_epub_atomic(input_epub, wip_out, modified, make_backup=False)
                print(f"  [CHECKPOINT] zapisano: {written_to} (po pliku {spine_idx}/{spine_total})")

    written_to = write_epub_atomic(input_epub, output_epub, modified, make_backup=True)

    print("\n=== KONIEC ===")
    print(f"  Nowe tłumaczenia: {global_new}")
    print(f"  Segmenty łącznie: {global_total}")
    if global_total > 0:
        print(f"  Final progress:   {global_done}/{global_total} ({(global_done/global_total)*100:.1f}%)")
    print(f"  Output EPUB:      {written_to}")
    if cache_path:
        print(f"  Cache:            {cache_path}")
    if debug_dir is not None:
        print(f"  Debug dir:        {debug_dir}")


# ----------------------------
# CLI
# ----------------------------

def main() -> int:
    ap = argparse.ArgumentParser(description="EPUB -> LLM (Ollama lub Google Gemini API) -> EPUB (hybryda, global progress)")
    ap.add_argument("input_epub", type=Path)
    ap.add_argument("output_epub", type=Path)

    ap.add_argument("--provider", choices=["ollama", "google"], required=True)
    ap.add_argument("--api-key", type=str, default=None, help="Google API key (wymagany dla --provider=google)")
    ap.add_argument("--prompt", type=Path, required=True)
    ap.add_argument("--glossary", type=Path, default=None)
    ap.add_argument("--no-glossary", action="store_true")
    ap.add_argument("--model", type=str, required=True)
    ap.add_argument("--host", type=str, default="http://127.0.0.1:11434")  # starter nie pyta, ale CLI zostaje
    ap.add_argument("--temperature", type=float, default=0.1)
    ap.add_argument("--num-ctx", type=int, default=8192)
    ap.add_argument("--num-predict", type=int, default=2048)
    ap.add_argument("--timeout", type=int, default=300)
    ap.add_argument("--cache", type=Path, default=None)
    ap.add_argument("--sleep", type=float, default=0.0)
    ap.add_argument("--batch-max-chars", type=int, required=True)
    ap.add_argument("--batch-max-segs", type=int, required=True)
    ap.add_argument("--checkpoint-every-files", type=int, default=0)
    ap.add_argument("--debug-dir", type=Path, default=Path("debug"))
    ap.add_argument("--attempts", type=int, default=3)
    ap.add_argument("--backoff", type=str, default="5,15,30")
    ap.add_argument("--tags", type=str, default=",".join(DEFAULT_BLOCK_TAGS))

    args = ap.parse_args()

    if not args.input_epub.exists():
        ap.error(f"Nie istnieje plik: {args.input_epub}")

    base_prompt = args.prompt.read_text(encoding="utf-8", errors="replace")

    glossary_index = None
    if (not args.no_glossary) and args.glossary:
        glossary_index = load_glossary(args.glossary)

    try:
        backoff_tuple = tuple(int(x.strip()) for x in args.backoff.split(",") if x.strip())
        if not backoff_tuple:
            backoff_tuple = (5, 15, 30)
    except Exception:
        backoff_tuple = (5, 15, 30)

    provider = (args.provider or "").strip().lower()

    if provider == "google":
        api_key = (args.api_key or "").strip()
        if not api_key:
            ap.error("Dla --provider=google musisz podać --api-key (jawnie).")
        gcfg = GoogleConfig(
            api_key=api_key,
            model=args.model,
            temperature=args.temperature,
            max_output_tokens=args.num_predict,
            timeout_s=args.timeout,
            min_interval_s=float(args.sleep or 0.0),
            max_attempts=max(1, args.attempts),
            backoff_s=backoff_tuple,
        )
        client: LLMClient = GoogleClient(gcfg)
    else:
        cfg = OllamaConfig(
            host=args.host,
            model=args.model,
            temperature=args.temperature,
            num_ctx=args.num_ctx,
            num_predict=args.num_predict,
            timeout_s=args.timeout,
            max_attempts=max(1, args.attempts),
            backoff_s=backoff_tuple,
        )
        client = OllamaClient(cfg)

    tags = tuple([t.strip() for t in args.tags.split(",") if t.strip()])

    translate_epub(
        input_epub=args.input_epub,
        output_epub=args.output_epub,
        base_prompt=base_prompt,
        llm=client,
        provider=provider,
        glossary_index=glossary_index,
        cache_path=args.cache,
        block_tags=tags,
        batch_max_chars=args.batch_max_chars,
        batch_max_segs=args.batch_max_segs,
        sleep_s=float(args.sleep or 0.0),
        debug_dir=args.debug_dir if args.debug_dir else None,
        checkpoint_every_files=args.checkpoint_every_files,
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
