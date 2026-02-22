"""Read and validate canonical security sources."""

import json
from pathlib import Path

from twsrt.lib.models import Action, Scope, SecurityRule, Source


def read_srt(srt_path: Path) -> list[SecurityRule]:
    """Parse SRT JSON into SecurityRules."""
    if not srt_path.exists():
        raise FileNotFoundError(f"SRT settings not found: {srt_path}")

    try:
        data = json.loads(srt_path.read_text())
    except json.JSONDecodeError as e:
        raise ValueError(f"Invalid JSON in {srt_path}: {e}") from e

    rules: list[SecurityRule] = []

    # Support both SRT formats:
    # Flat:   {"filesystem": {"denyRead": [...]}, "network": {"allowedDomains": [...]}}
    # Nested: {"sandbox": {"permissions": {"filesystem": {"read": {"denyOnly": [...]}}}}}
    if "filesystem" in data or "network" in data:
        filesystem = data.get("filesystem", {})
        deny_read = filesystem.get("denyRead", [])
        deny_write = filesystem.get("denyWrite", [])
        allow_write = filesystem.get("allowWrite", [])
        network = data.get("network", {})
        allowed_domains = network.get("allowedDomains", [])
    else:
        permissions = data.get("sandbox", {}).get("permissions", {})
        filesystem = permissions.get("filesystem", {})
        deny_read = filesystem.get("read", {}).get("denyOnly", [])
        deny_write = filesystem.get("write", {}).get("denyWithinAllow", [])
        allow_write = filesystem.get("write", {}).get("allowOnly", [])
        network = permissions.get("network", {})
        allowed_domains = network.get("allowedHosts", [])

    for pattern in deny_read:
        rules.append(
            SecurityRule(
                scope=Scope.READ,
                action=Action.DENY,
                pattern=pattern,
                source=Source.SRT_FILESYSTEM,
            )
        )

    for pattern in deny_write:
        rules.append(
            SecurityRule(
                scope=Scope.WRITE,
                action=Action.DENY,
                pattern=pattern,
                source=Source.SRT_FILESYSTEM,
            )
        )

    for pattern in allow_write:
        rules.append(
            SecurityRule(
                scope=Scope.WRITE,
                action=Action.ALLOW,
                pattern=pattern,
                source=Source.SRT_FILESYSTEM,
            )
        )

    for domain in allowed_domains:
        rules.append(
            SecurityRule(
                scope=Scope.NETWORK,
                action=Action.ALLOW,
                pattern=domain,
                source=Source.SRT_NETWORK,
            )
        )

    return rules


def read_bash_rules(bash_rules_path: Path) -> list[SecurityRule]:
    """Parse bash-rules JSON into SecurityRules."""
    if not bash_rules_path.exists():
        raise FileNotFoundError(f"Bash rules not found: {bash_rules_path}")

    try:
        data = json.loads(bash_rules_path.read_text())
    except json.JSONDecodeError as e:
        raise ValueError(f"Invalid JSON in {bash_rules_path}: {e}") from e

    rules: list[SecurityRule] = []

    for cmd in data.get("deny", []):
        rules.append(
            SecurityRule(
                scope=Scope.EXECUTE,
                action=Action.DENY,
                pattern=cmd,
                source=Source.BASH_RULES,
            )
        )

    for cmd in data.get("ask", []):
        rules.append(
            SecurityRule(
                scope=Scope.EXECUTE,
                action=Action.ASK,
                pattern=cmd,
                source=Source.BASH_RULES,
            )
        )

    return rules
