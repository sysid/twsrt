# Data Model: Network Domain Flags for Copilot and Claude

**Feature**: 003-copilot-allow-url | **Date**: 2026-02-23

## Entity Changes

### SecurityRule (modified)

No new fields. The only change is relaxing the validation constraint.

**Current validation** (line 37-38 of `models.py`):
```python
if self.scope == Scope.NETWORK and self.action != Action.ALLOW:
    raise ValueError("NETWORK scope requires ALLOW action")
```

**New validation**:
```python
if self.scope == Scope.NETWORK and self.action not in (Action.ALLOW, Action.DENY):
    raise ValueError("NETWORK scope requires ALLOW or DENY action")
```

This allows two valid NETWORK rule variants:

| Scope | Action | Source | Meaning |
|-------|--------|--------|---------|
| NETWORK | ALLOW | SRT_NETWORK | Whitelisted domain (existing) |
| NETWORK | DENY | SRT_NETWORK | Blocked domain (new) |

## SRT Parsing Changes

### Flat format additions

```json
{
  "network": {
    "allowedDomains": ["github.com"],
    "deniedDomains": ["evil.com"]
  }
}
```

New field read: `network.deniedDomains` → `SecurityRule(NETWORK, DENY, domain, SRT_NETWORK)`

### Nested format additions

```json
{
  "sandbox": {
    "permissions": {
      "network": {
        "allowedHosts": ["github.com"],
        "deniedHosts": ["evil.com"]
      }
    }
  }
}
```

New field read: `sandbox.permissions.network.deniedHosts` → `SecurityRule(NETWORK, DENY, domain, SRT_NETWORK)`

## Rule Mapping Updates

### SecurityRule → Copilot Flags

| Scope | Action | Copilot Flag | Status |
|-------|--------|-------------|--------|
| EXECUTE | DENY | `--deny-tool 'shell(pattern)'` | Existing |
| EXECUTE | ASK | `--deny-tool 'shell(pattern)'` + warning | Existing |
| WRITE | ALLOW | `--allow-tool` flags (deduplicated) | Existing |
| READ | DENY | *(none — SRT handles)* | Existing |
| WRITE | DENY | *(none — SRT handles)* | Existing |
| **NETWORK** | **ALLOW** | **`--allow-url '<domain>'`** | **New** |
| **NETWORK** | **DENY** | **`--deny-url '<domain>'`** | **New** |

### SecurityRule → Claude Entries

| Scope | Action | Claude Output | Status |
|-------|--------|--------------|--------|
| READ | DENY | `permissions.deny`: `Tool(pattern)` entries | Existing |
| WRITE | DENY | `permissions.deny`: write-tool entries | Existing |
| WRITE | ALLOW | *(none — SRT handles)* | Existing |
| NETWORK | ALLOW | `permissions.allow`: `WebFetch(domain:...)` + `sandbox.network.allowedDomains` | Existing |
| EXECUTE | DENY | `permissions.deny`: `Bash(cmd)` entries | Existing |
| EXECUTE | ASK | `permissions.ask`: `Bash(cmd)` entries | Existing |
| **NETWORK** | **DENY** | **`permissions.deny`: `WebFetch(domain:<domain>)`** | **New** |
