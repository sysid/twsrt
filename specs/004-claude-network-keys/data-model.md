# Data Model: Extend Claude Network Settings Generation

**Feature**: 004-claude-network-keys
**Date**: 2026-02-28

## New Entity: SrtResult

Return type for `read_srt()`, replacing the bare `list[SecurityRule]`.

| Field          | Type                    | Description                                              |
|----------------|-------------------------|----------------------------------------------------------|
| `rules`        | `list[SecurityRule]`    | ALLOW/DENY security rules (existing behavior)            |
| `network_config` | `dict[str, Any]`     | Pass-through network settings (new)                      |

### network_config keys

Only keys present in the SRT source are included. Absent keys are omitted (not set to defaults).

| Key                  | Type       | Example value                                   |
|----------------------|------------|-------------------------------------------------|
| `allowUnixSockets`   | list[str]  | `["/var/run/docker.sock", "~/.ssh/agent.sock"]` |
| `allowAllUnixSockets`| bool       | `true`                                          |
| `allowLocalBinding`  | bool       | `true`                                          |
| `httpProxyPort`      | int        | `8080`                                          |
| `socksProxyPort`     | int        | `1080`                                          |

## Modified Entity: AppConfig

Add `network_config` field to carry parsed network settings from CLI to generators.

| Field (existing)        | Type           | Change   |
|------------------------|----------------|----------|
| `srt_path`             | `Path`         | No change|
| `bash_rules_path`      | `Path`         | No change|
| `claude_settings_path` | `Path`         | No change|
| `copilot_output_path`  | `Path \| None` | No change|
| **`network_config`**   | **`dict`**     | **NEW** (default: `{}`) |

## Unchanged Entities

### SecurityRule

No changes. Pass-through network keys bypass the rule system.

| Field    | Type     | Change    |
|----------|----------|-----------|
| `scope`  | `Scope`  | No change |
| `action` | `Action` | No change |
| `pattern`| `str`    | No change |
| `source` | `Source` | No change |

### DiffResult

No changes. Drift entries for new network keys use the existing `missing`/`extra` lists with a `network.config:` prefix to distinguish them from domain entries (`network:` prefix).

| Field     | Type        | Change    |
|-----------|-------------|-----------|
| `agent`   | `str`       | No change |
| `missing` | `list[str]` | No change |
| `extra`   | `list[str]` | No change |
| `matched` | `bool`      | No change |

## Output Format Change: sandbox.network

### Before (only allowedDomains)

```json
{
  "sandbox": {
    "network": {
      "allowedDomains": ["github.com", "pypi.org"]
    }
  }
}
```

### After (all present keys)

```json
{
  "sandbox": {
    "network": {
      "allowedDomains": ["github.com", "pypi.org"],
      "allowUnixSockets": ["/var/run/docker.sock"],
      "allowAllUnixSockets": false,
      "allowLocalBinding": true,
      "httpProxyPort": 8080,
      "socksProxyPort": 1080
    }
  }
}
```

Keys absent from SRT source are omitted entirely (not set to `null` or defaults).
