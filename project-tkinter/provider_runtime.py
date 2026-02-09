#!/usr/bin/env python3
# -*- coding: utf-8 -*-

from __future__ import annotations

import asyncio
import hashlib
import json
import re
import shlex
import subprocess
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Dict, List, Optional, Tuple


@dataclass
class ProviderPlugin:
    path: Path
    name: str
    command_template: str


@dataclass
class PluginHealthResult:
    command: str
    ok: bool
    output: str
    duration_ms: int


_TPL_RE = re.compile(r"\{([a-zA-Z_][a-zA-Z0-9_]*)\}")
_ALLOWED_PLACEHOLDERS = {"model", "prompt_file", "input_file", "output_file"}
_ALLOWED_LAUNCHERS = {"python", "python.exe", "py", "py.exe"}
_PROVIDERS_DIR_NAME = "providers"
_MANIFEST_FILE_NAME = "manifest.json"
_SHA256_RE = re.compile(r"^[0-9a-f]{64}$")


def _is_relative(path_str: str) -> bool:
    p = Path(path_str)
    return not p.is_absolute() and ".." not in p.parts


def _validate_command_tokens(tokens: List[str], cwd: Optional[Path] = None) -> None:
    if not tokens:
        raise ValueError("Empty command")
    launcher = Path(tokens[0]).name.lower().strip()
    if launcher not in _ALLOWED_LAUNCHERS:
        raise ValueError(f"Unsupported launcher '{tokens[0]}'. Allowed: python/py")
    if len(tokens) < 2:
        raise ValueError("Command must include script path as second token")
    script = tokens[1].strip()
    if not script:
        raise ValueError("Empty script path")
    if not _is_relative(script):
        raise ValueError("Script path must be relative and cannot contain '..'")
    script_path = Path(script)
    if script_path.suffix.lower() != ".py":
        raise ValueError("Script must be a .py file")
    parts_lower = [p.lower() for p in script_path.parts]
    if _PROVIDERS_DIR_NAME not in parts_lower:
        raise ValueError("Script must be located under providers/")
    if cwd is not None:
        base = cwd.resolve()
        full = (base / script_path).resolve()
        providers_root = (base / _PROVIDERS_DIR_NAME).resolve()
        try:
            full.relative_to(providers_root)
        except Exception:
            raise ValueError("Script must resolve under providers/ directory")


def validate_command_template(command_template: str) -> None:
    cmd = str(command_template or "").strip()
    if not cmd:
        raise ValueError("Missing 'command_template'")
    if "\n" in cmd or "\r" in cmd:
        raise ValueError("command_template must be single-line")
    placeholders = set(_TPL_RE.findall(cmd))
    unknown = placeholders - _ALLOWED_PLACEHOLDERS
    if unknown:
        raise ValueError(f"Unsupported placeholders: {', '.join(sorted(unknown))}")
    tokens = shlex.split(cmd)
    _validate_command_tokens(tokens)


def load_plugins(plugins_dir: Path) -> Tuple[List[ProviderPlugin], List[str]]:
    plugins: List[ProviderPlugin] = []
    errors: List[str] = []
    if not plugins_dir.exists():
        return plugins, errors
    for p in sorted(plugins_dir.glob("*.json")):
        if p.name.lower() == _MANIFEST_FILE_NAME:
            continue
        try:
            data = json.loads(p.read_text(encoding="utf-8"))
            if not isinstance(data, dict):
                raise ValueError("JSON root must be object")
            name = str(data.get("name", "")).strip()
            cmd = str(data.get("command_template", "")).strip()
            if not name:
                raise ValueError("Missing 'name'")
            validate_command_template(cmd)
            plugins.append(ProviderPlugin(path=p, name=name, command_template=cmd))
        except Exception as e:
            errors.append(f"{p.name}: {e}")
    return plugins, errors


def render_command(template: str, values: Dict[str, str]) -> str:
    out = template
    for k, v in values.items():
        out = out.replace("{" + k + "}", v)
    return out


def _sha256_file(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as f:
        for chunk in iter(lambda: f.read(1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()


def _normalize_manifest_key(raw: str) -> str:
    p = str(raw or "").strip().replace("\\", "/")
    while p.startswith("./"):
        p = p[2:]
    if p.lower().startswith(_PROVIDERS_DIR_NAME + "/"):
        p = p[len(_PROVIDERS_DIR_NAME) + 1 :]
    return p


def _resolve_script_for_cwd(tokens: List[str], cwd: Path) -> Tuple[Path, str]:
    _validate_command_tokens(tokens, cwd=cwd)
    providers_root = (cwd.resolve() / _PROVIDERS_DIR_NAME).resolve()
    script_path = Path(tokens[1].strip())
    full = (cwd.resolve() / script_path).resolve()
    rel = full.relative_to(providers_root).as_posix()
    return full, rel


def load_provider_manifest(providers_dir: Path) -> Dict[str, str]:
    mf = providers_dir / _MANIFEST_FILE_NAME
    if not mf.exists():
        raise ValueError(f"Missing providers manifest: {mf}")
    try:
        raw = json.loads(mf.read_text(encoding="utf-8"))
    except Exception as e:
        raise ValueError(f"Invalid manifest JSON: {e}")
    if isinstance(raw, dict) and isinstance(raw.get("files"), dict):
        table = raw.get("files", {})
    elif isinstance(raw, dict):
        table = raw
    else:
        raise ValueError("Manifest root must be object")
    out: Dict[str, str] = {}
    for k, v in table.items():
        key = _normalize_manifest_key(str(k))
        hv = str(v).strip().lower()
        if not key:
            continue
        if not _SHA256_RE.fullmatch(hv):
            raise ValueError(f"Invalid SHA-256 for '{k}'")
        out[key] = hv
    if not out:
        raise ValueError("Manifest has no valid file hashes")
    return out


def verify_command_integrity(command: str, cwd: Path) -> None:
    cmd = shlex.split(command)
    full, rel = _resolve_script_for_cwd(cmd, cwd)
    providers_dir = (cwd.resolve() / _PROVIDERS_DIR_NAME).resolve()
    manifest = load_provider_manifest(providers_dir)
    expected = manifest.get(rel)
    if not expected:
        raise ValueError(f"Script not present in manifest: {rel}")
    if not full.exists():
        raise ValueError(f"Script file not found: {full}")
    actual = _sha256_file(full)
    if actual.lower() != expected.lower():
        raise ValueError(f"Script hash mismatch for {rel}")


def rebuild_provider_manifest(providers_dir: Path) -> Path:
    providers_dir.mkdir(parents=True, exist_ok=True)
    files: Dict[str, str] = {}
    for p in sorted(providers_dir.rglob("*.py")):
        if not p.is_file():
            continue
        rel = p.relative_to(providers_dir).as_posix()
        files[rel] = _sha256_file(p)
    payload = {
        "version": 1,
        "files": files,
    }
    mf = providers_dir / _MANIFEST_FILE_NAME
    mf.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return mf


def validate_plugins_integrity(plugins: List[ProviderPlugin], cwd: Path) -> List[str]:
    errors: List[str] = []
    for pl in plugins:
        try:
            verify_command_integrity(pl.command_template, cwd=cwd)
        except Exception as e:
            errors.append(f"{pl.path.name}: {e}")
    return errors


def plugin_health_check(command: str, cwd: Path, timeout_s: int = 10) -> Tuple[bool, str]:
    try:
        verify_command_integrity(command, cwd=cwd)
        cmd = shlex.split(command)
        p = subprocess.run(cmd, cwd=str(cwd), capture_output=True, text=True, timeout=timeout_s)
        out = (p.stdout or "") + "\n" + (p.stderr or "")
        if p.returncode == 0:
            return True, out.strip()
        return False, out.strip() or f"exit={p.returncode}"
    except Exception as e:
        return False, str(e)


async def plugin_health_check_async(command: str, cwd: Path, timeout_s: int = 10) -> Tuple[bool, str]:
    try:
        verify_command_integrity(command, cwd=cwd)
        cmd = shlex.split(command)
        try:
            p = await asyncio.create_subprocess_exec(
                *cmd,
                cwd=str(cwd),
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
            )
        except NotImplementedError:
            return await asyncio.to_thread(plugin_health_check, command, cwd, timeout_s)
        try:
            out_b, err_b = await asyncio.wait_for(p.communicate(), timeout=float(timeout_s))
        except asyncio.TimeoutError:
            p.kill()
            await p.communicate()
            return False, f"timeout after {int(timeout_s)}s"
        out = (out_b or b"").decode("utf-8", errors="replace") + "\n" + (err_b or b"").decode("utf-8", errors="replace")
        if int(p.returncode or 0) == 0:
            return True, out.strip()
        return False, out.strip() or f"exit={p.returncode}"
    except Exception as e:
        return False, str(e)


async def plugin_health_check_many_async(
    commands: List[str],
    cwd: Path,
    timeout_s: int = 10,
    max_concurrency: int = 4,
) -> List[PluginHealthResult]:
    sem = asyncio.Semaphore(max(1, int(max_concurrency)))
    results: List[Optional[PluginHealthResult]] = [None for _ in commands]

    async def _run_one(idx: int, command: str) -> None:
        started = time.perf_counter()
        async with sem:
            ok, out = await plugin_health_check_async(command, cwd=cwd, timeout_s=timeout_s)
        elapsed_ms = int((time.perf_counter() - started) * 1000.0)
        results[idx] = PluginHealthResult(
            command=command,
            ok=bool(ok),
            output=str(out or "").strip(),
            duration_ms=elapsed_ms,
        )

    await asyncio.gather(*[asyncio.create_task(_run_one(i, cmd)) for i, cmd in enumerate(commands)])
    return [r for r in results if r is not None]


def plugin_health_check_many(
    commands: List[str],
    cwd: Path,
    timeout_s: int = 10,
    max_concurrency: int = 4,
) -> List[PluginHealthResult]:
    return asyncio.run(
        plugin_health_check_many_async(
            commands=commands,
            cwd=cwd,
            timeout_s=timeout_s,
            max_concurrency=max_concurrency,
        )
    )
