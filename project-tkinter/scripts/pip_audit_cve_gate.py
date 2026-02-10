#!/usr/bin/env python3
from __future__ import annotations

import json
import re
import sys
from pathlib import Path
from typing import Any, Dict, Iterable, List, Set


CVE_RE = re.compile(r"^CVE-\d{4}-\d+$", re.IGNORECASE)


def _collect_cves(rows: Iterable[Dict[str, Any]]) -> Set[str]:
    out: Set[str] = set()
    for dep in rows:
        vulns = dep.get("vulns")
        if not isinstance(vulns, list):
            continue
        for vuln in vulns:
            if not isinstance(vuln, dict):
                continue
            ids: List[str] = []
            raw_id = str(vuln.get("id") or "").strip()
            if raw_id:
                ids.append(raw_id)
            aliases = vuln.get("aliases")
            if isinstance(aliases, list):
                ids.extend(str(x or "").strip() for x in aliases)
            for v in ids:
                key = v.upper()
                if CVE_RE.match(key):
                    out.add(key)
    return out


def main() -> int:
    if len(sys.argv) < 2:
        print("Usage: pip_audit_cve_gate.py <pip-audit.json> [cve_threshold]")
        return 2
    report = Path(sys.argv[1])
    threshold = int(sys.argv[2]) if len(sys.argv) >= 3 else 1
    threshold = max(1, threshold)
    if not report.exists():
        print(f"[pip-audit-gate] report missing: {report}")
        return 2
    try:
        payload = json.loads(report.read_text(encoding="utf-8"))
    except Exception as e:
        print(f"[pip-audit-gate] invalid json: {e}")
        return 2
    if not isinstance(payload, list):
        print("[pip-audit-gate] report format mismatch (expected list)")
        return 2
    cves = sorted(_collect_cves(payload))
    count = len(cves)
    print(f"[pip-audit-gate] detected CVEs: {count}; threshold: {threshold}")
    if cves:
        print("[pip-audit-gate] CVE list:")
        for c in cves:
            print(f"- {c}")
    if count >= threshold:
        print("[pip-audit-gate] FAIL: CVE threshold exceeded.")
        return 1
    print("[pip-audit-gate] PASS: CVE threshold not reached.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
