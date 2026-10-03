# ADR 0001: `denyRead` implies `denyWrite`

- **Status:** Accepted
- **Date:** 2026-10-03
- **Deciders:** Tom
- **Implementation:** `src/twsrt/lib/sources.py` `_imply_write_denies`
- **Related:** `SECURITY_CONCEPT.md` → "`denyRead` is not a write deny"; bkmr memories 3741, 3671

## Context

### The assumption that turned out false

The policy author's mental model was: *"a path I hide from the agent is also a path the agent cannot
change."* srt does not implement it that way. A `denyRead` entry compiles to a read deny plus
move-blocking, **never** a write deny (srt 0.0.78, `macos-sandbox-utils.js` `generateReadRules`;
`sandbox-manager.js` `getFsWriteConfig` builds the write-deny list from `denyWrite` only).

```
denyRead P  ──srt──►  (deny file-read* P)                         read blocked
                      (deny file-write-unlink file-write-create P) move blocked …
                      (allow file-write-unlink file-write-create <write root>)  … re-opened inside write roots
                      (deny file-write-unlink P)                   delete blocked again, CREATE stays open
                      ── no (deny file-write* P) ──                OVERWRITE NOT BLOCKED
```

Confirmed at runtime by Tom on 2026-10-03 with `srt -s`: a read-denied file inside an `allowWrite`
root was overwritten.

### What protected credentials until now: the write allowlist

srt's write model is default-deny:

```
(deny default)                          ← everything not allowed below is denied
(allow file-write* <allowOnly>)         ← srt's own paths + allowWrite
(deny  file-write* <denyWithinAllow>)   ← denyWrite only
```

`~/.ssh`, `~/.aws/credentials`, `~/.kube` were unwritable **only because no `allowWrite` entry
covers them**, not because of their `denyRead` entries. Whether a read-denied path is writable is
therefore decided by an unrelated list:

```
                    ┌──────────────────── allowWrite root (e.g. "." or "~/dev") ───────────────┐
                    │                                                                          │
  ~/.ssh            │   ./.env  (denyRead)       ./.twsrt/ (denyRead)      src/  (no rule)     │
  (denyRead)        │   read ✗  write ✓          read ✗  write ✓          read ✓  write ✓     │
  read ✗ write ✗    │                                                                          │
  (allowlist)       └──────────────────────────────────────────────────────────────────────────┘
```

An integrity attack on a read-denied file is usually *worse* than reading it: replace
`authorized_keys`, plant a `.git/hooks` script, overwrite `.env` with attacker values, or rewrite
`.twsrt/claude-settings.json` (which Claude hot-reloads) to loosen the agent's own policy.

### This was not hypothetical

`twsrt doctor` on the real configuration reported two such holes:

```
srt/base.jsonc:     filesystem.denyRead '**/.twsrt/**' (under '.')
srt/personal.jsonc: filesystem.denyRead '~/xxx/xxx'    (under '~/xxx')
```

## Decision

1. **The compiler adds every `denyRead` path to `denyWrite`.** `_imply_write_denies` runs inside
   `compile_sources`, after fragment composition and before rules are derived, so the implied
   entries are part of the canonical document every target is translated from.
2. **A path listed in both `denyRead` and `allowWrite` is a compile error.** It asks for write-only
   access, which contradicts the implication.

```
fragments ──compose──► srt document ──_imply_write_denies──► canonical document ──► every target
                       denyRead:  [P]                        denyRead:  [P]
                                                             denyWrite: [P, …]
```

| Target | Effect of the implied entry |
|---|---|
| srt (`srt -s`, Copilot, pi) | `(deny file-write* P)`; beats any `allowWrite` covering P |
| Claude Code | `Edit(P)` deny, already emitted for `denyRead`; the duplicate is removed. Claude folds `Edit` denies into its sandbox write rules |
| Codex | filesystem `deny`; outranks `read` |

## Alternatives considered

### A. Only reject exact `denyRead` = `allowWrite` and rely on the allowlist (rejected)

The tempting minimal fix: forbid the obvious contradiction, trust the default-deny write model for
everything else. It misses the case that actually occurs, because the danger is **coverage**, not
equality:

| Config | Exact-match check | Default allowlist | Without implied `denyWrite` |
|---|---|---|---|
| `denyRead ~/x` + `allowWrite ~/x` | error ✓ | — | — |
| `denyRead ~/xxx/xxx` + `allowWrite ~/xxx` | **passes** | covered by `~/xxx` → writable | **hole** (real config) |
| `denyRead **/.twsrt/**` + `allowWrite .` | **passes** | covered by `.` → writable | **hole** (real config) |
| `denyRead **/.env` + `allowWrite .` | **passes** | covered → writable | **hole**, in every project |

Both holes found in the real configuration belong to the rows this alternative lets through.

### B. Reject every `denyRead` that lies *under* an `allowWrite` root (rejected)

This would make the allowlist alone sufficient. It fails for three reasons:

1. **It bans normal policies.** Secrets inside a writable project (`.env`, `.twsrt`, `*.pem` below
   `.`) are the common case. The author would have to give up either the write root or the
   protection.
2. **"Under" is undecidable at compile time.**
   - Relative entries anchor at the **launch cwd**, known only at runtime.
   - Glob-versus-glob coverage (`**/.env` vs `~/dev`) cannot be decided reliably.
   - Symlinks: srt keeps unresolved paths while Seatbelt matches real paths (bkmr 3686).
3. **twsrt does not see the effective allowlist.** srt adds its own write paths (`/tmp/claude`,
   `~/.npm/_logs`, …); Claude Code adds its working directories, `~/.claude`, `/tmp/claude`.
   A read-denied path under one of those is writable although no fragment write-allows it.

```
what twsrt can see at compile time        what is writable at runtime
──────────────────────────────────        ──────────────────────────────────────────────
allowWrite from fragments           ⊂     allowWrite (relative entries resolved at launch cwd)
                                          + srt's own write paths
                                          + Claude Code's own write paths
                                          + symlink targets as the kernel resolves them
```

A check that cannot see the whole right-hand side cannot prove a path unwritable. An explicit
`(deny file-write* P)` does not need to: it wins regardless of which allow covers P.

### C. Require the author to write `denyWrite` by hand, enforced by `doctor` (rejected)

`doctor` would report missing write denies (it briefly did, as `read-deny-writable`). Protection
would then depend on running `doctor` and on the author fixing each finding — the manual discipline
that produced the two holes above. It is also blind to the runtime-only write roots listed under B.

### D. Allow write-only paths via an escape hatch (deferred)

Append-only logs or drop boxes are the one legitimate write-without-read case. None exists in the
current policy. Per YAGNI there is no escape hatch until a real case appears; until then the
contradiction is a loud compile error rather than a silent hole.

## Consequences

**Positive**

- A read-denied path cannot be overwritten or created, whatever `allowWrite` says — today or after
  a later broad `allowWrite` (`~`, `~/.config`, `~/dev`) is added.
- The guarantee no longer depends on the write allowlist, on the launch cwd, or on write roots twsrt
  cannot see.
- Explicit where it matters: the implied entries are visible in the compiled document
  (`twsrt show`), and `twsrt test` derives a **write probe** for each `denyRead` path, so a failing
  enforcement shows up as `FAIL`.

**Negative / limits**

| Limit | Impact |
|---|---|
| Implicit in the fragments | The rule must be known; documented here, in `SECURITY_CONCEPT.md` and `doc/REFERENCE.md` |
| Profile size | ~144 B per path (bkmr 3671); negligible at ~6 % of ARG_MAX |
| Linux | srt drops every write glob, including `denyWrite`; glob entries (`**/.env`) get no write protection there — same as before, macOS unaffected |
| Symlinked paths | The implied write deny inherits the read deny's symlink no-op; the real path must be listed |
| Exact-string conflict check | `denyRead ~/logs` + `allowWrite /Users/me/logs` is not flagged; still safe, because the implied write deny wins over the allow |
| Write-only use case | Not expressible (see D) |

**Unchanged**

- Paths named in no rule are protected by the write allowlist only. That is the allowlist's job.
- `doctor` no longer reports `read-deny-writable`; the condition cannot occur.

## Verification

| Layer | Evidence |
|---|---|
| Unit tests | `tests/lib/test_compilation.py::test_every_read_deny_is_also_compiled_as_a_write_deny`, `::test_read_deny_on_a_write_allowed_path_is_a_conflict`; `tests/lib/test_claude.py::test_read_and_write_deny_on_one_path_emit_each_rule_once`; `tests/lib/test_doctor.py::test_write_only_path_surfaces_as_a_compile_error` |
| Runtime (srt) | `twsrt test`: one `write-deny` probe per `denyRead` path; expect `PASS` |
| Runtime (Claude) | not probed by `twsrt test`; covered once probe parity (`test --direct` / `--compare`) exists |
