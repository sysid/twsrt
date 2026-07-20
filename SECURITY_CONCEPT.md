# Security Concept: Agentic Coding Configuration Management

## 1. Executive Summary

AI coding agents (Claude Code, GitHub Copilot CLI, Codex, pi-mono) operate with
broad access to the developer's filesystem, network, and shell. Each agent
implements its own permission model with its own configuration format. This
heterogeneity creates a systemic risk: security rules must be maintained
independently per agent, inviting configuration drift, human error, and
coverage gaps.

**twsrt** solves this with a profile-driven canonical-source compiler. Policy
is maintained in named JSONC fragments grouped by source kind. A profile
selects and inherits fragments for every source kind; twsrt resolves their
order, composes and validates each canonical document, emits strict runtime
JSON, then derives every agent's native configuration from the same compiled
result.

Combined with Anthropic's Sandbox Runtime Tool (SRT) at the OS level, this
creates a **defense-in-depth** architecture: SRT enforces OS-level invariants,
while twsrt consistently projects the selected policy into application-level
controls. Neither layer alone is sufficient; together they close each other's
gaps (see Section 3.7).

```
 config.toml
   source registries + profiles
               │
               ▼
      ordered JSONC fragments
               │
               ▼
        compose + validate
               │
      ┌────────┴────────┐
      ▼                 ▼
 strict canonical JSON  normalized rules
      │                 │
      ▼                 └─────► agent-specific configuration
 SRT / compiled Bash policy

                    ENFORCEMENT LAYERS
                    ==================
     Layer 1 (OS):  SRT sandbox — syscall-level deny (Bash only, kernel enforcement)
     Layer 2 (App): Agent permissions — tool-level deny/ask (all tools, application enforcement)
```

**Key invariant**: The resolved profile is the complete policy input for one
invocation. Canonical JSONC fragments are never written by twsrt. Compiled
canonical JSON and agent targets are generated artifacts and are never
hand-edited in managed sections.


## 2. Threat Model

### 2.1 What We Defend Against

Agentic coding tools execute code, read files, and make network requests on
behalf of the developer. The threat is the agent itself — acting on
malicious, hallucinated, or overly broad instructions.

### 2.2 Attack Surface

| Threat Vector | Example | Severity |
|---|---|---|
| Credential exfiltration | Agent reads `~/.aws/credentials` and sends to external URL | Critical |
| Destructive commands | Agent runs `rm -rf /`, `git push --force`, `dd` | Critical |
| Data leakage via network | Agent fetches content from or sends data to unauthorized domains | High |
| Secret file modification | Agent writes to `.env`, `*.pem`, service account JSON | High |
| Privilege escalation | Agent runs `sudo`, `pkexec`, `su` | Critical |
| Supply chain compromise | Agent runs `pip install malicious-package` without approval | High |
| Configuration tampering | Agent modifies `Makefile`, `Dockerfile`, CI/CD pipelines | Medium |

### 2.3 Threat Actors

The primary threat actor is the AI agent itself, specifically:

- **Prompt injection**: Malicious instructions embedded in code comments, README
  files, issue descriptions, or fetched web content that redirect agent behavior
- **Hallucinated commands**: The LLM generates plausible but dangerous commands
  (e.g., `rm` to "clean up" or `curl` to "check" a URL)
- **Overly broad tool use**: The agent uses correct tools but on sensitive targets
  (reading credential files to "understand the project structure")

The developer's security posture must assume the agent will occasionally attempt
actions outside its intended scope — whether through malice (injection) or
mistake (hallucination).


## 3. Security Principles

### 3.1 Defense in Depth

Security enforcement is **asymmetric** across tool types. The two layers
provide different coverage depending on how the agent accesses resources:

```
┌──────────────────────────────────────────────────────────────┐
│  Layer 2: Application-Level (Agent Permissions)              │
│  ──────────────────────────────────────────────────────────  │
│  Claude:  permissions.deny / .ask / .allow                   │
│  Copilot: --deny-tool / --allow-tool flags                   │
│  Scope:   ALL tools (Bash, Read, Write, Edit, WebFetch, ...) │
│  Enforcement: Agent's internal permission engine             │
│  Limitation: Best-effort for built-in tools (see §7.4)       │
│                                                              │
│  ┌────────────────────────────────────────────────────────┐  │
│  │  Layer 1: OS-Level (SRT Sandbox)                       │  │
│  │  ────────────────────────────────────────────────────  │  │
│  │  Scope: Bash commands and their child processes ONLY   │  │
│  │  Filesystem: denyRead, denyWrite, allowWrite           │  │
│  │  Network: allowedDomains (proxy-based filtering)       │  │
│  │  Enforcement: OS kernel (Seatbelt/bubblewrap/seccomp)  │  │
│  │  NOT applied to: Read, Write, Edit, Glob, Grep tools   │  │
│  └────────────────────────────────────────────────────────┘  │
└──────────────────────────────────────────────────────────────┘
```

**Coverage by tool type**:

| Access Method | SRT (Layer 1) | Agent Permissions (Layer 2) | Effective Depth |
|---|---|---|---|
| `Bash(cat ~/.aws/credentials)` | Kernel-enforced deny | Tool-level deny | **Two layers** |
| `Read(~/.aws/credentials)` | Not covered | Tool-level deny (best-effort) | **One layer** |
| `Bash(curl evil.com)` | Network proxy blocks | Tool-level deny | **Two layers** |
| `WebFetch(evil.com)` | Not covered | Tool-level allow check | **One layer** |

**Redundancy for Bash**: If the agent's permission engine has a bug that
allows `Bash(cat ~/.aws/credentials)`, the SRT sandbox still blocks the
underlying `read()` syscall. This is true two-layer defense.

**No redundancy for built-in tools**: If the agent's permission engine fails
to enforce `Read(~/.aws/credentials)`, there is no OS-level fallback. The
Read tool runs in the agent's Node.js process, outside the SRT sandbox.
See Section 7.4 for known enforcement gaps.

### 3.2 Resolved Profile as the Source of Truth

Every security rule is declared in a registered fragment and reaches runtime
through a resolved profile. There is no duplication between agents, and there
is no hidden include mechanism inside fragments.

| Security Domain | Canonical Source | Why Separate |
|---|---|---|
| Filesystem access (read/write deny, write allow) | Selected SRT JSONC fragments | SRT enforces at OS level for Bash; agent permissions for built-in tools |
| Network access (domain allowlist) | Selected SRT JSONC fragments | SRT enforces via proxy for Bash; agent permissions for WebFetch |
| Bash command restrictions (deny/ask) | Selected Bash JSONC fragments | SRT cannot distinguish `bash rm` from `bash git push` |

**Why this matters**: Shared policy can live in a base fragment while
environment- or role-specific policy lives in additional fragments selected by
named profiles. `twsrt generate --write` compiles one explicit selection and
propagates it to the canonical runtime files and every requested agent. No
manual per-agent editing or copy-pasted monolithic policy is required.

### 3.3 Fail-Safe Defaults

When the system encounters ambiguity, it defaults to the more restrictive
option:

| Ambiguity | Default | Rationale |
|---|---|---|
| Filesystem path not found | Treated as directory (adds `/**` deny) | Blocks more than necessary rather than less |
| Copilot has no "ask" equivalent | Maps to deny (blocks entirely) | Safer to block than to silently allow |
| SRT file format unknown | Tries both flat and nested parsing | No silent failure on format mismatch |

### 3.4 Least Privilege

**denyRead implies denyWrite**: If a path is sensitive enough to deny reading,
it must not be writable either. A `denyRead` entry denies both reading and every
form of editing. Claude Code matches file permissions on `Read(path)` and
`Edit(path)` — a single `Edit` rule covers all file-editing tools (Write, Edit,
NotebookEdit), so those two rules are sufficient:

```
denyRead: ["~/.aws"]
    → deny: Read(~/.aws), Read(~/.aws/**)
            Edit(~/.aws), Edit(~/.aws/**)
```

This prevents the agent from exfiltrating credentials by writing them to a
readable location, or from modifying credential files directly.

### 3.5 Separation of Concerns

Each enforcement layer handles what it does best:

| Capability | SRT (OS-Level) | Agent Permissions |
|---|---|---|
| Block Bash file access (`cat`, `rm`) | **Yes** (kernel) | Yes (tool-level) |
| Block built-in tool file access (Read, Edit) | **No** | Yes (best-effort) |
| Block Bash network access (`curl`) | **Yes** (proxy) | Yes (tool-level) |
| Block built-in network access (WebFetch) | **No** | Yes (allow check) |
| Distinguish `bash rm` from `bash git push` | **No** | **Yes** |
| Prompt user before risky commands (ask) | **No** | **Yes** (Claude only) |
| Enforce even if agent has bugs | **Yes** (Bash only) | No |

SRT cannot parse shell command semantics — it sees all bash invocations
equivalently. SRT also cannot intercept built-in tool operations — these
run inside the agent's own process. Agent permissions can distinguish
commands and cover all tools, but depend on the agent's own enforcement
correctness. The layers are complementary but not fully overlapping.

### 3.6 Auditability

- **Deterministic generation**: Given the same config, profile, and fragments,
  `twsrt generate` produces identical ordered output. No runtime state or
  randomness participates in composition.
- **Drift detection**: `twsrt diff` recompiles in memory and checks both strict
  canonical JSON and agent targets on disk.
- **No hand-editing**: Managed sections of target configs are machine-generated
  only. Human error in security-critical permission lists is eliminated.
- **Provenance-rich failure**: Composition and action conflicts name the
  profile, source kind, structural path or rule bucket, and both fragments.
- **Explicit warnings**: Lossy mappings (e.g., ask → deny for Copilot) emit
  warnings to stderr so administrators know where fidelity is reduced.

### 3.7 Why SRT + twsrt Together: A Strategic Assessment

Each layer alone has structural weaknesses. The combination eliminates them.

**SRT alone is insufficient.** SRT enforces hard OS-level boundaries for
Bash commands — no agent bug, prompt injection, or hallucination can bypass
a kernel-enforced `denyRead`. But SRT has no awareness of agent-specific
tool semantics. It cannot:

- Control built-in tools (Read, Write, Edit) that run inside the agent process

Without twsrt, the administrator must manually translate SRT's filesystem
rules into each agent's permission model — exactly the error-prone,
drift-susceptible process that creates security gaps.

**Agent permissions alone are insufficient.** Agent-level deny rules cover
all tools (Bash, Read, Write, Edit, WebFetch) and can express fine-grained
semantics (deny vs ask vs allow). But they are enforced in application
userspace — inside the agent's own process. This means:

- A bug in the agent's permission engine silently negates the control
  (documented: GitHub #6631, #24846)
- Each agent has a different configuration format; maintaining N agents
  with M rules requires N*M manual entries
- There is no independent verification that the policy is actually enforced
- The agent process itself has full OS-level access; permissions are
  self-imposed constraints, not external invariants

**The combination closes both gaps:**

```
                    SRT alone          twsrt alone        SRT + twsrt
                    ──────────         ───────────        ───────────
Bash file access    ✓ kernel deny      ✓ agent deny       ✓✓ two layers
Bash network        ✓ proxy deny       ✓ agent deny       ✓✓ two layers
Built-in tools      ✗ not covered      ✓ agent deny       ✓ agent layer
Enforcement depth   kernel (Bash)      userspace (all)    kernel + userspace
```

**The key insight**: SRT provides the **hardest** security boundary for
the **most dangerous** attack vector. Bash is the primary tool an agent
uses to interact with the OS — it can execute arbitrary programs, access
any file, and make network connections. A kernel-level deny on Bash is
un-bypassable by the agent. `twsrt` then ensures this same policy is
faithfully expressed as application-level rules for ALL tools across ALL
agents, covering the surface area that SRT cannot reach.

**Quantifying the risk reduction**: Consider the credential exfiltration
threat (`~/.aws/credentials`):

| Scenario | Without SRT+twsrt | With SRT+twsrt |
|---|---|---|
| Agent uses `Bash(cat ~/.aws/credentials)` | Depends on manual agent config | Kernel-blocked (SRT) + agent-blocked (twsrt-generated deny) |
| Agent uses `Read(~/.aws/credentials)` | Depends on manual agent config | Agent-blocked (twsrt-generated deny, best-effort) |
| Agent uses `Bash(curl) \| base64` to exfiltrate | Depends on manual network config | Kernel-blocked (SRT network proxy) + agent-blocked (twsrt-generated deny) |
| Admin forgets to update one agent | That agent is unprotected | Impossible — twsrt generates from single source for all agents |
| Agent config drifts after manual edit | Undetectable | `twsrt diff` catches it immediately |

The most critical attacks (Bash-based exfiltration and destruction) get
kernel-level protection. The remaining surface (built-in tools) gets
consistent, automatically-generated agent-level protection. And the
single-source model with drift detection eliminates the configuration
management failures that are, in practice, the most common cause of
security gaps.

**2026 update — native-sandbox convergence**: All three supported agents now
ship native OS sandboxes (Claude Code: built-in Seatbelt/bwrap, opt-in;
Copilot CLI: local sandbox in public preview; Codex: kernel sandbox
always-on). This shifts twsrt's durable core toward compiling one resolved
canonical policy (deny-paths + domains) into each agent's *native*
sandbox/profile configuration — a high-fidelity translation everywhere. The
bash-rules app layer remains a per-agent best-effort supplement:
Claude-primary (full deny/ask fidelity), deny-only for Copilot, and
forbidden-only sandbox-escape rules for Codex. Bash-rules translation is
frozen for new agents; new agents get restrictions-only compilation by
default.


## 4. Architecture

### 4.1 Data Flow

```
CONFIGURATION PLANE                       GENERATED PLANE
===================                       ===============

config.toml
  ├─ sources.srt fragments ──┐
  ├─ sources.bash fragments ─┼─► resolve selected profile
  └─ profiles + inheritance ─┘             │
                                           ▼
                                  ordered fragments by kind
                                           │
                                  parse JSONC + validate shape
                                           │
                                  recursive structural union
                                           │
                                  cross-action validation
                                           │
                         ┌─────────────────┴─────────────────┐
                         ▼                                   ▼
              strict canonical JSON               normalized SecurityRules
              ~/.srt-settings.json                          │
              compiled bash-rules.json                      ▼
                                                agent generators + targets
```

There is one composition pipeline per source kind and one resolved profile per
invocation. Agent generation begins only after every selected source kind has
compiled successfully.

### 4.2 Compilation Phases

| Phase | Input | Security property |
|---|---|---|
| Configuration loading | `config.toml` | Rejects unknown schema versions, legacy source paths, unknown source kinds, duplicate outputs, invalid fragment suffixes, unknown references, and inheritance cycles. |
| Profile resolution | Named profile | Walks parents first, deduplicates fragment names stably, and requires coverage for every configured source kind. |
| JSONC parsing | Selected `.jsonc` files | Supports line and block comments while retaining strict JSON: duplicate keys, trailing commas, non-finite numbers, non-object roots, and malformed comments fail. |
| Structural composition | Parsed objects | Recursively merges objects, forms stable array unions, accepts equal scalars, and rejects unequal scalars or incompatible types. |
| Domain validation | One composed source document | Rejects invalid field shapes, unknown Bash actions, and values assigned to opposing security actions. |
| Translation | Compiled documents | Produces strict canonical JSON plus normalized rules consumed by agent generators. |
| Preflight and write | Rendered targets | Configuration and rendering conflicts fail before any output write starts; individual files are replaced atomically. |

The compiler deliberately has no precedence rule such as “last fragment wins.”
For security policy, silently overriding a scalar can weaken the effective
sandbox. A conflict is therefore an error unless the fragments state the same
value. Profiles select compatible policy slices; they do not override parents.

### 4.3 Source/Generated-Artifact Invariant

This invariant is the foundation of the security model:

1. **JSONC fragments are NEVER written by twsrt** — they are human-maintained
   policy documents. twsrt only reads them.
2. **Compiled canonical JSON and target managed sections are NEVER
   hand-edited** — twsrt writes them via `generate --write`.
3. **Target non-managed sections ARE human-maintained** — hooks, plugins,
   MCP tool permissions, project-specific allows in Claude's settings.json
   are preserved by the selective merge algorithm (see Section 6.1.2).

Violating this invariant creates two risks:

- Hand-editing a target's managed section → will be overwritten on next
  `twsrt generate --write`, giving false sense of security
- Writing to a canonical JSONC fragment → creates circular dependency, makes
  it unclear what the "true" policy is

### 4.4 Internal Data Model

Composition is source-agnostic until domain validation and translation. The
configuration model keeps selection separate from content:

```
CanonicalSource
  name
  output_path
  fragments: name → SourceFragment(path)

Profile
  extends: [profile name]
  selections: source kind → [fragment name]

ResolvedProfile
  fragments: source kind → [SourceFragment]

CompiledDocument
  source_kind
  output_path
  document
```

Source adapters then normalize compiled policy into the existing translation
representation:

```
SecurityRule:
  scope:   READ | WRITE | EXECUTE | NETWORK
  action:  DENY | ASK | ALLOW
  pattern: string (path, glob, command, or domain)
  source:  SRT_FILESYSTEM | SRT_NETWORK | BASH_RULES
```

Validation constraints enforced at construction:

- `pattern` must not be empty
- `NETWORK` scope requires `ALLOW` or `DENY`
- `EXECUTE` scope requires `BASH_RULES` source
- `READ`/`WRITE` scope requires `SRT_FILESYSTEM` source


## 5. Canonical Sources

### 5.1 Registry and Output Contract

`config.toml` registers canonical sources independently from profiles and
agent targets:

```toml
schema_version = 1
default_profile = "default"

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

[profiles.default]
srt = ["base"]
bash = ["base"]

[profiles.work]
extends = ["default"]
srt = ["work"]
```

Each source kind owns a fragment namespace and exactly one compiled output.
Output paths must be distinct and may not equal a fragment path. Fragment
paths must end in `.jsonc`. Relative paths resolve from `config.toml`, making
the whole configuration directory relocatable.

The source registry is extensible but explicit. `srt` and `bash` are the only
currently registered kinds; unknown kinds fail instead of being composed
without validation or translation semantics.

### 5.2 Profiles and Inheritance

A profile names fragment selections per source kind. Resolution has these
properties:

- the configured `default_profile` is used unless `--profile` is supplied;
- parents resolve before children;
- diamond inheritance and repeated fragment names are deduplicated by first
  occurrence;
- cycles, unknown parents, and unknown fragments fail configuration loading;
- the resolved profile must select at least one fragment for every configured
  source kind.

Inheritance composes selections; it does not create an override hierarchy.
For example, a child fragment cannot change `enabled = true` from its parent to
`false`. That scalar disagreement fails compilation. This prevents a broad or
later profile from silently weakening a security property.

### 5.3 JSONC and Composition Semantics

twsrt implements JSONC locally without a parser dependency. It recognizes
`//` and `/* ... */` comments while preserving source locations for JSON
errors. Everything else is strict JSON: no trailing commas, single-quoted or
unquoted keys, duplicate object keys, `NaN`, infinities, or non-object roots.

Within each source kind, selected documents form a structural union:

| Values at the same path | Result |
|---|---|
| Objects | Merge recursively. |
| Arrays | Append values not already present; preserve first occurrence. |
| Equal scalars | Keep the value. |
| Unequal scalars | Fail with profile, source kind, JSON pointer, and both fragment paths. |
| Different JSON types | Fail with the same provenance. |

Domain validation runs before and after structural composition. SRT rejects
the same domain or path appearing in opposing allow/deny buckets. Bash rejects
the same command appearing in more than one of `allow`, `ask`, and `deny`.
There is no "safer value wins" heuristic: such a rule would be source-specific
and could conceal an authoring error.

### 5.4 SRT JSONC Fragments

SRT JSONC fragments define enforcement boundaries. The selected profile is
composed into strict JSON at `sources.srt.output` (normally
`~/.srt-settings.json`). SRT enforces that compiled configuration at the OS
level for Bash commands; for built-in tools, the same rules are translated to
agent-level permissions (see Section 3.1 for coverage details):

```jsonc
{
  // Human-maintained canonical fragment.
  "enabled": true,
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

**Filesystem rules**:
- `denyRead`: Paths the agent cannot read. Mix of directories (`~/.aws`)
  and files (`~/.netrc`). twsrt detects this distinction and translates
  accordingly (see Section 6.1.1).
- `denyWrite`: Glob patterns the agent cannot write to. Applied within
  otherwise-allowed write locations.
- `allowWrite`: Paths where writing is permitted. SRT uses an allowlist
  model — everything not listed is denied.

**Network rules**:
- `allowedDomains`: Domain allowlist. Only listed domains (and their
  wildcard subdomains) can be reached. Everything else is blocked at
  the network level.

### 5.5 Bash JSONC Fragments

Bash command restrictions that SRT cannot enforce (SRT sees all shell
invocations equivalently) are also composable JSONC fragments:

```jsonc
{
  "deny": ["rm", "sudo", "git push --force", "shutdown", "systemctl"],
  "ask":  ["git push", "git commit", "pip install", "docker", "ssh"]
}
```

- **deny**: Commands that should be unconditionally blocked across all agents.
- **ask**: Commands that should prompt the user for confirmation before
  execution. (Note: not all agents support "ask" — see Section 6.2.)

## 6. Translation Rules per Agent

### 6.1 Claude Code

Claude Code uses a JSON-based permission model in `~/.claude/settings.json`
with three permission tiers: `deny` (blocked), `ask` (prompt user), and
`allow` (permitted without prompt).

#### 6.1.1 Translation Table

| Canonical Rule | Claude Code Output | Notes |
|---|---|---|
| denyRead directory (e.g., `~/.aws`) | `Read(~/.aws)`, `Read(~/.aws/**)`, `Edit(~/.aws)`, `Edit(~/.aws/**)` in deny | Reading + all editing blocked; bare + recursive |
| denyRead file (e.g., `~/.netrc`) | `Read(~/.netrc)`, `Edit(~/.netrc)` in deny | Reading + all editing blocked; bare only (no `/**`) |
| denyRead glob (e.g., `**/.env`) | `Read(**/.env)`, `Edit(**/.env)` in deny | Glob preserved as-is |
| denyWrite pattern | `Edit({pattern})` in deny | Editing only (Read not included) |
| allowWrite path | No output | SRT enforces for Bash; Claude already has blanket allows |
| allowedDomains domain | `WebFetch(domain:{domain})` in allow + domain in `sandbox.network.allowedDomains` | Full fidelity |
| Bash deny command | `Bash({cmd})`, `Bash({cmd} *)` in deny | Bare + wildcard catches subcommands |
| Bash ask command | `Bash({cmd})`, `Bash({cmd} *)` in ask | Bare + wildcard catches subcommands |

**Why no `Write(path)` rule**: Claude Code's file permission checks match
`Edit(path)` only, and a single `Edit` rule covers every file-editing tool
(Write, Edit, NotebookEdit). `Write(path)` and `MultiEdit(path)` rules are never
consulted and are rejected at startup as unmatched, so twsrt does not emit them.
The Bash write path is enforced independently by `sandbox.filesystem.denyWrite`.

**Directory vs file detection**: twsrt checks the filesystem at generation time.
If the expanded path is a regular file, no `/**` suffix is added. If it is a
directory or does not exist, `/**` is added (fail-safe: assume directory).
Glob patterns (containing `*` or `?`) are never expanded.

#### 6.1.2 Selective Merge

Claude's `settings.json` contains both twsrt-managed sections and
human-maintained sections. The selective merge algorithm preserves the latter:

```
FULLY REPLACED by twsrt:          PRESERVED (human-maintained):
  permissions.deny                   hooks
  permissions.ask                    plugins
  sandbox.network.allowedDomains     additionalDirectories
                                     permissions.allow entries:
SELECTIVELY MERGED:                    - Blanket tool allows (Read, Glob, ...)
  permissions.allow                    - MCP tool allows (mcp__*)
    → Only WebFetch(domain:*) entries  - Project-specific (Bash(./gradlew:*))
      are managed by twsrt
```

This means a developer can add a `Bash(./gradlew:*)` allow, configure MCP
server permissions, or set up hooks — and `twsrt generate --write` will not
touch them. Only the WebFetch domain entries within the allow list are
managed.

### 6.2 Copilot CLI

GitHub Copilot CLI uses command-line flags for permission control. It has a
simpler, two-state model: deny or allow (no "ask" tier).

#### 6.2.1 Translation Table

| Canonical Rule | Copilot CLI Output | Notes |
|---|---|---|
| denyRead / denyWrite | No output | SRT enforces for Bash at OS level; Copilot has no path-level control |
| allowWrite | `--allow-tool 'shell(*)'`, `--allow-tool 'read'`, `--allow-tool 'edit'`, `--allow-tool 'write'` | Deduplicated across multiple allowWrite entries |
| allowedDomains | No output | SRT enforces for Bash at OS level |
| Bash deny command | `--deny-tool 'shell({cmd})'` | Full fidelity |
| Bash ask command | `--deny-tool 'shell({cmd})'` + stderr warning | **Lossy**: Copilot has no "ask" equivalent |

#### 6.2.2 Lossy Mapping: Ask → Deny

Copilot CLI has no concept of "prompt the user before executing." When a
bash-rules `ask` entry is translated, twsrt maps it to `--deny-tool`
(the more restrictive option) and emits a warning:

```
Warning: Bash ask rule 'git push' mapped to --deny-tool for copilot (no ask equivalent)
```

This is a deliberate **fail-safe**: it is better to block a command entirely
than to allow it without the intended human confirmation step. The warning
ensures administrators are aware of the fidelity loss.

### 6.3 Codex

Codex ships an always-on kernel sandbox of its own. twsrt compiles canonical
filesystem and network policy into a user-level named permission profile in
`~/.codex/config.toml` (extending the built-in `:workspace` base) plus
`deny`-only execution-prefix rules in `~/.codex/rules/twsrt.rules`. The
profile is the enforcement boundary for local subprocesses; the prefix rules
govern only requests to execute **outside** the sandbox. Upstream status:
permission profiles are Beta, `.rules` files are Experimental.

#### 6.3.1 Translation Table

| Canonical Rule | Codex Output | Notes |
|---|---|---|
| denyRead path/glob | filesystem `deny` | Blocks Codex's default read-everything posture |
| denyWrite exact path | filesystem `read` | Read-only |
| denyWrite glob | filesystem `deny` + warning | **Lossy narrowing**: Codex cannot express read-only for globs; deny blocks reads too (fail-safe) |
| allowWrite absolute/home path | Profile workspace root | Terminal `/**` and trailing slashes normalize to the concrete directory; unsupported shapes (`~`, `/`, other globs) and deny-conflicted roots are skipped with a warning; inherited workspace rules provide writes and deny overrides |
| allowWrite relative path | No additional output | Already covered by the runtime workspace |
| allowedDomains / deniedDomains | network `domains` allow/deny | `domains` table always emitted; empty map blocks all domain traffic (allowlist semantics) |
| Exact Unix socket path | network `unix_sockets` allow | Directory entries skipped with warning |
| Bash deny command | `prefix_rule(..., decision = "forbidden")` | Hard deny instead of default prompt for sandbox-escape requests; rules file only generated while `codex_rules` is set in config.toml (optional) |
| Bash ask command | Not compiled + warning | See 6.3.2 |
| Bash allow command | Not compiled + warning | See 6.3.2 |

Accepted trade-off: an added workspace root is writable in every Codex
session regardless of the working directory — exactly the grant canonical
`allowWrite` expresses, but broader than Codex's per-project trust default.
The inherited `.git`/`.codex`/`.agents` protection and the deny rules in
`filesystem.:workspace_roots` bound the blast radius, and a root that
collides with a deny rule is dropped in favor of the deny.

#### 6.3.2 Deliberately Not Compiled

Two canonical rule classes are skipped for Codex, each with a generation-time
warning. Both skips avoid weakening Codex's escalation boundary.

- **bash-rules `allow` commands.** In Codex's rules language,
  `decision = "allow"` means "run this command **outside the sandbox**
  without prompting" — auto-approved unsandboxed execution. That is strictly
  weaker than Codex's default, which prompts for every escalation request.
  The canonical `allow` intent ("don't ask, still sandboxed") does not
  survive translation, so it is not emitted.
- **bash-rules `ask` commands.** `decision = "prompt"` restates what Codex
  does by default for every out-of-sandbox request. Emitting ~50 prompt
  rules adds bulk, not security.

Consequently Codex output is identical in yolo and full mode, and the entire
Bash deny list is only enforced at the sandbox boundary: a command running
*inside* the writable workspace (e.g. `git reset --hard`) never consults the
prefix rules. Codex has no in-sandbox command gate; the kernel sandbox is the
enforcement layer there. Hooks are not used as a compensating control because
Codex documents their command interception as incomplete and does not support
hook-driven `ask` decisions.

#### 6.3.3 Pinned Invariants

twsrt owns four top-level keys in the managed `config.toml` and checks them
for drift; each defends a distinct silent-weakening vector:

| Key | Value | Defends against |
|---|---|---|
| `default_permissions` | `"twsrt"` | Profile deselected out-of-band |
| `approval_policy` | `"on-request"` | A stale `never` auto-approving escalations |
| `approvals_reviewer` | `"user"` | Delegating approval decisions to the model |
| `allow_login_shell` | `false` | Login-shell environments bypassing the profile (stricter than Codex's default `true`) |

twsrt does not manage WebSearch, MCP/apps, connectors, or subprocess
environment inheritance in this version.

User-level configuration is operationally convenient and requires no root
access, but it is not administrator-enforced: a user can deliberately bypass
it with full-access or ignore-user-configuration options. Machine-enforced
non-bypassability would require managed configuration outside the user profile.

### 6.4 pi-mono (Planned)

pi-mono support is architecturally planned but not yet implemented. The
`AgentGenerator` protocol allows adding new agents by implementing three
methods:

```
AgentGenerator Protocol:
  name      → str                          (agent identifier)
  generate  → (rules, config) → str        (produce agent-native config)
  diff      → (rules, target) → DiffResult (detect drift)
```

Adding pi-mono requires:
1. Implementing `PiMonoGenerator` conforming to the protocol
2. Registering it in the `GENERATORS` dictionary
3. Defining its translation rules (which canonical rules map to which
   pi-mono configuration format)
4. Identifying lossy mappings (if pi-mono lacks deny, ask, or network
   control equivalents)

The architecture imposes no coupling between agents — each generator
translates independently from the same normalized `SecurityRule` list.


## 7. Risk Reduction Analysis

### 7.1 Threat Mitigation Matrix

| Threat | Without twsrt | With twsrt (SRT + Agent) |
|---|---|---|
| Agent reads `~/.aws/credentials` via Bash (`cat`) | Must manually configure each agent's deny list | SRT blocks `read()` syscall **AND** agent blocks `Bash(cat)` — two layers |
| Agent reads `~/.aws/credentials` via Read tool | Must manually configure each agent's deny list | Agent blocks `Read()` tool — one layer (SRT does not cover built-in tools) |
| Agent runs `rm -rf /` | Must manually add to each agent's deny list | Bash deny rule translates to all agents automatically |
| Agent sends data to `evil.com` via Bash (`curl`) | Must manually configure network allowlists per agent | SRT network proxy blocks **AND** agent blocks `Bash(curl)` — two layers |
| Agent sends data to `evil.com` via WebFetch | Must manually configure network allowlists per agent | Agent `WebFetch(domain:...)` allow check — one layer |
| Config drift (deny rule removed) | Undetectable until exploit | `twsrt diff` detects missing rules, exit code 1 |
| Human error in settings.json | Manual edits to complex JSON | Managed sections are machine-generated; human edits only to non-security sections |
| New agent added to workflow | Start from scratch, risk incomplete coverage | Implement generator protocol; same resolved profile, guaranteed same policy |
| Agent "asks" to run `git push` but Copilot just runs it | Copilot silently allows (no ask concept) | twsrt maps ask → deny for Copilot, warns on stderr |

### 7.2 Quantitative Risk Reduction

Without twsrt, maintaining N agents with M security rules requires N*M
manual configuration entries. Each is independently editable, independently
driftable, and independently auditable.

With twsrt, M rules are maintained once. Translation is deterministic.
Drift is detectable. The attack surface for human error drops from O(N*M)
to O(M).

### 7.3 What twsrt Does NOT Protect Against

Honest limitations:

- **SRT bypass via kernel exploit**: If the OS sandbox is compromised,
  Layer 1 falls. Layer 2 (agent permissions) still applies but is
  implemented in userspace.
- **Agent software bugs (Bash tools)**: If Claude Code's permission engine
  has a vulnerability that ignores Bash deny rules, Layer 1 (SRT) still
  blocks at OS level. This is true defense in depth.
- **Agent software bugs (built-in tools)**: If the agent's permission
  engine fails to enforce Read/Write/Edit deny rules, there is **no
  OS-level fallback**. Built-in tools run inside the agent's Node.js
  process, outside the SRT sandbox. See Section 7.4.
- **Misconfigured canonical sources**: twsrt translates faithfully. If
  the selected JSONC fragments are too permissive, the compiled canonical
  JSON and generated agent configs will be too. Garbage in, garbage out —
  but at least it is consistent across all agents.
- **Runtime configuration changes**: SRT's `ignoreViolations` allows
  per-command exceptions at runtime. twsrt does not manage these.

### 7.4 Known Enforcement Gaps

This section documents verified limitations in the current enforcement
model. A security document that omits known gaps is worse than no
document at all.

**SRT sandbox scope**: The SRT sandbox (Seatbelt on macOS, bubblewrap on
Linux) enforces filesystem and network restrictions at the kernel level,
but **only for Bash commands and their child processes**. Built-in agent
tools (Read, Write, Edit, Glob, Grep, WebFetch) execute within the
agent's own process and are not subject to SRT enforcement.

This means the defense-in-depth model is asymmetric:

```
Bash(cat ~/.aws/credentials)  →  SRT blocks (kernel)  +  Agent blocks (permissions)
Read(~/.aws/credentials)      →  Agent blocks only (permissions, best-effort)
```

**Built-in tool permission enforcement**: Anthropic's documentation states
that Claude Code makes a *"best-effort attempt"* to apply deny rules to
built-in file tools. Multiple community-reported issues (GitHub #6631,
#24846) document cases where Read/Write deny rules were not enforced for
built-in tools. The deny rules generated by twsrt for Read/Write/Edit
provide defense-in-intent but may not be reliably enforced by all agent
versions.

**Implication for twsrt**: twsrt generates correct deny rules for all
tool types. The translation is faithful regardless of enforcement gaps.
However, administrators should understand that the effective security
posture differs by access path:

| Access Path | Enforcement Confidence |
|---|---|
| Bash commands accessing denied paths | **High** — kernel-enforced by SRT |
| Bash commands accessing denied network | **High** — proxy-enforced by SRT |
| Built-in tools accessing denied paths | **Medium** — depends on agent enforcement quality |
| Built-in tools accessing denied network | **Medium** — depends on agent enforcement quality |
| Codex out-of-sandbox escalation | **Medium** — user-level config, layer-bypassing possible (see below) |

**Codex profile silent deactivation**: If a legacy `sandbox_mode` /
`sandbox_workspace_write` setting appears in *any* loaded Codex config layer
(managed, team, project, config profile) or `--sandbox` is passed on the CLI,
Codex silently falls back to the legacy sandbox settings and ignores
`default_permissions` — no error is raised. twsrt's `_reject_legacy_sandbox`
guard is fail-safe only for the managed `config.toml` it owns; other layers
are invisible to it. Mitigations: twsrt prints a reminder on every Codex
generate/diff, and `codex doctor` shows the effective sandbox posture — run
it after changing any other config layer.

**Recommendation**: For the highest-value secrets (cloud credentials, SSH
keys, GPG keys), rely on the SRT sandbox as the primary control. Ensure
these paths are in `denyRead` so that Bash-based access is kernel-blocked.
The agent-level deny rules provide additional coverage but should not be
the sole control for critical assets.


## 8. Operational Model

### 8.1 Initial Setup

```bash
twsrt config --init                     # Create config and base JSONC fragments
twsrt config                            # Edit config.toml
# Edit the configured JSONC fragments   # Define sandbox and command policy
twsrt generate                           # Preview default profile for every agent
twsrt generate --write                   # Write canonical JSON + configured targets
twsrt diff                               # Verify both generated layers
```

`config --init` creates `config.toml`, `srt/base.jsonc`, and
`bash/base.jsonc`, then opens the TOML file in `$EDITOR` (falling back to
`vi`). Existing configurations are never overwritten by initialization.

### 8.2 Policy Change Workflow

```bash
# 1. Edit a canonical fragment
vim ~/.config/twsrt/bash/base.jsonc     # Add "terraform" to deny list

# 2. Preview the resolved profile
twsrt generate --profile default        # Compile in memory; write nothing

# 3. Apply canonical and agent outputs
twsrt generate --profile default --write

# 4. Verify the same profile
twsrt diff --profile default            # Exit 0 means no canonical or agent drift
```

For a specialized environment, define a profile that extends a compatible
base and adds fragments. Preview and diff with the same `--profile` value;
otherwise the configured default is intentionally compared instead.

### 8.3 Drift Detection

Run periodically or in CI to catch unauthorized changes:

```bash
twsrt diff                              # Check all agents
# Exit 0: no drift
# Exit 1: drift detected (missing or extra rules)
# Exit 2: target file missing

# Example output:
# srt canonical: no drift
# bash canonical: no drift
# claude: 2 missing, 1 extra
#   + Bash(terraform) (missing from existing)
#   + Bash(terraform *) (missing from existing)
#   - Bash(docker run:*) (in existing, not in sources)
```

### 8.4 Adding a New Agent

```python
# 1. Implement the AgentGenerator protocol
class PiMonoGenerator:
    @property
    def name(self) -> str:
        return "pimono"

    def generate(self, rules, config) -> str:
        # Translate SecurityRules to pi-mono format
        ...

    def diff(self, rules, target) -> DiffResult:
        # Compare generated vs existing
        ...

# 2. Register in GENERATORS dict
GENERATORS["pimono"] = PiMonoGenerator()

# 3. Use immediately
# twsrt generate pimono
# twsrt diff pimono
```

No changes to canonical fragments, profiles, or other generators are required.

### 8.5 Adding a Canonical Source Kind

Canonical composition is reusable, but accepting a new kind without domain
semantics would be unsafe. Adding one therefore requires an explicit adapter:

1. register the kind in `src/twsrt/lib/config.py`;
2. define its compiled-document validation and normalized-rule translation in
   `src/twsrt/lib/sources.py`;
3. include the resulting document in `CompilationResult` if downstream
   generators need source-specific metadata;
4. add configuration, profile-resolution, composition-conflict, compilation,
   write, and drift tests.

Profile inheritance, fragment lookup, JSONC parsing, structural union, strict
serialization, output staging, and canonical drift detection remain shared.
The explicit registration step is a security boundary: a new document format
cannot silently bypass validation merely because generic composition can merge
its JSON objects.
