# Data Model: Agent Security Config Generator

**Feature**: 001-agent-security-config
**Date**: 2026-02-22

## Entities

### SecurityRule

A single security intent extracted from a canonical source.

| Field | Type | Description |
|-------|------|-------------|
| scope | `Scope` enum | `READ`, `WRITE`, `EXECUTE`, `NETWORK` |
| action | `Action` enum | `DENY`, `ASK`, `ALLOW` |
| pattern | `str` | Path glob, command pattern, or domain |
| source | `Source` enum | `SRT_FILESYSTEM`, `SRT_NETWORK`, `BASH_RULES` |

**Validation rules**:
- `pattern` must not be empty
- `scope=NETWORK` requires `action=ALLOW` (domains are allowlisted)
- `scope=EXECUTE` requires `source=BASH_RULES`
- `scope=READ` or `scope=WRITE` requires `source=SRT_FILESYSTEM`

**Derivation from canonical sources**:

```
SRT denyRead entry   → SecurityRule(READ, DENY, pattern, SRT_FILESYSTEM)
SRT denyWrite entry  → SecurityRule(WRITE, DENY, pattern, SRT_FILESYSTEM)
SRT allowWrite entry → SecurityRule(WRITE, ALLOW, pattern, SRT_FILESYSTEM)
SRT allowedDomains   → SecurityRule(NETWORK, ALLOW, domain, SRT_NETWORK)
Bash deny entry      → SecurityRule(EXECUTE, DENY, cmd, BASH_RULES)
Bash ask entry       → SecurityRule(EXECUTE, ASK, cmd, BASH_RULES)
```

### Scope (Enum)

```
READ      — file read access
WRITE     — file write access
EXECUTE   — command execution (Bash)
NETWORK   — network domain access
```

### Action (Enum)

```
DENY      — block unconditionally
ASK       — prompt user for confirmation
ALLOW     — permit (used for allowlists)
```

### Source (Enum)

```
SRT_FILESYSTEM  — from ~/.srt-settings.json filesystem section
SRT_NETWORK     — from ~/.srt-settings.json network section
BASH_RULES      — from ~/.config/twsrt/bash-rules.json
```

### AgentGenerator (Protocol)

Defines the translation interface that every agent generator must
implement. Uses `typing.Protocol` (PEP 544) for structural subtyping
— no inheritance required, just implement the methods.

| Member | Type | Description |
|--------|------|-------------|
| name | `str` (property) | Agent identifier: `"claude"`, `"copilot"` |
| generate | method | Translate rules into agent-specific config string |
| diff | method | Compare generated config against existing target |

**Method signatures**:

```python
class AgentGenerator(Protocol):
    @property
    def name(self) -> str: ...

    def generate(self, rules: list[SecurityRule], config: AppConfig) -> str:
        """Generate agent-specific config from security rules.

        Returns the generated config as a string (JSON fragment,
        flag list, etc. depending on agent format).
        Emits warnings to stderr for lossy mappings.
        """
        ...

    def diff(self, rules: list[SecurityRule], target: Path) -> DiffResult:
        """Compare generated config against existing target file.

        Returns DiffResult with missing/extra entries.
        """
        ...
```

**Implementations**:

| Class | Module | Agent |
|-------|--------|-------|
| `ClaudeGenerator` | `lib/claude.py` | Claude Code (`settings.json`) |
| `CopilotGenerator` | `lib/copilot.py` | Copilot CLI (flag snippet) |

**Registry** (in `lib/agent.py`):

```python
GENERATORS: dict[str, AgentGenerator] = {
    "claude": ClaudeGenerator(),
    "copilot": CopilotGenerator(),
}
```

The CLI resolves the `AGENT` argument against this dict. `"all"`
iterates all values.

### AppConfig

Application configuration loaded from `~/.config/twsrt/config.toml`.

| Field | Type | Default | Description |
|-------|------|---------|-------------|
| srt_path | `Path` | `~/.srt-settings.json` | Path to SRT settings |
| bash_rules_path | `Path` | `~/.config/twsrt/bash-rules.json` | Path to Bash rules |
| claude_settings_path | `Path` | `~/.claude/settings.json` | Claude target path |
| copilot_output_path | `Path \| None` | `None` (stdout) | Copilot output path |

### DiffResult

Result of comparing generated config against an existing file.

| Field | Type | Description |
|-------|------|-------------|
| agent | `str` | Agent name (`claude`, `copilot`) |
| missing | `list[str]` | Rules in generated but not in existing |
| extra | `list[str]` | Rules in existing but not in generated |
| matched | `bool` | True if no drift detected |

## Relationships

```
AppConfig ──loads──> SRT JSON ──parses──> list[SecurityRule]
AppConfig ──loads──> Bash JSON ──parses──> list[SecurityRule]

                    AgentGenerator (Protocol)
                    ├── ClaudeGenerator.generate()  ──> settings.json sections
                    └── CopilotGenerator.generate() ──> flag snippet

list[SecurityRule] ──AgentGenerator.generate()──> agent-specific config string
existing target    ──AgentGenerator.diff()─────> DiffResult

GENERATORS registry: {"claude": ClaudeGenerator, "copilot": CopilotGenerator}
CLI resolves AGENT arg ──lookup──> GENERATORS[agent].generate(rules, config)
```

## Rule Mapping Detail

### SecurityRule → Claude Code Entries

| Rule (scope, action) | Claude Output |
|----------------------|---------------|
| (READ, DENY, path) | `Read(**/{path}/**)`, `Write(**/{path}/**)`, `Edit(**/{path}/**)`, `MultiEdit(**/{path}/**)` in `permissions.deny` |
| (WRITE, DENY, pattern) | `Write({pattern})`, `Edit({pattern})`, `MultiEdit({pattern})` in `permissions.deny` |
| (WRITE, ALLOW, path) | No output — Claude has blanket tool allows; SRT enforces OS-level |
| (NETWORK, ALLOW, domain) | `WebFetch(domain:{domain})` in `permissions.allow` + domain in `sandbox.network.allowedDomains` |
| (EXECUTE, DENY, cmd) | `Bash({cmd})` and `Bash({cmd} *)` in `permissions.deny` |
| (EXECUTE, ASK, cmd) | `Bash({cmd})` + `Bash({cmd} *)` in `permissions.ask` |

### SecurityRule → Copilot CLI Flags

| Rule (scope, action) | Copilot Output |
|----------------------|----------------|
| (READ, DENY, path) | No direct mapping (SRT handles at OS level) |
| (WRITE, DENY, pattern) | No direct mapping (SRT handles at OS level) |
| (WRITE, ALLOW, path) | `--allow-tool 'shell(*)'`, `--allow-tool 'read'`, `--allow-tool 'edit'`, `--allow-tool 'write'` |
| (NETWORK, ALLOW, domain) | No direct mapping (SRT handles) |
| (EXECUTE, DENY, cmd) | `--deny-tool 'shell({cmd})'` |
| (EXECUTE, ASK, cmd) | `--deny-tool 'shell({cmd})'` (lossy — warn) |

## File Formats

### ~/.config/twsrt/bash-rules.json

```json
{
  "deny": ["rm", "sudo", "git push --force"],
  "ask": ["git push", "git commit", "pip install"]
}
```

### ~/.config/twsrt/config.toml

```toml
[sources]
srt = "~/.srt-settings.json"
bash_rules = "~/.config/twsrt/bash-rules.json"

[targets]
claude_settings = "~/.claude/settings.json"
# copilot_output = "~/.config/twsrt/copilot-flags.txt"  # optional, stdout if omitted
```
