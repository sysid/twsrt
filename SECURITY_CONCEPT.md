# Security Concept: Agentic Coding Configuration Management

This document explains **why** twsrt is built the way it is: what it
defends against, which principles follow, and where its protection ends.
How it works is in the [README](README.md); exact translations and
mechanics are in [doc/REFERENCE.md](doc/REFERENCE.md).

## 1. Summary

AI coding agents (Claude Code, Codex, Copilot CLI, pi-mono) operate with
broad access to the developer's filesystem, network and shell, and each
implements its own permission model and configuration format. Maintaining
security rules per agent invites drift, human error and coverage gaps.

twsrt compiles one policy, maintained as composable JSONC fragments and
selected by a profile, into a canonical document and from it into every
agent's native configuration
([pipeline](README.md#1-one-policy-compiled-in-two-stages)). Combined with
Anthropic's Sandbox Runtime (SRT) and the agents' native sandboxes, this
yields **defense in depth**: a kernel layer enforces invariants for every
spawned command, an application layer applies the same policy to every tool.
Neither layer alone is sufficient (§4).

**Key invariant.** The resolved profile is the complete policy input for one
invocation. Fragments are never written by twsrt; compiled canonical JSON and
the managed sections of agent targets are generated artifacts, never
hand-edited.

## 2. Threat Model

### 2.1 What we defend against

Agentic coding tools execute code, read files and make network requests on
behalf of the developer. The threat is the agent itself, acting on
malicious, hallucinated or overly broad instructions.

### 2.2 Attack surface

| Threat vector | Example | Severity |
|---|---|---|
| Credential exfiltration | Agent reads `~/.aws/credentials` and sends it to an external URL | Critical |
| Destructive commands | Agent runs `rm -rf /`, `git push --force`, `dd` | Critical |
| Privilege escalation | Agent runs `sudo`, `pkexec`, `su` | Critical |
| Data leakage via network | Agent fetches from or sends data to unauthorized domains | High |
| Secret file modification | Agent writes to `.env`, `*.pem`, service account JSON, `authorized_keys` | High |
| Supply chain compromise | Agent runs `pip install malicious-package` without approval | High |
| Configuration tampering | Agent modifies `Makefile`, `Dockerfile`, CI/CD pipelines, its own settings | Medium |

### 2.3 Threat actors

The primary threat actor is the AI agent itself:

- **Prompt injection**: malicious instructions embedded in code comments,
  READMEs, issue descriptions or fetched web content redirect the agent.
- **Hallucinated commands**: the model generates plausible but dangerous
  commands (`rm` to "clean up", `curl` to "check" a URL).
- **Overly broad tool use**: correct tools on sensitive targets (reading
  credential files to "understand the project structure").

The developer's security posture must assume the agent will occasionally
attempt actions outside its intended scope, through malice (injection) or
mistake (hallucination).

## 3. Security Principles

### 3.1 Defense in depth

Enforcement is **asymmetric** across tool types. The kernel layer covers
every process the agent spawns; the application layer covers every tool,
including those running inside the agent process:

```
┌──────────────────────────────────────────────────────────────┐
│  Layer 2: application level (agent permissions)              │
│  Claude: permissions.deny/ask/allow · Codex: escalation      │
│  rules · Copilot: --deny-tool/--allow-tool flags             │
│  Scope: ALL tools (Bash, Read, Edit, WebFetch, …)            │
│  Enforced by: the agent's own permission engine (best-effort)│
│                                                              │
│  ┌────────────────────────────────────────────────────────┐  │
│  │  Layer 1: OS level (SRT / native agent sandbox)        │  │
│  │  Scope: spawned commands and their children ONLY       │  │
│  │  Filesystem: denyRead, denyWrite, allowWrite           │  │
│  │  Network: allowedDomains (proxy-based filtering)       │  │
│  │  Enforced by: kernel (Seatbelt / bubblewrap / seccomp) │  │
│  │  NOT applied to in-process tools: Read, Edit, WebFetch │  │
│  └────────────────────────────────────────────────────────┘  │
└──────────────────────────────────────────────────────────────┘
```

| Capability | Kernel sandbox | Agent permissions |
|---|---|---|
| Block Bash file access (`cat`, `rm`) | **Yes** (kernel) | Yes (tool level) |
| Block built-in tool file access (Read, Edit) | **No** | Yes (best-effort) |
| Block Bash network access (`curl`) | **Yes** (proxy) | Yes (tool level) |
| Block built-in network access (WebFetch) | **No** | Yes (allow check) |
| Distinguish `rm` from `git push` | **No** | **Yes** |
| Prompt before risky commands (ask) | **No** | **Yes** (Claude) |
| Hold even if the agent has bugs | **Yes** (spawned commands) | No |

**Redundancy for Bash.** If the agent's permission engine wrongly allows
`Bash(cat ~/.aws/credentials)`, the sandbox still blocks the `read()`
syscall: true two-layer defense.

**No redundancy for built-in tools.** If the permission engine fails to
enforce `Read(~/.aws/credentials)`, there is no OS-level fallback: the Read
tool runs in the agent's own process, outside the sandbox (§7.2).

The kernel layer cannot parse shell semantics; the application layer cannot
enforce anything against its own bugs. The layers are complementary, not
fully overlapping.

### 3.2 One source of truth, no silent override

Every rule is declared once in a registered fragment and reaches every agent
through the resolved profile: no duplication between agents and no hidden
include mechanism inside fragments.

| Security domain | Canonical source | Why separate |
|---|---|---|
| Filesystem access (read/write deny, write allow) | SRT fragments | Kernel-enforced for spawned commands; agent permissions for built-in tools |
| Network access (domain allowlist) | SRT fragments | Proxy-enforced for spawned commands; agent permissions for WebFetch |
| Command restrictions (deny/ask) | Bash fragments | The kernel cannot tell `rm` from `git push` |

The compiler deliberately has **no precedence rule** such as "last fragment
wins". For security policy, silently overriding a scalar can weaken the
effective sandbox; a conflict is therefore an error unless the fragments
state the same value. Profiles select compatible slices; they never override
parents. There is no "safer value wins" heuristic either: it would be
source-specific and could hide an authoring error.

Generated artifacts are never hand-edited. A hand edit to a managed section
is overwritten on the next `generate -w`, giving a false sense of security;
writing to a fragment from generated output would create a circular
definition of "the" policy.

### 3.3 Fail-safe defaults

When the system meets ambiguity it chooses the more restrictive option:

| Ambiguity | Default | Rationale |
|---|---|---|
| A deny path does not exist at generation time | Treated as a directory (adds the `/**` deny) | Blocks more rather than less |
| Copilot has no "ask" tier | Ask maps to deny, with a warning | Better to block than to run without the intended confirmation |
| Codex cannot express read-only for globs | A `denyWrite` glob becomes `deny`, with a warning | Narrows instead of widening |
| Codex `allow` rules mean "run unsandboxed" | Bash `allow` is not compiled for Codex | A translation must never widen the sandbox |
| Unknown source kind, disabled canonical sandbox, malformed path | Abort before writing | No output beats a guessed one |

### 3.4 Least privilege: `denyRead` implies `denyWrite`

A path secret enough to hide is never meant to be rewritten: overwriting
`authorized_keys`, `.git/hooks`, `.env` or the project's own `.twsrt`
settings is an integrity attack worse than reading it. The compiler
therefore adds every `denyRead` path to `denyWrite` for every target, and a
path both read-denied and write-allowed (write-only) fails compilation
([ADR 0001](doc/adr/0001-deny-read-implies-deny-write.md)). For Claude the
same intent is expressed as `Read(...)` plus `Edit(...)` denies, since one
`Edit` rule covers every file-editing tool. Why srt alone does not provide
this: §7.4.

### 3.5 Auditability

- **Deterministic generation.** The same config, profile and fragments
  produce identical output; rule sets are sorted, and no runtime state takes
  part in composition.
- **Drift detection.** `twsrt diff` recompiles in memory and checks both the
  canonical JSON and the agent targets on disk.
- **Enforcement verification.** `twsrt test` probes the kernel sandbox for
  every effective rule ([sandbox probes](doc/REFERENCE.md#sandbox-probes)).
- **Provenance-rich failure.** Conflicts name the profile, source kind, JSON
  pointer or rule bucket, and both fragments.
- **Explicit warnings.** Every lossy mapping (ask → deny for Copilot, glob
  narrowing for Codex) is reported, so administrators know where fidelity
  is reduced.
- **Secret-safe diagnostics.** `--verbose` never prints policy contents,
  environment values or credentials; probe stdout is never captured.

## 4. Why SRT and twsrt Together

**The kernel sandbox alone is insufficient.** It enforces hard OS-level
boundaries for spawned commands: no agent bug, injection or hallucination
bypasses a kernel-enforced `denyRead`. But it cannot see built-in tools that
run inside the agent process, and without twsrt the administrator must
translate its filesystem rules into each agent's permission model by hand,
exactly the drift-prone process that creates gaps.

**Agent permissions alone are insufficient.** They cover every tool and
express fine-grained semantics (deny vs ask vs allow), but they run in
application userspace:

- a bug in the permission engine silently negates the control (documented:
  GitHub #6631, #24846);
- N agents with M rules need N×M manual entries in N formats;
- nothing independently verifies that the policy is enforced;
- the agent process itself has full OS access: permissions are self-imposed
  constraints, not external invariants.

**Together they close both gaps:**

```
                    sandbox alone      permissions alone   sandbox + twsrt
                    ─────────────      ─────────────────   ───────────────
Bash file access    ✓ kernel deny      ✓ agent deny        ✓✓ two layers
Bash network        ✓ proxy deny       ✓ agent deny        ✓✓ two layers
Built-in tools      ✗ not covered      ✓ agent deny        ✓  agent layer
Enforcement depth   kernel (Bash)      userspace (all)     kernel + userspace
Consistency         one agent          per-agent by hand   one policy, all agents
```

The kernel layer provides the hardest boundary for the most dangerous
vector: Bash executes arbitrary programs, touches any file and opens network
connections. twsrt then expresses the same policy as application rules for
every tool of every agent, covering the surface the kernel cannot reach, and
the single-source model with drift detection removes the configuration
mistakes that in practice cause most gaps.

**Native-sandbox convergence (2026).** All supported agents now ship native
OS sandboxes (Claude Code: Seatbelt/bwrap, opt-in; Copilot CLI: local
sandbox in public preview; Codex: always on). twsrt's durable core is
therefore compiling deny paths and domains into each agent's native sandbox,
a high-fidelity translation everywhere; the Bash-rules app layer stays a
best-effort supplement ([roadmap](doc/REFERENCE.md#scope-and-roadmap)).

## 5. Per-project policy

`generate --project` compiles a chosen profile into `./.twsrt/` for a
per-launch `claude --setting-sources project,local --settings …` or
`srt -s …` ([usage](README.md#per-project-policy),
[launch premise](doc/REFERENCE.md#claude-per-project-launch-premise)).
Its security properties:

- **No subtraction.** A project weakens the global policy only by selecting
  a profile that omits a fragment, so the no-override property (§3.2) holds
  and every relaxation is visible as a profile in `config.toml`, never in the
  repository.
- **The user chooses, not the repository.** The profile is named at launch;
  omitting `-p` yields `default_profile`, the full global policy.
- **The global file must be skipped.** Claude unions list settings across
  scopes, so a dropped deny stays dropped only with
  `--setting-sources project,local`. The repository's own
  `.claude/settings*.json` still loads and, once the folder is trusted, can
  add rules or override sandbox scalars, the same exposure as a plain launch.
  Launching without the flags is not unsafe: the union is stricter.
- **The policy cannot rewrite itself.** Claude hot-reloads settings, so
  `./.twsrt` is added to the compiled `denyWrite`; every launch regenerates
  the files, overwriting anything a repository ships there.
- **Residual gap.** A session running under the global policy in the same
  directory lacks that deny. Close it with `.twsrt` in a global fragment's
  `denyWrite` and confirm with `twsrt test`.

## 6. Risk Reduction

### 6.1 Threat mitigation matrix

| Threat | Without twsrt | With twsrt (sandbox + agent) |
|---|---|---|
| Agent reads `~/.aws/credentials` via Bash | Each agent's deny list configured by hand | Kernel blocks `read()` **and** agent denies `Bash(cat)`: two layers |
| Agent reads `~/.aws/credentials` via Read tool | Each agent's deny list configured by hand | Agent denies `Read()`: one layer |
| Agent overwrites a read-denied file inside the project | Depends on a hand-written `denyWrite` | Implied `denyWrite` blocks it in every target |
| Agent runs `rm -rf /` | Added by hand to each agent | Bash deny translates to every agent |
| Agent sends data to `evil.com` via Bash | Network allowlist per agent by hand | Proxy blocks **and** agent denies: two layers |
| Agent sends data to `evil.com` via WebFetch | Network allowlist per agent by hand | `WebFetch(domain:…)` allow check: one layer |
| Copilot runs a command meant to be "ask" | Copilot runs it (no ask tier) | Mapped to deny, warned |
| Config drift (deny rule removed) | Undetectable until exploited | `twsrt diff` exits 1 |
| A rule written but not enforced (symlink, upgrade) | Undetectable | `twsrt test` reports `FAIL` |
| New agent added to the workflow | Start from scratch | New generator, same resolved policy |

### 6.2 Quantitative view

Without twsrt, N agents with M rules require N×M manual entries, each
independently editable, driftable and auditable. With twsrt, M rules are
maintained once, translation is deterministic, drift is detectable, and
enforcement is probed: the surface for human error drops from O(N×M) to
O(M).

## 7. Limits and Known Gaps

A security document that omits known gaps is worse than none.

### 7.1 What twsrt does not protect against

- **Kernel exploits.** If the OS sandbox is compromised, layer 1 falls;
  layer 2 still applies but runs in userspace.
- **Agent bugs in built-in tools.** If the permission engine fails to
  enforce Read/Edit denies, there is no OS-level fallback (§7.2). For Bash
  the kernel layer still holds.
- **A policy that is too permissive.** twsrt translates faithfully: garbage
  in, garbage out, but consistently across all agents. `twsrt test` proves
  the rules you wrote are enforced, not that you wrote the right ones.
- **Violation exceptions.** SRT `ignoreViolations` entries are passed
  through as written; twsrt does not judge them.
- **Agent configuration loaded from added directories.** Copilot's
  `--add-dir` grants file access *and* loads that directory's
  `.github/skills` and `.github/agents` as trusted configuration. The
  sandbox confines what those agents can touch, but not what they instruct
  the model to do. twsrt never emits `--add-dir`; adding one is a trust
  decision outside the policy.
- **User-level configuration is bypassable by the user.** Generated configs
  live in the user's home; a user can deliberately launch with full-access or
  ignore-configuration options. Non-bypassable enforcement needs managed
  (administrator) configuration outside the user profile.

### 7.2 Built-in tools are guarded by the agent only

The kernel sandbox (Seatbelt on macOS, bubblewrap on Linux) applies only to
spawned commands and their children. Built-in tools (Read, Write, Edit,
Glob, Grep, WebFetch) run in the agent's own process:

```
Bash(cat ~/.aws/credentials)  →  kernel blocks  +  agent blocks
Read(~/.aws/credentials)      →  agent blocks only (best-effort)
```

Anthropic documents Claude Code's deny rules for built-in file tools as a
*"best-effort attempt"*, and community reports (GitHub #6631, #24846) show
cases where they were not enforced. twsrt generates correct rules for every
tool type; the effective confidence differs by access path:

| Access path | Enforcement confidence |
|---|---|
| Spawned commands accessing denied paths | **High**: kernel-enforced |
| Spawned commands accessing denied network | **High**: proxy-enforced |
| Built-in tools accessing denied paths | **Medium**: depends on the agent |
| Built-in tools accessing denied network | **Medium**: depends on the agent |
| Codex out-of-sandbox escalation | **Medium**: user-level config, layer bypass possible (§7.3) |

**Recommendation.** Put the highest-value secrets (cloud credentials, SSH
and GPG keys) in `denyRead`, so command-based access is kernel-blocked, and
treat the agent-level rules as additional, not sole, coverage. Run
`twsrt test` after every srt, agent or OS upgrade: a control that is not
probed is a control that is assumed.

### 7.3 Codex profile silent deactivation

If a legacy `sandbox_mode` / `sandbox_workspace_write` setting appears in
*any* loaded Codex config layer (managed, team, project, config profile), or
`--sandbox` is passed on the CLI, Codex silently falls back to the legacy
sandbox and ignores `default_permissions`, without an error. twsrt's
`_reject_legacy_sandbox` guard is fail-safe only for the `config.toml` it
owns; other layers are invisible to it. Mitigations: twsrt prints a
reminder on every Codex generate/diff, and `codex doctor` shows the
effective sandbox posture. Run it after changing any other config layer.

### 7.4 Symlinked deny paths (macOS)

srt keeps a `denyRead` path unresolved in the Seatbelt profile when its
symlink target lies outside the original tree, while Seatbelt matches on the
real vnode path. `denyRead: ["~/.aws"]` therefore blocks nothing when
`~/.aws` is a symlink into a dotfiles repository, the most common layout for
managed configs. The implied write deny inherits the same no-op. Mitigation:
deny the real directory as well; `twsrt test` probes every deny path through
its real path and reports the gap as a `(realpath)` `FAIL`.

### 7.5 `denyRead` is not a write deny

**Gotcha.** In srt, a `denyRead` entry stops the agent *reading* a path; it
does **not** stop the agent *writing* to it. Whether a read-denied file can
be overwritten depends only on whether it sits below an `allowWrite` root.
twsrt closes this by compiling every `denyRead` into `denyWrite` (§3.4);
this section records why that is necessary.

**What actually protects credential files from writes: the write
allowlist.** srt's macOS profile denies everything by default and then
allows writes only where the configuration says so:

```
(deny default)                          ← every operation not allowed below is denied, writes included
(allow file-write* <allowOnly>)         ← allowOnly = srt's own paths + filesystem.allowWrite
(deny  file-write* <denyWithinAllow>)   ← denyWithinAllow = filesystem.denyWrite, and nothing else
```

`~/.ssh`, `~/.aws/credentials`, `~/.kube` and similar are unwritable because
no `allowWrite` entry covers them, so `(deny default)` applies; their
`denyRead` entries play no part in that. srt's own writable paths are
`/dev/{stdout,stderr,null,tty,dtracehelper,autofs_nowait}`, `/tmp/claude`,
`/private/tmp/claude`, and `~/.npm/_logs` and `~/.claude/debug` (each
dropped when a `denyRead` covers it).

**What `denyRead` compiles to in srt:**

| Rule emitted for a `denyRead` path P | Effect |
|---|---|
| `(deny file-read* P)` | P cannot be read |
| `(deny file-write-unlink file-write-create P + ancestors)` | Blocks moving P (or a parent) away to read it under another name |
| `(allow file-write-unlink file-write-create <each write root>)` | Re-opens create and delete inside write roots so `rm` works in the project |
| `(deny file-write-unlink P)`, only when P is inside a write root | Takes delete and rename back for P; create stays open |

No `file-write*` or `file-write-data` deny is emitted. So, without a
matching `denyWrite`:

| Where the read-denied path P is | Read | Delete or rename | Overwrite or append existing file | Create new file |
|---|---|---|---|---|
| Outside every `allowWrite` root (`~/.ssh`, …) | blocked | blocked | blocked by the **allowlist** | blocked by the **allowlist** |
| Inside an `allowWrite` root (`./.env`, `**/.twsrt`, `~/dev/x/secrets`) | blocked | blocked | **allowed** | **allowed** |
| Covered by a matching `denyWrite` as well | blocked | blocked | blocked | blocked |

Relative entries such as `**/.env` always fall in the second row whenever
`.` is write-allowed, because they resolve below the launch directory.
Adding an `allowWrite` entry that covers a credential path (`~`,
`~/.config` covering `~/.config/gh`, `~/dev` covering a repository's
`.env`) silently moves it from the first row to the second: reads stay
blocked and a read-only probe stays green, but the agent can replace the
file's contents. The implied `denyWrite` puts every read-denied path in the
third row, including for `allowWrite` entries added later, and `twsrt test`
derives a write probe for each.

**Per agent**, writes to a read-denied path inside a write root:

| Agent | Result |
|---|---|
| srt wrapper (`srt -s`, Copilot, pi) | blocked by the implied `denyWrite`; allowed for a policy compiled without it |
| Claude Code | Edit and Write tools blocked by the `Edit(...)` deny; Bash under Claude's native sandbox: not verified whether the `Edit` deny reaches the sandbox's write rules |
| Codex | filesystem `deny`, which outranks `read`; not runtime-verified |

**Evidence.** srt 0.0.78 as installed:

- `sandbox-manager.js:1032-1052` (`getFsWriteConfig`): `denyWithinAllow` is
  `filesystem.denyWrite` only.
- `macos-sandbox-utils.js:564-622` (`generateReadRules`), `626-670`
  (`generateWriteRules`) and `294-341` (`generateReadDenyUnlinkRules`): the
  rules above.
- `sandbox-utils.js:459-477`: the default writable paths.
- Profiles generated with `wrapCommandWithSandboxMacOS` on 2026-10-02, for
  `allowWrite W` with (a) `denyRead W/secret`: no `file-write*` deny for
  `W/secret`; (b) `denyWrite W/secret`: `(deny file-write* (subpath W/secret))`.
- Linux (bubblewrap) is not analysed; srt drops write globs there, so glob
  entries get no write protection on Linux.
- Runtime-confirmed by Tom on 2026-10-03 with `srt -s`: inside `allowWrite`, a
  read-denied file was overwritten without a `denyWrite`.
