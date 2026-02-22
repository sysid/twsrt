# CLI Contract: twsrt

**Feature**: 001-agent-security-config
**Date**: 2026-02-22

## Entry Point

```
twsrt = "twsrt.bin.cli:app"
```

Installed via `pip install twsrt` or `uv tool install twsrt`.

## Global Options

| Flag | Short | Type | Default | Description |
|------|-------|------|---------|-------------|
| `--verbose` | `-v` | bool | false | Enable DEBUG logging |
| `--version` | `-V` | bool | false | Print version and exit |
| `--config` | `-c` | Path | `~/.config/twsrt/config.toml` | Config file path |

Bare invocation (no subcommand, no flags) prints help.

## Commands

### `twsrt generate`

Generate agent-specific security config from canonical sources.

```
twsrt generate [OPTIONS] [AGENT]
```

| Argument | Type | Required | Default | Description |
|----------|------|----------|---------|-------------|
| `AGENT` | str | no | all | Target agent: `claude`, `copilot`, or `all` |

| Option | Short | Type | Default | Description |
|--------|-------|------|---------|-------------|
| `--write` | `-w` | bool | false | Write to target files instead of stdout |
| `--dry-run` | `-n` | bool | false | Show what would be generated without writing |

**Behavior**:
- Default: print generated config to stdout
- `--write`: write to target file paths from config.toml
- `--dry-run --write`: show target paths and what would be written
- If AGENT is omitted, generate for all configured agents

**Exit codes**:
- 0: success
- 1: canonical source file missing or invalid
- 2: target file write error

**Output format (stdout)**:
- Claude: JSON fragment (permissions + sandbox.network sections)
- Copilot: text block with one flag per line

**Warnings** (stderr):
- Lossy mapping: `⚠ Bash ask rule 'git push' mapped to --deny-tool for copilot (no ask equivalent)`

### `twsrt diff`

Compare generated config against existing agent config files.

```
twsrt diff [OPTIONS] [AGENT]
```

| Argument | Type | Required | Default | Description |
|----------|------|----------|---------|-------------|
| `AGENT` | str | no | all | Target agent: `claude`, `copilot`, or `all` |

**Behavior**:
- Generates config in memory, compares against existing target file
- Reports missing rules (in generated but not in existing)
- Reports extra rules (in existing but not in generated)
- No-drift: prints confirmation message

**Exit codes**:
- 0: no drift detected
- 1: drift detected (details printed to stdout)
- 2: canonical source or target file missing

**Output format**:
```
claude: 2 missing, 1 extra
  + Read(**/.kube/**) (missing from existing)
  + Write(**/.kube/**) (missing from existing)
  - Bash(docker run *) (in existing, not in sources)

copilot: no drift
```

### `twsrt init`

Initialize the `~/.config/twsrt/` config directory with default files.

```
twsrt init [OPTIONS]
```

| Option | Short | Type | Default | Description |
|--------|-------|------|---------|-------------|
| `--force` | `-f` | bool | false | Overwrite existing files |

**Behavior**:
- Creates `~/.config/twsrt/` directory
- Creates `~/.config/twsrt/config.toml` with default paths
- Creates `~/.config/twsrt/bash-rules.json` with empty deny/ask arrays
- If files exist and `--force` not set: skip with warning

**Exit codes**:
- 0: success (all files created or already exist)
- 1: error creating directory or files

### `twsrt version` (hidden)

Print version string. Hidden from help — accessible as `twsrt version`
or `twsrt -V`.

```
twsrt version: 0.1.0
```

## Config File Defaults

When `~/.config/twsrt/config.toml` does not exist, twsrt uses these defaults:

```toml
[sources]
srt = "~/.srt-settings.json"
bash_rules = "~/.config/twsrt/bash-rules.json"

[targets]
claude_settings = "~/.claude/settings.json"
```

## Error Messages

| Condition | Message | Exit |
|-----------|---------|------|
| SRT file missing | `Error: SRT settings not found: {path}` | 1 |
| Bash rules missing | `Error: Bash rules not found: {path}` | 1 |
| Invalid JSON in source | `Error: Invalid JSON in {path}: {detail}` | 1 |
| Config dir missing | `Error: Config directory ~/.config/twsrt/ not found. Run 'twsrt init' first.` | 1 |
| Target file write error | `Error: Cannot write to {path}: {detail}` | 2 |
