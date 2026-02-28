# Tasks: Extend Claude Network Settings Generation

**Input**: Design documents from `/specs/004-claude-network-keys/`
**Prerequisites**: plan.md, spec.md, research.md, data-model.md

**Tests**: Included (TDD is mandatory per constitution — Red-Green-Refactor enforced).

**Organization**: Tasks grouped by user story. US4 (nested removal) is foundational — blocks all other stories.

## Format: `[ID] [P?] [Story] Description`

- **[P]**: Can run in parallel (different files, no dependencies)
- **[Story]**: Which user story this task belongs to (e.g., US1, US3, US4)
- Include exact file paths in descriptions

---

## Phase 1: Foundational — Remove Nested SRT Format (US4)

**Purpose**: Remove legacy dead code (nested SRT format branch) and convert all test fixtures to the only real SRT format (flat). This MUST complete before any new feature work.

**⚠️ CRITICAL**: No feature work can begin until this phase is complete

- [x] T001 [US4] Convert SAMPLE_SRT from nested to flat format and fix SAMPLE_CLAUDE_SETTINGS (allowedHosts → allowedDomains) in tests/conftest.py
- [x] T002 [P] [US4] Convert inline nested format test data to flat format in tests/lib/test_sources.py (test_non_security_fields_ignored, test_tilde_in_paths_handled, test_denied_domains)
- [x] T003 [P] [US4] Convert inline nested format SRT data to flat format in tests/bin/test_cli.py (all scenario tests that use nested sandbox.permissions structure)
- [x] T004 [US4] Remove nested format branch (else clause at lines 32-40) and format dispatch conditional from read_srt() in src/twsrt/lib/sources.py — parser now only handles flat format
- [x] T005 [US4] Run full test suite — all existing tests must pass with flat-only parser

**Checkpoint**: Nested format eliminated. Parser only handles flat SRT. All tests green.

---

## Phase 2: US1 + US2 — Pass-through Network Configuration Keys (P1) 🎯 MVP

**Goal**: Read 5 network keys from `.srt-settings.json` and include them in generated Claude Code `settings.json` under `sandbox.network`. Omit keys not present in source.

**Independent Test**: Create an `.srt-settings.json` with all 5 new keys and verify the generated output contains them. Create one with only `allowedDomains` and verify the 5 keys are absent.

### Data Model

- [x] T006 [US1] Add SrtResult dataclass (rules + network_config) and add network_config: dict field to AppConfig in src/twsrt/lib/models.py

### Tests (RED — must fail before implementation)

- [x] T007 [P] [US1] Write tests for read_srt() returning SrtResult with network_config: all 5 keys present, partial keys, no network config keys, empty list for allowUnixSockets, falsy value 0 for ports in tests/lib/test_sources.py
- [x] T008 [P] [US1] Write tests for generate() including network_config keys in sandbox.network output and omitting absent keys (covers US2 acceptance scenarios) in tests/lib/test_claude.py
- [x] T009 [P] [US1] Write test for selective_merge() using dict.update() instead of full replacement — must preserve existing allowManagedDomainsOnly key in tests/lib/test_claude.py

### Implementation (GREEN)

- [x] T010 [US1] Implement network_config extraction in read_srt(): read allowUnixSockets, allowAllUnixSockets, allowLocalBinding, httpProxyPort, socksProxyPort from network dict, return SrtResult in src/twsrt/lib/sources.py
- [x] T011 [US1] Implement network_config pass-through in generate(): merge config.network_config into sandbox.network output dict alongside allowedDomains in src/twsrt/lib/claude.py
- [x] T012 [US1] Change selective_merge() from full dict replacement to dict.update() for sandbox.network in src/twsrt/lib/claude.py
- [x] T013 [US1] Wire SrtResult through CLI generate and diff commands: unpack SrtResult, set config.network_config, pass config through pipeline in src/twsrt/bin/cli.py
- [x] T014 [US1] Run tests — all T007-T009 tests must pass (GREEN). Existing tests must still pass.

**Checkpoint**: Pass-through keys flowing end-to-end. Absent keys omitted. Merge preserves unmanaged keys. MVP complete.

---

## Phase 3: US3 — Drift Detection for New Keys (P2)

**Goal**: The diff command detects mismatches between generated and existing settings for all 5 new network keys.

**Independent Test**: Generate settings with `allowLocalBinding: true`, compare against existing settings.json with `allowLocalBinding: false`, verify drift is reported.

### Tests (RED — must fail before implementation)

- [x] T015 [US3] Write tests for ClaudeGenerator.diff() comparing network config keys: missing key in existing, extra key in existing, matching keys, and mixed scenarios in tests/lib/test_diff.py

### Implementation (GREEN)

- [x] T016 [US3] Update AgentGenerator Protocol: add config: AppConfig parameter to diff() method in src/twsrt/lib/agent.py
- [x] T017 [P] [US3] Update CopilotGenerator.diff() to accept and use config: AppConfig parameter (remove internal AppConfig() creation) in src/twsrt/lib/copilot.py
- [x] T018 [US3] Implement network config key comparison in ClaudeGenerator.diff(): compare each key in config.network_config against existing sandbox.network, report missing/extra with network.config: prefix in src/twsrt/lib/claude.py
- [x] T019 [US3] Wire config through CLI diff command: pass config to gen.diff() instead of just (rules, target) in src/twsrt/bin/cli.py
- [x] T020 [US3] Run tests — all T015 tests must pass (GREEN). All previous tests must still pass.

**Checkpoint**: Drift detection covers all network keys. Full pipeline tested.

---

## Phase 4: Polish & Cross-Cutting Concerns

**Purpose**: Example updates, linting, final validation

- [x] T021 [P] Update example/.srt-settings.json to include all new network keys: allowUnixSockets, allowAllUnixSockets, httpProxyPort, socksProxyPort (allowLocalBinding already present)
- [x] T022 [P] Run ruff check on src/ and fix any issues
- [x] T023 Run full test suite — all tests must pass, zero regressions

---

## Dependencies & Execution Order

### Phase Dependencies

- **Foundational (Phase 1)**: No dependencies — start immediately. BLOCKS all feature work.
- **US1+US2 (Phase 2)**: Depends on Phase 1 completion (fixtures converted, nested branch removed)
- **US3 (Phase 3)**: Depends on Phase 2 (diff needs generate() changes to produce correct output)
- **Polish (Phase 4)**: Depends on all previous phases

### User Story Dependencies

- **US4 (Remove nested)**: Foundational — must complete first
- **US1+US2 (Pass-through keys)**: Depends on US4 — core feature, MVP
- **US3 (Drift detection)**: Depends on US1 — extends diff() to compare new keys

### Within Each Phase (TDD order)

1. Data model changes (if any) — structural additions that enable test imports
2. Tests MUST be written and FAIL before implementation (RED)
3. Implementation to make tests pass (GREEN)
4. Verify all tests pass (checkpoint)

### Parallel Opportunities

Within Phase 1:
- T002, T003 can run in parallel (different test files)

Within Phase 2:
- T007, T008, T009 can run in parallel (different test files)

Within Phase 3:
- T017 can run in parallel with other implementation tasks (different file)

Within Phase 4:
- T021, T022 can run in parallel

---

## Parallel Example: Phase 2 (US1 Tests)

```bash
# Launch all RED tests in parallel (different files):
Task T007: "Write read_srt() network_config tests in tests/lib/test_sources.py"
Task T008: "Write generate() pass-through key tests in tests/lib/test_claude.py"
Task T009: "Write selective_merge() preservation test in tests/lib/test_claude.py"
```

Note: T008 and T009 are in the same file but test different functions — they can be written together.

---

## Implementation Strategy

### MVP First (US4 → US1+US2)

1. Complete Phase 1: Remove nested format (US4)
2. Complete Phase 2: Pass-through keys (US1+US2)
3. **STOP and VALIDATE**: Generate settings from example SRT, verify all 5 keys appear
4. This is a deployable increment — all existing behavior preserved, new keys flowing

### Full Delivery

1. MVP (above)
2. Add Phase 3: Drift detection (US3) — extends value of the tool
3. Polish (Phase 4) — example updates, linting

---

## Notes

- [P] tasks = different files, no dependencies
- [Story] label maps task to specific user story for traceability
- TDD enforced: tests written and verified FAILING before implementation
- All 5 pass-through keys use identical handling — no special cases per key
- `allowedDomains` handling unchanged (still flows through SecurityRule pipeline)
- `deniedDomains` handling unchanged (still generates WebFetch deny entries)
- `deniedDomains` and `mitmProxy` are NOT generated into sandbox.network (FR-004)
- `allowManagedDomainsOnly` is NOT touched (FR-005) — preserved by key-by-key merge
