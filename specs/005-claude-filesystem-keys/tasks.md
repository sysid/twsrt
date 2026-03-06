# Tasks: Pass-through All Remaining Sandbox Configuration Keys

**Input**: Design documents from `/specs/005-claude-filesystem-keys/`
**Prerequisites**: plan.md, spec.md, research.md, data-model.md, contracts/

**Tests**: TDD is mandatory per constitution. Test tasks precede implementation in every phase.

**Organization**: Tasks grouped by user story for independent implementation and testing.

## Format: `[ID] [P?] [Story] Description`

- **[P]**: Can run in parallel (different files, no dependencies)
- **[Story]**: Which user story this task belongs to (e.g., US1, US2, US3)
- Include exact file paths in descriptions

---

## Phase 1: Setup

**Purpose**: No project initialization needed — existing project. This phase is empty.

**Checkpoint**: Project already set up. Proceed to foundational.

---

## Phase 2: Foundational (Blocking Prerequisites)

**Purpose**: Model changes and key tuples that ALL user stories depend on

**CRITICAL**: No user story work can begin until this phase is complete

- [x] T001 Add `_FILESYSTEM_CONFIG_KEYS` and `_SANDBOX_CONFIG_KEYS` tuples to `src/twsrt/lib/sources.py`
- [x] T002 Add `filesystem_config: dict[str, Any]` and `sandbox_config: dict[str, Any]` fields to `SrtResult` in `src/twsrt/lib/models.py`
- [x] T003 Add `filesystem_config: dict[str, Any]` and `sandbox_config: dict[str, Any]` fields to `AppConfig` in `src/twsrt/lib/models.py`
- [x] T004 Update `SAMPLE_SRT` fixture in `tests/conftest.py` to include `ignoreViolations`, `enableWeakerNestedSandbox`, and `enableWeakerNetworkIsolation` top-level keys
- [x] T005 Update `SAMPLE_CLAUDE_SETTINGS` fixture in `tests/conftest.py` to include `sandbox.filesystem`, `sandbox.enabled`, `sandbox.excludedCommands`, and `sandbox.autoAllowBashIfSandboxed`

**Checkpoint**: Foundation ready — model supports new config fields, fixtures updated

---

## Phase 3: User Story 1 — Generate Filesystem Sandbox Configuration (Priority: P1) MVP

**Goal**: `sandbox.filesystem.{allowWrite, denyWrite, denyRead}` appear in generated output from SRT source

**Independent Test**: Create SRT with all 3 filesystem keys → verify generated JSON has them under `sandbox.filesystem`

### Tests for User Story 1

> **Write these tests FIRST, ensure they FAIL before implementation**

- [x] T006 [P] [US1] Test `read_srt()` extracts all 3 filesystem config keys into `filesystem_config` in `tests/lib/test_sources.py` (class `TestReadSrtFilesystemConfig`)
- [x] T007 [P] [US1] Test `read_srt()` with partial filesystem keys — only present keys in `filesystem_config` in `tests/lib/test_sources.py`
- [x] T008 [P] [US1] Test `read_srt()` with no filesystem section — empty `filesystem_config` in `tests/lib/test_sources.py`
- [x] T009 [P] [US1] Test `read_srt()` preserves empty arrays in `filesystem_config` (e.g., `allowWrite: []`) in `tests/lib/test_sources.py`
- [x] T010 [P] [US1] Test `generate()` outputs all 3 filesystem keys under `sandbox.filesystem` in `tests/lib/test_claude.py`
- [x] T011 [P] [US1] Test `generate()` with partial filesystem config — only present keys in output in `tests/lib/test_claude.py`

### Implementation for User Story 1

- [x] T012 [US1] Implement filesystem config extraction in `read_srt()` in `src/twsrt/lib/sources.py`
- [x] T013 [US1] Extend `ClaudeGenerator.generate()` to emit `sandbox.filesystem` section from `config.filesystem_config` in `src/twsrt/lib/claude.py`
- [x] T014 [US1] Wire `srt_result.filesystem_config` to `config.filesystem_config` in `generate` command in `src/twsrt/bin/cli.py`

**Checkpoint**: `twsrt generate claude` outputs `sandbox.filesystem` when SRT has filesystem keys

---

## Phase 4: User Story 2 — Generate Top-level Sandbox Keys and ignoreViolations (Priority: P1)

**Goal**: `sandbox.{enabled, enableWeakerNetworkIsolation, enableWeakerNestedSandbox, ignoreViolations}` appear in generated output

**Independent Test**: Create SRT with all 4 keys → verify generated JSON has them under `sandbox`

### Tests for User Story 2

> **Write these tests FIRST, ensure they FAIL before implementation**

- [x] T015 [P] [US2] Test `read_srt()` extracts all 4 sandbox config keys into `sandbox_config` in `tests/lib/test_sources.py` (class `TestReadSrtSandboxConfig`)
- [x] T016 [P] [US2] Test `read_srt()` with partial sandbox keys — only present keys in `sandbox_config` in `tests/lib/test_sources.py`
- [x] T017 [P] [US2] Test `read_srt()` with no top-level sandbox keys — empty `sandbox_config` in `tests/lib/test_sources.py`
- [x] T018 [P] [US2] Test `read_srt()` excludes `allowPty` from `sandbox_config` in `tests/lib/test_sources.py`
- [x] T019 [P] [US2] Test `generate()` outputs all 4 top-level sandbox keys in `tests/lib/test_claude.py`
- [x] T020 [P] [US2] Test `generate()` with partial sandbox config — only present keys in output in `tests/lib/test_claude.py`
- [x] T021 [P] [US2] Test `generate()` with `enabled: false` — falsy boolean preserved in output in `tests/lib/test_claude.py`

### Implementation for User Story 2

- [x] T022 [US2] Implement sandbox config extraction in `read_srt()` in `src/twsrt/lib/sources.py`
- [x] T023 [US2] Extend `ClaudeGenerator.generate()` to emit top-level sandbox keys from `config.sandbox_config` in `src/twsrt/lib/claude.py`
- [x] T024 [US2] Wire `srt_result.sandbox_config` to `config.sandbox_config` in `generate` command in `src/twsrt/bin/cli.py`

**Checkpoint**: `twsrt generate claude` outputs all sandbox keys present in SRT

---

## Phase 5: User Story 3 — Omit Absent Keys from Output (Priority: P2)

**Goal**: Keys absent from SRT never appear in generated output; empty sections omitted

**Independent Test**: Generate from minimal SRT (only `network.allowedDomains`) → verify no new sandbox keys appear

### Tests for User Story 3

> **Write these tests FIRST, ensure they FAIL before implementation**

- [x] T025 [P] [US3] Test `generate()` with empty `filesystem_config` — no `sandbox.filesystem` section in output in `tests/lib/test_claude.py`
- [x] T026 [P] [US3] Test `generate()` with empty `sandbox_config` — no top-level sandbox keys in output in `tests/lib/test_claude.py`
- [x] T027 [P] [US3] Test `generate()` with only `filesystem.denyRead` — `sandbox.filesystem` contains only `denyRead` in `tests/lib/test_claude.py`

### Implementation for User Story 3

- [x] T028 [US3] Add conditional emission logic: skip `sandbox.filesystem` section when `filesystem_config` is empty, skip individual top-level keys when absent from `sandbox_config`, in `src/twsrt/lib/claude.py`

**Checkpoint**: Absent SRT keys never leak into generated output

---

## Phase 6: User Story 4 — Claude-only Keys Never Touched (Priority: P1)

**Goal**: `excludedCommands`, `autoAllowBashIfSandboxed`, `allowUnsandboxedCommands`, `allowManagedDomainsOnly` survive generate+apply unchanged

**Independent Test**: Apply generated settings to a settings.json with all 4 Claude-only keys → verify all 4 preserved

### Tests for User Story 4

> **Write these tests FIRST, ensure they FAIL before implementation**

- [x] T029 [P] [US4] Test `selective_merge()` preserves `sandbox.excludedCommands` in `tests/lib/test_claude.py`
- [x] T030 [P] [US4] Test `selective_merge()` preserves `sandbox.autoAllowBashIfSandboxed` in `tests/lib/test_claude.py`
- [x] T031 [P] [US4] Test `selective_merge()` preserves `sandbox.allowUnsandboxedCommands` in `tests/lib/test_claude.py`
- [x] T032 [P] [US4] Test `selective_merge()` merges `sandbox.filesystem` key-by-key (preserving unmanaged keys) in `tests/lib/test_claude.py`
- [x] T033 [P] [US4] Test `selective_merge()` merges top-level sandbox keys via `dict.update()` (preserving Claude-only keys) in `tests/lib/test_claude.py`

### Implementation for User Story 4

- [x] T034 [US4] Extend `selective_merge()` to merge `sandbox.filesystem` key-by-key (same pattern as `sandbox.network`) in `src/twsrt/lib/claude.py`
- [x] T035 [US4] Extend `selective_merge()` to merge top-level sandbox keys via `dict.update()` at `sandbox` level in `src/twsrt/lib/claude.py`

**Checkpoint**: Claude-only keys survive all generate+apply operations

---

## Phase 7: User Story 5 — Drift Detection for All New Keys (Priority: P2)

**Goal**: `twsrt diff claude` reports mismatches for filesystem, top-level, and ignoreViolations keys

**Independent Test**: Generate with specific values, compare against settings.json with different values → verify drift reported

### Tests for User Story 5

> **Write these tests FIRST, ensure they FAIL before implementation**

- [x] T036 [P] [US5] Test `diff()` detects missing `filesystem.config:allowWrite` in `tests/lib/test_diff.py` (class `TestClaudeFilesystemConfigDrift`)
- [x] T037 [P] [US5] Test `diff()` detects extra `filesystem.config:denyRead` in `tests/lib/test_diff.py`
- [x] T038 [P] [US5] Test `diff()` detects value mismatch for filesystem key in `tests/lib/test_diff.py`
- [x] T039 [P] [US5] Test `diff()` detects missing `sandbox.config:enabled` in `tests/lib/test_diff.py` (class `TestClaudeSandboxConfigDrift`)
- [x] T040 [P] [US5] Test `diff()` detects extra `sandbox.config:ignoreViolations` in `tests/lib/test_diff.py`
- [x] T041 [P] [US5] Test `diff()` reports no drift when all sandbox keys match in `tests/lib/test_diff.py`

### Implementation for User Story 5

- [x] T042 [US5] Extend `ClaudeGenerator.diff()` to compare `sandbox.filesystem` keys using `_FILESYSTEM_CONFIG_KEYS` in `src/twsrt/lib/claude.py`
- [x] T043 [US5] Extend `ClaudeGenerator.diff()` to compare top-level sandbox keys using `_SANDBOX_CONFIG_KEYS` in `src/twsrt/lib/claude.py`
- [x] T044 [US5] Wire `filesystem_config` and `sandbox_config` in `diff` command in `src/twsrt/bin/cli.py`

**Checkpoint**: `twsrt diff claude` detects drift for all new sandbox keys

---

## Phase 8: User Story 6 — README Documents Full Mapping (Priority: P2)

**Goal**: README has a complete table mapping every Claude Code sandbox key to its SRT source and management status

**Independent Test**: Read README → verify every Claude sandbox schema key is listed with management status

### Implementation for User Story 6

- [x] T045 [US6] Add "Sandbox Key Mapping" section to `README.md` with complete table of all 17 Claude sandbox keys, SRT source, and management status (managed / Claude-only)
- [x] T046 [US6] Update "Merge Behavior" table in `README.md` to include `sandbox.filesystem` and top-level sandbox key merge strategies

**Checkpoint**: README documents the full SRT → Claude sandbox relationship

---

## Phase 9: Polish & Cross-Cutting Concerns

**Purpose**: Finalize, verify, clean up

- [x] T047 Verify `example/.srt-settings.json` includes all 7 new keys (it already does — confirm no changes needed)
- [x] T048 Run full test suite: `cd src && pytest`
- [x] T049 Run linter: `cd src && ruff check .`
- [x] T050 Run quickstart.md validation steps

---

## Dependencies & Execution Order

### Phase Dependencies

- **Foundational (Phase 2)**: No dependencies — start immediately
- **US1 (Phase 3)**: Depends on Phase 2 (model fields + key tuples)
- **US2 (Phase 4)**: Depends on Phase 2 (model fields + key tuples). Independent of US1.
- **US3 (Phase 5)**: Depends on US1 + US2 (generation logic must exist to test absent key behavior)
- **US4 (Phase 6)**: Depends on US1 + US2 (merge needs generated output with new sections)
- **US5 (Phase 7)**: Depends on US1 + US2 (diff needs generation to produce expected output)
- **US6 (Phase 8)**: Independent — can run in parallel with any phase
- **Polish (Phase 9)**: Depends on all previous phases

### User Story Dependencies

```
Phase 2 (Foundational)
    ├──> US1 (filesystem generation)  ──┐
    ├──> US2 (top-level generation)   ──┼──> US3 (absent keys)
    │                                   ├──> US4 (Claude-only preservation)
    │                                   └──> US5 (drift detection)
    └──> US6 (README) ─────────────────────> (independent)
```

### Parallel Opportunities

- **US1 and US2** can run in parallel (different config groups, different key tuples)
- **US6** can run in parallel with any other phase
- Within each phase, all test tasks marked [P] can run in parallel
- T001, T002, T003 (foundational) are sequential (T001 defines keys, T002/T003 use them)
- T004, T005 (fixtures) can run in parallel with T001-T003

---

## Parallel Example: US1 + US2

```
# After Phase 2 completes, launch US1 and US2 in parallel:

Worker A (US1 - Filesystem):
  T006-T009: Source parser tests (parallel)
  T010-T011: Generator tests (parallel)
  T012: Parser implementation
  T013: Generator implementation
  T014: CLI wiring

Worker B (US2 - Top-level):
  T015-T018: Source parser tests (parallel)
  T019-T021: Generator tests (parallel)
  T022: Parser implementation
  T023: Generator implementation
  T024: CLI wiring
```

---

## Implementation Strategy

### MVP First (User Stories 1 + 2)

1. Complete Phase 2: Foundational (model changes)
2. Complete Phase 3: US1 — filesystem sandbox generation
3. Complete Phase 4: US2 — top-level sandbox generation
4. **STOP and VALIDATE**: `twsrt generate claude` produces correct sandbox output
5. This is a usable MVP — users get all 7 keys in generated output

### Incremental Delivery

1. Foundational → models ready
2. US1 + US2 → generation works (MVP)
3. US3 → absent key edge cases verified
4. US4 → merge preserves Claude-only keys
5. US5 → drift detection complete
6. US6 → documentation complete
7. Each increment is independently valuable

---

## Notes

- [P] tasks = different files, no dependencies
- [Story] label maps task to specific user story
- TDD mandatory: test tasks MUST fail before implementation
- All 7 new keys are pass-through (no transformation)
- Pattern mirrors feature 004 (network keys) — consult for reference
