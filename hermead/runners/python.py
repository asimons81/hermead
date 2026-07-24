"""Python runner for HermeAd.

Runs ruff (lint), mypy (type check), bandit (security), and
ruff format / black (format check) on a Python file and returns
structured results.

Tool availability is checked via PATH. Missing tools are silently skipped
with a debug log — the runner never crashes.

Every function is idempotent and stateless. Safe to call multiple times
on the same file.
"""

from __future__ import annotations

import json
import logging
import re
import shutil
import subprocess
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)

# ── Public result type aliases ────────────────────────────────────────────
# These are just dict shapes for documentation purposes. Actual return values
# are plain dicts / lists of dicts.

"""
Lint violation::
    {"severity": "error"|"warning", "line": int, "col": int,
     "code": str, "message": str}

Type error::
    {"severity": "error"|"note"|"warning", "line": int,
     "message": str, "code": str | None}

Security issue::
    {"severity": "HIGH"|"MEDIUM"|"LOW", "line": int,
     "vuln_type": str, "message": str}

Format result::
    {"needs_formatting": bool}
"""

# ── Helpers ───────────────────────────────────────────────────────────────


def _check_tool(name: str) -> bool:
    """Return True when *name* is available on PATH."""
    return shutil.which(name) is not None


def _warn_missing_tool(tool: str) -> None:
    logger.debug("HermeAd: %s not on PATH — skipping", tool)


# ── Ruff linter (ruff check) ──────────────────────────────────────────────
# Output format (concise):
#   path/to/file.py:1:5: F401 `os` imported but unused
#   path/to/file.py:10:1: E302 expected 2 blank lines, found 1
#   path/to/file.py:42:13: F821 undefined name 'x'
#   Found 3 errors.

_RUFF_RE = re.compile(
    r"^"
    r"(?:\S+:)?(?P<line>\d+):(?P<col>\d+):\s+"
    r"(?P<code>\S+)\s+(?P<message>.+)"
    r"$"
)

# Error-like codes: E (pycodestyle errors), F (pyflakes), SYN (syntax)
_ERROR_CODES = frozenset({"E", "F", "SYN"})


def _parse_ruff_output(output: str) -> list[dict[str, Any]]:
    """Parse ``ruff check`` line-based output into structured violations."""
    results: list[dict[str, Any]] = []
    for line in output.splitlines():
        m = _RUFF_RE.match(line)
        if m is None:
            continue
        code = m.group("code")
        first_letter = code.split("[", 1)[0][:3]  # e.g. "F40" from "F401"
        severity = "error" if any(
            first_letter.startswith(c) for c in _ERROR_CODES
        ) else "warning"
        results.append({
            "severity": severity,
            "line": int(m.group("line")),
            "col": int(m.group("col")),
            "code": code,
            "message": m.group("message").strip(),
        })
    return results


def run_linter(file_path: str) -> list[dict[str, Any]]:
    """Run ``ruff check`` on *file_path* and return parsed violations.

    Returns an empty list when ruff is not available or no violations found.
    """
    path = Path(file_path)
    if not _check_tool("ruff"):
        _warn_missing_tool("ruff")
        return []

    try:
        result = subprocess.run(
            ["ruff", "check", "--output-format=concise", str(path)],
            capture_output=True,
            text=True,
            timeout=60,
            check=False,
        )
    except (subprocess.TimeoutExpired, OSError) as exc:
        logger.debug("HermeAd: ruff check failed: %s", exc)
        return []

    output = (result.stdout or result.stderr).strip()
    if not output:
        return []
    return _parse_ruff_output(output)


# ── mypy type checker ─────────────────────────────────────────────────────
# Output format:
#   path/to/file.py:5: error: Name 'x' is not defined  [name-defined]
#   path/to/file.py:10: note: See https://mypy-lang.org/...
#   path/to/file.py:12: warning: unused variable 'y'  [unused-ignore]

_MYPY_RE = re.compile(
    r"^"
    r"(?:\S+:)?(?P<line>\d+):\s+"
    r"(?P<severity>error|note|warning):\s+"
    r"(?P<message>.+?)"
    r"(?:\s+\[(?P<code>[\w\-.]+)\])?"
    r"$"
)


def _parse_mypy_output(output: str) -> list[dict[str, Any]]:
    """Parse mypy line-based output into structured type errors."""
    results: list[dict[str, Any]] = []
    for line in output.splitlines():
        m = _MYPY_RE.match(line)
        if m is None:
            continue
        results.append({
            "severity": m.group("severity"),
            "line": int(m.group("line")),
            "message": m.group("message").strip(),
            "code": m.group("code"),
        })
    return results


def run_type_checker(file_path: str) -> list[dict[str, Any]]:
    """Run ``mypy`` on *file_path* and return parsed type errors.

    Returns an empty list when mypy is not available or no errors found.
    """
    path = Path(file_path)
    if not _check_tool("mypy"):
        _warn_missing_tool("mypy")
        return []

    try:
        result = subprocess.run(
            ["mypy", "--show-error-codes", str(path)],
            capture_output=True,
            text=True,
            timeout=120,
            check=False,
        )
    except (subprocess.TimeoutExpired, OSError) as exc:
        logger.debug("HermeAd: mypy failed: %s", exc)
        return []

    output = (result.stdout or result.stderr).strip()
    if not output:
        return []
    return _parse_mypy_output(output)


# ── bandit security scanner ───────────────────────────────────────────────
# Bandit is called with -f json so we parse JSON rather than fragile text.
# JSON shape:
#   {"results": [
#       {"issue_severity": "MEDIUM", "issue_confidence": "HIGH",
#        "line_number": 5, "test_id": "B105",
#        "issue_text": "Possible hardcoded password: 'secret'"}
#   ]}


def _parse_bandit_json(data: dict[str, Any]) -> list[dict[str, Any]]:
    """Parse bandit JSON output into structured security issues."""
    results: list[dict[str, Any]] = []
    for issue in data.get("results", []):
        results.append({
            "severity": issue.get("issue_severity", "MEDIUM").upper(),
            "line": issue.get("line_number", 0),
            "vuln_type": issue.get("test_id", ""),
            "message": issue.get("issue_text", ""),
        })
    return results


def run_security_scan(file_path: str) -> list[dict[str, Any]]:
    """Run ``bandit`` on *file_path* and return parsed security issues.

    Uses JSON output format for reliable parsing. Returns an empty list when
    bandit is not available or no issues found.
    """
    path = Path(file_path)
    if not _check_tool("bandit"):
        _warn_missing_tool("bandit")
        return []

    try:
        result = subprocess.run(
            ["bandit", "-f", "json", str(path)],
            capture_output=True,
            text=True,
            timeout=120,
            check=False,
        )
    except (subprocess.TimeoutExpired, OSError) as exc:
        logger.debug("HermeAd: bandit failed: %s", exc)
        return []

    # bandit exits 0 (no issues) or 1 (issues found) — both are valid
    if result.returncode not in (0, 1):
        logger.debug("HermeAd: bandit returned rc=%d", result.returncode)
        return []

    if not result.stdout.strip():
        return []

    try:
        data = json.loads(result.stdout)
    except json.JSONDecodeError as exc:
        logger.debug("HermeAd: bandit JSON parse failed: %s", exc)
        return []

    return _parse_bandit_json(data)


# ── Format checker (ruff format --check / black --check) ─────────────
# ruff format --check exits:
#   0 -> file already formatted
#   1 -> file would be reformatted
#
# black --check --quiet exits:
#   0 -> file already formatted
#   1 -> file would be reformatted


def run_formatter(file_path: str, tool: str = "black") -> dict[str, bool]:
    """Check whether *file_path* needs formatting.

    Supports ``ruff`` (``ruff format --check``) and ``black``
    (``black --check --quiet``). Any other tool name returns
    ``{"needs_formatting": False}`` gracefully.

    Returns ``{"needs_formatting": True}`` when the formatter would
    reformat the file.
    Returns ``{"needs_formatting": False}`` when already formatted or
    the tool is not available.
    """
    path = Path(file_path)

    if tool == "ruff":
        if not _check_tool("ruff"):
            _warn_missing_tool("ruff")
            return {"needs_formatting": False}
        try:
            result = subprocess.run(
                ["ruff", "format", "--check", str(path)],
                capture_output=True,
                text=True,
                timeout=60,
                check=False,
            )
        except (subprocess.TimeoutExpired, OSError) as exc:
            logger.debug("HermeAd: ruff format --check failed: %s", exc)
            return {"needs_formatting": False}
        return {"needs_formatting": result.returncode != 0}

    if tool == "black":
        if not _check_tool("black"):
            _warn_missing_tool("black")
            return {"needs_formatting": False}
        try:
            result = subprocess.run(
                ["black", "--check", "--quiet", str(path)],
                capture_output=True,
                text=True,
                timeout=60,
                check=False,
            )
        except (subprocess.TimeoutExpired, OSError) as exc:
            logger.debug("HermeAd: black --check failed: %s", exc)
            return {"needs_formatting": False}
        return {"needs_formatting": result.returncode != 0}

    # Unknown tool -- graceful no-op
    logger.debug("HermeAd: unknown formatter tool %r -- skipping", tool)
    return {"needs_formatting": False}


# ── Registry-compatible adapters ──────────────────────────────────────────
# These wrap the internal functions to match the registry convention:
#   (file_path, project_root, **kwargs) -> list[dict]
# Dict keys: tool, severity, line, col, message, code


def _run_lint(file_path: str, project_root: str | Path, **kwargs: Any) -> list[dict[str, Any]]:
    """Registry adapter: run ruff lint with standard output format."""
    results = run_linter(file_path)
    for r in results:
        r.setdefault("tool", "ruff")
    return results


def _run_type_check(file_path: str, project_root: str | Path, **kwargs: Any) -> list[dict[str, Any]]:
    """Registry adapter: run mypy with standard output format."""
    results = run_type_checker(file_path)
    for r in results:
        r.setdefault("tool", "mypy")
    return results


def _run_format_check(file_path: str, project_root: str | Path, **kwargs: Any) -> list[dict[str, Any]]:
    """Registry adapter: run formatter with standard output format."""
    tool = kwargs.get("tool", "black")
    result = run_formatter(file_path, tool=tool)
    if result.get("needs_formatting"):
        fix_cmd = f"Run `{tool} format` to fix." if tool == "ruff" else f"Run `{tool}` to fix."
        return [{
            "tool": tool,
            "severity": "style",
            "line": None,
            "col": None,
            "message": f"File is not {tool}-formatted. {fix_cmd}",
            "code": tool,
        }]
    return []


def _run_security(file_path: str, project_root: str | Path, **kwargs: Any) -> list[dict[str, Any]]:
    """Registry adapter: run bandit with standard output format."""
    results = run_security_scan(file_path)
    for r in results:
        r.setdefault("tool", "bandit")
    return results


# ── Aggregated runner ─────────────────────────────────────────────────────


def run_all(
    file_path: str,
    config: dict[str, Any] | None = None,
    detected: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Run all configured Python tools on *file_path*.

    Determines which tools to use by checking *detected* (auto-detected from
    project files) first, then falling back to *config* (explicit config).

    Parameters
    ----------
    file_path:
        Absolute or relative path to the Python file to check.
    config:
        Effective HermeAd config (from ``load_hermead_config``). May contain
        a ``python`` section with tool assignments. Defaults to empty.
    detected:
        Auto-detected tooling (from ``detect_tooling``). May contain a
        ``python`` section. Takes priority over *config*.

    Returns
    -------
    dict
        With keys ``lint``, ``type_check``, ``format``, ``security`` — each
        mapped to the corresponding runner result (list or dict). Missing
        or skipped keys are omitted.
    """
    python_cfg = (config or {}).get("python", {})
    detected_python = (detected or {}).get("python", {})

    lint_tool: str | None = detected_python.get("lint") or python_cfg.get("lint")
    type_check_tool: str | None = (
        detected_python.get("type_check") or python_cfg.get("type_check")
    )
    formatter_tool: str | None = (
        detected_python.get("formatter") or python_cfg.get("formatter")
    )
    security_tool: str | None = (
        detected_python.get("security") or python_cfg.get("security")
    )

    results: dict[str, Any] = {}

    if lint_tool == "ruff":
        results["lint"] = run_linter(file_path)
    if type_check_tool == "mypy":
        results["type_check"] = run_type_checker(file_path)
    if formatter_tool in ("black", "ruff"):
        results["format"] = run_formatter(file_path, tool=formatter_tool)
    if security_tool == "bandit":
        results["security"] = run_security_scan(file_path)

    return results
