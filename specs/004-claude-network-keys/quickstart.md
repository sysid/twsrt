# Quickstart: 004-claude-network-keys

## Setup

```bash
cd ~/dev/s/private/twsrt
git checkout 004-claude-network-keys
```

direnv handles the virtual environment automatically.

## Run tests

```bash
cd src && pytest
```

## Run linter

```bash
cd src && ruff check .
```

## Manual testing

```bash
# Generate Claude settings from example SRT file
cd src && python -m twsrt.bin.cli generate claude

# Generate with write
cd src && python -m twsrt.bin.cli generate claude --write

# Check drift
cd src && python -m twsrt.bin.cli diff claude
```

## Key files to modify

| File | What changes |
|------|-------------|
| `src/twsrt/lib/models.py` | Add `SrtResult`, add `network_config` to `AppConfig` |
| `src/twsrt/lib/sources.py` | Remove nested branch, extract network config |
| `src/twsrt/lib/claude.py` | Generate/diff/merge for new keys |
| `src/twsrt/lib/agent.py` | Update Protocol signature |
| `src/twsrt/lib/copilot.py` | Update diff() signature |
| `src/twsrt/bin/cli.py` | Wire network config through pipeline |
| `tests/conftest.py` | Convert fixtures to flat format |
