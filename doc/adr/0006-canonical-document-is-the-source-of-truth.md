# ADR 0006: The canonical document is the single source of truth

- **Status:** Accepted (records an existing invariant)
- **Date:** 2026-10-03
- **Deciders:** Tom
- **Implementation:** `src/twsrt/bin/cli.py` `_compile`, `generate`; `src/twsrt/lib/sources.py`
  `compile_sources`; generators in `src/twsrt/lib/{claude,codex,copilot}.py`
- **Related:** README → "1. One policy, compiled in two stages"; `SECURITY_CONCEPT.md` §3.2;
  `doc/REFERENCE.md` → "Invariants"

## Context

The same security policy must reach agents with very different enforcement models:

| Target | Native model |
|---|---|
| srt (srt CLI, Copilot, pi) | `~/.srt-settings.json`: deny/allow paths, domains |
| Claude Code | permission rules + `sandbox.*` in `settings.json`, own path semantics |
| Codex | permission profile + Starlark `.rules`, escalation-only |
| Copilot | CLI flags |

If each target were authored or edited independently, they would drift apart, and nobody could say
which file states the actual policy. Translations are also **lossy**: no target can express
everything the others can.

## Decision

One compiled **canonical document** per source kind (`srt`, `bash`) is the source of truth.
Every agent configuration is a **translation** of it.

```
fragments ──(profile)──► compile ──► canonical documents (in memory)
                                     ├── srt  ──► ~/.srt-settings.json      (also read by srt itself)
                                     └── bash ──► bash-rules.json
                                              │
                                              ▼ translate (agent argument picks which)
                          Claude settings · Codex config + rules · Copilot flags
```

Rules that follow from it:

1. **Fragments are the only hand-edited policy input.** twsrt never writes them.
2. **Canonical files are rewritten on every `generate -w`**, whichever agent is named, so all
   targets always correspond to one compiled policy. Hand edits there are overwritten; `twsrt diff`
   reports them as drift.
3. **Agent configs are translated from the in-memory compile**, not from files on disk, so a stale
   or tampered canonical file cannot leak into a target.
4. **Translations narrow, never widen.** Where a target cannot express a rule exactly, the generator
   emits the stricter form or skips it **with a warning** — it never silently drops a deny or
   invents an allow.
5. **Only declared sections of a target are managed** (selective merge); hooks, plugins and other
   user settings are preserved.
6. **Compile-time rules apply to every target at once** (e.g. ADR 0001's implied `denyWrite`, the
   `.twsrt` deny of ADR 0004), because they are added to the canonical document before translation.

## Alternatives considered

| Alternative | Why rejected |
|---|---|
| One hand-maintained config per agent | Drift; no single answer to "what is the policy?"; every change made N times |
| Agent configs as source, srt derived from them | Agent models are lossy in different directions; no lossless common source |
| Translate from the canonical files on disk | A hand edit or stale file would propagate silently into every target |
| Write only the canonical file of the named agent | Targets could correspond to different compiles; `generate copilot -w` rewriting `~/.srt-settings.json` is the intended price |

## Consequences

**Positive**

- One place to review the policy (`twsrt show`), one place to test it (`twsrt test` probes the
  canonical srt document), one place to detect drift (`twsrt diff`).
- Cross-cutting safety rules (ADR 0001, 0004) are implemented once.

**Negative**

- `generate <any agent> -w` rewrites `~/.srt-settings.json`; users must know this (README).
- Equivalence between targets is only as good as each translation; target-specific semantics
  (e.g. Claude's relative-path anchoring, bkmr 3742) can make a faithful-looking translation behave
  differently. That gap is what probe parity (open, ADR 0002/0005) is meant to measure.
- One profile is in force globally at a time; per-project policy needed a separate output location
  (ADR 0004).

**Known violation of rule 4 (open, 2026-10-03):** relative `allowWrite` entries (`.`, `.git`) are
passed verbatim into Claude's `sandbox.filesystem.allowWrite`. Claude anchors those at the
settings-file root, so in `~/.claude/settings.json` they grant `~/.claude` and `~/.claude/.git`
instead of the project — a **widening**, and a divergence from srt, where they mean the launch
directory. Observed in a live session's sandbox config (`allowOnly` contained
`/Users/Q187392/.claude` and `/Users/Q187392/.claude/.git`). Fix pending; see ADR 0002.
