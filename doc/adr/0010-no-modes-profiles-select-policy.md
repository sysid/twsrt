# ADR 0010: No modes — profiles select policy, launch flags select prompting

- **Status:** Accepted
- **Date:** 2026-11-24
- **Deciders:** Tom
- **Implementation:** `src/twsrt/lib/config.py` `_reject_unknown_keys`, `_REMOVED_KEYS`;
  `src/twsrt/lib/claude.py` `_FIXED_POSTURE`, `selective_merge`; `src/twsrt/lib/models.py`
  `require_sandbox`; `src/twsrt/bin/cli.py` `_compile`. Breaking change, target 4.0.0
- **Amends:** ADR 0003 (per-mode scalars via `[sandbox_overrides]`), ADR 0004 (output file names,
  mode-dependent merge base)
- **Related:** ADR 0002 (file rules as permission rules), ADR 0008 (policy files write-denied),
  ADR 0009 (Copilot native sandbox)

## Context

`--yolo` (March 2026) was added to run Claude with fewer prompts. One flag now decides three
unrelated things:

```
                     decided by --yolo today        where it belongs
 ask rules           kept / dropped                 policy  → profile
 sandbox posture     [sandbox_overrides.<mode>]     fixed   → same for every profile
 prompt skipping     implied, not done for Claude   launch  → the agent's own flag
```

### The flag means something different per agent

| | Claude | Copilot CLI | Codex | Copilot JetBrains |
|---|---|---|---|---|
| Output changes | yes | flags file only | no, silently | no, silently |
| `ask` rule, full | prompt | deny | not compiled | not compiled |
| `ask` rule, yolo | **allowed** | **allowed** | not compiled | not compiled |
| Enables prompt skipping | no | yes (emits `--yolo`) | no | no |
| Changes the sandbox | yes | no | no | no |
| Vendor's own "yolo" | skips prompts | all tools, paths, URLs | **sandbox off** | — |

### Defects that follow from it

1. **The names are inverted.** With the documented `[sandbox_overrides.full] enabled = false`, the
   mode that sounds safer has no kernel sandbox and yolo has one. Full mode then relies on
   permission rules alone; a bare `Bash` allow in the user's own settings (kept by the selective
   merge) lets every command without a deny/ask rule run unsandboxed and, in Manual mode,
   unprompted.
2. **`ask` fails open.** Dropping an ask rule turns "needs a human" into "allowed" exactly when no
   human is present. This contradicts the invariant that lossy translation goes the fail-safe way.
   It caused the critical finding of the 2026-08-01 audit (`docker` in `ask`, dropped by yolo,
   unsandboxed via `excludedCommands`).
3. **A per-session choice is global state.** Every `-w` repoints `settings.json`, also under running
   sessions. A routine `generate all -w` (e.g. in a housekeeping job) switches the machine to full.
4. **`diff` can miss the active file.** It compares the mode named on the command line, not the file
   Claude reads: with the active yolo file's `permissions.deny` emptied, `diff claude` exits 0.
5. **Override tables are not validated.** `[sandbox_overrides.yollo]` loads silently and the
   hardening is gone; neither `generate` nor `doctor` reports it.
6. **The sandbox can be off without anyone saying so.** A canonical srt document without `enabled`
   produces Claude settings without `sandbox.enabled`, which Claude treats as off. Codex and
   Copilot's native sandbox refuse `enabled: false`; Claude accepts it. Only Claude fails open.
7. **Most Claude-specific machinery exists only for the second file:** symlink anchor, migration,
   `[claude_sync]`, `mode_specific`, `*.yolo.*` targets, `[sandbox_overrides.*]`.

Profiles already express "the same policy without the prompts". With equal sandbox posture,
`generate claude --yolo` and `generate claude -p noask` differ only in `permissions.ask` being
absent versus `[]`.

## Decision

1. **There are no modes.** `--yolo` is removed from `generate` and `diff`, together with
   `claude_settings_yolo`, `copilot_output_yolo` and the `*.yolo.*` file names. A profile is the
   only policy selector; every agent has one target.
2. **Which commands prompt is policy, so it lives in fragments.** The default profile keeps `ask`
   for commands whose effect leaves the sandbox. A setup that wants a set of commands to run without
   asking puts their `ask` rules in a fragment of their own; profiles only add (ADR 0003), so the
   profile without them is the parent:

   ```toml
   [profiles.noask]             # optional: what "ask" lists runs without asking
   srt  = ["base"]
   bash = ["deny"]

   [profiles.default]           # default_profile: forgetting -p fails closed
   extends = ["noask"]
   bash = ["ask"]
   ```

   Leaving a command out means it is **allowed** inside the sandbox, attended or not. twsrt never
   drops an `ask` rule on its own.
3. **An `ask` rule without a human means deny.** twsrt emits the rule; the launch decides who
   answers (decision 4). No second profile is needed for this. Copilot keeps mapping `ask` to
   `--deny-tool`, Codex keeps not compiling it.
4. **Prompt skipping is a launch flag, never generated.** Copilot output no longer starts with
   `--yolo`.

   | Agent | Fewer prompts, ask rules still ask | Nobody present, ask rules deny |
   |---|---|---|
   | Claude | `--permission-mode auto` (or `bypassPermissions`) | `--permission-mode dontAsk`, or `permissions.denyInsteadOfPrompting` via `--settings` (keeps auto mode) |
   | Copilot | `--allow-all-tools` (deny flags win) | `-p` / `--autopilot`: what would prompt is denied |
   | Codex | `approvals_reviewer=auto_review` | `-a never` |

   Documented as traps: `codex --yolo` removes the sandbox; `copilot --yolo` also drops path and URL
   verification, and its in-process file tools are checked in software only (ADR 0009).
5. **Claude's sandbox posture is fixed**, as it already is for Copilot and Codex. twsrt always emits
   `sandbox.enabled: true` and `sandbox.allowUnsandboxedCommands: false`. A canonical
   `enabled: false` is an error for Claude, as for Codex and Copilot. `[sandbox_overrides.*]` is
   removed without replacement; `autoAllowBashIfSandboxed` and `excludedCommands` stay unmanaged and
   are preserved by the selective merge. Running one session without sandbox is a launch decision:
   `claude --settings '{"sandbox":{"enabled":false}}'`.
6. **Claude gets one real file.** `claude_settings` names the file Claude reads
   (`~/.claude/settings.json`; any other file name is a load error) and is written in place by the
   selective merge. The symlink anchor, migration and `[claude_sync]` are removed. `diff` therefore
   checks what Claude reads. Pass-through sandbox keys the profile does not set are removed from
   the file: otherwise a loosening from another profile, or from a removed override table, stays.
7. **Per-launch policy is `--project`** (ADR 0004), which works in any directory, so no new
   mechanism is needed. Its outputs move to **`./.twsrt/<profile>/`**, so sessions with different
   profiles in one directory do not overwrite each other. `.gitignore` and the write-deny stay on
   `./.twsrt`; stdout stays the directory to use, so launchers that capture it do not change. A
   launcher with the 3.x path hard-coded would keep loading the old file, so `--project` refuses to
   run while 3.x files are left in `./.twsrt`. It also refuses a symlinked directory, and profile
   names that share a directory on a case-insensitive filesystem are a load error:

   ```bash
   # nobody present: default profile, ask rules deny
   claude-unattended() {
     claude --settings '{"permissions":{"denyInsteadOfPrompting":true}}' "$@"
   }
   # other policy, this launch only
   claude-p() {
     local p=$1 d; shift; d=$(twsrt generate claude -w -p "$p" --project) || return
     claude --setting-sources project,local --settings "$d/claude-settings.json" "$@"
   }
   ```

   The global files keep the strict `default_profile`. The direction matters: Claude merges lists
   across scopes, so a launch can add ask rules but only `--setting-sources` can leave them out.
8. **Unknown and removed keys are load errors**; a removed key names its replacement.
   Nothing is silently ignored, and there is no compatibility shim.

## Alternatives considered

| Alternative | Why rejected |
|---|---|
| Rename the modes (e.g. attended/unattended) | Fixes the name only; defects 2–7 remain |
| Give every agent a mode | Codex, Copilot settings and JetBrains have no second posture to select; it would be invented |
| Reject `--yolo` for Codex and JetBrains only | Removes the silent no-op; Claude and Copilot keep disagreeing about `ask` |
| Global file without asks, attended sessions add them via `--settings` | Forgetting the overlay fails open |
| twsrt resolves `ask` by a config switch (`prompt`/`deny`/`allow`) | Reintroduces a mode; `allow` is the fail-open case again |
| One mode-free `[claude_sandbox]` table | Nothing left to configure: `enabled` must be true, the rest is preserved. Nested tables also replace compiled sections, bypassing ADR 0003 |
| Keep `[sandbox_overrides.full] enabled = false` | No remaining use case (Tom, 2026-11-24) |
| twsrt writes `denyInsteadOfPrompting` | It also removes `AskUserQuestion` and plan tools; a session property, not policy |

## Consequences

**Positive**

- One rule for every agent: profile = policy, launch flag = prompting, sandbox always on.
- Files on disk no longer depend on which session started last; `diff` needs no mode.
- `ask` never becomes allow.
- Per-launch Claude sessions are stricter than global ones: `allowUnsandboxedCommands: false` from
  `--settings` makes the sandbox admin-required (Claude ≥ 2.1.285), so a repository's
  `.claude/settings*.json` can no longer loosen it. From user settings it does not. This closes most
  of the ADR 0004 risk "the repo's own settings still load"; a repository's
  `autoAllowBashIfSandboxed` still applies.
- Codex and Copilot lose nothing: they had no working mode.

**Negative / risks**

| Risk | Mitigation |
|---|---|
| Breaking: CLI flag, config keys, file names, launchers | Major version; load errors name the replacement |
| The default profile prompts for commands yolo let through | Sort the ask list once: keep `ask` only where the effect leaves the sandbox; move the rest to `deny` or drop it |
| Another profile written with `-w` without `--project` still replaces the global files | Unchanged from today; per-launch policy uses `--project` |
| `--setting-sources project,local` sessions do not use the user file, so preferences changed in them may not persist | Change preferences in a plain `claude` session; every launch recompiles from the global file |
| `./.twsrt/` appears in each launch directory | Self-ignoring (`.gitignore` `*`) |
| A hand-written `excludedCommands` still opens the sandbox | Unchanged; not part of the policy. Candidate `doctor` check |
| A sandbox that cannot start: Claude runs commands unsandboxed (`failIfUnavailable` unset) | Unchanged; candidate follow-up, would break launches on unsupported hosts |

**Migration**

1. Sort the `ask` lists (decision 2), after the always-on sandbox is in place.
2. Set `claude_settings = "~/.claude/settings.json"`; delete `[claude_sync]`,
   `[sandbox_overrides.*]`, `*_yolo` keys.
3. `twsrt generate claude -w`: the merge reads through the old symlink, so the active file's own
   settings are kept, and the atomic write replaces the link with a regular file.
4. Remove `settings.full.json`, `settings.yolo.json`, `copilot-flags.yolo.txt` and the 3.x files
   directly under each `./.twsrt`; update launchers.

**Documents to change with the implementation:** README (modes, launch functions, Claude section),
REFERENCE (rule mapping, symlink, sync, per-project premise), SECURITY_CONCEPT, AGENTS.md
(`[sandbox_overrides.*]` invariant), ADR 0002 (yolo row), ADR 0003 and 0004 (amendment notes). The
per-project premise claims all settings files reload mid-session; `--settings` files are not watched
(below).

## Evidence

Checked 2026-11-24 with Claude Code 2.1.331, Codex 0.153.4, Copilot CLI 1.0.114, twsrt 3.4.0.

| Claim | Result | Source |
|---|---|---|
| Codex output identical with and without `--yolo`; no warning | Confirmed | twsrt run, throwaway config |
| `--yolo` ≡ profile without asks, given equal posture | Confirmed | twsrt run |
| Defects 4, 5, 6 | Reproduced | twsrt run |
| Codex and Copilot (native) refuse canonical `enabled: false` | Confirmed | twsrt run |
| `--project` works in a non-repository directory | Confirmed | twsrt run |
| Claude: ask and deny rules apply in every mode including `bypassPermissions` | Documented | permission-modes.md |
| Claude: command-specific asks prompt despite `autoAllowBashIfSandboxed` and in auto mode | Documented | sandboxing.md, permission-modes.md |
| Claude: `dontAsk` denies calls matching `ask` rules | Documented | permission-modes.md |
| Claude: `denyInsteadOfPrompting` (≥ 2.1.319), user, managed or `--settings` scope | Documented | settings-reference.md |
| Claude: `--settings` with `allowUnsandboxedCommands: false` ⇒ admin-required | Documented | sandboxing.md |
| Claude reloads `permissions` edits in running sessions | Documented | settings.md |
| Claude reads `sandbox.enabled` from merged settings per command | Static reading | binary, `vo`/`no`/`mh` |
| Claude watches a symlinked settings file **and** its target; skips `flagSettings` | Static reading | binary, settings watcher |
| **Switching the symlink turns the sandbox off in a running session** | **Not observed live**; follows from the two rows above | — |
| Copilot: `--yolo` = all tools + paths + URLs; `--deny-tool` still denies; `-p`/autopilot deny what would prompt | Confirmed | `copilot --help`, `copilot help permissions` |
| Copilot: `deniedPaths` still hold for in-process tools under `--allow-all-paths` | **Unknown** | — |
| Codex: `--yolo` = no sandbox, no approvals | Confirmed | `codex --help`, agent-approvals-security |
| Codex: `-a never` works with all `--sandbox` modes | Documented; with permission profiles **not verified** | agent-approvals-security |

The decision does not depend on the three unverified rows: defects 1, 2 and 4–7 stand without them.
