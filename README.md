# twsrt

Agent security configuration generator — translates canonical security rules into agent-specific configs.

## Overview

`twsrt` reads two canonical sources:

- **SRT settings** (`~/.srt-settings.json`) — filesystem read/write deny rules, write allow rules, network domain allowlists
- **Bash rules** (`~/.twsrt/bash-rules.json`) — command deny/ask rules for Bash execution

It generates security configurations for:

- **Claude Code** (`~/.claude/settings.json`) — permissions.deny, permissions.ask, permissions.allow, sandbox.network
- **Copilot CLI** — `--allow-tool` and `--deny-tool` flag snippets

```
~/.srt-settings.json ──┐
                        ├──> twsrt ──┬──> ~/.claude/settings.json
~/.twsrt/bash-rules.json ──┘         └──> copilot CLI flags (stdout)
```

**Invariant**: Source files are never written by twsrt. Target files are never hand-edited for managed sections.

## Installation

```bash
# Install as editable uv tool
make install

# Or via pip
pip install twsrt
```

## Usage

### Initialize config directory

```bash
twsrt init                    # Creates ~/.twsrt/ with config.toml + bash-rules.json
twsrt init --force            # Overwrite existing files
```

### Generate agent configs

```bash
twsrt generate claude         # Print Claude Code permissions to stdout
twsrt generate copilot        # Print Copilot CLI flags to stdout
twsrt generate                # Generate for all agents

twsrt generate claude --write # Write to ~/.claude/settings.json (selective merge)
twsrt generate claude -n -w   # Dry run: show what would be written
```

### Detect configuration drift

```bash
twsrt diff claude             # Compare generated vs existing settings.json
twsrt diff                    # Check all agents
```

Exit codes: `0` = no drift, `1` = drift detected, `2` = missing file.

## Configuration

### `~/.twsrt/config.toml`

```toml
[sources]
srt = "~/.srt-settings.json"
bash_rules = "~/.twsrt/bash-rules.json"

[targets]
claude_settings = "~/.claude/settings.json"
# copilot_output = "~/.twsrt/copilot-flags.txt"  # optional, stdout if omitted
```

### `~/.twsrt/bash-rules.json`

```json
{
  "deny": ["rm", "sudo", "git push --force"],
  "ask": ["git push", "git commit", "pip install"]
}
```

## Rule Mapping

| SRT / Bash Rule | Claude Code | Copilot CLI |
|-----------------|-------------|-------------|
| denyRead path | Read/Write/Edit/MultiEdit in deny | (SRT enforces) |
| denyWrite pattern | Write/Edit/MultiEdit in deny | (SRT enforces) |
| allowWrite path | (no output) | --allow-tool flags |
| allowedDomains domain | WebFetch(domain:X) in allow + sandbox.network | (SRT enforces) |
| Bash deny cmd | Bash(cmd:*) in deny | --deny-tool 'shell(cmd)' |
| Bash ask cmd | Bash(cmd) + Bash(cmd:*) in ask | --deny-tool (lossy, warns) |

## Development

```bash
make test              # Run tests
make lint              # Ruff lint
make format            # Ruff format
make ty                # Type check with ty
make static-analysis   # All of the above
```
