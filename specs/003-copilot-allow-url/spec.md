# Feature Specification: Network Domain Flags for Copilot and Claude

**Feature Branch**: `003-copilot-allow-url`
**Created**: 2026-02-23
**Status**: Draft
**Input**: User description: "Currently 'twsrt generate copilot' does not generate '--allow-url example.com' from the whitelisted domains in SRT configuration. Add this. Also add denied domains ('deniedDomains') support for both Claude and Copilot."

## User Scenarios & Testing *(mandatory)*

### User Story 1 - Generate allow-url flags for Copilot from allowed domains (Priority: P1)

As a user who has whitelisted network domains in my SRT configuration (`allowedDomains` or `allowedHosts`), when I run `twsrt generate copilot`, I want the output to include `--allow-url <domain>` flags for each whitelisted domain so that Copilot CLI receives the same network allow-list as Claude Code.

**Why this priority**: This is the original motivation for the feature. The Copilot generator silently drops network allow-list information, creating a parity gap with Claude.

**Independent Test**: Provide SRT configuration with whitelisted domains and verify the copilot output includes corresponding `--allow-url` flags.

**Acceptance Scenarios**:

1. **Given** an SRT config (flat format) with `network.allowedDomains` containing `["github.com", "*.npmjs.org"]`, **When** the user runs `twsrt generate copilot`, **Then** the output includes `--allow-url 'github.com'` and `--allow-url '*.npmjs.org'` (one per line, alongside any existing flags).

2. **Given** an SRT config (nested format) with `sandbox.permissions.network.allowedHosts` containing `["example.com"]`, **When** the user runs `twsrt generate copilot`, **Then** the output includes `--allow-url 'example.com'`.

3. **Given** an SRT config with empty or missing network allow-list, **When** the user runs `twsrt generate copilot`, **Then** no `--allow-url` flags appear and existing behavior is unchanged.

---

### User Story 2 - Parse and generate denied domain flags for both agents (Priority: P1)

As a user who has denied network domains in my SRT configuration (`deniedDomains`), when I run `twsrt generate`, I want both generators to emit the appropriate deny flags so that blocked domains are enforced across all agents.

**Why this priority**: Denied domains exist in SRT config but are completely ignored by the system — not parsed, not modeled, not generated. This is a security gap: domains the user intends to block are silently dropped.

**Independent Test**: Provide SRT configuration with denied domains and verify both generators emit deny flags.

**Acceptance Scenarios**:

1. **Given** an SRT config (flat format) with `network.deniedDomains` containing `["evil.com", "*.tracker.net"]`, **When** the user runs `twsrt generate copilot`, **Then** the output includes `--deny-url 'evil.com'` and `--deny-url '*.tracker.net'`.

2. **Given** an SRT config (flat format) with `network.deniedDomains` containing `["evil.com"]`, **When** the user runs `twsrt generate claude`, **Then** the output includes a deny entry for that domain (e.g., `WebFetch(domain:evil.com)` in the `permissions.deny` list).

3. **Given** an SRT config with empty `deniedDomains: []`, **When** the user runs `twsrt generate`, **Then** no deny-url/deny-domain flags appear and existing behavior is unchanged.

4. **Given** an SRT config (nested format) with `sandbox.permissions.network.deniedHosts` containing `["bad.com"]`, **When** the user runs `twsrt generate`, **Then** both generators emit appropriate deny flags for that domain.

---

### User Story 3 - Drift detection for network domain flags (Priority: P2)

As a user who runs `twsrt diff`, I want drift detection to cover both allowed and denied domain flags for both agents so that domain changes in SRT are flagged as drift.

**Why this priority**: Drift detection ensures ongoing correctness. Without it, domain changes in SRT would not be flagged for either agent.

**Independent Test**: Create agent output files with missing/extra domain entries and verify `twsrt diff` reports discrepancies.

**Acceptance Scenarios**:

1. **Given** an SRT config with `allowedDomains: ["a.com", "b.com"]` and a copilot file containing only `--allow-url 'a.com'`, **When** the user runs `twsrt diff copilot`, **Then** the output reports `--allow-url 'b.com'` as missing.

2. **Given** an SRT config with `deniedDomains: ["evil.com"]` and a Claude settings file with no deny entry for `evil.com`, **When** the user runs `twsrt diff claude`, **Then** the output reports the deny entry as missing.

---

### Edge Cases

- What happens when a domain contains wildcard patterns (e.g., `*.github.com`)? The pattern is passed through verbatim.
- What happens when the same domain appears in both allowed and denied lists? Each list is processed independently — both flags are emitted. The SRT configuration is assumed to be correct (twsrt does not validate SRT semantics).
- What happens when duplicate domains appear within the same list? Each unique domain produces exactly one flag (deduplication).
- What happens when the domain lists are empty or missing? No domain flags are generated; output is unchanged.

## Requirements *(mandatory)*

### Functional Requirements

**Allowed domains (Copilot — new):**
- **FR-001**: The Copilot generator MUST emit `--allow-url '<domain>'` for each domain in the SRT network allow-list (`allowedDomains` / `allowedHosts`).
- **FR-002**: Each `--allow-url` flag MUST appear on its own line, consistent with the existing flag-per-line output format.

**Denied domains (parsing — new):**
- **FR-003**: The SRT parser MUST read `deniedDomains` (flat format) and `deniedHosts` (nested format) into `NETWORK/DENY` security rules.
- **FR-004**: The SecurityRule model MUST support `NETWORK/DENY` in addition to the existing `NETWORK/ALLOW`.

**Denied domains (Copilot — new):**
- **FR-005**: The Copilot generator MUST emit `--deny-url '<domain>'` for each denied domain.

**Denied domains (Claude — new):**
- **FR-006**: The Claude generator MUST emit `WebFetch(domain:<domain>)` in the `permissions.deny` list for each denied domain.

**Drift detection:**
- **FR-007**: The Copilot diff operation MUST detect missing and extra `--allow-url` and `--deny-url` entries.
- **FR-008**: The Claude diff operation MUST detect missing and extra denied domain entries in `permissions.deny`.

**General:**
- **FR-009**: Duplicate domains MUST produce only one flag per unique domain per list (allow/deny independently deduplicated).
- **FR-010**: Existing behavior for all other rule types MUST remain unchanged.

### Key Entities

- **SecurityRule (NETWORK/ALLOW)**: Represents a whitelisted domain. Already parsed from SRT config but ignored by CopilotGenerator.
- **SecurityRule (NETWORK/DENY)**: Represents a blocked domain. Not yet supported — requires model change and new parsing logic.

## Clarifications

### Session 2026-02-23

- Q: Should FR-007 (`sandbox.network.deniedDomains` in Claude output) be kept or dropped? → A: Drop FR-007. Denied domains are expressed only via `permissions.deny` entries (`WebFetch(domain:...)`), not via a `sandbox.network.deniedDomains` field (which Claude Code does not consume).

## Assumptions

- The `--allow-url` and `--deny-url` flag names match GitHub Copilot CLI's actual flag syntax.
- The nested SRT format uses `deniedHosts` as the counterpart to `allowedHosts` for denied domains.
- Domain patterns are passed through as-is (no normalization or validation beyond what SRT provides).
- The existing line-based diff in `CopilotGenerator.diff()` naturally covers new flag types without structural changes.
- The Claude selective merge handles denied domain entries via the existing `permissions.deny` replacement logic (no `sandbox.network` changes needed for denied domains).

## Success Criteria *(mandatory)*

### Measurable Outcomes

- **SC-001**: Running `twsrt generate copilot` with N allowed domains produces exactly N `--allow-url` flags.
- **SC-002**: Running `twsrt generate copilot` with M denied domains produces exactly M `--deny-url` flags.
- **SC-003**: Running `twsrt generate claude` with M denied domains produces M `WebFetch(domain:...)` deny entries in `permissions.deny`.
- **SC-004**: Drift detection for both agents correctly identifies 100% of missing and extra domain entries.
- **SC-005**: All existing tests continue to pass without modification (no regressions).
- **SC-006**: Both agents achieve full parity with SRT's network domain configuration — every allowed and denied domain maps to the agent's respective format.
