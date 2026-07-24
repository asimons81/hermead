"""Shell runner: shellcheck + shfmt.

Targets: .sh, .bash, .zsh, .fish files.
Detects ``.shellcheckrc`` in project root for custom config.
"""

from __future__ import annotations

import json
import shutil
import subprocess
import re
from pathlib import Path
from typing import Any

from hermead.runners import register_runner

# Shell file extensions handled by this runner
SHELL_EXTS = {".sh", ".bash", ".zsh", ".fish"}

# ── Helpers ────────────────────────────────────────────────────────────────


def _has_tool(name: str) -> bool:
    return shutil.which(name) is not None


def _print_run(
    args: list[str], cwd: str | None, timeout: int = 60
) -> subprocess.CompletedProcess:
    return subprocess.run(
        args,
        capture_output=True,
        text=True,
        timeout=timeout,
        cwd=cwd,
    )


def _is_shell_file(file_path: str) -> bool:
    """Return True if the file has a recognised shell extension."""
    return Path(file_path).suffix.lower() in SHELL_EXTS


def _shellcheck_rc_path(project_root: str | Path) -> list[str]:
    """Return ``--source-path`` and optional ``--rcfile`` for shellcheck."""
    rcfile = Path(project_root) / ".shellcheckrc"
    args: list[str] = []
    if rcfile.is_file():
        args.extend(["--rcfile", str(rcfile)])
    # shellcheck tries to resolve source= relative to --source-path
    args.extend(["--source-path", str(project_root)])
    return args


# ── Lint: shellcheck ──────────────────────────────────────────────────────


def _run_lint(
    file_path: str, project_root: str | Path, **kwargs: Any
) -> list[dict[str, Any]]:
    """Run shellcheck with JSON output on the file."""
    if not _has_tool("shellcheck") or not _is_shell_file(file_path):
        return []

    try:
        proc = _print_run(
            [
                "shellcheck",
                "-f",
                "json",
                *_shellcheck_rc_path(project_root),
                file_path,
            ],
            cwd=str(project_root),
            timeout=30,
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

    for finding in data if isinstance(data, list) else data.get("comments", []):
        level = (finding.get("level") or "").lower()
        sev_map = {
            "error": "error",
            "warning": "warning",
            "info": "info",
            "style": "style",
        }
        severity = sev_map.get(level, "info")

        results.append(
            {
                "tool": "shellcheck",
                "severity": severity,
                "line": finding.get("line"),
                "col": finding.get("column"),
                "message": finding.get("message", ""),
                "code": finding.get("code", None),
            }
        )

    return results


# ── Format check: shfmt ─────────────────────────────────────────────────


def _run_format_check(
    file_path: str, project_root: str | Path, **kwargs: Any
) -> list[dict[str, Any]]:
    """Run shfmt in diff mode; any diff means the file needs formatting.

    shfmt supports -i (indent), -bn (binary ops like &&), -ci (switch indentation).
    We use defaults for a basic check.
    """
    if not _has_tool("shfmt") or not _is_shell_file(file_path):
        return []

    try:
        proc = _print_run(
            ["shfmt", "-d", file_path],
            cwd=str(project_root),
            timeout=30,
        )
    except subprocess.TimeoutExpired:
        return []
    except FileNotFoundError:
        return []

    if proc.returncode == 0 and not (proc.stdout or proc.stderr):
        return []

    return [
        {
            "tool": "shfmt",
            "severity": "style",
            "line": None,
            "col": None,
            "message": "File is not shfmt-formatted. Run `shfmt -w` to fix.",
            "code": "shfmt",
        }
    ]


# ── Type check: None for shell ────────────────────────────────────────────


def _run_type_check(
    file_path: str, project_root: str | Path, **kwargs: Any
) -> list[dict[str, Any]]:
    """Shell has no type checker — always returns empty."""
    return []


# ── Security: None for shell ─────────────────────────────────────────────


def _run_security(
    file_path: str, project_root: str | Path, **kwargs: Any
) -> list[dict[str, Any]]:
    """Shell has no dedicated security scanner — always returns empty."""
    return []


# ── Register ──────────────────────────────────────────────────────────────

register_runner("shell", "run_lint", _run_lint)
register_runner("shell", "run_type_check", _run_type_check)
register_runner("shell", "run_format_check", _run_format_check)
register_runner("shell", "run_security", _run_security)
