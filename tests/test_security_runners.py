"""Focused tests for security-runner dispatch and safe tool handling."""

from __future__ import annotations

import json
import subprocess

from hermead import runners
from hermead.runners import javascript, python, ruby


def test_python_registry_honors_configured_semgrep_tool(monkeypatch) -> None:
    """The registry must not silently replace configured Semgrep with Bandit."""
    seen: dict[str, str] = {}

    def fake_scan(file_path: str, tool: str) -> list[dict[str, str]]:
        seen["tool"] = tool
        return [{"severity": "HIGH", "line": 7, "vuln_type": "rule", "message": "issue"}]

    monkeypatch.setattr(runners, "_py_run_security_scan", fake_scan)

    findings = runners.run("python", "run_security", "example.py", ".", tool="semgrep")

    assert seen == {"tool": "semgrep"}
    assert findings[0]["tool"] == "semgrep"
    assert findings[0]["severity"] == "error"


def test_python_semgrep_invocation_and_parsing(monkeypatch) -> None:
    payload = {"results": [{
        "check_id": "python.lang.security.rule",
        "start": {"line": 12},
        "extra": {"severity": "ERROR", "message": "unsafe call"},
    }]}
    seen: list[str] = []

    monkeypatch.setattr(python, "_check_tool", lambda name: name == "semgrep")

    def fake_run(args: list[str], **kwargs: object) -> subprocess.CompletedProcess[str]:
        seen.extend(args)
        return subprocess.CompletedProcess(args, 0, stdout=json.dumps(payload), stderr="")

    monkeypatch.setattr(python.subprocess, "run", fake_run)

    findings = python.run_security_scan("example.py", tool="semgrep")

    assert seen[0] == "semgrep"
    assert "p/security-audit" in seen
    assert findings == [{
        "severity": "HIGH", "line": 12,
        "vuln_type": "python.lang.security.rule", "message": "unsafe call",
    }]


def test_javascript_semgrep_invocation_and_structured_results(tmp_path, monkeypatch) -> None:
    source = tmp_path / "app.js"
    source.write_text("eval(input)\n", encoding="utf-8")
    (tmp_path / "package.json").write_text("{}", encoding="utf-8")
    payload = {"results": [{
        "check_id": "javascript.lang.security.rule",
        "start": {"line": 1, "col": 1},
        "extra": {"severity": "WARNING", "message": "avoid eval"},
    }]}
    seen: list[str] = []

    monkeypatch.setattr(javascript.shutil, "which", lambda name: "semgrep" if name == "semgrep" else None)

    def fake_run(args: list[str], **kwargs: object) -> subprocess.CompletedProcess[str]:
        seen.extend(args)
        return subprocess.CompletedProcess(args, 0, stdout=json.dumps(payload), stderr="")

    monkeypatch.setattr(javascript.subprocess, "run", fake_run)

    findings = javascript.run_security_scan(str(source), "semgrep")

    assert seen[0] == "semgrep"
    assert "p/security-audit" in seen
    assert findings == [{
        "tool": "semgrep", "severity": "warning", "line": 1, "col": 1,
        "message": "avoid eval", "code": "javascript.lang.security.rule",
    }]


def test_javascript_security_skips_unsupported_tool(tmp_path, monkeypatch) -> None:
    source = tmp_path / "app.js"
    source.write_text("const x = 1;\n", encoding="utf-8")
    monkeypatch.setattr(javascript.subprocess, "run", lambda *args, **kwargs: (_ for _ in ()).throw(AssertionError()))

    assert javascript.run_security_scan(str(source), "unknown") == []


def test_ruby_missing_tool_never_installs_a_gem(monkeypatch) -> None:
    """A post-write check may skip a missing tool but must not mutate PATH/env."""
    monkeypatch.setattr(ruby.shutil, "which", lambda _name: None)
    monkeypatch.setattr(ruby.subprocess, "run", lambda *args, **kwargs: (_ for _ in ()).throw(AssertionError()))

    assert ruby._run_lint("example.rb", ".") == []
