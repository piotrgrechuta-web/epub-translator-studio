#!/usr/bin/env python3
# -*- coding: utf-8 -*-

from __future__ import annotations

import argparse
import random
import string
import time
from pathlib import Path

from translation_engine import TranslationMemory


def _rand_words(n: int) -> str:
    words = []
    for _ in range(n):
        wlen = random.randint(3, 10)
        w = "".join(random.choice(string.ascii_lowercase) for _ in range(wlen))
        words.append(w)
    return " ".join(words)


def main() -> int:
    ap = argparse.ArgumentParser(description="Benchmark TranslationMemory")
    ap.add_argument("--db", type=Path, default=Path("tm_bench.db"))
    ap.add_argument("--rows", type=int, default=20000)
    ap.add_argument("--lookups", type=int, default=300)
    args = ap.parse_args()

    random.seed(42)
    tm = TranslationMemory(args.db, project_id=999)
    try:
        print(f"[BENCH] inserting rows={args.rows}")
        t0 = time.perf_counter()
        samples = []
        for i in range(args.rows):
            s = _rand_words(random.randint(8, 20))
            t = f"pl_{s}"
            tm.add(s, t, score=1.0)
            if i % max(1, args.rows // 20) == 0:
                samples.append(s)
        t1 = time.perf_counter()
        print(f"[BENCH] insert time: {t1 - t0:.2f}s")

        if not samples:
            samples = [_rand_words(12)]
        print(f"[BENCH] lookup count={args.lookups}")
        t2 = time.perf_counter()
        hits = 0
        for _ in range(args.lookups):
            q = random.choice(samples)
            if random.random() < 0.5:
                q = q + " extra"
            res = tm.lookup(q, fuzzy_threshold=0.80)
            if res:
                hits += 1
        t3 = time.perf_counter()
        per = (t3 - t2) / max(1, args.lookups)
        print(f"[BENCH] lookup total: {t3 - t2:.3f}s | per lookup: {per*1000:.2f} ms | hits={hits}/{args.lookups}")
    finally:
        tm.close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

