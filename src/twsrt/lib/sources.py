"""Read and validate canonical security sources."""

import json
from pathlib import Path

from twsrt.lib.models import Action, Scope, SecurityRule, Source, SrtResult

# Pass-through network keys (not handled as SecurityRules)
_NETWORK_CONFIG_KEYS = (
    "allowUnixSockets",
    "allowAllUnixSockets",
    "allowLocalBinding",
    "httpProxyPort",
    "socksProxyPort",
)


def read_srt(srt_path: Path) -> SrtResult:
    """Parse SRT JSON into SecurityRules and pass-through network config."""
    if not srt_path.exists():
        raise FileNotFoundError(f"SRT settings not found: {srt_path}")

    try:
        data = json.loads(srt_path.read_text())
    except json.JSONDecodeError as e:
        raise ValueError(f"Invalid JSON in {srt_path}: {e}") from e

    rules: list[SecurityRule] = []

    filesystem = data.get("filesystem", {})
    deny_read = filesystem.get("denyRead", [])
    deny_write = filesystem.get("denyWrite", [])
    allow_write = filesystem.get("allowWrite", [])
    network = data.get("network", {})
    allowed_domains = network.get("allowedDomains", [])
    denied_domains = network.get("deniedDomains", [])

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

    for domain in denied_domains:
        rules.append(
            SecurityRule(
                scope=Scope.NETWORK,
                action=Action.DENY,
                pattern=domain,
                source=Source.SRT_NETWORK,
            )
        )

    # Extract pass-through network config keys
    network_config = {k: network[k] for k in _NETWORK_CONFIG_KEYS if k in network}

    return SrtResult(rules=rules, network_config=network_config)


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
