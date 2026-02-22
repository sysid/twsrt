# Implementation Plan: Edit Canonical Sources

**Branch**: `002-add-srt-domain` | **Date**: 2026-02-22 | **Spec**: [spec.md](spec.md)
**Input**: Feature specification from `/specs/002-add-srt-domain/spec.md`

## Summary

Add a `twsrt edit <source>` CLI command that opens canonical source
files in the user's editor. Maps short names (`srt`, `bash`) to
resolved config paths and launches `$EDITOR` (fallback `$VISUAL`,
then `vi`). Tiny feature — one new command in `cli.py`, one helper
function, corresponding tests.

## Technical Context

**Language/Version**: Python >=3.11
**Primary Dependencies**: typer (already present)
**Storage**: N/A (reads existing config paths, does not write)
**Testing**: pytest, pytest-mock
**Target Platform**: macOS (primary), Linux (secondary) — CLI tool
**Project Type**: CLI application (Python)
**Performance Goals**: N/A (launches editor, blocks until user closes)
**Constraints**: Must use `os.execvp` or `subprocess.run` to launch editor; no network
**Scale/Scope**: Adds one command with ~30 lines of implementation

## Constitution Check

*GATE: Must pass before Phase 0 research. Re-check after Phase 1 design.*

### I. Test-First (NON-NEGOTIABLE)

**Status: PASS**

Tests for the `edit` command will be written before implementation.
Tests will mock `subprocess.run` to verify correct editor resolution
and file path passing without actually launching an editor.

### II. Simplicity

**Status: PASS**

- No new modules — command lives in `cli.py`
- One helper function to resolve editor (`_resolve_editor()`)
- Source name → path mapping uses existing `AppConfig` fields directly
- No abstraction needed: a dict mapping `{"srt": config.srt_path, "bash": config.bash_rules_path}` suffices

### III. Project Standards Compliance

**Status: PASS**

- Follows existing CLI command pattern in `cli.py` (typer command with `ctx` parameter)
- Tests go in `tests/bin/test_cli.py` alongside existing CLI tests
- No new dependencies, no infrastructure changes

## Project Structure

### Documentation (this feature)

```text
specs/002-add-srt-domain/
├── plan.md              # This file
├── research.md          # Phase 0 output
├── data-model.md        # Phase 1 output
├── quickstart.md        # Phase 1 output
├── contracts/           # Phase 1 output
│   └── cli-contract.md  # CLI edit command contract
└── tasks.md             # Phase 2 output (/speckit.tasks)
```

### Source Code (repository root)

```text
src/
  twsrt/
    bin/
      cli.py             # ADD: edit command + _resolve_editor() helper
tests/
  bin/
    test_cli.py          # ADD: edit command tests
```

**Structure Decision**: No new files. The `edit` command and its
helper function are added directly to the existing `cli.py`. Tests
are added to the existing `test_cli.py`.

## Complexity Tracking

No complexity violations. This is a minimal feature addition.
