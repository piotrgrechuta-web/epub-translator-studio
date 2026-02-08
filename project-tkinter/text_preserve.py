#!/usr/bin/env python3
# -*- coding: utf-8 -*-

from __future__ import annotations

from typing import List, Tuple

from lxml import etree


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
