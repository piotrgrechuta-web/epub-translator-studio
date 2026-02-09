from __future__ import annotations

import sys
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[1]
SCRIPTS_DIR = PROJECT_ROOT / "scripts"
if str(SCRIPTS_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPTS_DIR))

import generate_release_notes as grn  # noqa: E402


def test_extract_changelog_unreleased(tmp_path: Path) -> None:
    changelog = tmp_path / "CHANGELOG.md"
    changelog.write_text(
        "\n".join(
            [
                "# Changelog",
                "",
                "## [Unreleased]",
                "- Added: runtime metrics export.",
                "- Fixed: retry counter edge case.",
                "",
                "## [0.6.0] - 2026-02-08",
                "- Previous release entry.",
            ]
        ),
        encoding="utf-8",
    )
    lines = grn._extract_changelog_unreleased(changelog)  # noqa: SLF001
    assert lines == ["- Added: runtime metrics export.", "- Fixed: retry counter edge case."]


def test_build_release_notes_contains_required_sections() -> None:
    out = grn.build_release_notes(
        title="Release Draft",
        commits=["abc123 feat: improve telemetry"],
        changelog_unreleased=["- Added: CI release draft workflow."],
        metrics={"global_done": 12, "global_total": 18},
        from_ref="v0.6.0",
        to_ref="HEAD",
    )
    assert "## Zmiany" in out
    assert "## Ryzyka" in out
    assert "## Migracja" in out
    assert "## Testy" in out
    assert "## Runtime Metrics" in out
    assert "```json" in out
    assert "global_done" in out
