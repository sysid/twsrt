# Data Model: YOLO Mode

**Feature**: 006-yolo-mode | **Date**: 2026-03-14

## Modified Entities

### AppConfig (existing, modified)

Carrier for all configuration state passed to generators.

| Field                    | Type           | Default                          | Change    |
|--------------------------|----------------|----------------------------------|-----------|
| `srt_path`               | `Path`         | `~/.srt-settings.json`           | unchanged |
| `bash_rules_path`        | `Path`         | `~/.config/twsrt/bash-rules.json`| unchanged |
| `claude_settings_path`   | `Path`         | `~/.claude/settings.json`        | unchanged |
| `copilot_output_path`    | `Path \| None` | `None`                           | unchanged |
| `claude_yolo_path`       | `Path \| None` | `None`                           | **new**   |
| `copilot_yolo_path`      | `Path \| None` | `None`                           | **new**   |
| `network_config`         | `dict`         | `{}`                             | unchanged |
| `filesystem_config`      | `dict`         | `{}`                             | unchanged |
| `sandbox_config`         | `dict`         | `{}`                             | unchanged |
| `yolo`                   | `bool`         | `False`                          | **new**   |

- `claude_yolo_path`: Override for Claude yolo output. If `None`, derived as `yolo_path(claude_settings_path)`.
- `copilot_yolo_path`: Override for Copilot yolo output. If `None`, derived as `yolo_path(copilot_output_path)`.
- `yolo`: Flag indicating yolo mode is active. Set by CLI `--yolo` flag.

### SecurityRule (existing, unchanged)

No changes. The filtering of ASK rules happens at the generator level, not the data model.

## New Functions

### `yolo_path(original: Path) -> Path`

Derives a yolo variant path by inserting `.yolo` before the file extension.

| Input                    | Output                       |
|--------------------------|------------------------------|
| `~/.claude/settings.json`| `~/.claude/settings.yolo.json`|
| `copilot-flags.txt`      | `copilot-flags.yolo.txt`     |
| `config`                 | `config.yolo`                |

## Generator Behavior Changes

### ClaudeGenerator.generate() in YOLO mode

```
Standard mode:                    YOLO mode:
┌─────────────────────────┐       ┌─────────────────────────┐
│ permissions:            │       │ permissions:            │
│   deny: [DENY rules]   │       │   deny: [DENY rules]   │
│   ask:  [ASK rules]    │       │   (no ask key)          │
│   allow: [WebFetch...]  │       │   allow: [WebFetch...]  │
│ sandbox:                │       │ sandbox:                │
│   network: {...}        │       │   network: {...}        │
│   filesystem: {...}     │       │   filesystem: {...}     │
│   ...                   │       │   ...                   │
└─────────────────────────┘       └─────────────────────────┘
```

- `permissions.ask` key omitted entirely (not empty list — omitted)
- `permissions.deny` includes all DENY rules (bash-rules + SRT)
- `permissions.allow` includes WebFetch domain entries (unchanged)
- `sandbox` section identical to standard mode

### CopilotGenerator.generate() in YOLO mode

```
Standard mode:                    YOLO mode:
┌─────────────────────────┐       ┌─────────────────────────┐
│ --deny-tool 'shell(rm)' │       │ --yolo \                │
│ --deny-tool 'shell(dd)' │       │ --deny-tool 'shell(rm)' │
│ --deny-tool 'shell(git  │       │ --deny-tool 'shell(dd)' │
│   push)' (from ASK)     │       │ --deny-url 'evil.com'   │
│ --allow-tool 'shell(*)' │       │                         │
│ --allow-url 'github.com'│       │                         │
│ --deny-url 'evil.com'   │       │                         │
└─────────────────────────┘       └─────────────────────────┘
```

- `--yolo` as first flag
- ASK-derived `--deny-tool` entries omitted
- `--allow-tool` and `--allow-url` entries omitted (subsumed by `--yolo`)
- DENY-derived `--deny-tool` entries kept
- `--deny-url` entries kept (deny overrides allow)
