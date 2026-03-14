# CLI Contract: YOLO Mode

**Feature**: 006-yolo-mode | **Date**: 2026-03-14

## Modified Commands

### `twsrt generate`

```
twsrt generate [OPTIONS] [AGENT]

Arguments:
  AGENT    Target agent: claude, copilot, or all  [default: all]

Options:
  --write, -w      Write to target files
  --dry-run, -n    Show what would be written (requires --write)
  --yolo           Generate permissive config (deny rules only, no ask rules)  [NEW]
```

**Behavior with `--yolo`**:

| Combination           | Effect                                                  |
|-----------------------|---------------------------------------------------------|
| `--yolo`              | Print yolo config to stdout                             |
| `--yolo -w`           | Write yolo config to yolo-specific target files         |
| `--yolo -w -n`        | Show what yolo config would be written (dry run)        |
| `--yolo claude`       | Generate yolo config for Claude only                    |
| `--yolo copilot`      | Generate yolo config for Copilot only                   |
| `--yolo all`          | Generate yolo config for all agents                     |

### `twsrt diff`

```
twsrt diff [OPTIONS] [AGENT]

Arguments:
  AGENT    Target agent: claude, copilot, or all  [default: all]

Options:
  --yolo           Diff against yolo-specific config files  [NEW]
```

**Exit codes** (unchanged): 0 = no drift, 1 = drift detected, 2 = missing file

## Output Contracts

### Claude YOLO Output (`settings.yolo.json`)

```json
{
  "permissions": {
    "deny": [
      "Bash(rm)",
      "Bash(rm *)",
      "Bash(sudo)",
      "Bash(sudo *)"
    ],
    "allow": [
      "WebFetch(domain:github.com)",
      "WebFetch(domain:anthropic.com)"
    ]
  },
  "sandbox": {
    "network": {
      "allowedDomains": ["github.com", "anthropic.com"]
    },
    "filesystem": {
      "denyRead": ["~/.ssh"],
      "denyWrite": ["~/.ssh"],
      "allowWrite": ["."]
    }
  }
}
```

Note: No `permissions.ask` key. The `allow` and `sandbox` sections are identical to standard mode.

### Copilot YOLO Output

```
--yolo \
--deny-tool 'shell(rm)' \
--deny-tool 'shell(sudo)' \
--deny-url 'evil.example.com'
```

Note: No `--allow-tool` or `--allow-url` entries (subsumed by `--yolo`). Only `--deny-*` entries follow.

## Config Contract (`config.toml`)

```toml
[sources]
srt = "~/.srt-settings.json"
bash_rules = "~/.config/twsrt/bash-rules.json"

[targets]
claude_settings = "~/.claude/settings.json"
# copilot_output = "~/.config/twsrt/copilot-flags.txt"

# Optional yolo path overrides (auto-derived if absent)
# claude_settings_yolo = "~/.claude/settings.yolo.json"
# copilot_output_yolo = "~/.config/twsrt/copilot-flags.yolo.txt"
```
