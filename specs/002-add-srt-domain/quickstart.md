# Quickstart: Edit Canonical Sources

## Usage

```bash
# Edit the SRT settings file
twsrt edit srt

# Edit the bash rules file
twsrt edit bash

# Show available sources (no argument)
twsrt edit
```

## Editor Selection

The command uses the first available editor from:

1. `$EDITOR` environment variable
2. `$VISUAL` environment variable
3. `vi` (fallback)

Override for a single invocation:

```bash
EDITOR=nano twsrt edit srt
```

## Custom Config Path

If your config lives elsewhere, the `--config` flag is respected:

```bash
twsrt --config ~/my-config.toml edit srt
```
