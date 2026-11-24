# twsrt

<!-- MANUAL ADDITIONS START -->
Compiles one security policy (srt + bash-rules JSONC fragments, chosen by a profile) into
canonical documents, then into native agent configs: `claude`, `copilot`, `copilot-jetbrains`,
`codex`.

## Commands

- Test: `uv run pytest -m "not (integration or experimentation)"` (`make test` adds coverage)
- Lint/format/types: `ruff check .` · `ruff format src tests` · `uvx ty check src/twsrt`

## Map

`config.py` (config.toml) → `profiles.py`/`composition.py` (fragments) → `sources.py` (compile,
key allowlists) → `models.py` (`SecurityRule`, `AppConfig`) → generators registered in `agent.py`
(`claude.py`, `codex.py`, `copilot.py`, `copilot_jetbrains.py`; shared Copilot policy in
`copilot_sandbox.py`). `cli.py` stages, writes and diffs; `doctor.py`, `probe.py` verify.

## Invariants

- Lossy translation goes the fail-safe way (deny, not allow) and is warned.
- `compatibility_warnings` returns strings, never prints; the CLI deduplicates them.
- Generators own only their keys/options; everything else in a target is preserved.
- denyRead implies denyWrite (ADR 0001); composition only adds (ADR 0003).
- No modes (ADR 0010): the profile alone decides the output, `ask` is never dropped, prompt skipping
  is never generated, and Claude's sandbox posture is fixed (`_FIXED_POSTURE`).
- Nothing in `config.toml` is silently ignored: unknown and removed keys are load errors.
- Fragments are never written; compiled outputs are never hand-edited.

## Docs

Behaviour change → update `README.md` and `doc/REFERENCE.md`; a decision → `doc/adr/`; an
enforcement gap → `SECURITY_CONCEPT.md`. Tests cite FR ids from `thoughts/designs/`.

## Sandbox gotchas

- Tests cannot create sandbox-denied names (`.env`, `.ssh`, …): use neutral names in new tests.
  `test_probe.py::…::test_directory_rule_probes_first_regular_file_inside` fails in the sandbox
  only for this reason.
- `sed` here is GNU (`sed -i` takes no `''`).
<!-- MANUAL ADDITIONS END -->
