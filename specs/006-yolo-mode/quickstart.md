# Quickstart: YOLO Mode

**Feature**: 006-yolo-mode | **Date**: 2026-03-14

## What Changes

Add a `--yolo` flag to `twsrt generate` and `twsrt diff` that produces permissive agent configs — only deny rules, no ask rules.

## Files to Modify

| File | Change |
|------|--------|
| `src/twsrt/lib/models.py` | Add `yolo`, `claude_yolo_path`, `copilot_yolo_path` to `AppConfig`; add `yolo_path()` helper |
| `src/twsrt/lib/config.py` | Load optional yolo path overrides from config.toml |
| `src/twsrt/lib/claude.py` | Skip ASK rules when `config.yolo`; omit `permissions.ask` key |
| `src/twsrt/lib/copilot.py` | Prepend `--yolo` flag, skip ASK rules and `--allow-*` entries when `config.yolo` |
| `src/twsrt/bin/cli.py` | Add `--yolo` flag to `generate` and `diff`; route to yolo target paths |
| `tests/lib/test_models.py` | Test `yolo_path()`, new AppConfig fields |
| `tests/lib/test_claude.py` | Test yolo mode output (no ask, keep allow) |
| `tests/lib/test_copilot.py` | Test yolo mode output (`--yolo` flag, no `--allow-*`, no ask-derived deny) |
| `tests/lib/test_config.py` | Test yolo path loading from config.toml |
| `tests/lib/test_diff.py` | Test diff with yolo target paths |
| `tests/bin/test_cli.py` | Integration tests for `--yolo` flag on generate and diff |

## Implementation Order

1. `models.py` — data model changes + `yolo_path()` helper
2. `config.py` — load yolo config keys
3. `claude.py` — yolo generation logic
4. `copilot.py` — yolo generation logic
5. `cli.py` — CLI flag wiring + yolo path routing
6. Tests at each step (TDD: test first, then implement)

## Key Design Decision

Each generator handles yolo mode internally via `config.yolo` flag rather than filtering rules at the CLI level. This is because:
- Claude needs to omit the `permissions.ask` key (structural change)
- Copilot needs to prepend `--yolo` and omit `--allow-*` entries (structural change)
- Simple rule filtering at CLI level can't express these agent-specific behaviors
