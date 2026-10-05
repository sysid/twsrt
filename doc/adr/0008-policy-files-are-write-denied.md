# ADR 0008: Policy files are write-denied in every compile

- **Status:** Accepted
- **Date:** 2026-10-05
- **Deciders:** Tom
- **Implementation:** `src/twsrt/lib/config.py` `_policy_files`, `_tilde`;
  `src/twsrt/lib/sources.py` `compile_sources`
- **Related:** ADR 0001 (`denyRead` ⇒ `denyWrite`), ADR 0004 (per-project policy, `.twsrt`
  protection); `SECURITY_CONCEPT.md` §3.4, §7.4

## Context

An agent that can write the twsrt policy can loosen it:

```
agent edits fragment / config.toml ──► next `generate -w` compiles the weaker policy
agent edits ~/.srt-settings.json   ──► next bare `srt` launch runs the weaker policy
```

Nothing protected these files. They were unwritable only while no `allowWrite` root covered them.
A stow-managed config breaks that: `~/.config/twsrt` links into a dotfiles repository, and an agent
launched there gets `allowWrite: ["."]` over the fragments.

A fragment cannot name these paths itself, because srt has no way to refer to the config location
(srt 0.0.78, `sandbox-utils.js` `normalizePathForSandbox`):

| Spelling in the srt settings | srt resolves it against |
|---|---|
| `x`, `./x`, `**/x` | the **launch cwd** (`path.resolve(process.cwd(), …)`), not the settings file |
| `~/x` | the home directory |
| `/x` | itself |
| `$HOME/x`, `${VAR}/x` | nothing: taken literally, then cwd-relative, so it matches nothing |

Symlinks: srt replaces a path with its real path only when the target stays inside the link's own
tree (`isSymlinkOutsideBoundary`). A stow link points outside it, so srt keeps the link spelling,
while Seatbelt matches the real vnode path. A deny on `~/.config/twsrt/config.toml` alone would
block nothing.

## Decision

1. `load_config` records `AppConfig.policy_files`: `config.toml` plus every `[sources.<kind>]`
   `output` and every `fragments.*.path`, including fragments no profile selects. Switching
   profiles must not activate a fragment that an agent has already rewritten.
2. `compile_sources` adds them to `denyWrite` in every compile, through the same implied-deny path
   as ADR 0001. `generate`, `show`, `diff`, `test` and `doctor` therefore see the same document.
3. Each path is emitted **absolute**, as `~/…` under `$HOME`, and, if it differs, **also as its
   real path**.
4. They are captured at load time, before `--project` moves the outputs into `.twsrt/`, so a
   project session still protects the global files.
5. Write-deny only. Reading the policy is harmless.

## Alternatives considered

| Alternative | Why rejected |
|---|---|
| Placeholder in fragments (`{config_dir}/**`), expanded at compile | New fragment syntax, easy to forget; every translator and `doctor` must handle it |
| Hard-coded paths in fragments | Breaks with `--config` or another layout; duplicates `config.toml` |
| Native srt variable or settings-file anchor | Does not exist (see table) |
| Protect only the config directory | Fragments may live outside it; relative `[sources]` paths can point anywhere |
| Emit only the link spelling | No-op under stow on macOS (see Context) |

## Consequences

**Positive**

- Wherever a write root covers the config, a sandboxed agent cannot change the policy it runs
  under. This holds in every target: srt `denyWrite`, Claude `Edit` deny, Codex read-only.
- The `~/…` spelling coincides with hand-written fragment entries, which are then deduplicated.

**Negative / risks**

| Risk | Mitigation |
|---|---|
| Fragments cannot be edited from inside a sandboxed agent | Intended; edit from a plain terminal |
| Compiled output depends on `$HOME` and the symlink layout (REFERENCE invariant 6) | `generate` and `diff` run under the same `$HOME` in practice |
| Agent targets (`[targets]`: Codex config, rules, Copilot flags) are not covered | Claude protects its own settings; extend to `[targets]` if needed |
| `twsrt test` cannot prove the deny when the files lie outside every write root | Run it from the directory that covers them (e.g. the dotfiles repo) |
