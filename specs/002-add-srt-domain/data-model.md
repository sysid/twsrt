# Data Model: Edit Canonical Sources

## No New Entities

This feature introduces no new data models. It reuses the existing
`AppConfig` dataclass to resolve source file paths:

| Source Name | AppConfig Field      | Default Path                        |
|-------------|----------------------|-------------------------------------|
| `srt`       | `srt_path`           | `~/.srt-settings.json`              |
| `bash`      | `bash_rules_path`    | `~/.config/twsrt/bash-rules.json`   |

## Mapping

```
SOURCE_PATHS = {
    "srt": config.srt_path,
    "bash": config.bash_rules_path,
}
```

No state transitions, no new persistence, no schema changes.
