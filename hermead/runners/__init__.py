"""Runner registry for HermeAd.

Each runner module registers itself at import time via
``register_runner(language, action, func)``.

Use ``runners.run(language, action, file_path, project_root, tool)``
to dispatch a check.

Standard result item::

    {"tool": str, "severity": str, "line": int|None, "col": int|None,
     "message": str, "code": str|None}
"""

from __future__ import annotations

from collections.abc import Callable
from pathlib import Path
from typing import Any

# ── Registry ──────────────────────────────────────────────────────────────

_registry: dict[str, dict[str, Callable[..., list[dict[str, Any]]]]] = {}
# _registry[language][action] -> callable


def register_runner(
    language: str,
    action: str,
    func: Callable[..., list[dict[str, Any]]],
) -> None:
    """Register *func* as the runner for *language* / *action*."""
    _registry.setdefault(language, {})[action] = func


def get_runner(
    language: str, action: str
) -> Callable[..., list[dict[str, Any]]] | None:
    """Return the registered runner for *language* + *action*, or None."""
    return _registry.get(language, {}).get(action)


def run(
    language: str,
    action: str,
    file_path: str,
    project_root: str | Path,
    tool: str | None = None,
) -> list[dict[str, Any]]:
    """Dispatch *action* for *language* to the registered runner.

    Returns an empty list if no runner is registered for the given
    language + action combination.
    """
    func = get_runner(language, action)
    if func is None:
        return []
    return func(file_path=file_path, project_root=project_root, tool=tool)


# ── Python runner adapter ──────────────────────────────────────────────
# python.py exposes run_linter(file_path), run_type_checker(file_path),
# run_formatter(file_path), run_security_scan(file_path, tool).
# We wrap them to align with the (file_path, project_root, tool) signature.

from hermead.runners.python import (
    run_formatter as _py_run_formatter,
)
from hermead.runners.python import (
    run_linter as _py_run_linter,
)
from hermead.runners.python import (
    run_security_scan as _py_run_security_scan,
)
from hermead.runners.python import (
    run_type_checker as _py_run_type_checker,
)


def _py_lint(file_path: str, project_root: str | Path, **kwargs: Any) -> list[dict[str, Any]]:
    return _py_run_linter(file_path)


def _py_type_check(file_path: str, project_root: str | Path, **kwargs: Any) -> list[dict[str, Any]]:
    return _py_run_type_checker(file_path)


def _py_format(file_path: str, project_root: str | Path, **kwargs: Any) -> list[dict[str, Any]]:
    tool = kwargs.get("tool", "black")
    result = _py_run_formatter(file_path, tool=tool)
    if isinstance(result, dict) and result.get("needs_formatting"):
        fix_cmd = f"Run `{tool} format` to fix." if tool == "ruff" else f"Run `{tool}` to fix."
        return [{
            "tool": tool,
            "severity": "style",
            "line": None, "col": None,
            "message": f"File is not {tool}-formatted. {fix_cmd}",
            "code": tool,
        }]
    return []


def _py_security(file_path: str, project_root: str | Path, **kwargs: Any) -> list[dict[str, Any]]:
    tool = kwargs.get("tool", "bandit")
    raw = _py_run_security_scan(file_path, tool=tool)
    normalised: list[dict[str, Any]] = []
    for r in raw:
        sev_raw = (r.get("severity") or "").upper()
        severity = "error" if sev_raw == "HIGH" else ("warning" if sev_raw == "MEDIUM" else "info")
        normalised.append({
            "tool": tool,
            "severity": severity,
            "line": r.get("line"),
            "col": None,
            "message": r.get("message", ""),
            "code": r.get("vuln_type", ""),
        })
    return normalised


register_runner("python", "run_lint", _py_lint)
register_runner("python", "run_type_check", _py_type_check)
register_runner("python", "run_format_check", _py_format)
register_runner("python", "run_security", _py_security)


# ── JavaScript runner adapter ──────────────────────────────────────────
# javascript.py exposes run_linter(file_path, tool), run_formatter(...),
# run_type_checker(file_path, tool), run_security_scan(file_path, tool).

from hermead.runners.javascript import (
    run_formatter as _js_run_formatter,
)
from hermead.runners.javascript import (
    run_linter as _js_run_linter,
)
from hermead.runners.javascript import (
    run_security_scan as _js_run_security_scan,
)
from hermead.runners.javascript import (
    run_type_checker as _js_run_type_checker,
)


def _js_lint(file_path: str, project_root: str | Path, **kwargs: Any) -> list[dict[str, Any]]:
    return _js_run_linter(file_path, kwargs.get("tool", "eslint"))


def _js_type_check(file_path: str, project_root: str | Path, **kwargs: Any) -> list[dict[str, Any]]:
    return _js_run_type_checker(file_path, kwargs.get("tool", "tsc"))


def _js_format(file_path: str, project_root: str | Path, **kwargs: Any) -> list[dict[str, Any]]:
    return _js_run_formatter(file_path, kwargs.get("tool", "prettier"))


def _js_security(file_path: str, project_root: str | Path, **kwargs: Any) -> list[dict[str, Any]]:
    return _js_run_security_scan(file_path, kwargs.get("tool", ""))


register_runner("javascript", "run_lint", _js_lint)
register_runner("javascript", "run_type_check", _js_type_check)
register_runner("javascript", "run_format_check", _js_format)
register_runner("javascript", "run_security", _js_security)


# ── Generic / Go / Rust / Shell runners (self-register on import) ──────

import hermead.runners.generic
import hermead.runners.go
import hermead.runners.ruby
import hermead.runners.rust
import hermead.runners.shell  # noqa: F401
