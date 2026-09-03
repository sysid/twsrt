# twsrt Reference

Detail that the [README](../README.md) links to but does not need on the
reader path: exact rule translations, key-by-key sandbox mapping, a full
before/after merge example, Codex translation rules, diagnostics, and roadmap.

## Contents

- [Rule mapping per agent](#rule-mapping-per-agent)
- [Claude sandbox key mapping](#claude-sandbox-key-mapping)
- [Claude merge example](#claude-merge-example)
- [Codex translation rules](#codex-translation-rules)
- [Compiler model](#compiler-model)
- [Diagnostic output](#diagnostic-output)
- [Invariants](#invariants)
- [Scope and roadmap](#scope-and-roadmap)

## Rule mapping per agent

| SRT / Bash rule | Claude Code | Copilot CLI | Codex |
|---|---|---|---|
| denyRead directory | `Read(path)`, `Read(path/**)`, `Edit(path)`, `Edit(path/**)` in deny | (SRT enforces) | filesystem `deny` |
| denyRead file | `Read(path)`, `Edit(path)` in deny | (SRT enforces) | filesystem `deny` |
| denyWrite exact path | `Edit(path)` in deny | (SRT enforces) | filesystem `read` |
| denyWrite glob | `Edit(pattern)` in deny | (SRT enforces) | filesystem `deny` (stricter; warns) |
| allowWrite absolute or home path | (no output) | `--allow-tool` flags | profile workspace root |
| allowWrite relative path | (no output) | `--allow-tool` flags | named path → filesystem `write`; `.` omitted |
| allowedDomains | `WebFetch(domain:X)` allow + `sandbox.network.allowedDomains` | (SRT enforces) | domain `allow` |
| deniedDomains | `WebFetch(domain:X)` in deny | `--deny-url` | domain `deny` |
| Bash allow | (no output) | (no output) | not compiled (would auto-approve unsandboxed; warns) |
| Bash deny | `Bash(cmd)`, `Bash(cmd *)` in deny | `--deny-tool 'shell(cmd)'` | prefix `forbidden` |
| Bash ask | `Bash(cmd)`, `Bash(cmd *)` in ask | `--deny-tool` (lossy, warns) | not compiled (Codex prompts by default; warns) |

The same table as a flow, `∅` = deliberately not compiled:

```
srt denyRead ────► claude deny(Read/Edit) ─► copilot ∅ (SRT) ──► codex fs "deny"
srt denyWrite ───► claude deny(Edit)      ─► copilot ∅ (SRT) ──► codex "read"/glob "deny" (warn)
srt allowWrite ──► claude ∅ (hardcoded!)  ─► copilot allow-*  ─► codex workspace roots
bash allow ──────► claude ∅               ─► copilot ∅        ─► codex ∅ warn (would unsandbox)
bash ask ────────► claude ask             ─► copilot deny warn ─► codex ∅ warn (default prompts)
bash deny ───────► claude deny            ─► copilot deny      ─► codex "forbidden" (escalation only)
```

**YOLO mode differences.** Bash ask rules are skipped entirely. Copilot
`--allow-*` flags are omitted (subsumed by `--yolo`). Claude `permissions.ask`
is removed and `[sandbox_overrides.yolo]` applies instead of
`[sandbox_overrides.full]`. Codex output is identical in yolo and full mode.

**Claude file rules.** Claude Code matches file permissions on `Edit(path)`
only. A single `Edit` rule covers every file-editing tool (Write, Edit,
NotebookEdit), so no separate `Write(path)` rule is emitted. Directory versus
file detection uses the filesystem at generation time: globs stay bare, files
get no suffix, directories and unknown paths get an additional `/**` variant.
Absolute paths use Claude's `//` filesystem-root anchor because a single
leading `/` anchors at the settings source and silently matches nothing.

## Claude sandbox key mapping

Claude Code's `sandbox` section has 17 configurable keys. twsrt manages a
subset from the compiled SRT document; `[sandbox_overrides.*]` may also set
the Claude-only keys per mode.

| Claude Code key | SRT source | Status |
|---|---|---|
| `sandbox.network.allowedDomains` | `network.allowedDomains` | Managed |
| `sandbox.network.deniedDomains` | `network.deniedDomains` | Managed |
| `sandbox.network.allowLocalBinding` | `network.allowLocalBinding` | Managed (pass-through) |
| `sandbox.network.allowUnixSockets` | `network.allowUnixSockets` | Managed (pass-through) |
| `sandbox.network.allowAllUnixSockets` | `network.allowAllUnixSockets` | Managed (pass-through) |
| `sandbox.network.httpProxyPort` | `network.httpProxyPort` | Managed (pass-through) |
| `sandbox.network.socksProxyPort` | `network.socksProxyPort` | Managed (pass-through) |
| `sandbox.filesystem.allowWrite` | `filesystem.allowWrite` | Managed (pass-through) |
| `sandbox.filesystem.denyWrite` | `filesystem.denyWrite` | Managed-empty; emitted as `Edit` deny rules instead |
| `sandbox.filesystem.denyRead` | `filesystem.denyRead` | Managed-empty; emitted as `Read`/`Edit` deny rules instead |
| `sandbox.enabled` | `enabled` | Managed (pass-through) |
| `sandbox.enableWeakerNetworkIsolation` | `enableWeakerNetworkIsolation` | Managed (pass-through) |
| `sandbox.enableWeakerNestedSandbox` | `enableWeakerNestedSandbox` | Managed (pass-through) |
| `sandbox.ignoreViolations` | `ignoreViolations` | Managed (pass-through) |
| `sandbox.excludedCommands` | (none) | Claude-only; preserved, overridable via `[sandbox_overrides]` |
| `sandbox.autoAllowBashIfSandboxed` | (none) | Claude-only; preserved, overridable via `[sandbox_overrides]` |
| `sandbox.allowUnsandboxedCommands` | (none) | Claude-only; preserved, overridable via `[sandbox_overrides]` |

**Pass-through** keys are copied verbatim. A pass-through key absent from SRT
is omitted from the output. The two managed-empty deny lists are the
exception: they are always emitted as `[]` so a write clears stale values
generated by older twsrt versions.

**Why the deny lists are empty.** Claude Code folds `Read`/`Edit` permission
deny rules into the native OS sandbox profile. twsrt relies on that merge to
enforce canonical `denyRead`/`denyWrite` paths without duplicating them under
`sandbox.filesystem`, which previously expanded the Seatbelt profile past
macOS `ARG_MAX` (E2BIG on every Bash call). Consequently these two keys cannot
be set through `[sandbox_overrides]`; define deny paths in SRT fragments.

**Canary after every Claude Code upgrade.** From sandboxed Bash, reading and
moving a configured read-deny path must fail, and writing a configured
relative deny such as a cwd `.env` must fail. If any probe succeeds, stop
using the generated configuration and reconsider direct `sandbox.filesystem`
emission.

**Claude-only** keys have no SRT equivalent. `twsrt generate` never creates
them; `--write` preserves them; `[sandbox_overrides]` can set them per mode.

## Claude merge example

Existing hand-maintained `~/.claude/settings.full.json`:

```json
{
  "permissions": {
    "deny": ["Bash(old-deny-entry)"],
    "ask": ["Bash(old-ask-entry)"],
    "allow": [
      "Read", "Glob", "Grep", "WebSearch",
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

After `twsrt generate claude -w` with SRT `allowedDomains` `github.com` and
`*.github.com`, `denyRead` `~/.aws`, bash deny `rm` and `sudo`, bash ask
`git push`:

```json
{
  "permissions": {
    "deny": [
      "Read(~/.aws)", "Read(~/.aws/**)", "Edit(~/.aws)", "Edit(~/.aws/**)",
      "Bash(rm)", "Bash(rm *)", "Bash(sudo)", "Bash(sudo *)"
    ],
    "ask": ["Bash(git push)", "Bash(git push *)"],
    "allow": [
      "Read", "Glob", "Grep", "WebSearch",
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
    "filesystem": { "denyRead": [], "denyWrite": [] },
    "autoAllowBashIfSandboxed": true,
    "excludedCommands": ["docker"]
  }
}
```

What changed and what did not:

```
  permissions.deny          ← REPLACED  (old-deny-entry gone; SRT + bash-rules)
  permissions.ask           ← REPLACED  (old-ask-entry gone; bash-rules)
  permissions.allow
    ├─ Read, Glob, ...      ← PRESERVED (not WebFetch entries)
    ├─ Bash(npm test:*)     ← PRESERVED
    ├─ mcp__memory__store   ← PRESERVED
    └─ WebFetch(domain:...) ← REPLACED  (old.example.com gone, github.com added)
  hooks                     ← PRESERVED (or synced from the donor with [claude_sync])
  additionalDirectories     ← PRESERVED (or synced)
  sandbox.network
    ├─ allowedDomains       ← REPLACED
    └─ allowLocalBinding    ← PRESERVED (key-by-key merge)
  sandbox.filesystem
    ├─ denyRead             ← RESET to [] (enforced through permission rules)
    └─ denyWrite            ← RESET to []
  sandbox.autoAllowBash...  ← PRESERVED unless [sandbox_overrides] sets it
  sandbox.excludedCommands  ← PRESERVED unless [sandbox_overrides] sets it
```

In yolo mode the merge is the same except `permissions.ask` is removed and
`[sandbox_overrides.yolo]` applies.

## Codex translation rules

twsrt compiles the canonical filesystem and network policy into a native
permission profile named `twsrt`, selected via `default_permissions`. The
profile extends the built-in `:workspace` base (workspace and tmp writable,
`.git`/`.codex`/`.agents` protected) and adds:

- Absolute and home-relative `allowWrite` paths become reusable workspace
  roots; a terminal `/**` or trailing slash is normalized to the concrete
  directory. Named relative paths become workspace filesystem `write` rules,
  which can intentionally reopen a Codex-protected path such as `.git`; `.`
  alone is omitted because the runtime workspace already covers it.
  Unsupported absolute shapes (`~`, `/`, other wildcards) and roots also
  matched by a deny rule are skipped with a warning; the deny wins.
- `denyRead` paths become filesystem `deny` (blocks Codex's default
  read-everything).
- `denyWrite` exact paths become `read`; `denyWrite` globs become `deny`
  (stricter, fail-safe; Codex cannot express read-only for globs; warned).
- `allowedDomains`/`deniedDomains` become the network `domains` allowlist. The
  `domains` table is always emitted, even empty: an empty map blocks all
  domain traffic, matching SRT allowlist semantics.
- Exact Unix socket paths become `unix_sockets` allow entries.

Added workspace roots inherit the `:workspace` write policy and every rule in
`filesystem.:workspace_roots`, so canonical deny globs constrain them without
repeating `"." = "write"`. Example: permit fetch/pull metadata updates while
keeping repository-local configuration and hooks read-only:

```toml
[permissions.twsrt.filesystem.":workspace_roots"]
".git" = "write"
".git/config" = "read"
".git/hooks" = "read"
```

**Deliberately not compiled** (each skip is warned at generation time):

- bash-rules `allow` commands. In Codex an `allow` execution rule means "run
  outside the sandbox without prompting", strictly weaker than the default.
- bash-rules `ask` commands. Codex already prompts for every out-of-sandbox
  request; restating the default adds bulk, not security.

`~/.codex/rules/twsrt.rules` therefore contains only `deny` → `forbidden`
prefix rules. They govern only requests to execute outside the sandbox; a
command running inside the sandbox never consults them.

**Skipped SRT fields** (cannot be translated without widening access):
`allowLocalBinding`, socket directory entries, integer proxy ports, Mach
lookup, violation-reporting exceptions, weaker-isolation switches. A disabled
canonical SRT sandbox or a malformed `/~/...` path fails generation.

**Owned keys in `~/.codex/config.toml`**: `default_permissions`,
`approval_policy`, `approvals_reviewer`, `allow_login_shell`, and
`[permissions.twsrt]`. Everything else (projects, MCP servers, headers,
WebSearch, apps, `shell_environment_policy`) is preserved. Preview and diff
output contain only managed security data, so foreign credentials are never
printed.

## Compiler model

| Concept | Responsibility |
|---|---|
| Source kind | One canonical document type with its fragment registry, compiled output, validation, and rule translation. `srt` and `bash` are registered. |
| Fragment | A named `.jsonc` object holding one reusable policy slice. Fragments never reference each other. |
| Profile | Selects ordered fragment names per source kind; may extend other profiles. |
| Resolved profile | Parent-first, stable-deduplicated fragment order for one invocation. |
| Compiled document | Strict JSON from recursively composing one source kind's selected fragments. |
| Agent target | Configuration derived from the normalized rules after compilation succeeds. |

Composition rules: objects merge recursively, arrays form a stable
deduplicated union, equal scalars agree. Unequal scalars, incompatible types,
cycles, missing source selections, unknown fragments, SRT allow/deny overlaps,
and Bash allow/ask/deny overlaps fail with profile, path, and fragment
context. Compilation and target rendering complete before `--write` touches
any file, so a conflict cannot leave partial output.

Profile inheritance is selection reuse, not override precedence: a child can
add fragments but cannot silently replace a conflicting parent value. Model
intentional variants as separate profiles sharing a non-conflicting base.

Adding a source kind means registering its name, validating its compiled
document, and translating it into normalized rules; profile resolution and
composition are reused. Adding an agent consumes the normalized rules and
does not touch fragments or profiles.

## Diagnostic output

Generated JSON, TOML, rules, and Copilot flags stay unstyled on stdout so they
can be piped. Human diagnostics use fixed severities and streams:

| Kind | Color | Stream |
|---|---|---|
| Error | red, bold | stderr |
| Warning | yellow | stderr |
| Info | cyan | stdout |
| Successful write, clean diff | green | stdout |
| Drift | yellow | stdout |
| Unexpected extra entry | red | stdout |
| Debug (`--verbose`) | dim cyan | stderr |

Colors are enabled only on an interactive terminal; `NO_COLOR` (even empty)
disables ANSI output. `--verbose` goes before the subcommand and reports
lifecycle facts only: selected profile, mode, agent names, counts, target
paths, caught exception tracebacks. It never prints policy contents, rule
patterns, domains, environment values, or credentials.

## Invariants

1. **The resolved profile is the single source of truth for an invocation.**
   Registered JSONC fragments are the human-maintained inputs. Compiled
   canonical JSON and agent configs are artifacts; `twsrt diff` detects drift
   in both.
2. **Canonical allows widen only the named sandbox boundary.** SRT
   `allowWrite` directories become Codex workspace roots, retaining inherited
   protected paths and deny globs. Lossy translations narrow or skip with a
   warning; Bash allows never become unsandboxed execution.
3. **Selective merge owns only declared sections.** Everything else in a
   target file (hooks, MCP servers, projects, credentials) is preserved
   byte-for-byte where the format allows. With `[claude_sync]`, those
   unmanaged keys converge between the full and yolo targets on the next mode
   switch; drift between them is transient by design.
4. **Fail-safe on ambiguity.** Disabled canonical sandbox, malformed paths,
   conflicting fragments, incomplete profiles, and legacy Codex
   `sandbox_mode` in the managed file abort generation instead of guessing.

## Scope and roadmap

All three agents ship native OS sandboxes (Claude Code: built-in
Seatbelt/bwrap, opt-in; Copilot CLI: local sandbox in public preview; Codex:
kernel sandbox always-on). The durable core compiles into each of them. The
bash-rules app layer is the per-agent best-effort supplement:

- **Bash-rules translation is Claude-primary and frozen for new agents.**
  Claude gets full deny/ask fidelity; Copilot keeps deny-only flags (deny
  takes precedence over `--yolo`); Codex gets forbidden-only escalation
  rules. New agents get restrictions-only compilation by default.
- **Copilot native sandbox** (`sandbox` key in Copilot settings.json) is the
  intended replacement for the flag-snippet generator, deferred while the
  feature is in public preview with an undocumented backend.
