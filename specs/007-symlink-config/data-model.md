# Data Model: Symlink-Based Config Management

## Entities

### AppConfig (modified)

Existing dataclass in `src/twsrt/lib/models.py`. Changes:

| Field | Type | Default | Change |
|-------|------|---------|--------|
| `claude_settings_path` | `Path` | `~/.claude/settings.full.json` | **DEFAULT CHANGED** from `settings.json` |
| `symlink_anchor` | `Path` | `~/.claude/settings.json` | **NEW** — fixed path Claude Code reads |

All other fields unchanged.

### Symlink State Machine

The symlink anchor (`settings.json`) can be in one of these states:

```
                    ┌──────────────┐
                    │  NOT EXISTS  │
                    └──────┬───────┘
                           │ generate -w
                           │ (fresh write + symlink)
                           v
    ┌───────────────┐     ┌──────────────────┐
    │ REGULAR FILE  │────>│  SYMLINK → full  │
    │ (legacy)      │move │                  │
    └───────┬───────┘     └────────┬─────────┘
            │                      │ generate --yolo -w
            │ generate --yolo -w   │ (re-point)
            │ (move to yolo)       v
            │              ┌──────────────────┐
            └─────────────>│  SYMLINK → yolo  │
                           └──────────────────┘

    ERROR state: REGULAR FILE + target exists → refuse
```

### Config TOML Structure

```toml
[sources]
srt = "~/.srt-settings.json"
bash_rules = "~/.config/twsrt/bash-rules.json"

[targets]
claude_settings = "~/.claude/settings.full.json"
# copilot_output = "~/.config/twsrt/copilot-flags.txt"

# YOLO targets (optional — defaults to inserting .yolo before extension)
# claude_settings_yolo = "~/.claude/settings.yolo.json"
# copilot_output_yolo = "~/.config/twsrt/copilot-flags.yolo.txt"
```

## Validation Rules

1. `symlink_anchor` must be in the same directory as `claude_settings_path` for relative symlinks (checked at runtime, absolute fallback).
2. When `settings.json` is a regular file AND target exists → error, do not modify.
3. When `settings.json` is a regular file AND target does not exist → move, then symlink.
