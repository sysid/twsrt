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
    sandbox = data.get("sandbox", {})
    permissions = sandbox.get("permissions", {})

    # Filesystem rules
    filesystem = permissions.get("filesystem", {})

    # denyRead → READ/DENY
    read_section = filesystem.get("read", {})
    for pattern in read_section.get("denyOnly", []):
        rules.append(
            SecurityRule(
                scope=Scope.READ,
                action=Action.DENY,
                pattern=pattern,
                source=Source.SRT_FILESYSTEM,
            )
        )

    # denyWrite → WRITE/DENY (from denyWithinAllow)
    write_section = filesystem.get("write", {})
    for pattern in write_section.get("denyWithinAllow", []):
        rules.append(
            SecurityRule(
                scope=Scope.WRITE,
                action=Action.DENY,
                pattern=pattern,
                source=Source.SRT_FILESYSTEM,
            )
        )

    # allowWrite → WRITE/ALLOW (from allowOnly)
    for pattern in write_section.get("allowOnly", []):
        rules.append(
            SecurityRule(
                scope=Scope.WRITE,
                action=Action.ALLOW,
                pattern=pattern,
                source=Source.SRT_FILESYSTEM,
            )
        )

    # Network rules
    network = permissions.get("network", {})
    for domain in network.get("allowedHosts", []):
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
