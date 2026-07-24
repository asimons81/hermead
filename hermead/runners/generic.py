"""Generic runner: semgrep.

Applies to any file — semgrep scans for patterns based on its rules.
Never blocks: returns empty results gracefully if semgrep is unavailable.
"""

from __future__ import annotations

import json
import shutil
import subprocess
from pathlib import Path
from typing import Any

from hermead.runners import register_runner

# ── Helpers ────────────────────────────────────────────────────────────────


def _has_tool(name: str) -> bool:
    return shutil.which(name) is not None


def _print_run(
    args: list[str], cwd: str | None, timeout: int = 120
) -> subprocess.CompletedProcess:
    return subprocess.run(
        args,
        capture_output=True,
        text=True,
        timeout=timeout,
        cwd=cwd,
        check=False,
    )


# ── Lint: semgrep ─────────────────────────────────────────────────────────


def _run_lint(
    file_path: str, project_root: str | Path, **kwargs: Any
) -> list[dict[str, Any]]:
    """Run semgrep on the given file and parse JSON output.

    Returns empty list if semgrep is not installed.
    """
    if not _has_tool("semgrep"):
        return []

    try:
        proc = _print_run(
            [
                "semgrep",
                "--json",
                "--quiet",
                "--no-error-on-files",
                file_path,
            ],
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

    for result in data.get("results", []):
        severity = "warning"
        extra = result.get("extra", {})
        raw_sev = (extra.get("severity") or "").lower()

        # Map semgrep severity
        if raw_sev in ("error",):
            severity = "error"
        elif raw_sev in ("warning", "warn"):
            severity = "warning"
        elif raw_sev in ("info",):
            severity = "info"

        check_id = result.get("check_id", "") or ""

        # Get lines from extra.lines if available
        lines = extra.get("lines", "")

        results.append(
            {
                "tool": "semgrep",
                "severity": severity,
                "line": result.get("start", {}).get("line"),
                "col": result.get("start", {}).get("col"),
                "message": extra.get("message", extra.get("metavars", {}).get("$...MSG", {}).get("abstract_content", lines)[:200]),
                "code": check_id,
            }
        )

    return results


# ── Security: semgrep (same tool, runs again in case config varies) ──────


def _run_security(
    file_path: str, project_root: str | Path, **kwargs: Any
) -> list[dict[str, Any]]:
    """Run semgrep with ``--config auto`` or ``--config p/security-audit``.

    Falls back to regular semgrep if no security-specific config.
    """
    if not _has_tool("semgrep"):
        return []

    # Try security-specific config first
    configs = ["p/security-audit", "auto"]
    for cfg in configs:
        try:
            proc = _print_run(
                [
                    "semgrep",
                    "--json",
                    "--quiet",
                    "--no-error-on-files",
                    "--config",
                    cfg,
                    file_path,
                ],
                cwd=str(project_root),
                timeout=120,
            )
        except (subprocess.TimeoutExpired, FileNotFoundError):
            continue

        if proc.stdout.strip():
            break
    else:
        return []

    results: list[dict[str, Any]] = []
    try:
        data = json.loads(proc.stdout)
    except json.JSONDecodeError:
        return []

    for result in data.get("results", []):
        severity = "warning"
        extra = result.get("extra", {})
        raw_sev = (extra.get("severity") or "").lower()

        if raw_sev in ("error", "critical"):
            severity = "error"
        elif raw_sev in ("warning", "warn"):
            severity = "warning"
        else:
            severity = "info"

        check_id = result.get("check_id", "") or ""
        lines = extra.get("lines", "")

        results.append(
            {
                "tool": "semgrep",
                "severity": severity,
                "line": result.get("start", {}).get("line"),
                "col": result.get("start", {}).get("col"),
                "message": extra.get("message", lines[:200]),
                "code": check_id,
            }
        )

    return results


# ── Type check: None for generic ─────────────────────────────────────────


def _run_type_check(
    file_path: str, project_root: str | Path, **kwargs: Any
) -> list[dict[str, Any]]:
    """Generic has no type checker — always returns empty."""
    return []


# ── Format check: None for generic ──────────────────────────────────────


def _run_format_check(
    file_path: str, project_root: str | Path, **kwargs: Any
) -> list[dict[str, Any]]:
    """Generic has no formatter — always returns empty."""
    return []


# ── Register ──────────────────────────────────────────────────────────────

register_runner("generic", "run_lint", _run_lint)
register_runner("generic", "run_type_check", _run_type_check)
register_runner("generic", "run_format_check", _run_format_check)
register_runner("generic", "run_security", _run_security)
