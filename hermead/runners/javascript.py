"""JavaScript/TypeScript runner: eslint, prettier, tsc.

Each function takes ``(file_path, tool)`` and returns a list of findings
dicts. They skip gracefully when the tool is unavailable and return an
empty list on success.
"""

from __future__ import annotations

import json
import os
import re
import shutil
import subprocess
import sys
from pathlib import Path
from typing import Any


# ── Helpers ──────────────────────────────────────────────────────────────


def _find_js_project_root(file_path: str) -> Path | None:
    """Walk up from *file_path* looking for the first directory with package.json."""
    start = Path(file_path).resolve()
    for ancestor in [start] + list(start.parents):
        if not ancestor.is_dir():
            continue
        if (ancestor / "package.json").is_file():
            return ancestor
    return None


def _tool_installed(project_root: Path, tool: str) -> bool:
    """Return True if *tool* is available in the project's node_modules/.bin."""
    tool_bin = project_root / "node_modules" / ".bin"
    if sys.platform == "win32":
        return (tool_bin / f"{tool}.cmd").is_file() or (tool_bin / f"{tool}.ps1").is_file()
    return (tool_bin / tool).is_file() or (tool_bin / f"{tool}.js").is_file()


def _npx_available() -> bool:
    """Return True if npx is on PATH."""
    return shutil.which("npx") is not None


def _run_npx(
    args: list[str],
    cwd: str | Path | None = None,
    timeout: int = 60,
) -> subprocess.CompletedProcess:
    """Run npx *args* and return the CompletedProcess.

    Resolves the full path to npx (.CMD on Windows) so subprocess.run
    works correctly on all platforms.

    Raises FileNotFoundError if npx is not on PATH.
    """
    npx_path = shutil.which("npx")
    if npx_path is None:
        raise FileNotFoundError("npx not found on PATH")
    cmd = [npx_path, "--no-install", *args]
    return subprocess.run(
        cmd,
        capture_output=True,
        text=True,
        cwd=cwd,
        timeout=timeout,
    )


def _findings_item(
    tool_name: str,
    severity: str,
    line: int | None,
    col: int | None,
    message: str,
    code: str | None = None,
) -> dict[str, Any]:
    return {
        "tool": tool_name,
        "severity": severity,
        "line": line,
        "col": col,
        "message": message,
        "code": code,
    }


# ── ESLint ───────────────────────────────────────────────────────────────


ESLINT_SEVERITY_MAP = {1: "warning", 2: "error"}


def _parse_eslint_results(data: Any) -> list[dict[str, Any]]:
    """Parse the ESLint JSON output array into HermeAd finding dicts."""
    findings: list[dict[str, Any]] = []
    if not isinstance(data, list):
        return findings

    for result in data:
        file_path = result.get("filePath", "")
        for msg in result.get("messages", []):
            severity = ESLINT_SEVERITY_MAP.get(msg.get("severity", 1), "warning")
            findings.append(
                _findings_item(
                    tool_name="eslint",
                    severity=severity,
                    line=msg.get("line"),
                    col=msg.get("column"),
                    message=msg.get("message", "unknown eslint violation"),
                    code=msg.get("ruleId", ""),
                )
            )
    return findings


def run_linter(file_path: str, tool: str) -> list[dict[str, Any]]:
    """Run ESLint on *file_path*.

    Returns a list of findings. Returns an empty list when eslint is
    not available or the file has no lint errors.
    """
    if tool != "eslint":
        return []

    project_root = _find_js_project_root(file_path)
    if project_root is None:
        return []

    if not _npx_available():
        return []
    if not _tool_installed(project_root, "eslint"):
        return []

    try:
        proc = _run_npx(
            ["eslint", "--format", "json", "--no-ignore", str(file_path)],
            cwd=project_root,
        )
    except (FileNotFoundError, subprocess.TimeoutExpired, OSError):
        return []

    # ESLint exits 0 (no errors) or 1 (errors/warnings) — both may have JSON
    if proc.returncode not in (0, 1):
        return []

    try:
        data = json.loads(proc.stdout)
    except (json.JSONDecodeError, ValueError):
        return []

    return _parse_eslint_results(data)


# ── Prettier ─────────────────────────────────────────────────────────────


_ANSI_RE = re.compile(r"\x1b\[[0-9;]*m")


def _strip_ansi(text: str) -> str:
    """Remove ANSI escape sequences from *text*."""
    return _ANSI_RE.sub("", text)


def run_formatter(file_path: str, tool: str) -> list[dict[str, Any]]:
    """Run Prettier --check on *file_path*.

    Returns one finding per unformatted file indicating it needs formatting.
    Returns an empty list if prettier is unavailable or the file is already
    formatted.
    """
    if tool != "prettier":
        return []

    project_root = _find_js_project_root(file_path)
    if project_root is None:
        return []

    if not _npx_available():
        return []
    if not _tool_installed(project_root, "prettier"):
        return []

    if not _ts_or_js(file_path):
        return []

    try:
        proc = _run_npx(
            ["prettier", "--check", "--no-color", str(file_path)],
            cwd=project_root,
        )
    except (FileNotFoundError, subprocess.TimeoutExpired, OSError):
        return []

    # Exit 0 → already formatted
    if proc.returncode == 0:
        return []

    # Exit 1 + file path in stderr → needs formatting
    # Prettier outputs relative paths prefixed with [warn] to stderr:
    #   [warn] test.js
    # Exit code 2 → error (no config, etc.) — skip silently
    if proc.returncode == 1:
        # Check both stdout and stderr for file paths
        unformatted: list[str] = []
        for source in (proc.stdout, proc.stderr):
            for line in source.splitlines():
                stripped = _strip_ansi(line).strip()
                # Skip non-path lines
                if not stripped or stripped.startswith("Checking"):
                    continue
                # Remove [warn] prefix
                if stripped.startswith("[warn]"):
                    stripped = stripped.replace("[warn]", "", 1).strip()
                if stripped:
                    unformatted.append(stripped)

        # Match: absolute path, relative path (resolved against project root),
        # or filename-only match
        target_abs = Path(file_path).resolve()
        target_name = target_abs.name

        needs_formatting = False
        for uf in unformatted:
            candidate = Path(uf)
            if candidate.is_absolute() and candidate.resolve() == target_abs:
                needs_formatting = True
                break
            if not candidate.is_absolute():
                resolved = (project_root / candidate).resolve()
                if resolved == target_abs:
                    needs_formatting = True
                    break
            if candidate.name == target_name:
                needs_formatting = True
                break

        if needs_formatting:
            return [
                _findings_item(
                    tool_name="prettier",
                    severity="warning",
                    line=None,
                    col=None,
                    message="File needs formatting (prettier --check failed)",
                    code="prettier/format",
                )
            ]

    return []


# ── TypeScript (tsc) ────────────────────────────────────────────────────


# Regex for tsc error/warning output lines:
#   filepath(line,col): error TS2345: message
#   filepath(line,col): warning TS2345: message
_TSC_LINE_RE = re.compile(
    r"^(.+)\((\d+),(\d+)\):\s+(error|warning)\s+(TS\d+):\s+(.*)"
)


def _ts_or_js(file_path: str) -> bool:
    ext = Path(file_path).suffix.lower()
    return ext in (".ts", ".tsx", ".js", ".jsx", ".mjs", ".cjs")


def _parse_tsc_output(
    stdout: str, stderr: str, file_path: str, project_root: Path, tool: str
) -> list[dict[str, Any]]:
    """Parse tsc --noEmit output into HermeAd finding dicts.

    *project_root* is used to resolve relative source file paths from
    tsc output against the correct directory.
    """
    findings: list[dict[str, Any]] = []
    target = Path(file_path).resolve()
    combined = stdout + "\n" + stderr
    for line in combined.splitlines():
        m = _TSC_LINE_RE.match(line)
        if m:
            source_file, raw_line, raw_col, severity, code, message = m.groups()
            # tsc outputs relative paths — resolve against project_root
            source_path = (project_root / source_file).resolve()
            if source_path != target:
                continue
            findings.append(
                _findings_item(
                    tool_name=tool,
                    severity="error" if severity == "error" else "warning",
                    line=int(raw_line),
                    col=int(raw_col),
                    message=message.strip(),
                    code=code.strip(),
                )
            )
    return findings


def run_type_checker(file_path: str, tool: str) -> list[dict[str, Any]]:
    """Run ``tsc --noEmit`` on the project when *file_path* is .ts/.tsx.

    Returns findings scoped to the modified file. Skips when tsc is not
    available or when the project has no tsconfig.json.
    """
    if tool != "tsc":
        return []

    ext = Path(file_path).suffix.lower()
    if ext not in (".ts", ".tsx"):
        return []

    project_root = _find_js_project_root(file_path)
    if project_root is None:
        return []

    # tsc requires tsconfig.json at project root
    if not (project_root / "tsconfig.json").is_file():
        return []

    if not _npx_available():
        return []
    if not _tool_installed(project_root, "typescript") and not _tool_installed(
        project_root, "tsc"
    ):
        return []

    try:
        proc = _run_npx(
            ["tsc", "--noEmit", "--pretty", "false"],
            cwd=project_root,
            timeout=120,
        )
    except (FileNotFoundError, subprocess.TimeoutExpired, OSError):
        return []

    return _parse_tsc_output(proc.stdout, proc.stderr, file_path, project_root, tool)


# ── Unimplemented ────────────────────────────────────────────────────────


def run_security_scan(file_path: str, tool: str) -> list[dict[str, Any]]:
    """Placeholder: JavaScript security scanning not yet implemented."""
    return []
