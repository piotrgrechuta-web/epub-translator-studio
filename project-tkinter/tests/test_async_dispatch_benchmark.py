from __future__ import annotations

import sys
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[1]
SCRIPTS_DIR = PROJECT_ROOT / "scripts"
if str(SCRIPTS_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPTS_DIR))

from benchmark_async_dispatch import BenchRow, build_markdown  # noqa: E402


def test_build_markdown_contains_table_and_speedup() -> None:
    rows = [
        BenchRow(io_concurrency=1, repeat=1, elapsed_s=1.20, batches=10, segments=20),
        BenchRow(io_concurrency=1, repeat=2, elapsed_s=1.10, batches=10, segments=20),
        BenchRow(io_concurrency=2, repeat=1, elapsed_s=0.70, batches=10, segments=20),
        BenchRow(io_concurrency=2, repeat=2, elapsed_s=0.68, batches=10, segments=20),
    ]
    out = build_markdown(
        rows=rows,
        batches=10,
        segs_per_batch=2,
        delay_s=0.05,
        dispatch_interval_s=0.0,
        python_version="3.11.9",
    )
    assert "# M8#45 Async Dispatch Benchmark" in out
    assert "| io_concurrency | mean_s | min_s | max_s | speedup_vs_1x |" in out
    assert "| 2 |" in out
    assert "x |" in out
