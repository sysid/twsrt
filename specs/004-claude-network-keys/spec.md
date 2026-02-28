# Feature Specification: Extend Claude Network Settings Generation

**Feature Branch**: `004-claude-network-keys`
**Created**: 2026-02-28
**Status**: Draft
**Input**: User description: "Extend the Claude Code settings generation to include all network keys from .srt-settings.json that exist in the Claude Code settings.json schema (allowUnixSockets, allowAllUnixSockets, allowLocalBinding, httpProxyPort, socksProxyPort). Exclude keys not present in the target schema (deniedDomains, mitmProxy). Do not touch allowManagedDomainsOnly since it has no SRT source."

## Clarifications

### Session 2026-02-28

- Q: What should happen with Story 4 (nested SRT format) and the nested format code branch in sources.py? → A: Remove Story 4. Remove the nested format code branch entirely from the codebase. There is only one SRT format (the flat format). The "nested" branch (`sandbox.permissions.network.*`) is legacy dead code.
- Q: Which keys exist in SRT `.srt-settings.json`? → A: Tom's comparison table is the authority, not the SRT README. SRT has: allowedDomains, deniedDomains, allowUnixSockets, allowAllUnixSockets, allowLocalBinding, httpProxyPort, socksProxyPort, mitmProxy.

## User Scenarios & Testing *(mandatory)*

### User Story 1 - Pass-through Network Configuration Keys (Priority: P1)

As a security administrator, I configure network settings in `.srt-settings.json` (the canonical source) and expect all applicable settings to propagate into the generated Claude Code `settings.json`. Currently only `allowedDomains` and `deniedDomains` are propagated. The remaining network keys (`allowUnixSockets`, `allowAllUnixSockets`, `allowLocalBinding`, `httpProxyPort`, `socksProxyPort`) are silently ignored, forcing manual configuration of Claude Code settings.

**Why this priority**: This is the core value of the feature — ensuring the canonical SRT source drives all supported network settings in Claude Code, eliminating configuration drift.

**Independent Test**: Can be tested by creating an `.srt-settings.json` with all five new network keys populated and verifying the generated `settings.json` contains them under `sandbox.network`.

**Acceptance Scenarios**:

1. **Given** an `.srt-settings.json` with `network.allowUnixSockets` containing a list of socket paths, **When** the Claude generator runs, **Then** the output `sandbox.network.allowUnixSockets` contains the same list of socket paths.
2. **Given** an `.srt-settings.json` with `network.allowAllUnixSockets` set to `true`, **When** the Claude generator runs, **Then** the output `sandbox.network.allowAllUnixSockets` is `true`.
3. **Given** an `.srt-settings.json` with `network.allowLocalBinding` set to `true`, **When** the Claude generator runs, **Then** the output `sandbox.network.allowLocalBinding` is `true`.
4. **Given** an `.srt-settings.json` with `network.httpProxyPort` set to a port number, **When** the Claude generator runs, **Then** the output `sandbox.network.httpProxyPort` contains the same port number.
5. **Given** an `.srt-settings.json` with `network.socksProxyPort` set to a port number, **When** the Claude generator runs, **Then** the output `sandbox.network.socksProxyPort` contains the same port number.

---

### User Story 2 - Omit Absent Keys from Output (Priority: P2)

As a user, I only define the network keys I need in my `.srt-settings.json`. Keys I do not specify should not appear in the generated Claude Code settings — they should remain absent rather than being set to defaults, so Claude Code falls back to its own built-in defaults.

**Why this priority**: Prevents the generator from injecting unwanted configuration that could override Claude Code defaults or conflict with other configuration layers.

**Independent Test**: Can be tested by generating settings from an `.srt-settings.json` that only has `allowedDomains` and verifying the five new keys are absent from `sandbox.network` in the output.

**Acceptance Scenarios**:

1. **Given** an `.srt-settings.json` with only `network.allowedDomains` defined, **When** the Claude generator runs, **Then** the output `sandbox.network` contains only `allowedDomains` — no `allowUnixSockets`, `allowAllUnixSockets`, `allowLocalBinding`, `httpProxyPort`, or `socksProxyPort`.
2. **Given** an `.srt-settings.json` with `network.allowLocalBinding` defined but `network.httpProxyPort` absent, **When** the Claude generator runs, **Then** `sandbox.network.allowLocalBinding` is present and `sandbox.network.httpProxyPort` is absent.

---

### User Story 3 - Drift Detection for New Keys (Priority: P2)

As a user running the `diff` command, I want drift detection to cover all network keys, not just `allowedDomains`. If a key in the generated settings differs from the existing Claude Code settings, it should be reported.

**Why this priority**: Drift detection is essential for users who need to verify that their Claude Code settings match the canonical SRT source, especially for security-sensitive network configuration.

**Independent Test**: Can be tested by generating settings with `allowLocalBinding: true`, then comparing against an existing settings.json where `allowLocalBinding` is `false` or absent, and verifying the diff reports the discrepancy.

**Acceptance Scenarios**:

1. **Given** a generated settings with `sandbox.network.allowLocalBinding: true` and an existing settings.json with `sandbox.network.allowLocalBinding: false`, **When** the diff command runs, **Then** the discrepancy is reported.
2. **Given** a generated settings with `sandbox.network.httpProxyPort: 8080` and an existing settings.json without `httpProxyPort`, **When** the diff command runs, **Then** the missing key is reported.
3. **Given** generated settings and existing settings.json with identical network keys and values, **When** the diff command runs, **Then** no network drift is reported.

---

### User Story 4 - Remove Legacy Nested SRT Format (Priority: P2)

The parser in `sources.py` contains a legacy code branch that reads from a non-existent "nested" SRT format (`sandbox.permissions.network.*` with `allowedHosts`/`deniedHosts`). There is only one SRT format — the flat format with top-level `network`, `filesystem`, etc. The nested branch is dead code that should be removed to reduce confusion and maintenance burden.

**Why this priority**: Dead code creates false assumptions (as demonstrated by the initial spec draft). Removing it simplifies the parser and eliminates a misleading abstraction.

**Independent Test**: Can be tested by verifying that only the flat SRT format is parsed, and that all existing tests pass after removing the nested branch and its associated test cases.

**Acceptance Scenarios**:

1. **Given** an `.srt-settings.json` in the standard flat format, **When** the parser runs, **Then** all network and filesystem keys are correctly read.
2. **Given** the codebase after cleanup, **When** searching for `sandbox.permissions.network` or `allowedHosts`/`deniedHosts`, **Then** no references exist in production code.

---

### Edge Cases

- What happens when `allowUnixSockets` is an empty list? The key should still be included in the output as an empty list `[]`.
- What happens when boolean keys (`allowAllUnixSockets`, `allowLocalBinding`) have non-boolean values? The system should pass them through as-is; type validation is the responsibility of the SRT source and Claude Code consumer.
- What happens when proxy port keys have value `0`? The value `0` is valid and should be passed through (it is a falsy but meaningful value).
- What happens when the existing `settings.json` has `allowManagedDomainsOnly` set? The selective merge must preserve it since it is not managed by the SRT source.

## Requirements *(mandatory)*

### Functional Requirements

- **FR-001**: System MUST read the following keys from `.srt-settings.json` network section: `allowUnixSockets`, `allowAllUnixSockets`, `allowLocalBinding`, `httpProxyPort`, `socksProxyPort`.
- **FR-002**: System MUST write each present key into the generated Claude Code `settings.json` under `sandbox.network` using the same key name.
- **FR-003**: System MUST omit keys from the output when they are not present in the SRT source.
- **FR-004**: System MUST NOT generate `deniedDomains` or `mitmProxy` into `sandbox.network` (these keys do not exist in the Claude Code settings schema).
- **FR-005**: System MUST NOT modify or generate `allowManagedDomainsOnly` (this key has no SRT source).
- **FR-006**: System MUST only support the flat SRT format (`network.*`). The legacy nested format (`sandbox.permissions.network.*`) MUST be removed from the parser.
- **FR-007**: Drift detection MUST report differences for all five new keys between generated and existing settings.
- **FR-008**: The selective merge MUST preserve keys in `sandbox.network` that are not managed by the generator (specifically `allowManagedDomainsOnly`).
- **FR-009**: All code, tests, and references to the nested SRT format (`sandbox.permissions.network`, `allowedHosts`, `deniedHosts`) MUST be removed from the codebase.

### Key Entities

- **Network Settings**: The set of network-related configuration values: `allowedDomains` (list of strings), `allowUnixSockets` (list of strings), `allowAllUnixSockets` (boolean), `allowLocalBinding` (boolean), `httpProxyPort` (number), `socksProxyPort` (number).

## Assumptions

- The five new keys are simple pass-through values (no transformation needed, unlike `allowedDomains` which also generates `WebFetch` permission entries).
- The key names in `.srt-settings.json` match the key names in Claude Code `settings.json` exactly (no mapping needed).
- The existing selective merge behavior of fully replacing `sandbox.network` needs to be updated to a key-by-key merge to avoid wiping unmanaged keys like `allowManagedDomainsOnly`.
- Tom's comparison table is the authority for which keys exist in `.srt-settings.json`, not the SRT README.

## Success Criteria *(mandatory)*

### Measurable Outcomes

- **SC-001**: All five network keys present in the SRT source appear in the generated Claude Code settings output with correct values.
- **SC-002**: Network keys absent from the SRT source do not appear in the generated output.
- **SC-003**: Drift detection correctly identifies mismatches for all five new network keys.
- **SC-004**: The selective merge preserves `allowManagedDomainsOnly` and any other unmanaged keys in `sandbox.network`.
- **SC-005**: No references to the nested SRT format remain in production code or tests.
