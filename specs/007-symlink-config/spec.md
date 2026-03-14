# Feature Specification: Symlink-Based Config Management

**Feature Branch**: `007-symlink-config`
**Created**: 2026-03-14
**Status**: Draft
**Input**: User description: "Update twsrt configuration mechanism to use symlinks for Claude settings — generate writes to named config files and symlinks settings.json to the active one"

## Clarifications

### Session 2026-03-14

- Q: When `settings.json` is a regular file AND the target file already exists, what should happen? → A: Error out — refuse to proceed, tell user to resolve manually (e.g. "both settings.json (regular file) and settings.full.json exist — remove one before running generate -w").

## User Scenarios & Testing *(mandatory)*

### User Story 1 - Generate Claude Config with Symlink (Priority: P1)

When a user runs `twsrt generate claude -w`, twsrt writes the generated config to the
named target file (e.g. `settings.full.json`) rather than directly to `settings.json`.
It then creates (or updates) a symlink from `~/.claude/settings.json` pointing to the
target file. This allows switching between full and yolo configs by changing the symlink.

If `settings.json` already exists as a regular file (not a symlink), twsrt moves it to
the target path first and informs the user, preserving their existing configuration.
If both `settings.json` (regular file) and the target file already exist, twsrt errors
out and asks the user to resolve the conflict manually.

**Why this priority**: Core behavioral change — every `generate -w` must use symlinks.
Without this, switching between full and yolo configs requires manual file management.

**Independent Test**: Run `generate claude -w`, verify target file is written and
`settings.json` is a symlink pointing to it.

**Acceptance Scenarios**:

1. **Given** `settings.json` does not exist, **When** `generate claude -w` runs, **Then** target file is created with generated config and `settings.json` is a relative symlink to target.
2. **Given** `settings.json` is a regular file and target does not exist, **When** `generate claude -w` runs, **Then** `settings.json` is moved to the target path, the target is updated via selective merge, `settings.json` becomes a symlink to the target, and the user is informed of the migration.
3. **Given** `settings.json` is a regular file and target already exists, **When** `generate claude -w` runs, **Then** twsrt prints an error message naming both files and exits with a non-zero code without modifying either file.
4. **Given** `settings.json` is already a symlink to the target, **When** `generate claude -w` runs, **Then** the target is updated via selective merge and the symlink is unchanged.
5. **Given** `settings.json` is a symlink to a different file (e.g. yolo target), **When** `generate claude -w` runs, **Then** the target is updated and the symlink is re-pointed to the full target.

---

### User Story 2 - Generate Claude YOLO Config with Symlink (Priority: P1)

When a user runs `twsrt generate --yolo claude -w`, twsrt writes the yolo config to the
yolo target file (e.g. `settings.yolo.json`) and symlinks `settings.json` to it.

Same migration logic applies: if `settings.json` is a regular file and target does not
exist, move it. If both exist, error out.

**Why this priority**: Yolo mode is equally important — the symlink mechanism must work
for both modes to enable switching.

**Independent Test**: Run `generate --yolo claude -w`, verify yolo target file exists and
`settings.json` symlinks to it.

**Acceptance Scenarios**:

1. **Given** `settings.json` does not exist, **When** `generate --yolo claude -w` runs, **Then** yolo target is created and `settings.json` is a relative symlink to yolo target.
2. **Given** `settings.json` is a regular file and yolo target does not exist, **When** `generate --yolo claude -w` runs, **Then** `settings.json` is moved to the yolo target, updated via selective merge, and `settings.json` becomes a symlink to yolo target with user notification.
3. **Given** `settings.json` is a regular file and yolo target already exists, **When** `generate --yolo claude -w` runs, **Then** twsrt errors out naming both files without modifying either.
4. **Given** `settings.json` is a symlink to the full target, **When** `generate --yolo claude -w` runs, **Then** yolo target is updated and symlink is re-pointed to yolo target.

---

### User Story 3 - Updated Init Command (Priority: P2)

When a user runs `twsrt init`, the generated `config.toml` includes the full set of
configuration keys with the yolo targets commented out. The default `claude_settings`
target is `~/.claude/settings.full.json`.

**Why this priority**: First-time setup must produce a comprehensive config so users
understand all available options.

**Independent Test**: Run `twsrt init`, inspect generated `config.toml` for all keys.

**Acceptance Scenarios**:

1. **Given** no config directory exists, **When** `twsrt init` runs, **Then** `config.toml` contains `claude_settings = "~/.claude/settings.full.json"`, `copilot_output` (commented out), and both yolo targets (commented out) with explanatory comments.
2. **Given** config directory already exists without `--force`, **When** `twsrt init` runs, **Then** existing files are preserved (skip with message).

---

### User Story 4 - Diff with Symlink Awareness (Priority: P3)

When running `twsrt diff claude`, the tool follows the symlink and compares against the
resolved target file. When running `twsrt diff --yolo claude`, it compares against the
yolo target file. The diff command does not manage symlinks — it only reads.

**Why this priority**: Drift detection must work regardless of the symlink setup.

**Independent Test**: Create a yolo symlink, run `diff claude`, verify it reads the
correct resolved file.

**Acceptance Scenarios**:

1. **Given** `settings.json` is a symlink to `settings.full.json`, **When** `diff claude` runs, **Then** it compares against the resolved file content.
2. **Given** yolo target exists, **When** `diff --yolo claude` runs, **Then** it compares against the yolo target directly (not following `settings.json` symlink).

---

### Edge Cases

- What happens when the target directory does not exist? Create parent directories.
- What happens when the symlink target file does not exist (dangling symlink)? Treat as fresh write (create target, then symlink).
- What happens on a filesystem that does not support symlinks (rare, but Windows)? Fall back to direct write with a warning — do not create symlink.
- What happens when `settings.json` is a symlink to an unrelated file (not managed by twsrt)? Overwrite the symlink to point to the twsrt target, warn the user.
- What happens when both full and yolo target files exist and user switches between modes? The non-active file is left untouched; only the active target is updated and symlinked.
- What happens when `generate copilot -w` runs? Copilot does not use symlinks — direct write behavior is unchanged.
- What happens when `settings.json` is a regular file AND the target file already exists? Error out with a message naming both files, exit non-zero, do not modify either file.

## Requirements *(mandatory)*

### Functional Requirements

- **FR-001**: `generate claude -w` MUST write generated config to the configured `claude_settings` target path (default: `~/.claude/settings.full.json`), not directly to `settings.json`.
- **FR-002**: `generate claude -w` MUST create a relative symlink from `~/.claude/settings.json` to the target file after writing.
- **FR-003**: `generate --yolo claude -w` MUST write to the yolo target path (configured or auto-derived) and symlink `settings.json` to it.
- **FR-004**: When `settings.json` exists as a regular file (not a symlink) and the target file does not exist, `generate -w` MUST move `settings.json` to the target path before updating, and inform the user via stdout. When both `settings.json` (regular file) and the target file exist, `generate -w` MUST error out with a message naming both files and exit non-zero without modifying either.
- **FR-005**: The symlink MUST use a relative path (e.g. `settings.full.json`, not `/Users/tom/.claude/settings.full.json`) when target and symlink are in the same directory.
- **FR-006**: When target and symlink are in different directories, the symlink MUST use an absolute path.
- **FR-007**: `twsrt init` MUST generate a comprehensive `config.toml` with `claude_settings = "~/.claude/settings.full.json"` and yolo targets as commented-out lines.
- **FR-008**: `twsrt init` MUST include `copilot_output` as a commented-out line with a descriptive comment.
- **FR-009**: Copilot generate/write behavior MUST remain unchanged (no symlinks).
- **FR-010**: `diff` commands MUST work correctly whether `settings.json` is a regular file or a symlink.
- **FR-011**: Parent directories for target files MUST be created if they do not exist.

### Key Entities

- **Symlink anchor**: `~/.claude/settings.json` — the fixed path Claude Code reads. Always a symlink after first `generate -w`.
- **Full target**: Configured via `claude_settings` in `config.toml` (default: `~/.claude/settings.full.json`). Contains deny + ask + allow rules.
- **Yolo target**: Configured via `claude_settings_yolo` or auto-derived. Contains deny + allow rules (no ask).

### Assumptions

- Target and symlink anchor (`settings.json`) are typically in the same directory (`~/.claude/`). Relative symlinks are preferred for portability.
- Users may switch between full and yolo modes multiple times. Each `generate -w` updates the symlink to point to the appropriate target.
- The `init` default changes from `~/.claude/settings.json` to `~/.claude/settings.full.json`. Existing users who have already run `init` will need to update their `config.toml` manually or re-run `init --force`.

## Success Criteria *(mandatory)*

### Measurable Outcomes

- **SC-001**: After `generate claude -w`, `settings.json` is always a symlink (never a regular file), verifiable via filesystem check.
- **SC-002**: Users can switch between full and yolo configs by running `generate claude -w` or `generate --yolo claude -w` — each run updates the symlink within 1 second.
- **SC-003**: Existing users with a regular `settings.json` are migrated on first `generate -w` run: moved to target if target doesn't exist (with informational message), or error if both exist.
- **SC-004**: All existing tests continue to pass (zero regressions).
- **SC-005**: `twsrt init` produces a config file that documents all available options without requiring the user to read external documentation.
