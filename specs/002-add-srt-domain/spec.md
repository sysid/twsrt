# Feature Specification: Edit Canonical Sources

**Feature Branch**: `002-add-srt-domain`
**Created**: 2026-02-22
**Status**: Draft
**Input**: User description: "Add an edit command to edit the canonical sources"

## User Scenarios & Testing *(mandatory)*

### User Story 1 - Edit SRT Settings (Priority: P1)

A user wants to add, remove, or modify entries in the canonical SRT settings file (e.g., add a new domain to `allowedDomains`). They run `twsrt edit srt` and their default editor opens the SRT settings file. They make changes, save, and close the editor.

**Why this priority**: Direct editing of the primary security source file is the core use case. Users need a quick way to reach the canonical file without remembering its path.

**Independent Test**: Can be fully tested by running `twsrt edit srt` and verifying the correct file opens in the editor.

**Acceptance Scenarios**:

1. **Given** a configured SRT settings path, **When** the user runs `twsrt edit srt`, **Then** the SRT settings file opens in the user's `$EDITOR`
2. **Given** no `$EDITOR` set, **When** the user runs `twsrt edit srt`, **Then** the system falls back to `$VISUAL`, then `vi`
3. **Given** the SRT settings file does not exist, **When** the user runs `twsrt edit srt`, **Then** the system reports an error with the expected file path

---

### User Story 2 - Edit Bash Rules (Priority: P2)

A user wants to edit the bash rules file. They run `twsrt edit bash` and their editor opens the bash-rules.json file.

**Why this priority**: Second canonical source, same mechanism, lower usage frequency.

**Independent Test**: Can be fully tested by running `twsrt edit bash` and verifying the correct file opens.

**Acceptance Scenarios**:

1. **Given** a configured bash rules path, **When** the user runs `twsrt edit bash`, **Then** the bash-rules.json file opens in the user's editor
2. **Given** the bash rules file does not exist, **When** the user runs `twsrt edit bash`, **Then** the system reports an error with the expected file path

---

### User Story 3 - Edit Without Argument (Priority: P3)

A user runs `twsrt edit` without specifying a source. The system shows available source names.

**Why this priority**: Discoverability convenience, not core functionality.

**Independent Test**: Can be fully tested by running `twsrt edit` with no argument and checking output.

**Acceptance Scenarios**:

1. **Given** the user runs `twsrt edit` with no argument, **When** the command executes, **Then** it shows available sources: `srt`, `bash`

---

### Edge Cases

- What happens when `$EDITOR` is empty and `$VISUAL` is empty? Falls back to `vi`.
- What happens when the editor command fails (non-zero exit)? Report the error to the user.
- What happens when the config file path is overridden via `--config`? The resolved paths from that config are used.

## Requirements *(mandatory)*

### Functional Requirements

- **FR-001**: System MUST provide an `edit` command that accepts a source name argument (`srt` or `bash`)
- **FR-002**: System MUST open the resolved canonical source file in the user's editor
- **FR-003**: System MUST resolve the editor from `$EDITOR`, falling back to `$VISUAL`, then `vi`
- **FR-004**: System MUST report an error if the specified source file does not exist, showing the expected path
- **FR-005**: System MUST respect the `--config` flag to resolve source file paths
- **FR-006**: System MUST show available source names when no argument is provided

### Key Entities

- **Canonical Source**: A security rule source file read by twsrt (SRT settings JSON, bash rules JSON). Identified by a short name (`srt`, `bash`) mapped to a file path via config.

## Success Criteria *(mandatory)*

### Measurable Outcomes

- **SC-001**: Users can open any canonical source file for editing in a single command
- **SC-002**: The edit command correctly resolves all configured source paths without requiring the user to know file locations
- **SC-003**: 100% of error cases (missing file, missing editor) produce actionable error messages
