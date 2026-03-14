# Tasks: Symlink-Based Config Management

**Input**: Design documents from `/specs/007-symlink-config/`
**Prerequisites**: plan.md (required), spec.md (required for user stories), research.md, data-model.md, contracts/

**Tests**: TDD is mandatory per project constitution. Test tasks precede implementation.

**Organization**: Tasks are grouped by user story to enable independent implementation and testing of each story.

## Format: `[ID] [P?] [Story] Description`

- **[P]**: Can run in parallel (different files, no dependencies)
- **[Story]**: Which user story this task belongs to (e.g., US1, US2, US3)
- Include exact file paths in descriptions

## Phase 1: Setup

**Purpose**: No new project structure needed — existing project. Verify foundation.

- [x] T001 Verify all existing tests pass before starting (`make test`)

---

## Phase 2: Foundational (Blocking Prerequisites)

**Purpose**: Core symlink module and model changes that ALL user stories depend on

**⚠️ CRITICAL**: No user story work can begin until this phase is complete

### Tests

> **NOTE: Write these tests FIRST, ensure they FAIL before implementation**

- [x] T002 [P] Write tests for `ensure_symlink()` in `tests/lib/test_symlink.py`: relative symlink creation, absolute symlink when different dirs, atomic update of existing symlink, idempotent when already correct
- [x] T003 [P] Write tests for `prepare_claude_target()` in `tests/lib/test_symlink.py`: no-op when anchor is symlink, move when anchor is regular file and target missing, error when anchor is regular file and target exists, no-op when anchor does not exist
- [x] T004 [P] Write tests for updated AppConfig defaults in `tests/lib/test_config.py`: `claude_settings_path` defaults to `settings.full.json`, new `symlink_anchor` field defaults to `settings.json`

### Implementation

- [x] T005 [P] Add `symlink_anchor` field to AppConfig in `src/twsrt/lib/models.py` and update `claude_settings_path` default to `~/.claude/settings.full.json`
- [x] T006 [P] Create `src/twsrt/lib/symlink.py` with `ensure_symlink(target, anchor)` — atomic symlink creation using temp symlink + `os.replace()`, relative path when same directory
- [x] T007 Create `prepare_claude_target(anchor, target)` in `src/twsrt/lib/symlink.py` — migration logic: no-op if symlink, move if regular file + no target, error if regular file + target exists
- [x] T008 Update config loading in `src/twsrt/lib/config.py` to use new `claude_settings_path` default (`settings.full.json`)

**Checkpoint**: Foundation ready — `symlink.py` module complete, model updated, config loading updated. All foundational tests pass.

---

## Phase 3: User Story 1 — Generate Claude Config with Symlink (Priority: P1) 🎯 MVP

**Goal**: `generate claude -w` writes to `settings.full.json` and symlinks `settings.json` → target

**Independent Test**: Run `generate claude -w`, verify target file is written and `settings.json` is a symlink pointing to it.

### Tests

> **NOTE: Write these tests FIRST, ensure they FAIL before implementation**

- [x] T009 [P] [US1] Write CLI tests in `tests/bin/test_cli.py`: fresh write creates target + symlink, migration moves regular file + creates symlink, conflict errors out, update merges + leaves symlink, switch re-points symlink

### Implementation

- [x] T010 [US1] Modify `generate` command in `src/twsrt/bin/cli.py` to call `prepare_claude_target()` then `ensure_symlink()` after writing claude target (non-yolo path)

**Checkpoint**: `generate claude -w` creates/updates symlink. All US1 tests pass.

---

## Phase 4: User Story 2 — Generate Claude YOLO Config with Symlink (Priority: P1)

**Goal**: `generate --yolo claude -w` writes to `settings.yolo.json` and symlinks `settings.json` → yolo target

**Independent Test**: Run `generate --yolo claude -w`, verify yolo target file exists and `settings.json` symlinks to it.

### Tests

> **NOTE: Write these tests FIRST, ensure they FAIL before implementation**

- [x] T011 [P] [US2] Write CLI tests in `tests/bin/test_cli.py`: fresh yolo write creates target + symlink, yolo migration moves regular file, yolo conflict errors out, switch from full to yolo re-points symlink

### Implementation

- [x] T012 [US2] Modify `generate` command in `src/twsrt/bin/cli.py` to call `prepare_claude_target()` then `ensure_symlink()` after writing claude yolo target (yolo path)

**Checkpoint**: `generate --yolo claude -w` creates/updates symlink. All US2 tests pass.

---

## Phase 5: User Story 3 — Updated Init Command (Priority: P2)

**Goal**: `twsrt init` generates comprehensive `config.toml` with `settings.full.json` default and commented-out yolo targets

**Independent Test**: Run `twsrt init`, inspect generated `config.toml` for all keys.

### Tests

> **NOTE: Write these tests FIRST, ensure they FAIL before implementation**

- [x] T013 [P] [US3] Write CLI tests in `tests/bin/test_cli.py`: init creates config with `claude_settings = "~/.claude/settings.full.json"`, yolo targets commented out, copilot_output commented out

### Implementation

- [x] T014 [US3] Update `DEFAULT_CONFIG_TOML` in `src/twsrt/bin/cli.py` to include comprehensive template with `settings.full.json` default, commented-out yolo targets, and explanatory comments

**Checkpoint**: `twsrt init` produces comprehensive config. All US3 tests pass.

---

## Phase 6: User Story 4 — Diff with Symlink Awareness (Priority: P3)

**Goal**: `diff` follows symlinks transparently; `diff --yolo` reads yolo target directly

**Independent Test**: Create a yolo symlink, run `diff claude`, verify it reads the correct resolved file.

### Tests

> **NOTE: Write these tests FIRST, ensure they FAIL before implementation**

- [x] T015 [P] [US4] Write diff tests in `tests/bin/test_cli.py` or `tests/lib/test_diff.py`: diff follows symlink to full target, diff --yolo reads yolo target directly

### Implementation

- [x] T016 [US4] Verify and adjust diff target resolution in `src/twsrt/bin/cli.py` to use resolved target paths (symlinks followed transparently by `Path.read_text()`)

**Checkpoint**: Diff works correctly with symlinks. All US4 tests pass.

---

## Phase 7: Polish & Cross-Cutting Concerns

**Purpose**: Edge cases, Windows fallback, cleanup

- [x] T017 [P] Add Windows fallback in `src/twsrt/lib/symlink.py`: catch `OSError` from `os.symlink()`, fall back to direct write with warning
- [x] T018 [P] Add edge case tests in `tests/lib/test_symlink.py`: dangling symlink target, unrelated symlink overwrite with warning, parent directory creation
- [x] T019 Run full test suite and verify zero regressions (`make test`)
- [ ] T020 Run quickstart.md scenarios manually or as integration validation

---

## Dependencies & Execution Order

### Phase Dependencies

- **Setup (Phase 1)**: No dependencies — verify baseline
- **Foundational (Phase 2)**: Depends on Phase 1 — BLOCKS all user stories
- **US1 (Phase 3)**: Depends on Phase 2 — core symlink write
- **US2 (Phase 4)**: Depends on Phase 2 — can run in parallel with US1 (different code paths)
- **US3 (Phase 5)**: Depends on Phase 2 — independent of US1/US2
- **US4 (Phase 6)**: Depends on Phase 2 — independent of US1/US2/US3
- **Polish (Phase 7)**: Depends on all user stories complete

### User Story Dependencies

- **US1 (P1)**: After Phase 2 — no dependency on other stories
- **US2 (P1)**: After Phase 2 — shares symlink module with US1 but different code path in CLI
- **US3 (P2)**: After Phase 2 — independent (init template only)
- **US4 (P3)**: After Phase 2 — independent (diff is read-only)

### Within Each User Story

- Tests MUST be written and FAIL before implementation
- Implementation follows TDD red-green-refactor

### Parallel Opportunities

- T002, T003, T004 can all run in parallel (different test files/sections)
- T005, T006 can run in parallel (different files: models.py vs symlink.py)
- US1 tests (T009) and US2 tests (T011) can run in parallel
- US3 tests (T013) and US4 tests (T015) can run in parallel
- All user stories can run in parallel after Phase 2

---

## Parallel Example: Foundational Phase

```bash
# Launch all foundational tests in parallel:
Task: T002 "Tests for ensure_symlink in tests/lib/test_symlink.py"
Task: T003 "Tests for prepare_claude_target in tests/lib/test_symlink.py"
Task: T004 "Tests for AppConfig defaults in tests/lib/test_config.py"

# Launch parallel implementations:
Task: T005 "Add symlink_anchor to AppConfig in src/twsrt/lib/models.py"
Task: T006 "Create ensure_symlink in src/twsrt/lib/symlink.py"
```

---

## Implementation Strategy

### MVP First (User Story 1 Only)

1. Complete Phase 1: Verify baseline
2. Complete Phase 2: Foundational (symlink module + model)
3. Complete Phase 3: User Story 1
4. **STOP and VALIDATE**: `generate claude -w` creates symlink
5. Proceed to remaining stories

### Incremental Delivery

1. Phase 1 + 2 → Foundation ready
2. Add US1 → Test → MVP: basic symlink write
3. Add US2 → Test → Yolo symlink switching
4. Add US3 → Test → Comprehensive init
5. Add US4 → Test → Diff awareness
6. Phase 7 → Polish, edge cases, full validation

---

## Notes

- [P] tasks = different files, no dependencies
- [Story] label maps task to specific user story for traceability
- TDD mandatory: write tests first, verify they fail, then implement
- Commit after each phase or logical group
- `symlink.py` is the only new file — all other changes modify existing files
- Copilot is explicitly unchanged (FR-009) — no tasks needed
