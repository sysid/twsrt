# Implementation Plan: Agent Security Config Generator

**Branch**: `001-agent-security-config` | **Date**: 2026-02-22 | **Spec**: [spec.md](spec.md)
**Input**: Feature specification from `/specs/001-agent-security-config/spec.md`

## Summary

CLI utility (`twsrt`) that reads two canonical sources — SRT
(`~/.srt-settings.json`) for filesystem/network rules and
`~/.twsrt/bash-rules.json` for Bash deny/ask rules — and generates
agent-specific security configurations for Claude Code
(`settings.json`) and Copilot CLI (flag snippets). Includes drift
detection via diff mode. Built as a Python typer+rich CLI following
Tom's Python project standards.

## Technical Context

**Language/Version**: Python >=3.11 (enables `tomllib` stdlib for TOML config)
**Primary Dependencies**: typer (brings rich, click, shellingham transitively)
**Storage**: JSON files (read: `~/.srt-settings.json`, `~/.twsrt/bash-rules.json`; write: `~/.claude/settings.json`), TOML config (`~/.twsrt/config.toml`)
**Testing**: pytest, pytest-cov, pytest-mock
**Target Platform**: macOS (primary), Linux (secondary) — CLI tool
**Project Type**: CLI application (Python, PyPI-distributable)
**Performance Goals**: Generate all agent configs in <10 seconds (SC-001)
**Constraints**: Zero network access required; all operations are local file transforms
**Scale/Scope**: Single-user CLI; ~20 SRT deny rules, ~10 Bash rules, 2 target agents (MVP)

## Constitution Check

*GATE: Must pass before Phase 0 research. Re-check after Phase 1 design.*

### I. Test-First (NON-NEGOTIABLE)

**Status: PASS**

All implementation tasks in the task plan will require corresponding
test tasks that precede them. The TDD red-green-refactor cycle will
be enforced: write test → verify it fails → implement → verify it
passes. No test deletion.

### II. Simplicity

**Status: PASS**

- Single runtime dependency: `typer` (brings rich transitively)
- Flat module layout in `lib/` — one module per agent generator
- `AgentGenerator` Protocol defines the translation interface;
  `ClaudeGenerator` and `CopilotGenerator` implement it.
  Adding a new agent = add a module implementing the Protocol.
- No plugin system or dynamic registration — generators are
  explicitly listed in a module-level registry dict
- stdlib `json` and `tomllib` — no third-party JSON/TOML libraries
- Dataclasses for models, not Pydantic

### III. Project Standards Compliance

**Status: PASS**

- Project type: Python (Section 3 of development-standards.md)
- `src/` layout: `src/twsrt/`
- Makefile with `uv run` prefix for all commands
- VERSION file as single source of truth
- bump-my-version for version management
- ruff for formatting/linting, ty for type checking
- pytest with markers (integration, experimentation)
- pyproject.toml with setuptools backend
- .pre-commit-config.yaml with ruff-format, ruff, ty hooks
- CI/CD via GitHub Actions (push/PR to main)

## Project Structure

### Documentation (this feature)

```text
specs/001-agent-security-config/
├── plan.md              # This file
├── research.md          # Phase 0 output
├── data-model.md        # Phase 1 output
├── quickstart.md        # Phase 1 output
├── contracts/           # Phase 1 output
│   └── cli-contract.md  # CLI command interface contract
└── tasks.md             # Phase 2 output (/speckit.tasks)
```

### Source Code (repository root)

```text
VERSION
Makefile
pyproject.toml
.pre-commit-config.yaml
.gitignore
README.md
src/
  twsrt/
    __init__.py          # empty (version lives in bin/cli.py per rplc pattern)
    bin/
      __init__.py
      cli.py             # typer app, commands: generate, diff, init, version
    lib/
      __init__.py
      config.py          # TOML config loading (~/.twsrt/config.toml)
      sources.py         # Read/validate canonical sources (SRT, bash-rules)
      models.py          # SecurityRule, enums, AppConfig, DiffResult dataclasses
      agent.py           # AgentGenerator Protocol + registry dict
      claude.py          # ClaudeGenerator(AgentGenerator) implementation
      copilot.py         # CopilotGenerator(AgentGenerator) implementation
      diff.py            # Drift detection: compare generated vs existing
tests/
  __init__.py
  conftest.py            # shared fixtures (tmp SRT files, bash-rules, etc.)
  bin/
    test_cli.py          # CLI integration tests via typer.testing.CliRunner
  lib/
    test_sources.py      # canonical source reading/validation
    test_models.py       # model construction and rule mapping
    test_agent.py        # Protocol contract tests (applied to each generator)
    test_claude.py       # Claude Code generation
    test_copilot.py      # Copilot CLI flags generation
    test_diff.py         # drift detection
    test_config.py       # TOML config loading
```

**Structure Decision**: Single project, `src/` layout per
development-standards.md Section 3. Follows rplc's `bin/` + `lib/`
sub-package pattern. Flat module layout in `lib/` — one module per
agent generator. `AgentGenerator` Protocol in `agent.py` defines
the translation interface; each agent module implements it.
Registry dict in `agent.py` maps agent names to generator instances.

## Complexity Tracking

| Violation | Why Needed | Simpler Alternative Rejected Because |
|-----------|------------|-------------------------------------|
| AgentGenerator Protocol abstraction | Tom's explicit request — enables consistent interface for adding future agents (pi-mono, etc.) | Plain functions with matching signatures: works but doesn't enforce the contract or make the extension point visible |
