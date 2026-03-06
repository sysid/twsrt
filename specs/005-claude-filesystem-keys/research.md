# Research: Pass-through All Remaining Sandbox Configuration Keys

## Decision 1: Config dict structure — three dicts vs one

**Decision**: Three separate config dicts (`network_config`, `filesystem_config`, `sandbox_config`)

**Rationale**: Each dict targets a different nesting level in the output JSON:
- `network_config` → `sandbox.network.*`
- `filesystem_config` → `sandbox.filesystem.*`
- `sandbox_config` → `sandbox.*` (top-level)

One big dict would require the generator to know which keys go where, duplicating the nesting knowledge. Three dicts encode the nesting implicitly.

**Alternatives considered**:
- Single `sandbox_passthrough: dict` with nested structure — cleaner but forces the parser to build output-shaped data, coupling it to the Claude Code schema
- Flat dict with dotted keys (`"filesystem.allowWrite"`) — awkward parsing, no benefit

## Decision 2: Filesystem keys — dual-use vs pass-through-only

**Decision**: Dual-use. `denyRead`, `denyWrite`, `allowWrite` continue to produce `SecurityRule` objects AND are also extracted as raw arrays into `filesystem_config`.

**Rationale**: The `SecurityRule` → `permissions.deny` pipeline (Layer 2: tool-level) is unchanged. The new `filesystem_config` → `sandbox.filesystem` pipeline (Layer 1: OS-level) is additive defense-in-depth. Both layers serve different enforcement mechanisms.

**Alternatives considered**:
- Pass-through only (remove SecurityRule generation) — breaks existing Layer 2 protection
- Derive `sandbox.filesystem` from SecurityRules in the generator — lossy (rules have been transformed with tool prefixes and `/**` expansion)

## Decision 3: Merge strategy for top-level sandbox keys

**Decision**: `dict.update()` at the `sandbox` level for top-level keys.

**Rationale**: Same pattern as `sandbox.network`. Keys in the generated output overwrite existing values. Keys NOT in the generated output (Claude-only keys like `excludedCommands`) are preserved because `update()` only touches keys present in the source dict.

**Alternatives considered**:
- Full replacement of `sandbox` section — would wipe Claude-only keys
- Explicitly listing preserved keys — fragile, breaks when Claude adds new keys

## Decision 4: Drift detection for complex types

**Decision**: For `ignoreViolations` (nested object) and filesystem arrays, compare using Python equality (`==`). Report drift as `sandbox.config:<key>` (present/absent/mismatch), same pattern as `network.config:<key>`.

**Rationale**: Deep structural diff of `ignoreViolations` would add complexity for minimal benefit. The user just needs to know "this key drifted", then they can run `generate` to see the expected value.

**Alternatives considered**:
- Per-command-pattern diff for `ignoreViolations` — over-engineered for this use case
- JSON patch output — too complex for a CLI drift report

## Decision 5: Where filesystem config values come from

**Decision**: Extract `filesystem_config` directly from the raw `filesystem` dict in `.srt-settings.json`, using the same key names (`allowWrite`, `denyWrite`, `denyRead`).

**Rationale**: The SRT key names match the Claude Code schema key names exactly. No mapping needed.

**Important nuance**: The `SecurityRule` pipeline already reads these arrays to create rules. The `filesystem_config` extraction reads the SAME arrays independently (not from the rules). This is intentional — the rules undergo transformation (scope/action classification), while `filesystem_config` is raw pass-through.
