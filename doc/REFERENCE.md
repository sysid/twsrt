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
- [Sandbox probes](#sandbox-probes)
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

## Sandbox probes

`twsrt test` answers one question: does the kernel enforce what
`~/.srt-settings.json` says? `diff` proves the file matches the fragments;
`test` proves the sandbox matches the file. It exercises the SRT wrapper only
(`srt -s <settings> -c`), not Claude Code's native sandbox, Codex, or the
bash deny/ask rules.

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
control failure stays `INVALID`. Verdict table:

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

### Probe catalogue

| Rule | Host condition | Command | Expect | Leaves behind | `SKIP` when |
|---|---|---|---|---|---|
| `denyRead` path | regular file | `head -c 1 -- <file>` | deny | nothing | glob pattern; path absent |
| `denyRead` path | directory with a file inside | `head -c 1 -- <first regular file>` | deny | nothing | as above |
| `denyRead` path | directory without files | `ls -- <dir>` | deny | nothing | as above |
| `denyRead` path | symlink anywhere in the probed path | second probe on the realpath, rule shown as `<pattern> (realpath)` | deny | nothing | never |
| `denyWrite` `**/`-glob | — | `: >> <scratch>/<name>` | deny | file removed after each run | mid-path wildcard, `[...]`, absolute or `~` glob |
| `denyWrite` path | directory | `: >> <dir>/.twsrt-probe-<pid>` | deny | file removed after each run | path absent |
| `denyWrite` path | existing file | `: >> <file>` | deny | nothing | path absent |
| `allowWrite` path | directory (`.` = cwd) | `: >> <dir>/.twsrt-probe-<pid>` | allow | file removed after each run | glob; path absent |
| `allowWrite` path | existing file | `: >> <file>` | allow | nothing | glob; path absent |
| `allowedDomains` host | — | `curl -sS -m 10 -o /dev/null -I https://<host>/` | allow | nothing | wildcard (`*.`) |
| `deniedDomains` host | — | same curl | deny | nothing | wildcard |
| allowlist canary | — | same curl against `example.com`, `.org`, or `.net`, whichever is not allowlisted | deny | nothing | never |

### Read probes

- `head -c 1` reads a single byte: enough to trigger the kernel's
  `file-read*` check, cheap on large files. Its output goes to `/dev/null`.
- For a directory, the first regular file is found by a sorted walk at most
  four levels deep, ignoring symlinks. Sorting makes the choice stable across
  runs. A directory without files is probed with `ls`, which needs read
  permission on the directory itself.
- **Realpath twin.** On macOS, srt keeps a `denyRead` path unresolved in the
  Seatbelt profile when its symlink target lies outside the original tree,
  while Seatbelt matches the real vnode path. `denyRead: ["~/.aws"]` then
  blocks nothing when `~/.aws` is a symlink. Whenever the probed path
  resolves to something else, a second probe reads the same file through its
  real path. That row failing while the plain row passes is the signature of
  the symlink gap; the fix is to deny the real directory as well.

### Write probes

- **Glob rules** need a witness file that matches the glob. It is created
  in a temporary `.twsrt-test-*` directory below the first concrete
  `allowWrite` directory (falling back to cwd), because a deny glob can only
  be observed where writing is otherwise allowed. The witness name is
  derived from the last segment: `*` becomes `probe`, `?` becomes `x`, a
  trailing `**` becomes `<segment>/probe`. Examples:

  | glob | witness |
  |---|---|
  | `**/.env` | `.env` |
  | `**/*.pem` | `probe.pem` |
  | `**/serviceAccount*.json` | `serviceAccountprobe.json` |
  | `**/secrets/**` | `secrets/probe` |
  | `**/.github/workflows/**` | `.github/workflows/probe` |

  Only `**/`-anchored globs are convertible: they match anywhere, so a file
  in the scratch directory is a valid witness. Parent directories are
  created on the host beforehand so a sandboxed failure can only come from
  the deny rule, not from a missing directory. The scratch directory is
  removed when the run ends.
- **Every write probe is an append-open that writes nothing**, `: >> path`.
  The kernel checks write permission at `open()`, so the sandboxed run fails
  exactly when the rule denies writing. On a missing path `>>` creates an
  empty file; on an existing one it leaves size, content, and mtime
  untouched. There is deliberately no `>` redirect and no `printf`/`touch`
  anywhere: `>` would truncate, `touch` bumps mtime, and a wrong target path
  must never be able to lose data.
- **Directory rules** create `.twsrt-probe-<pid>` inside the directory.
  Existing files are never opened.
- **File rules** open the named file itself. A file that does not exist is
  skipped rather than created.
- A file a probe creates is recorded as its artifact and removed after the
  control run and again after the sandboxed run, so both runs start from the
  same state and nothing is left behind, even on a timeout. A file that
  already exists at the artifact path before the run is never removed.

### Network probes

- `curl -I` sends a HEAD request with a 10-second limit. Exit code 0 means
  the connection was established; the HTTP status is irrelevant, so a 403
  or 405 still counts as reachable. Under srt the proxy refuses the
  `CONNECT` for a non-allowlisted host and curl exits non-zero.
- Wildcard entries (`*.github.com`) have no concrete host to dial and are
  skipped. Add the bare domain to the allowlist if you want it probed.
- The canary proves allowlist mode is active at all: it dials the first of
  `example.com`, `example.org`, `example.net` that is not allowlisted and
  expects the sandbox to block it. Without the canary, an empty or ignored
  allowlist would produce no failing row.
- The control run of a network probe really connects to the host from your
  machine, including for `deniedDomains` entries.

### Preflight and safety

- Before any probe, `test` resolves `srt` on `PATH`, reads its version from
  the `package.json` next to the binary (`srt --version` reports a
  hardcoded `1.0.0`), and runs `srt -s <settings> -c true`. If that fails
  the run aborts with exit `2`; `sandbox_apply: Operation not permitted`
  means srt cannot nest inside another sandbox, so run from a plain
  terminal rather than from Claude Code's Bash tool.
- The compiled settings file is compared against the fragments first; drift
  is a warning, and the on-disk file is what gets probed, because that is
  what srt enforces.
- Command stdout is sent to `/dev/null` for both runs and never captured, so
  a failing deny probe cannot leak the secret it just read. Only stderr is
  kept, for both runs, truncated to 400 characters; the control run's
  stderr is what distinguishes an OS permission denial from a broken probe.
- The control run executes each command as your user with full privileges:
  it reads one byte of each protected file and opens each writable file for
  append. Nothing is modified.
- `--timeout` (default 30 s) bounds each command; a timeout yields `ERROR`.

### Known limits

- Only the SRT wrapper is exercised. Claude Code's native sandbox consumes
  the same deny paths but is not probed.
- `denyRead` globs, wildcard domains, and globs with wildcards in a
  non-final segment are reported as `SKIP`, never silently dropped.
- Bash deny/ask rules are application-layer and out of scope.
- Probes run one after another; a long allowlist costs one HEAD request per
  domain.

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
patterns, domains, environment values, or credentials. `test` is the
exception: with `-v` it traces the whole run on stderr so a verdict can be
reproduced by hand. In order: the compiled profile, whether the settings file
matches the fragments, the resolved `srt` binary and where its version came
from, the preflight, the scratch directory, every derivation decision (which
file inside a deny directory is probed, symlink detection, why a rule is
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

### `twsrt test` output

How probes are derived and judged is described under
[Sandbox probes](#sandbox-probes). The table lists one row per probe as it
completes:

```
srt 0.0.75, settings /Users/x/.srt-settings.json, 9 probes
STATUS   KIND       RULE               CTL SBX     MS  PROBE
PASS     read-deny  ~/.ssh               0   1     85  head -c 1 -- /Users/x/.ssh/config
FAIL     read-deny  ~/.aws (realpath)    0   0     90  head -c 1 -- /Users/x/configs/dot-aws/sso/cache/x.json
SKIP     read-deny  **/.env              -   -      -  glob pattern: no concrete probe
PASS     net-deny   example.com (not allowlisted)  0  56  412  curl -sS -m 10 -o /dev/null -I https://example.com/
--- read-deny ~/.aws (realpath): FAIL ---
  not blocked: command succeeded inside the sandbox
  command: head -c 1 -- /Users/x/configs/dot-aws/sso/cache/x.json
--- summary ---
FAIL     read-deny  ~/.aws (realpath)  not blocked: command succeeded inside the sandbox
SKIP     read-deny  **/.env            glob pattern: no concrete probe
passed=7 failed=1 invalid=0 error=0 skipped=1
```

After the table come a detail block per `FAIL`/`INVALID`/`ERROR` (reason,
command, sandbox stderr), a short summary listing every probe that did not
pass including `SKIP`s, and the counts line. A clean run prints only the
table and the counts. `CTL` and `SBX` are the exit codes of the control and
sandboxed run. Statuses:

| Status | Meaning |
|---|---|
| `PASS` | control succeeded and the sandboxed run matched the expectation, or a deny probe was refused by the OS itself (reason field says so) |
| `FAIL` | rule not enforced (deny probe succeeded) or over-enforced (allow probe blocked) |
| `INVALID` | control run failed for a reason other than an OS permission denial: the probe proves nothing (file absent, host unreachable) |
| `ERROR` | timeout, or srt could not apply the sandbox for that probe |
| `SKIP` | no concrete probe derivable (glob deny-read, wildcard domain, absent path) |

Command stdout is discarded for both runs and never captured, so a failing
deny probe cannot leak the secret it just read. Only the sandboxed run's
stderr is kept (last 400 characters). Glob write probes create their files
below the first concrete `allowWrite` directory (`.` is the working directory)
in a temporary `.twsrt-test-*` directory that is removed afterwards. A
`denyWrite` or `allowWrite` entry naming a directory gets a new file inside it
that is removed after each run; one naming an existing file is opened for
append without writing a byte (`: >> file`), which exercises the kernel's
write check while leaving size, content, and mtime unchanged.

Exit codes: `0` every executed probe passed, `1` any `FAIL`, `INVALID`, or
`ERROR`, `2` configuration or settings missing, or the preflight
`srt -s <settings> -c true` failed (srt not on `PATH`, unloadable settings,
or `sandbox_apply` refused because twsrt itself runs inside a sandbox).

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

`srt_version` comes from the `package.json` next to the resolved `srt` binary
because `srt --version` reports a hardcoded `1.0.0`.

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
