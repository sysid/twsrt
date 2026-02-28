# Implementation Plan: Extend Claude Network Settings Generation

**Branch**: `004-claude-network-keys` | **Date**: 2026-02-28 | **Spec**: [spec.md](spec.md)
**Input**: Feature specification from `/specs/004-claude-network-keys/spec.md`

## Summary

Extend the SRT-to-Claude-Code pipeline to read and generate 5 additional network configuration keys (`allowUnixSockets`, `allowAllUnixSockets`, `allowLocalBinding`, `httpProxyPort`, `socksProxyPort`) as pass-through values. Remove the legacy nested SRT format branch. Update drift detection and selective merge to handle the new keys.

## Technical Context

**Language/Version**: Python >=3.11
**Primary Dependencies**: typer (CLI), pytest (testing), ruff (linting)
**Storage**: JSON files (`.srt-settings.json` → `settings.json`)
**Testing**: pytest
**Target Platform**: macOS / Linux
**Project Type**: CLI tool
**Performance Goals**: N/A (offline config generation)
**Constraints**: Must not break existing behavior for `allowedDomains` / `deniedDomains`
**Scale/Scope**: 7 source files + 4 test files affected

## Constitution Check

*GATE: Must pass before Phase 0 research. Re-check after Phase 1 design.*

### I. Test-First (NON-NEGOTIABLE)

**Status**: PASS

Plan requires test-first ordering:
- Phase 1 (nested removal): convert fixtures first, then remove code, then verify tests pass
- Phase 2 (new keys): write failing tests for each component (parser, generator, merge, diff) before implementation

### II. Simplicity

**Status**: PASS

- Pass-through keys bypass the `SecurityRule` model entirely (no new enum values, no action/scope expansion)
- `SrtResult` dataclass is the minimal container to carry non-rule data from parser to generator
- Key-by-key merge replaces full dict replacement — one line change, no new abstractions
- No backward compatibility shims — nested format is removed, not deprecated

### III. Project Standards Compliance

**Status**: PASS

- Project type: Python CLI tool with standard layout (`src/`, `tests/`)
- Testing: pytest (existing)
- Linting: ruff (existing)
- No new dependencies

## Project Structure

### Documentation (this feature)

```text
specs/004-claude-network-keys/
├── plan.md              # This file
├── spec.md              # Feature specification
├── research.md          # Design decisions
├── data-model.md        # Data model changes
├── quickstart.md        # Development quickstart
└── checklists/
    └── requirements.md  # Spec quality checklist
```

### Source Code (repository root)

```text
src/twsrt/
├── lib/
│   ├── models.py        # MODIFY: Add SrtResult dataclass, add network_config to AppConfig
│   ├── sources.py       # MODIFY: Remove nested branch, extract network config, return SrtResult
│   ├── claude.py        # MODIFY: generate() uses network_config, diff() accepts config, merge key-by-key
│   ├── agent.py         # MODIFY: Update AgentGenerator Protocol (diff signature)
│   └── copilot.py       # MODIFY: Update diff() signature to accept config
├── bin/
│   └── cli.py           # MODIFY: Wire SrtResult and network_config through pipeline
tests/
├── conftest.py          # MODIFY: Convert SAMPLE_SRT to flat, fix SAMPLE_CLAUDE_SETTINGS
├── lib/
│   ├── test_sources.py  # MODIFY: Convert to flat format, add network config tests
│   ├── test_claude.py   # MODIFY: Add pass-through key tests, merge preservation tests
│   └── test_diff.py     # MODIFY: Add network key drift tests
└── bin/
    └── test_cli.py      # MODIFY: Convert to flat format, add integration tests
```

**Structure Decision**: Existing structure is preserved. No new files created — all changes are modifications to existing files.

## Design Approach

### Data Flow (current → proposed)

```
CURRENT:
  read_srt(path) → list[SecurityRule]
  gen.generate(rules, config) → JSON
  gen.diff(rules, target) → DiffResult
  selective_merge(target, generated) → dict

PROPOSED:
  read_srt(path) → SrtResult(rules, network_config)
  config.network_config = srt_result.network_config
  gen.generate(rules, config) → JSON (includes network_config keys)
  gen.diff(rules, target, config) → DiffResult (compares network_config keys)
  selective_merge(target, generated) → dict (key-by-key merge for sandbox.network)
```

### Key Design Decisions

1. **Pass-through keys bypass SecurityRule entirely**: The 5 new keys are scalar/list config values, not ALLOW/DENY domain patterns. They don't fit the `SecurityRule(scope, action, pattern, source)` shape. Carrying them separately in `SrtResult.network_config` as a plain dict is the simplest approach.

2. **`SrtResult` dataclass**: A named container is clearer than a bare tuple. It's the minimal change to `read_srt()`'s return type that avoids reading the file twice.

3. **`AppConfig.network_config` field**: Since `AppConfig` is already threaded through `generate()` and will be threaded through `diff()`, adding `network_config: dict` to it is the path of least resistance. The CLI populates it from `SrtResult`.

4. **Key-by-key merge**: Change `existing["sandbox"]["network"] = generated[...]` (full replacement) to `existing["sandbox"]["network"].update(generated[...])` (key-by-key). This preserves unmanaged keys like `allowManagedDomainsOnly`.

5. **`diff()` signature change**: Add `config: AppConfig` parameter to the `AgentGenerator` Protocol's `diff()` method. This eliminates the internal `config = AppConfig()` creation (which was already using wrong defaults) and ensures `diff()` has access to `network_config` for generating the expected output.

### Managed Network Keys

The generator explicitly manages these keys in `sandbox.network`:

| Key                  | Source                         | Type          | Handling          |
|----------------------|--------------------------------|---------------|-------------------|
| `allowedDomains`     | NETWORK/ALLOW SecurityRules    | list[str]     | Existing (rules)  |
| `allowUnixSockets`   | `network_config` pass-through  | list[str]     | New                |
| `allowAllUnixSockets`| `network_config` pass-through  | bool          | New                |
| `allowLocalBinding`  | `network_config` pass-through  | bool          | New                |
| `httpProxyPort`      | `network_config` pass-through  | int           | New                |
| `socksProxyPort`     | `network_config` pass-through  | int           | New                |

**Not managed** (preserved during merge): `allowManagedDomainsOnly`, any other unrecognized keys.

### Implementation Phases

**Phase 1: Remove nested SRT format (FR-006, FR-009)**
- Convert all test fixtures (conftest.py, test_sources.py, test_cli.py) from nested to flat SRT format
- Remove the `else` branch in `read_srt()` (sources.py:32-40)
- Fix `SAMPLE_CLAUDE_SETTINGS` fixture (`allowedHosts` → `allowedDomains`)
- Verify all existing tests pass

**Phase 2: Add pass-through network keys (FR-001, FR-002, FR-003)**
- Add `SrtResult` dataclass to models.py
- Add `network_config: dict` field to `AppConfig`
- Modify `read_srt()` to return `SrtResult` with network config extraction
- Modify `generate()` to include pass-through keys in `sandbox.network` output
- Update CLI to wire `SrtResult` through the pipeline

**Phase 3: Update merge and drift detection (FR-007, FR-008)**
- Change `selective_merge()` from full dict replacement to key-by-key update
- Update `AgentGenerator` Protocol: `diff()` accepts `config: AppConfig`
- Update `diff()` in both ClaudeGenerator and CopilotGenerator
- Add network key comparison logic to `ClaudeGenerator.diff()`
- Update CLI diff command to pass config

**Phase 4: Finalize**
- Update `example/.srt-settings.json` with all new network keys
- Full test suite + ruff check

## Complexity Tracking

No complexity violations. All changes are minimal and follow existing patterns.
