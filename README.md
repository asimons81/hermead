# HermeAd

[![PyPI version](https://img.shields.io/pypi/v/hermead?color=blue)](https://pypi.org/project/hermead/)
[![License](https://img.shields.io/pypi/l/hermead?color=green)](LICENSE)
[![Python](https://img.shields.io/pypi/pyversions/hermead?color=blueviolet)](https://pypi.org/project/hermead/)
[![CI](https://github.com/asimons81/hermead/actions/workflows/test.yml/badge.svg)](https://github.com/asimons81/hermead/actions/workflows/test.yml)

**HermeAd** is a Hermes Agent plugin that automatically runs linters, type checkers, formatters, and security scanners on project files after every `write_file` or `patch` tool call.

No manual commands. No context switching. Files get checked the moment you write them.

## How It Works

HermeAd registers a single `post_tool_call` hook. After each file modification:

1. Detects the file type from extension or filename
2. Walks up the tree to find the project root (`.git`, `.hg`, or `.hermes` directory)
3. Loads config: built-in defaults → global `~/.hermes/hermead.yaml` → per-project `.hermes/hermead.yaml`
4. Auto-detects tooling from `pyproject.toml`, `package.json`, `go.mod`, `Cargo.toml`, `.shellcheckrc`
5. Routes to the right runner for each check category (lint, type check, format, security)

Results appear inline in the session. Issues surface at the moment of introduction, not after a CI run.

## Quick Install

```bash
pip install hermead
```

From source:

```bash
git clone https://github.com/asimons81/hermead.git
cd hermead
pip install -e ".[dev]"
```

Verify it loaded:

```bash
hermes plugin list
# → hermead should appear
```

## Features

- **Zero-config for common projects.** Works out of the box with ruff + mypy for Python, eslint + prettier + tsc for JS/TS, golangci-lint + go vet + gofmt for Go, clippy + rustfmt for Rust, shellcheck for shell scripts, and rubocop + standardrb + brakeman for Ruby.
- **Auto-detection.** Reads `pyproject.toml`, `package.json`, `go.mod`, `Cargo.toml`, `.shellcheckrc`, and `.rubocop.yml`/`Gemfile` to pick the right tools. Auto-detected tools take priority over config.
- **Per-project config.** `.hermes/hermead.yaml` overrides global `~/.hermes/hermead.yaml`, which overrides built-in defaults.
- **Advisory thresholds.** `block` writes a prominent hook warning for a configured finding category; thresholds never reject the original tool call or remove findings from the report.
- **7 language runners.** Python, JavaScript/TypeScript, Go, Rust, Shell, Ruby, and a Generic runner for config/script files (semgrep).
- **Graceful degredation.** Missing tools produce empty results. No crashes, no spurious errors. Use `which <tool>` to check availability.
- **Ignore patterns.** Skip `node_modules/`, `venv/`, build output dirs, and anything else you add.

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

ignore_paths:
  - node_modules/**
  - venv/**
  - __pycache__/**
```

### Full Reference

```yaml
# Per-language tool assignments. `null` skips the configured fallback for that
# category; a tool detected from project configuration still takes precedence.
python:
  lint: ruff
  type_check: mypy
  formatter: ruff
  security: semgrep

javascript:
  lint: eslint
  type_check: tsc
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

thresholds:
  lint_warnings: warn       # `block` emits an advisory log warning
  type_errors: block
  security_high: block
  security_medium: warn

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

Configure tool-specific options in the tool's normal project configuration
(such as `pyproject.toml`, `eslint.config.*`, or `.golangci.yml`).

## Safety

HermeAd runs local analyzers in the target project's directory. Those tools may
load project configuration, plugins, or dependencies, so only enable HermeAd
for repositories you trust. Review a repository's analyzer configuration before
running checks against unfamiliar code.

## Supported Languages

| Language | Extensions | Lint | Type Check | Format | Security |
|----------|-----------|------|------------|--------|----------|
| Python | `.py` | ruff | mypy | ruff / black | bandit / semgrep |
| JavaScript / TypeScript | `.js`, `.ts`, `.jsx`, `.tsx`, `.mjs`, `.cjs` | eslint | tsc | prettier | semgrep |
| Go | `.go` | golangci-lint | go vet | gofmt | gosec |
| Rust | `.rs` | clippy | cargo check | rustfmt | cargo audit |
| Shell | `.sh`, `.bash`, `.zsh`, `.fish` | shellcheck | — | shfmt | — |
| Ruby | `.rb`, Gemfile, Rakefile | rubocop | — | standardrb | brakeman |
| Generic | Dockerfile, Makefile, `.gitignore`, etc. | semgrep | — | — | semgrep |

## Inline Reports

When HermeAd runs, findings appear in your session as structured results:

```
🔍 ruff: 1 error

  🔍(line 42:5) F841 — local variable 'x' is assigned to but never used (F841)
```

Each result shows the tool, severity, source location, message, and rule code. Empty output means the file passed or the tool wasn't available.

## Contributing

PRs welcome. HermeAd is a young project — the runner interface, result format, and hooks API are still finding their shape.

- Runners live in `hermead/runners/`. Each module self-registers via `register_runner(language, action, func)`.
- The hook dispatcher lives in `hermead/hooks.py`.
- Config loading lives in `hermead/config.py`.
- The registry lives in `hermead/runners/__init__.py`.

Before opening a PR, run the test suite:

```bash
pip install -e ".[dev]"
pytest -v
```

## Plugin Architecture

HermeAd is a Hermes Agent plugin — no MCP server, no web server, no external API. It registers a single hook entry point in `pyproject.toml`:

```toml
[project.entry-points."hermes_agent.plugins"]
hermead = "hermead"
```

The `hermead` module exports `register`, which Hermes uses to load the plugin.

For more on building Hermes plugins, see the [Hermes Agent Plugin Docs](https://hermes-agent.nousresearch.com/docs/plugins).

## License

MIT — see [LICENSE](LICENSE).
