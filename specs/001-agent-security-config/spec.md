# Feature Specification: Agent Security Config Generator

**Feature Branch**: `001-agent-security-config`
**Created**: 2026-02-22
**Status**: Draft
**Input**: User description: Utility to generate agent-specific security configurations from canonical sources for Claude Code, Copilot CLI, and future agents.

## Canonical Source Model

**Invariant: Canonical sources are NEVER written by twsrt.
Generated targets are NEVER hand-edited for security rules.**

Two canonical sources, one per security layer:

| Canonical Source | Security Layer | Governs | Why separate |
|-----------------|----------------|---------|--------------|
| SRT (`~/.srt-settings.json`) | OS-level (kernel syscalls) | Filesystem paths, network domains | Only SRT can block `cat ~/.aws/credentials` at OS level |
| Bash rules (`~/.twsrt/bash-rules.json`) | Agent-level (tool permissions) | Bash command deny/ask | SRT cannot distinguish `bash rm` from `bash git push` |

**Source/target separation — no file is both:**

```
CANONICAL SOURCES                      GENERATED TARGETS
(human edits, twsrt reads)             (twsrt writes, human never edits)
────────────────────────               ────────────────────────────────
~/.srt-settings.json                   ~/.claude/settings.json
  • filesystem.denyRead                  permissions.deny    — FULLY replaced
  • filesystem.allowWrite                permissions.ask     — FULLY replaced
  • filesystem.denyWrite                 permissions.allow   — SELECTIVE MERGE:
  • network.allowedDomains                 only WebFetch(domain:...) entries
                                           managed; all others preserved
~/.twsrt/bash-rules.json                sandbox.network     — FULLY replaced
                                         (no other sandbox keys are touched)
  • deny: ["rm", "sudo", ...]
  • ask:  ["git push", ...]            copilot-configured() flags
                                         --deny-tool / --allow-tool snippet
~/.twsrt/
  (config directory for                (future: pi-mono, etc.)
   future extensions)
```

**permissions.allow ownership model:**
- `WebFetch(domain:...)` entries — GENERATED from SRT allowedDomains
- Tool blanket allows (`Read`, `Glob`, `Grep`, etc.) — NOT managed, preserved
- Project-specific allows (`Bash(./gradlew:*)`, etc.) — NOT managed, preserved
- MCP tool allows (`mcp__*`) — NOT managed, preserved

**Data flow — each canonical rule maps to specific generated entries:**

```
SRT denyRead       → Claude Read/Write/Edit/MultiEdit(...) deny
SRT denyWrite      → Claude Write/Edit/MultiEdit(...) deny
SRT allowWrite     → Copilot --allow-tool 'read/write/edit'
                     (Claude: no mapping needed — blanket tool
                      allows already in permissions.allow;
                      SRT enforces OS-level write restriction)
SRT allowedDomains → Claude WebFetch(domain:...) allow
                   → Claude sandbox.network.allowedDomains
Bash deny rules    → Claude Bash(...) deny
                   → Copilot --deny-tool 'shell(...)'
Bash ask rules     → Claude Bash(...) ask
                   → Copilot --deny-tool 'shell(...)' (lossy)
```

## User Scenarios & Testing *(mandatory)*

### User Story 1 - Generate Claude Code Permissions (Priority: P1)

Tom edits SRT (`~/.srt-settings.json`) for filesystem/network
rules and maintains Bash deny/ask rules in
`~/.twsrt/bash-rules.json`. He runs twsrt to generate the Claude
Code `settings.json` permissions and sandbox.network sections.
The generated output merges both canonical sources into correctly
formatted `allow`, `deny`, and `ask` arrays with tool-specific
patterns, while preserving all non-security settings (hooks,
plugins, MCP permissions) in the target file.

**Why this priority**: Claude Code has the most complex permission
model (allow/deny/ask with glob patterns per tool). It is the
primary agent and the hardest to maintain manually. The Read/Write/
Edit/WebFetch deny/allow entries in settings.json are currently
hand-maintained duplicates of SRT rules — this duplication is
the core problem.

**Independent Test**: Run twsrt with an SRT config containing
filesystem deny rules and allowed domains, plus a
`~/.twsrt/bash-rules.json` with deny/ask entries. Verify the
output matches the expected Claude Code permissions format.

**Acceptance Scenarios**:

1. **Given** SRT with `denyRead: ["~/.aws", "~/.ssh"]`,
   **When** Tom runs twsrt to generate Claude Code config,
   **Then** the output contains `Read(**/.aws/**)`,
   `Write(**/.aws/**)`, `Edit(**/.aws/**)`,
   `MultiEdit(**/.aws/**)` (and same for `.ssh`) in the deny
   section — denyRead protects against ALL file tool access.

2. **Given** SRT with `allowWrite: [".", "/tmp"]`,
   **When** Tom runs twsrt to generate Claude Code config,
   **Then** no entries are generated for allowWrite — Claude
   already has blanket `Write`/`Edit`/`Read` allows in
   `permissions.allow`, and SRT enforces the OS-level write
   restriction. (Copilot generation uses allowWrite for
   `--allow-tool` flags.)

3. **Given** SRT with `allowedDomains: ["github.com", "*.github.com"]`,
   **When** Tom runs twsrt to generate Claude Code config,
   **Then** the output contains `WebFetch(domain:github.com)` in
   the allow section and both entries in
   `sandbox.network.allowedDomains`.

4. **Given** `~/.twsrt/bash-rules.json` with
   `deny: ["rm", "sudo", "git push --force"]`,
   **When** Tom runs twsrt to generate Claude Code config,
   **Then** the output contains `Bash(rm:*)`, `Bash(sudo:*)`, and
   `Bash(git push --force:*)` in the deny section.

5. **Given** `~/.twsrt/bash-rules.json` with
   `ask: ["git push", "git commit", "pip install"]`,
   **When** Tom runs twsrt to generate Claude Code config,
   **Then** the output contains `Bash(git push)`, `Bash(git push:*)`,
   `Bash(git commit)`, `Bash(git commit:*)`, and
   `Bash(pip install:*)` in the ask section.

6. **Given** SRT with `denyWrite: ["**/.env", "**/*.pem"]`,
   **When** Tom runs twsrt to generate Claude Code config,
   **Then** the output contains `Write(**/.env)`, `Edit(**/.env)`,
   `Write(**/*.pem)`, `Edit(**/*.pem)` in the deny section.

7. **Given** an existing `settings.json` with hooks, plugins,
   `mcp__*` tool permissions, and tool blanket allows
   (`Read`, `Glob`, `Grep`, `LS`, `Task`, `WebSearch`),
   **When** Tom runs twsrt to generate Claude Code config,
   **Then** `permissions.deny` and `permissions.ask` are fully
   replaced, `permissions.allow` has only its `WebFetch(domain:...)`
   entries replaced (all other allow entries preserved),
   `sandbox.network` is fully replaced, and all other settings
   (hooks, plugins, etc.) are preserved unchanged.

---

### User Story 2 - Generate Copilot CLI Flags (Priority: P2)

Tom runs twsrt to generate the `--allow-tool` and `--deny-tool`
flags for his Copilot CLI wrapper function, derived from the
same canonical sources.

**Why this priority**: Copilot's flag-based config is simpler than
Claude's but must stay in sync. Currently these flags are hardcoded
in a bash function (`copilot-configured()`), making drift
inevitable.

**Independent Test**: Run twsrt with SRT config and
`~/.twsrt/bash-rules.json`. Verify the output produces valid
Copilot CLI flags.

**Acceptance Scenarios**:

1. **Given** `~/.twsrt/bash-rules.json` with
   `deny: ["rm", "sudo", "git push --force"]`,
   **When** Tom runs twsrt to generate Copilot config,
   **Then** the output contains `--deny-tool 'shell(rm)'`,
   `--deny-tool 'shell(sudo)'`, and
   `--deny-tool 'shell(git push --force)'`.

2. **Given** SRT with `allowWrite: [".", "/tmp"]`,
   **When** Tom runs twsrt to generate Copilot config,
   **Then** the output contains `--allow-tool 'shell(*)'`,
   `--allow-tool 'read'`, `--allow-tool 'edit'`,
   `--allow-tool 'write'`.

3. **Given** `~/.twsrt/bash-rules.json` with
   `ask: ["git push", "pip install"]`,
   **When** Tom runs twsrt to generate Copilot config,
   **Then** these rules are mapped to `--deny-tool` entries since
   Copilot has no "ask" equivalent, and a warning is emitted
   about the lossy mapping.

---

### User Story 3 - Detect Configuration Drift (Priority: P3)

Tom suspects his existing agent configs have drifted from
what the canonical sources would generate. He runs twsrt in
diff mode to compare generated vs. existing configs.

**Why this priority**: Drift detection catches security gaps.
Lower priority because generation (US1-2) eliminates manual
maintenance, reducing drift at the source. But during
migration from hand-maintained configs, drift detection
validates that the generator produces correct output.

**Independent Test**: Place a known-drifted Claude settings.json
next to the canonical sources. Run twsrt diff and verify it
reports the specific differences.

**Acceptance Scenarios**:

1. **Given** an existing Claude settings.json missing a deny rule
   that SRT's denyRead would generate,
   **When** Tom runs twsrt in diff mode for Claude,
   **Then** the output reports the missing deny rule with
   the specific path and expected entry.

2. **Given** all generated configs matching the existing files,
   **When** Tom runs twsrt in diff mode,
   **Then** the output reports no drift and exits with status 0.

3. **Given** an existing Copilot wrapper with a deny-tool flag
   not present in the canonical Bash deny rules,
   **When** Tom runs twsrt in diff mode for Copilot,
   **Then** the output reports the extra rule as "not in
   canonical source".

---

### Edge Cases

- What happens when a Bash ask rule has no equivalent in a target
  agent? (e.g., Copilot has no "ask" concept)
  The tool MUST map it to deny (safe default) and warn about the
  lossy mapping.

- What happens when a path uses tilde (`~`) expansion?
  The tool MUST handle `~` consistently across all output formats,
  expanding or preserving as required by each agent's format.

- What happens when SRT denyRead and denyWrite overlap for the
  same path?
  This is valid — a path can be both deny-read and deny-write.
  The tool MUST generate deny entries for all applicable tools.

- What happens when a canonical source file is missing?
  The tool MUST report which file is missing and exit with a
  non-zero status. It MUST NOT generate partial configs silently.

- What happens when SRT contains fields unrelated to security
  rules (e.g., `enabled`, `allowPty`, `ignoreViolations`)?
  The tool MUST ignore these fields — they are SRT runtime
  settings, not security rules.

- What happens when the Claude settings.json contains entries
  NOT derivable from the canonical sources (e.g., `mcp__*`
  tool permissions, `additionalDirectories`, `hooks`)?
  The tool MUST preserve all non-managed entries. Within
  `permissions.allow`, only `WebFetch(domain:...)` entries are
  managed — tool blanket allows (`Read`, `Glob`, etc.),
  project-specific allows, and MCP allows are preserved.

- What happens when `~/.twsrt/` directory does not exist?
  The tool MUST report the missing directory and provide
  instructions to initialize it (e.g., `twsrt init`).

## Requirements *(mandatory)*

### Functional Requirements

- **FR-001**: System MUST read filesystem and network rules from
  SRT (`~/.srt-settings.json`) as the sole canonical source for
  path-based and domain-based security rules.

- **FR-002**: System MUST read Bash tool deny/ask rules from
  `~/.twsrt/bash-rules.json` as the canonical source for
  agent-level Bash command permissions.

- **FR-003**: System MUST use `~/.twsrt/` as its configuration
  directory for all twsrt-specific canonical sources and
  future configuration files.

- **FR-004**: System MUST generate Claude Code permissions in the
  format expected by `~/.claude/settings.json`, including `allow`,
  `deny`, and `ask` arrays with tool-specific patterns
  (`Read(...)`, `Write(...)`, `Edit(...)`, `MultiEdit(...)`,
  `WebFetch(domain:...)`, `Bash(...)`).

- **FR-005**: System MUST generate Copilot CLI flags as a
  text block with one `--allow-tool` or `--deny-tool` entry
  per line, suitable for embedding in a shell wrapper function.
  The output MUST NOT include the wrapper function itself
  (e.g., `copilot-configured()`, `srt -c` invocation) — only
  the security-relevant flags.

- **FR-006**: System MUST map SRT denyRead paths to Claude
  `Read(PATH)`, `Write(PATH)`, `Edit(PATH)`, and
  `MultiEdit(PATH)` deny entries with appropriate glob
  expansion. If a path is denied for reading, it MUST also
  be denied for writing — a path sensitive enough to block
  reading MUST NOT be writable.

- **FR-007**: System MUST map SRT denyWrite patterns to Claude
  `Write(PATTERN)`, `Edit(PATTERN)`, and `MultiEdit(PATTERN)`
  deny entries.

- **FR-008**: SRT allowWrite paths do NOT generate Claude Code
  permissions entries — Claude already has blanket tool allows
  and SRT enforces write restrictions at OS level. However,
  SRT allowWrite MUST be used to generate Copilot
  `--allow-tool 'read/write/edit'` flags.

- **FR-009**: System MUST map SRT allowedDomains to Claude
  `WebFetch(domain:DOMAIN)` allow entries and
  `sandbox.network.allowedDomains`.

- **FR-010**: System MUST map Bash deny rules to Claude
  `Bash(CMD:*)` deny entries and Copilot
  `--deny-tool 'shell(CMD)'` flags.

- **FR-011**: System MUST map Bash ask rules to Claude
  `Bash(CMD)` and `Bash(CMD:*)` ask entries, and to Copilot
  `--deny-tool` flags (lossy — with warning).

- **FR-012**: System MUST warn when a rule cannot be fully
  represented in a target agent's format (lossy mapping).

- **FR-013**: System MUST validate canonical sources on load
  and report specific errors before attempting generation.

- **FR-014**: System MUST support a diff mode that compares
  generated configs against existing files and reports drift.

- **FR-015**: System MUST handle tilde (`~`) paths consistently,
  expanding or preserving as each target format requires.

- **FR-016**: System MUST support generating config for a single
  target agent or all agents at once.

- **FR-017**: System MUST output generated configs to stdout by
  default, with an option to write directly to target files.

- **FR-018**: System MUST use selective merge for Claude Code's
  `settings.json`:
  - `permissions.deny` — FULLY replaced with generated entries
  - `permissions.ask` — FULLY replaced with generated entries
  - `permissions.allow` — SELECTIVE: only `WebFetch(domain:...)`
    entries are managed (added/removed); all other entries
    (tool blanket allows, project-specific allows, MCP tool
    allows) are preserved unchanged
  - `sandbox.network` — FULLY replaced with generated entries
  - All other settings (hooks, plugins, etc.) — preserved

- **FR-019**: System MUST NEVER write to canonical source files.
  Canonical sources are read-only inputs to the generator.

### Key Entities

- **Security Rule**: A single security intent with scope
  (read/write/execute/network), target paths or patterns, and
  enforcement level (block/prompt/allow).

- **Agent Profile**: A target agent (Claude Code, Copilot CLI)
  with its configuration format, supported enforcement levels,
  and output file path.

- **Canonical Source**: A file that authoritatively defines
  security rules for its domain. SRT for filesystem/network,
  `~/.twsrt/bash-rules.json` for Bash tool permissions.
  Canonical sources are read-only to twsrt.

- **Generated Config**: An agent-specific configuration file or
  snippet produced by transforming canonical rules into the
  target agent's format. Generated configs are write-only
  targets — never treated as inputs.

- **Rule Mapping**: The translation logic between a canonical
  rule and an agent-specific representation, including any lossy
  transformations.

- **Config Directory** (`~/.twsrt/`): The directory containing
  all twsrt-specific configuration files. Provides a namespace
  for future extensions without polluting the home directory.

## Assumptions

- pi-mono is out of scope for MVP since it currently has no
  configuration mechanism. The architecture MUST allow adding
  new agent profiles later.

- The tool is a CLI utility invoked from the terminal.

- SRT (`~/.srt-settings.json`) is a canonical INPUT, not a
  generated output. The tool reads SRT but NEVER writes to it.

- `~/.twsrt/bash-rules.json` is a canonical INPUT, not a
  generated output. The tool reads it but NEVER writes to it.

- The tool does NOT restart or reload agents after generating
  configs — that is the user's responsibility.

- Copilot's `--allow-tool`/`--deny-tool` flags do not support
  path-level granularity for read/write/edit. The tool generates
  broad allow/deny without path restrictions for Copilot.

- The existing permission rules in `settings.json` and
  `copilot-configured()` represent the desired security posture.
  A one-time migration extracts the current Bash deny/ask rules
  from `settings.json` into `~/.twsrt/bash-rules.json`.

- When writing to Claude's `settings.json`, the tool fully
  replaces `permissions.deny`, `permissions.ask`, and
  `sandbox.network`. Within `permissions.allow`, only
  `WebFetch(domain:...)` entries are managed — all other
  allow entries are preserved.

## Clarifications

### Session 2026-02-22

- Q: How should twsrt handle `permissions.allow` in Claude's settings.json, given it contains both generated entries (WebFetch domains) and non-generated entries (Read, Glob, Grep, MCP tools, project-specific allows)? → A: Selective merge — twsrt only manages `WebFetch(domain:...)` entries within `permissions.allow`; all other entries are preserved unchanged.
- Q: Should SRT denyRead paths also generate Write/Edit/MultiEdit deny entries, not just Read deny? → A: Yes — denyRead MUST generate deny for ALL file tools (Read + Write + Edit + MultiEdit). If a path is denied for reading, writing to it must also be blocked.
- Q: Should Copilot output be the complete bash function, the full `srt -c` command, or just the flags? → A: Flags-only snippet — one `--deny-tool`/`--allow-tool` per line, ready for embedding. The wrapper function contains non-security logic that twsrt should not manage.
- Correction: `sandbox.filesystem.write.allowOnly` does not exist in Claude's settings.json. SRT `allowWrite` does not generate any Claude permissions entries — Claude already has blanket tool allows, and SRT enforces write restrictions at OS level. twsrt MUST NOT add new keys to the settings.json `sandbox` section beyond `sandbox.network`.

## Success Criteria *(mandatory)*

### Measurable Outcomes

- **SC-001**: User can update security rules in canonical sources
  and generate all agent configs in under 10 seconds.

- **SC-002**: Generated Claude Code permissions produce the same
  security enforcement as the current hand-maintained config for
  the same rule set.

- **SC-003**: Generated Copilot flags produce the same deny
  coverage as the current handcrafted `copilot-configured()`
  function.

- **SC-004**: Drift detection correctly identifies 100% of
  rule discrepancies between generated and existing agent
  config files.

- **SC-005**: Zero security rules are lost during generation —
  every canonical rule maps to at least one enforcement in every
  supported agent (with warnings for lossy mappings).

- **SC-006**: Non-generated content in target config files
  (hooks, plugins, MCP permissions) is preserved across
  regeneration cycles.
