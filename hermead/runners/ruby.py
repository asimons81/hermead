"""Ruby runner: rubocop, standardrb, brakeman.

Each function takes (file_path, project_root, **kwargs) and returns a list
of finding dicts. Missing tools skip gracefully; hooks never install gems or
otherwise modify the user's environment.
"""

from __future__ import annotations

import json
import re
import shutil
import subprocess
from pathlib import Path
from typing import Any

from hermead.runners import register_runner

# ── Helpers ────────────────────────────────────────────────────────────────


def _has_tool(name: str) -> bool:
    return shutil.which(name) is not None


def _ensure_tool(tool: str) -> bool:
    """Return whether *tool* is already available without installing it."""
    return _has_tool(tool)


def _print_run(
    args: list[str],
    cwd: str | None,
    timeout: int = 60,
) -> subprocess.CompletedProcess:
    return subprocess.run(
        args,
        capture_output=True,
        text=True,
        timeout=timeout,
        cwd=cwd,
        check=False,
    )


# ── Severity normalisation ─────────────────────────────────────────────────

_RUBOCOP_SEVERITY = {
    "fatal": "error",
    "error": "error",
    "warning": "warning",
    "convention": "style",
    "refactor": "info",
    "info": "info",
}

_BRAKEMAN_CONFIDENCE = {
    "High": "error",
    "Medium": "warning",
    "Weak": "info",
}

# Regex for standardrb progress output:
#   path/file.rb:line:col: C: Style/FrozenStringLiteralComment: Some message
_STANDARDRB_LINE_RE = re.compile(
    r"^(.+?):(\d+):(\d+):\s+\w:\s+([^:]+):\s+(.*)"
)


# ── Lint: rubocop ──────────────────────────────────────────────────────────


def _run_lint(
    file_path: str,
    project_root: str | Path,
    **kwargs: Any,
) -> list[dict[str, Any]]:
    """Run rubocop with JSON output --format json."""
    if not _ensure_tool("rubocop"):
        return []

    try:
        proc = _print_run(
            ["rubocop", "--format", "json", "--no-color", str(file_path)],
            cwd=str(project_root),
            timeout=60,
        )
    except (subprocess.TimeoutExpired, FileNotFoundError, OSError):
        return []

    if not proc.stdout.strip():
        return []

    try:
        data = json.loads(proc.stdout)
    except (json.JSONDecodeError, ValueError):
        return []

    results: list[dict[str, Any]] = []
    for file_result in data.get("files", []):
        for offense in file_result.get("offenses", []):
            sev_raw = (offense.get("severity") or "").lower()
            severity = _RUBOCOP_SEVERITY.get(sev_raw, "info")
            loc = offense.get("location", {})
            results.append({
                "tool": "rubocop",
                "severity": severity,
                "line": loc.get("line"),
                "col": loc.get("column"),
                "message": offense.get("message", ""),
                "code": offense.get("cop_name"),
            })

    return results


# ── Format check: standardrb ────────────────────────────────────────────────


def _run_format_check(
    file_path: str,
    project_root: str | Path,
    **kwargs: Any,
) -> list[dict[str, Any]]:
    """Run standardrb --no-correct and parse progress-format output."""
    if not _ensure_tool("standardrb"):
        return []

    try:
        proc = _print_run(
            [
                "standardrb",
                "--no-correct",
                "--format",
                "progress",
                str(file_path),
            ],
            cwd=str(project_root),
            timeout=60,
        )
    except (subprocess.TimeoutExpired, FileNotFoundError, OSError):
        return []

    if proc.returncode == 0:
        return []

    results: list[dict[str, Any]] = []
    target_abs = Path(file_path).resolve()

    for line in (proc.stdout + "\n" + proc.stderr).splitlines():
        line = line.strip()
        if not line:
            continue
        m = _STANDARDRB_LINE_RE.match(line)
        if m:
            source, raw_line, raw_col, cop_name, message = m.groups()
            # Resolve reported path against project root
            source_path = (Path(project_root) / source).resolve()
            if source_path != target_abs:
                continue
            results.append({
                "tool": "standardrb",
                "severity": "style",
                "line": int(raw_line),
                "col": int(raw_col),
                "message": message.strip(),
                "code": cop_name.strip(),
            })

    return results


# ── Security: brakeman ──────────────────────────────────────────────────────


def _run_security(
    file_path: str,
    project_root: str | Path,
    **kwargs: Any,
) -> list[dict[str, Any]]:
    """Run brakeman -f json and filter warnings for the given file."""
    if not _ensure_tool("brakeman"):
        return []

    try:
        proc = _print_run(
            ["brakeman", "-f", "json", "--no-progress", str(project_root)],
            cwd=str(project_root),
            timeout=120,
        )
    except (subprocess.TimeoutExpired, FileNotFoundError, OSError):
        return []

    if not proc.stdout.strip():
        return []

    try:
        data = json.loads(proc.stdout)
    except (json.JSONDecodeError, ValueError):
        return []

    results: list[dict[str, Any]] = []
    target_abs = Path(file_path).resolve()

    for warning in data.get("warnings", []):
        reported_file = warning.get("file", "")
        if not reported_file:
            continue
        warning_path = (Path(project_root) / reported_file).resolve()
        if warning_path != target_abs:
            continue

        confidence = warning.get("confidence", "Weak")
        severity = _BRAKEMAN_CONFIDENCE.get(confidence, "info")

        results.append({
            "tool": "brakeman",
            "severity": severity,
            "line": warning.get("line"),
            "col": None,
            "message": warning.get("message", ""),
            "code": warning.get("warning_type"),
        })

    return results


# ── Type check: not available for Ruby ──────────────────────────────────────


def _run_type_check(
    file_path: str,
    project_root: str | Path,
    **kwargs: Any,
) -> list[dict[str, Any]]:
    """Ruby has no built-in type checker — always returns empty."""
    return []


# ── Register ────────────────────────────────────────────────────────────────

register_runner("ruby", "run_lint", _run_lint)
register_runner("ruby", "run_format_check", _run_format_check)
register_runner("ruby", "run_security", _run_security)
register_runner("ruby", "run_type_check", _run_type_check)
