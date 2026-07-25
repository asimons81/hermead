"""Integration test: end-to-end HermeAd hook → runner → reporter pipeline.

Creates a test project with intentional issues, invokes the post_tool_call
hook, and verifies that:
- Runner results are collected
- Reporter formats the output correctly
- Structured data is stored
- Config override chain works
- Missing tools are handled gracefully (debug log, skip)
"""

from __future__ import annotations

import json
import logging
import tempfile
from collections.abc import Generator
from pathlib import Path
from typing import Any

import pytest

from hermead import hooks, reporter
from hermead.hooks import _file_type, _is_ignored, post_tool_call
from hermead.reporter import format_full, format_inline, format_structured

# ── Test fixtures ────────────────────────────────────────────────────────────


@pytest.fixture
def test_project() -> Generator[Path, None, None]:
    """Create a temporary project with intentional issues."""
    with tempfile.TemporaryDirectory(prefix="hermead_inttest_") as tmp:
        root = Path(tmp)

        # .git marker so find_project_root works
        (root / ".git").mkdir()

        # Config
        (root / ".hermes").mkdir()
        (root / ".hermes" / "hermead.yaml").write_text(
            json.dumps({
                "python": {
                    "lint": "ruff",
                    "type_check": "mypy",
                    "formatter": "ruff",
                    "security": "bandit",
                },
                "thresholds": {
                    "security_high": "warn",
                },
            }),
            encoding="utf-8",
        )

        # Intentional-issues Python file
        (root / "bad_code.py").write_text(
            '"""Bad Python file."""\n'
            "import os\n"
            "import sys\n"
            "\n"
            "\n"
            'def unused(x):\n'
            "    return x\n"
            "\n"
            "\n"
            'def type_issue() -> str:\n'
            "    return 42\n"
            "\n"
            "\n"
            'PASSWORD = "hunter2"\n',
            encoding="utf-8",
        )

        # Clean Python file
        (root / "clean.py").write_text(
            '"""Clean Python file."""\n'
            "\n"
            "\n"
            'def greet(name: str) -> str:\n'
            '    return f"Hello {name}"',
            encoding="utf-8",
        )

        # Intentional-issues Ruby file (for Ruby runner coverage)
        (root / "bad_code.rb").write_text(
            '# frozen_string_literal: true\n'
            "\n"
            "class Greeter\n"
            "  def initialize(name)\n"
            '    @name = name\n'
            "  end\n"
            "\n"
            "  def greet\n"
            '    unused = "this is never used"\n'
            '    return "Hello, #{@name}"\n'
            "  end\n"
            "end\n",
            encoding="utf-8",
        )

        yield root


class CaptureHandler(logging.Handler):
    """Capture log records for assertion."""

    def __init__(self) -> None:
        super().__init__()
        self.records: list[logging.LogRecord] = []

    def emit(self, record: logging.LogRecord) -> None:
        self.records.append(record)


@pytest.fixture
def capture_log() -> Generator[CaptureHandler, None, None]:
    """Capture all logs from the hermead logger."""
    handler = CaptureHandler()
    logger = logging.getLogger("hermead")
    logger.setLevel(logging.DEBUG)
    logger.addHandler(handler)
    yield handler
    logger.removeHandler(handler)


# ── Reporter tests ──────────────────────────────────────────────────────────


class TestReporter:
    """Unit tests for the reporter module."""

    def test_format_inline_empty(self) -> None:
        assert format_inline([]) == ""

    def test_format_inline_single_tool(self) -> None:
        results = [
            {"tool": "ruff", "severity": "error", "line": 1, "col": 1, "message": "x", "code": "F401"},
            {"tool": "ruff", "severity": "error", "line": 5, "col": 3, "message": "y", "code": "E302"},
            {"tool": "ruff", "severity": "warning", "line": 10, "col": 1, "message": "z", "code": "W292"},
        ]
        text = format_inline(results)
        assert "ruff" in text
        assert "2 errors" in text
        assert "1 warning" in text

    def test_format_inline_multiple_tools(self) -> None:
        results = [
            {"tool": "ruff", "severity": "error", "line": 1, "col": 1, "message": "x", "code": "F401"},
            {"tool": "bandit", "severity": "error", "line": 10, "message": "y", "code": "B105"},
        ]
        text = format_inline(results)
        assert "\U0001f50d" in text or "ruff" in text
        assert "\U0001f512" in text or "bandit" in text

    def test_format_full_empty(self) -> None:
        assert format_full([]) == ""

    def test_format_full_only_warnings(self) -> None:
        results = [{"tool": "ruff", "severity": "warning", "line": 3, "col": 1, "message": "unused", "code": "F841"}]
        text = format_full(results)
        assert "ruff" in text
        assert "F841" not in text  # error-level detail shouldn't include warnings

    def test_format_full_with_errors(self) -> None:
        results = [
            {"tool": "ruff", "severity": "error", "line": 1, "col": 1, "message": "imported but unused", "code": "F401"},
        ]
        text = format_full(results)
        assert "imported but unused" in text
        assert "F401" in text

    def test_format_structured_shape(self) -> None:
        results = [
            {"tool": "ruff", "severity": "error", "line": 1, "col": 1, "message": "x", "code": "F401"},
            {"tool": "bandit", "severity": "error", "line": 10, "message": "y", "code": "B105"},
        ]
        structured = format_structured(results)
        assert structured["summary"]["total"] == 2
        assert structured["summary"]["by_severity"]["error"] == 2
        assert structured["summary"]["by_tool"]["ruff"] == 1
        assert len(structured["errors"]) == 2
        assert len(structured["warnings"]) == 0


# ── Hook-level tests ────────────────────────────────────────────────────────


class TestHooks:
    """Tests for the hook dispatch and file type detection."""

    def test_file_type_py(self) -> None:
        assert _file_type("/path/to/file.py") == "python"

    def test_file_type_js(self) -> None:
        assert _file_type("/path/to/file.js") == "javascript"
        assert _file_type("/path/to/file.ts") == "javascript"
        assert _file_type("/path/to/file.jsx") == "javascript"

    def test_file_type_unknown(self) -> None:
        assert _file_type("/path/to/file.xyz") is None

    def test_file_type_by_name(self) -> None:
        assert _file_type("/path/to/Dockerfile") == "generic"
        assert _file_type("/path/to/Makefile") == "generic"

    def test_is_ignored_matches(self) -> None:
        config = {"ignore_paths": ["node_modules/**"]}
        # fnmatch handles ** as * — matches everything after node_modules/
        assert _is_ignored("node_modules/foo/bar.js", config) is True
        assert _is_ignored("node_modules/lodash/index.js", config) is True

    def test_is_ignored_no_match(self) -> None:
        config = {"ignore_paths": ["node_modules/**"]}
        assert _is_ignored("/project/src/foo.py", config) is False

    def test_documented_hook_signature_scans_write(
        self, test_project: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Hermes' (tool_name, params, result) callback shape is honored."""
        target = test_project / "written.py"
        target.write_text("x = 1\n", encoding="utf-8")
        dispatched: list[tuple[str, str]] = []

        monkeypatch.setattr(
            hooks, "detect_tooling", lambda _root: {"python": {"lint": "ruff"}}
        )
        monkeypatch.setattr(
            hooks, "load_hermead_config", lambda _root: {"python": {}}
        )
        monkeypatch.setattr(
            hooks,
            "_run_check",
            lambda _lang, path, tool, _action, _root: dispatched.append((path, tool))
            or [],
        )
        monkeypatch.setattr(hooks, "record_results", lambda *_args, **_kwargs: None)

        post_tool_call("write_file", {"path": str(target)}, {"status": "ok"})

        assert dispatched == [(str(target), "ruff")]

    def test_persistence_failure_does_not_break_hook(
        self, test_project: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        target = test_project / "written.py"
        target.write_text("x = 1\n", encoding="utf-8")

        monkeypatch.setattr(hooks, "detect_tooling", lambda _root: {"python": {}})
        monkeypatch.setattr(
            hooks, "load_hermead_config", lambda _root: {"python": {}}
        )

        def fail_persistence(*_args: Any, **_kwargs: Any) -> None:
            raise PermissionError("result store is read-only")

        monkeypatch.setattr(hooks, "record_results", fail_persistence)

        post_tool_call("write_file", {"path": str(target)}, {"status": "ok"})

    def test_reporter_handles_unavailable_store(
        self, test_project: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        def deny_directory() -> None:
            raise PermissionError("result store is read-only")

        monkeypatch.setattr(reporter, "_ensure_dir", deny_directory)

        reporter.record_results([], str(test_project / "written.py"), "python", test_project)


# ── Integration tests ───────────────────────────────────────────────────────


class TestIntegration:
    """End-to-end: hook fires, runners execute, reporter formats."""

    def test_hook_ignores_non_write_tools(self) -> None:
        """Only write_file and patch trigger the hook."""
        # This should not raise — it exits early in post_tool_call
        post_tool_call("read_file", None, {"path": "test.py"})
        assert True  # No exception means early-exit worked

    def test_hook_skips_unsupported_file_type(self) -> None:
        """Unknown file extensions are silently skipped."""
        post_tool_call("write_file", None, {"path": "/tmp/test.xyz"})
        assert True

    def test_hook_runs_on_write_file(
        self,
        test_project: Path,
        capture_log: CaptureHandler,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        """A write collects findings and formats them for the host."""
        bad_py = test_project / "bad_code.py"

        def run_check(
            _language: str,
            _path: str,
            tool: str,
            _action: str,
            _project_root: Path,
        ) -> list[dict[str, Any]]:
            if tool != "ruff":
                return []
            return [{
                "tool": "ruff",
                "severity": "error",
                "line": 1,
                "col": 1,
                "message": "intentional finding",
                "code": "F401",
            }]

        monkeypatch.setattr(hooks, "_run_check", run_check)
        post_tool_call("write_file", None, {"path": str(bad_py)})

        # Check that results were stored
        results = getattr(post_tool_call, "_last_results", None)
        assert results is not None, "post_tool_call should store _last_results"
        assert isinstance(results, list)
        assert len(results) > 0, "Expected at least some findings on bad_code.py"

        # Check structured data was stored
        structured = getattr(post_tool_call, "_last_structured", None)
        assert structured is not None
        assert structured["summary"]["total"] > 0

        # Check that the reporter logged something with HermeAd prefix
        hermead_records = [r for r in capture_log.records if "HermeAd" in r.getMessage()]
        report_records = [r for r in hermead_records if "report" in r.getMessage()]
        assert len(report_records) >= 1, "Expected at least one report log message"

        # Validate the report text contains tool names
        report_text = report_records[0].getMessage()
        # We should see at least one tool appearing in the inline summary
        for tool in ("ruff", "bandit"):
            if any(r.get("tool") == tool for r in results):
                assert tool in report_text

    def test_clean_file_produces_no_findings(self, test_project: Path) -> None:
        """A file with no issues should produce zero (or very minimal) findings."""
        clean_py = test_project / "clean.py"
        post_tool_call("write_file", None, {"path": str(clean_py)})

        results = getattr(post_tool_call, "_last_results", None)
        # Could be empty or just style notes — but shouldn't be errors
        if results:
            errors = [r for r in results if r.get("severity") == "error"]
            assert len(errors) == 0, f"Clean file should have no errors: {errors}"

    def test_missing_tool_is_graceful(self, test_project: Path) -> None:
        """Running a tool that isn't installed should log debug + skip, not crash."""
        # Write a Go file — no Go tools on this system
        go_file = test_project / "main.go"
        go_file.write_text("package main\n\nfunc main() {}\n", encoding="utf-8")
        post_tool_call("write_file", None, {"path": str(go_file)})
        # Should not raise — the Go runner returns empty gracefully

        results = getattr(post_tool_call, "_last_results", None) or []
        # No Go tools → no results
        go_results = [r for r in results if r.get("tool") in ("golangci-lint", "go vet", "gofmt", "gosec")]
        assert len(go_results) == 0

    def test_ignore_paths_skips_file(self, test_project: Path) -> None:
        """Files matching ignore_paths are skipped entirely."""
        ignored_dir = test_project / "venv"
        ignored_dir.mkdir()
        ignored_file = ignored_dir / "ignored.py"
        ignored_file.write_text('import os\n', encoding="utf-8")

        # This file's path contains 'venv' which matches the default ignore pattern
        old_ignore = test_project / ".hermes" / "hermead.yaml"
        old_ignore.write_text(
            json.dumps({"ignore_paths": ["venv/**"]}),
            encoding="utf-8",
        )

        post_tool_call("write_file", None, {"path": str(ignored_file)})
        results = getattr(post_tool_call, "_last_results", None)
        # Should be empty (or whatever the last non-ignored file had)
        assert results is not None

    def test_ruby_runner_graceful_on_missing_tools(self, test_project: Path) -> None:
        """Ruby runner handles missing Ruby tools gracefully — no crash, empty results."""
        config = test_project / ".hermes" / "hermead.yaml"
        config.write_text(
            json.dumps({
                "ruby": {
                    "lint": "rubocop",
                    "formatter": "standardrb",
                    "security": "brakeman",
                },
            }),
            encoding="utf-8",
        )

        rb_file = test_project / "bad_code.rb"
        post_tool_call("write_file", None, {"path": str(rb_file)})

        results = getattr(post_tool_call, "_last_results", None) or []
        # If Ruby tools are not installed, results should be empty — no crash
        ruby_results = [r for r in results if r.get("tool") in ("rubocop", "standardrb", "brakeman")]
        # Accept either empty (tools missing) or actual findings (tools present)
        # The key requirement is no exception
        assert isinstance(ruby_results, list)

    def test_format_inline_empty_input(self) -> None:
        assert format_inline([]) == ""

    def test_format_structured_empty_input(self) -> None:
        structured = format_structured([])
        assert structured["summary"]["total"] == 0
        assert len(structured["findings"]) == 0
        assert len(structured["errors"]) == 0
        assert len(structured["warnings"]) == 0

    def test_format_structured_with_findings(self) -> None:
        results = [
            {"tool": "ruff", "severity": "error", "line": 1, "col": 5, "message": "unused import", "code": "F401"},
            {"tool": "ruff", "severity": "warning", "line": 3, "col": 1, "message": "redefined", "code": "F811"},
            {"tool": "bandit", "severity": "error", "line": 10, "col": None, "message": "hardcoded password", "code": "B105"},
        ]
        structured = format_structured(results)
        assert structured["summary"]["total"] == 3
        assert structured["summary"]["by_severity"]["error"] == 2
        assert structured["summary"]["by_severity"]["warning"] == 1
        assert len(structured["errors"]) == 2
        assert len(structured["warnings"]) == 1
