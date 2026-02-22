# Quickstart: twsrt

**Feature**: 001-agent-security-config
**Date**: 2026-02-22

## Prerequisites

- Python >=3.11
- uv (for development)
- Existing SRT config at `~/.srt-settings.json`

## Install (Development)

```bash
git clone <repo-url> twsrt
cd twsrt
uv sync --dev
uv run pre-commit install
```

## Initialize Config Directory

```bash
uv run twsrt init
```

Creates:
```
~/.config/twsrt/
├── config.toml          # paths to sources and targets
└── bash-rules.json      # Bash deny/ask rules (edit this)
```

## Edit Bash Rules

Edit `~/.config/twsrt/bash-rules.json` with your Bash deny/ask rules:

```json
{
  "deny": ["rm", "sudo", "git push --force", "tskill"],
  "ask": ["git push", "git commit", "pip install", "cargo publish"]
}
```

## Generate Claude Code Config

Preview what would be generated:
```bash
uv run twsrt generate claude
```

Write directly to `~/.claude/settings.json`:
```bash
uv run twsrt generate claude --write
```

## Generate Copilot CLI Flags

```bash
uv run twsrt generate copilot
```

Output (copy into your `copilot-configured()` wrapper):
```
--deny-tool 'shell(rm)'
--deny-tool 'shell(sudo)'
--deny-tool 'shell(git push --force)'
--deny-tool 'shell(tskill)'
--deny-tool 'shell(git push)'
--deny-tool 'shell(git commit)'
--deny-tool 'shell(pip install)'
--deny-tool 'shell(cargo publish)'
--allow-tool 'shell(*)'
--allow-tool 'read'
--allow-tool 'edit'
--allow-tool 'write'
```

## Generate All Agents

```bash
uv run twsrt generate          # preview all
uv run twsrt generate --write  # write all targets
```

## Check for Drift

```bash
uv run twsrt diff
```

Reports discrepancies between canonical sources and existing configs.
Exit code 0 = no drift, exit code 1 = drift detected.

## Development Workflow

```bash
make test           # run tests
make lint           # ruff check
make format         # ruff format
make ty             # type check with ty
make help           # show all targets
```

## Key Files

| File | Role | Edited by |
|------|------|-----------|
| `~/.srt-settings.json` | Canonical: filesystem/network rules | Human (Tom) |
| `~/.config/twsrt/bash-rules.json` | Canonical: Bash deny/ask rules | Human (Tom) |
| `~/.config/twsrt/config.toml` | App config: paths to sources/targets | Human (Tom) |
| `~/.claude/settings.json` | Generated target: Claude Code permissions | twsrt only |
| Copilot flags snippet | Generated target: Copilot CLI flags | twsrt only |
