<p align="left">
  <img src="doc/twsrt-logo.png" width="300" />
</p>

One security policy, compiled into the native permission and sandbox
configuration of every AI coding agent you run.

![demo](./doc/demo.gif)

## Contents

1. [What twsrt does](#what-twsrt-does)
2. [Install and quickstart](#install-and-quickstart)
3. [Concepts](#concepts)
4. [Configuration](#configuration)
5. [Commands](#commands)
6. [Claude Code target](#claude-code-target)
7. [Codex target](#codex-target)
8. [Copilot CLI target](#copilot-cli-target)
9. [Security model](#security-model)
10. [Development](#development)

Deep-dive tables and examples live in [doc/REFERENCE.md](doc/REFERENCE.md).
The threat model is in [SECURITY_CONCEPT.md](SECURITY_CONCEPT.md).

## What twsrt does

Claude Code, Codex, and Copilot CLI each have their own permission model and
config format. Maintaining "never read `~/.aws`, never run `sudo`, only reach
`github.com`" three times by hand drifts and leaves gaps.

twsrt keeps that policy in small JSONC fragments, composes them per profile
into strict canonical JSON, and derives each agent's native configuration
from the result:

```
 config.toml ──► resolve profile ──► parse JSONC ──► compose ──► validate
                                                                    │
                        ┌───────────────────────────────────────────┤
                        ▼                                           ▼
             compiled canonical JSON                     normalized rules
             ~/.srt-settings.json                                   │
             bash-rules.json                                        ▼
                                                     Claude settings.json
                                                     Codex config.toml + .rules
                                                     Copilot CLI flags
```

Two enforcement layers come out of it:

| Layer | Enforced by | Covers | Does not cover |
|---|---|---|---|
| Kernel sandbox | Claude native sandbox, Codex sandbox, or the [SRT](https://github.com/anthropic-experimental/sandbox-runtime) wrapper | Every command an agent spawns | Built-in tools (Read, Edit, WebFetch) that run inside the agent process |
| Agent permissions | Each agent's own rule engine | All tools, including built-in ones | Best-effort only; semantics differ per agent |

The kernel layer (deny paths and allowed domains) is the durable core and
translates with high fidelity everywhere. The bash deny/ask rules are a
per-agent supplement. Example:

| Access path | Kernel sandbox | Agent permissions |
|---|---|---|
| `Bash(cat ~/.aws/credentials)` | denied | denied |
| `Read(~/.aws/credentials)` | not covered (in-process) | denied |
| `Bash(curl evil.com)` | proxy blocks | denied |
| `WebFetch(evil.com)` | not covered (in-process) | allow check |

## Install and quickstart

```bash
uv tool install twsrt        # or: pip install twsrt

twsrt config --init          # writes ~/.config/twsrt/config.toml + starter fragments
twsrt config                 # opens config.toml in $EDITOR
$EDITOR ~/.config/twsrt/srt/base.jsonc     # deny paths, allowed domains
$EDITOR ~/.config/twsrt/bash/base.jsonc    # command deny / ask lists

twsrt generate claude        # preview what would be written
twsrt generate claude -w     # write ~/.claude/settings.full.json, point settings.json at it
twsrt diff                   # exit 0 when every target matches the fragments
```

A common launch pattern regenerates the active mode on every start:

```bash
claude-full() { twsrt generate -w claude; claude "$@"; }
claude-yolo() { twsrt generate --yolo -w claude; claude --allow-dangerously-skip-permissions "$@"; }
```

## Concepts

| Term | Meaning |
|---|---|
| Source kind | A canonical document type. Two exist: `srt` (filesystem and network policy) and `bash` (command allow/ask/deny lists). |
| Fragment | One named `.jsonc` file holding a slice of policy for one source kind. Fragments never include each other. |
| Profile | Picks an ordered list of fragments per source kind and may extend other profiles. `default_profile` applies when `--profile` is omitted. |
| Canonical output | The strict JSON each source kind compiles to: `~/.srt-settings.json` (read by SRT) and `bash-rules.json`. Generated; never hand-edited. |
| Target | An agent config file derived from the compiled rules: Claude settings, Codex config and rules, Copilot flags. |
| Mode | `full` (default) keeps ask rules and interactive approval. `--yolo` drops ask rules and writes to separate `*.yolo.*` targets, for launches that skip permission prompts. |

Composition merges objects recursively and unions arrays. Conflicting scalars
or opposing allow/deny rules fail with the path and the fragments involved.
Nothing is written until every target rendered cleanly. Details in
[Compiler model](doc/REFERENCE.md#compiler-model).

## Configuration

Only `config.toml` and the `.jsonc` fragments are edited by hand. Relative
paths resolve from the directory containing `config.toml`; `~` and absolute
paths also work.

### config.toml

```toml
schema_version = 1
default_profile = "default"

# --- canonical sources: one compiled output, one or more fragments each ---
[sources.srt]
output = "~/.srt-settings.json"
[sources.srt.fragments.base]
path = "srt/base.jsonc"
[sources.srt.fragments.work]
path = "srt/work.jsonc"

[sources.bash]
output = "bash-rules.json"
[sources.bash.fragments.base]
path = "bash/base.jsonc"

# --- profiles: fragment selections; children add, they never override ---
[profiles.default]
srt = ["base"]
bash = ["base"]

[profiles.work]
extends = ["default"]
srt = ["work"]

# --- targets ---
[targets]
claude_settings = "~/.claude/settings.full.json"   # must not be settings.json (symlink anchor)
codex_config    = "~/.codex/config.toml"
codex_rules     = "~/.codex/rules/twsrt.rules"      # optional: omit to skip escalation rules
copilot_output  = "~/.config/twsrt/copilot-flags.txt"   # optional: stdout if omitted
# claude_settings_yolo / copilot_output_yolo: optional; default inserts ".yolo" before the suffix

# --- Claude: keep unmanaged settings in sync between full and yolo files ---
[claude_sync]
mode_specific = ["skipDangerousModePermissionPrompt", "skipAutoPermissionPrompt"]

# --- Claude: sandbox posture per mode, applied after SRT values ---
[sandbox_overrides.yolo]
enabled = true
autoAllowBashIfSandboxed = true
allowUnsandboxedCommands = false

[sandbox_overrides.full]
enabled = false
```

`twsrt config --init` writes a fully commented version of this file.

### SRT fragment (`srt/*.jsonc`)

Follows the [SRT configuration schema](https://github.com/anthropic-experimental/sandbox-runtime?tab=readme-ov-file#configuration).
Comments are allowed; trailing commas, duplicate keys, and non-finite numbers
are rejected.

```jsonc
{
  "filesystem": {
    "denyRead":  ["~/.aws", "~/.ssh", "~/.gnupg", "~/.netrc"],
    "denyWrite": ["**/.env", "**/*.pem", "**/*.key", "**/secrets/**"],
    "allowWrite": [".", "/tmp", "~/dev"]
  },
  "network": {
    "allowedDomains": ["github.com", "*.github.com", "pypi.org", "*.pypi.org"]
  }
}
```

Full example: [example/srt-settings.jsonc](example/srt-settings.jsonc).

### Bash fragment (`bash/*.jsonc`)

```jsonc
{
  "allow": ["gh pr view"],
  "deny":  ["rm", "sudo", "git push --force"],
  "ask":   ["git push", "git commit", "pip install"]
}
```

Full example: [example/bash-rules.jsonc](example/bash-rules.jsonc).

## Commands

| Command | Effect |
|---|---|
| `twsrt config --init` | Create starter `config.toml` and fragments |
| `twsrt config` | Open `config.toml` in `$EDITOR` |
| `twsrt generate [claude\|codex\|copilot]` | Print the generated config for one agent, or all |
| `twsrt generate <agent> -w` | Write the canonical outputs and the agent target (selective merge) |
| `twsrt generate <agent> -w -n` | Dry run: show what would be written |
| `twsrt generate --yolo <agent>` | Yolo mode: no ask rules, `*.yolo.*` targets, yolo sandbox overrides |
| `twsrt generate -p work <agent>` | Use profile `work` instead of `default_profile` |
| `twsrt diff [agent] [--yolo]` | Compare fragments against canonical outputs and targets on disk |
| `twsrt test [-k TEXT] [--json]` | Prove the compiled SRT settings are enforced by probing the sandbox |

`diff` exit codes: `0` no drift, `1` drift, `2` target missing. It compiles
the profile in memory and catches both unapplied fragment edits and
out-of-band changes to generated files.

`test` derives one probe command per effective SRT rule from the compiled
`~/.srt-settings.json` (a `head` on a file inside every `denyRead` path, an
append-open that writes nothing for every `denyWrite` glob, directory, or
file and every `allowWrite` directory or file, a `curl` per concrete domain,
plus a canary for a host outside the allowlist) and runs each probe twice:
plainly as
a control, then under `srt -s <settings> -c`. A deny rule passes if the
control succeeds and the sandboxed run fails, or if the OS itself refuses the
control run (a root-owned directory), so a missing file can never count as
protected while an already-protected path still does. Symlinked deny paths get a second probe on their real
path, which exposes the macOS symlink no-op (see
[Security model](#security-model)). Exit codes: `0` all probes passed, `1` any
`FAIL`, `INVALID`, or `ERROR`, `2` settings missing or srt unable to sandbox.
`--json` replaces the table with a machine-readable report. It must run from a
plain terminal: inside another sandbox (Claude Code's Bash tool, Codex) srt
cannot apply its profile and the preflight aborts with exit `2`. Probe
catalogue, verdict table, and safety properties:
[Sandbox probes](doc/REFERENCE.md#sandbox-probes).

Generated content goes to stdout unstyled; diagnostics go to stderr with
color. `--verbose` before the subcommand adds debug output that never prints
policy contents; the one exception is `test`, where `-v` traces the whole run:
every executed command as a copyable line (`exec: sh -c ...`,
`exec: srt -s ... -c ...`) with exit code, duration, and stderr, plus each
derivation decision, so the deny paths under test do appear. Details in
[Diagnostic output](doc/REFERENCE.md#diagnostic-output).

## Claude Code target

**Files.** twsrt writes `~/.claude/settings.full.json` (or `settings.yolo.json`
with `--yolo`) and points the symlink `~/.claude/settings.json` at it. A
regular `settings.json` found on first run is moved to the target. Both
regular file and target existing at once is an error.

**What Claude enforces.** The native sandbox (Seatbelt or bwrap, configured
under `sandbox`) covers Bash commands. Read, Edit, and WebFetch run inside
the agent process and are guarded only by the generated `permissions` rules.
Claude folds `Read`/`Edit` deny rules into the sandbox profile, so twsrt
emits deny paths as permission rules only and leaves
`sandbox.filesystem.denyRead/denyWrite` empty. Duplicating them once pushed
the profile past macOS `ARG_MAX`.

**Selective merge.** `-w` rewrites only what twsrt owns:

| Section | Handling |
|---|---|
| `permissions.deny`, `permissions.ask` | replaced |
| `permissions.allow` | only `WebFetch(domain:...)` entries replaced; other allows kept |
| `sandbox.network`, `sandbox.filesystem`, `sandbox.*` | merged key by key; Claude-only keys kept; deny lists reset to `[]` |
| everything else (hooks, plugins, model, theme, ...) | kept, or synced from the other mode's file with `[claude_sync]` |

Worked example with before and after JSON:
[Claude merge example](doc/REFERENCE.md#claude-merge-example). Key-by-key
table: [Claude sandbox key mapping](doc/REFERENCE.md#claude-sandbox-key-mapping).

**Sandbox posture per mode.** `[sandbox_overrides.yolo]` and
`[sandbox_overrides.full]` set top-level `sandbox` keys after SRT values. A
nested `network` or `filesystem` table replaces that whole section. Typical
use: yolo keeps the kernel sandbox on as the safety net for skipped prompts;
full turns it off because every action is approved interactively.

**Keeping full and yolo in sync (`[claude_sync]`).** Claude Code writes
runtime settings (`model`, `theme`, `editorMode`, hooks added in the UI) into
whatever `settings.json` points to, so with two files and a symlink flip per
launch those keys would land in one file only. With the table present,
`generate -w claude` first copies every unmanaged key from the file the
symlink currently points to (the donor, the one Claude has been writing to)
into the target, then applies the merge above. The two files converge on
every mode switch.

- Donor values replace target values wholesale; deletions propagate. Last
  writer wins.
- Dotted paths in `mode_specific` (for example `hooks.PostToolUse`) keep the
  target's value and are never synced.
- Managed sections and the whole `sandbox` subtree are never synced.
- No donor, no sync: fresh install, migration, dangling symlink, or symlink
  already pointing at the target. A missing target is bootstrapped from the
  donor.
- `twsrt diff` does not report full/yolo drift; it is transient by design.

**Gotcha.** Claude's sandbox write allowlist is hardcoded and cannot be
managed from settings
([claude-code#10377](https://github.com/anthropics/claude-code/issues/10377#issuecomment-3468689124)),
so SRT `allowWrite` produces no Claude output.

## Codex target

Codex runs all work through its always-on kernel sandbox, so the compiled
policy becomes a native permission profile named `twsrt` in
`~/.codex/config.toml`, plus optional escalation rules in
`~/.codex/rules/twsrt.rules`. Output is identical in full and yolo mode.

| Canonical rule | Codex |
|---|---|
| `denyRead` | filesystem `deny` |
| `denyWrite` exact path / glob | `read` / `deny` (stricter; warned) |
| `allowWrite` | workspace roots and `write` rules on top of the `:workspace` base |
| `allowedDomains`, `deniedDomains` | `domains` allowlist (always emitted; empty blocks everything) |
| bash `deny` | `forbidden` prefix rules, consulted only for requests to run outside the sandbox |
| bash `allow`, bash `ask` | not compiled: `allow` would auto-approve unsandboxed execution, `ask` restates the default prompt |

twsrt owns `default_permissions`, `approval_policy`, `approvals_reviewer`,
`allow_login_shell`, and `[permissions.twsrt]`; everything else in the file is
preserved. Omit `codex_rules` in config.toml to skip escalation rules and rely
on Codex's prompt-on-escalation default. Restart Codex after generation.

> **Trap.** A legacy `sandbox_mode` or `sandbox_workspace_write` in *any*
> loaded Codex config layer, or `--sandbox` on the CLI, makes Codex silently
> ignore `default_permissions`. twsrt fails fast only for the file it owns and
> prints a reminder on every run. Run `codex doctor` after changing other
> layers. Permission profiles are Beta and `.rules` Experimental upstream.

Full translation rules, skipped SRT fields, and the workspace-roots example:
[Codex translation rules](doc/REFERENCE.md#codex-translation-rules).

## Copilot CLI target

Copilot has no settings file, so twsrt emits a flag snippet for the launch
command (to stdout, or to `copilot_output` if set):

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

Copilot has no ask tier, so ask rules become `--deny-tool` with a warning.
With `--yolo` the snippet starts with `--yolo` and keeps only `--deny-tool`
and `--deny-url`; deny flags still take precedence over `--yolo`.

Nothing kernel-guards Copilot's tools, so run it under the SRT wrapper:

```bash
srt -c "copilot --allow-tool 'shell(*)' --deny-tool 'shell(rm)' ..."
```

## Security model

| | Claude Code | Copilot CLI | Codex |
|---|---|---|---|
| Kernel layer | native sandbox, opt-in | none (use SRT wrapper) | native sandbox, always on |
| App layer | permission rules | CLI flags per invocation | profile + escalation rules |
| Built-in tools | in-process, app rules only | in-process, flags only | run as sandboxed subprocesses |
| ask tier | native | absent, mapped to deny | native default, not restated |
| Known trap | `allowWrite` hardcoded | ask to deny fidelity loss | `sandbox_mode` anywhere disables the profile |

**Verifying enforcement.** Configuration says what should be blocked; only a
probe shows what is. `twsrt test` runs derived probes under the SRT wrapper
and fails when a rule is not enforced. The case it was built for: on macOS,
srt keeps a symlinked `denyRead` path unresolved while Seatbelt matches the
real path, so `denyRead: ["~/.aws"]` blocks nothing when `~/.aws` is a
symlink. The `(realpath)` probe row turns that silent gap into a `FAIL`; the
fix is to deny the real directory as well. Run it after every srt or agent
upgrade. It exercises srt only; Claude Code's native sandbox and Codex are
not probed. Mechanics: [Sandbox probes](doc/REFERENCE.md#sandbox-probes).

Rule-by-rule translation: [Rule mapping per agent](doc/REFERENCE.md#rule-mapping-per-agent).
Guarantees twsrt upholds: [Invariants](doc/REFERENCE.md#invariants).
Threat model: [SECURITY_CONCEPT.md](SECURITY_CONCEPT.md).
pi-mono integration: [pi-extensions/sandbox](https://github.com/sysid/pi-extensions/tree/main/packages/sandbox).

## Development

```bash
make test              # pytest with coverage
make lint              # ruff check --fix
make format            # ruff format
make ty                # type check with ty
make static-analysis   # all of the above
make install           # uv tool install -e . plus shell completion
```
