# Tasks: Edit Canonical Sources

**Input**: Design documents from `/specs/002-add-srt-domain/`
**Prerequisites**: plan.md, spec.md, research.md, data-model.md, contracts/cli-contract.md

**Tests**: Included per constitution (Test-First is NON-NEGOTIABLE).

**Organization**: Tasks grouped by user story. US1 and US2 share the same `_resolve_editor()` helper, so US1 includes it as foundational work. US2 and US3 are thin increments on top.

## Format: `[ID] [P?] [Story] Description`

- **[P]**: Can run in parallel (different files, no dependencies)
- **[Story]**: Which user story this task belongs to (e.g., US1, US2, US3)
- Include exact file paths in descriptions

---

## Phase 1: Setup

**Purpose**: No setup needed — project infrastructure already exists. No new files, no new dependencies.

(No tasks — skip to user stories.)

---

## Phase 2: Foundational

**Purpose**: No foundational/blocking prerequisites needed. The `edit` command builds entirely on existing `AppConfig` and CLI infrastructure.

(No tasks — skip to user stories.)

---

## Phase 3: User Story 1 - Edit SRT Settings (Priority: P1) MVP

**Goal**: `twsrt edit srt` opens the SRT settings file in the user's editor.

**Independent Test**: Run `twsrt edit srt` with a configured SRT path and verify the correct file is passed to the editor.

### Tests for User Story 1

> **NOTE: Write these tests FIRST, ensure they FAIL before implementation**

- [x] T001 [US1] Write test for `_resolve_editor()` helper: returns `$EDITOR` when set, falls back to `$VISUAL`, then `vi` in tests/bin/test_cli.py
- [x] T002 [US1] Write test for `twsrt edit srt`: verifies `subprocess.run` is called with resolved editor and SRT path in tests/bin/test_cli.py
- [x] T003 [US1] Write test for `twsrt edit srt` when SRT file does not exist: expects exit code 1 and error message with path in tests/bin/test_cli.py
- [x] T004 [US1] Write test for `twsrt edit srt` when editor exits non-zero: expects warning message and matching exit code in tests/bin/test_cli.py

### Implementation for User Story 1

- [x] T005 [US1] Implement `_resolve_editor()` helper in src/twsrt/bin/cli.py — check `$EDITOR`, `$VISUAL`, fallback to `vi`
- [x] T006 [US1] Implement `edit` command in src/twsrt/bin/cli.py — accept `source` argument, map `srt` to `config.srt_path`, validate file exists, call `subprocess.run([editor, path])`
- [x] T007 [US1] Verify all T001-T004 tests pass (green)

**Checkpoint**: `twsrt edit srt` works end-to-end. MVP complete.

---

## Phase 4: User Story 2 - Edit Bash Rules (Priority: P2)

**Goal**: `twsrt edit bash` opens the bash rules file in the user's editor.

**Independent Test**: Run `twsrt edit bash` with a configured bash rules path and verify correct file is passed to editor.

### Tests for User Story 2

- [x] T008 [US2] Write test for `twsrt edit bash`: verifies editor is called with bash rules path in tests/bin/test_cli.py
- [x] T009 [US2] Write test for `twsrt edit bash` when file does not exist: expects exit code 1 and error message in tests/bin/test_cli.py

### Implementation for User Story 2

- [x] T010 [US2] Add `bash` to source mapping dict in the `edit` command in src/twsrt/bin/cli.py (likely already present from T006 if mapping was built complete — verify and adjust)
- [x] T011 [US2] Verify T008-T009 tests pass (green)

**Checkpoint**: Both `twsrt edit srt` and `twsrt edit bash` work independently.

---

## Phase 5: User Story 3 - Edit Without Argument (Priority: P3)

**Goal**: `twsrt edit` (no argument) shows available source names.

**Independent Test**: Run `twsrt edit` with no argument and verify output lists `srt` and `bash`.

### Tests for User Story 3

- [x] T012 [US3] Write test for `twsrt edit` with no argument: expects output listing available sources in tests/bin/test_cli.py
- [x] T013 [US3] Write test for `twsrt edit foo` (invalid source): expects exit code 1 and error message listing valid sources in tests/bin/test_cli.py

### Implementation for User Story 3

- [x] T014 [US3] Handle missing/invalid source argument in `edit` command in src/twsrt/bin/cli.py — show available sources and exit
- [x] T015 [US3] Verify T012-T013 tests pass (green)

**Checkpoint**: All three user stories work. Feature complete.

---

## Phase 6: Polish & Cross-Cutting Concerns

- [x] T016 Run full test suite (`pytest`) to verify no regressions
- [x] T017 Run `ruff check .` and fix any lint issues in src/twsrt/bin/cli.py
- [x] T018 Validate quickstart.md examples manually (smoke test)

---

## Dependencies & Execution Order

### Phase Dependencies

- **Setup (Phase 1)**: Skipped — nothing to do
- **Foundational (Phase 2)**: Skipped — nothing to do
- **User Story 1 (Phase 3)**: Can start immediately — implements `_resolve_editor()` + core `edit` command
- **User Story 2 (Phase 4)**: Depends on Phase 3 (reuses `_resolve_editor()` and command structure)
- **User Story 3 (Phase 5)**: Depends on Phase 3 (extends the `edit` command's argument handling)
- **Polish (Phase 6)**: Depends on all user stories complete

### User Story Dependencies

- **User Story 1 (P1)**: No dependencies. Creates `_resolve_editor()` and `edit` command. MVP.
- **User Story 2 (P2)**: Depends on US1 (shares same command and helper). Thin addition.
- **User Story 3 (P3)**: Depends on US1 (extends argument handling). Thin addition.

### Within Each User Story

- Tests MUST be written and FAIL before implementation (TDD)
- Implementation follows tests
- Verify green after implementation

### Parallel Opportunities

- T001-T004 (US1 tests) can be written in parallel since they test independent behaviors
- T008-T009 (US2 tests) can be written in parallel
- T012-T013 (US3 tests) can be written in parallel
- US2 and US3 are independent of each other and could be parallelized after US1

---

## Implementation Strategy

### MVP First (User Story 1 Only)

1. Write tests T001-T004 → verify they fail
2. Implement T005-T006 → verify tests pass (T007)
3. **STOP and VALIDATE**: `twsrt edit srt` works

### Incremental Delivery

1. US1 → `twsrt edit srt` works (MVP)
2. US2 → `twsrt edit bash` works
3. US3 → `twsrt edit` (no arg) shows help
4. Polish → full suite green, lint clean

---

## Notes

- All changes are in exactly 2 files: `src/twsrt/bin/cli.py` and `tests/bin/test_cli.py`
- Tests mock `subprocess.run` to avoid actually launching an editor
- The source mapping dict should include both `srt` and `bash` from the start in T006, but US2 tests verify the `bash` path specifically
- Total estimated tasks: 18 (4 test + 3 impl + verify for US1, 2 test + 1 impl + verify for US2, 2 test + 1 impl + verify for US3, 3 polish)
