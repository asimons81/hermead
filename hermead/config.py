"""Configuration loader for HermeAd.

Loads .hermes/hermead.yaml with per-project first, then global fallback.
"""

from __future__ import annotations

import os
from pathlib import Path
from typing import Any

import yaml

DEFAULT_CONFIG: dict[str, Any] = {
    "python": {
        "lint": "ruff",
        "type_check": "mypy",
        "formatter": "ruff",
        "security": "semgrep",
    },
    "javascript": {
        "lint": "eslint",
        "type_check": "tsc",
        "formatter": "prettier",
        "security": "semgrep",
    },
    "go": {
        "lint": "golangci-lint",
        "type_check": "go vet",
        "formatter": "gofmt",
        "security": "gosec",
    },
    "rust": {
        "lint": "clippy",
        "type_check": "rustc",
        "formatter": "rustfmt",
        "security": "cargo audit",
    },
    "shell": {
        "lint": "shellcheck",
        "type_check": None,
        "formatter": "shfmt",
        "security": None,
    },
    "ruby": {
        "lint": "rubocop",
        "type_check": None,
        "formatter": "standardrb",
        "security": "brakeman",
    },
    "generic": {
        "lint": "semgrep",
        "type_check": None,
        "formatter": None,
        "security": "semgrep",
    },
    "thresholds": {
        "lint_warnings": "warn",
        "type_errors": "block",
        "security_high": "block",
        "security_medium": "warn",
    },
    "ignore_paths": [
        "node_modules/**",
        "venv/**",
        ".venv/**",
        "__pycache__/**",
        ".git/**",
        "dist/**",
        "build/**",
        "target/**",
        ".hermes/**",
    ],
    "extra_args": {},
}


def find_project_root(path: str | Path | None = None) -> Path | None:
    """Walk up from *path* (default: cwd) looking for a .git, .hg, or .hermes directory."""
    start = Path(path or os.getcwd()).resolve()
    for ancestor in [start] + list(start.parents):
        if (ancestor / ".git").is_dir():
            return ancestor
        if (ancestor / ".hg").is_dir():
            return ancestor
        if (ancestor / ".hermes").is_dir():
            return ancestor
    return None


def load_hermead_config(path: str | Path | None = None) -> dict[str, Any]:
    """Load the effective HermeAd config, merging global → per-project overrides.

    1. Start with DEFAULT_CONFIG.
    2. Overlay ``~/.hermes/hermead.yaml`` if it exists (global).
    3. Overlay ``<project-root>/.hermes/hermead.yaml`` if it exists (per-project).
    """
    config: dict[str, Any] = _deep_merge({}, DEFAULT_CONFIG)

    # Global fallback
    global_path = Path.home() / ".hermes" / "hermead.yaml"
    if global_path.is_file():
        with open(global_path, encoding="utf-8") as fh:
            global_cfg: dict[str, Any] = yaml.safe_load(fh) or {}
        config = _deep_merge(config, global_cfg)

    # Per-project override
    project_root = find_project_root(path)
    if project_root is not None:
        local_path = project_root / ".hermes" / "hermead.yaml"
        if local_path.is_file():
            with open(local_path, encoding="utf-8") as fh:
                local_cfg: dict[str, Any] = yaml.safe_load(fh) or {}
            config = _deep_merge(config, local_cfg)

    return config


def _deep_merge(base: dict, overlay: dict) -> dict:
    """Recursively merge *overlay* into *base* (keys in overlay win)."""
    merged = dict(base)
    for key, value in overlay.items():
        if key in merged and isinstance(merged[key], dict) and isinstance(value, dict):
            merged[key] = _deep_merge(merged[key], value)
        else:
            merged[key] = value
    return merged
