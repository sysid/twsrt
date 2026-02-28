# Research: Extend Claude Network Settings Generation

**Feature**: 004-claude-network-keys
**Date**: 2026-02-28

## Decision 1: How to carry pass-through network config from parser to generator

**Decision**: Introduce `SrtResult` dataclass; add `network_config` field to `AppConfig`.

**Rationale**: The 5 new keys (`allowUnixSockets`, `allowAllUnixSockets`, `allowLocalBinding`, `httpProxyPort`, `socksProxyPort`) are scalar/list values that don't fit the `SecurityRule(scope, action, pattern, source)` model. They need a separate channel from parser to generator.

**Alternatives considered**:

| Alternative | Why rejected |
|-------------|-------------|
| Bare tuple return from `read_srt()` | Less readable than named dataclass; tuple unpacking is fragile |
| Separate `read_srt_network_config()` function | Reads and parses the same file twice; fragile if file changes between reads |
| New SecurityRule scope/action for config values | Violates the domain model — these aren't ALLOW/DENY rules with patterns |
| Store on generator instance | Couples parsing to generation; breaks the clean data flow |

## Decision 2: Selective merge strategy for sandbox.network

**Decision**: Change from full dict replacement to `dict.update()` (key-by-key merge).

**Rationale**: Full replacement (`existing["sandbox"]["network"] = generated[...]`) wipes `allowManagedDomainsOnly` which is a Claude Code managed-settings-only key with no SRT source. Key-by-key merge preserves unmanaged keys while correctly setting all managed ones.

**Alternatives considered**:

| Alternative | Why rejected |
|-------------|-------------|
| Maintain a MANAGED_KEYS set and explicitly copy only those | Over-engineering for current needs; `update()` achieves the same result since the generated dict only contains managed keys by construction |
| Add `allowManagedDomainsOnly` to generated output | Violates FR-005; this key has no SRT source and must not be touched |
| Keep full replacement and document the limitation | Would break existing Claude Code configurations that use `allowManagedDomainsOnly` |

## Decision 3: diff() signature change

**Decision**: Add `config: AppConfig` parameter to `AgentGenerator.diff()` Protocol method.

**Rationale**: `diff()` internally calls `self.generate(rules, config)` to produce the expected output. It currently creates `config = AppConfig()` with defaults, which means the generated output lacks `network_config`. To compare network pass-through keys, `diff()` needs the real config with populated `network_config`. Passing config from the CLI is cleaner than having `diff()` re-read the SRT file.

**Alternatives considered**:

| Alternative | Why rejected |
|-------------|-------------|
| Have `diff()` re-read the SRT file itself | Duplicates file reading; requires passing the SRT path separately |
| Make `network_config` a module-level global | Global state is fragile and untestable |
| Keep internal `AppConfig()` default | Would miss all network config keys in drift detection |

## Decision 4: Nested SRT format removal scope

**Decision**: Remove the nested format branch (`sources.py:32-40`) and convert ALL test fixtures to flat format.

**Rationale**: Per clarification with Tom: there is only one SRT format (the flat format). The nested branch reads from `sandbox.permissions.network` with different key names (`allowedHosts`/`deniedHosts`), which is neither the official SRT format nor the Claude Code format. It's legacy dead code that caused confusion during spec drafting.

**Impact**:
- `SAMPLE_SRT` in conftest.py (used by 5+ tests) must be converted to flat
- `SAMPLE_CLAUDE_SETTINGS` in conftest.py has `allowedHosts` → needs `allowedDomains`
- ~8 tests in test_cli.py use inline nested format → convert to flat
- 3 tests in test_sources.py use inline nested format → convert to flat
