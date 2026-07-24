"""Go runner: golangci-lint, go vet, gofmt, gosec.

Available only when ``go.mod`` exists in the project root.
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


def _has_go_tool(name: str) -> bool:
    return shutil.which(name) is not None


def _print_run(args: list[str], cwd: str | None, timeout: int = 60) -> subprocess.CompletedProcess:
    return subprocess.run(
        args,
        capture_output=True,
        text=True,
        timeout=timeout,
        cwd=cwd,
        check=False,
    )


# ── Lint: golangci-lint ───────────────────────────────────────────────────


def _run_lint(
    file_path: str, project_root: str | Path, **kwargs: Any
) -> list[dict[str, Any]]:
    """Run golangci-lint with JSON output. Fall back to text parsing on failure."""
    if not _has_go_tool("golangci-lint"):
        return []

    try:
        proc = _print_run(
            ["golangci-lint", "run", "--out-format", "json", "--no-config", file_path],
            cwd=str(project_root),
            timeout=120,
        )
    except subprocess.TimeoutExpired:
        return []
    except FileNotFoundError:
        return []

    if proc.returncode > 1 and not proc.stdout.strip():
        # Exit code 0 = clean, 1 = issues found, >1 = tool error
        return _run_lint_text(file_path, proc)

    return _parse_golangci_json(proc.stdout, file_path)


def _parse_golangci_json(
    raw: str, file_path: str
) -> list[dict[str, Any]]:
    """Parse golangci-lint JSON output (--out-format json)."""
    results: list[dict[str, Any]] = []
    try:
        data = json.loads(raw)
    except json.JSONDecodeError:
        return []

    for issue in data.get("Issues", []):
        pos = issue.get("Pos", {})
        text = issue.get("Text", "")
        linter = issue.get("FromLinter", "")
        severity = issue.get("Severity", "warning")

        # Normalise severity
        if severity in ("error", "critical", "high"):
            sev = "error"
        elif severity in ("medium", "warning"):
            sev = "warning"
        else:
            sev = "info"

        results.append(
            {
                "tool": "golangci-lint",
                "severity": sev,
                "line": pos.get("Line"),
                "col": pos.get("Column"),
                "message": text,
                "code": linter or None,
                "file": pos.get("Filename", ""),
            }
        )

    # Filter to only items for the given file
    file_abs = str(Path(file_path).resolve())
    return [r for r in results if str(Path(r.get("file", "")).resolve()) == file_abs]


def _run_lint_text(
    file_path: str, proc: subprocess.CompletedProcess
) -> list[dict[str, Any]]:
    """Fallback: parse golangci-lint text output, filtered to *file_path*."""
    target_abs = str(Path(file_path).resolve())
    results: list[dict[str, Any]] = []
    # Typical format: path/file.go:line:col: message (linter)
    pattern = re.compile(
        r"^(.+?)\.go:(\d+):(\d+)?:\s*(.+?)\s*\((.+?)\)\s*$"
    )

    for line in (proc.stdout + "\n" + proc.stderr).splitlines():
        line = line.strip()
        if not line:
            continue
        m = pattern.match(line)
        if m:
            result_path = m.group(1).strip()
            # Resolve the result path relative to the file_path's directory
            result_abs = str(
                (Path(file_path).parent / result_path).resolve()
            )
            if result_abs != target_abs:
                continue
            results.append(
                {
                    "tool": "golangci-lint",
                    "severity": "warning",
                    "message": m.group(4).strip(),
                    "line": int(m.group(2)),
                    "col": int(m.group(3)) if m.group(3) else 1,
                    "code": m.group(5).strip(),
                }
            )
    return results


def _run_type_check(
    file_path: str, project_root: str | Path, **kwargs: Any
) -> list[dict[str, Any]]:
    """Run go vet on the file's package, filtered to *file_path*."""
    if not _has_go_tool("go"):
        return []

    # go vet works at the package level; point at the file's directory
    pkg_dir = Path(file_path).parent
    if not pkg_dir.is_dir():
        pkg_dir = Path(project_root)

    try:
        proc = _print_run(
            ["go", "vet", str(pkg_dir)],
            cwd=str(project_root),
            timeout=120,
        )
    except subprocess.TimeoutExpired:
        return []
    except FileNotFoundError:
        return []

    if proc.returncode == 0:
        return []

    target_abs = str(Path(file_path).resolve())
    results: list[dict[str, Any]] = []
    pattern = re.compile(r"^(.+?)\.go:(\d+):(\d+)?:\s*(.*)")

    for line in (proc.stdout + "\n" + proc.stderr).splitlines():
        line = line.strip()
        if not line:
            continue
        m = pattern.match(line)
        if m:
            result_path = m.group(1).strip()
            result_abs = str(
                (Path(file_path).parent / result_path).resolve()
            )
            if result_abs != target_abs:
                continue
            results.append(
                {
                    "tool": "go vet",
                    "severity": "warning",
                    "line": int(m.group(2)),
                    "col": int(m.group(3)) if m.group(3) else None,
                    "message": m.group(4).strip(),
                    "code": "go vet",
                }
            )

    return results


def _run_format_check(
    file_path: str, project_root: str | Path, **kwargs: Any
) -> list[dict[str, Any]]:
    """Run ``gofmt -d`` (diff mode); non-empty diff means needs formatting."""
    if not _has_go_tool("gofmt"):
        return []

    try:
        proc = _print_run(
            ["gofmt", "-d", file_path],
            cwd=str(project_root),
            timeout=30,
        )
    except subprocess.TimeoutExpired:
        return []
    except FileNotFoundError:
        return []

    if proc.returncode == 0 and not proc.stdout.strip():
        return []

    return [
        {
            "tool": "gofmt",
            "severity": "style",
            "line": None,
            "col": None,
            "message": "File is not gofmt-formatted. Run `gofmt -w` to fix.",
            "code": "gofmt",
        }
    ]


# ── Security: gosec ──────────────────────────────────────────────────────


def _run_security(
    file_path: str, project_root: str | Path, **kwargs: Any
) -> list[dict[str, Any]]:
    """Run ``gosec`` with JSON output on the given file."""
    if not _has_go_tool("gosec"):
        return []

    try:
        proc = _print_run(
            ["gosec", "-quiet", "-fmt=json", file_path],
            cwd=str(project_root),
            timeout=60,
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

    for issue in data.get("Issues", []):
        severity_map = {
            "high": "error",
            "medium": "warning",
            "low": "info",
        }
        raw_sev = (issue.get("severity") or "medium").lower()
        cwe = issue.get("CWE", {}) or {}
        cwe_id = cwe.get("id", "")

        results.append(
            {
                "tool": "gosec",
                "severity": severity_map.get(raw_sev, "warning"),
                "line": issue.get("line"),
                "col": issue.get("column"),
                "message": issue.get("details", issue.get("long_msg", "")),
                "code": cwe_id or f"GSC-{issue.get('rule_id', '')}",
            }
        )

    return results


# ── Register ──────────────────────────────────────────────────────────────

register_runner("go", "run_lint", _run_lint)
register_runner("go", "run_type_check", _run_type_check)
register_runner("go", "run_format_check", _run_format_check)
register_runner("go", "run_security", _run_security)
