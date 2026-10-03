# ADR 0003: Composition only adds — no override, no subtraction

- **Status:** Accepted (records an existing invariant)
- **Date:** 2026-10-03
- **Deciders:** Tom
- **Implementation:** `src/twsrt/lib/composition.py` `_merge`; `src/twsrt/lib/sources.py`
  `_reject_cross_action_conflicts`; `src/twsrt/lib/profiles.py` `resolve_profile`
- **Related:** `SECURITY_CONCEPT.md` §3.2; `doc/REFERENCE.md` → "Compiler model"; ADR 0004 (per-project policy)

## Context

Policy is split into JSONC fragments that profiles combine. Every combination mechanism has to
answer one question: **what happens when two fragments say different things?** Common answers in
configuration systems are "last one wins", "child overrides parent", or explicit `remove:` lists.
Each of them lets a later or more specific piece of configuration **weaken** an earlier one without
anything looking wrong.

```
"last one wins"                         twsrt
───────────────                         ─────
base.jsonc   enabled: true              base.jsonc   enabled: true
work.jsonc   enabled: false             work.jsonc   enabled: false
     ⇒ sandbox OFF, silently                 ⇒ CompositionError: conflict at /enabled
                                               (names both fragments)
```

For a security policy, a silent weakening is the worst failure mode: the generated files look
valid, `diff` is clean, and the protection is gone.

## Decision

Composition is **monotone**: combining fragments can only add rules, never remove or weaken one.

| Element | Rule |
|---|---|
| Objects | merged recursively |
| Lists (paths, domains, commands) | **union**; rule lists are sorted so output does not depend on fragment order |
| Scalars (`enabled`, …) | must be **equal** in every fragment that sets them; a disagreement is a `CompositionError` naming both fragments |
| Opposing actions | the same value in `allowWrite` and `denyWrite`, `allowedDomains` and `deniedDomains`, or two Bash actions is an error |
| Profiles | `extends` selects *more* fragments; a child cannot change what a parent selected |
| `remove:` / negation | **does not exist** |

Dropping a rule for some context is done by **choosing a profile whose fragment list leaves the
rule's fragment out** — never by subtracting it:

```
[profiles.default]                    [profiles.slim]          # no cloud-creds
srt = ["base", "cloud-creds"]         srt = ["base"]
```

## Alternatives considered

| Alternative | Why rejected |
|---|---|
| Last fragment wins | A fragment added later (or ordered differently) silently flips a security scalar |
| Child profile overrides parent | Same, scoped to profiles; "work extends default" could switch the sandbox off |
| Explicit `remove:` list | Makes weakening a first-class operation; every reader must check all remove lists to know the effective policy; hard to audit |
| Priority numbers per fragment | Order-dependent semantics with extra indirection; same silent-weakening risk |

## Consequences

**Positive**

- The effective policy of a profile is the **union** of what its fragments say: readable by listing
  them (`twsrt profiles`, `twsrt edit -p X -n`).
- Adding a fragment can never make an existing profile less safe.
- Conflicts surface at compile time, before any file is written, with the fragments named.

**Negative**

- Rules that some context must drop have to live in their **own fragment**. Fragment granularity is
  a design task for the policy author.
- Scalars cannot be specialised per profile through fragments; per-mode differences use
  `[sandbox_overrides.full|yolo]`, which applies after compilation and only to the Claude target.
- The opposing-action check compares exact strings; `allowWrite ~/x` + `denyWrite ~/x/secret` is
  not a conflict (deny wins at runtime, which is the intended reading).

**Interaction with other decisions**

- ADR 0001 adds rules *during* compilation (`denyRead` ⇒ `denyWrite`); that is consistent with
  "only adds".
- ADR 0004 (per-project policy) drops rules per project by profile choice, never by subtraction.
