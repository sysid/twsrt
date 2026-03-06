# Implementation Plan: Pass-through All Remaining Sandbox Configuration Keys

**Branch**: `005-claude-filesystem-keys` | **Date**: 2026-03-06 | **Spec**: [spec.md](spec.md)
**Input**: Feature specification from `/specs/005-claude-filesystem-keys/spec.md`

## Summary

Extend the SRT-to-Claude-Code pipeline to pass through 7 additional sandbox configuration keys: 3 filesystem keys (`allowWrite`, `denyWrite`, `denyRead`), 3 top-level booleans (`enabled`, `enableWeakerNetworkIsolation`, `enableWeakerNestedSandbox`), and 1 object (`ignoreViolations`). Update drift detection and selective merge to handle the new keys. Document the full SRT → Claude sandbox mapping in README. Ensure 4 Claude-only keys are never touched.

## Technical Context

**Language/Version**: Python >=3.11
**Primary Dependencies**: typer (CLI), pytest (testing), ruff (linting)
**Storage**: JSON files (`.srt-settings.json` → `settings.json`)
**Testing**: pytest
**Target Platform**: macOS / Linux
**Project Type**: CLI tool
**Performance Goals**: N/A (offline config generation)
**Constraints**: Must not break existing behavior for permissions or network keys
**Scale/Scope**: 4 source files + 4 test files modified, README updated

## Constitution Check

*GATE: Must pass before Phase 0 research. Re-check after Phase 1 design.*

### I. Test-First (NON-NEGOTIABLE)

**Status**: PASS

Plan requires test-first ordering:
- Write failing tests for each component (parser, generator, merge, diff) before implementation
- Each implementation phase is preceded by its corresponding test phase

### II. Simplicity

**Status**: PASS

- All 7 keys are simple pass-through values — no transformation, no new enums
- Follows the exact same pattern established by feature 004 for network keys
- Two new dict fields on `SrtResult` and `AppConfig` — minimal model change
- `selective_merge` extends with the same `dict.update()` pattern for `sandbox.filesystem` and top-level sandbox keys
- No new abstractions, no new files

### III. Project Standards Compliance

**Status**: PASS

- Project type: Python CLI tool with standard layout (`src/`, `tests/`)
- Testing: pytest (existing)
- Linting: ruff (existing)
- No new dependencies

## Project Structure

### Documentation (this feature)

```text
specs/005-claude-filesystem-keys/
├── plan.md              # This file
├── spec.md              # Feature specification
├── research.md          # Design decisions
├── data-model.md        # Data model changes
├── quickstart.md        # Development quickstart
├── contracts/
│   └── cli-contract.md  # CLI output contract changes
└── checklists/
    └── requirements.md  # Spec quality checklist
```

### Source Code (repository root)

```text
src/twsrt/
├── lib/
│   ├── models.py        # MODIFY: Add filesystem_config + sandbox_config to SrtResult and AppConfig
│   ├── sources.py       # MODIFY: Extract filesystem and sandbox pass-through keys
│   └── claude.py        # MODIFY: generate(), diff(), selective_merge() for new keys
├── bin/
│   └── cli.py           # MODIFY: Wire new config fields through pipeline
tests/
├── conftest.py          # MODIFY: Add sandbox keys to SAMPLE_SRT and SAMPLE_CLAUDE_SETTINGS
├── lib/
│   ├── test_sources.py  # MODIFY: Add filesystem/sandbox config extraction tests
│   ├── test_claude.py   # MODIFY: Add generation, merge, Claude-only preservation tests
│   └── test_diff.py     # MODIFY: Add filesystem/sandbox drift tests
README.md                # MODIFY: Add full sandbox mapping table
```

**Structure Decision**: Existing structure preserved. No new files — all changes are modifications.

## Design Approach

### Data Flow (current → proposed)

```
CURRENT:
  read_srt(path) → SrtResult(rules, network_config)
  config.network_config = srt_result.network_config
  gen.generate(rules, config) → JSON (permissions + sandbox.network)
  gen.diff(rules, target, config) → DiffResult
  selective_merge(target, generated) → dict

PROPOSED:
  read_srt(path) → SrtResult(rules, network_config, filesystem_config, sandbox_config)
  config.network_config = srt_result.network_config
  config.filesystem_config = srt_result.filesystem_config
  config.sandbox_config = srt_result.sandbox_config
  gen.generate(rules, config) → JSON (permissions + sandbox.network + sandbox.filesystem + sandbox top-level)
  gen.diff(rules, target, config) → DiffResult (compares all sandbox keys)
  selective_merge(target, generated) → dict (key-by-key merge for sandbox.filesystem + sandbox top-level)
```

### Key Design Decisions

1. **Three separate config dicts** on `SrtResult` and `AppConfig`:
   - `network_config` — already exists (feature 004)
   - `filesystem_config` — `{allowWrite: [...], denyWrite: [...], denyRead: [...]}`
   - `sandbox_config` — `{enabled: bool, enableWeakerNetworkIsolation: bool, enableWeakerNestedSandbox: bool, ignoreViolations: {...}}`

   Why three instead of one big dict: `network_config` keys go under `sandbox.network`, `filesystem_config` keys go under `sandbox.filesystem`, and `sandbox_config` keys go directly under `sandbox`. Different nesting targets = different dicts.

2. **Filesystem keys are pass-through AND produce SecurityRules**: The `denyRead`, `denyWrite`, `allowWrite` arrays continue to be parsed into `SecurityRule` objects (for `permissions.deny` generation). They are ALSO extracted as raw arrays into `filesystem_config` (for `sandbox.filesystem` generation). This is dual-use, not replacement.

3. **`selective_merge` extends with same pattern**: Add `sandbox.filesystem` and top-level sandbox keys using `dict.update()`, identical to existing `sandbox.network` merge.

4. **Claude-only keys are protected by merge strategy**: Since `selective_merge` uses `dict.update()` on existing sandbox sections, keys not present in the generated output are never deleted. The 4 Claude-only keys (`excludedCommands`, `autoAllowBashIfSandboxed`, `allowUnsandboxedCommands`, `allowManagedDomainsOnly`) are preserved automatically.

5. **Drift detection uses explicit key lists**: Like `_NETWORK_CONFIG_KEYS`, add `_FILESYSTEM_CONFIG_KEYS` and `_SANDBOX_CONFIG_KEYS` tuples to `sources.py`. The diff method iterates over these lists to compare generated vs existing.

### Managed Sandbox Keys (after this feature)

| Key path in `sandbox.*` | Source in `.srt-settings.json` | Config dict |
|--------------------------|-------------------------------|-------------|
| `network.allowedDomains` | `network.allowedDomains` | (rules) |
| `network.allowUnixSockets` | `network.allowUnixSockets` | `network_config` |
| `network.allowAllUnixSockets` | `network.allowAllUnixSockets` | `network_config` |
| `network.allowLocalBinding` | `network.allowLocalBinding` | `network_config` |
| `network.httpProxyPort` | `network.httpProxyPort` | `network_config` |
| `network.socksProxyPort` | `network.socksProxyPort` | `network_config` |
| `filesystem.allowWrite` | `filesystem.allowWrite` | `filesystem_config` |
| `filesystem.denyWrite` | `filesystem.denyWrite` | `filesystem_config` |
| `filesystem.denyRead` | `filesystem.denyRead` | `filesystem_config` |
| `enabled` | `enabled` | `sandbox_config` |
| `enableWeakerNetworkIsolation` | `enableWeakerNetworkIsolation` | `sandbox_config` |
| `enableWeakerNestedSandbox` | `enableWeakerNestedSandbox` | `sandbox_config` |
| `ignoreViolations` | `ignoreViolations` | `sandbox_config` |

**Never touched** (Claude-only): `excludedCommands`, `autoAllowBashIfSandboxed`, `allowUnsandboxedCommands`, `network.allowManagedDomainsOnly`

### Implementation Phases

**Phase 1: Parser — extract new config keys (FR-001, FR-004, FR-007)**
- Tests first: add `TestReadSrtFilesystemConfig` and `TestReadSrtSandboxConfig` classes
- Add `_FILESYSTEM_CONFIG_KEYS` and `_SANDBOX_CONFIG_KEYS` tuples to `sources.py`
- Add `filesystem_config` and `sandbox_config` fields to `SrtResult` and `AppConfig`
- Modify `read_srt()` to extract filesystem and sandbox pass-through keys

**Phase 2: Generator — emit new sandbox sections (FR-002, FR-005, FR-008)**
- Tests first: add generation tests for filesystem, top-level, ignoreViolations
- Modify `ClaudeGenerator.generate()` to include `sandbox.filesystem` and top-level sandbox keys
- Omit empty sections (FR-003, FR-006)

**Phase 3: Merge — key-by-key for new sections (FR-011, FR-010)**
- Tests first: add merge tests for filesystem preservation, Claude-only key preservation
- Extend `selective_merge()` for `sandbox.filesystem` and top-level sandbox keys
- Wire new config fields in CLI (`cli.py`)

**Phase 4: Drift detection (FR-012)**
- Tests first: add drift tests for filesystem, top-level, ignoreViolations
- Extend `ClaudeGenerator.diff()` to compare new keys

**Phase 5: Documentation and fixtures (FR-013)**
- Update `SAMPLE_SRT` and `SAMPLE_CLAUDE_SETTINGS` in `conftest.py`
- Update `example/.srt-settings.json` if needed
- Add sandbox mapping table to README
- Run full test suite + ruff check

## Complexity Tracking

No complexity violations. All changes follow established patterns from feature 004.
