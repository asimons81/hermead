---
name: hermead
description: Use when Hermead code quality reports appear in the session, or when configuring project-level linting/formatting tools via the Hermead plugin.
version: 1.0.0
author: asimons81
license: MIT
metadata:
  hermes:
    tags: [code-quality, linting, formatting, type-checking, security-scanning, plugin]
    related_skills: [hermes-agent, debug-sessions, systematic-debugging]
---

# Hermead

Hermead is a Hermes Agent plugin that runs linters, type checkers, formatters, and security scanners on project files automatically after every `write_file` or `patch` tool call.

It hooks into the `post_tool_call` lifecycle and dispatches to the right tool for the file type. No manual step. No leaving the terminal. The results appear inline in the session so you see issues the moment they're introduced.

## Overview

Every time Hermes runs `write_file` or `patch` on a project file, Hermead:

1. Detects the file type from the extension (`.py`, `.ts`, `.go`, `.rs`, `.sh`) or filename (`Dockerfile`, `Makefile`).
2. Walks up from the file to find the project root (looks for `.git`, `.hg`, or `.hermes` directory).
3. Loads effective config: `DEFAULT_CONFIG` → `~/.hermes/hermead.yaml` (global) → `<project>/.hermes/hermead.yaml` (per-project overlay).
4. Auto-detects tooling from project files (`pyproject.toml`, `package.json`, `go.mod`, `Cargo.toml`, `.shellcheckrc`). Auto-detected tools take priority over config.
5. Checks the file against `ignore_paths` patterns — skipped if matched.
6. Routes to the registered runner for each enabled check (lint, type check, format check, security).

## When to Use

- **Code quality reports appear** in your session output. Use this skill to interpret the structured results and understand what each tool checks. Thresholds are advisory and never stop the original tool call.
- **Configuring Hermead for a new project.** Use this skill to set up `.hermes/hermead.yaml` with the right tools, thresholds, and ignore patterns.
- **A tool is missing or not working.** Use this skill to check tool availability and debug runner issues.
- **Don't use for:** writing lint rules, configuring build pipelines that don't run through Hermes, or managing CI/CD systems outside Hermes.

## Reading Reports

Every check returns a list of standardised result items:

```json
{
  "tool": "ruff",
  "severity": "error",
  "line": 42,
  "col": 5,
  "message": "F841 local variable 'x' is assigned to but never used",
  "code": "F841"
}
```

Fields:

| Field | Meaning |
|-------|---------|
| `tool` | The CLI tool that produced the finding (ruff, eslint, mypy, etc.) |
| `severity` | `error`, `warning`, `info`, or `style` |
| `line` / `col` | Source location (may be null for whole-file issues) |
| `message` | Human-readable description |
| `code` | Rule / issue identifier |

Empty results (empty array) mean the check passed cleanly or the tool wasn't available.

## Configuration

### Quick Start

Create `.hermes/hermead.yaml` at your project root:

```yaml
python:
  lint: ruff
  type_check: mypy
  formatter: ruff
  security: semgrep

thresholds:
  lint_warnings: warn
  type_errors: block
  security_high: block
  security_medium: warn

ignore_paths:
  - node_modules/**
  - venv/**
  - __pycache__/**

```

### Global Defaults

Place `~/.hermes/hermead.yaml` for settings that apply across every project. Per-project values merge over global, which merge over built-in defaults.

### Full Config Reference

```yaml
# Per-language tool overrides
python:
  lint: ruff
  type_check: mypy
  formatter: ruff         # or: black
  security: semgrep       # or: bandit

javascript:
  lint: eslint
  type_check: tsc         # TypeScript only
  formatter: prettier
  security: semgrep

go:
  lint: golangci-lint
  type_check: go vet
  formatter: gofmt
  security: gosec

rust:
  lint: clippy
  type_check: cargo check
  formatter: rustfmt
  security: cargo audit

shell:
  lint: shellcheck
  formatter: shfmt

generic:
  lint: semgrep
  security: semgrep

# `block` emits an advisory log warning; it never blocks the source write.
thresholds:
  lint_warnings: warn
  type_errors: block
  security_high: block
  security_medium: warn

# Glob patterns to skip
ignore_paths:
  - node_modules/**
  - venv/**
  - .venv/**
  - __pycache__/**
  - .git/**
  - dist/**
  - build/**
  - target/**
  - .hermes/**

```

Set options in each tool's own project configuration.

## Slash Commands

Hermead registers a `/hermead` slash command with three subcommands. Use them in any Hermes session (CLI, Telegram, Discord, etc.).

### /hermead check

```
/hermead check <file_or_dir>
```

Runs all applicable linters, type checkers, formatters, and security scanners on a file or directory. Uses the same detection and runner dispatch as the auto-hook.

**Examples:**

```
/hermead check src/app.py
→ Hermead check: 1 file(s) checked, 3 finding(s)
  🔍 ruff: 2 errors
  🔒 bandit: 1 error

/hermead check src/
→ Hermead check: 14 file(s) checked, 0 finding(s)
```

### /hermead status

```
/hermead status
```

Shows tool availability per language, config file paths, and session statistics.

**Example output:**

```
Tool Availability:
  python: ✅ lint | ❌ type_check | ✅ formatter | ❌ security
  go: ✅ lint | ✅ type_check | ✅ formatter | ❌ security

Global config: C:\Users\asimo\.hermes\hermead.yaml
  ❌ Not found (using defaults)
Project root: C:\Users\asimo\projects\myapp
Project config: C:\Users\asimo\projects\myapp\.hermes\hermead.yaml
  ✅ Present

Last Session Stats:
  Session id:    20260724_151200_123456
  Files checked: 8
  Issues found:  12
  Blocked writes:0
```

### /hermead config

```
/hermead config
```

Shows the resolved effective configuration, including the merge chain from built-in defaults through global (`~/.hermes/hermead.yaml`) to per-project overrides (`.hermes/hermead.yaml`).

**Example output:**

```
Config Merge Chain:
  1. Built-in defaults (11 top-level keys)
  2. Global: C:\Users\asimo\.hermes\hermead.yaml  [not found]
  3. Project: C:\Users\asimo\projects\myapp\.hermes\hermead.yaml  [present]

Effective Config:
  python:
    lint: ruff
    type_check: mypy
    formatter: ruff
    security: bandit
  ...
  thresholds:
    lint_warnings: warn
    type_errors: block
    security_high: warn
  ignore_paths:
    - node_modules/**
```

## Usage Tips

- Use `/hermead status` to quickly check whether your expected tools are on PATH.
- Use `/hermead config` to debug unexpected config overrides — see the merge chain.
- Use `/hermead check <file>` to manually run checks after fixing reported issues.
- `/hermead check` on a directory recursively finds supported files.

## Supported Languages

| Language | Extensions | Lint | Type Check | Format | Security |
|----------|-----------|------|------------|--------|----------|
| Python | `.py` | ruff | mypy | ruff / black | bandit / semgrep |
| JavaScript / TypeScript | `.js`, `.ts`, `.jsx`, `.tsx`, `.mjs`, `.cjs` | eslint | tsc | prettier | semgrep |
| Go | `.go` | golangci-lint | go vet | gofmt | gosec |
| Rust | `.rs` | clippy | cargo check | rustfmt | cargo audit |
| Shell | `.sh`, `.bash`, `.zsh`, `.fish` | shellcheck | — | shfmt | — |
| Generic | Dockerfile, Makefile, cfg files | semgrep | — | — | semgrep |

## Tool Detection

Hermead auto-detects which tools your project uses by reading config files:

- **Python:** `pyproject.toml` sections (`[tool.ruff]`, `[tool.mypy]`, `[tool.black]`)
- **JavaScript:** `package.json` fields (eslintConfig) and config file presence (`.eslintrc.*`, `.prettierrc.*`, `tsconfig.json`)
- **Go:** `go.mod` content and `.golangci.yml` presence
- **Rust:** `Cargo.toml` content for audit tooling
- **Shell:** `.shellcheckrc` presence

Auto-detection takes priority over explicit config. This means a project with `pyproject.toml` + `[tool.ruff]` will use ruff for linting even if the config file says something else. Setting a configured tool to `null` only removes the configured fallback; it does not disable auto-detection.

## Common Pitfalls

1. **Tool not installed.** Hermead never blocks on a missing tool — it silently returns an empty result. Check availability with `which <tool>`. If the report is empty but you expected findings, the tool probably isn't on PATH.

2. **Config file in wrong location.** Per-project config must go in `<project-root>/.hermes/hermead.yaml`, not `.hermead.yaml` or `hermead.yaml` at root. Global config goes in `~/.hermes/hermead.yaml`.

3. **Auto-detection overriding your config.** If `pyproject.toml` has `[tool.ruff]`, its ruff configuration takes priority over another configured linter. To use a different tool, remove the detected tool configuration.

4. **Sensitive files not ignored.** By default Hermead skips `node_modules/`, `venv/`, `.git/`, and common build output dirs. Add your own patterns if you're using a monorepo with unconventional output paths.

5. **Threshold confusion.** `block` means a prominent warning in the log output. Thresholds are advisory: they cannot block the source tool call and do not discard findings.

6. **Format checks are read-only.** Hermead checks whether a file matches formatter output but never auto-formats. Format-check results appear as `style`-severity items when formatting would change the file. Run the formatter manually or configure a save-hook in your editor.

7. **Plugin not registering.** After `pip install hermead`, verify the plugin loads: `hermes plugin list` should show `hermead`. If it doesn't, check that `pyproject.toml` has the correct entry point (`hermead = "hermead"` under `[project.entry-points."hermes_agent.plugins"]`).

## Verification Checklist

- [ ] After editing a `.py` file, Hermead runs ruff (or configured tool) and shows findings
- [ ] After editing a `.ts` file, Hermead runs eslint + prettier + tsc
- [ ] `~/.hermes/hermead.yaml` global defaults load when no per-project config exists
- [ ] `.hermes/hermead.yaml` overrides global settings
- [ ] Files matching `ignore_paths` produce no findings
- [ ] Unavailable tools produce empty results (no crash, no error)
