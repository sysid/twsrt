"""ClaudeGenerator — translate SecurityRules to Claude Code settings.json format."""

import json
from pathlib import Path

from twsrt.lib.models import (
    Action,
    AppConfig,
    DiffResult,
    Scope,
    SecurityRule,
)


class ClaudeGenerator:
    @property
    def name(self) -> str:
        return "claude"

    def generate(self, rules: list[SecurityRule], config: AppConfig) -> str:
        """Generate Claude Code permission sections as JSON string."""
        deny: list[str] = []
        ask: list[str] = []
        allow: list[str] = []
        domains: list[str] = []

        for rule in rules:
            if rule.scope == Scope.READ and rule.action == Action.DENY:
                # FR-006: denyRead → deny ALL file tools
                # Bare pattern always included; /** only for directories
                for tool in ("Read", "Write", "Edit", "MultiEdit"):
                    deny.append(f"{tool}({rule.pattern})")
                    if _is_directory_pattern(rule.pattern):
                        deny.append(f"{tool}({rule.pattern}/**)")

            elif rule.scope == Scope.WRITE and rule.action == Action.DENY:
                # FR-007: denyWrite → deny write tools only
                deny.append(f"Write({rule.pattern})")
                deny.append(f"Edit({rule.pattern})")
                deny.append(f"MultiEdit({rule.pattern})")

            elif rule.scope == Scope.WRITE and rule.action == Action.ALLOW:
                # FR-008: allowWrite → no Claude output (SRT enforces)
                pass

            elif rule.scope == Scope.NETWORK and rule.action == Action.ALLOW:
                # FR-009: allowedDomains → WebFetch + sandbox.network
                allow.append(f"WebFetch(domain:{rule.pattern})")
                domains.append(rule.pattern)

            elif rule.scope == Scope.NETWORK and rule.action == Action.DENY:
                # FR-006: deniedDomains → WebFetch deny only (no sandbox.network)
                deny.append(f"WebFetch(domain:{rule.pattern})")

            elif rule.scope == Scope.EXECUTE and rule.action == Action.DENY:
                # FR-010: Bash deny — bare command + wildcard
                deny.append(f"Bash({rule.pattern})")
                deny.append(f"Bash({rule.pattern} *)")

            elif rule.scope == Scope.EXECUTE and rule.action == Action.ASK:
                # FR-011: Bash ask — bare command + wildcard
                ask.append(f"Bash({rule.pattern})")
                ask.append(f"Bash({rule.pattern} *)")

        network: dict = {"allowedDomains": domains}
        network.update(config.network_config)

        output = {
            "permissions": {
                "deny": deny,
                "ask": ask,
                "allow": allow,
            },
            "sandbox": {
                "network": network,
            },
        }
        return json.dumps(output, indent=2)

    def diff(self, rules: list[SecurityRule], target: Path, config: AppConfig) -> DiffResult:
        """Compare generated config against existing Claude settings.json."""
        generated = json.loads(self.generate(rules, config))
        existing = json.loads(target.read_text())

        missing: list[str] = []
        extra: list[str] = []

        # Compare deny, ask, allow sections
        for section in ("deny", "ask", "allow"):
            gen_set = set(generated["permissions"].get(section, []))
            ext_set = set(existing.get("permissions", {}).get(section, []))

            if section == "allow":
                # Only compare WebFetch entries (others are unmanaged)
                gen_set = {e for e in gen_set if _is_webfetch_entry(e)}
                ext_set = {e for e in ext_set if _is_webfetch_entry(e)}

            for entry in gen_set - ext_set:
                missing.append(entry)
            for entry in ext_set - gen_set:
                extra.append(entry)

        # Compare sandbox.network.allowedDomains
        gen_domains = set(
            generated.get("sandbox", {}).get("network", {}).get("allowedDomains", [])
        )
        ext_domains = set(
            existing.get("sandbox", {}).get("network", {}).get("allowedDomains", [])
        )
        for d in gen_domains - ext_domains:
            missing.append(f"network:{d}")
        for d in ext_domains - gen_domains:
            extra.append(f"network:{d}")

        # Compare pass-through network config keys
        from twsrt.lib.sources import _NETWORK_CONFIG_KEYS

        gen_network = generated.get("sandbox", {}).get("network", {})
        ext_network = existing.get("sandbox", {}).get("network", {})
        for key in _NETWORK_CONFIG_KEYS:
            gen_val = gen_network.get(key)
            ext_val = ext_network.get(key)
            if gen_val != ext_val:
                if gen_val is not None and ext_val is None:
                    missing.append(f"network.config:{key}")
                elif gen_val is None and ext_val is not None:
                    extra.append(f"network.config:{key}")
                else:
                    # Value mismatch — report both
                    missing.append(f"network.config:{key}")
                    extra.append(f"network.config:{key}")

        return DiffResult(
            agent=self.name,
            missing=sorted(missing),
            extra=sorted(extra),
            matched=len(missing) == 0 and len(extra) == 0,
        )


def _is_directory_pattern(pattern: str) -> bool:
    """Determine if a deny pattern refers to a directory (needs /** expansion).

    Glob patterns (containing * or ?) are treated as-is (no expansion).
    Concrete paths are checked on the filesystem; unknown or inaccessible
    paths default to directory (safer — more restrictive).
    """
    if "*" in pattern or "?" in pattern:
        return False
    try:
        expanded = Path(pattern).expanduser()
        if expanded.is_file():
            return False
    except OSError:
        pass
    # Unknown, inaccessible, or directory → assume directory (safer default)
    return True


def _is_webfetch_entry(entry: str) -> bool:
    """Check if an allow entry is a WebFetch(domain:...) entry managed by twsrt."""
    return entry.startswith("WebFetch(domain:")


def selective_merge(target: Path, generated: dict) -> dict:
    """Merge generated permissions into existing settings.json.

    FR-018: Selective merge rules:
    - permissions.deny: fully replaced
    - permissions.ask: fully replaced
    - permissions.allow: WebFetch(domain:*) entries replaced,
      blanket allows, mcp__ allows, and project-specific allows preserved
    - sandbox.network: key-by-key merge (preserves unmanaged keys)
    - hooks, plugins, additionalDirectories: preserved unchanged
    """
    existing = json.loads(target.read_text())

    # Replace deny and ask fully
    existing.setdefault("permissions", {})
    existing["permissions"]["deny"] = generated["permissions"]["deny"]
    existing["permissions"]["ask"] = generated["permissions"]["ask"]

    # Selective merge for allow: strip WebFetch entries, keep everything else
    existing_allow = existing["permissions"].get("allow", [])
    preserved = [e for e in existing_allow if not _is_webfetch_entry(e)]
    generated_allow = generated["permissions"].get("allow", [])
    existing["permissions"]["allow"] = preserved + generated_allow

    # Merge sandbox.network key-by-key (preserves unmanaged keys like allowManagedDomainsOnly)
    existing.setdefault("sandbox", {})
    existing["sandbox"].setdefault("network", {})
    existing["sandbox"]["network"].update(generated["sandbox"]["network"])

    return existing
