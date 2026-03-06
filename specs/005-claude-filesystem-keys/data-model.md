# Data Model: Pass-through All Remaining Sandbox Configuration Keys

## Model Changes

### `SrtResult` (models.py)

Current:
```
SrtResult
├── rules: list[SecurityRule]
└── network_config: dict[str, Any]
```

Proposed:
```
SrtResult
├── rules: list[SecurityRule]
├── network_config: dict[str, Any]       # (existing) → sandbox.network.*
├── filesystem_config: dict[str, Any]    # (new) → sandbox.filesystem.*
└── sandbox_config: dict[str, Any]       # (new) → sandbox.*
```

New fields:
- `filesystem_config` — keys: `allowWrite` (list[str]), `denyWrite` (list[str]), `denyRead` (list[str]). Only present keys included.
- `sandbox_config` — keys: `enabled` (bool), `enableWeakerNetworkIsolation` (bool), `enableWeakerNestedSandbox` (bool), `ignoreViolations` (dict[str, list[str]]). Only present keys included.

### `AppConfig` (models.py)

Current:
```
AppConfig
├── srt_path: Path
├── bash_rules_path: Path
├── claude_settings_path: Path
├── copilot_output_path: Path | None
└── network_config: dict[str, Any]
```

Proposed:
```
AppConfig
├── srt_path: Path
├── bash_rules_path: Path
├── claude_settings_path: Path
├── copilot_output_path: Path | None
├── network_config: dict[str, Any]       # (existing)
├── filesystem_config: dict[str, Any]    # (new)
└── sandbox_config: dict[str, Any]       # (new)
```

### Key Lists (sources.py)

Current:
```python
_NETWORK_CONFIG_KEYS = ("allowUnixSockets", "allowAllUnixSockets", ...)
```

Proposed — add:
```python
_FILESYSTEM_CONFIG_KEYS = ("allowWrite", "denyWrite", "denyRead")
_SANDBOX_CONFIG_KEYS = ("enabled", "enableWeakerNetworkIsolation", "enableWeakerNestedSandbox", "ignoreViolations")
```

## Output Structure Change

### Current generated `sandbox` section:
```json
{
  "sandbox": {
    "network": { "allowedDomains": [...], ...network_config_keys }
  }
}
```

### Proposed generated `sandbox` section:
```json
{
  "sandbox": {
    "network": { "allowedDomains": [...], ...network_config_keys },
    "filesystem": { ...filesystem_config_keys },
    "enabled": true,
    "enableWeakerNetworkIsolation": true,
    "enableWeakerNestedSandbox": false,
    "ignoreViolations": { "*": ["/usr/bin"], ... }
  }
}
```

Only keys present in SRT appear in output. Empty sections omitted.

## Drift Report Labels

| Key group | Report format | Example |
|-----------|--------------|---------|
| Network config | `network.config:<key>` | `network.config:httpProxyPort` |
| Filesystem config | `filesystem.config:<key>` | `filesystem.config:allowWrite` |
| Sandbox config | `sandbox.config:<key>` | `sandbox.config:enabled` |
