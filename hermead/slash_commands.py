"""Slash command handlers for HermeAd.

Provides /hermead with three subcommands:
- check <file_or_dir> — runs applicable runners on a file/directory
- status — shows tool availability, config path, session stats
- config — shows resolved effective configuration
"""

from __future__ import annotations

import os
from pathlib import Path
from typing import Any

from hermead.config import DEFAULT_CONFIG, find_project_root, load_hermead_config
from hermead.detector import detect_tooling
from hermead.hooks import _file_type, _is_ignored
from hermead.hooks import _run_check as _dispatch_check
from hermead.reporter import (
    format_full,
    get_summary,
)
from hermead.reporter import get_tool_status as _get_tool_status

# ── Check handler ──────────────────────────────────────────────────────────


def _run_all_checks(
    file_path: str, project_root: Path
) -> list[dict[str, Any]]:
    """Run ALL applicable checks on *file_path* and return the results."""
    ftype = _file_type(file_path)
    if ftype is None:
        return []

    config = load_hermead_config(project_root)
    if _is_ignored(file_path, config):
        return []

    detected = detect_tooling(project_root)
    lang_cfg = config.get(ftype, {})
    detected_lang = detected.get(ftype, {})

    checks = [
        ("lint", detected_lang.get("lint") or lang_cfg.get("lint")),
        ("type_check", detected_lang.get("type_check") or lang_cfg.get("type_check")),
        ("formatter", detected_lang.get("formatter") or lang_cfg.get("formatter")),
        ("security", detected_lang.get("security") or lang_cfg.get("security")),
    ]

    all_results: list[dict[str, Any]] = []
    for action, tool in checks:
        if tool:
            all_results.extend(
                _dispatch_check(ftype, file_path, tool, action, project_root)
            )

    return all_results


def _find_project(path_str: str) -> Path | None:
    """Try to resolve *path_str* and find its project root."""
    p = Path(path_str)
    if not p.is_absolute():
        p = Path(os.getcwd()) / p
    p = p.resolve()
    if p.is_file():
        return find_project_root(p.parent)
    if p.is_dir():
        return find_project_root(p)
    return find_project_root(p)


def _handle_check(raw_args: str) -> str:
    """Check a file or directory using all applicable runners.

    /hermead check <file_or_dir>
    """
    target = raw_args.strip()
    if not target:
        return (
            "Usage: /hermead check <file_or_dir>\n"
            "Runs all applicable linters, type checkers, formatters, and security "
            "scanners on the given file or directory."
        )

    project_root = _find_project(target)
    if project_root is None:
        return (
            f"Error: cannot find project root for '{target}'.\n"
            "HermeAd needs a .git, .hg, or .hermes directory in the path."
        )

    path = Path(target)
    if not path.is_absolute():
        path = Path(os.getcwd()) / path
    path = path.resolve()

    if not path.exists():
        return f"Error: '{target}' does not exist."

    # Collect files to check
    files_to_check: list[Path] = []
    if path.is_file():
        files_to_check.append(path)
    elif path.is_dir():
        config = load_hermead_config(project_root)
        for child in sorted(path.rglob("*")):
            if child.is_file() and not _is_ignored(str(child), config):
                ftype = _file_type(child)
                if ftype is not None:
                    files_to_check.append(child)

    if not files_to_check:
        return f"No supported files found in '{target}'."

    all_results: list[dict[str, Any]] = []
    checked_count = 0
    for f in files_to_check:
        results = _run_all_checks(str(f), project_root)
        if results:
            all_results.extend(results)
        checked_count += 1

    if not all_results:
        return (
            f"HermeAd check: {checked_count} file(s) checked, "
            "no issues found."
        )

    report = format_full(all_results)
    return (
        f"HermeAd check: {checked_count} file(s) checked, "
        f"{len(all_results)} finding(s)\n\n{report}"
    )


# ── Status handler ─────────────────────────────────────────────────────────


def _handle_status(raw_args: str) -> str:
    """Show tool availability, config paths, and session stats.

    /hermead status
    """
    lines: list[str] = []

    # Tool availability per language
    lines.append("Tool Availability:")
    tool_status = _get_tool_status()
    if tool_status:
        for lang in sorted(tool_status.keys()):
            status = tool_status[lang]
            parts: list[str] = []
            for category in ("lint", "type_check", "formatter", "security"):
                available = status.get(category, False)
                icon = "\u2705" if available else "\u274c"
                parts.append(f"{icon} {category}")
            lines.append(f"  {lang}: {' | '.join(parts)}")
    else:
        lines.append("  No tool status available.")

    lines.append("")

    # Config paths
    global_path = Path.home() / ".hermes" / "hermead.yaml"
    lines.append(f"Global config: {global_path}")
    if global_path.is_file():
        lines.append("  \u2705 Present")
    else:
        lines.append("  \u274c Not found (using defaults)")

    project_root = find_project_root()
    if project_root is not None:
        local_path = project_root / ".hermes" / "hermead.yaml"
        lines.append(f"Project root: {project_root}")
        lines.append(f"Project config: {local_path}")
        if local_path.is_file():
            lines.append("  \u2705 Present")
        else:
            lines.append("  \u2014 Not found (using defaults or global)")
    else:
        lines.append("Project root: not detected (no .git/.hg/.hermes in path)")

    lines.append("")

    # Session stats
    session = get_summary()
    if session:
        lines.append("Last Session Stats:")
        lines.append(f"  Session id:    {session.get('session_id', '?')}")
        lines.append(f"  Files checked: {session.get('files_checked', 0)}")
        lines.append(f"  Issues found:  {session.get('issues_found', 0)}")
        lines.append(f"  Blocked writes:{session.get('blocked_writes', 0)}")
    else:
        lines.append("Session Stats: no session data yet.")

    return "\n".join(lines)


# ── Config handler ─────────────────────────────────────────────────────────


def _format_config_section(
    label: str, data: Any, indent: int = 2
) -> list[str]:
    """Format a config section as indented lines."""
    prefix = " " * indent
    lines: list[str] = []
    if isinstance(data, dict):
        lines.append(f"{prefix}{label}:")
        for key, value in data.items():
            if isinstance(value, dict):
                lines.extend(_format_config_section(str(key), value, indent + 2))
            elif isinstance(value, list):
                items = ", ".join(str(v) for v in value)
                lines.append(f"{' ' * (indent + 2)}{key}: [{items}]")
            else:
                lines.append(f"{' ' * (indent + 2)}{key}: {value}")
    else:
        lines.append(f"{prefix}{label}: {data}")
    return lines


def _handle_config(raw_args: str) -> str:
    """Show the resolved effective configuration.

    /hermead config

    Displays the config merge chain: built-in defaults -> global
    (~/.hermes/hermead.yaml) -> project (.hermes/hermead.yaml).
    """
    lines: list[str] = []

    # Identify all configs used
    global_path = Path.home() / ".hermes" / "hermead.yaml"
    project_root = find_project_root()
    local_path: Path | None = None
    if project_root is not None:
        local_path = project_root / ".hermes" / "hermead.yaml"

    has_global = global_path.is_file()
    has_local = local_path is not None and local_path.is_file()

    # Build config chain summary
    lines.append("Config Merge Chain:")
    lines.append(f"  1. Built-in defaults ({len(DEFAULT_CONFIG)} top-level keys)")
    lines.append(f"  2. Global: {global_path}  [{'present' if has_global else 'not found'}]")
    if project_root is not None:
        lines.append(f"  3. Project: {local_path}  [{'present' if has_local else 'not found'}]")
    lines.append("")

    # Resolved effective config
    lines.append("Effective Config:")
    effective = load_hermead_config()
    for section in ("python", "javascript", "go", "rust", "shell", "generic"):
        if section in effective:
            lines.extend(_format_config_section(section, effective[section]))

    # Non-language sections
    for section in ("thresholds", "ignore_paths"):
        if section in effective:
            lines.append(f"  {section}:")
            val = effective[section]
            if isinstance(val, dict):
                for k, v in val.items():
                    lines.append(f"    {k}: {v}")
            elif isinstance(val, list):
                for item in val:
                    lines.append(f"    - {item}")
            else:
                lines.append(f"    {val}")

    return "\n".join(lines)


# ── Top-level dispatcher ───────────────────────────────────────────────────


def handle(raw_args: str) -> str:
    """Top-level handler for /hermead slash commands.

    Parses the subcommand (check, status, config) from the raw argument
    string and dispatches to the appropriate handler.
    """
    parts = raw_args.strip().split(None, 1) if raw_args.strip() else []

    if not parts:
        return (
            "HermeAd: /hermead <subcommand> [args]\n\n"
            "Subcommands:\n"
            "  check <file|dir>   Run all applicable checks on a file or directory\n"
            "  status             Show tool availability, config paths, and session stats\n"
            "  config             Show the resolved effective configuration\n"
        )

    subcommand = parts[0].lower()
    subargs = parts[1] if len(parts) > 1 else ""

    if subcommand == "check":
        return _handle_check(subargs)
    elif subcommand == "status":
        return _handle_status(subargs)
    elif subcommand == "config":
        return _handle_config(subargs)
    else:
        return (
            f"Unknown subcommand: '{subcommand}'. "
            "Valid subcommands: check, status, config"
        )
