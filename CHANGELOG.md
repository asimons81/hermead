# Changelog

All notable changes to Hermead are documented here.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [0.2.0] — 2026-07-24

### Added

- **Ruby runner** — rubocop (lint), standardrb (format), brakeman (security). Auto-detects `.rb`, `Gemfile`, `Rakefile` and uses already-installed gems. (@t_188a3459)
- **Slash commands** — `/hermead check <file|dir>`, `/hermead status`, `/hermead config` registered via `ctx.register_command`. (@t_4e7f2989)
- **CI pipeline** — GitHub Actions workflow (`test.yml`) running pytest on push and PR, with ruff + mypy dogfooding on Hermead's own source. (@t_72573cd1)
- **Live smoke test** — hook pipeline verified end-to-end in a real Hermes session. Entry point fixed (`hermead:register` -> `hermead` module ref); `pyproject.toml` is parsed as TOML. (@t_9177de73)

### Fixed

- **Rust runner timeout** — clippy/cargo check timeout reduced to 5 seconds; long compiles return a `TIMEOUT` result instead of blocking the tool call. (S1)
- **Rust detection tightening** — `_detect_rust` only matches `cargo audit` in Cargo.toml `[package.metadata]` or `[workspace.metadata]` sections. (S6)
- **Go runner filtering** — `_run_lint_text` and `_run_type_check` now filter results by the specific file path being checked, not the entire project. (W5)
- **README formatting** — replaced box-drawing example with emoji+text output matching the actual reporter. (W4)
- **SKILL.md accuracy** — removed "may abort tool call" threshold claim; documented advisory-only behavior. (W6)
- **16 ruff lint errors** fixed across 9 source files: 3 over-broad `except` clauses (BLE001), 12 missing explicit `check=False` on `subprocess.run` (PLW1510), 1 unused variable (F841). (@t_a390da4e)
