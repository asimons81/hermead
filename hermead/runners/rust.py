"""Rust runner: cargo clippy + rustfmt.

Only available when ``Cargo.toml`` exists in the project root.
"""

from __future__ import annotations

import json
import shutil
import subprocess
import re
from pathlib import Path
from typing import Any

from hermead.runners import register_runner

# ── Helpers ────────────────────────────────────────────────────────────────


def _check_cargo_toml(project_root: str | Path) -> bool:
    return (Path(project_root) / "Cargo.toml").is_file()


def _has_tool(name: str) -> bool:
    return shutil.which(name) is not None


def _print_run(
    args: list[str], cwd: str | None, timeout: int = 300
) -> subprocess.CompletedProcess:
    return subprocess.run(
        args,
        capture_output=True,
        text=True,
        timeout=timeout,
        cwd=cwd,
    )


# ── Lint: cargo clippy ──────────────────────────────────────────────────


def _run_lint(
    file_path: str, project_root: str | Path, **kwargs: Any
) -> list[dict[str, Any]]:
    """Run ``cargo clippy --message-format=json`` and filter for the target file.

    Clippy is a project-level lint — we run it on the whole project and
    keep only diagnostics that reference *file_path*.
    """
    if not _has_tool("cargo") or not _check_cargo_toml(project_root):
        return []

    # Determine the file's relative path from the project root for matching
    file_abs = Path(file_path).resolve()
    proj_root = Path(project_root).resolve()
    try:
        rel_path = file_abs.relative_to(proj_root)
    except ValueError:
        rel_path = file_abs.name

    try:
        proc = _print_run(
            [
                "cargo",
                "clippy",
                "--message-format=json",
                "--quiet",
                "--",
                "-W",
                "clippy::all",
                "-W",
                "clippy::pedantic",
            ],
            cwd=str(proj_root),
            timeout=300,
        )
    except subprocess.TimeoutExpired:
        return []
    except FileNotFoundError:
        return []

    results: list[dict[str, Any]] = []
    for raw_line in proc.stdout.splitlines():
        raw_line = raw_line.strip()
        if not raw_line:
            continue

        # Cargo outputs JSON for diagnostics and non-JSON for progress
        if not raw_line.startswith("{"):
            continue

        try:
            msg = json.loads(raw_line)
        except json.JSONDecodeError:
            continue

        # We only care about compiler diagnostics
        if msg.get("reason") != "compiler-message":
            continue

        message = msg.get("message", {})
        spans = message.get("spans", [])
        if not spans:
            continue

        # Check if any span targets our file
        target_spans = [
            s
            for s in spans
            if s.get("file_name", "") in (
                str(file_abs),
                str(rel_path),
                str(file_abs.name),
            )
        ]
        if not target_spans:
            continue

        span = target_spans[0]
        level = (message.get("level") or "").lower()

        # Map level to our severity
        sev_map = {
            "error": "error",
            "warning": "warning",
            "help": "info",
            "note": "info",
            "style": "style",
        }
        severity = sev_map.get(level, "info")

        code_info = message.get("code", None) or {}
        code_str = code_info.get("code", "") if isinstance(code_info, dict) else ""

        results.append(
            {
                "tool": "clippy",
                "severity": severity,
                "line": span.get("line_start"),
                "col": span.get("column_start"),
                "message": message.get("rendered", message.get("message", "")),
                "code": code_str or None,
            }
        )

    return results


# ── Type check: rustc ─────────────────────────────────────────────────────


def _run_type_check(
    file_path: str, project_root: str | Path, **kwargs: Any
) -> list[dict[str, Any]]:
    """Run ``cargo check`` to type-check the project."""
    if not _has_tool("cargo") or not _check_cargo_toml(project_root):
        return []

    proj_root = Path(project_root).resolve()
    file_abs = Path(file_path).resolve()
    try:
        rel_path = file_abs.relative_to(proj_root)
    except ValueError:
        rel_path = file_abs.name

    try:
        proc = _print_run(
            ["cargo", "check", "--message-format=json", "--quiet"],
            cwd=str(proj_root),
            timeout=300,
        )
    except subprocess.TimeoutExpired:
        return []
    except FileNotFoundError:
        return []

    results: list[dict[str, Any]] = []
    for raw_line in proc.stdout.splitlines():
        raw_line = raw_line.strip()
        if not raw_line:
            continue
        if not raw_line.startswith("{"):
            continue

        try:
            msg = json.loads(raw_line)
        except json.JSONDecodeError:
            continue

        if msg.get("reason") != "compiler-message":
            continue

        message = msg.get("message", {})
        spans = message.get("spans", [])
        if not spans:
            continue

        target_spans = [
            s
            for s in spans
            if s.get("file_name", "") in (
                str(file_abs),
                str(rel_path),
                str(file_abs.name),
            )
        ]
        if not target_spans:
            continue

        span = target_spans[0]
        level = (message.get("level") or "").lower()
        sev_map = {
            "error": "error",
            "warning": "warning",
            "help": "info",
            "note": "info",
        }
        severity = sev_map.get(level, "info")

        code_info = message.get("code", None) or {}
        code_str = code_info.get("code", "") if isinstance(code_info, dict) else ""

        results.append(
            {
                "tool": "rustc",
                "severity": severity,
                "line": span.get("line_start"),
                "col": span.get("column_start"),
                "message": message.get("rendered", message.get("message", "")),
                "code": code_str or None,
            }
        )

    return results


# ── Formatter: rustfmt ──────────────────────────────────────────────────


def _run_format_check(
    file_path: str, project_root: str | Path, **kwargs: Any
) -> list[dict[str, Any]]:
    """Run ``rustfmt --check`` on the file.

    Exit code 1 means the file is not formatted.
    """
    if not _has_tool("rustfmt"):
        return []

    try:
        proc = _print_run(
            ["rustfmt", "--check", file_path],
            cwd=str(project_root),
            timeout=30,
        )
    except subprocess.TimeoutExpired:
        return []
    except FileNotFoundError:
        return []

    if proc.returncode == 0:
        return []

    return [
        {
            "tool": "rustfmt",
            "severity": "style",
            "line": None,
            "col": None,
            "message": "File is not rustfmt-formatted. Run `rustfmt` to fix.",
            "code": "rustfmt",
        }
    ]


# ── Security: cargo audit ────────────────────────────────────────────────


def _run_security(
    file_path: str, project_root: str | Path, **kwargs: Any
) -> list[dict[str, Any]]:
    """Run ``cargo audit`` on the project (dependency-level security check)."""
    if not _has_tool("cargo") or not _check_cargo_toml(project_root):
        return []

    try:
        proc = _print_run(
            ["cargo", "audit", "--json"],
            cwd=str(project_root),
            timeout=120,
        )
    except subprocess.TimeoutExpired:
        return []
    except FileNotFoundError:
        return []

    if not proc.stdout.strip():
        return []

    results: list[dict[str, Any]] = []
    try:
        data = json.loads(proc.stdout)
    except json.JSONDecodeError:
        return []

    for vuln in data.get("vulnerabilities", {}).get("list", []):
        advisory = vuln.get("advisory", {})
        pkg = vuln.get("package", {})

        results.append(
            {
                "tool": "cargo audit",
                "severity": "error",
                "line": None,
                "col": None,
                "message": (
                    f"{advisory.get('title', 'Unknown vulnerability')} "
                    f"in {pkg.get('name', '?')} {pkg.get('version', '?')}"
                ),
                "code": advisory.get("id", "RUSTSEC-?"),
            }
        )

    for warning in data.get("warnings", []):
        results.append(
            {
                "tool": "cargo audit",
                "severity": "warning",
                "line": None,
                "col": None,
                "message": warning.get("message", str(warning)),
                "code": "cargo audit",
            }
        )

    return results


# ── Register ──────────────────────────────────────────────────────────────

register_runner("rust", "run_lint", _run_lint)
register_runner("rust", "run_type_check", _run_type_check)
register_runner("rust", "run_format_check", _run_format_check)
register_runner("rust", "run_security", _run_security)
