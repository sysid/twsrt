# CLI Contract: edit command

## Command Signature

```
twsrt edit [SOURCE]
```

## Arguments

| Argument | Type   | Required | Values         | Description                          |
|----------|--------|----------|----------------|--------------------------------------|
| SOURCE   | string | No       | `srt`, `bash`  | Canonical source to open for editing |

## Behavior

| Condition                        | Action                                                  | Exit Code |
|----------------------------------|---------------------------------------------------------|-----------|
| SOURCE provided, file exists     | Open file in editor, block until editor closes          | 0         |
| SOURCE provided, file missing    | Print error: "File not found: {path}"                   | 1         |
| SOURCE not provided              | Print available sources: `srt`, `bash`                  | 0         |
| SOURCE invalid                   | Print error: "Unknown source '{name}'. Available: ..."  | 1         |
| Editor exits with non-zero code  | Print warning: "Editor exited with code {N}"            | N         |

## Editor Resolution

Priority order:
1. `$EDITOR`
2. `$VISUAL`
3. `vi`

## Examples

```bash
$ twsrt edit srt
# Opens ~/.srt-settings.json in $EDITOR

$ twsrt edit bash
# Opens ~/.config/twsrt/bash-rules.json in $EDITOR

$ twsrt edit
Available sources: srt, bash

$ twsrt edit foo
Error: Unknown source 'foo'. Available: srt, bash
```
