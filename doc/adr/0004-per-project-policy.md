# ADR 0004: Per-project policy via `generate --project`

- **Status:** Accepted
- **Date:** 2026-10-03
- **Deciders:** Tom
- **Implementation:** `src/twsrt/bin/cli.py` `generate --project`, `_stage_project_claude`;
  `src/twsrt/lib/sources.py` `compile_sources(extra_deny_write=…)`
- **Related:** ADR 0003 (composition only adds), ADR 0001 (`denyRead` ⇒ `denyWrite`);
  `doc/REFERENCE.md` → "Claude per-project launch premise"; README → "Per-project policy"

## Context

Some repositories need a different policy: extra write paths or domains, and — the hard part —
**fewer** rules than the global policy (e.g. a repo that legitimately reads `~/.kube`).

twsrt wrote global outputs only (`~/.srt-settings.json`, `~/.claude/settings.json`). Claude Code
layers project settings on top of the user file, but it **unions list settings across scopes**, so
a project file can add rules and never remove one:

```
~/.claude/settings.json      deny: [Read(~/.kube)]   ┐
<repo>/.claude/settings.json deny: []                ├─ union ─► deny: [Read(~/.kube)]   ✗ cannot drop
```

## Decision

1. **A project's policy is a profile.** Removing a rule = choosing a profile without that rule's
   fragment (ADR 0003). No `[projects]` table: the profile is passed with `-p`.
2. **`twsrt generate claude -w -p <profile> --project`** compiles into **`$PWD/.twsrt/`**
   (`--project` takes no argument):

   ```
   .twsrt/srt-settings.json             canonical srt   → srt -s .twsrt/srt-settings.json
   .twsrt/bash-rules.json               canonical bash
   .twsrt/claude-settings[.yolo].json   Claude target   → claude --setting-sources project,local
   .twsrt/.gitignore                    "*"                       --settings .twsrt/claude-settings.json
   stdout: the absolute .twsrt directory (status messages go to stderr)
   ```

   Nothing global is written: no canonical files, no Claude symlink flip, no `claude_sync` donor.
3. **Claude launch premise: `--setting-sources project,local --settings <file>`.** Skipping the user
   source is the only way a dropped rule stays dropped. Because the user file is skipped, the
   project file carries the user settings too: it is the selective merge of the project policy onto
   the global Claude target of the same mode (hooks, plugins, model).
4. **`.twsrt` is write-protected.** The compiler adds the absolute `$PWD/.twsrt` to `denyWrite`.
   Claude re-reads settings files during a session; an agent able to write `.twsrt/` could loosen
   its own policy. Every launch regenerates the files, overwriting anything a repo ships there.
5. **Codex and Copilot are rejected with `--project`** — no per-launch settings file verified.

## Alternatives considered

| Alternative | Why rejected |
|---|---|
| Hand-written `<repo>/.claude/settings.local.json` | Union semantics: can add, cannot remove a global rule |
| twsrt writes `<repo>/.claude/settings.local.json` | A plain `claude` launch in that repo also loads the user file → hooks run twice |
| Files under `~/.config/twsrt/projects/<slug>/` | Works, but Tom preferred the files next to the project; protection solved by decision 4 instead |
| `[projects."<path>"]` table in `config.toml` | YAGNI: only maps a directory to a profile; `-p` does that, and the repo still cannot choose its own profile |
| `--project DIR` | An optional value swallows the next token (`generate --project claude`); cwd is unambiguous |
| A separate `twsrt project` command | Duplicates `generate`; the difference is only output location |
| `CLAUDE_CONFIG_DIR` per project | Relocates credentials, history and plugins too — far too broad |

## Consequences

**Positive**

- Per-repo policy, including dropped rules, without weakening the composition model.
- The repository cannot choose or influence its profile; omitting `-p` yields `default_profile`
  (the full policy) — fails closed.
- Global files and running sessions are untouched.

**Negative / risks**

| Risk | Direction | Mitigation |
|---|---|---|
| Claude changes `--setting-sources` so the user file loads again | dropped rules return — fails **closed** | none needed |
| Claude stops honouring `--settings` when `user` is excluded | project session runs without twsrt policy — fails **open** | re-verify after upgrades (REFERENCE checklist); probe parity (open) |
| The repo's own `.claude/settings*.json` still loads (`project,local`) | a trusted repo can add rules or override sandbox scalars | same exposure as a plain `claude` launch |
| A plain `claude` session in the same repo lacks the `.twsrt` deny | it could rewrite `.twsrt/` while a project session runs | a global `denyRead` of `**/.twsrt` now implies `denyWrite` (ADR 0001) |
| Running from a subdirectory creates a second `.twsrt/` there | stray directory, no security impact | launch from the project root |
| Relative `sandbox.filesystem` entries in the project file would anchor at `.twsrt/` (settings-file root) | `allowWrite .` would grant `.twsrt/`, not the project | ADR 0002: all file rules move to `Edit`/`Read` permission rules, which anchor at the launch cwd (implementation pending) |

**Verification**

- `tests/bin/test_cli_project.py` (dropped rule absent in both outputs, user keys carried over,
  yolo, global files untouched, `.twsrt` write-denied, `.gitignore`, stdout contract, error paths).
- `--setting-sources project,local` verified interactively by Tom on 2026-10-02.
- Settings-file root for `--settings FILE` = `dirname(FILE)`: Claude Code 2.1.288 binary, `o3t`
  (`flagSettings`).
