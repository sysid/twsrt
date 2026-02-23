# Implementation Plan: Network Domain Flags for Copilot and Claude

**Branch**: `003-copilot-allow-url` | **Date**: 2026-02-23 | **Spec**: [spec.md](spec.md)
**Input**: Feature specification from `/specs/003-copilot-allow-url/spec.md`

## Summary

Add network domain handling to both generators: Copilot emits `--allow-url` / `--deny-url` flags, Claude emits `WebFetch(domain:...)` deny entries for blocked domains. Requires relaxing the `SecurityRule` model to allow `NETWORK/DENY`, parsing `deniedDomains` from SRT config, and updating both generators and their drift detection.

## Technical Context

**Language/Version**: Python >=3.11
**Primary Dependencies**: typer (CLI), pytest (testing), ruff (linting)
**Storage**: JSON files (SRT config, Claude settings, Copilot output)
**Testing**: pytest (`cd src && pytest`)
**Target Platform**: macOS/Linux CLI
**Project Type**: CLI tool
**Performance Goals**: N/A (config file processing)
**Constraints**: N/A
**Scale/Scope**: ~9 files modified, ~100 lines of new code + tests

## Constitution Check

*GATE: Must pass before Phase 0 research. Re-check after Phase 1 design.*

### I. Test-First (NON-NEGOTIABLE)

**PASS**: All implementation tasks will have corresponding test tasks that precede them. The TDD cycle (write failing test → implement → verify green) will be followed for each change. Existing test patterns in `test_copilot.py`, `test_claude.py`, `test_sources.py`, and `test_models.py` provide clear templates.

### II. Simplicity

**PASS**: No new abstractions, patterns, or indirections. Changes follow the exact existing patterns:
- Model: relax one validation line
- Parser: add one field read + one loop (mirrors existing `allowed_domains` pattern)
- Copilot generator: add two `elif` branches (mirrors existing EXECUTE/DENY pattern)
- Claude generator: add one `elif` branch (mirrors existing NETWORK/ALLOW pattern)
- Tests: follow existing test class/method patterns

### III. Project Standards Compliance

**PASS**: Python CLI project. Uses existing project structure (`src/twsrt/`, `tests/`), existing tooling (pytest, ruff), existing patterns (typer CLI, dataclass models). No new infrastructure needed.

## Project Structure

### Documentation (this feature)

```text
specs/003-copilot-allow-url/
├── spec.md              # Feature specification
├── plan.md              # This file
├── research.md          # Phase 0: research findings
├── data-model.md        # Phase 1: data model changes
├── quickstart.md        # Phase 1: quickstart guide
├── contracts/
│   └── cli-contract.md  # Phase 1: CLI output contract changes
├── checklists/
│   └── requirements.md  # Spec quality checklist
└── tasks.md             # Phase 2: implementation tasks (created by /speckit.tasks)
```

### Source Code (repository root)

```text
src/twsrt/lib/
├── models.py      # MODIFY: relax NETWORK validation to allow DENY action
├── sources.py     # MODIFY: parse deniedDomains/deniedHosts from SRT config
├── copilot.py     # MODIFY: generate --allow-url and --deny-url flags
└── claude.py      # MODIFY: generate WebFetch deny entries for denied domains

tests/
├── conftest.py           # MODIFY: add deniedDomains to SAMPLE_SRT, update SAMPLE_CLAUDE_SETTINGS
└── lib/
    ├── test_models.py    # MODIFY: update NETWORK validation tests
    ├── test_sources.py   # MODIFY: add denied domain parsing tests
    ├── test_copilot.py   # MODIFY: add allow-url/deny-url tests, update network test
    └── test_claude.py    # MODIFY: add denied domain deny entry tests, update diff tests
```

**Structure Decision**: No new files or directories. All changes are modifications to existing files following established patterns.

## Complexity Tracking

No complexity violations. All changes are minimal additions following existing patterns — no new abstractions, no new files, no new dependencies.
