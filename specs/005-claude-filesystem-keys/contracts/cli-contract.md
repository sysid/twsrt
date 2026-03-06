# CLI Contract: Sandbox Output Changes

## `twsrt generate claude` — output contract

The `sandbox` section of the generated JSON is extended with:

### `sandbox.filesystem` (new section, conditional)

Present only if at least one filesystem key exists in SRT source.

```json
{
  "sandbox": {
    "filesystem": {
      "allowWrite": [".", "/tmp"],
      "denyWrite": ["**/.env", "**/*.pem"],
      "denyRead": ["~/.ssh", "~/.aws"]
    }
  }
}
```

Each key appears only if present in `.srt-settings.json`. Empty arrays are included.

### Top-level sandbox keys (new, conditional)

Present only if the corresponding key exists in SRT source.

```json
{
  "sandbox": {
    "enabled": true,
    "enableWeakerNetworkIsolation": true,
    "enableWeakerNestedSandbox": false,
    "ignoreViolations": {
      "*": ["/usr/bin", "/System"],
      "git push": ["/usr/bin/nc"]
    }
  }
}
```

### Complete generated sandbox example

```json
{
  "sandbox": {
    "network": {
      "allowedDomains": ["github.com"],
      "allowLocalBinding": true
    },
    "filesystem": {
      "allowWrite": [".", "/tmp"],
      "denyWrite": ["**/.env"],
      "denyRead": ["~/.ssh"]
    },
    "enabled": true,
    "enableWeakerNetworkIsolation": true,
    "enableWeakerNestedSandbox": false,
    "ignoreViolations": {
      "*": ["/usr/bin"]
    }
  }
}
```

## `twsrt diff claude` — drift report labels

New labels for drift entries:

| Label pattern | Example | Meaning |
|---------------|---------|---------|
| `filesystem.config:<key>` | `filesystem.config:allowWrite` | Filesystem key mismatch |
| `sandbox.config:<key>` | `sandbox.config:enabled` | Top-level sandbox key mismatch |

Existing labels unchanged:
- `network:<domain>` — domain mismatch
- `network.config:<key>` — network config key mismatch

## `twsrt generate claude --write` — merge contract

| Section | Strategy |
|---------|----------|
| `sandbox.network` | Key-by-key merge (existing) |
| `sandbox.filesystem` | Key-by-key merge (new) |
| `sandbox.enabled` | Overwrite if generated (new) |
| `sandbox.enableWeakerNetworkIsolation` | Overwrite if generated (new) |
| `sandbox.enableWeakerNestedSandbox` | Overwrite if generated (new) |
| `sandbox.ignoreViolations` | Overwrite if generated (new) |
| `sandbox.excludedCommands` | **Never touched** |
| `sandbox.autoAllowBashIfSandboxed` | **Never touched** |
| `sandbox.allowUnsandboxedCommands` | **Never touched** |
| `sandbox.network.allowManagedDomainsOnly` | **Never touched** |
