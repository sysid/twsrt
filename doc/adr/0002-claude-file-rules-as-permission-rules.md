# ADR 0002: Claude Code — all filesystem rules travel as `Read`/`Edit` permission rules

- **Status:** Accepted. Deny part implemented (existing behaviour); allow part decided 2026-10-03,
  **implementation pending**
- **Date:** 2026-10-03
- **Deciders:** Tom
- **Implementation:** `src/twsrt/lib/claude.py` `ClaudeGenerator.generate`, `selective_merge`
- **Related:** ADR 0001 (`denyRead` ⇒ `denyWrite`), ADR 0006 (translations never widen);
  bkmr memories 3742 (anchoring), 3671 (folding, ARG_MAX); vimwiki `help/srt.md` → Claude Code

## Context

### Two routes into one sandbox

A filesystem rule reaches Claude Code's OS sandbox (Bash tool) by one of two routes. Both end in the
same srt library, but they resolve relative paths **differently** (Claude Code 2.1.288 binary):

```
settings.json
├── permissions.deny/allow: Edit(P), Read(P)  ── route A ── Ugt → KYn ──┐
│     (also gates Claude's Read/Edit/Write tools)                       ├─► srt library ─► Seatbelt
└── sandbox.filesystem: allowWrite/denyWrite/denyRead ── route B ── hoe → YYn ──┘   (Bash only)
```

| Spelling | srt CLI | Route A (`Edit(…)`/`Read(…)`) | Route B (`sandbox.filesystem`) |
|---|---|---|---|
| `x`, `./x`, `**/x` | launch cwd | **left relative → Claude launch cwd** | **settings-file root** (`~/.claude` for user settings, `dirname(FILE)` for `--settings FILE`) |
| `/x` | absolute | settings-file root (trap) | absolute |
| `//x` | — | absolute | absolute |
| `~/x` | home | home | home |

Only route A anchors relative entries the way srt does.

### State before this decision

| Canonical rule | Claude output | Route |
|---|---|---|
| `denyRead P` | `Read(P)`, `Edit(P)` deny | A ✓ |
| `denyWrite P` | `Edit(P)` deny | A ✓ |
| `allowWrite P` | `sandbox.filesystem.allowWrite: [P]` | **B** |

The deny lists were already kept empty in `sandbox.filesystem` (emitting both routes once pushed the
Seatbelt profile past ARG_MAX, bkmr 3671). `allowWrite` was the one rule left on route B, chosen
because an `Edit` **allow** rule also auto-approves Claude's edit tools.

### The defect this exposed

The real policy contains the relative entries `.` and `.git`. On route B, in
`~/.claude/settings.json`, they resolve to `~/.claude` and `~/.claude/.git`. A live session's
sandbox config showed exactly that:

```
allowOnly: [ ".", …, "/Users/Q187392/.claude", "/Users/Q187392/.claude/.git", … ]
             ▲               ▲                          ▲
   Claude's own cwd   from twsrt's "."          from twsrt's ".git"
```

| Entry | srt CLI (intended) | Claude, route B (actual) |
|---|---|---|
| `.` | project directory | **`~/.claude` writable** |
| `.git` | `<project>/.git` | **`~/.claude/.git` writable** |

That is a **widening** (violates ADR 0006 rule 4) and a **divergence** between srt and Claude,
contradicting the goal that both behave identically for the same policy.

## Decision

**Every filesystem rule is translated to a route-A permission rule; Claude's
`sandbox.filesystem` path lists (`allowWrite`, `denyWrite`, `denyRead`) are all managed-empty.**

| Canonical rule | Claude output |
|---|---|
| `denyRead P` | `Read(P)`, `Edit(P)` in `permissions.deny` (+ `/**` variants for directories) |
| `denyWrite P` (incl. implied, ADR 0001) | `Edit(P)` in `permissions.deny` |
| `allowWrite P` | **`Edit(P)` in `permissions.allow`** (new) |

Path spelling follows route-A syntax: absolute `P` → `Edit(//P)`, `~/…` unchanged, relative entries
unchanged (they anchor at the Claude launch cwd, as under srt).

## Priority is preserved

Folding keeps srt's order: an `Edit` allow becomes a sandbox write allow, an `Edit` deny a write
deny emitted **after** it, so deny wins. Claude's tool check evaluates deny before allow. Example
with `allowWrite .` and `denyWrite ./xxx/x.md`:

```
permissions.allow: Edit(.)            permissions.deny: Edit(./xxx/x.md)
        │ fold                                │ fold
        ▼                                     ▼
(allow file-write* (subpath "<cwd>"))  (deny file-write* (subpath "<cwd>/xxx/x.md"))   ← later rule wins
Bash write to xxx/x.md:  blocked (srt source)       Edit tool on xxx/x.md: blocked (deny before allow; Claude docs)
```

The translation therefore cannot weaken any deny, implied or explicit.

## Trade-off accepted: auto-approval

An `Edit(P)` **allow** rule has a second effect that a deny rule does not have: Claude's
Edit/Write/NotebookEdit tools **no longer prompt** for files under P.

| Rule | Sandbox effect | Tool effect |
|---|---|---|
| `Edit(P)` deny | write deny | tools blocked — both effects restrict |
| `Edit(P)` allow | write grant | **tools auto-approved** — a second, unrelated relaxation |

| Mode | Consequence |
|---|---|
| yolo (prompts skipped anyway) | none beyond the sandbox grant |
| full (interactive approval) | edits under every `allowWrite` path — including `.`, i.e. the whole project — are no longer confirmed. If `[sandbox_overrides.full]` disables the sandbox, the auto-approval is the **only** effect of the rule in full mode |

Accepted because identical anchoring between srt and Claude and the removal of the `~/.claude`
widening outweigh the lost prompt. Denies still win in both gates.

## Alternatives considered

| Alternative | Why not chosen |
|---|---|
| Keep `allowWrite` on route B | Relative entries anchor at the settings-file root: the `~/.claude` widening and the srt/Claude divergence stay |
| Route B for absolute/`~`, drop relative entries with a warning | No prompt loss, and Claude grants its cwd itself; but `.git` handling would depend on Claude's own `.git` logic (not traced), and the rule set would no longer be translated uniformly |
| Emit both routes | Duplicates every path (ARG_MAX history) and keeps the anchoring defect |
| `Edit` allow only in yolo mode, route B / nothing in full mode | Avoids the prompt loss in full mode; adds mode-dependent translation. **Candidate follow-up** if the auto-approval proves unwelcome |
| Expand relative entries to absolute paths at generate time | Impossible: the launch cwd is unknown when twsrt generates |

## Consequences

**Positive**

- Relative entries anchor identically under srt and Claude.
- No more grants on `~/.claude` / `~/.claude/.git`; ADR 0006 rule 4 holds again.
- One uniform translation for all filesystem rules; `sandbox.filesystem` stays empty.

**Negative / open**

- Prompt loss for edits under `allowWrite` paths (see trade-off).
- `selective_merge` must own the generated `Edit(...)` allow entries (today it replaces only
  `WebFetch(domain:…)` allows); user-added `Edit` allows must survive regeneration.
- Unverified: whether gate 1 treats `Edit(.)` as covering files below `.` (may need `Edit(./**)`);
  in the sandbox `.` is recursive either way.
- Spike 2026-10-03 (Claude 2.1.288, `Vm()`): `Edit` allow folding is skipped only when the env var
  `CLAUDE_CODE_EVAL_CONFINED` is set (`h ? [] : FE(…)`). Grants are additionally dropped for
  untrusted tiers (`projectSettings`, `localSettings`) when they lie under a read-denied path;
  twsrt writes `userSettings` / `flagSettings`, so its grants fold normally.
- Claude-side enforcement is still unmeasured; probe parity (ADR 0005, open) would compare srt and
  Claude verdicts rule by rule.

## Verification plan

1. Unit tests (TDD): `allowWrite` → `Edit(//abs)`, `Edit(~/x)`, `Edit(.)` allows;
   `sandbox.filesystem.allowWrite == []`; `selective_merge` replaces generated and keeps user `Edit`
   allows; deny still emitted for overlapping paths.
2. Live: a new session's sandbox config no longer lists `~/.claude` or `~/.claude/.git` under
   `allowOnly`, while project writes still work.
3. Example above: Bash write and Edit tool on a denied file inside an allowed directory are both
   refused.
