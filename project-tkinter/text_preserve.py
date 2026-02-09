#!/usr/bin/env python3
# -*- coding: utf-8 -*-

from __future__ import annotations

import re
from typing import Dict, List, Tuple

from lxml import etree

INLINE_TOKEN_RE = re.compile(r"\[\[TAG\d{3}\]\]")


def iter_text_slots(el: etree._Element) -> List[Tuple[etree._Element, str, str]]:
    slots: List[Tuple[etree._Element, str, str]] = []
    slots.append((el, "text", str(el.text or "")))
    for node in el.iterdescendants():
        slots.append((node, "text", str(node.text or "")))
        slots.append((node, "tail", str(node.tail or "")))
    return slots


def set_text_preserving_inline(el: etree._Element, new_text: str) -> None:
    """Aktualizuje tekst segmentu bez usuwania inline tagow i atrybutow."""
    slots = iter_text_slots(el)
    if not slots:
        el.text = str(new_text or "")
        return
    text = str(new_text or "")
    total = sum(len(orig) for _, _, orig in slots)
    if total <= 0:
        obj, attr, _ = slots[0]
        setattr(obj, attr, text)
        for obj, attr, _ in slots[1:]:
            setattr(obj, attr, "")
        return

    pos = 0
    for idx, (obj, attr, orig) in enumerate(slots):
        if idx == len(slots) - 1:
            piece = text[pos:]
        else:
            take = len(orig)
            piece = text[pos: pos + take]
            pos += take
        setattr(obj, attr, piece)


def _tokenize_node_markup(
    node: etree._Element,
    parts: List[str],
    token_map: Dict[str, str],
    token_no: List[int],
) -> None:
    raw = etree.tostring(node, encoding="unicode", method="xml", with_tail=False)
    if not raw:
        return
    open_m = re.match(r"^<[^>]+>", raw, flags=re.DOTALL)
    close_m = re.search(r"</[^>]+>\s*$", raw, flags=re.DOTALL)
    if not open_m or not close_m:
        token = f"[[TAG{token_no[0]:03d}]]"
        token_no[0] += 1
        token_map[token] = raw
        parts.append(token)
        return

    open_token = f"[[TAG{token_no[0]:03d}]]"
    token_no[0] += 1
    close_token = f"[[TAG{token_no[0]:03d}]]"
    token_no[0] += 1
    token_map[open_token] = open_m.group(0)
    token_map[close_token] = close_m.group(0)
    parts.append(open_token)
    if node.text:
        parts.append(str(node.text))
    for child in list(node):
        _tokenize_node_markup(child, parts, token_map, token_no)
        if child.tail:
            parts.append(str(child.tail))
    parts.append(close_token)


def tokenize_inline_markup(el: etree._Element) -> Tuple[str, Dict[str, str]]:
    """Returns editable text with immutable token chips for inline tags."""
    token_map: Dict[str, str] = {}
    parts: List[str] = []
    token_no = [1]
    if el.text:
        parts.append(str(el.text))
    for child in list(el):
        _tokenize_node_markup(child, parts, token_map, token_no)
        if child.tail:
            parts.append(str(child.tail))
    return "".join(parts), token_map


def apply_tokenized_inline_markup(el: etree._Element, text: str, token_map: Dict[str, str]) -> None:
    rendered_parts: List[str] = []
    pos = 0
    for m in INLINE_TOKEN_RE.finditer(text):
        if m.start() > pos:
            rendered_parts.append(text[pos:m.start()])
        token = m.group(0)
        rendered_parts.append(str(token_map.get(token, token)))
        pos = m.end()
    if pos < len(text):
        rendered_parts.append(text[pos:])
    payload = "".join(rendered_parts)
    wrapped = f"<wrapper>{payload}</wrapper>"
    try:
        root = etree.fromstring(wrapped.encode("utf-8"), parser=etree.XMLParser(recover=False, resolve_entities=False))
    except Exception as e:
        raise ValueError(f"Invalid tokenized inline payload: {e}") from e
    for c in list(el):
        el.remove(c)
    el.text = root.text
    for c in list(root):
        root.remove(c)
        el.append(c)
