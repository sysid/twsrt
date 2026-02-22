# Security Concept: Agentic Coding Configuration Management

## 1. Executive Summary

AI coding agents (Claude Code, GitHub Copilot CLI, pi-mono) operate with
broad access to the developer's filesystem, network, and shell. Each agent
implements its own permission model with its own configuration format. This
heterogeneity creates a systemic risk: security rules must be maintained
independently per agent, inviting configuration drift, human error, and
coverage gaps.

**twsrt** solves this by establishing two canonical security sources and
automatically translating them into each agent's native configuration format.
Combined with Anthropic's Sandbox Runtime Tool (SRT) at the OS level, this
creates a **defense-in-depth** architecture: SRT enforces OS-level invariants
that no agent can bypass regardless of bugs, while twsrt ensures every agent
receives consistent, drift-free application-level rules from the same policy.
Neither layer alone is sufficient; together they close each other's gaps
(see Section 3.7).

```
                    CANONICAL SOURCES (human-maintained)
                    ====================================
                    ~/.srt-settings.json        — OS-level sandbox rules
                    ~/.config/twsrt/bash-rules.json — command deny/ask rules
                              │
                              ▼
                    ┌──────────────────┐
                    │      twsrt       │  deterministic translation
                    │   (generator)    │  + drift detection
                    └──────┬───────────┘
                           │
              ┌────────────┼────────────┐
              ▼            ▼            ▼
     Claude Code     Copilot CLI    pi-mono
     settings.json   --flag args    (planned)

                    ENFORCEMENT LAYERS
                    ==================
     Layer 1 (OS):  SRT sandbox — syscall-level deny (Bash only, kernel enforcement)
     Layer 2 (App): Agent permissions — tool-level deny/ask (all tools, application enforcement)
```

**Key invariant**: Canonical sources are never written by twsrt. Generated
targets are never hand-edited for managed sections.


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

### 3.2 Single Source of Truth

Every security rule exists in exactly one canonical location. There is no
duplication between agents.

| Security Domain | Canonical Source | Why Separate |
|---|---|---|
| Filesystem access (read/write deny, write allow) | `~/.srt-settings.json` | SRT enforces at OS level for Bash; agent permissions for built-in tools |
| Network access (domain allowlist) | `~/.srt-settings.json` | SRT enforces via proxy for Bash; agent permissions for WebFetch |
| Bash command restrictions (deny/ask) | `~/.config/twsrt/bash-rules.json` | SRT cannot distinguish `bash rm` from `bash git push` |

**Why this matters**: When a security policy changes (e.g., adding a new
credential path to the deny list), the administrator updates exactly one
file. `twsrt generate --write` propagates the change to all agents. No
manual per-agent editing required.

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
it must not be writable either. A `denyRead` entry generates deny rules for
ALL file tools — Read, Write, Edit, and MultiEdit:

```
denyRead: ["~/.aws"]
    → deny: Read(~/.aws), Read(~/.aws/**)
            Write(~/.aws), Write(~/.aws/**)
            Edit(~/.aws), Edit(~/.aws/**)
            MultiEdit(~/.aws), MultiEdit(~/.aws/**)
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

- **Deterministic generation**: Given the same canonical sources, `twsrt generate`
  produces identical output. No runtime state, no randomness.
- **Drift detection**: `twsrt diff` compares generated rules against existing
  configs and reports missing/extra entries with specific exit codes.
- **No hand-editing**: Managed sections of target configs are machine-generated
  only. Human error in security-critical permission lists is eliminated.
- **Explicit warnings**: Lossy mappings (e.g., ask → deny for Copilot) emit
  warnings to stderr so administrators know where fidelity is reduced.

### 3.7 Why SRT + twsrt Together: A Strategic Assessment

Each layer alone has structural weaknesses. The combination eliminates them.

**SRT alone is insufficient.** SRT enforces hard OS-level boundaries for
Bash commands — no agent bug, prompt injection, or hallucination can bypass
a kernel-enforced `denyRead`. But SRT has no awareness of agent-specific
tool semantics. It cannot:

- Distinguish `bash rm` from `bash git push` (all shell commands look alike
  to a syscall filter)
- Prompt the user before a risky-but-legitimate command ("ask" semantics)
- Control built-in tools (Read, Write, Edit) that run inside the agent process
- Express its policy in each agent's native configuration format

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
Bash cmd semantics  ✗ can't distinguish ✓ deny/ask rules  ✓ agent layer
Built-in tools      ✗ not covered      ✓ agent deny       ✓ agent layer
Multi-agent policy  ✗ manual per-agent ✓ auto-translated  ✓ consistent
Drift detection     ✗ none             ✓ twsrt diff       ✓ auditable
Enforcement depth   kernel (Bash)      userspace (all)    kernel + userspace
```

**The key insight**: SRT provides the **hardest** security boundary for
the **most dangerous** attack vector. Bash is the primary tool an agent
uses to interact with the OS — it can execute arbitrary programs, access
any file, and make network connections. A kernel-level deny on Bash is
un-bypassable by the agent. twsrt then ensures this same policy is
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


## 4. Architecture

### 4.1 Data Flow

```
SOURCES (read-only)                    TARGETS (write-only, managed sections)
=====================                  =====================================

~/.srt-settings.json ─────┐
  filesystem.denyRead      │
  filesystem.denyWrite     ├──→ twsrt ──┬──→ ~/.claude/settings.json
  filesystem.allowWrite    │            │     permissions.{deny,ask,allow}
  network.allowedDomains   │            │     sandbox.network.allowedDomains
                           │            │
~/.config/twsrt/           │            ├──→ Copilot CLI flags (stdout)
  bash-rules.json ─────────┘            │     --deny-tool / --allow-tool
    deny: [...]                         │
    ask: [...]                          └──→ pi-mono config (planned)
```

### 4.2 Source/Target Invariant

This invariant is the foundation of the security model:

1. **Sources are NEVER written by twsrt** — they are human-maintained policy
   documents. twsrt only reads them.
2. **Target managed sections are NEVER hand-edited** — they are generated
   output. twsrt writes them via `generate --write`.
3. **Target non-managed sections ARE human-maintained** — hooks, plugins,
   MCP tool permissions, project-specific allows in Claude's settings.json
   are preserved by the selective merge algorithm (see Section 6.1.2).

Violating this invariant creates two risks:
- Hand-editing a target's managed section → will be overwritten on next
  `twsrt generate --write`, giving false sense of security
- Writing to a canonical source → creates circular dependency, makes
  it unclear what the "true" policy is

### 4.3 Internal Data Model

All canonical sources are normalized into a uniform internal representation
before translation:

```
SecurityRule:
  scope:   READ | WRITE | EXECUTE | NETWORK
  action:  DENY | ASK | ALLOW
  pattern: string (path, glob, command, or domain)
  source:  SRT_FILESYSTEM | SRT_NETWORK | BASH_RULES
```

Validation constraints enforced at construction:
- `pattern` must not be empty
- `NETWORK` scope requires `ALLOW` action (domains are allowlists only)
- `EXECUTE` scope requires `BASH_RULES` source
- `READ`/`WRITE` scope requires `SRT_FILESYSTEM` source


## 5. Canonical Sources

### 5.1 SRT Settings (`~/.srt-settings.json`)

The SRT (Sandbox Runtime Tool) configuration defines enforcement
boundaries. SRT enforces these at the OS level for Bash commands;
for built-in tools, the same rules are translated to agent-level
permissions (see Section 3.1 for coverage details):

```json
{
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

### 5.2 Bash Rules (`~/.config/twsrt/bash-rules.json`)

Bash command restrictions that SRT cannot enforce (SRT sees all shell
invocations equivalently):

```json
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
| denyRead directory (e.g., `~/.aws`) | `Read(~/.aws)`, `Read(~/.aws/**)`, `Write(~/.aws)`, `Write(~/.aws/**)`, `Edit(~/.aws)`, `Edit(~/.aws/**)`, `MultiEdit(~/.aws)`, `MultiEdit(~/.aws/**)` in deny | All file tools blocked; bare + recursive |
| denyRead file (e.g., `~/.netrc`) | `Read(~/.netrc)`, `Write(~/.netrc)`, `Edit(~/.netrc)`, `MultiEdit(~/.netrc)` in deny | All file tools blocked; bare only (no `/**`) |
| denyRead glob (e.g., `**/.env`) | `Read(**/.env)`, `Write(**/.env)`, `Edit(**/.env)`, `MultiEdit(**/.env)` in deny | Glob preserved as-is |
| denyWrite pattern | `Write({pattern})`, `Edit({pattern})`, `MultiEdit({pattern})` in deny | Write tools only (Read not included) |
| allowWrite path | No output | SRT enforces for Bash; Claude already has blanket allows |
| allowedDomains domain | `WebFetch(domain:{domain})` in allow + domain in `sandbox.network.allowedDomains` | Full fidelity |
| Bash deny command | `Bash({cmd})`, `Bash({cmd} *)` in deny | Bare + wildcard catches subcommands |
| Bash ask command | `Bash({cmd})`, `Bash({cmd} *)` in ask | Bare + wildcard catches subcommands |

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

### 6.3 pi-mono (Planned)

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
| New agent added to workflow | Start from scratch, risk incomplete coverage | Implement generator protocol; same canonical sources, guaranteed same policy |
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
  `~/.srt-settings.json` is too permissive, the generated configs will
  be too. Garbage in, garbage out — but at least it's consistently
  garbage across all agents.
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

**Recommendation**: For the highest-value secrets (cloud credentials, SSH
keys, GPG keys), rely on the SRT sandbox as the primary control. Ensure
these paths are in `denyRead` so that Bash-based access is kernel-blocked.
The agent-level deny rules provide additional coverage but should not be
the sole control for critical assets.


## 8. Operational Model

### 8.1 Initial Setup

```bash
twsrt init                              # Creates ~/.config/twsrt/ with defaults
# Edit ~/.config/twsrt/bash-rules.json  # Define command deny/ask rules
# Ensure ~/.srt-settings.json exists    # SRT config (typically pre-existing)
twsrt generate claude --write           # Generate + write Claude settings
twsrt generate copilot                  # Print Copilot flags to stdout
```

### 8.2 Policy Change Workflow

```bash
# 1. Edit the canonical source
vim ~/.config/twsrt/bash-rules.json     # Add "terraform" to deny list

# 2. Preview the change
twsrt generate claude                   # See updated Claude permissions

# 3. Apply
twsrt generate claude --write           # Write to settings.json (selective merge)

# 4. Verify
twsrt diff claude                       # Should report: no drift (exit 0)
```

### 8.3 Drift Detection

Run periodically or in CI to catch unauthorized changes:

```bash
twsrt diff                              # Check all agents
# Exit 0: no drift
# Exit 1: drift detected (missing or extra rules)
# Exit 2: target file missing

# Example output:
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

No changes to canonical sources, CLI, or other generators required.
