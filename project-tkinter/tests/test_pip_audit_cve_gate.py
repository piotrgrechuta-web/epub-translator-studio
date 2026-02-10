from __future__ import annotations

import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from scripts.pip_audit_cve_gate import _collect_cves  # noqa: E402


def test_collect_cves_reads_ids_and_aliases() -> None:
    payload = [
        {
            "name": "pkg-a",
            "version": "1.0",
            "vulns": [
                {"id": "PYSEC-123", "aliases": ["CVE-2024-1111", "GHSA-xxx"]},
                {"id": "CVE-2024-2222", "aliases": []},
            ],
        },
        {
            "name": "pkg-b",
            "version": "2.0",
            "vulns": [{"id": "GHSA-abc", "aliases": ["not-cve"]}],
        },
    ]
    out = _collect_cves(payload)
    assert "CVE-2024-1111" in out
    assert "CVE-2024-2222" in out
    assert len(out) == 2
