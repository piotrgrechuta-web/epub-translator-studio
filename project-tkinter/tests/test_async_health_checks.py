from __future__ import annotations

import asyncio
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

import provider_runtime  # noqa: E402
import runtime_core  # noqa: E402


def test_gather_provider_health_async_checks_both_providers(monkeypatch) -> None:
    def fake_ollama(host: str, timeout_s: int = 10) -> runtime_core.ProviderHealthStatus:
        return runtime_core.ProviderHealthStatus(
            provider="ollama",
            state="ok",
            latency_ms=11,
            model_count=3,
            detail=host,
        )

    def fake_google(api_key: str, timeout_s: int = 10) -> runtime_core.ProviderHealthStatus:
        return runtime_core.ProviderHealthStatus(
            provider="google",
            state="ok",
            latency_ms=13,
            model_count=7,
            detail="models endpoint",
        )

    monkeypatch.setattr(runtime_core, "check_ollama_health", fake_ollama)
    monkeypatch.setattr(runtime_core, "check_google_health", fake_google)

    out = asyncio.run(
        runtime_core.gather_provider_health_async(
            ollama_host="http://127.0.0.1:11434",
            google_api_key="x",
            timeout_s=5,
            include_ollama=True,
            include_google=True,
        )
    )

    assert out["ollama"].state == "ok"
    assert out["ollama"].model_count == 3
    assert out["google"].state == "ok"
    assert out["google"].model_count == 7


def test_check_google_health_returns_skip_without_key() -> None:
    out = runtime_core.check_google_health("", timeout_s=3)
    assert out.provider == "google"
    assert out.state == "skip"
    assert out.model_count == 0


def test_plugin_health_check_many_async_preserves_input_order(monkeypatch) -> None:
    async def fake_health(command: str, cwd: Path, timeout_s: int = 10) -> tuple[bool, str]:
        if command.endswith("slow"):
            await asyncio.sleep(0.02)
        return True, f"ok:{command}"

    monkeypatch.setattr(provider_runtime, "plugin_health_check_async", fake_health)

    cmds = ["cmd-fast-1", "cmd-slow", "cmd-fast-2"]
    rows = asyncio.run(
        provider_runtime.plugin_health_check_many_async(
            commands=cmds,
            cwd=Path("."),
            timeout_s=5,
            max_concurrency=3,
        )
    )

    assert [r.command for r in rows] == cmds
    assert all(r.ok for r in rows)
    assert rows[1].output == "ok:cmd-slow"

