# Tasks: Network Domain Flags for Copilot and Claude

**Input**: Design documents from `/specs/003-copilot-allow-url/`
**Prerequisites**: plan.md (required), spec.md (required), data-model.md, contracts/, research.md

**Tests**: Included — TDD is mandatory per constitution (Test-First, NON-NEGOTIABLE).

**Organization**: Tasks grouped by user story. Each story independently testable.

## Format: `[ID] [P?] [Story] Description`

- **[P]**: Can run in parallel (different files, no dependencies)
- **[Story]**: Which user story (US1, US2, US3)
- Exact file paths included

## Phase 1: Setup (Shared Infrastructure)

**Purpose**: Update shared test fixtures that multiple stories depend on

- [x] T001 Add `deniedDomains` to SAMPLE_SRT and denied domain `WebFetch(domain:...)` entries to SAMPLE_CLAUDE_SETTINGS in tests/conftest.py: add `"deniedDomains": ["evil.com", "*.tracker.net"]` to the `network` section of SAMPLE_SRT (flat format already used), add `"WebFetch(domain:evil.com)"` to `permissions.deny` list in SAMPLE_CLAUDE_SETTINGS

---

## Phase 2: Foundational (Blocking Prerequisites)

**Purpose**: Model and parser changes that MUST complete before user story generator work

**CRITICAL**: US2 depends on these changes. US1 can start in parallel with this phase.

### Tests for Foundational

> **Write these tests FIRST, ensure they FAIL before implementation**

- [x] T002 Write test for NETWORK/DENY validation in tests/lib/test_models.py: add `test_network_deny_is_valid` (construct `SecurityRule(NETWORK, DENY, "evil.com", SRT_NETWORK)` — should succeed after fix, fails now), add `test_network_ask_still_rejected` (NETWORK+ASK should still raise ValueError). Update existing `test_network_requires_allow` to `test_network_requires_allow_or_deny` with updated error message match
- [x] T003 [P] Write tests for `deniedDomains` parsing in tests/lib/test_sources.py: add `test_denied_domains` (parse SAMPLE_SRT, filter `NETWORK/DENY` rules, assert 2 rules with patterns `evil.com` and `*.tracker.net`), add `test_flat_srt_denied_domains` (flat format with `deniedDomains` key produces NETWORK/DENY rules), add `test_empty_denied_domains` (empty list produces no NETWORK/DENY rules)

### Implementation for Foundational

- [x] T004 Relax NETWORK validation in src/twsrt/lib/models.py: change `if self.scope == Scope.NETWORK and self.action != Action.ALLOW` to `if self.scope == Scope.NETWORK and self.action not in (Action.ALLOW, Action.DENY)`, update error message to "NETWORK scope requires ALLOW or DENY action". Verify T002 tests pass.
- [x] T005 Parse `deniedDomains`/`deniedHosts` in src/twsrt/lib/sources.py: in flat format branch add `denied_domains = network.get("deniedDomains", [])`, in nested format branch add `denied_domains = network.get("deniedHosts", [])`, add loop creating `SecurityRule(NETWORK, DENY, domain, SRT_NETWORK)` for each denied domain (mirror existing allowed_domains loop). Verify T003 tests pass.

**Checkpoint**: Model accepts NETWORK/DENY, parser produces NETWORK/DENY rules from SRT config.

---

## Phase 3: User Story 1 — Copilot Allow-URL (Priority: P1) MVP

**Goal**: `twsrt generate copilot` emits `--allow-url '<domain>'` for each whitelisted domain from SRT config.

**Independent Test**: Run `twsrt generate copilot` with SRT containing `allowedDomains` and verify output includes `--allow-url` flags.

### Tests for User Story 1

> **Write these tests FIRST, ensure they FAIL before implementation**

- [x] T006 [US1] Write tests for `--allow-url` generation in tests/lib/test_copilot.py: add `test_network_allow_generates_allow_url` (create NETWORK/ALLOW rules for `github.com` and `*.npmjs.org`, assert output contains `--allow-url 'github.com'` and `--allow-url '*.npmjs.org'`), add `test_allow_url_one_per_line` (each `--allow-url` on its own line). Update existing `test_network_no_copilot_output` — rename to `test_network_allow_generates_allow_url_not_empty` or remove if redundant with new test

### Implementation for User Story 1

- [x] T007 [US1] Implement `--allow-url` generation in src/twsrt/lib/copilot.py: add `elif rule.scope == Scope.NETWORK and rule.action == Action.ALLOW:` branch that appends `f"--allow-url '{rule.pattern}'"` to flags list. Remove or update the comment on line 47 ("NETWORK/ALLOW: SRT handles at OS level"). Verify T006 tests pass.

**Checkpoint**: `twsrt generate copilot` outputs `--allow-url` flags for allowed domains. US1 is complete and independently testable.

---

## Phase 4: User Story 2 — Denied Domain Flags for Both Agents (Priority: P1)

**Goal**: Both generators emit deny flags for each blocked domain from SRT `deniedDomains`.

**Independent Test**: Run `twsrt generate copilot` and `twsrt generate claude` with SRT containing `deniedDomains` and verify deny flags appear.

### Tests for User Story 2

> **Write these tests FIRST, ensure they FAIL before implementation**

- [x] T008 [P] [US2] Write tests for `--deny-url` generation in tests/lib/test_copilot.py: add `test_network_deny_generates_deny_url` (create NETWORK/DENY rules for `evil.com` and `*.tracker.net`, assert output contains `--deny-url 'evil.com'` and `--deny-url '*.tracker.net'`), add `test_deny_url_one_per_line` (each `--deny-url` on its own line)
- [x] T009 [P] [US2] Write tests for Claude denied domain deny entries in tests/lib/test_claude.py: add `test_denied_domains_generate_webfetch_deny` (create NETWORK/DENY rule for `evil.com`, assert `"WebFetch(domain:evil.com)"` appears in `permissions.deny` list of JSON output), add `test_denied_domains_not_in_allow` (NETWORK/DENY entries must NOT appear in `permissions.allow`), add `test_denied_domains_not_in_sandbox_network` (NETWORK/DENY entries must NOT add to `sandbox.network.allowedDomains`)

### Implementation for User Story 2

- [x] T010 [US2] Implement `--deny-url` generation in src/twsrt/lib/copilot.py: add `elif rule.scope == Scope.NETWORK and rule.action == Action.DENY:` branch that appends `f"--deny-url '{rule.pattern}'"` to flags list. Verify T008 tests pass.
- [x] T011 [US2] Implement Claude denied domain deny entries in src/twsrt/lib/claude.py: add `elif rule.scope == Scope.NETWORK and rule.action == Action.DENY:` branch that appends `f"WebFetch(domain:{rule.pattern})"` to `deny` list. Verify T009 tests pass.

**Checkpoint**: Both generators handle denied domains. US2 is complete and independently testable.

---

## Phase 5: User Story 3 — Drift Detection for Network Domain Flags (Priority: P2)

**Goal**: `twsrt diff` detects missing/extra domain entries for both agents.

**Independent Test**: Create target files with missing/extra domain entries and verify `twsrt diff` reports discrepancies.

### Tests for User Story 3

> **Write these tests FIRST, ensure they FAIL before implementation**

- [x] T012 [P] [US3] Write drift detection tests for Copilot in tests/lib/test_copilot.py: add `test_diff_detects_missing_allow_url` (generate with allowed domains, target file missing one `--allow-url` line, assert `missing` list contains it), add `test_diff_detects_extra_allow_url` (target file has extra `--allow-url` line not in SRT, assert `extra` list contains it), add `test_diff_detects_missing_deny_url` (same pattern for `--deny-url`). These tests should pass immediately since line-based diff already covers new flags — this phase verifies correctness.
- [x] T013 [P] [US3] Write drift detection tests for Claude denied domains in tests/lib/test_claude.py: add `test_diff_detects_missing_denied_domain_deny_entry` (generate with denied domains, existing settings missing `WebFetch(domain:evil.com)` in deny list, assert it appears in `missing`), add `test_diff_detects_extra_denied_domain_deny_entry` (existing settings has `WebFetch(domain:stale.com)` in deny not in SRT, assert it appears in `extra`)

### Implementation for User Story 3

- [x] T014 [US3] Verify Copilot diff handles domain flags correctly — the existing line-based `CopilotGenerator.diff()` in src/twsrt/lib/copilot.py should already cover `--allow-url` and `--deny-url` lines with no code changes needed. If T012 tests pass, mark as verified. If not, debug and fix.
- [x] T015 [US3] Review Claude diff in src/twsrt/lib/claude.py: the existing diff compares `permissions.deny` sets directly (lines 86-97), so new `WebFetch(domain:...)` deny entries should already be detected. If T013 tests pass, mark as verified. If not, add denied domain handling to the diff method.

**Checkpoint**: Drift detection covers all domain flags for both agents. US3 is complete.

---

## Phase 6: Polish & Cross-Cutting Concerns

**Purpose**: Final validation and cleanup

- [x] T016 Run full test suite (`cd src && pytest`) and verify all tests pass including existing tests (regression check per SC-005)
- [x] T017 Run ruff linter (`cd src && ruff check .`) and fix any issues
- [x] T018 Verify end-to-end: run `twsrt generate copilot` and `twsrt generate claude` against real `~/.srt-settings.json` and confirm domain flags appear in output

---

## Dependencies & Execution Order

### Phase Dependencies

- **Setup (Phase 1)**: No dependencies — start immediately
- **Foundational (Phase 2)**: Depends on Phase 1 (conftest.py fixtures) — BLOCKS US2
- **US1 (Phase 3)**: Depends on Phase 1 only — can run IN PARALLEL with Phase 2
- **US2 (Phase 4)**: Depends on Phase 2 (model + parser changes)
- **US3 (Phase 5)**: Depends on US1 + US2 (needs generated flags to exist for diff)
- **Polish (Phase 6)**: Depends on all user stories complete

### User Story Dependencies

- **US1 (P1)**: Independent — only needs existing NETWORK/ALLOW rules (already parsed)
- **US2 (P1)**: Depends on foundational model + parser changes
- **US3 (P2)**: Depends on US1 + US2 (verifies their output in diff context)

### Within Each Story

- Tests MUST be written and FAIL before implementation (TDD)
- Verify tests pass after implementation
- Story complete before moving to next

### Parallel Opportunities

- T002 and T003 can run in parallel (different test files)
- T006 (US1 tests) can start as soon as Phase 1 completes, in parallel with Phase 2
- T008 and T009 can run in parallel (copilot vs claude test files)
- T012 and T013 can run in parallel (copilot vs claude diff test files)

---

## Parallel Example: US2

```
# Launch tests for both generators in parallel:
T008: "Write --deny-url tests in tests/lib/test_copilot.py"     [P]
T009: "Write Claude deny entry tests in tests/lib/test_claude.py" [P]

# Then implement sequentially (both touch their own file):
T010: "Implement --deny-url in src/twsrt/lib/copilot.py"
T011: "Implement Claude deny entries in src/twsrt/lib/claude.py"
```

---

## Implementation Strategy

### MVP First (US1 Only)

1. Complete Phase 1: Setup (T001)
2. Complete Phase 3: US1 — tests + implementation (T006-T007)
3. **STOP and VALIDATE**: `twsrt generate copilot` shows `--allow-url` flags
4. This alone delivers the original feature request

### Full Delivery

1. Phase 1: Setup → Phase 2: Foundational (in parallel with US1)
2. Phase 3: US1 → test independently
3. Phase 4: US2 → test independently
4. Phase 5: US3 → test independently
5. Phase 6: Polish → full regression + end-to-end

---

## Notes

- [P] tasks = different files, no dependencies
- [Story] label maps to spec.md user stories (US1=allow-url copilot, US2=denied domains both, US3=drift detection)
- US1 can be delivered as MVP without any foundational changes
- US2 foundational changes (model + parser) do not break existing behavior — they only add support for NETWORK/DENY
- Copilot diff (US3/T014) likely needs zero code changes — line-based comparison already covers new flags
- Claude diff (US3/T015) likely needs zero code changes — deny section comparison already exists
