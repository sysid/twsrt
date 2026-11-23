# ADR 0009: Copilot uses its native sandbox instead of the SRT wrapper

- **Status:** Accepted
- **Date:** 2026-11-23
- **Deciders:** Tom
- **Implementation:** `src/twsrt/lib/copilot_sandbox.py` (policy builder),
  `src/twsrt/lib/copilot.py` (settings.json + flags), `src/twsrt/lib/copilot_jetbrains.py`
  (github-copilot.xml), `src/twsrt/bin/cli.py` (staging, lock skip)
- **Related:** ADR 0001 (`denyRead` ⇒ `denyWrite`), ADR 0004 (per-project policy), ADR 0008
  (policy files write-denied); research `thoughts/research/2026-11-23-copilot-native-sandbox-cli-intellij.md`
  (probe evidence, §7.3–7.4)

## Context

Copilot ran under the SRT wrapper (`srt -c "copilot …"`); twsrt only emitted a flag snippet.
Copilot's local sandbox became GA for the CLI on 2026-10-07 and for JetBrains on 2026-10-28.
The IntelliJ agent cannot be wrapped by SRT at all, so without a native target it has no
sandbox policy.

Both surfaces use the same runtime (IntelliJ runs the bundled CLI), but read separate
configuration (verified: the IDE ignores `~/.copilot/settings.json`):

| Surface | File | Owned part |
|---|---|---|
| Copilot CLI | `~/.copilot/settings.json` | `sandbox` key, `allowedUrls`, `deniedUrls` |
| IntelliJ | `<IDE config>/options/github-copilot.xml`, one per product and version | `<option name="sandbox*">`, `<sandbox{Readwrite,Readonly,Denied}Paths>`, `<sandbox{Allowed,Blocked}Hosts>` |

The native model differs from SRT:

| Aspect | SRT | Copilot native |
|---|---|---|
| Confined | whole agent process | child processes (shell, local MCP/LSP); in-process file tools and web fetch are checked in software only |
| Read | read-all minus `denyRead` | deny-by-default allowlist plus automatic grants |
| Paths | literal, `~`, cwd-relative, globs | absolute or `~` literal; no globs, no cwd-relative |
| Empty host allowlist | no network | no restriction |

Probes against Copilot CLI 1.0.114 on macOS (research §7.3) showed that the native sandbox
already covers several things SRT needed explicit rules for: `.git/hooks` and `.git/config` are
read-only, docker.sock, ssh-agent and the pasteboard are unreachable, a denied path beats the
dev-tool grants, and `deniedUrls` blocks the web-fetch tool.

## Decision

1. **The native sandbox is the recommended enforcement layer for Copilot**, for both CLI and
   IntelliJ, and it is never combined with the SRT wrapper. Software-only enforcement of
   in-process tools is accepted. The flags-only mode under `srt -c "copilot …"` stays
   supported for configs without `copilot_settings` (decision 7).
2. **One policy builder, two renderers.** All translation lives in one builder; the CLI JSON
   and IntelliJ XML renderers only serialize. `copilot` and `copilot-jetbrains` are separate
   generators so `generate`, `diff` and warnings stay per surface.
3. **Translation:**

   | Canonical | Copilot |
   |---|---|
   | `denyRead` literal | `deniedPaths`, absolute, **including non-existent paths** (not created on macOS) |
   | `denyRead` glob with a concrete prefix | expanded at generate time, warned as a snapshot |
   | `allowWrite` `.` / `.git` | automatic grants (`addCurrentWorkingDirectory`) |
   | `allowWrite` literal | `readwritePaths` |
   | `denyWrite` literal not implied by `denyRead` | `readonlyPaths` (more specific path wins) |
   | `allowedDomains` non-empty / empty | `allowedHosts` / `allowOutbound: false` |
   | `deniedDomains` | `blockedHosts`; CLI also `deniedUrls` |
   | `allowedDomains` | CLI also `allowedUrls` (replaces `--allow-url` / `--deny-url` flags) |
   | `allowLocalBinding` | `allowLocalNetwork` (always explicit; IntelliJ defaults to `true`) |

   Fixed hardening values: `enabled`, `sandboxMcpServers`, `sandboxLspServers`,
   `sandboxExtensions` true; `allowBypass`, `keychainAccess` false; `allowDevToolAccess`,
   `auth.git`, `auth.gh` true.
4. **Not translated, warned:** unbounded globs (`**/.twsrt/**`, `/**/.env`, `/**/*.pem`, CI
   files), cwd-relative globs, `:port` suffixes (stripped), `allowUnixSockets`,
   `allowMachLookup`, `enableWeakerNetworkIsolation`, `ignoreViolations` (`allowPty` never
   reaches the generators: the canonical compile drops it).
   No repository enumeration to approximate them.
5. **Ownership and writes.** Only the owned part is merged and diffed; foreign keys and
   options are preserved. twsrt owns `allowedUrls` fully: URLs approved permanently inside
   Copilot are drift. An IntelliJ file whose IDE holds `<config>/.lock` is skipped with a
   warning (the running IDE overrides external changes); all other files are still written.
   IntelliJ targets are an explicit list in `config.toml`, not discovered.
6. **Self-protection.** The generated policy lists its own target files (both spellings, as in
   ADR 0008) in `readonlyPaths`, so a session started inside the dotfiles repository that holds
   `~/.copilot` cannot rewrite its own sandbox config.
7. `--project` is rejected for both generators: Copilot ignores sandbox settings in
   repository-level files. The Bash-rules flag snippet (`--deny-tool`, `--allow-tool`) remains.
   `copilot_settings` and `copilot_output` are independent `[targets]` keys; the URL flags
   leave the snippet only when `copilot_settings` is set.

## Alternatives considered

| Alternative | Why rejected |
|---|---|
| Keep the SRT wrapper (status quo) | No coverage for IntelliJ; two systems for one agent |
| Native sandbox nested inside SRT | Tom: never run both; nesting adds a failure mode without fixing IntelliJ |
| Enumerate repositories to protect `.git` / `.twsrt` | `.git` is protected natively; for `.twsrt`, a snapshot that goes stale silently isn't worth it |
| Skip non-existent `deniedPaths` | Docs say they are created as directories; macOS probe shows they are not, and emitting them protects files created later |
| Mirror SRT's read-all model (`readonlyPaths: ["~"]`) | Copilot's allowlist is stricter; add paths on demand |

## Consequences

**Positive**

- IntelliJ gets a twsrt-managed sandbox policy for the first time.
- One canonical policy drives Claude, Codex, Copilot CLI and Copilot IntelliJ.
- Git credentials are masked (`auth.git`/`auth.gh`), which SRT never offered.

**Negative / risks**

| Risk | Mitigation |
|---|---|
| In-process file tools and web fetch have no OS backstop | Accepted (decision 1); `deniedPaths` and `deniedUrls` keep the software check fully informed |
| Secret-file and CI-file globs are lost: `.env`, `*.pem`, `id_rsa`, `Jenkinsfile`, … are writable in write roots | Warned on every `generate` |
| `.twsrt` per-project policy is writable by the agent (weakens ADR 0008 for Copilot) | Warned; per-project policy does not apply to Copilot anyway |
| IntelliJ renderer depends on the plugin's undocumented XML format | `diff` detects drift; reverse-engineering notes in the research doc |
| IntelliJ has no URL rules: web fetch is unrestricted in the IDE | Warned |
| Results come from macOS only | Linux behaviour (path creation, sockets) unverified; revisit before supporting it |
