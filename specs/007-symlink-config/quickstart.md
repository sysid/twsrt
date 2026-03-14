# Quickstart: Symlink-Based Config Management

## Scenario 1: First-time user

```bash
twsrt init                          # Creates config.toml with settings.full.json default
twsrt generate claude -w            # Writes settings.full.json, symlinks settings.json → settings.full.json
ls -la ~/.claude/settings.json      # settings.json -> settings.full.json
```

## Scenario 2: Existing user (has regular settings.json)

```bash
twsrt generate claude -w
# Output:
#   Migrated: /Users/tom/.claude/settings.json → /Users/tom/.claude/settings.full.json
#   Wrote: /Users/tom/.claude/settings.full.json
ls -la ~/.claude/settings.json      # settings.json -> settings.full.json
```

## Scenario 3: Switching between full and yolo

```bash
twsrt generate claude -w            # settings.json → settings.full.json
twsrt generate --yolo claude -w     # settings.json → settings.yolo.json (re-pointed)
twsrt generate claude -w            # settings.json → settings.full.json (re-pointed back)
```

## Scenario 4: Conflict (both files exist)

```bash
# User manually created settings.full.json, settings.json is still a regular file
twsrt generate claude -w
# Error: Both /Users/tom/.claude/settings.json (regular file) and
#        /Users/tom/.claude/settings.full.json exist.
#        Remove one before running generate -w.
# Exit code: 1
```

## Scenario 5: Diff follows symlinks

```bash
twsrt generate --yolo claude -w     # settings.json → settings.yolo.json
twsrt diff claude                   # Reads settings.json (follows symlink to yolo)
twsrt diff --yolo claude            # Reads settings.yolo.json directly
```
