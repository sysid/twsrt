# Research: Network Domain Flags for Copilot and Claude

**Feature**: 003-copilot-allow-url | **Date**: 2026-02-23

## R-001: Copilot CLI URL Permission Flags

**Decision**: Use `--allow-url '<domain>'` and `--deny-url '<domain>'` as flag format.

**Rationale**: Confirmed via [GitHub Copilot CLI docs](https://docs.github.com/en/copilot/how-tos/copilot-cli/set-up-copilot-cli/configure-copilot-cli) and [Command-Line Flags Reference](https://deepwiki.com/github/copilot-cli/5.6-command-line-flags-reference). These are documented Copilot CLI flags for network domain whitelisting/blacklisting.

**Alternatives considered**: None — these are the canonical flags.

**Notes**: Copilot URL flags are protocol-aware (patterns without explicit protocol default to `https://`). SRT domain patterns (e.g., `*.github.com`) are passed through as-is — protocol handling is Copilot CLI's responsibility.

## R-002: Nested SRT Format Field Name for Denied Domains

**Decision**: Use `deniedHosts` as the nested format counterpart to `deniedDomains` (flat format), mirroring the `allowedHosts` / `allowedDomains` parallel.

**Rationale**: The existing SRT parsing (`sources.py`) maps:
- Flat: `network.allowedDomains` ↔ Nested: `sandbox.permissions.network.allowedHosts`

Following the same naming convention:
- Flat: `network.deniedDomains` ↔ Nested: `sandbox.permissions.network.deniedHosts`

**Alternatives considered**:
- `blockedHosts` — possible but inconsistent with the `denied*` / `allowed*` naming pattern already established.

## R-003: Claude Code Denied Domain Mechanism

**Decision**: Denied domains in Claude Code are expressed solely via `permissions.deny` entries as `WebFetch(domain:<domain>)`. No `sandbox.network.deniedDomains` field exists in Claude Code settings.

**Rationale**: Confirmed during `/speckit.clarify` session (Q1). Claude Code's `sandbox.network` section only contains `allowedHosts`/`allowedDomains`. The `permissions.deny` mechanism is the established way to block specific tool invocations.

**Alternatives considered**:
- `sandbox.network.deniedDomains` — rejected because Claude Code does not consume this field.

## R-004: SecurityRule Model Constraint Change

**Decision**: Relax `SecurityRule.__post_init__` validation to allow `NETWORK/DENY` in addition to `NETWORK/ALLOW`.

**Rationale**: The current constraint (`NETWORK scope requires ALLOW action`) was an MVP simplification. The SRT config has `deniedDomains` which maps to `NETWORK/DENY`. The constraint must be relaxed to support both actions.

**Alternatives considered**:
- New scope `NETWORK_DENY` — rejected as overly complex; `NETWORK` + `DENY` action is the natural model.
- Bypass validation entirely — rejected as unsafe; keep validation for invalid combinations.

## R-005: Drift Detection Approach

**Decision**: Copilot drift detection requires no structural changes — the existing line-based set comparison in `CopilotGenerator.diff()` naturally covers `--allow-url` and `--deny-url` lines. Claude drift detection requires adding `WebFetch(domain:...)` deny entry comparison alongside the existing allow entry comparison.

**Rationale**: Copilot diff compares line sets. New `--allow-url` and `--deny-url` lines will be in the generated set and compared against the target file. For Claude diff, the existing code only filters `WebFetch(domain:...)` entries in the `allow` section — denied domain entries in the `deny` section need similar treatment.

**Alternatives considered**: None — following established patterns.

## R-006: Selective Merge Impact

**Decision**: No changes needed to `selective_merge()`. The `permissions.deny` section is already fully replaced during merge, so denied domain `WebFetch(domain:...)` entries will be included automatically.

**Rationale**: `selective_merge()` fully replaces `permissions.deny` and `permissions.ask`. Only `permissions.allow` uses selective replacement (preserving non-WebFetch entries). Since denied domains go into `permissions.deny`, the existing full-replacement logic handles them correctly.

**Alternatives considered**: None — existing merge logic already works.
