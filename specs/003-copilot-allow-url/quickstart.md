# Quickstart: Network Domain Flags

**Feature**: 003-copilot-allow-url | **Date**: 2026-02-23

## Prerequisites

- Existing twsrt installation (see `specs/001-agent-security-config/quickstart.md`)
- SRT config with network domains (`~/.srt-settings.json`)

## Verify SRT Config Has Network Domains

```bash
# Check allowed domains
python3 -c "import json; d=json.load(open('~/.srt-settings.json'.replace('~','$HOME'))); print(d.get('network',{}).get('allowedDomains', []))"

# Check denied domains
python3 -c "import json; d=json.load(open('~/.srt-settings.json'.replace('~','$HOME'))); print(d.get('network',{}).get('deniedDomains', []))"
```

## Generate Copilot Config with Domain Flags

```bash
# Generate copilot flags (now includes --allow-url and --deny-url)
twsrt generate copilot
```

Example output:
```
--deny-tool 'shell(rm)'
--deny-tool 'shell(sudo)'
--allow-tool 'shell(*)'
--allow-tool 'read'
--allow-tool 'edit'
--allow-tool 'write'
--allow-url 'github.com'
--allow-url '*.github.com'
--allow-url 'pypi.org'
--deny-url 'evil.com'
```

## Generate Claude Config with Denied Domains

```bash
# Generate claude config (now includes denied domain entries)
twsrt generate claude
```

Denied domains appear as `WebFetch(domain:...)` in `permissions.deny`.

## Check for Drift

```bash
# Check both agents for domain drift
twsrt diff all
```

## Development Workflow

```bash
cd src && pytest         # Run all tests
cd src && ruff check .   # Lint
```

## Files Modified by This Feature

| File | Change |
|------|--------|
| `src/twsrt/lib/models.py` | Relax NETWORK validation to allow DENY |
| `src/twsrt/lib/sources.py` | Parse `deniedDomains` / `deniedHosts` |
| `src/twsrt/lib/copilot.py` | Generate `--allow-url` and `--deny-url` |
| `src/twsrt/lib/claude.py` | Generate `WebFetch(domain:...)` deny entries |
| `tests/conftest.py` | Add denied domains to sample data |
| `tests/lib/test_models.py` | Update NETWORK validation tests |
| `tests/lib/test_sources.py` | Add denied domain parsing tests |
| `tests/lib/test_copilot.py` | Add allow-url/deny-url generation tests |
| `tests/lib/test_claude.py` | Add denied domain deny entry tests |
