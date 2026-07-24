"""Auto-detect project tooling from standard project files.

Supports:
- Python (pyproject.toml)
- JavaScript / TypeScript (package.json, .eslintrc.*, .prettierrc.*)
- Go (go.mod, .golangci.yml)
- Rust (Cargo.toml)
- Shell (.shellcheckrc)
"""

from __future__ import annotations

import configparser
import json
from pathlib import Path
from typing import Any


def detect_tooling(project_root: str | Path) -> dict[str, Any]:
    """Auto-detect available linting and formatting tools for a project.

    Returns a dict like::

        {
            "python": {"lint": "ruff", "type_check": "mypy", ...},
            "javascript": {"lint": "eslint", ...},
        }
    """
    root = Path(project_root).resolve()
    detected: dict[str, Any] = {}

    _detect_python(root, detected)
    _detect_javascript(root, detected)
    _detect_go(root, detected)
    _detect_rust(root, detected)
    _detect_shell(root, detected)

    return detected


def _detect_python(root: Path, detected: dict[str, Any]) -> None:
    pyproject = root / "pyproject.toml"
    if not pyproject.is_file():
        return

    cfg = configparser.ConfigParser()
    try:
        # TOML is not INI, but for our narrow pattern (tool.X sections)
        # ConfigParser with '[' as delimiters works well enough.
        # For production use, consider a TOML parser.
        cfg.read_string(pyproject.read_text(encoding="utf-8"))
    except Exception:
        return

    python: dict[str, str | None] = {
        "lint": None,
        "type_check": None,
        "formatter": None,
        "security": None,
    }

    if cfg.has_section("tool.ruff"):
        python["lint"] = "ruff"
        if cfg.has_section("tool.ruff.format") or cfg.has_option("tool.ruff", "format"):
            python["formatter"] = "ruff"
    if cfg.has_section("tool.mypy"):
        python["type_check"] = "mypy"
    if cfg.has_section("tool.black"):
        python["formatter"] = "black"

    if any(python.values()):
        detected["python"] = python


def _detect_javascript(root: Path, detected: dict[str, Any]) -> None:
    pkg = root / "package.json"
    if not pkg.is_file():
        return

    js: dict[str, str | None] = {
        "lint": None,
        "type_check": None,
        "formatter": None,
        "security": None,
    }

    try:
        data = json.loads(pkg.read_text(encoding="utf-8"))
    except Exception:
        return

    # eslint either inline in package.json or as config file
    if "eslintConfig" in data:
        js["lint"] = "eslint"
    else:
        for pattern in [".eslintrc*", ".eslintrc.json", ".eslintrc.js", ".eslintrc.yaml", ".eslintrc.yml"]:
            if list(root.glob(pattern)):
                js["lint"] = "eslint"
                break

    # prettier
    for pattern in [".prettierrc*", ".prettierrc.json", ".prettierrc.js", ".prettierrc.yaml",
                     ".prettierrc.yml", ".prettierrc.toml", "prettier.config.js"]:
        if list(root.glob(pattern)):
            js["formatter"] = "prettier"
            break

    # TypeScript
    if (root / "tsconfig.json").is_file():
        js["type_check"] = "tsc"

    if any(js.values()):
        detected["javascript"] = js


def _detect_go(root: Path, detected: dict[str, Any]) -> None:
    if not (root / "go.mod").is_file():
        return

    go: dict[str, str | None] = {
        "lint": None,
        "type_check": "go vet",
        "formatter": "gofmt",
        "security": None,
    }

    # golangci-lint: check go.mod for dependency OR .golangci.yml at root
    gomod = root / "go.mod"
    if gomod.is_file():
        content = gomod.read_text(encoding="utf-8")
        if "golangci-lint" in content:
            go["lint"] = "golangci-lint"
    if (root / ".golangci.yml").is_file() or (root / ".golangci.yaml").is_file():
        go["lint"] = "golangci-lint"

    # gosec is commonly used but not mandatory
    if gomod.is_file() and "gosec" in gomod.read_text(encoding="utf-8"):
        go["security"] = "gosec"

    detected["go"] = go


def _detect_rust(root: Path, detected: dict[str, Any]) -> None:
    cargo = root / "Cargo.toml"
    if not cargo.is_file():
        return

    rust: dict[str, str | None] = {
        "lint": "clippy",
        "type_check": "rustc",
        "formatter": "rustfmt",
        "security": None,
    }

    content = cargo.read_text(encoding="utf-8")
    if "cargo-audit" in content or "audit" in content.lower():
        rust["security"] = "cargo audit"

    detected["rust"] = rust


def _detect_shell(root: Path, detected: dict[str, Any]) -> None:
    shellcheckrc = root / ".shellcheckrc"
    if not shellcheckrc.is_file():
        return

    detected["shell"] = {
        "lint": "shellcheck",
        "type_check": None,
        "formatter": "shfmt",
        "security": None,
    }
