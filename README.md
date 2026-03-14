<p align="center">
  <img src="doc/logo_twsrt_300x300.png" alt="twsrt logo" width="300">
</p>


Agent security configuration generator — translates canonical security rules into agent-specific configs.

## The Problem

AI coding agents (Claude Code, Copilot CLI, etc.) each have their own permission model and
configuration format. Maintaining security rules independently per agent leads to configuration
drift, and coverage gaps.

Meanwhile, Anthropic's [Sandbox Runtime Tool
(SRT)](https://github.com/anthropic-experimental/sandbox-runtime) enforces OS-level restrictions
(filesystem deny, network allowlists) for Bash commands via kernel sandboxing. But SRT cannot
control an agent's built-in tools (Read, Write, Edit, WebFetch) — those run inside the agent's own
process.

## The Solution: Defense in Depth

`twsrt` tries to bridge the gap. It reads the same SRT policy that enforces OS-level Bash
restrictions and translates it into application-level rules for every agent's built-in tools:

```
                CANONICAL SOURCES (human-maintained)
                ====================================
                ~/.srt-settings.json        — OS-level sandbox rules
                ~/.config/twsrt/bash-rules.json — command deny/ask rules
                          |
                          v
                +-----------------+
                |      twsrt      |  deterministic translation
                |   (generator)   |  + drift detection
                +--------+--------+
                         |
            +------------+------------+
            v            v            v
     Claude Code    Copilot CLI    (future agents)
     settings.json  --flag args

                ENFORCEMENT LAYERS
                ==================
     Layer 1 (OS):  SRT sandbox — kernel-level deny (Bash only)
     Layer 2 (App): Agent permissions — tool-level deny/ask (all tools)
```

This gives you **two layers** for the most dangerous attack vector (Bash commands accessing
credentials or network) and **one consistent layer** for built-in tools — all generated from a
single source of truth.

| Access Path | SRT (Layer 1) | Agent Permissions (Layer 2) | Depth |
|---|---|---|---|
| `Bash(cat ~/.aws/credentials)` | Kernel-enforced deny | Tool-level deny | Two layers |
| `Read(~/.aws/credentials)` | Not covered | Tool-level deny | One layer |
| `Bash(curl evil.com)` | Network proxy blocks | Tool-level deny | Two layers |
| `WebFetch(evil.com)` | Not covered | Tool-level allow check | One layer |


You then start your agent either with SRT builtin (e.g. claude-code, pi-mono via extenstion) or with `srt` as
wrapper, e.g. copilot-cli.

```bash
srt -c "copilot \
    --allow-tool 'shell(*)' \
    --allow-tool 'read' \
    --allow-tool 'edit' \
    --allow-tool 'write' \
    --deny-tool 'shell(rm)' \
    --deny-tool 'shell(rmdir)' \
    --deny-tool 'shell(dd)' \
    --deny-tool 'shell(mkfs)' \
    ...
```

For the full security analysis and threat model see [SECURITY_CONCEPT.md](SECURITY_CONCEPT.md).

## Overview

`twsrt` reads two canonical sources:

- **SRT settings** (`~/.srt-settings.json`) — filesystem read/write deny rules, write allow rules, network domain allowlists
- **Bash rules** (`~/.config/twsrt/bash-rules.json`) — command deny/ask rules for Bash execution

It generates security configurations for:

- **Claude Code** (`~/.claude/settings.json`) — permissions.deny, permissions.ask, permissions.allow, sandbox.network
- **Copilot CLI** — `--allow-tool` and `--deny-tool` flag snippets

**Key invariant**: Source files are never written by twsrt. Target managed sections are never hand-edited.

### Installation

```bash
# Install as editable uv tool
make install

# Or via pip
pip install twsrt
```

### Usage

#### Initialize config directory

```bash
twsrt init                    # Creates ~/.config/twsrt/ with config.toml + bash-rules.json
twsrt init --force            # Overwrite existing files
```

#### Generate agent configs

```bash
twsrt generate claude         # Print Claude Code permissions to stdout
twsrt generate copilot        # Print Copilot CLI flags to stdout
twsrt generate                # Generate for all agents

twsrt generate claude --write # Write to ~/.claude/settings.json (selective merge)
twsrt generate claude -n -w   # Dry run: show what would be written
```

#### YOLO mode

YOLO mode generates deny-only configs — no `ask` rules. Use this with Claude's
`--dangerously-skip-permissions` or Copilot's `--yolo` (`--allow-all`) flag.
Deny rules still override the permissive mode in both agents.

```bash
twsrt generate --yolo claude         # Claude: JSON with permissions.deny only (no ask key)
twsrt generate --yolo copilot        # Copilot: --yolo flag + --deny-tool/--deny-url only
twsrt generate --yolo claude --write # Write to settings.yolo.json (selective merge)

twsrt diff --yolo claude             # Compare against settings.yolo.json
twsrt diff --yolo                    # Check all yolo configs
```

Target files default to inserting `.yolo` before the extension (e.g.
`settings.json` → `settings.yolo.json`). Override with explicit paths in
`config.toml` (see [Configuration](#configuration)).

#### Edit canonical sources

```bash
twsrt edit srt                # Open ~/.srt-settings.json in $EDITOR
twsrt edit bash               # Open ~/.config/twsrt/bash-rules.json in $EDITOR
twsrt edit                    # Show available sources
```

#### Detect configuration drift

```bash
twsrt diff claude             # Compare generated vs existing settings.json
twsrt diff                    # Check all agents
```

Exit codes: `0` = no drift, `1` = drift detected, `2` = missing file.

#### Typical workflow

```bash
twsrt edit srt                # Add a domain to allowedDomains
twsrt generate claude         # Preview the change
twsrt generate claude --write # Apply (selective merge preserves hooks, MCP, etc.)
twsrt diff claude             # Verify: exit 0 = no drift
```


## Copilot Configuration (`generate copilot -w`)

**Target file**: `copilot_output` from `config.toml` (stdout if omitted)
**Write behavior**: Full overwrite of target file

Copilot has no settings file — it uses CLI flags. `twsrt generate copilot` produces a
line-continuation block you paste into your launch command:

```
--allow-tool 'shell(*)' \
--allow-tool 'read' \
--allow-tool 'edit' \
--allow-tool 'write' \
--deny-tool 'shell(rm)' \
--deny-tool 'shell(sudo)' \
--allow-url 'github.com' \
--allow-url '*.github.com' \
```

With `-w` the entire target file is replaced — there is no merge logic.

**Lossy mappings**: Copilot has no `ask` equivalent. Bash ask rules are mapped to
`--deny-tool` with a stderr warning. `allowWrite` rules emit `--allow-tool` flags
(shell, read, edit, write). Network deny rules emit `--deny-url`.

**YOLO mode** (`generate --yolo copilot`): Outputs `--yolo` as first flag, followed
by `--deny-tool` and `--deny-url` only. No `--allow-*` flags (subsumed by `--yolo`),
no ASK-to-deny mapping (no warning). Deny rules take precedence over `--yolo`:

```
--yolo \
--deny-tool 'shell(rm)' \
--deny-tool 'shell(sudo)' \
--deny-url 'evil.com' \
```

## Claude Configuration (`generate claude -w`)

**Target file**: `~/.claude/settings.json`
**Write behavior**: Selective merge — twsrt owns specific sections and preserves everything else

With `-w`, twsrt reads the existing `settings.json`, updates only the sections it manages,
and writes the result back. Sections it does **not** manage (hooks, additionalDirectories,
MCP allows, blanket tool allows, etc.) are preserved untouched.

### Merge strategy per section

| Section | Strategy | Detail |
|---|---|---|
| `permissions.deny` | **Fully replaced** | All existing deny entries removed, replaced with generated ones |
| `permissions.ask` | **Fully replaced** | All existing ask entries removed, replaced with generated ones |
| `permissions.allow` | **Selective** | Only `WebFetch(domain:...)` entries replaced; all other allows preserved |
| `sandbox.network` | **Key-by-key merge** | Generated keys overwrite, unmanaged keys preserved |
| `sandbox.filesystem` | **Key-by-key merge** | Generated keys overwrite, unmanaged keys preserved |
| `sandbox.*` (top-level) | **Key-by-key merge** | `enabled`, `enableWeaker*`, `ignoreViolations` overwrite; Claude-only keys preserved |
| `hooks` | **Preserved** | Untouched |
| `additionalDirectories` | **Preserved** | Untouched |
| All other keys | **Preserved** | Untouched |

### Example: before and after `generate claude -w`

**Existing `~/.claude/settings.json`** (hand-maintained):

```json
{
  "permissions": {
    "deny": [
      "Bash(old-deny-entry)"
    ],
    "ask": [
      "Bash(old-ask-entry)"
    ],
    "allow": [
      "Read",
      "Glob",
      "Grep",
      "WebSearch",
      "Bash(npm test:*)",
      "mcp__memory__store",
      "WebFetch(domain:old.example.com)"
    ]
  },
  "hooks": {
    "PreToolUse": [
      { "matcher": "Bash", "hooks": [{ "type": "command", "command": "my-hook" }] }
    ]
  },
  "additionalDirectories": ["/home/user/other-project"],
  "sandbox": {
    "network": {
      "allowedDomains": ["old.example.com"],
      "allowLocalBinding": true
    },
    "autoAllowBashIfSandboxed": true,
    "excludedCommands": ["docker"]
  }
}
```

**After `twsrt generate claude -w`** (with SRT rules for `github.com`, `*.github.com`,
bash deny `rm`/`sudo`, bash ask `git push`, denyRead `~/.aws`):

```json
{
  "permissions": {
    "deny": [
      "Read(~/.aws)",
      "Read(~/.aws/**)",
      "Write(~/.aws)",
      "Write(~/.aws/**)",
      "Edit(~/.aws)",
      "Edit(~/.aws/**)",
      "MultiEdit(~/.aws)",
      "MultiEdit(~/.aws/**)",
      "Bash(rm)",
      "Bash(rm *)",
      "Bash(sudo)",
      "Bash(sudo *)"
    ],
    "ask": [
      "Bash(git push)",
      "Bash(git push *)"
    ],
    "allow": [
      "Read",
      "Glob",
      "Grep",
      "WebSearch",
      "Bash(npm test:*)",
      "mcp__memory__store",
      "WebFetch(domain:github.com)",
      "WebFetch(domain:*.github.com)"
    ]
  },
  "hooks": {
    "PreToolUse": [
      { "matcher": "Bash", "hooks": [{ "type": "command", "command": "my-hook" }] }
    ]
  },
  "additionalDirectories": ["/home/user/other-project"],
  "sandbox": {
    "network": {
      "allowedDomains": ["github.com", "*.github.com"],
      "allowLocalBinding": true
    },
    "autoAllowBashIfSandboxed": true,
    "excludedCommands": ["docker"]
  }
}
```

**YOLO mode** (`generate --yolo claude -w`): Same selective merge, but the `permissions.ask`
key is removed entirely. Deny rules still apply — Claude's `--dangerously-skip-permissions`
does not override deny entries. Target defaults to `settings.yolo.json`.

**What changed** (twsrt-managed) vs **what didn't** (user-managed):

```
  permissions.deny          ← REPLACED (old-deny-entry gone, new rules from SRT + bash-rules)
  permissions.ask           ← REPLACED (old-ask-entry gone, new rules from bash-rules)
  permissions.allow
    ├─ Read, Glob, ...      ← PRESERVED (not WebFetch entries)
    ├─ Bash(npm test:*)     ← PRESERVED (not WebFetch entries)
    ├─ mcp__memory__store   ← PRESERVED (not WebFetch entries)
    └─ WebFetch(domain:...) ← REPLACED (old.example.com gone, github.com added)
  hooks                     ← PRESERVED (untouched)
  additionalDirectories     ← PRESERVED (untouched)
  sandbox.network
    ├─ allowedDomains       ← REPLACED (managed by twsrt)
    └─ allowLocalBinding    ← PRESERVED (was already there, merge keeps it)
  sandbox.autoAllowBash...  ← PRESERVED (Claude-only key, invisible to twsrt)
  sandbox.excludedCommands  ← PRESERVED (Claude-only key, invisible to twsrt)
```

## Configuration

[SRT](https://github.com/anthropic-experimental/sandbox-runtime) is a dependency and needs to be
installed separately.

> GOTCHA: [sandbox write allowlist being hardcoded](https://github.com/anthropics/claude-code/issues/10377#issuecomment-3468689124)

### `~/.srt-settings.json` (SRT — prerequisite)

SRT configuration is the primary
canonical source that defines OS-level enforcement boundaries. **twsrt** reads it to
generate matching agent-level rules:

```json
{
  "filesystem": {
    "denyRead":  ["~/.aws", "~/.ssh", "~/.gnupg", "~/.netrc"],
    "denyWrite": ["**/.env", "**/*.pem", "**/*.key", "**/secrets/**"],
    "allowWrite": [".", "/tmp", "~/dev"]
  },
  "network": {
    "allowedDomains": [
      "github.com", "*.github.com",
      "pypi.org", "*.pypi.org",
      "registry.npmjs.org"
    ]
  }
}
```

Comprehensive example: 
[.srt-settings.json](example/.srt-settings.json)


### `~/.config/twsrt/config.toml`

Minimal config (generated by `twsrt init`):

```toml
[sources]
srt = "~/.srt-settings.json"
bash_rules = "~/.config/twsrt/bash-rules.json"

[targets]
claude_settings = "~/.claude/settings.json"
```

Full config with all optional keys:

```toml
[sources]
srt = "~/.srt-settings.json"
bash_rules = "~/.config/twsrt/bash-rules.json"

[targets]
claude_settings = "~/.claude/settings.json"
copilot_output = "~/.config/twsrt/copilot-flags.txt"    # optional, stdout if omitted

# YOLO target overrides (optional — defaults to inserting .yolo before extension)
# claude_settings_yolo = "~/.claude/settings.yolo.json"
# copilot_output_yolo = "~/.config/twsrt/copilot-flags.yolo.txt"
```

### `~/.config/twsrt/bash-rules.json`

```json
{
  "deny": ["rm", "sudo", "git push --force"],
  "ask": ["git push", "git commit", "pip install"]
}
```
Comprehensive example:
[bash-rules.json](example/bash-rules.json)


## Rule and Security Mappings
### Rule Mapping

| SRT / Bash Rule | Claude Code | Copilot CLI |
|-----------------|-------------|-------------|
| denyRead directory | Tool(path) + Tool(path/**) in deny | (SRT enforces) |
| denyRead file | Tool(path) in deny | (SRT enforces) |
| denyWrite pattern | Write/Edit/MultiEdit in deny | (SRT enforces) |
| allowWrite path | (no output) | --allow-tool flags |
| allowedDomains domain | WebFetch(domain:X) in allow + sandbox.network | (SRT enforces) |
| deniedDomains domain | WebFetch(domain:X) in deny | --deny-url |
| Bash deny cmd | Bash(cmd) + Bash(cmd *) in deny | --deny-tool 'shell(cmd)' |
| Bash ask cmd | Bash(cmd) + Bash(cmd *) in ask | --deny-tool (lossy, warns) |

**YOLO mode differences**: Bash ask rules are skipped entirely. Copilot `--allow-*`
flags are omitted (subsumed by `--yolo`). Claude `permissions.ask` key is removed.

Where Tool = Read, Write, Edit, MultiEdit. Directory vs file detection uses the
filesystem at generation time; glob patterns and unknown paths are treated as
bare patterns (no `/**` suffix for globs, `/**` added for unknown paths).

### Sandbox Key Mapping

Claude Code's `sandbox` section has 17 configurable keys. twsrt manages a subset of them
(sourced from `.srt-settings.json`) and never touches the rest:

| Claude Code Key | SRT Source | Status |
|---|---|---|
| `sandbox.network.allowedDomains` | `network.allowedDomains` | **Managed** |
| `sandbox.network.deniedDomains` | `network.deniedDomains` | **Managed** |
| `sandbox.network.allowLocalBinding` | `network.allowLocalBinding` | **Managed** (pass-through) |
| `sandbox.network.allowUnixSockets` | `network.allowUnixSockets` | **Managed** (pass-through) |
| `sandbox.network.allowAllUnixSockets` | `network.allowAllUnixSockets` | **Managed** (pass-through) |
| `sandbox.network.httpProxyPort` | `network.httpProxyPort` | **Managed** (pass-through) |
| `sandbox.network.socksProxyPort` | `network.socksProxyPort` | **Managed** (pass-through) |
| `sandbox.filesystem.allowWrite` | `filesystem.allowWrite` | **Managed** (pass-through) |
| `sandbox.filesystem.denyWrite` | `filesystem.denyWrite` | **Managed** (pass-through) |
| `sandbox.filesystem.denyRead` | `filesystem.denyRead` | **Managed** (pass-through) |
| `sandbox.enabled` | `enabled` | **Managed** (pass-through) |
| `sandbox.enableWeakerNetworkIsolation` | `enableWeakerNetworkIsolation` | **Managed** (pass-through) |
| `sandbox.enableWeakerNestedSandbox` | `enableWeakerNestedSandbox` | **Managed** (pass-through) |
| `sandbox.ignoreViolations` | `ignoreViolations` | **Managed** (pass-through) |
| `sandbox.excludedCommands` | *(no SRT source)* | **Claude-only** — never generated, never removed |
| `sandbox.autoAllowBashIfSandboxed` | *(no SRT source)* | **Claude-only** — never generated, never removed |
| `sandbox.allowUnsandboxedCommands` | *(no SRT source)* | **Claude-only** — never generated, never removed |

**Pass-through** keys are copied verbatim from SRT to Claude settings without transformation.
If a key is absent from SRT, it is omitted from generated output (never set to a default).

**Claude-only** keys exist only in Claude Code's schema and have no SRT equivalent.
`twsrt generate` never creates them, and `twsrt generate --write` preserves them via
selective merge. They are invisible to twsrt.

## Development

```bash
make test              # Run tests
make lint              # Ruff lint
make format            # Ruff format
make ty                # Type check with ty
make static-analysis   # All of the above
```
