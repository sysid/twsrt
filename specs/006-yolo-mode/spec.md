# Feature Specification: YOLO Mode

**Feature Branch**: `006-yolo-mode`
**Created**: 2026-03-14
**Status**: Draft
**Input**: User description: "Add a --yolo mode which ignores the ask section of bash-rules.json and only creates configuration with the deny rules. For claude it should update settings.yolo.json, for copilot we need to figure this out."

## User Scenarios & Testing *(mandatory)*

### User Story 1 - Generate Claude Config in YOLO Mode (Priority: P1)

As a developer, I want to generate a Claude configuration that only contains deny rules (no ask rules), so that I can run Claude with `--dangerously-skip-permissions` while retaining hard safety boundaries via deny rules.

**Why this priority**: This is the core feature — generating a permissive Claude config designed for unattended/autonomous use. Deny rules override `--dangerously-skip-permissions`, so dangerous commands remain blocked even in bypass mode.

**Independent Test**: Can be fully tested by running the generate command with the yolo flag targeting Claude and verifying the output contains only `permissions.deny` entries (no ask entries) and is written to `settings.yolo.json`.

**Acceptance Scenarios**:

1. **Given** a bash-rules.json with both "deny" and "ask" sections, **When** the user runs the generate command with the yolo flag for Claude, **Then** the generated configuration contains only `permissions.deny` entries — no `permissions.ask` entries appear in the output.
2. **Given** the yolo flag is active for Claude, **When** the configuration is written to disk, **Then** the output is saved to `settings.yolo.json` (not `settings.json`), preserving the standard config untouched.
3. **Given** the yolo flag is active, **When** the generate command runs, **Then** all non-bash-rules configuration (network allowlists, filesystem rules, sandbox settings) is included identically to the standard mode.
4. **Given** the generated `settings.yolo.json` is in place, **When** the user runs Claude with `--dangerously-skip-permissions`, **Then** commands from the "deny" section are still blocked while all other commands execute without prompts.

---

### User Story 2 - Generate Copilot Config in YOLO Mode (Priority: P2)

As a developer, I want to generate a Copilot configuration in yolo mode that includes `--yolo` as the first flag followed by `--deny-tool` entries for denied commands only, so that Copilot runs autonomously while dangerous commands remain blocked.

**Why this priority**: Extends yolo mode to the second supported agent. Copilot's `--yolo` flag (alias for `--allow-all`) enables autonomous operation, while `--deny-tool` entries always take precedence, ensuring dangerous commands stay blocked.

**Independent Test**: Can be fully tested by running the generate command with the yolo flag targeting Copilot and verifying that the output starts with `--yolo` followed by only deny-derived `--deny-tool` entries (no ask-derived entries).

**Acceptance Scenarios**:

1. **Given** a bash-rules.json with both "deny" and "ask" sections, **When** the user runs the generate command with the yolo flag for Copilot, **Then** the generated output begins with `--yolo` as the first flag, followed by `--deny-tool` entries for commands from the "deny" section only — no ask-derived entries appear.
2. **Given** the yolo flag is active for Copilot, **When** the configuration is written to disk, **Then** the output is saved to a yolo-specific file separate from the standard copilot flags file.
3. **Given** the generated yolo copilot flags are in use, **When** Copilot runs with those flags, **Then** commands from the "deny" section are blocked while all other commands execute without prompts.

---

### User Story 3 - Generate All Agents in YOLO Mode (Priority: P2)

As a developer, I want to run the generate command with `--yolo` targeting "all" agents, so that both Claude and Copilot configurations are generated in yolo mode in a single command.

**Why this priority**: Convenience feature — developers often generate configs for all agents at once. YOLO mode must work with the existing "all" target.

**Independent Test**: Can be tested by running generate with yolo flag and "all" target, verifying both agent outputs use yolo behavior and write to their respective yolo-specific files.

**Acceptance Scenarios**:

1. **Given** the yolo flag is active with agent target "all", **When** the generate command runs, **Then** both Claude and Copilot configs are generated using yolo rules and written to their respective yolo-specific output files.

---

### User Story 4 - Diff Against YOLO Config (Priority: P3)

As a developer, I want the diff command to detect drift between the generated yolo config and the existing yolo config files on disk, so that I know when my yolo configs are out of date.

**Why this priority**: Extends existing drift detection to yolo configs. Lower priority because the core value is in generation, not diffing.

**Independent Test**: Can be tested by generating yolo config, manually modifying the output file, then running diff with yolo flag and verifying drift is detected.

**Acceptance Scenarios**:

1. **Given** a yolo config file exists on disk, **When** the user runs the diff command with the yolo flag, **Then** the diff compares the generated yolo config against the yolo-specific file (not the standard config file).
2. **Given** no yolo config file exists, **When** the user runs diff with the yolo flag, **Then** the system reports the missing file appropriately.

---

### Edge Cases

- What happens when bash-rules.json has no "ask" section? The yolo output should be identical to the standard output (only deny rules exist in both cases).
- What happens when bash-rules.json has an "ask" section but no "deny" section? The yolo output should contain no bash command restrictions (Claude: empty deny list; Copilot: `--yolo` flag only, no `--deny-tool` entries).
- What happens when the user combines `--yolo` with `--dry-run`? Both flags should work together — dry-run shows what the yolo config would look like without writing.
- What happens when the standard settings file doesn't exist but the user runs yolo generate with `--write`? The yolo file should still be created — it doesn't depend on the standard file existing.

## Requirements *(mandatory)*

### Functional Requirements

- **FR-001**: The generate command MUST accept a `--yolo` flag that switches to yolo mode.
- **FR-002**: In yolo mode, the system MUST exclude all rules derived from the "ask" section of bash-rules.json from the generated configuration.
- **FR-003**: In yolo mode, the system MUST include all rules derived from the "deny" section of bash-rules.json in the generated configuration.
- **FR-004**: In yolo mode for Claude, the system MUST generate a `settings.yolo.json` containing only `permissions.deny` entries (no `permissions.ask`). The user is expected to combine this with `--dangerously-skip-permissions` at runtime, where deny rules take precedence over the bypass flag.
- **FR-005**: In yolo mode for Copilot, the system MUST generate output with `--yolo` as the first flag, followed by `--deny-tool` entries for deny-section commands only. Copilot's `--yolo` flag enables autonomous operation while `--deny-tool` always takes precedence.
- **FR-006**: In yolo mode, all non-bash-rules configuration (network, filesystem, sandbox settings) MUST be included identically to standard mode.
- **FR-007**: The `--yolo` flag MUST be combinable with existing flags (`--write`, `--dry-run`, agent target argument).
- **FR-008**: The diff command MUST support a `--yolo` flag that compares against the yolo-specific output files.
- **FR-009**: The yolo output file paths MUST default to automatic derivation from the standard paths by inserting "yolo" into the filename (e.g., `settings.json` becomes `settings.yolo.json`, `copilot-flags.txt` becomes `copilot-flags.yolo.txt`). Users MAY override these defaults via configuration.

### Key Entities

- **Bash Rules Source**: The canonical bash-rules.json file containing "deny" and "ask" sections. In yolo mode, only the "deny" section is consumed.
- **YOLO Config Output**: Agent-specific configuration files generated in yolo mode, stored at separate paths from standard config files. For Claude: JSON settings with deny-only permissions. For Copilot: flag file starting with `--yolo` followed by `--deny-tool` entries.

## Assumptions

- The yolo mode only affects bash-rules processing. All other sources (SRT settings for network, filesystem, sandbox) are processed identically to standard mode.
- The name "yolo" is user-facing and will appear in CLI help text and output messages.
- The `--yolo` flag applies to the entire generate/diff operation — there is no per-agent yolo toggle.
- For Claude, `settings.yolo.json` lives in the same directory as `settings.json` (i.e., `~/.claude/settings.yolo.json`).
- For Copilot, the yolo output file is derived by inserting ".yolo" into the standard output filename.
- Claude's deny rules override `--dangerously-skip-permissions` (documented behavior: deny is evaluated before bypass mode).
- Copilot's `--deny-tool` overrides `--yolo`/`--allow-all` (documented behavior: deny takes precedence over allow).

## Success Criteria *(mandatory)*

### Measurable Outcomes

- **SC-001**: Users can generate a yolo configuration for any supported agent in a single command, completing in under 2 seconds.
- **SC-002**: The generated yolo configuration contains zero entries derived from the "ask" section of bash-rules.json — verified by comparing entry counts between standard and yolo output.
- **SC-003**: All deny rules from bash-rules.json appear in the yolo output — 100% coverage of the deny section.
- **SC-004**: The standard configuration files remain untouched when generating yolo configs — no side effects on existing setup.
- **SC-005**: Drift detection works for yolo configs with the same reliability as standard configs (exit code 0 for no drift, 1 for drift, 2 for missing file).
- **SC-006**: For Copilot, `--yolo` appears as the first flag in the generated output, before any `--deny-tool` entries.
