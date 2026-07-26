"""Hook implementations for Hermead.

The primary hook is ``post_tool_call`` which fires after every Hermes tool
invocation. It detects write_file / patch calls on project files and routes
to the appropriate runner for linting, type-checking, formatting, and security
scanning.
"""

from __future__ import annotations

import logging
import os
from collections.abc import Mapping
from pathlib import Path
from typing import Any

from hermead import runners
from hermead.config import find_project_root, load_hermead_config
from hermead.detector import detect_tooling
from hermead.reporter import (
    format_full,
    format_structured,
    record_results,
)

logger = logging.getLogger(__name__)

# ── File type detection map ──────────────────────────────────────────────

EXTENSION_MAP: dict[str, str] = {
    ".py": "python",
    ".js": "javascript",
    ".ts": "javascript",
    ".jsx": "javascript",
    ".tsx": "javascript",
    ".mjs": "javascript",
    ".cjs": "javascript",
    ".go": "go",
    ".rs": "rust",
    ".sh": "shell",
    ".bash": "shell",
    ".zsh": "shell",
    ".fish": "shell",
    ".rb": "ruby",
}

FILE_MAP: dict[str, str] = {
    "Dockerfile": "generic",
    ".dockerignore": "generic",
    ".gitignore": "generic",
    "Makefile": "generic",
    "pyproject.toml": "python",
    "package.json": "javascript",
    "go.mod": "go",
    "Cargo.toml": "rust",
    "Gemfile": "ruby",
    "Rakefile": "ruby",
}


def _file_type(file_path: str | Path) -> str | None:
    """Map a file path to a language type, or None if unsupported."""
    path = Path(file_path)
    ext = path.suffix.lower()
    if ext in EXTENSION_MAP:
        return EXTENSION_MAP[ext]
    name = path.name
    if name in FILE_MAP:
        return FILE_MAP[name]
    # Fallback: if no extension but has a shebang, classify by interpreter
    if not ext and path.is_file():
        try:
            first_line = path.read_text(encoding="utf-8", errors="replace").split("\n", 1)[0]
        except (OSError, UnicodeDecodeError):
            return None
        if first_line.startswith("#!/"):
            for token in ("python", "bash", "sh", "zsh", "node", "deno", "go", "rust"):
                if token in first_line:
                    if token in ("bash", "sh", "zsh"):
                        return "shell"
                    break
    return None


def _is_ignored(file_path: str | Path, config: dict[str, Any]) -> bool:
    """Check whether a file matches any ignore_paths glob."""
    import fnmatch

    path_str = str(file_path).replace("\\", "/")
    for pattern in config.get("ignore_paths", []):
        if fnmatch.fnmatch(path_str, pattern) or fnmatch.fnmatch(
            path_str.split("/")[-1], pattern
        ):
            return True
    return False


# ── Runner dispatch ──────────────────────────────────────────────────────

ACTION_MAP: dict[str, str] = {
    "lint": "run_lint",
    "type_check": "run_type_check",
    "formatter": "run_format_check",
    "security": "run_security",
}


def _run_check(
    file_type: str, file_path: str, tool: str, action: str, project_root: str | Path
) -> list[dict[str, Any]]:
    """Dispatch a check to the appropriate runner via the registry.

    Returns the standardised result list (possibly empty).
    """
    if not tool:
        return []
    runner_action = ACTION_MAP.get(action)
    if runner_action is None:
        return []
    return runners.run(
        language=file_type,
        action=runner_action,
        file_path=file_path,
        project_root=project_root,
        tool=tool,
    )


# ── Threshold enforcement ─────────────────────────────────────────────────


def _log_threshold_warnings(
    results: list[dict[str, Any]], thresholds: dict[str, str]
) -> None:
    """Log warnings when findings exceed configured thresholds.

    Plugin hooks can't prevent tool execution, so this is advisory only.
    Threshold keys (from config):
      - lint_warnings    (default: warn)
      - type_errors      (default: block)
      - security_high    (default: block)
      - security_medium  (default: warn)
    """
    if not results:
        return

    # Count errors/warnings by tool category
    lint_errors = 0
    type_errors = 0
    security_high = 0
    security_medium = 0

    security_tools = {"bandit", "gosec", "cargo audit", "semgrep", "brakeman"}
    lint_tools = {"ruff", "eslint", "golangci-lint", "clippy", "shellcheck", "rubocop"}
    type_check_tools = {"mypy", "tsc", "go vet", "rustc"}

    for r in results:
        tool = r.get("tool", "")
        sev = r.get("severity", "")

        # Lint tools — count only errors (warnings are informational)
        if tool in lint_tools:
            if sev == "error":
                lint_errors += 1
        # Type check tools
        elif tool in type_check_tools:
            if sev == "error":
                type_errors += 1
        # Security tools — split high (error) from medium (warning)
        elif tool in security_tools:
            if sev == "error":
                security_high += 1
            elif sev == "warning":
                security_medium += 1

    # Check thresholds
    if lint_errors > 0 and thresholds.get("lint_warnings") == "block":
        logger.warning(
            "Hermead threshold: %d lint errors found (threshold=block)",
            lint_errors,
        )

    if type_errors > 0 and thresholds.get("type_errors") == "block":
        logger.warning(
            "Hermead threshold: %d type errors found (threshold=block)",
            type_errors,
        )

    if security_high > 0 and thresholds.get("security_high") == "block":
        logger.warning(
            "Hermead threshold: %d HIGH security findings (threshold=block)",
            security_high,
        )

    if security_medium > 0 and thresholds.get("security_medium") == "block":
        logger.warning(
            "Hermead threshold: %d MEDIUM security findings (threshold=block)",
            security_medium,
        )


# ── Hook implementation ──────────────────────────────────────────────────


def _modified_path(params: Any, extra: Mapping[str, Any]) -> str | None:
    """Extract a modified path from documented and legacy hook call shapes."""
    candidates = [params, extra.get("params"), extra.get("kwargs"), extra]
    legacy_result = extra.get("result")
    if isinstance(legacy_result, Mapping):
        candidates.append(legacy_result)

    for candidate in candidates:
        if not isinstance(candidate, Mapping):
            continue
        value = candidate.get("path")
        if isinstance(value, Path):
            return str(value)
        if isinstance(value, str) and value.strip():
            return value
    return None


def post_tool_call(
    tool_name: str,
    params: Any = None,
    result: Any = None,
    **extra: Any,
) -> None:
    """Post-tool-call hook: detect write_file/patch on project files.

    When a tool modifies a project file, this hook:
    1. Determines the file type from the extension map.
    2. Loads the effective Hermead config (global + per-project).
    3. Auto-detects project tooling.
    4. Routes to the appropriate runner for lint / type-check / format / security.
    """
    # Only act on file-modifying tools
    if tool_name not in ("write_file", "patch"):
        return

    # Hermes calls this hook as (tool_name, params, result).  Older Hermead
    # releases accepted (tool_name, result, kwargs), so retain that shape when
    # the documented params argument does not include a path.
    if not _modified_path(params, extra) and isinstance(result, Mapping):
        extra = {**extra, "result": result}
    modified_path = _modified_path(params, extra)
    if not modified_path:
        return

    # Resolve to absolute path
    path = Path(modified_path)
    if not path.is_absolute():
        # Try resolving relative to cwd — best effort
        path = Path(os.getcwd()) / path
    path_str = str(path)

    # Determine the project root for this file
    project_root = find_project_root(path)
    if project_root is None:
        return

    # Determine file type
    ftype = _file_type(path)
    if ftype is None:
        return  # Unsupported file type, skip

    # Load config + detect tooling
    config = load_hermead_config(project_root)
    if _is_ignored(path_str, config):
        return

    detected = detect_tooling(project_root)

    # Get tool config for this file type — prefer auto-detected, fallback to config
    lang_cfg = config.get(ftype, {})
    detected_lang = detected.get(ftype, {})

    lint_tool = detected_lang.get("lint") or lang_cfg.get("lint")
    type_check_tool = detected_lang.get("type_check") or lang_cfg.get("type_check")
    formatter_tool = detected_lang.get("formatter") or lang_cfg.get("formatter")
    security_tool = detected_lang.get("security") or lang_cfg.get("security")

    # Gather all results via the registry-based dispatch
    all_results: list[dict[str, Any]] = []

    if lint_tool:
        all_results.extend(
            _run_check(ftype, path_str, lint_tool, "lint", project_root)
        )
    if type_check_tool:
        all_results.extend(
            _run_check(ftype, path_str, type_check_tool, "type_check", project_root)
        )
    if formatter_tool:
        all_results.extend(
            _run_check(ftype, path_str, formatter_tool, "formatter", project_root)
        )
    if security_tool:
        all_results.extend(
            _run_check(ftype, path_str, security_tool, "security", project_root)
        )

    # Format and report results
    if all_results:
        report_text = format_full(all_results)
        logger.info("Hermead report:\n%s", report_text)

    # Threshold enforcement (non-blocking — plugin hooks can't prevent tool execution)
    thresholds = config.get("thresholds", {})
    _log_threshold_warnings(all_results, thresholds)

    # Persist results for the dashboard
    try:
        record_results(
            all_results,
            file_path=path_str,
            language=ftype,
            project_root=project_root,
        )
    except Exception:
        # Dashboard persistence is optional; it must not break the host's
        # file-write lifecycle when the user home directory is unavailable.
        logger.warning("Hermead could not persist scan results", exc_info=True)

    # Store results as function attributes for test assertions and dashboards
    post_tool_call._last_results = all_results  # type: ignore[attr-defined]
    post_tool_call._last_structured = format_structured(all_results)  # type: ignore[attr-defined]
