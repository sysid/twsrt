# Research: Agent Security Config Generator

**Feature**: 001-agent-security-config
**Date**: 2026-02-22

## R1: Python Version Target

**Decision**: Python >=3.11
**Rationale**: `tomllib` is in stdlib since 3.11, eliminating the need
for a `tomli` dependency. Python 3.10 reaches EOL October 2026 — no
reason to support it for a new project. Typer 0.24+ requires >=3.10
anyway.
**Alternatives considered**:
- Python >=3.12: Too restrictive — 3.11 is still widely deployed.
- Python >=3.10 with `tomli` fallback: Adds conditional dependency
  for a version reaching EOL in 8 months.

## R2: TOML Configuration Library

**Decision**: `tomllib` (stdlib, read-only)
**Rationale**: `~/.config/twsrt/config.toml` is read-only for the app.
`tomllib` provides everything needed with zero dependencies. It is
the stdlib version of `tomli` with identical API.
**Alternatives considered**:
- `tomlkit`: Preserves comments/formatting on write. Unnecessary
  since twsrt only reads TOML config, never writes it.
- `tomli-w`: Write-only companion to tomli. Not needed.
- `typer-config`: Adds decorator for config loading. Pulls in an
  extra dependency for ~10 lines of code we can write ourselves.

## R3: JSON Handling

**Decision**: stdlib `json` module
**Rationale**: Settings files are small (<50KB). Performance
difference between `json` and `orjson` is irrelevant at this scale.
No validation library needed — we validate with explicit checks in
`sources.py` and use dataclasses for structure.
**Alternatives considered**:
- `orjson`: 4-5x faster but Rust extension, adds build complexity.
  Overkill for small settings files.
- `pydantic`: Heavy (~15+ transitive deps). Dataclasses with manual
  validation are sufficient for our simple schema.

## R4: Type Checker

**Decision**: `ty` (Astral)
**Rationale**: Development-standards.md mandates `ty` for Python
projects ("MUST use `ty` for type checking (NOT mypy)"). Tom already
uses `ty` in rplc (Makefile: `uvx ty check $(pkg_src)`). Current
version 0.0.18 — still pre-stable but works well for common typing
patterns per Astral's own assessment.
**Alternatives considered**:
- `mypy`: Explicitly rejected by project standards.
- `pyright`: Not in Tom's standard toolchain.

## R5: Runtime Dependencies

**Decision**: Single dependency — `typer`
**Rationale**: `typer` (0.24+) brings `rich`, `click`, and
`shellingham` transitively. Combined with stdlib `json`, `tomllib`,
`pathlib`, and `dataclasses`, this covers all requirements:
- CLI framework: typer
- Pretty output: rich (via typer)
- JSON read/write: stdlib json
- TOML config read: stdlib tomllib
- Path handling: stdlib pathlib
- Data models: stdlib dataclasses

Total installed packages: ~7 (typer + its transitive deps).
**Alternatives considered**:
- Adding `pydantic` for config validation: YAGNI. Dataclasses
  with explicit checks are simpler and dependency-free.
- Adding `deepdiff` for drift detection: YAGNI. Simple dict
  comparison with stdlib is sufficient.

## R6: Project Infrastructure (Reference: rplc)

**Decision**: Follow rplc patterns exactly
**Rationale**: rplc is Tom's reference Python project. Direct
inspection confirms:
- `src/` layout with `bin/` + `lib/` sub-packages
- `__version__` defined in `bin/cli.py` (not `__init__.py`)
- Entry point: `package = "package.bin.cli:app"`
- Makefile uses `uv run` prefix for all commands
- `uvx ty check` for type checking
- `VERSION` file bumped by `bump-my-version`
- `pyproject.toml` with `[tool.uv] managed = true, package = true`
- `[dependency-groups] dev = [...]` for dev dependencies
- pytest with `python_files = "*.py"` (discover tests in any .py)
- `pytest-cov` with coverage config in pyproject.toml

**Key patterns to replicate**:
1. `bin/cli.py` — typer `@app.callback(invoke_without_command=True)`
   pattern with `-v`/`--verbose` and `-V`/`--version` global options
2. Hidden `version` subcommand: `@app.command("version", hidden=True)`
3. Bare invocation shows help
4. `if __name__ == "__main__": app()` for direct execution

## R7: SRT Settings File Format

**Decision**: Parse `~/.srt-settings.json` as flat JSON with known keys
**Rationale**: Direct inspection of `~/.srt-settings.json` reveals:
```json
{
  "filesystem": {
    "denyRead": ["~/.aws", "~/.ssh", ...],
    "allowWrite": [".", "/tmp/claude", ...],
    "denyWrite": ["**/.env", "**/*.pem", ...]
  },
  "network": {
    "allowedDomains": ["github.com", "*.github.com", ...]
  },
  "enabled": true,
  "allowPty": false,
  ...
}
```
Only `filesystem.*` and `network.allowedDomains` are security rules.
Other fields (`enabled`, `allowPty`, `ignoreViolations`) are SRT
runtime settings — twsrt ignores them per FR-015.

## R8: Claude Code settings.json Format

**Decision**: Operate on known sections, preserve everything else
**Rationale**: Direct inspection of `~/.claude/settings.json`:
- `permissions.deny`: array of strings like `Read(**/.aws/**)`
- `permissions.ask`: array of strings like `Bash(git push:*)`
- `permissions.allow`: mixed array — blanket tools, WebFetch domains,
  MCP tools, project-specific — selective merge (FR-018)
- `sandbox.network.allowedDomains`: array of domain strings
- Other keys: `hooks`, `additionalDirectories`, etc. — preserved

## R9: Config File Purpose (~/.config/twsrt/config.toml)

**Decision**: Application-level config for target file paths and
generation preferences
**Rationale**: The TOML config stores:
- Path to SRT settings file (default: `~/.srt-settings.json`)
- Path to bash-rules file (default: `~/.config/twsrt/bash-rules.json`)
- Path to Claude settings file (default: `~/.claude/settings.json`)
- Path to Copilot output file (optional, stdout by default)
- Agent-specific overrides if needed

This separates "where are things" from "what are the security rules".
Canonical sources hold the rules; `config.toml` tells twsrt where to
find them and where to write output.
