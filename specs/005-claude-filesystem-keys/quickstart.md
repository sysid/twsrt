# Quickstart: 005-claude-filesystem-keys

## Setup

```bash
cd /Users/Q187392/dev/s/private/twsrt
git checkout 005-claude-filesystem-keys
```

## Run tests

```bash
cd src && pytest
```

## Run linter

```bash
cd src && ruff check .
```

## Key files to modify

| File | Change |
|------|--------|
| `src/twsrt/lib/models.py` | Add `filesystem_config`, `sandbox_config` fields |
| `src/twsrt/lib/sources.py` | Add key tuples, extract new configs in `read_srt()` |
| `src/twsrt/lib/claude.py` | Extend `generate()`, `diff()`, `selective_merge()` |
| `src/twsrt/bin/cli.py` | Wire new config fields |
| `tests/conftest.py` | Update fixtures with sandbox keys |
| `tests/lib/test_sources.py` | Add filesystem/sandbox config tests |
| `tests/lib/test_claude.py` | Add generation/merge/preservation tests |
| `tests/lib/test_diff.py` | Add filesystem/sandbox drift tests |
| `README.md` | Add sandbox mapping table |

## Verify after changes

```bash
cd src && pytest && ruff check .
```
