# Tasks: Agent Security Config Generator

**Input**: Design documents from `/specs/001-agent-security-config/`
**Prerequisites**: plan.md, spec.md, research.md, data-model.md, contracts/cli-contract.md

**Tests**: TDD is NON-NEGOTIABLE per constitution. All test tasks precede their implementation tasks. Red-Green-Refactor cycle enforced.

**Organization**: Tasks grouped by user story. Each story is independently testable.

## Format: `[ID] [P?] [Story] Description`

- **[P]**: Can run in parallel (different files, no dependencies)
- **[Story]**: US1, US2, US3 (maps to spec.md user stories)
- Paths relative to repository root

---

## Phase 1: Setup (Project Initialization)

**Purpose**: Bootstrap project scaffold per development-standards.md Section 3

- [X] T001 Create project scaffold: VERSION (0.1.0), pyproject.toml (setuptools backend, typer dependency, [tool.uv] managed=true package=true, [dependency-groups] dev, [tool.bumpversion], [tool.pytest], [tool.ruff], [tool.coverage]), Makefile (uv run prefix, test/lint/format/ty/bump targets), .gitignore, .pre-commit-config.yaml (ruff-format, ruff, ty hooks)
- [X] T002 [P] Create package structure: src/twsrt/__init__.py (empty), src/twsrt/bin/__init__.py, src/twsrt/bin/cli.py (empty), src/twsrt/lib/__init__.py, src/twsrt/lib/models.py (empty), src/twsrt/lib/config.py (empty), src/twsrt/lib/sources.py (empty), src/twsrt/lib/agent.py (empty), src/twsrt/lib/claude.py (empty), src/twsrt/lib/copilot.py (empty), src/twsrt/lib/diff.py (empty), tests/__init__.py, tests/conftest.py (empty), tests/bin/__init__.py, tests/lib/__init__.py
- [X] T003 [P] Verify toolchain: uv sync --dev, confirm `make test` runs (empty suite passes), `make lint` runs, `make format` runs, `make ty` runs, entry point `twsrt = "twsrt.bin.cli:app"` resolves

---

## Phase 2: Foundational (Blocking Prerequisites)

**Purpose**: Core infrastructure that ALL user stories depend on

**CRITICAL**: No user story work can begin until this phase is complete

- [X] T004 Create shared test fixtures in tests/conftest.py: sample SRT JSON (denyRead, denyWrite, allowWrite, allowedDomains), sample bash-rules.json (deny + ask arrays), sample config.toml (source/target paths), sample Claude settings.json (with hooks, plugins, mcp__ allows, blanket tool allows, WebFetch domains, deny/ask entries), tmp_twsrt_dir fixture for isolated ~/.twsrt/
- [X] T005 [P] Write tests for models in tests/lib/test_models.py: SecurityRule construction, Scope/Action/Source enum values, AppConfig defaults and path expansion, DiffResult construction, SecurityRule validation (empty pattern rejected, scope-source consistency, network requires allow)
- [X] T006 [P] Write tests for config loading in tests/lib/test_config.py: load valid TOML returns AppConfig, missing TOML uses defaults, invalid TOML raises error, tilde expansion in paths
- [X] T007 [P] Write tests for source reading in tests/lib/test_sources.py: valid SRT→list[SecurityRule] (denyRead→READ/DENY, denyWrite→WRITE/DENY, allowWrite→WRITE/ALLOW, allowedDomains→NETWORK/ALLOW), valid bash-rules→list[SecurityRule] (deny→EXECUTE/DENY, ask→EXECUTE/ASK), missing file→error with path, invalid JSON→error with detail, SRT non-security fields (enabled, allowPty) ignored, tilde in paths handled
- [X] T008 Implement models (SecurityRule dataclass with validation, Scope/Action/Source enums, AppConfig dataclass with defaults, DiffResult dataclass) in src/twsrt/lib/models.py
- [X] T009 [P] Implement config loading (read TOML via tomllib, return AppConfig, fallback to defaults when missing, tilde expansion) in src/twsrt/lib/config.py
- [X] T010 [P] Implement source reading (parse SRT JSON→SecurityRules, parse bash-rules JSON→SecurityRules, validate file exists, validate JSON structure) in src/twsrt/lib/sources.py
- [X] T011 Define AgentGenerator Protocol (name property, generate method, diff method) and empty GENERATORS dict in src/twsrt/lib/agent.py
- [X] T012 Write tests for CLI init and version commands in tests/bin/test_cli.py: init creates ~/.twsrt/ dir + config.toml + bash-rules.json, init with existing files skips with warning, init --force overwrites, bare invocation shows help, -V prints version, `twsrt version` prints version
- [X] T013 Implement CLI skeleton in src/twsrt/bin/cli.py: typer app with @app.callback(invoke_without_command=True), -v/--verbose (logging), -V/--version, -c/--config (Path), hidden version command, init command (--force), __version__ string, `if __name__ == "__main__": app()`

**Checkpoint**: Foundation ready. `make test` passes. init/version commands work. Sources load. Models validate.

---

## Phase 3: User Story 1 — Generate Claude Code Permissions (Priority: P1) MVP

**Goal**: Generate Claude Code `settings.json` permissions (deny/ask/allow) and sandbox.network from SRT + bash-rules canonical sources

**Independent Test**: Run `twsrt generate claude` with sample SRT and bash-rules. Verify output matches expected Claude Code permission format with correct tool-specific patterns.

**FR coverage**: FR-001, FR-002, FR-004, FR-006, FR-007, FR-008, FR-009, FR-010, FR-011, FR-012, FR-013, FR-015, FR-016, FR-017, FR-018, FR-019

### Tests for US1

> Write tests FIRST, verify they FAIL, then implement

- [X] T014 [P] [US1] Write AgentGenerator contract tests (parametrized over GENERATORS.values()) in tests/lib/test_agent.py: each generator has name property (str), generate() accepts (list[SecurityRule], AppConfig) and returns str, diff() accepts (list[SecurityRule], Path) and returns DiffResult
- [X] T015 [P] [US1] Write Claude generation tests in tests/lib/test_claude.py: denyRead ["~/.aws"]→Read(**/.aws/**)+Write(**/.aws/**)+Edit(**/.aws/**)+MultiEdit(**/.aws/**) in deny (FR-006), denyWrite ["**/.env"]→Write(**/.env)+Edit(**/.env)+MultiEdit(**/.env) in deny (FR-007), allowWrite [".","/tmp"]→no Claude output (FR-008), allowedDomains ["github.com"]→WebFetch(domain:github.com) in allow + sandbox.network.allowedDomains (FR-009), Bash deny ["rm"]→Bash(rm:*) in deny (FR-010), Bash ask ["git push"]→Bash(git push)+Bash(git push:*) in ask (FR-011), denyRead+denyWrite overlap on same path→all applicable tools denied

### Implementation for US1

- [X] T016 [US1] Implement ClaudeGenerator.generate() in src/twsrt/lib/claude.py: map SecurityRules to Claude permission entries per data-model rule mapping table, return JSON string with permissions.deny, permissions.ask, permissions.allow (WebFetch only), sandbox.network.allowedDomains. Register ClaudeGenerator in GENERATORS dict in src/twsrt/lib/agent.py
- [X] T017 [US1] Write selective merge tests in tests/lib/test_claude.py: permissions.deny fully replaced, permissions.ask fully replaced, permissions.allow WebFetch entries replaced but blanket allows (Read, Glob, Grep, LS, Task, WebSearch) preserved and mcp__ allows preserved and project-specific allows (Bash(./gradlew:*)) preserved, sandbox.network fully replaced, hooks/plugins/additionalDirectories preserved unchanged (FR-018)
- [X] T018 [US1] Implement selective merge for Claude settings.json write mode in src/twsrt/lib/claude.py: read existing settings.json, replace deny/ask/sandbox.network sections, selectively merge allow (strip WebFetch(domain:*) entries, insert generated ones, preserve all others), write back preserving JSON formatting
- [X] T019 [US1] Write CLI generate command tests in tests/bin/test_cli.py: `twsrt generate claude` prints to stdout, `twsrt generate claude --write` writes to settings.json (via selective merge), `twsrt generate claude --dry-run --write` shows what would be written, `twsrt generate` (no agent) generates for all, missing source file exits 1 with error message, `twsrt generate claude` with -c custom config path
- [X] T020 [US1] Implement generate command in src/twsrt/bin/cli.py: AGENT argument (default "all"), --write/-w flag, --dry-run/-n flag, resolve agent from GENERATORS registry, call generate(), print to stdout or write via agent-specific write logic, exit codes per cli-contract.md
- [X] T021 [US1] Write and run acceptance scenario integration tests in tests/bin/test_cli.py: all 7 acceptance scenarios from spec.md US1 as individual test cases, using typer.testing.CliRunner with tmp fixture files

**Checkpoint**: `twsrt generate claude` produces correct permissions. `twsrt generate claude --write` performs selective merge. All 7 US1 acceptance scenarios pass.

---

## Phase 4: User Story 2 — Generate Copilot CLI Flags (Priority: P2)

**Goal**: Generate `--allow-tool` and `--deny-tool` flag snippet for Copilot CLI wrapper function

**Independent Test**: Run `twsrt generate copilot` with sample SRT and bash-rules. Verify output produces valid Copilot CLI flags with one flag per line.

**FR coverage**: FR-005, FR-008, FR-010, FR-011, FR-012

### Tests for US2

- [X] T022 [P] [US2] Write Copilot flag generation tests in tests/lib/test_copilot.py: Bash deny ["rm","sudo"]→`--deny-tool 'shell(rm)'` + `--deny-tool 'shell(sudo)'`, allowWrite [".","/tmp"]→`--allow-tool 'shell(*)'` + `--allow-tool 'read'` + `--allow-tool 'edit'` + `--allow-tool 'write'` (FR-008), output is one flag per line, no wrapper function or srt -c in output (FR-005)

### Implementation for US2

- [X] T023 [US2] Implement CopilotGenerator.generate() in src/twsrt/lib/copilot.py: map SecurityRules to Copilot flags per data-model rule mapping table, return text with one flag per line. Register CopilotGenerator in GENERATORS dict in src/twsrt/lib/agent.py
- [X] T024 [US2] Write lossy mapping tests in tests/lib/test_copilot.py: Bash ask ["git push","pip install"]→`--deny-tool 'shell(git push)'` + `--deny-tool 'shell(pip install)'` with warning emitted to stderr containing "no ask equivalent" (FR-012)
- [X] T025 [US2] Implement lossy mapping warnings in CopilotGenerator: ask rules mapped to deny-tool with warning to stderr per FR-012 in src/twsrt/lib/copilot.py
- [X] T026 [US2] Write and run acceptance scenario integration tests in tests/bin/test_cli.py: all 3 acceptance scenarios from spec.md US2, verify `twsrt generate copilot` output format, verify `twsrt generate` (all) includes both Claude and Copilot output

**Checkpoint**: `twsrt generate copilot` produces correct flags. Lossy warnings emitted. `twsrt generate` produces both agents. All 3 US2 acceptance scenarios pass.

---

## Phase 5: User Story 3 — Detect Configuration Drift (Priority: P3)

**Goal**: Compare generated configs against existing agent config files and report drift

**Independent Test**: Place a known-drifted Claude settings.json next to canonical sources. Run `twsrt diff claude`. Verify it reports specific missing/extra rules.

**FR coverage**: FR-014

### Tests for US3

- [X] T027 [P] [US3] Write Claude drift detection tests in tests/lib/test_diff.py: existing settings.json missing a denyRead-derived deny rule→DiffResult with missing entry, existing settings.json matching generated→DiffResult matched=True, existing settings.json with extra Bash deny not in sources→DiffResult with extra entry
- [X] T028 [P] [US3] Write Copilot drift detection tests in tests/lib/test_diff.py: existing flags file with extra --deny-tool not in bash-rules→DiffResult with extra entry, matching flags→DiffResult matched=True

### Implementation for US3

- [X] T029 [US3] Implement ClaudeGenerator.diff() in src/twsrt/lib/claude.py: generate expected entries, parse existing settings.json sections, compare deny/ask/allow/sandbox.network entries, return DiffResult with missing and extra lists
- [X] T030 [US3] Implement CopilotGenerator.diff() in src/twsrt/lib/copilot.py: generate expected flags, parse existing flags text, compare line by line, return DiffResult
- [X] T031 [US3] Write CLI diff command tests in tests/bin/test_cli.py: `twsrt diff claude` with drift exits 1 with formatted output (+ for missing, - for extra), `twsrt diff` with no drift exits 0, `twsrt diff copilot` with missing target file exits 2 with error
- [X] T032 [US3] Implement diff command in src/twsrt/bin/cli.py: AGENT argument (default "all"), resolve agent from GENERATORS, call diff(), format output per cli-contract.md, exit codes (0=no drift, 1=drift, 2=missing file)
- [X] T033 [US3] Write and run acceptance scenario integration tests in tests/bin/test_cli.py: all 3 acceptance scenarios from spec.md US3

**Checkpoint**: `twsrt diff` detects drift correctly. Exit codes match contract. All 3 US3 acceptance scenarios pass.

---

## Phase 6: Polish & Cross-Cutting Concerns

**Purpose**: Documentation, quality gates, final validation

- [X] T034 Update README.md with installation (uv/pip), usage (generate/diff/init commands), configuration (config.toml, bash-rules.json), canonical source model diagram
- [X] T035 [P] Validate quickstart.md flow end-to-end: follow every step in specs/001-agent-security-config/quickstart.md against real tool
- [X] T036 [P] Verify ty type check passes: `make ty` exits 0 on all src/twsrt/ modules
- [X] T037 Verify test coverage ≥85%: `make test` with --cov-report, check pyproject.toml fail_under=85 enforced

---

## Dependencies & Execution Order

### Phase Dependencies

```
Phase 1: Setup ──────────> Phase 2: Foundational ──┬──> Phase 3: US1 (P1) MVP
                                                    │        │
                                                    ├──> Phase 4: US2 (P2) ──┐
                                                    │                         │
                                                    └──> Phase 5: US3 (P3) ──┴──> Phase 6: Polish
```

- **Setup (Phase 1)**: No dependencies — start immediately
- **Foundational (Phase 2)**: Depends on Setup — BLOCKS all user stories
- **US1 (Phase 3)**: Depends on Foundational — can start immediately after
- **US2 (Phase 4)**: Depends on Foundational — can run in parallel with US1 but generate command created in US1
- **US3 (Phase 5)**: Depends on US1+US2 (needs both generators implemented for full diff testing)
- **Polish (Phase 6)**: Depends on all user stories

### User Story Dependencies

| Story | Depends On | Can Parallel With | Notes |
|-------|-----------|-------------------|-------|
| US1 (Claude) | Phase 2 only | — | Creates generate command, first generator |
| US2 (Copilot) | Phase 2 + US1 T020 | US1 T017-T021 | Needs generate command from US1 |
| US3 (Drift) | US1 + US2 | — | Needs both generators to test diff |

### Within Each User Story (TDD order)

1. Write tests → verify they FAIL (import errors, missing implementations)
2. Implement module → verify tests PASS
3. Write integration tests → verify they FAIL
4. Wire CLI command → verify integration tests PASS
5. Run acceptance scenarios → all pass

### Parallel Opportunities

**Phase 2** (after T004 conftest):
```
T005 (test_models) ─┐
T006 (test_config) ─┼─ parallel ─> T008 (models) ─> T009 (config) ─┐
T007 (test_sources) ┘                               T010 (sources) ─┤─> T011-T013
                                                                     ┘
```

**Phase 3** (US1):
```
T014 (test_agent) ──┐
T015 (test_claude) ─┴─ parallel ─> T016 (claude impl) ─> T017-T021
```

**Phase 5** (US3):
```
T027 (test Claude diff) ─┐
T028 (test Copilot diff) ┴─ parallel ─> T029-T033
```

---

## Implementation Strategy

### MVP First (User Story 1 Only)

1. Complete Phase 1: Setup → project builds
2. Complete Phase 2: Foundational → sources load, models validate, init works
3. Complete Phase 3: US1 → `twsrt generate claude` works end-to-end
4. **STOP and VALIDATE**: Run all 7 US1 acceptance scenarios
5. Tom can start using twsrt for Claude Code config generation

### Incremental Delivery

1. Setup + Foundational → Foundation ready
2. US1 → `twsrt generate claude [--write]` → MVP usable
3. US2 → `twsrt generate copilot` + `twsrt generate` (all) → Full generation
4. US3 → `twsrt diff` → Migration validation
5. Polish → README, coverage, type checks → Release ready

### Suggested MVP Scope

**US1 alone is a usable MVP.** Claude Code is the primary agent with the most complex config. Once `twsrt generate claude --write` works, Tom can stop hand-maintaining settings.json. US2 and US3 add value but are not blocking daily use.

---

## Summary

| Phase | Tasks | Scope |
|-------|-------|-------|
| Phase 1: Setup | T001–T003 (3) | Project scaffold |
| Phase 2: Foundational | T004–T013 (10) | Models, config, sources, CLI skeleton |
| Phase 3: US1 Claude | T014–T021 (8) | Claude generation + selective merge + CLI |
| Phase 4: US2 Copilot | T022–T026 (5) | Copilot flags + lossy warnings |
| Phase 5: US3 Drift | T027–T033 (7) | Drift detection + CLI diff command |
| Phase 6: Polish | T034–T037 (4) | README, quickstart, ty, coverage |
| **Total** | **37 tasks** | |

## Notes

- [P] tasks = different files, no dependencies on incomplete tasks
- [Story] label maps task to specific user story for traceability
- Each user story is independently completable and testable
- TDD: verify tests FAIL before implementing, verify they PASS after
- Commit after each task or logical group
- Stop at any checkpoint to validate story independently
