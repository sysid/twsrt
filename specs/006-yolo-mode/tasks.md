# Tasks: YOLO Mode

**Input**: Design documents from `/specs/006-yolo-mode/`
**Prerequisites**: plan.md (required), spec.md (required for user stories), research.md, data-model.md, contracts/

**Tests**: TDD is mandatory per constitution. Test tasks precede their implementation tasks.

**Organization**: Tasks are grouped by user story to enable independent implementation and testing of each story.

## Format: `[ID] [P?] [Story] Description`

- **[P]**: Can run in parallel (different files, no dependencies)
- **[Story]**: Which user story this task belongs to (e.g., US1, US2, US3)
- Include exact file paths in descriptions

## Phase 1: Foundational (Data Model + Config)

**Purpose**: Add yolo support to AppConfig and config loading — MUST complete before any user story

### Tests

> **Write these tests FIRST, ensure they FAIL before implementation**

- [x] T001 [P] Add tests for `yolo_path()` helper: `settings.json` → `settings.yolo.json`, `copilot-flags.txt` → `copilot-flags.yolo.txt`, extensionless `config` → `config.yolo` in `tests/lib/test_models.py`
- [x] T002 [P] Add tests for new `AppConfig` fields: `yolo` defaults to `False`, `claude_yolo_path` defaults to `None`, `copilot_yolo_path` defaults to `None` in `tests/lib/test_models.py`
- [x] T003 [P] Add tests for config.toml loading of optional `claude_settings_yolo` and `copilot_output_yolo` keys (present and absent cases, tilde expansion) in `tests/lib/test_config.py`

### Implementation

- [x] T004 [P] Add `yolo_path(original: Path) -> Path` helper function to `src/twsrt/lib/models.py` — insert `.yolo` before file extension using `Path.stem` and `Path.suffix`
- [x] T005 [P] Add `yolo: bool = False`, `claude_yolo_path: Path | None = None`, `copilot_yolo_path: Path | None = None` fields to `AppConfig` dataclass in `src/twsrt/lib/models.py`
- [x] T006 Load optional `claude_settings_yolo` and `copilot_output_yolo` from `[targets]` in `src/twsrt/lib/config.py` — same pattern as existing path loading with `.expanduser()`

**Checkpoint**: Foundation ready — `AppConfig` carries yolo state, `yolo_path()` derives output paths, config.toml supports optional overrides

---

## Phase 2: User Story 1 - Generate Claude Config in YOLO Mode (Priority: P1) 🎯 MVP

**Goal**: Generate `settings.yolo.json` with only `permissions.deny` (no `permissions.ask`), keeping `permissions.allow` (WebFetch) and `sandbox` identical to standard mode

**Independent Test**: Run `twsrt generate --yolo claude` and verify output has no `permissions.ask` key, has `permissions.deny` and `permissions.allow`, and `sandbox` matches standard output

### Tests for User Story 1

> **Write these tests FIRST, ensure they FAIL before implementation**

- [x] T007 [P] [US1] Add test in `tests/lib/test_claude.py`: ClaudeGenerator with `config.yolo=True` produces output with `permissions.deny` entries, no `permissions.ask` key, `permissions.allow` with WebFetch entries, and identical `sandbox` section
- [x] T008 [P] [US1] Add test in `tests/lib/test_claude.py`: ClaudeGenerator yolo mode with rules containing both ASK and DENY bash rules — verify ASK-derived `Bash(cmd)` entries are absent from `permissions.deny`, DENY-derived entries are present
- [x] T009 [P] [US1] Add test in `tests/lib/test_claude.py`: ClaudeGenerator yolo mode with no ASK rules in input — output identical to standard mode except missing `permissions.ask` key
- [x] T010 [P] [US1] Add CLI integration test in `tests/bin/test_cli.py`: `generate --yolo claude` prints JSON with no `permissions.ask`; `generate --yolo -w claude` writes to yolo-derived path (not standard path); `generate --yolo -w -n claude` shows dry-run output with yolo path

### Implementation for User Story 1

- [x] T011 [US1] Modify `ClaudeGenerator.generate()` in `src/twsrt/lib/claude.py`: when `config.yolo` is True, skip rules where `action == ASK` in the rule loop, and omit `"ask"` key from the output dict
- [x] T012 [US1] Add `--yolo` flag to `generate` command in `src/twsrt/bin/cli.py`: typer.Option, set `config.yolo = True`, resolve Claude yolo target path as `config.claude_yolo_path or yolo_path(config.claude_settings_path)`, write without `selective_merge()` (always fresh write)

**Checkpoint**: `twsrt generate --yolo claude` produces correct deny-only output and writes to `settings.yolo.json`

---

## Phase 3: User Story 2 - Generate Copilot Config in YOLO Mode (Priority: P2)

**Goal**: Generate Copilot flags starting with `--yolo`, followed by `--deny-tool` (deny section only) and `--deny-url` entries — no `--allow-*` entries

**Independent Test**: Run `twsrt generate --yolo copilot` and verify output starts with `--yolo \`, contains only `--deny-tool` and `--deny-url` entries, no `--allow-tool` or `--allow-url`

### Tests for User Story 2

> **Write these tests FIRST, ensure they FAIL before implementation**

- [x] T013 [P] [US2] Add test in `tests/lib/test_copilot.py`: CopilotGenerator with `config.yolo=True` produces output starting with `--yolo \` as first line, followed by `--deny-tool` entries for DENY rules only, no ASK-derived `--deny-tool`, no `--allow-tool`, no `--allow-url`
- [x] T014 [P] [US2] Add test in `tests/lib/test_copilot.py`: CopilotGenerator yolo mode includes `--deny-url` entries from NETWORK/DENY rules (deny overrides allow)
- [x] T015 [P] [US2] Add test in `tests/lib/test_copilot.py`: CopilotGenerator yolo mode with no ASK rules — output has `--yolo` flag, DENY entries, but no lossy-mapping stderr warning
- [x] T016 [P] [US2] Add CLI integration test in `tests/bin/test_cli.py`: `generate --yolo copilot` prints output starting with `--yolo`; `generate --yolo -w copilot` writes to yolo-derived path

### Implementation for User Story 2

- [x] T017 [US2] Modify `CopilotGenerator.generate()` in `src/twsrt/lib/copilot.py`: when `config.yolo` is True, prepend `--yolo \` as first line, skip ASK rules entirely (no lossy mapping), skip `--allow-tool` and `--allow-url` entries (subsumed by `--yolo`), keep `--deny-tool` (DENY only) and `--deny-url`
- [x] T018 [US2] Wire Copilot yolo target path in `src/twsrt/bin/cli.py`: resolve as `config.copilot_yolo_path or yolo_path(config.copilot_output_path)` when writing in yolo mode (handle `None` copilot_output_path — skip with warning, same as standard mode)

**Checkpoint**: `twsrt generate --yolo copilot` produces correct `--yolo` + deny-only output

---

## Phase 4: User Story 3 - Generate All Agents in YOLO Mode (Priority: P2)

**Goal**: `twsrt generate --yolo all` generates yolo configs for both Claude and Copilot in a single command

**Independent Test**: Run `twsrt generate --yolo all` and verify both outputs appear with correct yolo behavior

### Tests for User Story 3

- [x] T019 [US3] Add CLI integration test in `tests/bin/test_cli.py`: `generate --yolo` (default "all") produces both Claude and Copilot yolo outputs; `generate --yolo -w` writes both to yolo-specific paths

### Implementation for User Story 3

- [x] T020 [US3] Verify `--yolo` flag works with "all" agent target in `src/twsrt/bin/cli.py` — the generator loop already handles "all", ensure yolo path resolution works for each generator in the loop (may already work from T012+T018, verify and fix if needed)

**Checkpoint**: `twsrt generate --yolo` works for all agents

---

## Phase 5: User Story 4 - Diff Against YOLO Config (Priority: P3)

**Goal**: `twsrt diff --yolo` compares generated yolo config against yolo-specific files on disk

**Independent Test**: Generate yolo config, modify the output file, run `twsrt diff --yolo` and verify drift is detected (exit code 1)

### Tests for User Story 4

> **Write these tests FIRST, ensure they FAIL before implementation**

- [x] T021 [P] [US4] Add test in `tests/lib/test_diff.py`: Claude diff in yolo mode compares against yolo target path, detects drift in `permissions.deny` (no ask comparison needed)
- [x] T022 [P] [US4] Add test in `tests/lib/test_diff.py`: Copilot diff in yolo mode compares against yolo target path, detects missing/extra `--deny-tool` entries
- [x] T023 [P] [US4] Add CLI integration test in `tests/bin/test_cli.py`: `diff --yolo claude` with matching yolo file exits 0; with drifted file exits 1; with missing file exits 2

### Implementation for User Story 4

- [x] T024 [US4] Add `--yolo` flag to `diff` command in `src/twsrt/bin/cli.py`: set `config.yolo = True`, resolve target path via yolo path (same logic as generate)
- [x] T025 [US4] Verify `ClaudeGenerator.diff()` and `CopilotGenerator.diff()` work correctly in yolo mode in `src/twsrt/lib/claude.py` and `src/twsrt/lib/copilot.py` — diff methods call `self.generate()` internally which already handles yolo, so the comparison should work. For Claude diff, ensure `permissions.ask` comparison is skipped when `config.yolo` (no ask key in either generated or target). Fix if needed.

**Checkpoint**: `twsrt diff --yolo` detects drift against yolo-specific config files

---

## Phase 6: Polish & Cross-Cutting Concerns

**Purpose**: Final validation and cleanup

- [x] T026 Run full test suite (`pytest`) — verify all tests pass and coverage ≥ 85%
- [x] T027 Run linter (`ruff check .`) — fix any issues
- [x] T028 Verify existing tests still pass (no regressions from yolo changes)

---

## Dependencies & Execution Order

### Phase Dependencies

- **Foundational (Phase 1)**: No dependencies — start immediately
- **US1 Claude (Phase 2)**: Depends on Phase 1 completion
- **US2 Copilot (Phase 3)**: Depends on Phase 1 completion. Can run in parallel with US1.
- **US3 All Agents (Phase 4)**: Depends on US1 + US2 completion
- **US4 Diff (Phase 5)**: Depends on Phase 1 completion. Can run in parallel with US1/US2.
- **Polish (Phase 6)**: Depends on all user stories being complete

### User Story Dependencies

```
Phase 1: Foundational
    ├──→ Phase 2: US1 (Claude)  ──┐
    ├──→ Phase 3: US2 (Copilot) ──├──→ Phase 4: US3 (All) ──→ Phase 6: Polish
    └──→ Phase 5: US4 (Diff)   ──┘
```

- **US1 (Claude)** + **US2 (Copilot)**: Independent, can run in parallel after Phase 1
- **US3 (All Agents)**: Requires US1 + US2 (both generators must support yolo)
- **US4 (Diff)**: Can start after Phase 1, but full testing needs US1+US2 generators

### Within Each User Story

- Tests MUST be written and FAIL before implementation
- Generator changes before CLI wiring
- Verify at checkpoint before proceeding

### Parallel Opportunities

- T001, T002, T003 can run in parallel (different test files/sections)
- T004, T005 can run in parallel (different functions in same file, but logically separate)
- T007, T008, T009, T010 can run in parallel (different test cases)
- T013, T014, T015, T016 can run in parallel (different test cases)
- T021, T022, T023 can run in parallel (different test files)
- US1 and US2 can run in parallel after Phase 1

---

## Parallel Example: Phase 1

```
# Launch all foundational tests together:
Task: T001 "Test yolo_path() in tests/lib/test_models.py"
Task: T002 "Test AppConfig yolo fields in tests/lib/test_models.py"
Task: T003 "Test config.toml yolo loading in tests/lib/test_config.py"

# Then launch implementations together:
Task: T004 "Implement yolo_path() in src/twsrt/lib/models.py"
Task: T005 "Add AppConfig yolo fields in src/twsrt/lib/models.py"
Task: T006 "Load yolo config keys in src/twsrt/lib/config.py"
```

## Parallel Example: US1 + US2

```
# After Phase 1, launch both stories in parallel:

# Story 1 tests:
Task: T007 "Claude yolo generate test"
Task: T008 "Claude yolo ASK filtering test"
Task: T009 "Claude yolo no-ASK test"
Task: T010 "Claude yolo CLI test"

# Story 2 tests (parallel with Story 1):
Task: T013 "Copilot yolo generate test"
Task: T014 "Copilot yolo deny-url test"
Task: T015 "Copilot yolo no-ASK test"
Task: T016 "Copilot yolo CLI test"
```

---

## Implementation Strategy

### MVP First (User Story 1 Only)

1. Complete Phase 1: Foundational (T001–T006)
2. Complete Phase 2: US1 Claude YOLO (T007–T012)
3. **STOP and VALIDATE**: `twsrt generate --yolo claude` works end-to-end
4. Demo: show `settings.yolo.json` output vs `settings.json` output

### Incremental Delivery

1. Phase 1 → Foundation ready
2. Add US1 (Claude) → Test independently → MVP!
3. Add US2 (Copilot) → Test independently → Both agents supported
4. Add US3 (All) → Integration verified → Full generate support
5. Add US4 (Diff) → Drift detection for yolo configs
6. Polish → Full test suite, coverage, linting

---

## Notes

- [P] tasks = different files, no dependencies
- [Story] label maps task to specific user story for traceability
- Each user story should be independently completable and testable
- Verify tests fail before implementing
- No `selective_merge()` for yolo files — always fresh write
- Copilot yolo: `--yolo` flag first, then `--deny-tool` + `--deny-url` only
- Claude yolo: omit `permissions.ask` key entirely (not empty list)
