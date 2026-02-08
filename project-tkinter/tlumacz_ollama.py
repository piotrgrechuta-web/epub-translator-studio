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
import html
import gc
import json
import os
import re
import shutil
import sqlite3
import time
import zipfile
from dataclasses import dataclass
from difflib import SequenceMatcher
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
POLISH_CHARS = set("ąćęłńóśźż")
POLISH_HINT_WORDS = {
    "i", "oraz", "że", "się", "jest", "nie", "na", "do", "z", "za", "dla", "który",
    "która", "które", "jako", "aby", "czy", "to", "ten", "ta", "te", "po", "przez",
    "w", "przy", "od", "pod", "nad", "bez", "już", "więc", "gdy", "gdyż",
}
ENGLISH_HINT_WORDS = {
    "the", "and", "of", "to", "in", "for", "with", "on", "that", "this", "is", "are",
    "was", "were", "be", "as", "by", "from", "at", "or", "an", "a", "it", "if", "we",
}


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


def build_language_instruction(source_lang: str, target_lang: str) -> str:
    src = (source_lang or "en").strip().lower()
    tgt = (target_lang or "pl").strip().lower()
    return (
        "KRYTYCZNE: Tlumacz wiernie z jezyka "
        f"{src} na jezyk {tgt}. "
        f"Wynik musi byc wyłącznie w jezyku {tgt}. "
        "Zachowaj znaczniki XML i ich kolejnosc."
    )


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


def _plain_text_from_inner_xml(inner_xml_text: str) -> str:
    no_tags = re.sub(r"<[^>]+>", " ", inner_xml_text)
    no_tags = html.unescape(no_tags)
    no_tags = re.sub(r"\s+", " ", no_tags)
    return no_tags.strip()


def looks_like_polish(inner_xml_text: str) -> bool:
    txt = _plain_text_from_inner_xml(inner_xml_text)
    if not txt:
        return True

    low = txt.lower()
    if any(ch in low for ch in POLISH_CHARS):
        return True

    tokens = re.findall(r"[a-ząćęłńóśźż]{2,}", low, flags=re.IGNORECASE)
    if not tokens:
        return True

    pl_hits = sum(1 for t in tokens if t in POLISH_HINT_WORDS)
    en_hits = sum(1 for t in tokens if t in ENGLISH_HINT_WORDS)

    if pl_hits >= 2 and pl_hits >= en_hits:
        return True
    if en_hits >= 3 and pl_hits == 0:
        return False
    if len(tokens) >= 8 and en_hits >= 2 and pl_hits == 0:
        return False
    return True


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


def ensure_polish_translation(
    llm: LLMClient,
    model: str,
    base_prompt: str,
    seg: Segment,
    translated_inner: str,
    glossary_index: Optional[Dict[str, List[GlossaryEntry]]],
    debug_dir: Optional[Path],
    debug_prefix: str,
) -> str:
    if looks_like_polish(translated_inner):
        return translated_inner

    print(f"  [LANG-GUARD] Segment wygląda na nietłumaczony (EN). Retry z wymuszeniem PL: {seg.seg_id}")
    forced_prompt = (
        base_prompt.strip()
        + "\n\n"
        + "KRYTYCZNE: Zwróć wynik wyłącznie po polsku. "
          "Jeśli wejście jest po angielsku, obowiązkowo przetłumacz je na polski."
    )
    retry = translate_single_segment(
        llm=llm,
        model=model,
        base_prompt=forced_prompt,
        seg=seg,
        glossary_index=glossary_index,
        debug_dir=debug_dir,
        debug_prefix=f"{debug_prefix}__lang_retry_{seg.idx:06d}",
    )
    if looks_like_polish(retry):
        return retry

    raise RuntimeError(
        f"Guard języka: segment nadal nie wygląda na polski po retry: {seg.seg_id}"
    )


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
            if len(batch_local) > 1 and depth < max_split_depth and is_google_retriable_error(e):
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


@dataclass
class ValidationTotals:
    spine_files: int = 0
    checked_files: int = 0
    xml_ok_files: int = 0
    checked_segments: int = 0
    suspicious_segments: int = 0
    hard_errors: int = 0


class TranslationMemory:
    def __init__(self, db_path: Path, project_id: Optional[int] = None):
        self.db_path = db_path
        self.project_id = project_id
        self.conn = sqlite3.connect(str(db_path), timeout=30.0)
        self.conn.row_factory = sqlite3.Row
        self.conn.execute("PRAGMA journal_mode = WAL")
        self.conn.execute("PRAGMA busy_timeout = 5000")
        self._init()

    def _init(self) -> None:
        cur = self.conn.cursor()
        cur.execute(
            """
            CREATE TABLE IF NOT EXISTS tm_segments (
              id INTEGER PRIMARY KEY AUTOINCREMENT,
              source_text TEXT NOT NULL,
              target_text TEXT NOT NULL,
              source_lang TEXT NOT NULL DEFAULT 'en',
              target_lang TEXT NOT NULL DEFAULT 'pl',
              source_hash TEXT NOT NULL,
              source_len INTEGER NOT NULL DEFAULT 0,
              project_id INTEGER,
              score REAL NOT NULL DEFAULT 1.0,
              created_at INTEGER NOT NULL
            )
            """
        )
        cols = {str(r["name"]) for r in cur.execute("PRAGMA table_info(tm_segments)").fetchall()}
        if "source_len" not in cols:
            cur.execute("ALTER TABLE tm_segments ADD COLUMN source_len INTEGER NOT NULL DEFAULT 0")
        cur.execute("CREATE INDEX IF NOT EXISTS idx_tm_source_hash ON tm_segments(source_hash)")
        cur.execute("CREATE INDEX IF NOT EXISTS idx_tm_src_len ON tm_segments(source_len)")
        cur.execute("UPDATE tm_segments SET source_len = LENGTH(source_text) WHERE source_len = 0")
        self.conn.commit()

    def close(self) -> None:
        self.conn.close()

    def _norm_hash(self, s: str) -> str:
        return hashlib.sha1((s or "").strip().lower().encode("utf-8", errors="replace")).hexdigest()

    def add(
        self,
        source_text: str,
        target_text: str,
        score: float = 1.0,
        source_lang: str = "en",
        target_lang: str = "pl",
    ) -> None:
        src = (source_text or "").strip()
        dst = (target_text or "").strip()
        if not src or not dst:
            return
        self.conn.execute(
            """
            INSERT INTO tm_segments(source_text, target_text, source_lang, target_lang, source_hash, source_len, project_id, score, created_at)
            VALUES(?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                src,
                dst,
                str(source_lang or "en"),
                str(target_lang or "pl"),
                self._norm_hash(src),
                len(src),
                self.project_id,
                float(score),
                int(time.time()),
            ),
        )
        self.conn.commit()

    def lookup(
        self,
        source_text: str,
        fuzzy_threshold: float = 0.92,
        source_lang: Optional[str] = None,
        target_lang: Optional[str] = None,
    ) -> Optional[str]:
        src = (source_text or "").strip()
        if not src:
            return None
        h = self._norm_hash(src)
        where = "source_hash = ?"
        args: List[object] = [h]
        if source_lang:
            where += " AND source_lang = ?"
            args.append(str(source_lang))
        if target_lang:
            where += " AND target_lang = ?"
            args.append(str(target_lang))
        row = self.conn.execute(
            f"SELECT target_text FROM tm_segments WHERE {where} ORDER BY score DESC, id DESC LIMIT 1",
            args,
        ).fetchone()
        if row:
            return str(row["target_text"])
        if fuzzy_threshold <= 0:
            return None

        src_len = len(src)
        delta = max(40, int(src_len * 0.35))
        where2 = "source_len BETWEEN ? AND ?"
        args2: List[object] = [max(0, src_len - delta), src_len + delta]
        if source_lang:
            where2 += " AND source_lang = ?"
            args2.append(str(source_lang))
        if target_lang:
            where2 += " AND target_lang = ?"
            args2.append(str(target_lang))
        candidates = self.conn.execute(
            f"""
            SELECT source_text, target_text
            FROM tm_segments
            WHERE {where2}
            ORDER BY id DESC
            LIMIT 2000
            """,
            args2,
        ).fetchall()
        best_ratio = 0.0
        best_target = None
        for c in candidates:
            ratio = SequenceMatcher(None, src, str(c["source_text"])).ratio()
            if ratio > best_ratio:
                best_ratio = ratio
                best_target = str(c["target_text"])
        if best_target and best_ratio >= fuzzy_threshold:
            return best_target
        return None


class SegmentLedger:
    """Idempotentny ledger segmentow per projekt i krok pipeline."""

    def __init__(self, db_path: Path, project_id: Optional[int] = None, run_step: str = "translate"):
        self.db_path = db_path
        self.project_id = int(project_id or 0)
        step = str(run_step or "translate").strip().lower()
        self.run_step = step if step in {"translate", "edit"} else "translate"
        self.conn = sqlite3.connect(str(db_path), timeout=30.0)
        self.conn.row_factory = sqlite3.Row
        self.conn.execute("PRAGMA journal_mode = WAL")
        self.conn.execute("PRAGMA busy_timeout = 5000")
        self._init()
        self.reset_stale_processing()

    def _init(self) -> None:
        cur = self.conn.cursor()
        cur.execute(
            """
            CREATE TABLE IF NOT EXISTS segment_ledger (
              id INTEGER PRIMARY KEY AUTOINCREMENT,
              project_id INTEGER NOT NULL DEFAULT 0,
              run_step TEXT NOT NULL DEFAULT 'translate',
              chapter_path TEXT NOT NULL DEFAULT '',
              segment_id TEXT NOT NULL DEFAULT '',
              segment_hash TEXT NOT NULL,
              source_hash TEXT NOT NULL DEFAULT '',
              source_len INTEGER NOT NULL DEFAULT 0,
              status TEXT NOT NULL DEFAULT 'PENDING',
              translated_inner TEXT NOT NULL DEFAULT '',
              error_message TEXT NOT NULL DEFAULT '',
              attempt_count INTEGER NOT NULL DEFAULT 0,
              provider TEXT NOT NULL DEFAULT '',
              model TEXT NOT NULL DEFAULT '',
              created_at INTEGER NOT NULL,
              updated_at INTEGER NOT NULL,
              last_request_at INTEGER,
              completed_at INTEGER
            )
            """
        )
        cur.execute(
            """
            CREATE UNIQUE INDEX IF NOT EXISTS idx_segment_ledger_scope_hash
            ON segment_ledger(project_id, run_step, segment_hash)
            """
        )
        cur.execute(
            """
            CREATE INDEX IF NOT EXISTS idx_segment_ledger_status
            ON segment_ledger(project_id, run_step, status, updated_at DESC)
            """
        )
        cur.execute(
            """
            CREATE INDEX IF NOT EXISTS idx_segment_ledger_chapter
            ON segment_ledger(project_id, run_step, chapter_path, updated_at DESC)
            """
        )
        self.conn.commit()

    def close(self) -> None:
        self.conn.close()

    @staticmethod
    def _hash_source_text(source_text: str) -> str:
        src = (source_text or "").strip().lower()
        return hashlib.sha1(src.encode("utf-8", errors="replace")).hexdigest()

    def reset_stale_processing(self, max_age_s: int = 6 * 60 * 60) -> int:
        now = int(time.time())
        cutoff = now - max(60, int(max_age_s))
        cur = self.conn.execute(
            """
            UPDATE segment_ledger
            SET status = 'PENDING',
                error_message = CASE
                    WHEN error_message = '' THEN 'stale processing reset'
                    ELSE error_message
                END,
                updated_at = ?
            WHERE project_id = ?
              AND run_step = ?
              AND status = 'PROCESSING'
              AND updated_at < ?
            """,
            (now, self.project_id, self.run_step, cutoff),
        )
        self.conn.commit()
        return int(cur.rowcount or 0)

    def load_chapter_states(self, chapter_path: str) -> Dict[str, sqlite3.Row]:
        rows = self.conn.execute(
            """
            SELECT *
            FROM segment_ledger
            WHERE project_id = ? AND run_step = ? AND chapter_path = ?
            """,
            (self.project_id, self.run_step, str(chapter_path or "")),
        ).fetchall()
        out: Dict[str, sqlite3.Row] = {}
        for row in rows:
            key = str(row["segment_hash"] or "").strip()
            if key:
                out[key] = row
        return out

    def ensure_pending(self, chapter_path: str, segment_id: str, source_text: str) -> None:
        now = int(time.time())
        seg_hash = str(segment_id or "").strip()
        if not seg_hash:
            return
        self.conn.execute(
            """
            INSERT INTO segment_ledger(
              project_id, run_step, chapter_path, segment_id, segment_hash,
              source_hash, source_len, status, created_at, updated_at
            )
            VALUES(?, ?, ?, ?, ?, ?, ?, 'PENDING', ?, ?)
            ON CONFLICT(project_id, run_step, segment_hash) DO UPDATE SET
              chapter_path = excluded.chapter_path,
              segment_id = excluded.segment_id,
              source_hash = excluded.source_hash,
              source_len = excluded.source_len,
              updated_at = excluded.updated_at
            """,
            (
                self.project_id,
                self.run_step,
                str(chapter_path or ""),
                seg_hash,
                seg_hash,
                self._hash_source_text(source_text),
                len(source_text or ""),
                now,
                now,
            ),
        )
        self.conn.commit()

    def mark_processing(
        self,
        chapter_path: str,
        segment_id: str,
        source_text: str,
        *,
        provider: str = "",
        model: str = "",
    ) -> None:
        seg_hash = str(segment_id or "").strip()
        if not seg_hash:
            return
        self.ensure_pending(chapter_path, seg_hash, source_text)
        now = int(time.time())
        self.conn.execute(
            """
            UPDATE segment_ledger
            SET status = 'PROCESSING',
                attempt_count = attempt_count + 1,
                error_message = '',
                provider = ?,
                model = ?,
                last_request_at = ?,
                updated_at = ?
            WHERE project_id = ? AND run_step = ? AND segment_hash = ?
            """,
            (
                str(provider or ""),
                str(model or ""),
                now,
                now,
                self.project_id,
                self.run_step,
                seg_hash,
            ),
        )
        self.conn.commit()

    def mark_completed(
        self,
        chapter_path: str,
        segment_id: str,
        source_text: str,
        translated_inner: str,
        *,
        provider: str = "",
        model: str = "",
    ) -> None:
        seg_hash = str(segment_id or "").strip()
        if not seg_hash:
            return
        now = int(time.time())
        self.conn.execute(
            """
            INSERT INTO segment_ledger(
              project_id, run_step, chapter_path, segment_id, segment_hash,
              source_hash, source_len, status, translated_inner, error_message,
              attempt_count, provider, model, created_at, updated_at, last_request_at, completed_at
            )
            VALUES(?, ?, ?, ?, ?, ?, ?, 'COMPLETED', ?, '', 1, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(project_id, run_step, segment_hash) DO UPDATE SET
              chapter_path = excluded.chapter_path,
              segment_id = excluded.segment_id,
              source_hash = excluded.source_hash,
              source_len = excluded.source_len,
              status = 'COMPLETED',
              translated_inner = excluded.translated_inner,
              error_message = '',
              provider = excluded.provider,
              model = excluded.model,
              updated_at = excluded.updated_at,
              completed_at = excluded.completed_at,
              last_request_at = excluded.last_request_at,
              attempt_count = CASE
                  WHEN segment_ledger.attempt_count < 1 THEN 1
                  ELSE segment_ledger.attempt_count
              END
            """,
            (
                self.project_id,
                self.run_step,
                str(chapter_path or ""),
                seg_hash,
                seg_hash,
                self._hash_source_text(source_text),
                len(source_text or ""),
                str(translated_inner or ""),
                str(provider or ""),
                str(model or ""),
                now,
                now,
                now,
                now,
            ),
        )
        self.conn.commit()

    def mark_error(self, segment_id: str, error_message: str) -> None:
        seg_hash = str(segment_id or "").strip()
        if not seg_hash:
            return
        now = int(time.time())
        self.conn.execute(
            """
            UPDATE segment_ledger
            SET status = 'ERROR',
                error_message = ?,
                updated_at = ?
            WHERE project_id = ? AND run_step = ? AND segment_hash = ?
            """,
            (str(error_message or "")[:2000], now, self.project_id, self.run_step, seg_hash),
        )
        self.conn.commit()


def default_checkpoint_json_path(output_epub: Path) -> Path:
    return output_epub.with_name(output_epub.stem + ".checkpoint.json")


def save_checkpoint_json(
    checkpoint_path: Path,
    *,
    input_epub: Path,
    output_epub: Path,
    wip_epub: Path,
    completed_chapters: List[str],
    processed_files: int,
    spine_total_files: int,
) -> None:
    checkpoint_path.parent.mkdir(parents=True, exist_ok=True)
    payload = {
        "version": 1,
        "input_epub": str(input_epub),
        "output_epub": str(output_epub),
        "wip_epub": str(wip_epub),
        "completed_chapters": completed_chapters,
        "processed_files": int(processed_files),
        "spine_total_files": int(spine_total_files),
        "updated_at": int(time.time()),
    }
    checkpoint_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")


def load_checkpoint_json(checkpoint_path: Path) -> Optional[Dict[str, object]]:
    if not checkpoint_path.exists():
        return None
    try:
        data = json.loads(checkpoint_path.read_text(encoding="utf-8"))
    except Exception:
        return None
    if not isinstance(data, dict):
        return None
    return data


def compute_resume_extra_done(
    input_epub: Path,
    cache: Cache,
    block_tags: Tuple[str, ...],
    completed_chapters: set[str],
) -> int:
    if not completed_chapters:
        return 0
    extra_done = 0
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
            if chapter_path not in completed_chapters:
                continue
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
                if cache.get(sid) is None:
                    extra_done += 1
    return extra_done


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


def validate_translated_epub(
    epub_path: Path,
    block_tags: Tuple[str, ...],
    *,
    min_chars: int = 40,
    max_suspicious_ratio: float = 0.35,
) -> int:
    print("\n=== WALIDACJA EPUB ===")
    print(f"  Plik: {epub_path}")

    totals = ValidationTotals()
    if not epub_path.exists():
        print(f"[VAL-ERR] Nie istnieje plik: {epub_path}")
        return 2

    try:
        with zipfile.ZipFile(epub_path, "r") as zin:
            bad_member = zin.testzip()
            if bad_member is not None:
                totals.hard_errors += 1
                print(f"[VAL-ERR] Uszkodzony wpis ZIP: {bad_member}")

            try:
                opf_path = find_opf_path(zin)
                manifest, spine = parse_spine_and_manifest(zin, opf_path)
            except Exception as e:
                print(f"[VAL-ERR] Błąd odczytu OPF/spine: {type(e).__name__}: {e}")
                return 2

            totals.spine_files = len(spine)
            xpath = _xpath_translatable(block_tags)

            for item_id in spine:
                href, media_type = manifest.get(item_id, ("", ""))
                if not href:
                    continue
                if "xhtml" not in media_type and "html" not in media_type:
                    continue

                totals.checked_files += 1
                chapter_path = normalize_epub_path(opf_path, href)
                try:
                    raw = zin.read(chapter_path)
                except KeyError:
                    totals.hard_errors += 1
                    print(f"[VAL-ERR] Brak pliku ze spine: {chapter_path}")
                    continue

                parser = etree.XMLParser(recover=False, resolve_entities=False, huge_tree=True)
                try:
                    root = etree.fromstring(raw, parser=parser)
                    totals.xml_ok_files += 1
                except Exception as e:
                    totals.hard_errors += 1
                    print(f"[VAL-ERR] Niepoprawny XML/XHTML: {chapter_path} ({type(e).__name__})")
                    continue

                for el in root.xpath(xpath):
                    if not has_translatable_text(el):
                        continue
                    plain = etree.tostring(el, encoding="unicode", method="text").strip()
                    if len(re.sub(r"\s+", "", plain)) < min_chars:
                        continue
                    totals.checked_segments += 1
                    if not looks_like_polish(plain):
                        totals.suspicious_segments += 1

    except zipfile.BadZipFile as e:
        print(f"[VAL-ERR] Niepoprawny plik EPUB/ZIP: {e}")
        return 2
    except Exception as e:
        print(f"[VAL-ERR] Nieoczekiwany błąd walidacji: {type(e).__name__}: {e}")
        return 2

    suspicious_ratio = (
        totals.suspicious_segments / totals.checked_segments if totals.checked_segments > 0 else 0.0
    )
    print("\n=== PODSUMOWANIE WALIDACJI ===")
    print(f"  Pliki w spine:                 {totals.spine_files}")
    print(f"  Pliki sprawdzone:              {totals.checked_files}")
    print(f"  Pliki XML OK:                  {totals.xml_ok_files}")
    print(f"  Segmenty sprawdzone (>= {min_chars} znaków): {totals.checked_segments}")
    print(f"  Segmenty podejrzane (EN):      {totals.suspicious_segments}")
    print(f"  Współczynnik podejrzanych:     {suspicious_ratio:.1%}")
    print(f"  Twarde błędy:                  {totals.hard_errors}")

    if totals.hard_errors > 0:
        print("VALIDATION RESULT: FAIL (hard errors)")
        return 2
    if suspicious_ratio > max_suspicious_ratio:
        print(
            f"VALIDATION RESULT: FAIL (suspicious ratio {suspicious_ratio:.1%} > {max_suspicious_ratio:.1%})"
        )
        return 3
    if totals.suspicious_segments > 0:
        print("VALIDATION RESULT: OK_WITH_WARNINGS")
        print("[VAL-WARN] Wykryto segmenty prawdopodobnie nieprzetłumaczone.")
        return 0

    print("VALIDATION RESULT: OK")
    return 0


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
    checkpoint_json_path: Optional[Path] = None,
    polish_guard: bool = True,
    source_lang: str = "en",
    target_lang: str = "pl",
    tm: Optional[TranslationMemory] = None,
    segment_ledger: Optional[SegmentLedger] = None,
    tm_fuzzy_threshold: float = 0.92,
) -> None:
    source_lang = (source_lang or "en").strip().lower()
    target_lang = (target_lang or "pl").strip().lower()
    if target_lang != "pl" and polish_guard:
        print(f"[LANG-GUARD] target_lang={target_lang} -> wyłączam polish guard.")
        polish_guard = False
    base_prompt = base_prompt.strip() + "\n\n" + build_language_instruction(source_lang, target_lang)
    model = llm.resolve_model()
    cache = load_cache(cache_path)
    modified: Dict[str, bytes] = {}
    wip_out = output_epub.with_name(output_epub.stem + ".wip" + output_epub.suffix)
    checkpoint_path = checkpoint_json_path or default_checkpoint_json_path(output_epub)
    effective_checkpoint_every = checkpoint_every_files
    if effective_checkpoint_every <= 0 and checkpoint_json_path is not None:
        effective_checkpoint_every = 1
    working_input = input_epub
    completed_chapters: set[str] = set()

    ck = load_checkpoint_json(checkpoint_path)
    if ck:
        ck_input = str(ck.get("input_epub", "")).strip()
        ck_output = str(ck.get("output_epub", "")).strip()
        ck_wip = str(ck.get("wip_epub", "")).strip()
        ck_completed = ck.get("completed_chapters", [])
        if ck_input == str(input_epub) and ck_output == str(output_epub) and ck_wip and Path(ck_wip).exists():
            working_input = Path(ck_wip)
            if isinstance(ck_completed, list):
                completed_chapters = {str(x) for x in ck_completed if isinstance(x, str)}
            print(
                f"[CHECKPOINT-RESUME] wznowienie z {working_input} | "
                f"ukończone rozdziały: {len(completed_chapters)}"
            )
        else:
            print("[CHECKPOINT-RESUME] checkpoint niepasujący do bieżących ścieżek - ignoruję.")

    totals = compute_project_totals(working_input, cache, block_tags)
    global_total = totals.total_segments
    global_cached = totals.cached_segments
    global_to_translate = totals.to_translate_segments
    resume_extra_done = compute_resume_extra_done(working_input, cache, block_tags, completed_chapters)

    # Liczniki postępu globalnego:
    global_done = global_cached + resume_extra_done
    global_new = 0
    global_ledger_reused = 0

    print("\n=== POSTĘP GLOBALNY (CAŁY EPUB) ===")
    print(f"  Segmenty łącznie:     {global_total}")
    print(f"  Segmenty z cache:     {global_cached}")
    if resume_extra_done > 0:
        print(f"  Segmenty z resume:    {resume_extra_done}")
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

    with zipfile.ZipFile(working_input, "r") as zin:
        opf_path = find_opf_path(zin)
        manifest, spine = parse_spine_and_manifest(zin, opf_path)

        spine_total = len(spine)
        processed_spine_files = 0

        for spine_idx, item_id in enumerate(spine, 1):
            href, media_type = manifest.get(item_id, ("", ""))
            if not href:
                continue
            if "xhtml" not in media_type and "html" not in media_type:
                continue

            chapter_path = normalize_epub_path(opf_path, href)
            if chapter_path in completed_chapters:
                processed_spine_files += 1
                _print_global_progress(chapter_path, extra=f"spine {spine_idx}/{spine_total} | resume skip")
                continue
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
            chapter_tm = 0
            chapter_ledger = 0
            ledger_rows = segment_ledger.load_chapter_states(chapter_path) if segment_ledger else {}

            # cache + lista do tłumaczenia
            for i, el in enumerate(elements):
                if not has_translatable_text(el):
                    continue
                seg_inner = inner_xml(el).strip()
                if not seg_inner:
                    continue

                seg_plain = etree.tostring(el, encoding="unicode", method="text")
                sid = stable_id(chapter_path, i, seg_inner)
                ledger_done_inner: Optional[str] = None
                if segment_ledger is not None:
                    row = ledger_rows.get(sid)
                    if row is None:
                        segment_ledger.ensure_pending(chapter_path, sid, seg_plain)
                    elif str(row["status"] or "").upper() == "COMPLETED":
                        val = str(row["translated_inner"] or "").strip()
                        if val:
                            ledger_done_inner = val

                tr_cached = cache.get(sid)
                if tr_cached is not None:
                    if polish_guard and not looks_like_polish(tr_cached):
                        print(f"  [LANG-GUARD] Ignoruję cache (wygląda na EN): {sid}")
                        segs.append(Segment(idx=i, el=el, seg_id=sid, inner=seg_inner, plain=seg_plain))
                        continue
                    replace_inner_xml(el, tr_cached)
                    chapter_cache += 1
                    if segment_ledger is not None:
                        segment_ledger.mark_completed(chapter_path, sid, seg_plain, tr_cached, provider="cache", model=model)
                elif ledger_done_inner is not None:
                    if polish_guard and not looks_like_polish(ledger_done_inner):
                        segs.append(Segment(idx=i, el=el, seg_id=sid, inner=seg_inner, plain=seg_plain))
                        continue
                    replace_inner_xml(el, ledger_done_inner)
                    cache[sid] = ledger_done_inner
                    cache.append(sid, ledger_done_inner)
                    chapter_ledger += 1
                    global_done += 1
                    global_ledger_reused += 1
                    if tm is not None:
                        tm.add(seg_plain, ledger_done_inner, score=1.0, source_lang=source_lang, target_lang=target_lang)
                    if segment_ledger is not None:
                        segment_ledger.mark_completed(chapter_path, sid, seg_plain, ledger_done_inner, provider="ledger", model=model)
                else:
                    tm_hit = (
                        tm.lookup(
                            seg_plain,
                            fuzzy_threshold=tm_fuzzy_threshold,
                            source_lang=source_lang,
                            target_lang=target_lang,
                        )
                        if tm
                        else None
                    )
                    if tm_hit:
                        if polish_guard and not looks_like_polish(tm_hit):
                            segs.append(Segment(idx=i, el=el, seg_id=sid, inner=seg_inner, plain=seg_plain))
                        else:
                            replace_inner_xml(el, tm_hit)
                            chapter_tm += 1
                            global_done += 1
                            if segment_ledger is not None:
                                segment_ledger.mark_completed(chapter_path, sid, seg_plain, tm_hit, provider="tm", model=model)
                    else:
                        segs.append(Segment(idx=i, el=el, seg_id=sid, inner=seg_inner, plain=seg_plain))

            chapter_new_total = len(segs)

            if chapter_cache > 0 or chapter_tm > 0 or chapter_ledger > 0:
                # global_done nie zwiększamy tutaj, bo cache policzyliśmy w prepass jako global_cached.
                _print_global_progress(
                    chapter_path,
                    extra=f"spine {spine_idx}/{spine_total} | cache: {chapter_cache} | tm: {chapter_tm} | ledger: {chapter_ledger}",
                )

            if chapter_new_total == 0:
                # jeśli cache zmienił DOM, zapisujemy ten plik
                if chapter_cache > 0 or chapter_tm > 0 or chapter_ledger > 0:
                    out_bytes = etree.tostring(root, encoding="utf-8", xml_declaration=True, pretty_print=False)
                    modified[chapter_path] = out_bytes
                completed_chapters.add(chapter_path)
                processed_spine_files += 1
                del elements
                del segs
                del root
                continue

            print(
                f"\n[{spine_idx}/{spine_total}] {chapter_path}: "
                f"do przetłumaczenia {chapter_new_total} segmentów (cache: {chapter_cache}, tm: {chapter_tm})"
            )

            changed = False
            chapter_new_done = 0

            for batch_no, batch in enumerate(chunk_segments(segs, batch_max_chars, batch_max_segs), 1):
                debug_prefix = f"{Path(chapter_path).stem}_b{batch_no:04d}"
                batch_first_idx = batch[0].idx if batch else -1
                batch_last_idx = batch[-1].idx if batch else -1
                batch_chars = sum(len(s.inner) for s in batch)
                print(
                    f"  [BATCH-START] spine {spine_idx}/{spine_total} | "
                    f"batch {batch_no} | segs={len(batch)} | idx={batch_first_idx}-{batch_last_idx} | chars~{batch_chars}",
                    flush=True,
                )

                if segment_ledger is not None:
                    for s in batch:
                        segment_ledger.mark_processing(
                            chapter_path,
                            s.seg_id,
                            s.plain,
                            provider=provider,
                            model=model,
                        )
                try:
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
                except Exception as e:
                    if segment_ledger is not None:
                        msg = f"{type(e).__name__}: {e}"
                        for s in batch:
                            segment_ledger.mark_error(s.seg_id, msg)
                    raise
                print(
                    f"  [BATCH-DONE]  spine {spine_idx}/{spine_total} | batch {batch_no} | map={len(mapping)}",
                    flush=True,
                )

                # wstrzyknięcie + cache
                for s in batch:
                    tr_inner = (mapping.get(s.seg_id) or "").strip()
                    if not tr_inner:
                        raise RuntimeError(f"Pusty wynik tłumaczenia po fallbacku dla segmentu: {s.seg_id}")
                    if polish_guard:
                        tr_inner = ensure_polish_translation(
                            llm=llm,
                            model=model,
                            base_prompt=base_prompt,
                            seg=s,
                            translated_inner=tr_inner,
                            glossary_index=glossary_index,
                            debug_dir=debug_dir,
                            debug_prefix=debug_prefix,
                        )
                    if segment_ledger is not None:
                        segment_ledger.mark_completed(
                            chapter_path,
                            s.seg_id,
                            s.plain,
                            tr_inner,
                            provider=provider,
                            model=model,
                        )
                    replace_inner_xml(s.el, tr_inner)
                    cache[s.seg_id] = tr_inner
                    cache.append(s.seg_id, tr_inner)
                    if tm is not None:
                        tm.add(s.plain, tr_inner, score=1.0, source_lang=source_lang, target_lang=target_lang)
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

            completed_chapters.add(chapter_path)
            processed_spine_files += 1

            if effective_checkpoint_every and (spine_idx % effective_checkpoint_every == 0):
                written_to = write_epub_atomic(working_input, wip_out, modified, make_backup=False)
                print(f"  [CHECKPOINT] zapisano: {written_to} (po pliku {spine_idx}/{spine_total})")
                save_checkpoint_json(
                    checkpoint_path,
                    input_epub=input_epub,
                    output_epub=output_epub,
                    wip_epub=wip_out,
                    completed_chapters=sorted(completed_chapters),
                    processed_files=processed_spine_files,
                    spine_total_files=spine_total,
                )
            del elements
            del segs
            del root
            if spine_idx % 8 == 0:
                gc.collect()

    written_to = write_epub_atomic(working_input, output_epub, modified, make_backup=True)
    try:
        if checkpoint_path.exists():
            checkpoint_path.unlink()
    except Exception:
        pass
    try:
        if wip_out.exists():
            wip_out.unlink()
    except Exception:
        pass

    print("\n=== KONIEC ===")
    print(f"  Nowe tłumaczenia: {global_new}")
    print(f"  Segmenty łącznie: {global_total}")
    if global_total > 0:
        print(f"  Final progress:   {global_done}/{global_total} ({(global_done/global_total)*100:.1f}%)")
    if global_ledger_reused > 0:
        print(f"  Ledger reuse:     {global_ledger_reused}")
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
    ap.add_argument("input_epub", type=Path, nargs="?")
    ap.add_argument("output_epub", type=Path, nargs="?")

    ap.add_argument("--provider", choices=["ollama", "google"], default=None)
    ap.add_argument("--api-key", type=str, default=None, help="Google API key (opcjonalnie; fallback: env GOOGLE_API_KEY)")
    ap.add_argument("--prompt", type=Path, default=None)
    ap.add_argument("--glossary", type=Path, default=None)
    ap.add_argument("--no-glossary", action="store_true")
    ap.add_argument("--model", type=str, default=None)
    ap.add_argument("--host", type=str, default="http://127.0.0.1:11434")  # starter nie pyta, ale CLI zostaje
    ap.add_argument("--temperature", type=float, default=0.1)
    ap.add_argument("--num-ctx", type=int, default=8192)
    ap.add_argument("--num-predict", type=int, default=2048)
    ap.add_argument("--timeout", type=int, default=300)
    ap.add_argument("--cache", type=Path, default=None)
    ap.add_argument("--sleep", type=float, default=0.0)
    ap.add_argument("--batch-max-chars", type=int, default=None)
    ap.add_argument("--batch-max-segs", type=int, default=None)
    ap.add_argument("--source-lang", type=str, default="en")
    ap.add_argument("--target-lang", type=str, default="pl")
    ap.add_argument("--checkpoint-every-files", type=int, default=0)
    ap.add_argument("--checkpoint-json", type=Path, default=None, help="Plik checkpoint.json dla resume po rozdziałach.")
    ap.add_argument("--debug-dir", type=Path, default=Path("debug"))
    ap.add_argument("--attempts", type=int, default=3)
    ap.add_argument("--backoff", type=str, default="5,15,30")
    ap.add_argument("--tags", type=str, default=",".join(DEFAULT_BLOCK_TAGS))
    ap.add_argument("--validate-epub", type=Path, default=None, help="Waliduj istniejący EPUB i zakończ bez tłumaczenia.")
    ap.add_argument("--validate-min-chars", type=int, default=40, help="Minimalna długość segmentu do heurystyki EN/PL.")
    ap.add_argument(
        "--validate-max-suspicious-ratio",
        type=float,
        default=0.35,
        help="Maksymalny akceptowalny odsetek podejrzanych segmentów EN.",
    )
    ap.add_argument(
        "--no-polish-guard",
        action="store_true",
        help="Wyłącz walidację języka PL przed zapisem do cache (domyślnie guard jest włączony).",
    )
    ap.add_argument("--tm-db", type=Path, default=None, help="Ścieżka do SQLite Translation Memory.")
    ap.add_argument("--tm-project-id", type=int, default=None, help="ID projektu do powiązania wpisów TM.")
    ap.add_argument("--tm-fuzzy-threshold", type=float, default=0.92, help="Próg fuzzy TM 0..1.")
    ap.add_argument("--run-step", choices=["translate", "edit"], default="translate", help="Krok pipeline do scope ledgera.")

    args = ap.parse_args()
    tags = tuple([t.strip() for t in args.tags.split(",") if t.strip()])

    if args.validate_epub is not None:
        return validate_translated_epub(
            epub_path=args.validate_epub,
            block_tags=tags,
            min_chars=max(1, args.validate_min_chars),
            max_suspicious_ratio=max(0.0, min(1.0, args.validate_max_suspicious_ratio)),
        )

    if args.input_epub is None or args.output_epub is None:
        ap.error("Tryb tłumaczenia wymaga pozycyjnych argumentów: input_epub output_epub.")
    if args.prompt is None:
        ap.error("Tryb tłumaczenia wymaga --prompt.")
    if not args.provider:
        ap.error("Tryb tłumaczenia wymaga --provider.")
    if not args.model:
        ap.error("Tryb tłumaczenia wymaga --model.")
    if args.batch_max_chars is None or args.batch_max_segs is None:
        ap.error("Tryb tłumaczenia wymaga --batch-max-chars i --batch-max-segs.")

    if not args.input_epub.exists():
        ap.error(f"Nie istnieje plik: {args.input_epub}")

    if not args.prompt.exists():
        ap.error(f"Nie istnieje plik prompt: {args.prompt}")

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

    provider = args.provider.strip().lower()

    if provider == "google":
        api_key = (args.api_key or "").strip() or os.environ.get("GOOGLE_API_KEY", "").strip()
        if not api_key:
            ap.error("Dla --provider=google musisz podać --api-key lub ustawić env GOOGLE_API_KEY.")
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

    tm_store: Optional[TranslationMemory] = None
    segment_ledger: Optional[SegmentLedger] = None
    if args.tm_db is not None:
        tm_store = TranslationMemory(args.tm_db, project_id=args.tm_project_id)
        segment_ledger = SegmentLedger(args.tm_db, project_id=args.tm_project_id, run_step=args.run_step)

    try:
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
            checkpoint_json_path=args.checkpoint_json,
            polish_guard=not args.no_polish_guard,
            source_lang=args.source_lang,
            target_lang=args.target_lang,
            tm=tm_store,
            segment_ledger=segment_ledger,
            tm_fuzzy_threshold=max(0.0, min(1.0, float(args.tm_fuzzy_threshold))),
        )
    finally:
        if segment_ledger is not None:
            segment_ledger.close()
        if tm_store is not None:
            tm_store.close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
