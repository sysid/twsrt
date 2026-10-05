# twsrt Reference

Technical detail the [README](../README.md) links to: how the compiler
works, exactly what each agent receives, how `doctor` and `test` decide, and
how to extend twsrt. The README explains the concepts; the threat model and
rationale are in [SECURITY_CONCEPT.md](../SECURITY_CONCEPT.md).

## Contents

- [Compiler model](#compiler-model)
- [Rule mapping per agent](#rule-mapping-per-agent)
- [Claude sandbox key mapping](#claude-sandbox-key-mapping)
- [Claude merge example](#claude-merge-example)
- [Claude full and yolo sync](#claude-full-and-yolo-sync)
- [Claude per-project launch premise](#claude-per-project-launch-premise)
- [Codex translation rules](#codex-translation-rules)
- [Copilot flags](#copilot-flags)
- [Doctor checks](#doctor-checks)
- [Sandbox probes](#sandbox-probes)
- [Diagnostic output](#diagnostic-output)
- [Invariants](#invariants)
- [Extending twsrt](#extending-twsrt)
- [Scope and roadmap](#scope-and-roadmap)

## Compiler model

```
 config.toml ──► load + validate ──► resolve profile ──► parse JSONC ──► compose
                                                                           │
                                     imply write denies ◄── validate ◄─────┘
                                            │
                         ┌──────────────────┴──────────────────┐
                         ▼                                     ▼
              canonical documents                    normalized SecurityRules
              (~/.srt-settings.json,                           │
               bash-rules.json)                                ▼
                                                     agent generators ──► targets
```

| Concept | Responsibility |
|---|---|
| Source kind | One canonical document type with its fragment registry, compiled output, validation, and rule translation. `srt` and `bash` are registered. |
| Fragment | A named `.jsonc` object holding one reusable policy slice. Fragments never reference each other. |
| Profile | Selects ordered fragment names per source kind; may extend other profiles. |
| Resolved profile | Parent-first, stable-deduplicated fragment order for one invocation. |
| Compiled document | Strict JSON from composing one source kind's selected fragments. |
| Agent target | Configuration derived from the normalized rules after compilation succeeds. |

### Phases

| Phase | Input | Fails on |
|---|---|---|
| Configuration loading | `config.toml` | Unknown schema version, legacy source paths, unknown source kinds, duplicate outputs, an output equal to a fragment path, a fragment path not ending in `.jsonc`, unknown references, inheritance cycles |
| Profile resolution | Profile name (`default_profile` unless `-p`) | Unknown parents or fragments; a source kind with no selected fragment |
| JSONC parsing | Selected `.jsonc` files | Duplicate keys, trailing commas, single-quoted or unquoted keys, `NaN`/infinities, non-object roots, malformed comments |
| Composition | Parsed objects | Unequal scalars, incompatible types |
| Domain validation | Each fragment and the composed document | Invalid field shapes, unknown Bash actions, a value in opposing buckets |
| Write-deny implication | Composed srt document | A path in both `denyRead` and `allowWrite` |
| Translation and write | Compiled documents | Any rendering conflict; nothing is written until every target rendered, and each file is replaced atomically |

Each source kind owns a fragment namespace and exactly one compiled output.
Relative paths resolve from `config.toml`, so the configuration directory is
relocatable. Unknown source kinds fail instead of being composed without
validation or translation semantics.

### Profile resolution

- Parents resolve before children; diamond inheritance and repeated
  fragment names are deduplicated by first occurrence.
- Inheritance is selection reuse, not override precedence: a child adds
  fragments but cannot change a value a parent set. `enabled: true` in a
  parent and `false` in a child is a compile error, so no profile silently
  weakens another. Model intentional variants as separate profiles sharing a
  non-conflicting base.

### JSONC and composition

twsrt parses JSONC itself (no parser dependency): `//` and `/* … */`
comments, source locations preserved for errors, everything else strict JSON.
Within a source kind the selected documents form a structural union:

| Values at the same path | Result |
|---|---|
| Objects | Merge recursively |
| Arrays | Deduplicated union. Rule arrays the schema knows to be sets (`filesystem.*`, `network.allowedDomains`/`deniedDomains`/`allowUnixSockets`, `ignoreViolations.*`, Bash `allow`/`ask`/`deny`) are sorted, so output is independent of fragment order; every other array keeps first-seen order, because an unknown pass-through list may be a sequence such as argv |
| Equal scalars | Keep the value |
| Unequal scalars, different JSON types | Fail with profile, source kind, JSON pointer and both fragment paths |

Domain validation rejects the same value in opposing buckets: SRT
`allowedDomains`/`deniedDomains` and `allowWrite`/`denyWrite`; Bash
`allow`/`ask`/`deny`. There is no "safer value wins" heuristic: it would be
source-specific and could conceal an authoring error.

**Write denies are implied.** After composition every `denyRead` path is
added to `denyWrite` (`sources._imply_write_denies`), plus `./.twsrt` under
`--project`, plus the policy files: `config.toml` and every `[sources]`
output and fragment path (`AppConfig.policy_files`), absolute (`~/…` under
the home directory) and, behind a symlink, also as the real path. `--project` keeps protecting the global
outputs. A path in both `denyRead` and `allowWrite` asks for write-only
access and fails. Why: [ADR 0001](adr/0001-deny-read-implies-deny-write.md),
[SECURITY_CONCEPT §3.4](../SECURITY_CONCEPT.md#34-least-privilege-denyread-implies-denywrite).

### Canonical documents feed every target

Generators consume the normalized rules parsed from the compiled documents
in memory, never the fragments and never the canonical files on disk.
`--write` therefore rewrites every canonical output on each run, whichever
agent is named, so a target can never disagree with the canonical file it
was translated from.

### Internal data model

```
CanonicalSource   name, output_path, fragments: name → SourceFragment(path)
Profile           extends: [profile], selections: source kind → [fragment name]
ResolvedProfile   fragments: source kind → [SourceFragment]
CompiledDocument  source_kind, output_path, document

SecurityRule      scope:   READ | WRITE | EXECUTE | NETWORK
                  action:  DENY | ASK | ALLOW
                  pattern: path, glob, command, or domain (never empty)
                  source:  SRT_FILESYSTEM | SRT_NETWORK | BASH_RULES
```

Enforced at construction: `NETWORK` takes only `ALLOW` or `DENY`;
`EXECUTE` requires `BASH_RULES`; `READ`/`WRITE` require `SRT_FILESYSTEM`.

## Rule mapping per agent

`—` = no output; for Copilot the SRT wrapper enforces paths and domains.

| Canonical rule | Claude Code | Copilot CLI | Codex |
|---|---|---|---|
| `denyRead` directory | `Read(p)`, `Read(p/**)`, `Edit(p)`, `Edit(p/**)` deny | — | filesystem `deny` |
| `denyRead` file | `Read(p)`, `Edit(p)` deny | — | filesystem `deny` |
| `denyRead` glob | `Read(g)`, `Edit(g)` deny | — | filesystem `deny` |
| `denyWrite` exact path | `Edit(p)` deny | — | filesystem `read` |
| `denyWrite` glob | `Edit(g)` deny | — | filesystem `deny` (stricter; warned) |
| `allowWrite` absolute or home path | `Edit(//p)` / `Edit(~/p)` allow (+ `/**` for directories); see [ADR 0002](adr/0002-claude-file-rules-as-permission-rules.md) | `--allow-tool 'shell'`, `'read'`, `'edit'`, `'write'` (once) | profile workspace root |
| `allowWrite` relative path | `Edit(p)` allow, left relative so it anchors at the launch cwd (+ `/**`) | as above | named path → filesystem `write`; `.` omitted |
| `allowedDomains` | `WebFetch(domain:X)` allow + `sandbox.network.allowedDomains` | `--allow-url 'X'` | domain `allow` |
| `deniedDomains` | `WebFetch(domain:X)` deny | `--deny-url 'X'` | domain `deny` |
| Bash `allow` | — | — | not compiled (would auto-approve unsandboxed execution; warned) |
| Bash `deny` | `Bash(c)`, `Bash(c *)` deny | `--deny-tool 'shell(c)'` | prefix `forbidden` |
| Bash `ask` | `Bash(c)`, `Bash(c *)` ask | `--deny-tool 'shell(c)'` (lossy; warned) | not compiled (Codex prompts by default; warned) |

Every `denyRead` path also arrives as an implied `denyWrite`; Claude drops
the resulting duplicate `Edit(p)`, and Codex keeps `deny`, which outranks
`read`.

**Yolo mode.** Bash `ask` rules are skipped. Claude's `permissions.ask` is
removed and `[sandbox_overrides.yolo]` applies instead of
`[sandbox_overrides.full]`. Copilot's output starts with `--yolo` and drops
the `--allow-*` flags. Codex output is identical in both modes.

**Claude file rules.** Claude Code matches file permissions on `Edit(path)`
only, and one `Edit` rule covers every file-editing tool (Write, Edit,
NotebookEdit); `Write(path)`/`MultiEdit(path)` are never consulted and are
rejected at startup, so twsrt does not emit them. Directory versus file is
detected on the filesystem at generation time: globs stay bare, files get no
suffix, directories and paths that do not exist get an additional `/**`
variant (fail-safe: assume directory). Absolute paths use Claude's `//`
filesystem-root anchor, because a single leading `/` anchors at the settings
source and silently matches nothing.

## Claude sandbox key mapping

Claude Code's `sandbox` section has 17 configurable keys. twsrt manages a
subset from the compiled SRT document; `[sandbox_overrides.*]` may also set
the Claude-only keys per mode.

| Claude Code key | SRT source | Status |
|---|---|---|
| `sandbox.network.allowedDomains` | `network.allowedDomains` | Managed |
| `sandbox.network.deniedDomains` | (none) | Not generated: `deniedDomains` become `WebFetch(domain:X)` deny rules only |
| `sandbox.network.allowLocalBinding` | `network.allowLocalBinding` | Managed (pass-through) |
| `sandbox.network.allowUnixSockets` | `network.allowUnixSockets` | Managed (pass-through) |
| `sandbox.network.allowAllUnixSockets` | `network.allowAllUnixSockets` | Managed (pass-through) |
| `sandbox.network.httpProxyPort` | `network.httpProxyPort` | Managed (pass-through) |
| `sandbox.network.socksProxyPort` | `network.socksProxyPort` | Managed (pass-through) |
| `sandbox.filesystem.allowWrite` | `filesystem.allowWrite` | Managed-empty; emitted as `Edit` allow rules instead (a raw entry anchors relative paths at the settings-file root, ADR 0002) |
| `sandbox.filesystem.denyWrite` | `filesystem.denyWrite` | Managed-empty; emitted as `Edit` deny rules instead |
| `sandbox.filesystem.denyRead` | `filesystem.denyRead` | Managed-empty; emitted as `Read`/`Edit` deny rules instead |
| `sandbox.enabled` | `enabled` | Managed (pass-through) |
| `sandbox.enableWeakerNetworkIsolation` | `enableWeakerNetworkIsolation` | Managed (pass-through) |
| `sandbox.enableWeakerNestedSandbox` | `enableWeakerNestedSandbox` | Managed (pass-through) |
| `sandbox.ignoreViolations` | `ignoreViolations` | Managed (pass-through) |
| `sandbox.excludedCommands` | (none) | Claude-only; preserved, overridable via `[sandbox_overrides]` |
| `sandbox.autoAllowBashIfSandboxed` | (none) | Claude-only; preserved, overridable via `[sandbox_overrides]` |
| `sandbox.allowUnsandboxedCommands` | (none) | Claude-only; preserved, overridable via `[sandbox_overrides]` |

**Pass-through** keys are copied verbatim; one absent from SRT is omitted.
The two managed-empty deny lists are always emitted as `[]` so a write
clears stale values generated by older twsrt versions.

**Why the deny lists are empty.** Claude Code folds `Read`/`Edit` permission
deny rules into the native OS sandbox profile. twsrt relies on that merge to
enforce canonical `denyRead`/`denyWrite` paths without duplicating them under
`sandbox.filesystem`, which previously expanded the Seatbelt profile past
macOS `ARG_MAX` (E2BIG on every Bash call). Consequently these two keys
cannot be set through `[sandbox_overrides]`; define deny paths in SRT
fragments.

**Canary after every Claude Code upgrade.** From sandboxed Bash, reading and
moving a configured read-deny path must fail, and writing a configured
relative deny such as a cwd `.env` must fail. If any probe succeeds, stop
using the generated configuration and reconsider direct
`sandbox.filesystem` emission.

**Sandbox posture per mode.** `[sandbox_overrides.yolo]` and
`[sandbox_overrides.full]` set top-level `sandbox` keys after the SRT values.
A nested `network` or `filesystem` table replaces that whole section.

## Claude merge example

`generate -w claude` rewrites only what twsrt owns:

| Section | Handling |
|---|---|
| `permissions.deny`, `permissions.ask` | replaced |
| `permissions.allow` | `WebFetch(domain:…)` and `Edit(…)` entries replaced (twsrt owns them); other allows kept |
| `sandbox.network`, `sandbox.filesystem`, `sandbox.*` | merged key by key; Claude-only keys kept; `denyRead`/`denyWrite`/`allowWrite` reset to `[]` |
| everything else (hooks, plugins, model, theme, …) | kept, or synced from the other mode's file with `[claude_sync]` |

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

## Claude full and yolo sync

Claude Code writes runtime settings (`model`, `theme`, `editorMode`, hooks
added in the UI) into whatever `settings.json` points to. With two files and
a symlink flip per launch those keys would land in one file only:

```
 claude-full ──► settings.json ─symlink─► settings.full.json   ◄── Claude writes "model" here
 claude-yolo ──► generate --yolo -w:
                   1. donor = current symlink target (settings.full.json)
                   2. copy unmanaged keys donor ──► settings.yolo.json
                   3. apply the selective merge
                   4. flip symlink ──► settings.yolo.json
```

With the `[claude_sync]` table present, both files converge on every mode
switch:

- Donor values replace target values wholesale; deletions propagate. Last
  writer wins.
- Dotted paths in `mode_specific` (for example `hooks.PostToolUse`) keep the
  target's value and are never synced.
- Managed sections and the whole `sandbox` subtree are never synced.
- No donor, no sync: fresh install, migration, dangling symlink, or symlink
  already pointing at the target. A missing target is bootstrapped from the
  donor.
- `twsrt diff` does not report full/yolo drift; it is transient by design.

## Claude per-project launch premise (not relevant for `srt`)

`generate --project` is only useful for Claude if Claude is launched as:

```bash
claude --setting-sources project,local --settings .twsrt/claude-settings.json
```

twsrt does not launch Claude and cannot check the flags; the launcher must
pass them. This section records why the line works, what is documented
versus observed, and what breaks if Claude Code changes.

**Settings loaded per launch style:**

```
                         managed   --settings X   local    project   user (~/.claude/settings.json)
plain `claude`             yes          -          yes       yes      yes
claude --settings X        yes         yes         yes       yes      yes   ← dropped denies return
claude --setting-sources
  project,local
  --settings X             yes         yes         yes       yes      NO    ← what --project needs
```

**Claude Code behaviour the premise depends on:**

| # | Claim | Source |
|---|---|---|
| 1 | Precedence: managed > command line (`--settings`) > local > project > user | documented, settings.md "Settings precedence" |
| 2 | List keys (`permissions.deny`, `sandbox.filesystem.*`, `sandbox.network.allowedDomains`, …) are combined across scopes; a scope can add entries but never remove another scope's | documented, settings.md and sandboxing.md |
| 3 | No setting subtracts an entry defined in another scope | no such mechanism found in the settings, permissions or sandboxing docs (searched 2026-10-02) |
| 4 | `--setting-sources` takes a comma list of `user`, `project`, `local`; managed settings always load | documented, cli-reference.md |
| 5 | `--setting-sources project,local --settings X` in an interactive session skips the user file and applies `X` | the docs do not say whether the flag applies to interactive sessions; verified manually by Tom on 2026-10-02 |
| 6 | Settings files are watched and reloaded mid-session | documented, settings.md "When edits take effect" |

Claims 2 and 3 are why a project cannot drop a rule by layering a file on
top: only not loading the global file works (claims 4 and 5). Claim 6 is why
`./.twsrt` is added to `denyWrite`.

**Consequences:**

- `X` replaces the user scope completely, so it carries the user keys too.
  It is built by `selective_merge` from the global Claude target of the same
  mode (`settings.full.json` or `settings.yolo.json`). A hook or plugin added
  to the global file appears in a project session on the next launch, since
  every launch regenerates `X`.
- The repository's `.claude/settings.json` and `.claude/settings.local.json`
  still load. They can add rules and, once the folder is trusted, override
  sandbox scalars such as `sandbox.enabled`. This is the same exposure as a
  plain `claude` launch.
- Managed settings cannot be skipped and still apply.
- Starting `claude` without both flags in a project directory is not unsafe:
  the global file loads.

**If Claude Code changes:**

| Change | Effect | Direction |
|---|---|---|
| `--setting-sources` stops excluding the user file | dropped denies return through the union | fails closed: stricter, the feature stops working |
| `--settings` stops being honoured with `user` excluded | project session runs with no twsrt policy, only repo and managed settings | fails **open**: re-verify after Claude Code upgrades |
| Lists replace instead of union across scopes | `--settings X` alone would suffice | harmless |

**Re-verify** after a Claude Code upgrade, from a plain terminal:

1. `twsrt generate claude -w -p <profile-without-rule-R> --project`
2. `claude --setting-sources project,local --settings .twsrt/claude-settings.json`
3. `/permissions`: rule R is absent and the other twsrt denies are present.
4. A deny that exists only in `~/.claude/settings.json` (not in any
   fragment) is absent from `/permissions`: proves the user file was skipped.
5. Ask the agent to `echo x >> .twsrt/claude-settings.json`: refused.

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
- Exact Unix socket paths become `unix_sockets` allow entries; directory
  entries are skipped with a warning.

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

**Accepted trade-off.** An added workspace root is writable in every Codex
session regardless of the working directory: exactly the grant canonical
`allowWrite` expresses, but broader than Codex's per-project trust default.
More-specific `read`/`deny` rules and workspace deny globs still bound the
blast radius.

**Deliberately not compiled** (each skip is warned at generation time):

- Bash `allow` commands. In Codex's rules language `decision = "allow"` means
  "run outside the sandbox without prompting", strictly weaker than the
  default prompt for every escalation. The canonical intent ("don't ask,
  still sandboxed") does not survive translation.
- Bash `ask` commands. `decision = "prompt"` restates Codex's default for
  every out-of-sandbox request; ~50 prompt rules add bulk, not security.

`~/.codex/rules/twsrt.rules` therefore contains only `deny` → `forbidden`
prefix rules, and only while `codex_rules` is set. They govern requests to
execute *outside* the sandbox; a command running inside the writable
workspace (e.g. `git reset --hard`) never consults them. The kernel sandbox
is the enforcement layer there. Hooks are not used as a compensating
control: Codex documents their command interception as incomplete and does
not support hook-driven `ask` decisions.

**Skipped SRT fields** (cannot be translated without widening access):
`allowLocalBinding`, socket directory entries, integer proxy ports, Mach
lookup, violation-reporting exceptions, weaker-isolation switches. A disabled
canonical SRT sandbox or a malformed `/~/...` path fails generation.

**Owned keys in `~/.codex/config.toml`**, each pinned against a distinct
silent-weakening vector and checked by `diff`:

| Key | Value | Defends against |
|---|---|---|
| `default_permissions` | `"twsrt"` | Profile deselected out-of-band |
| `approval_policy` | `"on-request"` | A stale `never` auto-approving escalations |
| `approvals_reviewer` | `"user"` | Delegating approval decisions to the model |
| `allow_login_shell` | `false` | Login-shell environments bypassing the profile (stricter than Codex's default `true`) |
| `[permissions.twsrt]` | generated | The profile itself |

Everything else (projects, MCP servers, headers, WebSearch, apps,
connectors, `shell_environment_policy`) is preserved and not managed.
Preview and diff output contain only managed security data, so foreign
credentials are never printed.

## Copilot flags

| Canonical rule | Flag | Full | Yolo |
|---|---|---|---|
| any `allowWrite` | `--allow-tool 'shell'`, `'read'`, `'edit'`, `'write'`, emitted once | ✓ | — |
| `allowedDomains` | `--allow-url 'X'` | ✓ | — |
| `deniedDomains` | `--deny-url 'X'` | ✓ | ✓ |
| Bash `deny` | `--deny-tool 'shell(c)'` | ✓ | ✓ |
| Bash `ask` | `--deny-tool 'shell(c)'` + warning | ✓ | — |
| `denyRead`, `denyWrite` | — (SRT wrapper enforces) | | |

Yolo output starts with `--yolo`; deny flags still take precedence over it.
Copilot has no "ask before running" tier, so an ask rule becomes a deny, the
fail-safe direction:

```
Warning: Bash ask rule 'git push' mapped to --deny-tool for copilot (no ask equivalent)
```

## Doctor checks

`twsrt doctor` reads `config.toml`, every registered fragment, and the Claude
settings files that can carry sandbox paths (the twsrt Claude targets, full
and yolo, and `./.claude/settings.json` / `settings.local.json` of the current
directory). It writes nothing, and prints one line per finding on stdout followed by a count.
Without options it shows errors and warnings; `--error`, `--warn` and `--info` show exactly
those levels and combine, `--all` shows every level. The filter is display only: the count
covers every level, and exit is `1` on any error, shown or not, else `0`.

Correctness runs the real pipeline (JSONC load, profile resolution,
compilation) over every profile, so doctor and `generate` cannot disagree.
Redundancy is checked within the rule union each profile compiles to;
findings shared by several profiles are reported once. Output is grouped
under the location to fix (a fragment, `profile 'x'`, or a Claude settings
file), the location holding the most severe finding first. Per-entry
findings are grouped per fragment and list, one affected entry per line.
`dir` and `dir/**` are reported once, as the longer spelling:

```
bash/base.jsonc
  warning  subsumed-rule      deny: 3 entries already covered
                              • 'rm -fr' by 'rm'
                              • 'rm -r' by 'rm'
                              • 'rm -rf' by 'rm'

srt/base.jsonc
  warning  cwd-anchored-glob  filesystem.denyWrite: 24 entries anchored at the launch directory, not global
                              • '**/.env'
                              ...

doctor: 0 errors, 2 warnings, 0 info
```

The covering entry's fragment is shown only when it differs from the
covered entry's. A `duplicate-rule` is reported at the later fragment, the
redundant copy, and names the earlier one.

| Code | Severity | Meaning |
|---|---|---|
| `fragment-load` | error | A registered fragment is missing or not valid JSONC, used or not |
| `profile-compile` | error | A profile fails to compile: scalar conflict, opposing allow/deny, a write-only path, invalid shape. Profiles using a broken fragment are not reported again |
| `profile-incomplete` | warning | A profile selects no fragment for some source kind, so `-p NAME` fails. Legitimate for mixins used only via `extends` |
| `subsumed-rule` | warning | An entry is already covered by another entry in the same list: a path below a listed directory (`dir` and `dir/**` count as equal; `.` covers every relative path), a wildcard domain below a broader `*.` wildcard or `*` (a concrete host is never flagged: it is the only host `twsrt test` can probe for that wildcard), a Bash command extending a listed command (`rm -rf` under `rm`; Claude emits `Bash(rm *)`) |
| `duplicate-rule` | warning | The same entry appears in two fragments of one profile |
| `inherited-fragment` | warning | A profile selects a fragment its `extends` chain already selects |
| `redundant-extends` | warning | A profile extends a parent it already reaches through another parent |
| `unused-fragment` | warning | A registered fragment no profile selects |
| `unknown-srt-key` | warning | A top-level, `network.*` or `filesystem.*` key outside srt's config schema (sandbox-runtime 0.0.78) that twsrt does not map either. srt strips it without a word, so it reaches no agent. Typical case: a Claude-only key such as `excludedCommands`, which belongs in `[sandbox_overrides]`. Fragment-level, so `// doctor-ignore` does not apply |
| `symlinked-deny-path` | warning | A `denyRead`/`denyWrite` path reaches a symlink on disk and its real path is not denied too. srt keeps the unresolved spelling while Seatbelt matches the real path, so the deny is a no-op (bkmr 3686) |
| `broad-allow-write` | warning | `allowWrite` on or above `/`, `~`, `~/.config` or `~/Library`. With Claude Code every `allowWrite` path also auto-approves the edit tools (ADR 0002) |
| `claude-relative-sandbox-path` | warning | A relative or `**/` entry in `sandbox.filesystem.*` of a scanned Claude settings file. Claude anchors it at the settings-file root (`~/.claude`, the project root, or the `--settings` file's directory), not the launch cwd; use `Read()`/`Edit()` rules (bkmr 3742) |
| `narrow-allow-glob` | warning | A glob in `allowWrite`/`allowRead`: on macOS `dir/*` grants direct children only and `a/*/b` only the directory `b` itself; Linux drops the rule |
| `cwd-anchored-glob` | warning | A relative `**/x` entry protects or grants only below the directory the agent was launched in, not everywhere |
| `linux-drops-write-glob` | info | A glob in `denyWrite` holds on macOS only; srt drops write globs on Linux |
| `noop-glob-suffix` | info | A trailing `/**` is stripped by srt; the bare directory is the same rule |
| `wildcard-apex` | info | `*.x.com` without `x.com` in the same list: the apex is not matched |

### Silencing a finding

A trailing `// doctor-ignore` comment on a fragment line accepts its entries
as intended and silences every entry-level finding about them. Anything after
a colon is a free-text reason for the reader; doctor does not interpret it:

```jsonc
"allowWrite": [
  "~/.copilot",
  "~/.copilot/ide/**",  // doctor-ignore: spelled out for readers
  "~/legacy/**"         // doctor-ignore
],
"denyWrite": [
  "**/.env"             // doctor-ignore: project-local by design
]
```

- Only the entries on the comment's own line; a directive on a line of its
  own covers nothing.
- Applies to entry-level codes: `subsumed-rule`, `duplicate-rule`,
  `wildcard-apex`, `symlinked-deny-path`, `broad-allow-write` and the pattern
  traps. Errors and profile or fragment findings cannot be silenced; Claude
  settings files are JSON and carry no comments.
- All of an entry's findings go silent together; there is no per-code choice.
- `subsumed-rule` is silenced on the covered entry (the one reported), not
  the covering one. `duplicate-rule` is silenced by a directive in any of the
  fragments that list the entry.
- A directive applies to the same string in every list of its fragment.

Pattern semantics are from srt `117eb92` (v0.0.78), see
`thoughts/research/2026-10-02-srt-wildcard-semantics.md`. Not modelled
(deliberate simplifications): coverage by a glob entry and port-qualified
domains. `~/x` and its absolute spelling compare as equal.
Drift and the Claude settings symlink are out of scope; use `diff`.

## Sandbox probes

`twsrt test` answers one question: does the kernel enforce what
`~/.srt-settings.json` says? `diff` proves the file matches the fragments;
`test` proves the sandbox matches the file. It exercises the SRT wrapper only
(`srt -s <settings> -c`), not Claude Code's native sandbox, Codex, or the
Bash deny/ask rules. Design rationale: [ADR 0007](adr/0007-probes-are-derived-and-judged-differentially.md).

### Probe patterns

| Pattern | Guarantees | Details |
|---|---|---|
| Derived probes | the probe set follows the compiled settings; unprobeable rules show as `SKIP` | [Maintaining the probe set](#maintaining-the-probe-set) |
| Control vs. sandbox run | a block counts only if the same command works outside the sandbox | [Execution model](#execution-model) |
| OS-denial exception | a root-owned path denied below srt still passes, with a reason | [Execution model](#execution-model) |
| One-byte read | read denies are proven without leaking content (stdout discarded) | [Read probes](#read-probes) |
| Realpath twin | a deny that a symlink turns into a no-op shows as its own failing row | [Read probes](#read-probes) |
| Append-open write | write denies are proven without truncating or touching mtime | [Write probes](#write-probes) |
| Glob witness | a deny glob is observed on a matching file inside a writable root, below the glob's prefix | [Write probes](#write-probes) |
| HEAD request | domain rules are proven by connecting, regardless of HTTP status | [Network probes](#network-probes) |
| Allowlist canary | allowlist mode itself is on: a non-allowlisted host is blocked | [Network probes](#network-probes) |
| Section options | `--denyRead`, `--denyWrite`, … run one settings key's probes | below |
| Artifact cleanup | created files and witness directories are removed; pre-existing files never | [Write probes](#write-probes), [Known limits](#known-limits) |

### Execution model

Every effective rule becomes one or two probes. A probe is a plain `sh`
command with an expectation, and it runs twice:

```
 rule in ~/.srt-settings.json
        │  derive (reads the host: file or dir? symlink? exists?)
        ▼
 probe: command + expect (deny | allow)
        │
        ├──► control:  sh -c '<command>'                     exit code C
        │
        └──► sandbox:  srt -s <settings> -c '<command>'      exit code S
                                                             │
                                                             ▼
                                            verdict = judge(expect, C, S)
```

The control run is the fail-safe. Without it, `head` on a file that does
not exist or `curl` to a host that is down would exit non-zero and read as
"blocked". A deny rule passes when the very same command succeeds outside
the sandbox and fails inside it. One exception: when the control run is
refused by the OS itself (its stderr says `Operation not permitted`,
`Permission denied`, or `Read-only file system`, as for a root-owned
`/Library/Keychains`), the deny intent is met by a layer below srt, and the
probe passes with the reason "denied outside the sandbox too". Any other
control failure stays `INVALID`.

| expect | control C | sandbox S | status | meaning |
|---|---|---|---|---|
| deny | ≠ 0, other error | any | `INVALID` | the probe proves nothing (file absent, host unreachable) |
| deny | ≠ 0, OS permission denial | ≠ 0 | `PASS` | intent met before srt is involved (root-owned dir, read-only volume); reason says so |
| deny | ≠ 0, OS permission denial | 0 | `FAIL` | the sandbox is more permissive than a plain shell |
| deny | 0 | 0 | `FAIL` | not blocked: the rule is not enforced |
| deny | 0 | ≠ 0 | `PASS` | |
| allow | ≠ 0 | any | `INVALID` | an allow rule cannot be verified when the plain shell is refused too |
| allow | 0 | ≠ 0 | `FAIL` | blocked although allowed |
| allow | 0 | 0 | `PASS` | |
| any | — | — | `SKIP` | no concrete command could be derived (never executed) |
| any | — | — | `ERROR` | timeout, or `sandbox_apply` refused mid-run |

Probes run sequentially in a fixed order: read-deny, write-deny,
write-allow, net-allow, net-deny, then the allowlist canary. Each row is
printed as soon as its verdict is known.

Section options named after the settings keys run only that section's
probes and combine; without any, all run. `-k` narrows further.

| Option | Probes |
|---|---|
| `--denyRead` | read-deny, including `(realpath)` twins |
| `--denyWrite` | write-deny, including the denies implied by `denyRead` |
| `--allowWrite` | write-allow |
| `--allowedDomains` | net-allow and the allowlist canary, which proves the allowlist |
| `--deniedDomains` | net-deny |

`--json` reports each probe's `section`.

### Probe catalogue

| Rule | Host condition | Command | Expect | Leaves behind | `SKIP` when |
|---|---|---|---|---|---|
| `denyRead` path | regular file | `head -c 1 -- <file>` | deny | nothing | glob pattern; path absent |
| `denyRead` path | directory with a file inside | `head -c 1 -- <first regular file>` | deny | nothing | as above |
| `denyRead` path | directory without files | `ls -- <dir>` | deny | nothing | as above |
| `denyRead` path | symlink anywhere in the probed path | second probe on the realpath, rule shown as `<pattern> (realpath)` | deny | nothing | never |
| `denyWrite` `**/`-glob | — | `: >> <scratch>/<name>` | deny | file removed after each run | mid-path wildcard, `[...]`, single-segment glob (`~/keys/*.pem`) |
| `denyWrite` `<abs or ~>/**/`-glob | a writable directory below the prefix | `: >> <witness dir>/<name>` | deny | file removed after each run; witness dir after the whole run | no `allowWrite` directory below or around the prefix |
| `denyWrite` path (incl. every implied one from `denyRead`) | directory | `: >> <dir>/.twsrt-probe-<pid>` | deny | file removed after each run | path absent |
| `denyWrite` path | existing file | `: >> <file>` | deny | nothing | path absent |
| `allowWrite` path | directory (`.` = cwd) | `: >> <dir>/.twsrt-probe-<pid>` | allow | file removed after each run | glob; path absent |
| `allowWrite` path | existing file | `: >> <file>` | allow | nothing | glob; path absent |
| `allowedDomains` host | — | `curl -sS -m 10 -o /dev/null -I https://<host>/` | allow | nothing | wildcard (`*.`) |
| `deniedDomains` host | — | same curl | deny | nothing | wildcard |
| allowlist canary | — | same curl against `example.com`, `.org`, or `.net`, whichever is not allowlisted | deny | nothing | never |

### Read probes

- `head -c 1` reads a single byte: enough to trigger the kernel's
  `file-read*` check, cheap on large files.
- For a directory, the first regular file is found by a sorted walk at most
  four levels deep, ignoring symlinks; sorting makes the choice stable. A
  directory without files is probed with `ls`, which needs read permission
  on the directory itself.
- **Realpath twin.** On macOS, srt keeps a `denyRead` path unresolved in the
  Seatbelt profile when its symlink target lies outside the original tree,
  while Seatbelt matches the real vnode path. `denyRead: ["~/.aws"]` then
  blocks nothing when `~/.aws` is a symlink. Whenever the probed path
  resolves to something else, a second probe reads the same file through its
  real path. That row failing while the plain row passes is the signature of
  the symlink gap; the fix is to deny the real directory as well.

### Write probes

- **Every write probe is an append-open that writes nothing**, `: >> path`.
  The kernel checks write permission at `open()`, so the sandboxed run fails
  exactly when the rule denies writing. On a missing path `>>` creates an
  empty file; on an existing one it leaves size, content, and mtime
  untouched. There is deliberately no `>` redirect and no `printf`/`touch`:
  `>` would truncate, `touch` bumps mtime, and a wrong target path must never
  be able to lose data.
- **Glob rules** need a witness file that matches the glob. It is created
  in a temporary `.twsrt-test-*` directory below the first concrete
  `allowWrite` directory (falling back to cwd), because a deny glob can only
  be observed where writing is otherwise allowed. The witness name is
  derived from the last segment: `*` becomes `probe`, `?` becomes `x`, a
  trailing `**` becomes `<segment>/probe`:

  | glob | witness |
  |---|---|
  | `**/.env` | `.env` |
  | `**/*.pem` | `probe.pem` |
  | `**/serviceAccount*.json` | `serviceAccountprobe.json` |
  | `**/secrets/**` | `secrets/probe` |
  | `**/.github/workflows/**` | `.github/workflows/probe` |

  Convertible globs are `**/x` and `<prefix>/**/x` with a literal absolute
  or `~` prefix (`/**/.env`, `~/dev/los/**/.env`). A relative `**/x` matches
  below the launch cwd, so the scratch directory serves. An anchored glob
  needs its witness below the prefix (compared as real paths, like srt) and
  inside a writable root: the scratch directory if the prefix covers it
  (always for `/**/x`), else a temporary `.twsrt-test-*` directory in the
  first `allowWrite` directory below the prefix, or in the prefix itself
  when an `allowWrite` directory contains it. With neither, the probe is
  skipped: outside every write root the allowlist blocks the write anyway,
  so a block would prove nothing. Parent directories are created on the
  host beforehand so a sandboxed failure can only come from the deny rule.
  All scratch and witness directories are removed when the run ends.
- **Directory rules** create `.twsrt-probe-<pid>` inside the directory;
  existing files are never opened. **File rules** open the named file
  itself; a file that does not exist is skipped rather than created.
- A file a probe creates is removed after the control run and again after
  the sandboxed run, so both runs start from the same state and nothing is
  left behind, even on a timeout. A file that already existed at that path
  is never removed.

### Network probes

- `curl -I` sends a HEAD request with a 10-second limit. Exit code 0 means
  the connection was established; the HTTP status is irrelevant, so a 403
  or 405 still counts as reachable. Under srt the proxy refuses the
  `CONNECT` for a non-allowlisted host and curl exits non-zero.
- Wildcard entries (`*.github.com`) have no concrete host to dial and are
  skipped. Add the bare domain to the allowlist if you want it probed.
- The canary proves allowlist mode is active at all: it dials the first of
  `example.com`, `example.org`, `example.net` that is not allowlisted and
  expects the sandbox to block it. Without it, an empty or ignored allowlist
  would produce no failing row.
- The control run of a network probe really connects to the host from your
  machine, including for `deniedDomains` entries.

### Preflight and safety

- Before any probe, `test` resolves `srt` on `PATH`, reads its version from
  the `package.json` next to the binary (`srt --version` reports a
  hardcoded `1.0.0`), and runs `srt -s <settings> -c true`. If that fails
  the run aborts with exit `2`; `sandbox_apply: Operation not permitted`
  means srt cannot nest inside another sandbox, so run from a plain
  terminal rather than from Claude Code's Bash tool or Codex.
- The compiled settings are compared against the fragments first; drift is
  a warning (`srt canonical drift`), and the on-disk file is what gets
  probed, because that is what srt enforces. An unapplied fragment edit can
  therefore never pass as a green run.
- Command stdout is sent to `/dev/null` for both runs and never captured, so
  a failing deny probe cannot leak the secret it just read. Only stderr is
  kept, truncated to 400 characters; the control run's stderr is what
  distinguishes an OS permission denial from a broken probe.
- The control run executes each command as your user with full privileges:
  it reads one byte of each protected file and opens each writable file for
  append. Nothing is modified.
- `--timeout` (default 30 s) bounds each command; a timeout yields `ERROR`.

### Output and exit codes

One row per probe as it completes, then a detail block per
`FAIL`/`INVALID`/`ERROR` (reason, command, sandbox stderr), a summary of
every probe that did not pass (including `SKIP`s), and the counts. A clean
run prints only the table and the counts. `CTL` and `SBX` are the exit codes
of the control and sandboxed run.

```
srt 0.0.75, settings /Users/x/.srt-settings.json, 9 probes
STATUS   KIND       RULE               CTL SBX     MS  PROBE
PASS     read-deny  ~/.ssh               0   1     85  head -c 1 -- /Users/x/.ssh/config
FAIL     read-deny  ~/.aws (realpath)    0   0     90  head -c 1 -- /Users/x/configs/dot-aws/sso/cache/x.json
SKIP     read-deny  **/.env              -   -      -  glob pattern: no concrete probe
PASS     net-deny   example.com (not allowlisted)  0  56  412  curl -sS -m 10 -o /dev/null -I https://example.com/

FAIL read-deny ~/.aws (realpath)
  reason: not blocked: command succeeded inside the sandbox
  command: head -c 1 -- /Users/x/configs/dot-aws/sso/cache/x.json
--- summary ---
FAIL     read-deny  ~/.aws (realpath)  not blocked: command succeeded inside the sandbox
SKIP     read-deny  **/.env            glob pattern: no concrete probe
passed=7 failed=1 invalid=0 error=0 skipped=1
```

Exit codes: `0` every executed probe passed, `1` any `FAIL`, `INVALID`, or
`ERROR`, `2` configuration or settings missing, or the preflight failed (srt
not on `PATH`, unloadable settings, or `sandbox_apply` refused because twsrt
itself runs inside a sandbox).

`--json` prints this document instead of the table (warnings stay on stderr):

```json
{
  "srt_version": "0.0.75",
  "settings": "/Users/x/.srt-settings.json",
  "summary": {"total": 9, "passed": 7, "failed": 1, "invalid": 0, "error": 0, "skipped": 1},
  "results": [
    {
      "kind": "read-deny",
      "rule": "~/.aws (realpath)",
      "command": "head -c 1 -- /Users/x/configs/dot-aws/sso/cache/x.json",
      "expect": "deny",
      "status": "FAIL",
      "control_exit": 0,
      "sandbox_exit": 0,
      "control_stderr": "",
      "sandbox_stderr": "",
      "duration_ms": 90,
      "reason": "not blocked: command succeeded inside the sandbox"
    }
  ]
}
```

### Maintaining the probe set

There is no probe catalogue to maintain. Every probe is derived at run time
from the effective rules in the compiled settings file, so the tests follow
the rules and cannot fall out of sync:

```
 srt fragments (*.jsonc)
        │  twsrt generate -w
        ▼
 ~/.srt-settings.json                      read at test time
        │  derive_probes()
        ▼
 Probe(kind, rule, command, expect)
        │  run_probe(): control + sandbox
        ▼
 judge() → PASS | FAIL | INVALID | SKIP | ERROR
```

| To change | Edit | Consequence |
|---|---|---|
| which rules are probed | the registered fragments (`twsrt edit`), then `twsrt generate -w` | the probe set follows; no code change |
| how a rule becomes a command | `derive_probes` and its `_read_deny` / `_write_deny` / `_write_allow` / `_network` helpers in `src/twsrt/lib/probe.py`; glob witness placement in `_witness_dir` | new probe shape; update the [probe catalogue](#probe-catalogue) |
| what counts as a pass | `judge` in the same module | update the [verdict table](#execution-model) |

Derivation and verdict logic are covered by `tests/lib/test_probe.py` and
`tests/bin/test_cli_test.py`, which substitute a fake runner for
`subprocess.run`; the unit tests never execute a probe or invoke `srt`.

### Known limits

- **Enforcement, not intent.** Probes are derived from the rules that exist,
  so a rule never written produces no row and no failure. `test` cannot say
  that `~/.aws/credentials` is unprotected, only that every path already
  denied is enforced. The allowlist canary is the one assertion not derived
  from your own settings.
- Only the SRT wrapper is exercised. Claude Code's native sandbox consumes
  the same deny paths but is not probed.
- `denyRead` globs, wildcard domains, and globs with wildcards in a
  non-final segment are reported as `SKIP`, never silently dropped.
- Bash deny/ask rules are application-layer and out of scope.
- Probes run one after another; a long allowlist costs one HEAD request per
  domain.
- Cleanup runs after each run and on timeout, not on Ctrl-C or a crash. An
  interruption right after a control run can leave `.twsrt-probe-<pid>` in
  the probed directory, and `kill -9` can leave `.twsrt-test-*` directories.
  Find leftovers with
  `find ~ \( -name '.twsrt-probe-*' -o -name '.twsrt-test-*' \) 2>/dev/null`.

## Diagnostic output

Generated JSON, TOML, rules, and Copilot flags stay unstyled on stdout so
they can be piped. stdout carries a command's result; narration about side
effects goes to stderr, so `generate -w` leaves stdout capturable
(`--project -w` prints only the `.twsrt` directory there). Generators return
warnings as data and never write to the terminal; the CLI owns severity,
stream and color.

| Kind | Color | Stream |
|---|---|---|
| Error | red, bold | stderr |
| Warning | yellow | stderr |
| Write narration: `Wrote …`, `Would write …`, sync and migration notes, restart hints | green (done) / cyan | stderr |
| Report info: `test` header and summary, `edit -n` paths, preview section headers | cyan | stdout |
| Clean diff | green | stdout |
| Drift (canonical, agent target header) | yellow | stdout |
| Diff entry missing from target / extra in target | green `+` / red `-` | stdout |
| `doctor` severity: error / warning / info | bold red / yellow / cyan | stdout |
| Debug (`--verbose`) | dim cyan | stderr |

Colors are enabled only on an interactive terminal; `NO_COLOR` (even empty)
disables ANSI output. Long lines are never broken, so piped output stays
one entry per line. `diff` reports per target, naming each drifted file,
with the `+`/`-` legend printed once:

```
srt canonical: no drift
bash canonical: no drift
claude: 2 missing, 1 extra  /Users/x/.claude/settings.full.json
  + Bash(terraform)
  + Bash(terraform *)
  - Bash(docker run:*)

+ missing from target   - in target, not in sources
```

`--verbose` goes before the subcommand and reports lifecycle facts only:
selected profile, mode, agent names, counts, target paths, caught exception
tracebacks. It never prints policy contents, rule patterns, domains,
environment values, or credentials. `test` is the exception: with `-v` it
traces the whole run on stderr so a verdict can be reproduced by hand. In
order: the compiled profile, whether the settings file matches the
fragments, the resolved `srt` binary and where its version came from, the
preflight, the scratch directory, every derivation decision (which file
inside a deny directory is probed, symlink detection, why a rule is
skipped), the keyword filter, and per probe the control and sandboxed
command as copyable `exec:` lines, each followed by `exit=<code> in <ms>ms`
with the stderr tail, artifact cleanup, and the verdict with its reason:

```
Debug: exec: sh -c 'head -c 1 -- /Users/x/.ssh/config'
Debug: exit=0 in 12ms
Debug: exec: srt -s /Users/x/.srt-settings.json -c 'head -c 1 -- /Users/x/.ssh/config'
Debug: exit=1 in 88ms stderr: head: /Users/x/.ssh/config: Operation not permitted
Debug: verdict PASS read-deny ~/.ssh control=0 sandbox=1 101ms
```

Command stdout is still never captured or logged.

## Invariants

1. **The resolved profile is the single source of truth for an invocation.**
   JSONC fragments are human-maintained and never written by twsrt.
   Compiled canonical JSON and the managed sections of agent targets are
   artifacts, never hand-edited; `twsrt diff` detects drift in both. A hand
   edit to a managed section is overwritten on the next `generate -w`,
   giving a false sense of security.
2. **Canonical allows widen only the named sandbox boundary.** SRT
   `allowWrite` directories become Codex workspace roots, retaining inherited
   protected paths and deny globs. Lossy translations narrow or skip with a
   warning; Bash allows never become unsandboxed execution.
3. **A read-denied path is never writable.** Every `denyRead` path is
   compiled into `denyWrite`; a write-only path is a compile error.
4. **Selective merge owns only declared sections.** Everything else in a
   target file (hooks, MCP servers, projects, credentials) is preserved
   byte-for-byte where the format allows. With `[claude_sync]`, those
   unmanaged keys converge between the full and yolo targets on the next mode
   switch; drift between them is transient by design.
5. **Fail-safe on ambiguity.** Disabled canonical sandbox, malformed paths,
   conflicting fragments, incomplete profiles, and legacy Codex
   `sandbox_mode` in the managed file abort generation instead of guessing.
6. **Deterministic output.** The same config, profile and fragments produce
   identical output; rule sets are sorted, and no runtime state takes part
   in composition. One exception: the policy-file denies (invariant 8)
   follow `$HOME` (`~/…` spelling) and the symlinks on their paths, so
   `generate` and `diff` must run under the same `$HOME`.
7. **Project mode writes nothing global.** `generate --project` sends
   every canonical output and the Claude target to `./.twsrt/`, adds that
   directory to the compiled `denyWrite`, reads the global Claude target only
   as merge base, and never touches the symlink or the `[claude_sync]` donor.
   Rules are dropped per project by profile choice, never by subtraction.
   The global policy files stay write-denied (invariant 8).
8. **The policy is never writable by the agent it governs.** Every compile
   write-denies `config.toml` and every `[sources]` output and fragment path,
   whatever the profile selects, absolute (`~/…` under `$HOME`) and through
   a symlink also as the real path
   ([ADR 0008](adr/0008-policy-files-are-write-denied.md)).

## Extending twsrt

**A new agent** consumes the normalized rules and touches neither fragments
nor profiles nor other generators. Implement the `AgentGenerator` protocol
and register it:

```python
class PiMonoGenerator:
    @property
    def name(self) -> str:
        return "pimono"

    def generate(self, rules, config) -> str:
        ...  # translate SecurityRules to the agent's native format

    def compatibility_warnings(self, rules, config) -> list[str]:
        ...  # lossy or safety-relevant mappings, returned, never printed

    def diff(self, rules, target, config) -> DiffResult:
        ...  # compare generated against existing

GENERATORS["pimono"] = PiMonoGenerator()   # then: twsrt generate pimono
```

Decide per rule class what the agent can express and where it is lossy; new
agents get restrictions-only compilation by default (see
[Scope and roadmap](#scope-and-roadmap)).

**A new canonical source kind** needs an explicit adapter, because accepting
a format without domain semantics would be unsafe:

1. register the kind in `src/twsrt/lib/config.py`;
2. define its compiled-document validation and normalized-rule translation
   in `src/twsrt/lib/sources.py`, including which arrays are sets;
3. include the resulting document in `CompilationResult` if generators need
   source-specific metadata;
4. add configuration, profile-resolution, composition-conflict, compilation,
   write, and drift tests.

Profile inheritance, fragment lookup, JSONC parsing, structural union,
strict serialization, output staging, and canonical drift detection are
shared. The registration step is a security boundary: a new document format
cannot bypass validation merely because generic composition can merge its
JSON objects.

## Scope and roadmap

All three agents ship native OS sandboxes (Claude Code: built-in
Seatbelt/bwrap, opt-in; Copilot CLI: local sandbox in public preview; Codex:
kernel sandbox always-on). The durable core, deny paths and domains,
compiles into each of them with high fidelity. The Bash-rules app layer is
the per-agent best-effort supplement:

- **Bash-rules translation is Claude-primary and frozen for new agents.**
  Claude gets full deny/ask fidelity; Copilot keeps deny-only flags (deny
  takes precedence over `--yolo`); Codex gets forbidden-only escalation
  rules. New agents get restrictions-only compilation by default.
- **Copilot native sandbox** (`sandbox` key in Copilot settings.json) is the
  intended replacement for the flag-snippet generator, deferred while the
  feature is in public preview with an undocumented backend.
- **pi-mono** runs under the SRT wrapper today
  ([pi-extensions/sandbox](https://github.com/sysid/pi-extensions/tree/main/packages/sandbox));
  a native generator follows the [extension path](#extending-twsrt).
