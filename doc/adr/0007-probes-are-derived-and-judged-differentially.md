# ADR 0007: Sandbox probes are derived from the settings and judged differentially

- **Status:** Accepted (records the existing `twsrt test` design, extended 2026-10-03,
  amended 2026-10-09: proxy-witnessed wildcard domains)
- **Date:** 2026-10-03
- **Deciders:** Tom
- **Implementation:** `src/twsrt/lib/probe.py` (`derive_probes`, `run_probe`, `judge`);
  `src/twsrt/bin/cli.py` `test_command`
- **Related:** `doc/REFERENCE.md` → "Sandbox probes"; ADR 0006 (the canonical document is what gets
  probed); bkmr 3686 (symlinked denies), 3743 (absolute and root-anchored deny globs)

## Context

`twsrt diff` proves `~/.srt-settings.json` matches the fragments. It cannot prove the kernel
enforces that file: srt's path semantics hold surprises that a correct-looking file hides —
symlinked denies that match nothing, deny globs anchored at the launch directory, allow globs that
grant one directory level, write globs dropped on Linux. Only running a command inside the sandbox
answers "is this rule enforced?". A naive "run it under srt and expect a failure" is not enough
either: a missing file or an unreachable host also fails, and would read as "blocked".

## Decision

`twsrt test` turns every effective rule into a probe at run time and judges it by comparing two
runs of the same command.

1. **Derived, not catalogued.** Probes come from the compiled settings file on disk, so the test set
   follows the policy without maintenance. A rule with no concrete probe is reported as `SKIP` with
   a reason, never dropped silently.
2. **Differential verdict.** Each command runs once plainly (control) and once under
   `srt -s <settings> -c`. A deny passes only if the control succeeds and the sandbox fails; a
   failing control makes the probe `INVALID`, except when the OS itself refused it (root-owned
   path), which already meets the deny intent.
3. **Probes must not be able to damage anything.** Writes are append-opens that write nothing
   (`: >> path`); reads take one byte with stdout discarded; a file a probe creates is removed after
   each run, and a pre-existing file is never removed.
4. **A deny is witnessed where it is the only reason to fail.** Glob witnesses and directory probes
   live inside an `allowWrite` root (for an absolute or `~` glob: below its prefix), so a block
   cannot come from the allowlist instead. Without such a place the probe is skipped.
5. **One assertion is not derived from the settings**: the allowlist canary, a host that is not
   allowlisted and must be blocked, proves allowlist mode is on at all.
6. **Scope is the srt wrapper.** Claude Code's native sandbox and Codex are not probed.
7. **Wildcard domains are witnessed by the proxy, not differentially** (amendment 2026-10-09).
   `*.x` has no concrete host, but srt's proxy filters on the hostname before any DNS lookup
   (sandbox-runtime 0.0.79, `http-proxy.js`). The probe dials the made-up `twsrt-probe.x` and
   reads the proxy's answer to the `CONNECT` (`curl -w '%{http_connect}'`): `403` is the policy
   denial, any other answer (`502` for the unresolvable host) means the filter admitted it, `000`
   is an `ERROR`. There is no control run: outside the sandbox the host does not resolve, so a
   control would only ever be `INVALID`. Exit codes are ignored, because curl fails for both 403
   and 502 and a broken sandbox must not read as a block. Verified manually by Tom on 2026-10-09
   (`403` for a denied, `502` for an allowed wildcard).

## Alternatives considered

| Alternative | Why rejected |
|---|---|
| Hand-written test catalogue per rule | Drifts from the policy; every fragment edit needs a test edit |
| Sandbox run only, no control | A missing file or an unreachable host reads as "blocked" |
| Statically check the generated Seatbelt profile | Proves the profile text, not the kernel; misses realpath and anchoring effects |
| `touch`, `>` or real content as write probe | `touch` bumps mtime, `>` truncates; a wrong path could destroy data |
| Witness globs in any directory | Outside every write root the allowlist blocks the write, so the deny is never observed |
| Also drive Claude Code / Codex | Needs an agent run per probe; non-deterministic, slow, billed |
| Wildcards: probe a real subdomain (`www.x`, a configured host) | Not every base has one (`*.amazonaws.com`); a per-wildcard host list is maintenance |
| Wildcards: judge by curl's exit code | 403 and 502 both exit 56; a missing curl would pass every deny |

## Consequences

**Positive**

- A green run means every rule that exists is enforced by the kernel, including the cases where a
  plausible rule is a no-op (symlinks: the realpath twin row; globs: the witness).
- New probe shapes are local to `derive_probes`; verdict logic stays in `judge`.

**Negative**

- **Enforcement, not intent:** a missing rule produces no row.
- The control run executes every command with full user rights, and network probes really connect,
  `deniedDomains` included.
- Unconvertible shapes stay `SKIP`: `denyRead` globs, mid-path wildcards, single-segment globs,
  the bare `*` domain and mid-label domain wildcards.
- A wildcard probe proves srt's filter decision, not an end-to-end connection, and it relies on the
  proxy's `403` staying the denial signal. If srt changed it, every wildcard deny would `FAIL`
  (loud), but a blocked wildcard allow would read as `PASS`. It also proves one subdomain level; `*.x` matching deeper
  levels rests on srt's suffix match.
- A glob is witnessed at one location; that root-anchoring covers every writable tree rests on srt's
  regex semantics (bkmr 3743), not on a probe per root.
- **Cleanup gap:** cleanup runs after each run and on timeout, not on Ctrl-C or a crash. An
  interruption between the control run and its cleanup leaves `.twsrt-probe-<pid>` in the probed
  directory; `kill -9` can also leave `.twsrt-test-*` directories.
