# CLI Contract: Symlink-Based Config Management

## Modified Commands

### `twsrt generate claude -w`

**Behavior change**: Writes to `claude_settings` target (default: `~/.claude/settings.full.json`), then symlinks `~/.claude/settings.json` → target.

| Scenario | Anchor state | Target state | Action | Exit | Stdout |
|----------|-------------|--------------|--------|------|--------|
| Fresh | not exists | not exists | write target, create symlink | 0 | `Wrote: <target>` |
| Fresh + target | not exists | exists | merge into target, create symlink | 0 | `Wrote: <target>` |
| Migration | regular file | not exists | move anchor→target, merge, symlink | 0 | `Migrated: <anchor> → <target>\nWrote: <target>` |
| Conflict | regular file | exists | error | 1 | stderr: `Error: both <anchor> and <target> exist...` |
| Update | symlink→target | exists | merge into target | 0 | `Wrote: <target>` |
| Switch | symlink→other | exists/not | write/merge target, re-point symlink | 0 | `Wrote: <target>` |

### `twsrt generate --yolo claude -w`

Same table as above, but target = yolo target path.

### `twsrt generate copilot -w`

**No change**. Direct write, no symlinks.

### `twsrt diff [--yolo] claude`

**No change to behavior**. Reads target file (follows symlinks transparently via `Path.read_text()`). `--yolo` reads yolo target directly.

### `twsrt init`

**Behavior change**: Default `config.toml` template updated.

**New template content**:
```toml
[sources]
srt = "~/.srt-settings.json"
bash_rules = "~/.config/twsrt/bash-rules.json"

[targets]
claude_settings = "~/.claude/settings.full.json"
# copilot_output = "~/.config/twsrt/copilot-flags.txt"

# YOLO targets (optional — auto-derived from above if omitted)
# claude_settings_yolo = "~/.claude/settings.yolo.json"
# copilot_output_yolo = "~/.config/twsrt/copilot-flags.yolo.txt"
```

## New Module: `src/twsrt/lib/symlink.py`

### `ensure_symlink(target: Path, anchor: Path) -> None`

Create or update symlink from anchor → target. Uses relative path if same directory, absolute otherwise. Atomic via temp symlink + `os.replace()`.

### `prepare_claude_target(anchor: Path, target: Path) -> None`

Handle migration logic before writing:
- If anchor is a symlink: no-op (already managed)
- If anchor is a regular file and target does not exist: move anchor → target
- If anchor is a regular file and target exists: raise error
- If anchor does not exist: no-op

Returns after preparation; caller proceeds with write + symlink.
