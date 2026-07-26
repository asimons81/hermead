"""Tests for the Hermead slash command handlers.
"""
from __future__ import annotations

from hermead.slash_commands import _handle_config, _handle_status, handle


class TestSlashDispatcher:
    """Tests for the top-level slash command dispatcher."""

    def test_empty_args(self) -> None:
        result = handle("")
        assert "Hermead:" in result
        assert "check" in result
        assert "status" in result
        assert "config" in result

    def test_check_no_args(self) -> None:
        result = handle("check")
        assert "Usage" in result
        assert "check" in result

    def test_status(self) -> None:
        result = handle("status")
        assert "Tool Availability" in result or "Global config" in result

    def test_config(self) -> None:
        result = handle("config")
        assert "Config Merge Chain" in result
        assert "Built-in defaults" in result

    def test_unknown_subcommand(self) -> None:
        result = handle("foobar")
        assert "Unknown subcommand" in result

    def test_check_nonexistent_file_no_project(self) -> None:
        """File outside any project should return project-root error."""
        result = handle("check /nonexistent/path/file.py")
        assert "cannot find project root" in result

    def test_register_backward_compat(self) -> None:
        """Ensure the legacy register() path still works."""
        from hermead import register
        r = register()
        assert r is not None
        assert "hooks" in r
        assert "post_tool_call" in r["hooks"]
        assert "metadata" in r


class TestSlashStatus:
    """Tests for /hermead status handler."""

    def test_status_output_shape(self) -> None:
        result = _handle_status("")
        lines = result.split("\n")
        assert len(lines) >= 5
        has_global = any("Global config" in l for l in lines)
        has_availability = any("Tool Availability" in l for l in lines)
        assert has_global or has_availability


class TestSlashConfig:
    """Tests for /hermead config handler."""

    def test_config_contains_structure(self) -> None:
        result = _handle_config("")
        assert "Config Merge Chain" in result
        assert "Effective Config" in result
        assert "python" in result
        assert "thresholds" in result
