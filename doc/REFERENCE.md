# twsrt Reference

Technical detail the [README](../README.md) links to: how the compiler
works, exactly what each agent receives, how `doctor` and `test` decide, and
how to extend twsrt. The README explains the concepts; the threat model and
rationale are in [SECURITY_CONCEPT.md](../SECURITY_CONCEPT.md).

## Contents

- [Configuration](#configuration)
- [CLI](#cli)
- [Compiler model](#compiler-model)
- [Rule mapping per agent](#rule-mapping-per-agent)
- [Claude sandbox key mapping](#claude-sandbox-key-mapping)
- [Claude merge example](#claude-merge-example)
- [Claude settings file](#claude-settings-file)
- [Claude per-project launch premise](#claude-per-project-launch-premise)
- [Codex translation rules](#codex-translation-rules)
- [Copilot flags](#copilot-flags)
- [Copilot native sandbox](#copilot-native-sandbox)
- [Doctor checks](#doctor-checks)
- [Sandbox probes](#sandbox-probes)
- [Diagnostic output](#diagnostic-output)
- [Invariants](#invariants)
- [Extending twsrt](#extending-twsrt)
- [After an srt upgrade](#after-an-srt-upgrade)
- [Scope and roadmap](#scope-and-roadmap)

## Configuration

`config.toml` (default `~/.config/twsrt/config.toml`, override with `-c`). Relative
paths resolve from its directory; `~` and absolute paths work everywhere. `twsrt
config --init` writes the required keys and every optional key commented out with
its default. Unknown keys are load errors; nothing is silently ignored.

| Key | Required | Meaning |
|---|---|---|
| `schema_version` | yes | `1` |
| `default_profile` | yes | Profile compiled when `-p` is omitted |
| `[sources.srt]` | yes | Filesystem and network policy |
| `[sources.bash]` | no | Command rules. Without it no `bash-rules.json` is compiled, no agent gets Bash entries, and a profile, `show` or `edit` naming `bash` fails |
| `[sources.<kind>].output` | no | Compiled document; default `srt-settings.json` / `bash-rules.json` next to `config.toml` |
| `[sources.<kind>.fragments.<name>].path` | ≥ 1 per kind | A `.jsonc` fragment |
| `[profiles.<name>]` | ≥ 1 | `extends = [profile, …]` plus `srt = […]`, `bash = […]` fragment names |
| `[targets]` | no | Agent files, below |

| `[targets]` key | Agent | Notes |
|---|---|---|
| `claude_settings` | `claude` | Must be named `settings.json`, the only user file Claude Code reads |
| `codex_config` | `codex` | |
| `codex_rules` | `codex` | Optional `forbidden` rules file; requires `codex_config` |
| `copilot_settings` | `copilot` | Native sandbox in `~/.copilot/settings.json` |
| `copilot_output` | `copilot` | Flag snippet; independent of `copilot_settings` |
| `copilot_jetbrains_xml` | `copilot-jetbrains` | List, one `github-copilot.xml` per IDE product and version |

Keys removed in 4.0 (`claude_settings_yolo`, `copilot_output_yolo`, `claude_sync`,
`sandbox_overrides`) are load errors naming their replacement (ADR 0010).

srt itself reads only `~/.srt-settings.json`; a missing file runs srt with built-in
defaults and no `denyRead`. With the default `output`, launch `srt -s <output>`.

## CLI

Global options go before the subcommand: `-c/--config PATH`, `-v/--verbose`,
`-V/--version`. Results go to stdout, notices to stderr
([Diagnostic output](#diagnostic-output)).

| Command | Behaviour |
|---|---|
| `config [--init]` | Opens `config.toml` in `$EDITOR` (fallback `vi`). `--init` first creates it and starter fragments, never overwriting an existing file |
| `edit [srt\|bash\|all] [-p P] [-n]` | Opens every registered fragment (only profile P's with `-p`) in one editor call, then compiles and reports canonical drift; a fragment that no longer compiles exits `1`. A bare `vim`, `nvim`, `gvim` or `mvim` gets `-p` (one tab per file); an `$EDITOR` with arguments is passed through. `-n` lists the paths |
| `profiles` | Every profile with parents and resolved fragments; `*` marks `default_profile`, inherited fragments are dimmed, `invalid` marks one that does not compile on its own |
| `show [srt\|bash] [-p P]` | The compiled canonical document exactly as `-w` writes it |
| `generate [agent] [-p P]` | Preview: the agent translation on stdout, the files `-w` would write on stderr. Same compile and merge checks as `-w` |
| `generate [agent] [-p P] -w` | Writes every canonical output and the selected agents' targets, each atomically, only after all rendered |
| `diff [agent] [-p P]` | Exit `0` clean, `1` drift, `2` a target missing |
| `test …` | [Sandbox probes](#sandbox-probes) |
| `doctor …` | [Doctor checks](#doctor-checks) |

Agents: `claude`, `codex`, `copilot`, `copilot-jetbrains`, `all` (default). An agent
without its `[targets]` key is skipped with an `Info:` note and exit `0`, whether
named or reached through `all`; with no agent configured, `generate -w` writes only
the canonical outputs. Likewise `show bash` and `edit bash` without `[sources.bash]`.

**`generate --project`** writes profile P (default `default_profile`) to
`./.twsrt/P/` of the current directory and touches no global file:

| Aspect | Behaviour |
|---|---|
| Outputs | `srt-settings.json`, `bash-rules.json` (with `[sources.bash]`), `claude-settings.json`; `./.twsrt/.gitignore` = `*`; stdout prints the absolute `./.twsrt/P` |
| Agents | `all` means `claude`; `codex`, `copilot`, `copilot-jetbrains` are rejected (they read no per-launch settings file) |
| Claude target | Merged from the global `claude_settings`, which therefore must be configured |
| Added deny | The absolute path of `./.twsrt` joins `denyWrite`; global policy files stay denied |
| Refused | A symlinked `./.twsrt` or `./.twsrt/P` (a cloned repository could redirect the write); 3.x files directly in `./.twsrt` (a 3.x launcher would keep loading a frozen policy). Profile names that differ only in case or Unicode normalization are already a load error |

Why the launch line works: [Claude per-project launch premise](#claude-per-project-launch-premise).

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
| Source kind | One canonical document type with its fragment registry, compiled output, validation, and rule translation. `srt` (required) and `bash` (optional) are registered. |
| Fragment | A named `.jsonc` object holding one reusable policy slice. Fragments never reference each other. |
| Profile | Selects ordered fragment names per source kind; may extend other profiles. |
| Resolved profile | Parent-first, stable-deduplicated fragment order for one invocation. |
| Compiled document | Strict JSON from composing one source kind's selected fragments. |
| Agent target | Configuration derived from the normalized rules after compilation succeeds. |

### Phases

| Phase | Input | Fails on |
|---|---|---|
| Configuration loading | `config.toml` | Unknown or removed keys, unknown schema version, legacy source paths, unknown source kinds, duplicate outputs, a fragment path equal to its own kind's output, a fragment path not ending in `.jsonc`, unknown parents or fragments, inheritance cycles, colliding profile directory names |
| Profile resolution | Profile name (`default_profile` unless `-p`) | Unknown profile; a source kind with no selected fragment |
| JSONC parsing | Selected `.jsonc` files | Duplicate keys, trailing commas, single-quoted or unquoted keys, `NaN`/infinities, non-object roots, malformed comments |
| Composition | Parsed objects | Unequal scalars, incompatible types |
| Domain validation | Each fragment and the composed document | Invalid field shapes, unknown Bash actions, a value in opposing lists (even within one fragment) |
| Required srt lists | Composed srt document | Never fails: each missing required list is added as `[]`, so an unset `allowedDomains` allows no domain |
| Write-deny implication | Composed srt document | A path in both `denyRead` and `allowWrite` (the error names profile and path, not fragments) |
| Translation and write | Compiled documents | Any rendering conflict; nothing is written until every target rendered, and each file is replaced atomically |

Each source kind owns a fragment namespace and exactly one compiled output
(`config.DEFAULT_OUTPUT_NAMES`, the same names `--project` uses in
`./.twsrt/<profile>/`). Unknown source kinds fail instead of being composed
without validation or translation semantics.

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
| Arrays | Deduplicated union. Rule arrays known to be sets (`filesystem.allowWrite`/`denyWrite`/`denyRead`, `network.allowedDomains`/`deniedDomains`/`allowUnixSockets`, `ignoreViolations.*`, Bash `allow`/`ask`/`deny`) are sorted, so output is independent of fragment order; every other array keeps first-seen order, because an unknown pass-through list may be a sequence such as argv |
| Equal scalars | Keep the value |
| Unequal scalars, different JSON types | Fail with profile, source kind, JSON pointer and both fragment paths |

Domain validation rejects the same value in opposing lists, also within one
fragment: srt `allowedDomains`/`deniedDomains` and `allowWrite`/`denyWrite`;
any two of Bash `allow`/`ask`/`deny`. There is no "safer value wins"
heuristic: it would be source-specific and could conceal an authoring error.

**Required lists.** srt refuses a settings file lacking any of
`filesystem.denyRead`/`allowWrite`/`denyWrite` or
`network.allowedDomains`/`deniedDomains` (srt 0.0.83: `network.deniedDomains:
Required`). Each one no fragment sets is added as `[]`.

**Write denies are implied.** After composition every `denyRead` path is
added to `denyWrite` (`sources._imply_write_denies`), plus the absolute path
of `./.twsrt` under `--project`, plus the policy files: `config.toml` and every `[sources]`
output and fragment path (`AppConfig.policy_files`), absolute (`~/…` under
the home directory) and, behind a symlink, also as the real path. `--project`
keeps protecting the global outputs. A path in both `denyRead` and `allowWrite` asks for write-only
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

`—` = no output. The Copilot column shows the flag snippet. With
`copilot_settings`, paths and domains go into Copilot's native sandbox instead
([Copilot native sandbox](#copilot-native-sandbox)) and the URL flags are not
emitted; in flags-only mode the SRT wrapper enforces paths and domains.

| Canonical rule | Claude Code | Copilot flags | Codex |
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

**No modes.** The selected profile alone decides the output; `ask` rules are never
dropped. How a session answers them is a launch flag
([ADR 0010](adr/0010-no-modes-profiles-select-policy.md),
[README](../README.md#prompting-is-a-launch-choice)).

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

Claude Code's `sandbox` section has 18 configurable keys. twsrt manages a
subset from the compiled SRT document and two keys with a fixed value.

| Claude Code key | SRT source | Status |
|---|---|---|
| `sandbox.network.allowedDomains` | `network.allowedDomains` | Managed |
| `sandbox.network.deniedDomains` | (none) | Not generated: `deniedDomains` become `WebFetch(domain:X)` deny rules only |
| `sandbox.network.allowLocalBinding` | `network.allowLocalBinding` | Managed (pass-through) |
| `sandbox.network.allowUnixSockets` | `network.allowUnixSockets` | Managed (pass-through) |
| `sandbox.network.allowAllUnixSockets` | `network.allowAllUnixSockets` | Managed (pass-through) |
| `sandbox.network.allowMachLookup` | `network.allowMachLookup` | Managed (pass-through) |
| `sandbox.network.httpProxyPort` | `network.httpProxyPort` | Managed (pass-through) |
| `sandbox.network.socksProxyPort` | `network.socksProxyPort` | Managed (pass-through) |
| `sandbox.filesystem.allowWrite` | `filesystem.allowWrite` | Managed-empty; emitted as `Edit` allow rules instead (a raw entry anchors relative paths at the settings-file root, ADR 0002) |
| `sandbox.filesystem.denyWrite` | `filesystem.denyWrite` | Managed-empty; emitted as `Edit` deny rules instead |
| `sandbox.filesystem.denyRead` | `filesystem.denyRead` | Managed-empty; emitted as `Read`/`Edit` deny rules instead |
| `sandbox.enabled` | (fixed) | Always `true`; a canonical `enabled: false` is refused. Absent would mean off in Claude |
| `sandbox.enableWeakerNetworkIsolation` | `enableWeakerNetworkIsolation` | Managed (pass-through) |
| `sandbox.enableWeakerNestedSandbox` | `enableWeakerNestedSandbox` | Managed (pass-through) |
| `sandbox.ignoreViolations` | `ignoreViolations` | Managed (pass-through) |
| `sandbox.excludedCommands` | (none) | Claude-only; preserved. Each entry opens the sandbox and is not part of the policy |
| `sandbox.autoAllowBashIfSandboxed` | (none) | Claude-only; preserved |
| `sandbox.allowUnsandboxedCommands` | (fixed) | Always `false`; `diff` reports a hand edit |

**Pass-through** keys are copied verbatim; one absent from SRT is removed from
the target, so nothing another profile or a hand edit loosened survives a
write. To keep such a key, set it in an SRT fragment.
Every srt key not in this table is forwarded to no agent, valid or not
(`sources.py` allowlists): for example `allowPty` (Claude Code ignores
`sandbox.allowPty`), `filesystem.allowRead`, `allowGitConfig`,
`allowNestedUserNamespaces`, `allowAppleEvents` and the newer `network.*`
proxy options. They still reach srt itself through the canonical file.
`doctor` reports only keys outside srt's schema (`unknown-srt-key`), not these.
The three managed-empty filesystem lists are always emitted as `[]` so a write
clears stale values generated by older twsrt versions.

**Why the deny lists are empty.** Claude Code folds `Read`/`Edit` permission
deny rules into the native OS sandbox profile. twsrt relies on that merge to
enforce canonical `denyRead`/`denyWrite` paths without duplicating them under
`sandbox.filesystem`, which previously expanded the Seatbelt profile past
macOS `ARG_MAX` (E2BIG on every Bash call). Consequently these keys
cannot be set by hand; define paths in SRT fragments.

**Canary after every Claude Code upgrade.** From sandboxed Bash, reading and
moving a configured read-deny path must fail, and writing a configured
relative deny such as a cwd `.env` must fail. If any probe succeeds, stop
using the generated configuration and reconsider direct
`sandbox.filesystem` emission.

**Admin-required sandbox.** From a `--settings` file (`generate --project`),
`allowUnsandboxedCommands: false` makes the sandbox admin-required (Claude Code
2.1.285 or later): a repository's `.claude/settings*.json` can then no longer
loosen it, except through `autoAllowBashIfSandboxed`. From user settings the same
key does not have that effect.

## Claude merge example

`generate -w claude` rewrites only what twsrt owns:

| Section | Handling |
|---|---|
| `permissions.deny`, `permissions.ask` | replaced |
| `permissions.allow` | `WebFetch(domain:…)` and `Edit(…)` entries replaced (twsrt owns them); other allows kept |
| `sandbox.network`, `sandbox.filesystem`, `sandbox.*` | managed keys replaced, pass-through keys the policy does not set removed; Claude-only keys kept; `denyRead`/`denyWrite`/`allowWrite` reset to `[]` |
| everything else (hooks, plugins, model, theme, …) | kept |

Existing hand-maintained `~/.claude/settings.json`:

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
`git push` (the `Edit(...)` denies for the policy files, added by every compile,
are left out for brevity):

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
      "WebFetch(domain:*.github.com)",
      "WebFetch(domain:github.com)"
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
      "allowedDomains": ["*.github.com", "github.com"]
    },
    "autoAllowBashIfSandboxed": true,
    "excludedCommands": ["docker"],
    "filesystem": { "denyRead": [], "denyWrite": [], "allowWrite": [] },
    "enabled": true,
    "allowUnsandboxedCommands": false
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
  hooks                     ← PRESERVED
  additionalDirectories     ← PRESERVED
  sandbox.network
    ├─ allowedDomains       ← REPLACED
    └─ allowLocalBinding    ← REMOVED   (managed; not set in SRT)
  sandbox.filesystem
    ├─ denyRead             ← RESET to [] (enforced through permission rules)
    ├─ denyWrite            ← RESET to []
    └─ allowWrite           ← RESET to []
  sandbox.enabled           ← SET to true
  sandbox.allowUnsand...    ← SET to false
  sandbox.autoAllowBash...  ← PRESERVED
  sandbox.excludedCommands  ← PRESERVED
```

## Claude settings file

Claude Code reads exactly one user settings file, `settings.json` in its config
directory, and writes runtime changes (model, theme, hooks added in the UI) into
it. `claude_settings` must name that file; any other file name is a load error.

`generate -w claude` reads it, replaces the managed sections and writes the
result atomically (`os.replace`). A missing file or a dangling symlink counts as
empty. A symlink (the one twsrt 3.x maintained, or one from a dotfiles manager)
is replaced by a regular file holding the linked file's content plus the policy;
the linked file itself is not changed. A symlinked *directory* (`~/.claude` into a
dotfiles repository) is unaffected. A file that is not a JSON object, or in which
a section twsrt reads has the wrong type (`"sandbox": null`), stops preview, `-w`
and `diff` with an error naming the file and key; nothing is written.

Claude Code watches the user, project, local and managed settings files,
symlink targets included, and applies most edits to running sessions. A
`--settings` file is not watched (Claude Code 2.1.331, documented and read from
the binary), so `--project` sessions keep the policy they started with.

## Claude per-project launch premise

Not relevant for `srt`. `generate --project` is only useful for Claude if Claude is launched as:

```bash
claude --setting-sources project,local --settings .twsrt/<profile>/claude-settings.json
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
| 6 | User, project, local and managed settings files are watched and reloaded mid-session; a `--settings` file is not | documented, settings.md "When edits take effect"; watcher skips `flagSettings` (2.1.331 binary) |
| 7 | `allowUnsandboxedCommands: false` from `--settings` makes the sandbox admin-required | documented, sandboxing.md (2.1.285 or later) |

Claims 2 and 3 are why a project cannot drop a rule by layering a file on
top: only not loading the global file works (claims 4 and 5). `./.twsrt` is added
to `denyWrite` because an agent able to write it could loosen a later launch.

**Refused directories.** `--project` fails, preview included, while `./.twsrt` or
`./.twsrt/<profile>` is a symlink (a cloned repository could redirect the write)
or `./.twsrt` directly holds a file twsrt 3.x wrote there (`srt-settings.json`,
`bash-rules.json`, `claude-settings[.yolo].json`): a launcher on the old path
would keep loading that frozen policy. Delete what the error names.

**Consequences:**

- `X` replaces the user scope completely, so it carries the user keys too.
  It is built by `selective_merge` from the global Claude target. A hook or
  plugin added to the global file appears in a project session on the next
  launch, since every launch regenerates `X`. Preferences changed inside such a
  session may not persist: the user file is not one of its sources.
- The repository's `.claude/settings.json` and `.claude/settings.local.json`
  still load and can add rules. They cannot loosen the sandbox (claim 7), except
  through `autoAllowBashIfSandboxed`; a plain `claude` launch lacks that lock.
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
2. `claude --setting-sources project,local --settings .twsrt/<profile>/claude-settings.json`
3. `/permissions`: rule R is absent and the other twsrt denies are present.
4. A deny that exists only in `~/.claude/settings.json` (not in any
   fragment) is absent from `/permissions`: proves the user file was skipped.
5. Ask the agent to `echo x >> .twsrt/<profile>/claude-settings.json`: refused.

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
  entries are skipped with a warning. `allowAllUnixSockets: true` becomes
  `network.dangerously_allow_all_unix_sockets = true`.
- `network.enabled = true` is always emitted; the `domains` table does the
  filtering.

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
lookup (without a warning), violation-reporting exceptions, weaker-isolation
switches. A disabled canonical SRT sandbox, a `/~/...` path or a relative path
containing `..` fails generation.

**Legacy sandbox guard.** A top-level `sandbox_mode` or `sandbox_workspace_write`
in the owned `config.toml` fails generation (`_reject_legacy_sandbox`). The same
keys inside a `[profiles.*]` table, in any other Codex config layer (managed,
project), or `--sandbox` on the CLI make Codex silently ignore
`default_permissions`; twsrt cannot see them and warns, with a `codex doctor`
hint, whenever it renders the Codex target ([SECURITY_CONCEPT
§7.3](../SECURITY_CONCEPT.md#73-codex-profile-silent-deactivation)). Permission
profiles are Beta and `.rules` Experimental upstream. Restart Codex after
generating.

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

| Canonical rule | Flag |
|---|---|
| any `allowWrite` | `--allow-tool 'shell'`, `'read'`, `'edit'`, `'write'`, emitted once |
| `allowedDomains` | `--allow-url 'X'`, only without `copilot_settings` |
| `deniedDomains` | `--deny-url 'X'`, only without `copilot_settings` |
| Bash `deny` | `--deny-tool 'shell(c)'` |
| Bash `ask` | `--deny-tool 'shell(c)'` + warning |
| `denyRead`, `denyWrite` | — (native sandbox or SRT wrapper enforces) |

Deny flags take precedence over every allow, `--allow-all-tools` and `--yolo`
included. twsrt never emits `--yolo`.
Copilot has no "ask before running" tier, so an ask rule becomes a deny, the
fail-safe direction:

```
Warning: Bash ask rule 'git push' mapped to --deny-tool for copilot (no ask equivalent)
```

These flags exist only in the `copilot_output` file. With `copilot_settings`
alone, Bash deny and ask rules reach no Copilot CLI file;
twsrt warns that they are not enforced instead.

## Copilot native sandbox

Copilot CLI has two modes, chosen by the `[targets]` keys
([ADR 0009](adr/0009-copilot-native-sandbox.md)). Never combine them: run
Copilot either with its native sandbox or under srt.

| Mode | Keys | Paths and domains enforced by | Bash rules |
|---|---|---|---|
| Native sandbox (recommended) | `copilot_settings`, optionally `copilot_output` | Copilot's sandbox, from `settings.json` | Only via `copilot_output` flags; without it not enforced (warned) |
| Flags only | `copilot_output` | srt: `srt -c "copilot --allow-tool 'shell' --deny-tool 'shell(rm)' --allow-url 'github.com' …"` | `--deny-tool` flags |

Copilot confines shell, MCP and LSP processes at OS level; its file tools and
web fetch are checked in software only, so the snippet's `--allow-tool 'read'`,
`'edit'`, `'write'` rely on that check. Copilot itself keeps `.git/hooks` and
`.git/config` read-only. srt-only fields (`allowUnixSockets`, `allowMachLookup`,
`enableWeakerNetworkIsolation`, `ignoreViolations`) do not translate (warned);
Copilot's own Seatbelt profile decides, and docker.sock, ssh-agent and the
pasteboard were blocked in probes.

The JetBrains plugin reads its own `github-copilot.xml` per IDE product and
version, not `~/.copilot/settings.json`, and has no URL rules, no LSP/extension
switch and no environment masking (warned). After an IDE upgrade, add the new
config directory's file to `copilot_jetbrains_xml`; twsrt does not discover them.

One policy builder (`src/twsrt/lib/copilot_sandbox.py`) feeds two targets
([ADR 0009](adr/0009-copilot-native-sandbox.md)): `copilot` merges keys into
`~/.copilot/settings.json`, `copilot-jetbrains` merges options into each
`github-copilot.xml`. Every path is emitted absolute (`~` expanded, one
trailing `/**` removed); lists are deduplicated and sorted.

| Canonical | `settings.json` | `github-copilot.xml` |
|---|---|---|
| `denyRead` literal (existing or not) | `sandbox.userPolicy.filesystem.deniedPaths` | `<sandboxDeniedPaths>` |
| `denyWrite` literal, not also `denyRead` | `…readonlyPaths` | `<sandboxReadonlyPaths>` |
| `allowWrite` literal | `…readwritePaths` (dropped and warned if equal to a deny) | `<sandboxReadwritePaths>` |
| `allowWrite` `.` / `.git` | `addCurrentWorkingDirectory: true` / nothing (granted natively) | `sandboxAddCurrentWorkingDirectory` |
| glob below a fixed prefix (`~/x/*/y`) | expanded at generate time (warned snapshot) | same |
| other globs, cwd-relative entries | dropped, one warning | same |
| `allowedDomains` non-empty | `…network.allowedHosts` (`:port` stripped, warned), `allowOutbound: true` | `<sandboxAllowedHosts>`, `sandboxAllowOutboundNetwork` |
| no `allowedDomains` | `allowOutbound: false`, empty `allowedHosts` | `sandboxAllowOutboundNetwork=false` |
| `deniedDomains` | `…network.blockedHosts` | `<sandboxBlockedHosts>` |
| `allowLocalBinding` | `allowLocalNetwork` (always written; warned when true) | `sandboxAllowLocalNetwork` (IDE default is `true`) |
| `allowedDomains` / `deniedDomains` | top-level `allowedUrls` / `deniedUrls` | — (no URL rules) |
| Copilot's own targets (`copilot_settings`, each `copilot_jetbrains_xml`) | added to `readonlyPaths`, link and real spelling | same |
| canonical `enabled: false` | error | error |

Fixed values: `enabled`/`sandboxEnabled` true, MCP servers sandboxed, bypass
off, keychain off, dev-tool access on, git and gh authentication on; CLI only
also LSP servers and extensions sandboxed.

**Why an empty allowlist turns the network off.** srt reads an empty
`allowedDomains` as "no network"; Copilot reads an empty `allowedHosts` as "no
restriction". Emitting the empty list would invert the policy.

**Ownership and drift.** `settings.json`: twsrt owns `sandbox`,
`allowedUrls`, `deniedUrls` and compares them by JSON value; everything else is
ignored. `github-copilot.xml`: twsrt owns the ten `sandbox*` options and five
lists of component `github-copilot`; `diff` treats an absent option as its
IntelliJ default (the IDE omits defaults when it saves), so an IDE save is not
drift. `sandboxProxyUrl` and `enableCloudSandbox` stay the user's.

**Writes.** Both files are written atomically. A JetBrains file whose IDE
holds `<config>/.lock` is skipped with a warning; everything else is still
written and the command exits 0. A lock left behind by a crashed IDE has the
same effect until it is removed. XML comments in the file are preserved.
`diff` reports a missing JetBrains file as drift, whichever position it has in
`copilot_jetbrains_xml`.

## Doctor checks

`twsrt doctor` reads `config.toml`, every registered fragment, and the Claude
settings files that can carry sandbox paths (the twsrt Claude target and
`./.claude/settings.json` / `settings.local.json` of the current
directory). It writes nothing, and prints one line per finding on stdout followed by a count
(`doctor: no findings` when there are none).
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
| `profile-generate` | error | A profile compiles, but a configured agent refuses it, e.g. `enabled: false`; one finding per agent |
| `profile-incomplete` | warning | A profile selects no fragment for some source kind, so `-p NAME` fails. Legitimate for mixins used only via `extends` |
| `subsumed-rule` | warning | An entry is already covered by another entry in the same list: a path below a listed directory (`dir` and `dir/**` count as equal; `.` covers every relative path), a wildcard domain below a broader `*.` wildcard or `*` (a concrete host is never flagged: `twsrt test` checks a wildcard only by srt's filter decision, the concrete host is its only end-to-end probe), a Bash command extending a listed command (`rm -rf` under `rm`; Claude emits `Bash(rm *)`) |
| `duplicate-rule` | warning | The same entry appears in two fragments of one profile |
| `inherited-fragment` | warning | A profile selects a fragment its `extends` chain already selects |
| `redundant-extends` | warning | A profile extends a parent it already reaches through another parent |
| `unused-fragment` | warning | A registered fragment no profile selects |
| `unknown-srt-key` | warning | A top-level, `network.*` or `filesystem.*` key outside srt's config schema (sandbox-runtime 0.0.83; refresh with `make srt-schema-check`, see [After an srt upgrade](#after-an-srt-upgrade)) that twsrt does not map either. srt strips it without a word, so it reaches no agent. Typical case: a Claude-only key such as `excludedCommands`, which belongs in Claude's own `settings.json`. Fragment-level, so `// doctor-ignore` does not apply |
| `symlinked-deny-path` | warning | A `denyRead`/`denyWrite` path reaches a symlink on disk and its real path is not denied too. srt keeps the unresolved spelling while Seatbelt matches the real path, so the deny is a no-op (bkmr 3686) |
| `broad-allow-write` | warning | `allowWrite` on or above `/`, `~`, `~/.config` or `~/Library`. With Claude Code every `allowWrite` path also auto-approves the edit tools (ADR 0002) |
| `claude-relative-sandbox-path` | warning | A relative or `**/` entry in `sandbox.filesystem.*` of a scanned Claude settings file. Claude anchors it at the settings-file root (`~/.claude`, the project root, or the `--settings` file's directory), not the launch cwd; use `Read()`/`Edit()` rules (bkmr 3742) |
| `narrow-allow-glob` | warning | A glob in `allowWrite`/`allowRead`: on macOS `dir/*` grants direct children only and `a/*/b` only the directory `b` itself; Linux drops the rule |
| `cwd-anchored-glob` | warning | A relative `**/x` entry protects or grants only below the directory the agent was launched in, not everywhere |
| `linux-drops-write-glob` | info | A glob in `denyWrite` holds on macOS only; srt drops write globs on Linux |
| `noop-glob-suffix` | info | A trailing `/**` is stripped by srt; the bare directory is the same rule |
| `wildcard-apex` | info | `*.x.com` in `allowedDomains` without `x.com`: the apex is not matched |
| `wildcard-deny-apex` | warning | `*.x.com` in `deniedDomains` without `x.com`: the apex is not denied. Claude's `WebFetch` deny skips it, and srt blocks it only while no `allowedDomains` entry (such as `*`) admits it |

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
  `wildcard-apex`, `wildcard-deny-apex`, `symlinked-deny-path`, `broad-allow-write` and the pattern
  traps. Errors and profile or fragment findings cannot be silenced; Claude
  settings files are JSON and carry no comments.
- All of an entry's findings go silent together; there is no per-code choice.
- `subsumed-rule` is silenced on the covered entry (the one reported), not
  the covering one. `duplicate-rule` is silenced by a directive in any of the
  fragments that list the entry.
- A directive applies to the same string in every list of its fragment.

Pattern semantics were verified against srt `117eb92` (v0.0.78). Not modelled
(deliberate simplifications): coverage by a glob entry and port-qualified
domains. `~/x` and its absolute spelling compare as equal.
Drift is out of scope; use `diff`.

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
| Proxy verdict | a wildcard domain is proven by srt's answer to a made-up subdomain, no DNS needed | [Network probes](#network-probes) |
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

Wildcard domain probes are the exception to the two-run model: they have no
control run and are judged by srt's proxy answer, see
[Network probes](#network-probes).

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
| deny, wildcard | — | proxy `403` | `PASS` | srt's filter refused the host |
| deny, wildcard | — | proxy other | `FAIL` | not blocked: the filter let it through |
| allow, wildcard | — | proxy `403` | `FAIL` | blocked although allowed |
| allow, wildcard | — | proxy other (`200`, `502`) | `PASS` | the filter let it through; `502` only means the made-up host does not resolve |
| any, wildcard | — | proxy `000` or none | `ERROR` | curl never reached the proxy, nothing was judged |

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
| `allowedDomains` host | — | `curl -sS -m 10 -o /dev/null -I https://<host>/` | allow | nothing | other wildcard shapes (`*`, `api.*.x`) |
| `deniedDomains` host | — | same curl | deny | nothing | as above |
| `allowedDomains` / `deniedDomains` `*.x` | — | `curl -sS -m 10 -o /dev/null -w '%{http_connect}' https://twsrt-probe.x/`, sandboxed run only | allow / deny | nothing | never |
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
- **Wildcard entries** (`*.github.com`) are probed with the made-up
  subdomain `twsrt-probe.github.com` (a port suffix is kept). srt's proxy
  decides on the hostname before any DNS lookup, so the host need not exist.
  curl prints the proxy's answer to its `CONNECT` (`%{http_connect}`): `403`
  is srt's policy denial (`X-Proxy-Error: blocked-by-allowlist`), anything
  else means the filter let it through (`502` when the host does not
  resolve). That answer is the witness, so there is no control run, and
  curl's exit code is ignored: a missing curl or a broken sandbox yields
  `ERROR` (`000`), never a false `PASS`. `*.x` never matches the apex `x`;
  `twsrt doctor` reports a deny wildcard without its apex
  (`wildcard-deny-apex`). `*` and mid-label wildcards stay `SKIP`.
- The canary proves allowlist mode is active at all: it dials the first of
  `example.com`, `example.org`, `example.net` that is not allowlisted and
  expects the sandbox to block it. Without it, an empty or ignored allowlist
  would produce no failing row.
- The control run of a network probe really connects to the host from your
  machine, including for `deniedDomains` entries.

### Preflight and safety

- Before any probe, `test` resolves `srt` on `PATH`, reads its version from
  the package root's `package.json` (`<realpath of srt>/../../package.json`;
  `srt --version` reports a
  hardcoded `1.0.0`), and runs `srt -s <settings> -c true`. If that fails
  the run aborts with exit `2`; `sandbox_apply: Operation not permitted`
  means srt cannot nest inside another sandbox, so run from a plain
  terminal rather than from Claude Code's Bash tool or Codex.
- The compiled settings are compared against the fragments first; drift is
  a warning (`srt canonical drift`), and the on-disk file is what gets
  probed, because that is what srt enforces. An unapplied fragment edit can
  therefore never pass as a green run.
- Command stdout is sent to `/dev/null` for both runs and never captured, so
  a failing deny probe cannot leak the secret it just read. The one
  exception is a wildcard domain probe, whose stdout is curl's three-digit
  `CONNECT` status and nothing else (the body goes to `/dev/null`). Only stderr is
  kept, its last 400 characters; the control run's stderr is what
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
srt 0.0.83, settings /Users/x/.srt-settings.json, 9 probes
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
`ERROR`, `2` any setup error: config that does not load or compile, settings
file missing or unreadable, or the preflight failed (srt not on `PATH`, or
`sandbox_apply` refused because twsrt itself runs inside a sandbox).

`--json` prints this document instead of the table (warnings stay on stderr):

```json
{
  "srt_version": "0.0.83",
  "settings": "/Users/x/.srt-settings.json",
  "summary": {"total": 9, "passed": 7, "failed": 1, "invalid": 0, "error": 0, "skipped": 1},
  "results": [
    {
      "kind": "read-deny",
      "section": "denyRead",
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
(`--project -w` prints only the `.twsrt/<profile>` directory there). Generators return
warnings as data and never write to the terminal; the CLI owns severity,
stream and color.

Every stderr notice starts with its severity, so color is never the only
signal: `Error:` means the command failed (non-zero exit), `Warning:` means
it succeeded but something looks wrong, `Info:` means nothing is wrong.
Optional items that are not configured (an agent without a `[targets]` key,
a source kind without `[sources.<kind>]`) are `Info:`, never `Error:`.

| Kind | Color | Stream |
|---|---|---|
| `Error:` | red, bold | stderr |
| `Warning:` | yellow; red, bold when urgent (a skipped JetBrains file) | stderr |
| `Info:` skipped agents or kinds, sync and migration notes, restart hints, the preview's "nothing written" footer (bold) | cyan | stderr |
| Write narration: `Wrote …`, `Would write …` | green (done) / cyan | stderr |
| Report info: `test` header and `--- summary ---` heading, `edit -n` paths, preview section headers | cyan | stdout |
| Count lines: `test` `passed=…`, `doctor: …` | green when clean, else red (`doctor`: yellow for warnings only) | stdout |
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
claude: 2 missing, 1 extra  /Users/x/.claude/settings.json
  + Bash(terraform)
  + Bash(terraform *)
  - Bash(docker run:*)

+ missing from target   - in target, not in sources
```

`--verbose` goes before the subcommand and reports lifecycle facts only:
selected profile, agent names, counts, target paths, caught exception
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
   byte-for-byte where the format allows.
5. **Fail-safe on ambiguity.** Conflicting fragments, incomplete profiles,
   a disabled canonical sandbox (Claude, Codex and Copilot native targets),
   `/~/` or `..` paths (Codex, Copilot native) and a top-level legacy Codex
   `sandbox_mode` in the managed file abort generation instead of guessing.
6. **Deterministic output.** The same config, profile and fragments produce
   identical output; rule sets are sorted, and no runtime state takes part
   in composition. One exception: the policy-file denies (invariant 8)
   follow `$HOME` (`~/…` spelling) and the symlinks on their paths, so
   `generate` and `diff` must run under the same `$HOME`.
7. **Project mode writes nothing global.** `generate --project` sends
   every canonical output and the Claude target to `./.twsrt/<profile>/`, adds
   the absolute `./.twsrt` to the compiled `denyWrite`, and reads the global Claude target
   only as merge base.
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
(`src/twsrt/lib/agent.py`):

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

GENERATORS["pimono"] = PiMonoGenerator()
```

Registration alone is not enough; the agent also needs:

1. its `[targets]` key in `config._apply_target_paths` and an `AppConfig` field;
2. an entry in `AppConfig.agent_target` and `models.AGENT_TARGET_KEYS`;
3. a write branch in `cli._stage_agent_files`, or `-w` writes nothing for it.

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

## After an srt upgrade

srt ships no JSON schema, and twsrt hand-copies what it relies on: doctor's
`_SRT_SCHEMA_KEYS`, the required lists in `sources.py` (`_SRT_REQUIRED_LISTS`),
and plain-string path entries. srt strips unknown keys without a word, so drift
goes unnoticed unless it is checked. The Makefile's `SRT_VERSION` pins the
version all of this was checked against; `make install-srt` installs exactly
that version. To move to a new version `<new>`, from a plain terminal:

1. `make install-srt SRT_VERSION=<new>`.
2. `make srt-schema-check SRT_VERSION=<new>`: first confirms the installed srt
   is `<new>` (exit `2` otherwise), then compares top-level, `network.*` and
   `filesystem.*` key names with `_SRT_SCHEMA_KEYS` and fails on drift. Add or
   remove the reported keys and bump the version in the comment above the table.
3. Diff `src/sandbox/sandbox-config.ts` between the old and new release tag of
   [anthropics/sandbox-runtime](https://github.com/anthropics/sandbox-runtime),
   because step 2 sees key names only. Look for keys that became required
   (compare with `_SRT_REQUIRED_LISTS`), changed types, and new entry forms in
   path or domain lists. 0.0.83 added `{"path": ..., "literal": true}` path
   entries, which twsrt rejects with `must be a list of strings`.
4. `grep -rn '0\.0\.<old>' src doc tests scripts README.md SECURITY_CONCEPT.md`:
   update version pins that claim the current schema. Pins that cite where a
   behaviour was verified (ADRs, probe pattern semantics) stay until re-verified.
5. `twsrt test`: enforcement probes against the new srt (see
   [Sandbox probes](#sandbox-probes)).
6. Set `SRT_VERSION := <new>` in the Makefile; `make srt-schema-check` passes
   without arguments again.

## Scope and roadmap

All three agents ship native OS sandboxes (Claude Code: built-in
Seatbelt/bwrap, switched on by twsrt; Copilot CLI and JetBrains: local sandbox, GA since October 2026; Codex:
kernel sandbox always-on). The durable core, deny paths and domains,
compiles into each of them with high fidelity. The Bash-rules app layer is
the per-agent best-effort supplement:

- **Bash-rules translation is Claude-primary and frozen for new agents.**
  Claude gets full deny/ask fidelity; Copilot keeps deny-only flags (deny
  takes precedence over `--yolo`); Codex gets forbidden-only escalation
  rules. New agents get restrictions-only compilation by default.
- **Copilot native sandbox** is compiled for the CLI (`settings.json`) and
  JetBrains IDEs (`github-copilot.xml`); the flag snippet stays for Bash
  rules, and the flags-only mode under srt stays supported
  ([ADR 0009](adr/0009-copilot-native-sandbox.md),
  [details](#copilot-native-sandbox)).
- **pi-mono** runs under the SRT wrapper today
  ([pi-extensions/sandbox](https://github.com/sysid/pi-extensions/tree/main/packages/sandbox));
  a native generator follows the [extension path](#extending-twsrt).
