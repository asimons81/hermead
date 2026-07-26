"""Reporter module for Hermead — formatting and persistence.

Layers:
- Inline / structured formatting for the agent's chat output
- Persistent result store in ``~/.hermes/hermead/data/results.json`` for
  the desktop dashboard plugin
"""

from __future__ import annotations

import json
import logging
import os
import tempfile
import threading
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)

# ═══════════════════════════════════════════════════════════════════════════
# Part 1 — formatting (for agent output)
# ═══════════════════════════════════════════════════════════════════════════

TOOL_EMOJI: dict[str, str] = {
    # Security
    "bandit": "\U0001f512",  # 🔒
    "gosec": "\U0001f512",
    "cargo audit": "\U0001f512",
    "semgrep": "\U0001f512",
    # Linters
    "ruff": "\U0001f50d",  # 🔍
    "eslint": "\U0001f50d",
    "golangci-lint": "\U0001f50d",
    "clippy": "\U0001f50d",
    "shellcheck": "\U0001f50d",
    # Ruby tools
    "rubocop": "\U0001f50d",
    "standardrb": "\u2728",
    "brakeman": "\U0001f512",
    # Type checkers
    "mypy": "\U0001f3f7\ufe0f",  # 🏷️
    "tsc": "\U0001f3f7\ufe0f",
    "go vet": "\U0001f3f7\ufe0f",
    "rustc": "\U0001f3f7\ufe0f",
    # Formatters
    "black": "\u2728",  # ✨
    "prettier": "\u2728",
    "gofmt": "\u2728",
    "rustfmt": "\u2728",
    "shfmt": "\u2728",
}

FALLBACK_EMOJI = "\u26a1"  # ⚡

SEVERITY_LABEL: dict[str, str] = {
    "error": "error",
    "warning": "warning",
    "info": "info",
    "style": "style",
    "note": "note",
}

SEVERITY_ORDER = ["error", "warning", "info", "style", "note"]


def _tool_emoji(tool_name: str) -> str:
    return TOOL_EMOJI.get(tool_name, FALLBACK_EMOJI)


def _severity_sort_key(sev: str) -> int:
    try:
        return SEVERITY_ORDER.index(sev)
    except ValueError:
        return len(SEVERITY_ORDER)


def format_inline(results: list[dict[str, Any]]) -> str:
    """Format results as a compact inline summary string."""
    if not results:
        return ""

    by_tool: dict[str, dict[str, int]] = {}
    for r in results:
        tool = r.get("tool", "unknown")
        severity = r.get("severity", "info")
        by_tool.setdefault(tool, {})
        sev_label = SEVERITY_LABEL.get(severity, severity)
        by_tool[tool][sev_label] = by_tool[tool].get(sev_label, 0) + 1

    lines: list[str] = []
    for tool in sorted(by_tool.keys()):
        sev_counts = by_tool[tool]
        emoji = _tool_emoji(tool)
        parts: list[str] = []
        for sev in SEVERITY_ORDER:
            count = sev_counts.get(sev, 0)
            if count:
                label = SEVERITY_LABEL.get(sev, sev)
                parts.append(f"{count} {label}{'s' if count > 1 else ''}")
        if parts:
            lines.append(f"{emoji} {tool}: {', '.join(parts)}")

    return "\n".join(lines)


def format_structured(results: list[dict[str, Any]]) -> dict[str, Any]:
    """Format results as a structured dict for a dashboard tab."""
    summary: dict[str, Any] = {
        "total": len(results),
        "by_severity": {},
        "by_tool": {},
    }
    errors: list[dict[str, Any]] = []
    warnings: list[dict[str, Any]] = []

    for r in results:
        sev = r.get("severity", "info")
        tool = r.get("tool", "unknown")
        summary["by_severity"][sev] = summary["by_severity"].get(sev, 0) + 1
        summary["by_tool"][tool] = summary["by_tool"].get(tool, 0) + 1

        if sev == "error":
            errors.append(r)
        elif sev in ("warning", "style"):
            warnings.append(r)

    return {
        "summary": summary,
        "findings": results,
        "errors": errors,
        "warnings": warnings,
    }


def format_line_details(results: list[dict[str, Any]], severity: str = "error") -> str:
    """Format findings at the given *severity* as line-level detail text."""
    lines: list[str] = []
    for r in results:
        sev = r.get("severity", "info")
        if sev != severity:
            continue
        tool = r.get("tool", "?")
        emoji = _tool_emoji(tool)
        raw_line = r.get("line")
        col = r.get("col")
        pos = f"line {raw_line}" if raw_line else ""
        if col is not None:
            pos += f":{col}"
        loc = f"  ({pos})" if pos else ""
        msg = r.get("message", "").strip()
        code = r.get("code")
        code_str = f" ({code})" if code else ""
        lines.append(f"  {emoji}{loc} {msg}{code_str}")

    if not lines:
        return ""
    return "\n".join(lines)


def format_full(results: list[dict[str, Any]]) -> str:
    """Combine inline summary + detailed errors into a single report string."""
    if not results:
        return ""
    parts: list[str] = [format_inline(results)]
    error_details = format_line_details(results, severity="error")
    if error_details:
        parts.append("")
        parts.append(error_details)
    return "\n".join(parts)


# ═══════════════════════════════════════════════════════════════════════════
# Part 2 — persistence (for the desktop dashboard)
# ═══════════════════════════════════════════════════════════════════════════

HERMEAD_HOME = Path.home() / ".hermes" / "hermead"
RESULTS_FILE = HERMEAD_HOME / "data" / "results.json"
LOCK = threading.RLock()


def _empty_store() -> dict[str, Any]:
    return {"sessions": [], "files": {}, "version": 1}


def _ensure_dir() -> None:
    RESULTS_FILE.parent.mkdir(parents=True, exist_ok=True)


def _load() -> dict[str, Any]:
    try:
        _ensure_dir()
        if RESULTS_FILE.is_file():
            raw = RESULTS_FILE.read_text(encoding="utf-8")
            return json.loads(raw)
    except (json.JSONDecodeError, OSError):
        logger.warning(
            "Hermead result store is unavailable; using an in-memory store",
            exc_info=True,
        )
    return _empty_store()


def _save(data: dict[str, Any]) -> bool:
    """Atomically replace the result store without risking its prior contents."""
    tmp_path: Path | None = None
    try:
        _ensure_dir()
        fd, tmp_name = tempfile.mkstemp(
            prefix=f".{RESULTS_FILE.name}.", suffix=".tmp", dir=RESULTS_FILE.parent
        )
        tmp_path = Path(tmp_name)
        with os.fdopen(fd, "w", encoding="utf-8") as handle:
            json.dump(data, handle, indent=2, default=str)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(tmp_path, RESULTS_FILE)
        return True
    except (OSError, TypeError, ValueError):
        logger.warning("Hermead could not save result store", exc_info=True)
        return False
    finally:
        if tmp_path is not None:
            try:
                tmp_path.unlink(missing_ok=True)
            except OSError:
                pass


def start_session(project_root: str | Path) -> str:
    """Open a new session and return its id."""
    session_id = datetime.now(UTC).strftime("%Y%m%d_%H%M%S_%f")
    entry = {
        "session_id": session_id,
        "project_root": str(project_root),
        "started_at": datetime.now(UTC).isoformat(),
        "files_checked": 0,
        "issues_found": 0,
        "blocked_writes": 0,
        "findings": [],
    }
    with LOCK:
        store = _load()
        store["sessions"].append(entry)
        _save(store)
    return session_id


def record_results(
    results: list[dict[str, Any]],
    file_path: str,
    language: str,
    project_root: str | Path,
    session_id: str | None = None,
) -> None:
    """Persist a batch of scan results to the JSON store."""
    with LOCK:
        store = _load()
        now = datetime.now(UTC)

        # Use session_id or latest, creating one if needed
        session = _find_or_create_session(store, project_root, session_id)

        issues_in_batch = 0
        findings_batch: list[dict[str, Any]] = []
        relative_path = _relpath(file_path, project_root)

        for r in results:
            severity = r.get("severity", "info").lower()
            finding = {
                "tool": r.get("tool", ""),
                "severity": severity,
                "line": r.get("line"),
                "col": r.get("col"),
                "message": r.get("message", ""),
                "code": r.get("code", ""),
                "file": relative_path,
                "language": language,
                "timestamp": now.isoformat(),
            }
            findings_batch.append(finding)
            issues_in_batch += 1

        if results or relative_path:
            session["files_checked"] += 1
        session["issues_found"] += issues_in_batch
        session["findings"].extend(findings_batch)

        file_key = str(Path(project_root) / relative_path) if relative_path else file_path
        file_entry = store["files"].get(file_key, {
            "language": language,
            "errors": 0,
            "warnings": 0,
            "infos": 0,
            "last_checked": None,
        })
        file_entry["language"] = language
        file_entry["last_checked"] = now.isoformat()
        for f in findings_batch:
            sev = f["severity"]
            if sev == "error":
                file_entry["errors"] += 1
            elif sev == "warning":
                file_entry["warnings"] += 1
            else:
                file_entry["infos"] = file_entry.get("infos", 0) + 1
        store["files"][file_key] = file_entry
        _save(store)


def record_blocked_write(file_path: str, project_root: str | Path) -> None:
    """Record that a write was blocked (threshold exceeded)."""
    with LOCK:
        store = _load()
        session = _find_or_create_session(store, project_root)
        session["blocked_writes"] += 1
        now = datetime.now(UTC).isoformat()
        session["findings"].append({
            "tool": "hermead",
            "severity": "error",
            "line": None,
            "col": None,
            "message": f"Write blocked to {_relpath(file_path, project_root)} \u2014 threshold exceeded",
            "code": "BLOCKED_WRITE",
            "file": _relpath(file_path, project_root),
            "language": "unknown",
            "timestamp": now,
        })
        _save(store)


def get_summary(session_id: str | None = None) -> dict[str, Any]:
    """Return a summary of the latest session (or a specific one)."""
    store = _load()
    if session_id:
        for s in store.get("sessions", []):
            if s["session_id"] == session_id:
                return s
        return {}
    sessions = store.get("sessions", [])
    if not sessions:
        return {}
    return sessions[-1]


def get_findings(limit: int = 20) -> list[dict[str, Any]]:
    """Return the most recent *limit* findings across all sessions."""
    store = _load()
    all_findings: list[dict[str, Any]] = []
    for s in store.get("sessions", []):
        all_findings.extend(s.get("findings", []))
    all_findings.sort(key=lambda x: x.get("timestamp", ""), reverse=True)
    return all_findings[:limit]


def get_file_quality() -> list[dict[str, Any]]:
    """Return a list of files with their quality stats, sorted by last_checked desc."""
    store = _load()
    files = []
    for path_str, info in store.get("files", {}).items():
        files.append({
            "filename": os.path.basename(path_str),
            "path": path_str,
            "language": info.get("language", ""),
            "errors": info.get("errors", 0),
            "warnings": info.get("warnings", 0),
            "infos": info.get("infos", 0),
            "last_checked": info.get("last_checked", ""),
        })
    files.sort(key=lambda x: x.get("last_checked", ""), reverse=True)
    return files


def get_trend_data() -> list[dict[str, Any]]:
    """Return time-series data for the quality trend chart."""
    store = _load()
    points = []
    for s in store.get("sessions", []):
        errors = sum(1 for f in s.get("findings", []) if f.get("severity") == "error")
        warnings = sum(1 for f in s.get("findings", []) if f.get("severity") == "warning")
        infos = sum(1 for f in s.get("findings", []) if f.get("severity") == "info")
        points.append({
            "session_id": s.get("session_id", ""),
            "started_at": s.get("started_at", ""),
            "errors": errors,
            "warnings": warnings,
            "infos": infos,
            "files_checked": s.get("files_checked", 0),
            "issues_found": s.get("issues_found", 0),
            "blocked_writes": s.get("blocked_writes", 0),
        })
    return points


def get_tool_status() -> dict[str, dict[str, bool]]:
    """Return tool availability per language."""
    from hermead.config import DEFAULT_CONFIG

    status: dict[str, dict[str, bool]] = {}
    for lang, cfg in DEFAULT_CONFIG.items():
        if lang in ("thresholds", "ignore_paths"):
            continue
        tools_list = ["lint", "type_check", "formatter", "security"]
        lang_status: dict[str, bool] = {}
        for t in tools_list:
            tool_name = cfg.get(t)
            if tool_name is None:
                lang_status[t] = False
            else:
                lang_status[t] = _is_tool_available(tool_name)
        if any(lang_status.values()):
            status[lang] = lang_status
    return status


def reset(project_root: str | Path) -> None:
    """Clear all stored data (for testing / fresh start)."""
    with LOCK:
        store = _load()
        store["sessions"] = []
        store["files"] = {}
        _save(store)


def _find_or_create_session(
    store: dict[str, Any],
    project_root: str | Path,
    session_id: str | None = None,
) -> dict[str, Any]:
    """Find session by id or last, or create one and append to *store*."""
    sessions = store.setdefault("sessions", [])
    if session_id:
        for s in sessions:
            if s["session_id"] == session_id:
                return s
    if sessions:
        return sessions[-1]
    # Create a new session in-place
    sid = datetime.now(UTC).strftime("%Y%m%d_%H%M%S_%f")
    entry = {
        "session_id": sid,
        "project_root": str(project_root),
        "started_at": datetime.now(UTC).isoformat(),
        "files_checked": 0,
        "issues_found": 0,
        "blocked_writes": 0,
        "findings": [],
    }
    sessions.append(entry)
    return entry


def _relpath(file_path: str, project_root: str | Path) -> str:
    try:
        return str(Path(file_path).resolve().relative_to(Path(project_root).resolve()))
    except ValueError:
        return file_path


def _is_tool_available(tool_name: str) -> bool:
    import shutil
    base = tool_name.split()[0]
    return shutil.which(base) is not None
