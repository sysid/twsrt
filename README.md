<p align="left">
  <img src="doc/twsrt-logo.png" width="300" />
</p>

Agent security configuration generator — translates canonical security rules into agent-specific configs.

## The Problem

AI coding agents (Claude Code, Copilot CLI, Codex, ...) each have their own permission
model and configuration format. Maintaining security rules per agent by hand leads to
configuration drift and coverage gaps.

Kernel sandboxes close part of the gap: [Anthropic Sandbox Runtime](https://github.com/anthropic-experimental/sandbox-runtime)
(SRT) — and by now each agent's own native sandbox — enforce OS-level filesystem and
network restrictions. **But a sandbox guards the process boundary: it covers the
commands an agent spawns.** An agent's built-in tools (Read, Write, Edit, WebFetch)
run *inside the agent's own process* and are **not** covered by a command-scoped
sandbox. The exceptions: wrapping the entire agent process (`srt -c "copilot ..."`),
or an agent like Codex that executes its work through sandboxed subprocesses.

## Solution: One Canonical Policy, Compiled per Agent

**The guiding idea — the Durable Core.** One canonical statement of
restrictions — *paths no agent may read or write, plus domains agents may
reach* — compiled into each agent's **native kernel sandbox** config. This
translation is high-fidelity for every agent (they all natively express
deny-paths and domains) and survives the churn of per-agent permission
models. Everything else twsrt emits — bash deny/ask rules, copilot flags —
is a per-agent best-effort **supplement**: valuable where it is the only
control (built-in tools running inside the agent process), but never the
foundation.

```
     DURABLE CORE  (kernel-enforced, high-fidelity everywhere)
       deny-paths + domains ──► Claude sandbox.* / Codex profile / SRT wrapper

     SUPPLEMENT    (app-enforced, best-effort, per-agent semantics)
       bash deny/ask rules  ──► Claude permissions / Copilot flags / Codex .rules
```

How it flows from canonical sources to agents:

```
                CANONICAL SOURCES (human-maintained)
                ====================================
                ~/.srt-settings.json        — OS-level sandbox rules (SRT)
                ~/.config/twsrt/bash-rules.json — APP-level deny/ask rules
                          |
                          v
                +-----------------+
                |      twsrt      |  deterministic translation
                |   (generator)   |  + drift detection
                +--------+--------+
                         |
            +------------+------------+
            v            v            v
     Claude Code    Copilot CLI       Codex
     settings.json  --flag args       config.toml + .rules


                ENFORCEMENT LAYERS
                ==================
     Layer 1 (OS):  kernel sandbox (SRT wrapper or agent-native)
                    — covers spawned commands, NOT built-in tools
     Layer 2 (App): agent permission rules — deny/ask for all tools,
                    the only control over built-in tools in-process
```

Commands get two layers of protection (kernel + app); built-in tools get one
(app rules only) — all generated from a **single source of truth** (see
[Security Boundaries & Invariants](#security-boundaries--invariants)).

How the two layers collaborate:


| Access Path | Kernel Sandbox (Layer 1) | Agent Permissions (Layer 2) | Depth |
|---|---|---|---|
| `Bash(cat ~/.aws/credentials)` | Kernel-enforced deny | Tool-level deny | Two layers |
| `Read(~/.aws/credentials)` | Not covered (in-process tool) | Tool-level deny | One layer |
| `Bash(curl evil.com)` | Network proxy blocks | Tool-level deny | Two layers |
| `WebFetch(evil.com)` | Not covered (in-process tool) | Tool-level allow check | One layer |


![demo](./doc/demo.gif)

For the full security analysis and threat model see [SECURITY_CONCEPT.md](SECURITY_CONCEPT.md).

For the pi-mono integration see [pi-extensions/sandbox](https://github.com/sysid/pi-extensions/tree/main/packages/sandbox).

## Overview

`twsrt` reads canonical rule configuration sources:

1. **SRT settings** (`~/.srt-settings.json`) — OS-level enforced sandbox rules
2. **Bash rules** (`~/.config/twsrt/bash-rules.json`) — APP-level enforced deny/ask rules for Bash tool execution

It generates security configurations for:

- **Claude Code** (`~/.claude/settings.json`) — permissions + sandbox configuration
- **Copilot CLI** — `--allow-tool` / `--deny-tool` flag snippets for the copilot
  launch command
- **Codex** (`~/.codex/config.toml` + `~/.codex/rules/twsrt.rules`) — a native
  user-level permission profile plus optional escalation rules

**Key invariant**: Only the canonical sources are edited by the user. Generated
agent configs are compiled artifacts — never edit their managed sections by
hand; `twsrt diff` detects drift in both directions.


### Usage

```bash
pip install twsrt

#### Initialize config directory
twsrt init                    # Creates ~/.config/twsrt/ with config.toml + bash-rules.json
twsrt init --force            # Overwrite existing files

#### Generate agent configs
twsrt generate claude         # Print Claude Code permissions to stdout
twsrt generate copilot        # Print Copilot CLI flags to stdout
twsrt generate codex          # Preview Codex profile + escalation rules
twsrt generate                # Generate for all agents

twsrt generate claude --write # Write to settings.full.json, symlink settings.json → it
twsrt generate claude -n -w   # Dry run: show what would be written
twsrt generate codex --write  # Merge profile and write twsrt.rules

#### Edit canonical sources
twsrt edit srt                # Open ~/.srt-settings.json in $EDITOR
twsrt edit bash               # Open ~/.config/twsrt/bash-rules.json in $EDITOR
twsrt edit                    # Show available sources

#### Detect configuration drift
twsrt diff claude             # Compare generated vs existing target file
twsrt diff codex              # Compare owned profile + twsrt.rules
twsrt diff                    # Check all agents
twsrt diff --yolo             # Compare against yolo-specific config files
```

Exit codes: `0` = no drift, `1` = drift detected, `2` = missing file.

`diff` compares a **freshly generated config** (from your current SRT + bash rule sources)
against the **existing agent config file on disk**:

```
  Canonical sources                          Agent config on disk
  (SRT rules + bash rules)                   (e.g. settings.full.json)
          |                                           |
          v                                           v
    [ generate in memory ]  ──── compare ────  [ read from disk ]
          |                                           |
          +--- missing: in generated but not on disk (rules not yet applied)
          +--- extra:   on disk but not in generated  (out-of-band edits)
```

This detects two kinds of drift: unapplied rule changes (you edited SRT/bash rules
but forgot to `generate --write`) and out-of-band modifications (someone edited the
agent config directly).

#### Typical workflow

```bash
twsrt edit srt                # Add a domain to allowedDomains
twsrt generate claude         # Preview the change
twsrt generate claude --write # Apply (selective merge preserves hooks, MCP, etc.)
twsrt diff claude             # Verify: exit 0 = no drift
```


## Copilot Configuration (`generate copilot -w`)

Copilot has no settings file — it uses CLI flags. `twsrt generate copilot` produces a
line-continuation code snippet you paste into your launch command:

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

**Lossy mapping**: Copilot has no `ask` tier, so ask rules are conservatively
mapped to `--deny-tool` (warned on stderr). `allowWrite` rules emit
`--allow-tool` flags (shell, read, edit, write); network deny rules emit
`--deny-url`.

**YOLO mode** (`generate --yolo copilot`): outputs `--yolo` as first flag,
followed by `--deny-tool` and `--deny-url` only. These flags are the only
app-layer control Copilot has, and nothing kernel-guards its tools —
**use YOLO only under an SRT wrapper**.

Deny rules take precedence over `--yolo`:

```
--yolo \
--deny-tool 'shell(rm)' \
--deny-tool 'shell(sudo)' \
--deny-url 'evil.com' \
```

Run copilot with sandbox `srt` as wrapper:

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

## Claude Configuration (`generate claude -w`)

**Target file**: `~/.claude/settings.full|yolo.json` (configured via `claude_settings` in config.toml)

**Symlink**: `~/.claude/settings.json` → `settings.full|yolo.json` (created/updated automatically)

With `-w`, twsrt writes to `settings.full|yolo.json` and creates a symlink from
`settings.json` to the target. 

If `settings.json` is a regular file (e.g. first run), it is moved to `settings.full|yolo.json`
automatically.

Claude Code ships a native sandbox (Seatbelt/bwrap) configured via the
`sandbox` section — it covers sandboxed Bash commands. Built-in tools (Read,
Write, Edit, WebFetch) run inside the agent process, *outside* that sandbox,
and are guarded only by the generated `permissions` rules (best-effort).

**Selective merge**: `twsrt` updates only specific sections and preserves everything else:
- hooks, additionalDirectories, MCP allows, blanket tool allows, etc. are untouched

### Merge strategy per section

| Section | Strategy | Detail |
|---|---|---|
| `permissions.deny` | **Fully replaced** | |
| `permissions.ask` | **Fully replaced** | |
| `permissions.allow` | **Selective** | Only `WebFetch(domain:...)` entries replaced; existing allows preserved |
| `sandbox.network` | **Key-by-key merge** | unmanaged keys preserved |
| `sandbox.filesystem` | **Key-by-key merge** | unmanaged keys preserved |
| `sandbox.*` (top-level) | **Key-by-key merge** | `enabled`, `enableWeaker*`, `ignoreViolations` overwrite; Claude-only keys preserved |
| `hooks` | **Preserved** | Untouched |
| `additionalDirectories` | **Preserved** | Untouched |
| All other keys | **Preserved** | Untouched |

### Example: before and after `generate claude -w`

**Existing `~/.claude/settings.full.json`** (hand-maintained):

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
      "Edit(~/.aws)",
      "Edit(~/.aws/**)",
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
section is removed.

Target defaults to `settings.yolo.json`.

Deny rules still apply — Claude's `--dangerously-skip-permissions` does not override deny entries.

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

## Codex Configuration (`generate codex -w`)

Codex ships its own always-on kernel sandbox. twsrt therefore compiles only
**restrictions** into a native permission profile named `twsrt`, selected via
`default_permissions`. The profile extends the built-in `:workspace` base
(workspace + tmp writable, `.git`/`.codex`/`.agents` protected) and adds:

- `denyRead` paths → filesystem `deny` (blocks Codex's default read-everything)
- `denyWrite` exact paths → `read`; `denyWrite` globs → `deny` (stricter,
  fail-safe — Codex cannot express read-only for globs; warned)
- `allowedDomains`/`deniedDomains` → network `domains` allowlist. The
  `domains` table is always emitted, even empty: an empty map blocks all
  domain traffic, matching SRT allowlist semantics.
- Exact Unix socket paths → `unix_sockets` allow entries

**Deliberately NOT compiled** (each skip is warned at generation time):

- **SRT `allowWrite` paths.** Codex's per-project trust model governs writes;
  compiling `~/dev`-style paths would make them writable in *every* session
  regardless of cwd, bypassing per-project trust and `.git` protection.
- **bash-rules `allow` commands.** In Codex, an `allow` execution rule means
  "run **outside the sandbox** without prompting" — auto-approved unsandboxed
  execution, strictly weaker than the default (prompt on every escalation).
- **bash-rules `ask` commands.** Codex already prompts for every
  out-of-sandbox request; restating the default adds bulk, not security.

`~/.codex/rules/twsrt.rules` thus contains only `deny` → `forbidden` prefix
rules (hard deny instead of prompt for sandbox-escape requests). These rules
govern **only requests to execute outside the sandbox** — a command running
inside the sandbox never consults them. Codex output is identical in yolo and
full mode.

The user-level targets require no root access:

- `~/.codex/config.toml` — selectively merged; only `default_permissions`,
  `approval_policy`, `approvals_reviewer`, `allow_login_shell`, and
  `[permissions.twsrt]` are owned by twsrt.
- `~/.codex/rules/twsrt.rules` — fully generated from `bash-rules.json`.
  **Optional**: generated only while `codex_rules` is set in config.toml;
  omit the key to skip escalation rules entirely and rely on Codex's default
  prompt-on-every-escalation (security delta: escalations prompt instead of
  hard-deny, and TUI-saved allowlist entries take effect).

Restart Codex after generation. Active sessions do not reload permission
profiles or `.rules` files.

> **WARNING — silent profile deactivation**: if a legacy `sandbox_mode` /
> `sandbox_workspace_write` setting appears in *any* loaded Codex config layer
> (managed, team, project, config profile) or `--sandbox` is passed on the CLI,
> Codex silently ignores `default_permissions` — no error is raised. twsrt
> fails fast only for the managed `config.toml` it owns and prints this
> reminder on every generate/diff. Run `codex doctor` after changing other
> layers. Note: Codex permission profiles are Beta and `.rules` files are
> Experimental upstream; expect churn.

All other Codex configuration is preserved, including projects, MCP servers,
headers, WebSearch, apps, and `shell_environment_policy`. Preview and diff
output contain only managed security data, so foreign credentials are never
printed.

Some SRT fields cannot be translated without widening access. Codex generation
therefore skips them with warnings: `allowLocalBinding`, socket directory
entries, integer proxy ports, Mach lookup, violation-reporting exceptions, and
weaker-isolation switches. A disabled canonical SRT sandbox or a malformed
`/~/...` path fails generation.

## Configuration

[SRT](https://github.com/anthropic-experimental/sandbox-runtime) is needed only
for wrapping a whole agent (e.g. `srt -c "copilot --yolo ..."`) — Claude Code
and Codex bring native sandboxes. Recommended fork with proxy and browser
support:

```bash
npm install -g @sysid/sandbox-runtime-improved
```

> GOTCHA: [sandbox write allowlist is hardcoded and currently cannot be managed in claude-code](https://github.com/anthropics/claude-code/issues/10377#issuecomment-3468689124)

### `~/.srt-settings.json` (SRT — prerequisite)

[SRT configuration](https://github.com/anthropic-experimental/sandbox-runtime?tab=readme-ov-file#configuration) is the canonical source that defines OS-level enforcement boundaries. 

**twsrt** reads it to generate equivalent agent-level rules:

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
claude_settings = "~/.claude/settings.full.json"
codex_config = "~/.codex/config.toml"
codex_rules = "~/.codex/rules/twsrt.rules"    # optional: omit to skip escalation rules
```

Full config with all optional keys:

```toml
[sources]
srt = "~/.srt-settings.json"
bash_rules = "~/.config/twsrt/bash-rules.json"

[targets]
claude_settings = "~/.claude/settings.full.json"
codex_config = "~/.codex/config.toml"
codex_rules = "~/.codex/rules/twsrt.rules"    # optional: omit to skip escalation rules
copilot_output = "~/.config/twsrt/copilot-flags.txt"    # optional, stdout if omitted

# YOLO target overrides (optional — defaults to inserting .yolo before extension)
# claude_settings_yolo = "~/.claude/settings.yolo.json"
# copilot_output_yolo = "~/.config/twsrt/copilot-flags.yolo.txt"

# Mode-specific sandbox overrides (applied after SRT values, take precedence)
[sandbox_overrides.yolo]
enabled = true
autoAllowBashIfSandboxed = true
allowUnsandboxedCommands = false

[sandbox_overrides.full]
enabled = false
```

Sandbox overrides let you enforce different sandbox postures per mode.
When `--yolo` is used, overrides from `[sandbox_overrides.yolo]` are applied;
otherwise `[sandbox_overrides.full]` is used. These override SRT-sourced values
and flow through selective merge to update existing settings files.

Typical use: `claude-yolo` enforces sandbox (safety net when skipping
permission prompts), while `claude-full` disables it (user approves each action
interactively).

### `~/.config/twsrt/bash-rules.json`

```json
{
  "allow": ["gh pr view"],
  "deny": ["rm", "sudo", "git push --force"],
  "ask": ["git push", "git commit", "pip install"]
}
```
Comprehensive example:
[bash-rules.json](example/bash-rules.json)


## Rule and Security Mappings
### Rule Mapping

| SRT / Bash Rule | Claude Code | Copilot CLI | Codex |
|-----------------|-------------|-------------|-------|
| denyRead directory | Tool(path) + Tool(path/**) in deny | (SRT enforces) | filesystem `deny` |
| denyRead file | Tool(path) in deny | (SRT enforces) | filesystem `deny` |
| denyWrite exact path | Edit(path) in deny | (SRT enforces) | filesystem `read` |
| denyWrite glob | Edit(pattern) in deny | (SRT enforces) | filesystem `deny` (stricter; warns) |
| allowWrite path | (no output) | --allow-tool flags | not compiled (Codex trust model; warns) |
| allowedDomains domain | WebFetch(domain:X) + sandbox.network | (SRT enforces) | domain `allow` |
| deniedDomains domain | WebFetch(domain:X) in deny | --deny-url | domain `deny` |
| Bash allow cmd | (no output) | (no output) | not compiled (would auto-approve unsandboxed; warns) |
| Bash deny cmd | Bash(cmd) + Bash(cmd *) in deny | --deny-tool 'shell(cmd)' | prefix `forbidden` |
| Bash ask cmd | Bash(cmd) + Bash(cmd *) in ask | --deny-tool (lossy, warns) | not compiled (Codex prompts by default; warns) |

**YOLO mode differences**: Bash ask rules are skipped entirely. Copilot `--allow-*`
flags are omitted (subsumed by `--yolo`). Claude `permissions.ask` key is removed.
Codex output is identical in yolo and full mode.

Where Tool = Read, Edit. Claude Code matches file permissions on `Edit(path)`
only — a single `Edit` rule covers every file-editing tool (Write, Edit,
NotebookEdit), so no separate `Write(path)` rule is emitted. Directory vs file
detection uses the filesystem at generation time; glob patterns and unknown
paths are treated as bare patterns (no `/**` suffix for globs, `/**` added for
unknown paths).

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
| `sandbox.autoAllowBashIfSandboxed` | *(no SRT source)* | **Claude-only** — preserved by default; overridable via `[sandbox_overrides]` |
| `sandbox.allowUnsandboxedCommands` | *(no SRT source)* | **Claude-only** — preserved by default; overridable via `[sandbox_overrides]` |

**Pass-through** keys are copied verbatim from SRT to Claude settings without transformation.
If a key is absent from SRT, it is omitted from generated output (never set to a default).

**Claude-only** keys exist only in Claude Code's schema and have no SRT equivalent.
By default `twsrt generate` never creates them, and `twsrt generate --write` preserves
them via selective merge. However, `[sandbox_overrides]` in config.toml can explicitly
set any sandbox key (including Claude-only keys like `autoAllowBashIfSandboxed`) per mode,
allowing different sandbox postures for yolo vs full mode.

## Security Boundaries & Invariants

What each agent actually enforces, where, and what twsrt deliberately does
not compile. This is the authoritative summary; details per agent above.

### Per-agent boundary matrix

| Boundary | Claude Code | Copilot CLI | Codex |
|---|---|---|---|
| Enforcement point | app permission engine | CLI flags (per-invoke) | sandbox profile + escalation rules |
| Built-in tools (Read/Edit/WebFetch) | in agent process, **outside** native sandbox — app rules only | in agent process — flags only, no kernel guard | work runs as sandboxed subprocesses — profile applies |
| File deny | best-effort tool deny | none (SRT only) | profile-enforced (all access) |
| ask tier | native | ABSENT → deny (lossy) | native default; not restated |
| allow tier | emitted | --allow-tool | NOT compiled (would unsandbox) |
| In-sandbox commands | Bash rules apply | rules apply | NOT governed by .rules |
| Pinned invariants | managed sections merge | (stateless) | default_permissions, approval_policy, approvals_reviewer, allow_login_shell |
| Known trap | allowWrite hardcoded ([#10377](https://github.com/anthropics/claude-code/issues/10377)) | ask→deny fidelity loss | sandbox_mode in ANY layer disables profile |

### How canonical sources compile per agent

`∅` = deliberately not compiled (with a generation-time warning where noted):

```
srt denyRead ────► claude deny(Read/Edit) ─► copilot ∅ (SRT) ──► codex fs "deny"
srt denyWrite ───► claude deny(Edit)      ─► copilot ∅ (SRT) ──► codex "read"/glob "deny" (warn)
srt allowWrite ──► claude ∅ (hardcoded!)  ─► copilot allow-*  ─► codex ∅ warn (trust model)
bash allow ──────► claude ∅               ─► copilot ∅        ─► codex ∅ warn (would unsandbox)
bash ask ────────► claude ask             ─► copilot deny warn ─► codex ∅ warn (default prompts)
bash deny ───────► claude deny            ─► copilot deny      ─► codex "forbidden" (escalation only)
```

### Invariants

1. **Canonical sources are the single source of truth.** Agent configs are
   compiled artifacts; `twsrt diff` detects both unapplied rule changes and
   out-of-band edits.
2. **twsrt never weakens an agent's default posture.** Lossy translations
   always narrow (Copilot ask→deny, Codex denyWrite-glob→deny) or skip with a
   warning (Codex allow/ask/allowWrite) — never widen.
3. **Selective merge owns only declared sections.** Everything else in a
   target file (hooks, MCP servers, projects, credentials) is preserved
   byte-for-byte where the format allows.
4. **Fail-safe on ambiguity.** Disabled canonical sandbox, malformed paths,
   and legacy Codex `sandbox_mode` in the managed file abort generation
   instead of guessing.

### Scope & Roadmap

All three agents now ship native OS sandboxes (Claude Code: built-in
Seatbelt/bwrap, opt-in; Copilot CLI: local sandbox in public preview; Codex:
kernel sandbox always-on) — the [Durable Core](#solution-one-canonical-policy-compiled-per-agent)
compiles into each of them. The bash-rules app layer is the per-agent
best-effort supplement:

- **Bash-rules translation is Claude-primary and frozen for new agents.**
  Claude gets full deny/ask fidelity (tool-level gate); Copilot keeps
  deny-only flags (deny takes precedence over `--yolo` — the only app-layer
  control in yolo mode); Codex gets forbidden-only escalation rules. New
  agents get restrictions-only compilation by default.
- **Copilot native sandbox** (`sandbox` key in Copilot settings.json) is the
  intended future replacement for the flag-snippet generator — deferred while
  the feature is in public preview (backend undocumented, subject to change).
  See `thoughts/tickets/2026-07-18-copilot-native-sandbox-target.md`.

## Development

```bash
make test              # Run tests
make lint              # Ruff lint
make format            # Ruff format
make ty                # Type check with ty
make static-analysis   # All of the above
```
