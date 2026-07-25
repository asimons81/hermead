"""Tests for project tooling detection."""

from __future__ import annotations

from pathlib import Path

from hermead.detector import detect_tooling


def test_detect_python_tools_from_valid_toml(tmp_path: Path) -> None:
    """TOML tables, unlike INI sections, are parsed without guessing."""
    (tmp_path / "pyproject.toml").write_text(
        """\
[project]
name = "example"
version = "0.1.0"

[tool.ruff]
target-version = "py311"

[tool.mypy]
strict = true
""",
        encoding="utf-8",
    )

    assert detect_tooling(tmp_path)["python"] == {
        "lint": "ruff",
        "type_check": "mypy",
        "formatter": "ruff",
        "security": None,
    }


def test_invalid_pyproject_is_ignored(tmp_path: Path) -> None:
    (tmp_path / "pyproject.toml").write_text("[tool.ruff\n", encoding="utf-8")

    assert detect_tooling(tmp_path) == {}
