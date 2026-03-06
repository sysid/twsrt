# Feature Specification: Pass-through All Remaining Sandbox Configuration Keys

**Feature Branch**: `005-claude-filesystem-keys`
**Created**: 2026-03-06
**Status**: Draft
**Input**: User description: "The Claude Code sandbox configuration supports the filesystem configurations allowWrite, denyWrite, denyRead. Make sure that the corresponding configuration is created from the source .srt-settings.json. Also add all other missing sandbox keys and document the full mapping in README.md, especially which Claude sandbox keys have no SRT source and must never be touched by generate."

## Context

The Claude Code `sandbox` schema has keys across four groups: `network`, `filesystem`, top-level booleans, and `ignoreViolations`. Feature 004 covered network pass-through keys. This feature covers everything else.

### Full SRT → Claude Sandbox Mapping

| Claude Code `sandbox.*` key       | SRT `.srt-settings.json` key       | Status          |
|------------------------------------|-------------------------------------|-----------------|
| `network.allowedDomains`           | `network.allowedDomains`            | Done (001+004)  |
| `network.allowUnixSockets`         | `network.allowUnixSockets`          | Done (004)      |
| `network.allowAllUnixSockets`      | `network.allowAllUnixSockets`       | Done (004)      |
| `network.allowLocalBinding`        | `network.allowLocalBinding`         | Done (004)      |
| `network.httpProxyPort`            | `network.httpProxyPort`             | Done (004)      |
| `network.socksProxyPort`           | `network.socksProxyPort`            | Done (004)      |
| `network.allowManagedDomainsOnly`  | — (no SRT source)                   | Claude-only     |
| `filesystem.allowWrite`            | `filesystem.allowWrite`             | **This feature** |
| `filesystem.denyWrite`             | `filesystem.denyWrite`              | **This feature** |
| `filesystem.denyRead`              | `filesystem.denyRead`               | **This feature** |
| `ignoreViolations`                 | `ignoreViolations`                  | **This feature** |
| `enabled`                          | `enabled`                           | **This feature** |
| `enableWeakerNetworkIsolation`     | `enableWeakerNetworkIsolation`      | **This feature** |
| `enableWeakerNestedSandbox`        | `enableWeakerNestedSandbox`         | **This feature** |
| `excludedCommands`                 | — (no SRT source)                   | Claude-only     |
| `autoAllowBashIfSandboxed`         | — (no SRT source)                   | Claude-only     |
| `allowUnsandboxedCommands`         | — (no SRT source)                   | Claude-only     |

**Claude-only keys** (no SRT source) MUST NOT be generated, modified, or removed by twsrt.

## User Scenarios & Testing *(mandatory)*

### User Story 1 - Generate Filesystem Sandbox Configuration (Priority: P1)

As a security administrator, I configure filesystem access rules in `.srt-settings.json` under `filesystem.allowWrite`, `filesystem.denyWrite`, and `filesystem.denyRead`. Currently the generator produces `permissions.deny` entries from these rules but does NOT populate the `sandbox.filesystem` section in Claude Code `settings.json`. I need the generator to also emit `sandbox.filesystem.allowWrite`, `sandbox.filesystem.denyWrite`, and `sandbox.filesystem.denyRead` so that the sandbox enforces these restrictions at the OS level — not just at the tool-permission level.

**Why this priority**: Filesystem sandbox keys are the primary gap. They provide defense-in-depth: even if a permission rule is misconfigured, the OS-level sandbox blocks the operation.

**Independent Test**: Create an `.srt-settings.json` with all three filesystem keys populated and verify the generated `settings.json` contains them under `sandbox.filesystem`.

**Acceptance Scenarios**:

1. **Given** an `.srt-settings.json` with `filesystem.allowWrite` containing `[".", "/tmp", "~/.gradle"]`, **When** the Claude generator runs, **Then** `sandbox.filesystem.allowWrite` in the output contains the same list.
2. **Given** an `.srt-settings.json` with `filesystem.denyWrite` containing `["**/.env", "**/*.pem"]`, **When** the Claude generator runs, **Then** `sandbox.filesystem.denyWrite` in the output contains the same list.
3. **Given** an `.srt-settings.json` with `filesystem.denyRead` containing `["~/.ssh", "~/.aws"]`, **When** the Claude generator runs, **Then** `sandbox.filesystem.denyRead` in the output contains the same list.

---

### User Story 2 - Generate Top-level Sandbox Keys and ignoreViolations (Priority: P1)

As a security administrator, I also configure `enabled`, `enableWeakerNetworkIsolation`, `enableWeakerNestedSandbox`, and `ignoreViolations` in `.srt-settings.json`. These should propagate into the corresponding `sandbox.*` keys in the generated Claude Code settings.

**Why this priority**: These keys control fundamental sandbox behavior (on/off, isolation strength, violation exceptions). Without them, the generated config is incomplete.

**Independent Test**: Create an `.srt-settings.json` with all four keys and verify they appear in the generated output under `sandbox`.

**Acceptance Scenarios**:

1. **Given** an `.srt-settings.json` with `enabled: true`, **When** the Claude generator runs, **Then** `sandbox.enabled` is `true` in the output.
2. **Given** an `.srt-settings.json` with `enableWeakerNetworkIsolation: true`, **When** the Claude generator runs, **Then** `sandbox.enableWeakerNetworkIsolation` is `true` in the output.
3. **Given** an `.srt-settings.json` with `enableWeakerNestedSandbox: false`, **When** the Claude generator runs, **Then** `sandbox.enableWeakerNestedSandbox` is `false` in the output.
4. **Given** an `.srt-settings.json` with `ignoreViolations: {"*": ["/usr/bin"], "git push": ["/usr/bin/nc"]}`, **When** the Claude generator runs, **Then** `sandbox.ignoreViolations` contains the same mapping.

---

### User Story 3 - Omit Absent Keys from Output (Priority: P2)

As a user, keys I do not define in my `.srt-settings.json` should not appear in the generated `sandbox` output. This avoids overriding Claude Code's built-in defaults.

**Why this priority**: Prevents the generator from injecting defaults that could conflict with Claude Code's own defaults or other configuration layers.

**Independent Test**: Generate settings from a minimal `.srt-settings.json` (only `network.allowedDomains`) and verify none of the new sandbox keys appear.

**Acceptance Scenarios**:

1. **Given** an `.srt-settings.json` with only `filesystem.denyRead` defined, **When** the Claude generator runs, **Then** `sandbox.filesystem` contains only `denyRead`.
2. **Given** an `.srt-settings.json` with no `filesystem` section, **When** the Claude generator runs, **Then** `sandbox.filesystem` is absent from the output.
3. **Given** an `.srt-settings.json` with no `enabled` key, **When** the Claude generator runs, **Then** `sandbox.enabled` is absent from the output.
4. **Given** an `.srt-settings.json` with no `ignoreViolations` key, **When** the Claude generator runs, **Then** `sandbox.ignoreViolations` is absent from the output.

---

### User Story 4 - Claude-only Keys Never Touched (Priority: P1)

The Claude Code sandbox schema has keys that have no SRT source: `excludedCommands`, `autoAllowBashIfSandboxed`, `allowUnsandboxedCommands`, `allowManagedDomainsOnly`. The generator MUST NOT generate, modify, or remove these keys.

**Why this priority**: Touching Claude-only keys could break user configurations or introduce security regressions.

**Independent Test**: Generate and apply settings to a `settings.json` that has all four Claude-only keys set. Verify all four survive unchanged.

**Acceptance Scenarios**:

1. **Given** an existing `settings.json` with `sandbox.autoAllowBashIfSandboxed: true`, **When** the apply command runs, **Then** the value is preserved unchanged.
2. **Given** an existing `settings.json` with `sandbox.excludedCommands: ["docker"]`, **When** the apply command runs, **Then** the list is preserved unchanged.
3. **Given** an existing `settings.json` with `sandbox.allowUnsandboxedCommands: false`, **When** the apply command runs, **Then** the value is preserved unchanged.
4. **Given** an existing `settings.json` with `sandbox.network.allowManagedDomainsOnly: true`, **When** the apply command runs, **Then** the value is preserved unchanged.

---

### User Story 5 - Drift Detection for All New Keys (Priority: P2)

As a user running the `diff` command, I want drift detection to cover all new sandbox keys: filesystem keys, top-level booleans, and ignoreViolations.

**Why this priority**: Drift detection is the verification tool. Without it, users cannot confirm that their settings match the SRT source.

**Independent Test**: Generate settings with specific values, compare against an existing settings.json with different values, and verify the diff reports all discrepancies.

**Acceptance Scenarios**:

1. **Given** generated `sandbox.filesystem.denyRead: ["~/.ssh"]` and existing `sandbox.filesystem.denyRead: ["~/.aws"]`, **When** the diff runs, **Then** the discrepancy is reported.
2. **Given** generated `sandbox.enabled: true` and existing `sandbox.enabled: false`, **When** the diff runs, **Then** the discrepancy is reported.
3. **Given** generated and existing settings with identical sandbox keys, **When** the diff runs, **Then** no drift is reported.

---

### User Story 6 - README Documents Full Mapping (Priority: P2)

The README must include a clear reference table showing every Claude Code sandbox key, its SRT source (if any), and whether twsrt manages it. Keys with no SRT source must be explicitly marked as "Claude-only — never touched by twsrt".

**Why this priority**: Without documentation, users cannot understand what twsrt manages vs. what they must configure manually.

**Independent Test**: Read the README and verify every Claude Code sandbox schema key is listed with its management status.

**Acceptance Scenarios**:

1. **Given** the README, **When** a user looks up `autoAllowBashIfSandboxed`, **Then** it is listed as "Claude-only — never touched by twsrt".
2. **Given** the README, **When** a user looks up `filesystem.allowWrite`, **Then** it is listed as managed by twsrt with the SRT source key.

---

### Edge Cases

- What happens when `allowWrite` is an empty list in the SRT source? The key should be included in the output as `[]` (explicitly set differs from absent).
- What happens when `ignoreViolations` is an empty object `{}`? Include it in the output as `{}`.
- What happens when the SRT source has `filesystem` section but all three arrays are absent? `sandbox.filesystem` should not appear in the output.
- What happens when boolean keys (`enabled`, `enableWeakerNetworkIsolation`) are absent from SRT? They must not appear in the generated output.
- What happens when `enabled` is `false`? Pass through as `false` — it is a valid and meaningful value.

## Requirements *(mandatory)*

### Functional Requirements

**Filesystem keys:**
- **FR-001**: System MUST read `allowWrite`, `denyWrite`, `denyRead` from `.srt-settings.json` filesystem section.
- **FR-002**: System MUST write each present filesystem key into `sandbox.filesystem` using the same key name.
- **FR-003**: System MUST omit filesystem keys from the output when absent from the SRT source.

**Top-level sandbox keys:**
- **FR-004**: System MUST read `enabled`, `enableWeakerNetworkIsolation`, `enableWeakerNestedSandbox` from `.srt-settings.json` top level.
- **FR-005**: System MUST write each present top-level key into `sandbox` using the same key name.
- **FR-006**: System MUST omit top-level sandbox keys from the output when absent from the SRT source.

**ignoreViolations:**
- **FR-007**: System MUST read `ignoreViolations` from `.srt-settings.json` top level.
- **FR-008**: System MUST write it into `sandbox.ignoreViolations` when present.

**Preservation:**
- **FR-009**: System MUST continue generating `permissions.deny` entries from filesystem rules (existing behavior unchanged).
- **FR-010**: System MUST NOT generate, modify, or remove Claude-only keys: `excludedCommands`, `autoAllowBashIfSandboxed`, `allowUnsandboxedCommands`, `allowManagedDomainsOnly`.
- **FR-011**: Selective merge MUST preserve Claude-only keys and any other unmanaged keys in the `sandbox` section.

**Drift detection:**
- **FR-012**: Drift detection MUST report differences for all new managed sandbox keys.

**Documentation:**
- **FR-013**: README MUST include a complete mapping table of all Claude Code sandbox keys, their SRT source, and whether twsrt manages them.

**Empty/falsy value handling:**
- **FR-014**: System MUST treat explicitly-set empty arrays/objects and `false` values as present (they differ from absent keys).

### Key Entities

- **Filesystem Sandbox Config**: `allowWrite`, `denyWrite`, `denyRead` — arrays of path patterns, pass-through from SRT to `sandbox.filesystem`.
- **Top-level Sandbox Config**: `enabled` (boolean), `enableWeakerNetworkIsolation` (boolean), `enableWeakerNestedSandbox` (boolean) — pass-through from SRT top-level to `sandbox.*`.
- **Ignore Violations**: `ignoreViolations` — object mapping command patterns to filesystem path arrays, pass-through from SRT to `sandbox.ignoreViolations`.
- **Claude-only Keys**: `excludedCommands`, `autoAllowBashIfSandboxed`, `allowUnsandboxedCommands`, `allowManagedDomainsOnly` — exist only in Claude Code schema, never generated by twsrt.

## Assumptions

- All seven new keys are simple pass-through values (no transformation). Key names in SRT match Claude Code schema exactly.
- This feature is additive: existing `permissions.deny` generation from filesystem rules continues unchanged.
- The pass-through pattern mirrors feature 004 (claude-network-keys): extract from SRT, carry via config, emit in generator.
- `SrtResult` and `AppConfig` will gain new fields for `filesystem_config`, `sandbox_config` (top-level booleans + ignoreViolations), analogous to existing `network_config`.
- The `SRT.allowPty` key has no Claude Code counterpart and is excluded.
- The `SRT.network.deniedDomains` and `SRT.network.mitmProxy` keys have no Claude Code counterpart and remain excluded (as established in feature 004).

## Success Criteria *(mandatory)*

### Measurable Outcomes

- **SC-001**: All seven new keys present in the SRT source appear in the generated Claude Code settings output at the correct paths with correct values.
- **SC-002**: Keys absent from the SRT source do not appear in the generated output.
- **SC-003**: Claude-only keys in an existing settings.json survive generate and apply operations unchanged.
- **SC-004**: Drift detection correctly identifies mismatches for all new managed sandbox keys.
- **SC-005**: The selective merge preserves unmanaged keys in `sandbox`, `sandbox.filesystem`, and `sandbox.network`.
- **SC-006**: Existing `permissions.deny` generation from filesystem rules continues to work unchanged.
- **SC-007**: README contains a complete mapping table covering every Claude Code sandbox key with its management status.
