# CLI Contract Changes: Network Domain Flags

**Feature**: 003-copilot-allow-url | **Date**: 2026-02-23

No new commands or arguments are added. The changes are to the **output format** of existing commands.

## `twsrt generate copilot` — Output Changes

### New output lines (appended to existing flags)

For each domain in SRT `allowedDomains` / `allowedHosts`:
```
--allow-url '<domain>'
```

For each domain in SRT `deniedDomains` / `deniedHosts`:
```
--deny-url '<domain>'
```

### Example output (before)

```
--deny-tool 'shell(rm)'
--deny-tool 'shell(sudo)'
--allow-tool 'shell(*)'
--allow-tool 'read'
--allow-tool 'edit'
--allow-tool 'write'
```

### Example output (after)

```
--deny-tool 'shell(rm)'
--deny-tool 'shell(sudo)'
--allow-tool 'shell(*)'
--allow-tool 'read'
--allow-tool 'edit'
--allow-tool 'write'
--allow-url 'github.com'
--allow-url '*.github.com'
--allow-url 'pypi.org'
--allow-url 'registry.npmjs.org'
--deny-url 'evil.com'
```

## `twsrt generate claude` — Output Changes

### New entries in `permissions.deny`

For each domain in SRT `deniedDomains` / `deniedHosts`:
```json
"WebFetch(domain:<domain>)"
```

### Example (denied domain entries only)

```json
{
  "permissions": {
    "deny": [
      "Read(**/.env)",
      "WebFetch(domain:evil.com)",
      "WebFetch(domain:*.tracker.net)"
    ]
  }
}
```

## `twsrt diff copilot` — Output Changes

New `--allow-url` and `--deny-url` lines are covered by the existing line-based diff. No output format changes.

## `twsrt diff claude` — Output Changes

Denied domain `WebFetch(domain:...)` entries in `permissions.deny` are now compared during drift detection. Missing/extra entries are reported in the same format as existing drift output.
