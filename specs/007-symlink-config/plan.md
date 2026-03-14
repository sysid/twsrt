# Implementation Plan: Symlink-Based Config Management

**Branch**: `007-symlink-config` | **Date**: 2026-03-14 | **Spec**: [spec.md](spec.md)
**Input**: Feature specification from `/specs/007-symlink-config/spec.md`

## Summary

Replace direct writes to `~/.claude/settings.json` with a symlink-based approach: `generate -w` writes to a named target file (e.g. `settings.full.json` or `settings.yolo.json`) and symlinks `settings.json` to it. This enables instant switching between full and yolo configs. Includes migration logic for existing regular files, updated `init` defaults, and comprehensive `config.toml` generation.

## Technical Context

**Language/Version**: Python >=3.11
**Primary Dependencies**: typer (CLI), pathlib (symlinks/paths)
**Storage**: JSON files, filesystem symlinks
**Testing**: pytest, ruff (linting)
**Target Platform**: macOS/Linux (symlink support required; Windows fallback with warning)
**Project Type**: CLI tool
**Performance Goals**: N/A (CLI tool, runs in <1s)
**Constraints**: Must not break existing Claude Code integration — `settings.json` must remain the path Claude reads
**Scale/Scope**: Single-user CLI tool

## Constitution Check

*GATE: Must pass before Phase 0 research. Re-check after Phase 1 design.*

### I. Test-First (NON-NEGOTIABLE)

**Status**: PASS — All implementation tasks will have preceding test tasks. TDD red-green-refactor enforced.

### II. Simplicity

**Status**: PASS — Symlink management is a single helper function. No abstractions beyond what's needed. Migration logic is a straightforward move + symlink.

### III. Project Standards Compliance

**Status**: PASS — Python CLI tool using existing project structure (src/twsrt/, tests/). Makefile, pytest, ruff all in place.

## Project Structure

### Documentation (this feature)

```text
specs/007-symlink-config/
├── plan.md              # This file
├── research.md          # Phase 0 output
├── data-model.md        # Phase 1 output
├── quickstart.md        # Phase 1 output
├── contracts/           # Phase 1 output
│   └── cli.md
└── tasks.md             # Phase 2 output (/speckit.tasks)
```

### Source Code (repository root)

```text
src/twsrt/
├── bin/
│   └── cli.py           # MODIFY: init template, generate -w symlink logic
└── lib/
    ├── claude.py         # READ ONLY (selective_merge unchanged)
    ├── config.py         # MODIFY: new default for claude_settings
    ├── models.py         # MODIFY: add symlink_anchor_path to AppConfig
    └── symlink.py        # NEW: symlink helper functions

tests/
├── bin/
│   └── test_cli.py      # MODIFY: new tests for symlink write + init
└── lib/
    ├── test_config.py    # MODIFY: test new default
    └── test_symlink.py   # NEW: tests for symlink helpers
```

**Structure Decision**: Existing single-project layout. One new file (`symlink.py`) for symlink helper logic — keeps CLI clean and helpers testable independently.

## Complexity Tracking

No violations to justify. Single new module (`symlink.py`) with 3-4 functions.
