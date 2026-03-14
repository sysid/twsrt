# Implementation Plan: YOLO Mode

**Branch**: `006-yolo-mode` | **Date**: 2026-03-14 | **Spec**: [spec.md](spec.md)
**Input**: Feature specification from `/specs/006-yolo-mode/spec.md`

## Summary

Add a `--yolo` flag to `twsrt generate` and `twsrt diff` that produces permissive agent configurations. YOLO mode excludes all "ask" rules from bash-rules.json and generates deny-only configs. For Claude, output goes to `settings.yolo.json` (no `permissions.ask`, keep `permissions.allow` with WebFetch entries). For Copilot, output starts with `--yolo` flag followed by `--deny-tool` and `--deny-url` entries only (no `--allow-*` entries, which are subsumed by `--yolo`).

## Technical Context

**Language/Version**: Python >=3.11
**Primary Dependencies**: typer, tomllib (stdlib)
**Storage**: JSON + TOML files
**Testing**: pytest (fail_under = 85%)
**Target Platform**: macOS/Linux CLI
**Project Type**: CLI tool
**Performance Goals**: < 2 seconds for any generate/diff operation
**Constraints**: No new dependencies. Minimal changes to existing Protocol.
**Scale/Scope**: Single-user CLI, ~12 source files, ~12 test files

## Constitution Check

*GATE: Must pass before Phase 0 research. Re-check after Phase 1 design.*

### I. Test-First (NON-NEGOTIABLE) — PASS

All implementation tasks will have test tasks preceding them. TDD cycle enforced.

### II. Simplicity — PASS

- No new abstractions: `yolo` flag added to existing `AppConfig` dataclass
- No Protocol changes: generators already receive `AppConfig`
- `yolo_path()` is a simple path manipulation helper, not an abstraction
- No backward compatibility shims needed

### III. Project Standards Compliance — PASS

- Python >=3.11 CLI project, follows existing patterns
- pytest for testing, ruff for linting
- No infrastructure changes (Makefile, VERSION, etc.)

## Project Structure

### Documentation (this feature)

```text
specs/006-yolo-mode/
├── plan.md              # This file
├── spec.md              # Feature specification
├── research.md          # Phase 0 output
├── data-model.md        # Phase 1 output
├── quickstart.md        # Phase 1 output
├── contracts/
│   └── cli.md           # CLI contract
└── tasks.md             # Phase 2 output (created by /speckit.tasks)
```

### Source Code (repository root)

```text
src/twsrt/
├── bin/
│   └── cli.py           # --yolo flag on generate + diff commands
├── lib/
│   ├── models.py        # AppConfig + yolo_path() helper
│   ├── config.py        # Load yolo path overrides from config.toml
│   ├── claude.py        # Yolo generation: omit ask, keep allow
│   ├── copilot.py       # Yolo generation: --yolo flag, omit --allow-*
│   └── agent.py         # (unchanged)

tests/
├── lib/
│   ├── test_models.py   # yolo_path(), AppConfig fields
│   ├── test_config.py   # Yolo config loading
│   ├── test_claude.py   # Yolo Claude output
│   ├── test_copilot.py  # Yolo Copilot output
│   └── test_diff.py     # Yolo diff targets
└── bin/
    └── test_cli.py      # --yolo integration tests
```

**Structure Decision**: Single project, existing layout. No new directories or modules needed.

## Design Decisions

### D1: Allow Statement Handling (Recommendations)

#### Claude `permissions.allow` in YOLO mode → INCLUDE

- ClaudeGenerator only produces `WebFetch(domain:...)` allow entries from NETWORK/ALLOW rules
- In bypass mode these are technically redundant, but:
  - They keep `permissions` and `sandbox.network.allowedDomains` consistent
  - They make the config functional even without `--dangerously-skip-permissions`
  - They are harmless (redundant ≠ conflicting)
- **No blanket tool allows** (Read, Edit, etc.) are generated — those only come from `selective_merge()` with existing settings.json, which doesn't apply to yolo files

#### Claude `permissions.ask` in YOLO mode → OMIT ENTIRELY

- Not just an empty list — omit the key from the JSON output
- This is the core yolo behavior: no prompts for anything not explicitly denied

#### Copilot `--allow-tool` / `--allow-url` in YOLO mode → OMIT

- `--yolo` expands to `--allow-all` which subsumes `--allow-all-tools`, `--allow-all-paths`, `--allow-all-urls`
- Emitting `--allow-tool 'shell(*)'` after `--yolo` is pure noise
- Emitting `--allow-url 'github.com'` after `--yolo` is pure noise

#### Copilot `--deny-url` in YOLO mode → INCLUDE

- Deny overrides allow, even with `--yolo`'s `--allow-all-urls`
- Required by FR-006 (non-bash-rules config included identically)

### D2: State Carrier — `AppConfig.yolo` field

- Add `yolo: bool = False` to existing `AppConfig` dataclass
- No Protocol changes — `AppConfig` already flows through `generate()` and `diff()`
- Each generator checks `config.yolo` and adjusts output structure accordingly

### D3: YOLO Path Derivation

- `yolo_path(p: Path) -> Path`: insert `.yolo` before file extension
- Optional config.toml overrides: `claude_settings_yolo`, `copilot_output_yolo`
- CLI resolves effective path: config override > auto-derived > None

### D4: No `selective_merge()` for YOLO files

- `settings.yolo.json` is a standalone file — no merging with existing content
- Standard `settings.json` already handles merge; yolo is a fresh write every time
- This simplifies implementation and avoids the question of "what existing allows to preserve"

## Complexity Tracking

No violations to justify. All changes use existing patterns and data structures.
