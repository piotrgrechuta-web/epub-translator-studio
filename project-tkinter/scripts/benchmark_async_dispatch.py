#!/usr/bin/env python3
from __future__ import annotations

import argparse
import asyncio
import statistics
import sys
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Dict, List, Sequence, Tuple

from lxml import etree


SCRIPT_DIR = Path(__file__).resolve().parent
PROJECT_DIR = SCRIPT_DIR.parent
if str(PROJECT_DIR) not in sys.path:
    sys.path.insert(0, str(PROJECT_DIR))

from translation_engine import Segment, dispatch_translation_batches_async  # noqa: E402


@dataclass
class BenchRow:
    io_concurrency: int
    repeat: int
    elapsed_s: float
    batches: int
    segments: int


def _build_jobs(*, batches: int, segs_per_batch: int) -> List[Tuple[int, List[Segment], str]]:
    jobs: List[Tuple[int, List[Segment], str]] = []
    for batch_no in range(1, batches + 1):
        batch: List[Segment] = []
        for idx in range(segs_per_batch):
            seg_id = f"b{batch_no:03d}-s{idx:03d}"
            el = etree.Element("p")
            inner = f"segment {seg_id}"
            batch.append(Segment(idx=idx, el=el, seg_id=seg_id, inner=inner, plain=inner))
        jobs.append((batch_no, batch, f"[B#{batch_no}]"))
    return jobs


def _fake_translate_fn(delay_s: float):
    def _run(batch: List[Segment], debug_prefix: str) -> Dict[str, str]:
        _ = debug_prefix
        time.sleep(max(0.0, delay_s))
        return {seg.seg_id: f"tr::{seg.seg_id}" for seg in batch}

    return _run


def _run_once(
    *,
    jobs: List[Tuple[int, List[Segment], str]],
    io_concurrency: int,
    delay_s: float,
    dispatch_interval_s: float,
) -> float:
    t0 = time.perf_counter()
    results = asyncio.run(
        dispatch_translation_batches_async(
            jobs=jobs,
            translate_fn=_fake_translate_fn(delay_s),
            io_concurrency=io_concurrency,
            dispatch_interval_s=dispatch_interval_s,
        )
    )
    elapsed = time.perf_counter() - t0

    expected = sum(len(batch) for _, batch, _ in jobs)
    total = 0
    for row in results:
        if row.error is not None:
            raise RuntimeError(f"dispatch failed for batch={row.batch_no}: {row.error}")
        total += len(row.mapping)
    if total != expected:
        raise RuntimeError(f"invalid dispatch result size: expected={expected}, got={total}")
    return elapsed


def _fmt(n: float) -> str:
    return f"{n:.4f}"


def build_markdown(
    *,
    rows: List[BenchRow],
    batches: int,
    segs_per_batch: int,
    delay_s: float,
    dispatch_interval_s: float,
    python_version: str,
) -> str:
    groups: Dict[int, List[float]] = {}
    for row in rows:
        groups.setdefault(int(row.io_concurrency), []).append(float(row.elapsed_s))

    base = statistics.mean(groups[min(groups.keys())])
    lines: List[str] = []
    lines.append("# M8#45 Async Dispatch Benchmark")
    lines.append("")
    lines.append("## Setup")
    lines.append(f"- python: `{python_version}`")
    lines.append(f"- batches: `{batches}`")
    lines.append(f"- segments_per_batch: `{segs_per_batch}`")
    lines.append(f"- synthetic_translate_delay_s: `{_fmt(delay_s)}`")
    lines.append(f"- dispatch_interval_s: `{_fmt(dispatch_interval_s)}`")
    lines.append("")
    lines.append("## Results")
    lines.append("")
    lines.append("| io_concurrency | mean_s | min_s | max_s | speedup_vs_1x |")
    lines.append("|---:|---:|---:|---:|---:|")
    for c in sorted(groups.keys()):
        vals = groups[c]
        mean_v = statistics.mean(vals)
        min_v = min(vals)
        max_v = max(vals)
        speedup = base / mean_v if mean_v > 0 else 0.0
        lines.append(f"| {c} | {_fmt(mean_v)} | {_fmt(min_v)} | {_fmt(max_v)} | {_fmt(speedup)}x |")
    lines.append("")
    lines.append("## Raw Runs")
    lines.append("")
    lines.append("| io_concurrency | repeat | elapsed_s | batches | segments |")
    lines.append("|---:|---:|---:|---:|---:|")
    for row in rows:
        lines.append(
            f"| {row.io_concurrency} | {row.repeat} | {_fmt(row.elapsed_s)} | {row.batches} | {row.segments} |"
        )
    lines.append("")
    return "\n".join(lines)


def main() -> int:
    parser = argparse.ArgumentParser(description="Benchmark async translation dispatcher (M8#45).")
    parser.add_argument("--batches", type=int, default=40)
    parser.add_argument("--segments-per-batch", type=int, default=3)
    parser.add_argument("--delay-ms", type=float, default=80.0, help="Synthetic translation delay per batch in milliseconds.")
    parser.add_argument("--dispatch-interval-ms", type=float, default=0.0)
    parser.add_argument("--concurrency", type=str, default="1,2,4")
    parser.add_argument("--repeats", type=int, default=3)
    parser.add_argument(
        "--out",
        type=Path,
        default=Path("docs/benchmarks/M8-45-async-dispatch-benchmark.md"),
    )
    args = parser.parse_args()

    conc_values: List[int] = []
    for part in str(args.concurrency).split(","):
        p = part.strip()
        if not p:
            continue
        conc_values.append(max(1, int(p)))
    if not conc_values:
        raise SystemExit("No concurrency values provided.")

    jobs = _build_jobs(batches=max(1, int(args.batches)), segs_per_batch=max(1, int(args.segments_per_batch)))
    delay_s = max(0.0, float(args.delay_ms) / 1000.0)
    dispatch_interval_s = max(0.0, float(args.dispatch_interval_ms) / 1000.0)
    total_segments = sum(len(batch) for _, batch, _ in jobs)

    rows: List[BenchRow] = []
    for c in conc_values:
        for rep in range(1, max(1, int(args.repeats)) + 1):
            elapsed = _run_once(
                jobs=jobs,
                io_concurrency=c,
                delay_s=delay_s,
                dispatch_interval_s=dispatch_interval_s,
            )
            row = BenchRow(
                io_concurrency=c,
                repeat=rep,
                elapsed_s=elapsed,
                batches=len(jobs),
                segments=total_segments,
            )
            rows.append(row)
            print(
                f"[bench] io={row.io_concurrency} rep={row.repeat} "
                f"elapsed={row.elapsed_s:.4f}s batches={row.batches} segments={row.segments}"
            )

    md = build_markdown(
        rows=rows,
        batches=len(jobs),
        segs_per_batch=max(1, int(args.segments_per_batch)),
        delay_s=delay_s,
        dispatch_interval_s=dispatch_interval_s,
        python_version=sys.version.split()[0],
    )
    out_path = PROJECT_DIR / args.out
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(md, encoding="utf-8")
    print(f"[bench] report written: {out_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
