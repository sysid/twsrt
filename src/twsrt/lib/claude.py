"""ClaudeGenerator — translate SecurityRules to Claude Code settings.json format."""

import json
from pathlib import Path
from typing import Any

from twsrt.lib.jsonc import read_json_object
from twsrt.lib.models import (
    Action,
    AppConfig,
    DiffResult,
    Scope,
    SecurityRule,
)
from twsrt.lib.sources import (
    _FILESYSTEM_CONFIG_KEYS,
    _NETWORK_CONFIG_KEYS,
    _SANDBOX_CONFIG_KEYS,
)


# sandbox.filesystem path lists twsrt keeps empty; see ADR 0002.
_MANAGED_PATH_LISTS = ("denyRead", "denyWrite", "allowWrite")

# ADR 0010: the same posture for every profile. Claude treats an absent
# `enabled` as off and allows unsandboxed retries by default.
_FIXED_POSTURE = {"enabled": True, "allowUnsandboxedCommands": False}


class ClaudeGenerator:
    @property
    def name(self) -> str:
        return "claude"

    def generate(self, rules: list[SecurityRule], config: AppConfig) -> str:
        """Generate Claude Code permission sections as JSON string."""
        config.require_sandbox("Claude")
        deny: list[str] = []
        ask: list[str] = []
        allow: list[str] = []
        domains: list[str] = []

        for rule in rules:
            if rule.scope == Scope.READ and rule.action == Action.DENY:
                # FR-006: denyRead → deny reading and all file-editing.
                # Edit(path) is the only editing rule Claude Code's file
                # permission checks match — it covers every file-editing tool.
                # Write(path)/MultiEdit(path) are never consulted.
                # Bare pattern always included; /** only for directories
                pattern = _rule_pattern(rule.pattern)
                for tool in ("Read", "Edit"):
                    deny.append(f"{tool}({pattern})")
                    if _is_directory_pattern(rule.pattern):
                        deny.append(f"{tool}({pattern.rstrip('/')}/**)")

            elif rule.scope == Scope.WRITE and rule.action == Action.DENY:
                # FR-007: denyWrite → deny file-editing only (no Read)
                deny.append(f"Edit({_rule_pattern(rule.pattern)})")

            elif rule.scope == Scope.WRITE and rule.action == Action.ALLOW:
                # ADR 0002: allowWrite → Edit allow rule. Claude folds it into
                # the sandbox write grant and anchors relative entries at the
                # launch cwd, like srt; a raw sandbox.filesystem.allowWrite
                # entry would anchor at the settings-file root (~/.claude).
                # Side effect: Claude's edit tools no longer prompt there.
                pattern = _rule_pattern(rule.pattern)
                allow.append(f"Edit({pattern})")
                if _is_directory_pattern(rule.pattern):
                    allow.append(f"Edit({pattern.rstrip('/')}/**)")

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

        sandbox: dict = {"network": network}

        # The path lists are managed-empty (ADR 0002): every canonical path is
        # already emitted as a Read/Edit permission rule above, which Claude
        # Code folds into the OS sandbox profile anchored like srt. A raw
        # entry here anchors relative paths at the settings-file root instead
        # (bkmr 3742), and emitting both routes once pushed the Seatbelt
        # profile past ARG_MAX (E2BIG, bkmr 3671).
        filesystem = {
            key: value
            for key, value in config.filesystem_config.items()
            if key not in _MANAGED_PATH_LISTS
        }
        sandbox["filesystem"] = filesystem

        sandbox.update(config.sandbox_config)
        sandbox.update(_FIXED_POSTURE)
        for key in _MANAGED_PATH_LISTS:
            sandbox["filesystem"][key] = []

        # denyRead also arrives as an implied denyWrite, so Edit(path) is
        # emitted twice; keep the first occurrence.
        permissions: dict = {
            "deny": list(dict.fromkeys(deny)),
            "allow": list(dict.fromkeys(allow)),
            "ask": ask,
        }

        output = {
            "permissions": permissions,
            "sandbox": sandbox,
        }
        return json.dumps(output, indent=2)

    def compatibility_warnings(
        self, rules: list[SecurityRule], config: AppConfig
    ) -> list[str]:
        """Claude generation has no additional lossy mappings to report."""
        return []

    def diff(
        self, rules: list[SecurityRule], target: Path, config: AppConfig
    ) -> DiffResult:
        """Compare generated config against existing Claude settings.json."""
        generated = json.loads(self.generate(rules, config))
        existing = _read_settings(target)

        missing: list[str] = []
        extra: list[str] = []

        # Compare deny, ask, allow sections
        for section in ("deny", "ask", "allow"):
            gen_set = set(generated["permissions"].get(section, []))
            ext_set = set(existing.get("permissions", {}).get(section, []))

            if section == "allow":
                # Only compare twsrt-owned allows (others are unmanaged)
                gen_set = {e for e in gen_set if _is_managed_allow(e)}
                ext_set = {e for e in ext_set if _is_managed_allow(e)}

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
                    missing.append(f"network.config:{key}")
                    extra.append(f"network.config:{key}")

        # Compare pass-through filesystem config keys
        gen_filesystem = generated.get("sandbox", {}).get("filesystem", {})
        ext_filesystem = existing.get("sandbox", {}).get("filesystem", {})
        for key in _FILESYSTEM_CONFIG_KEYS:
            gen_val = gen_filesystem.get(key)
            ext_val = ext_filesystem.get(key)
            if gen_val != ext_val:
                if gen_val is not None and ext_val is None:
                    missing.append(f"filesystem.config:{key}")
                elif gen_val is None and ext_val is not None:
                    extra.append(f"filesystem.config:{key}")
                else:
                    missing.append(f"filesystem.config:{key}")
                    extra.append(f"filesystem.config:{key}")

        # Compare pass-through top-level sandbox config keys
        gen_sandbox = generated.get("sandbox", {})
        ext_sandbox = existing.get("sandbox", {})
        for key in dict.fromkeys((*_SANDBOX_CONFIG_KEYS, *_FIXED_POSTURE)):
            gen_val = gen_sandbox.get(key)
            ext_val = ext_sandbox.get(key)
            if gen_val != ext_val:
                if gen_val is not None and ext_val is None:
                    missing.append(f"sandbox.config:{key}")
                elif gen_val is None and ext_val is not None:
                    extra.append(f"sandbox.config:{key}")
                else:
                    missing.append(f"sandbox.config:{key}")
                    extra.append(f"sandbox.config:{key}")

        return DiffResult(
            agent=self.name,
            missing=sorted(missing),
            extra=sorted(extra),
            matched=len(missing) == 0 and len(extra) == 0,
        )


def _rule_pattern(pattern: str) -> str:
    """Anchor absolute paths at the filesystem root for Claude rule syntax.

    In Claude Code permission rules a single leading '/' anchors at the
    settings source, not the filesystem root — 'Edit(/etc/hosts)' silently
    matches nothing absolute. '//' is the documented absolute-path anchor.
    """
    if pattern.startswith("/") and not pattern.startswith("//"):
        return "/" + pattern
    return pattern


def _is_directory_pattern(pattern: str) -> bool:
    """Determine if a deny pattern refers to a directory (needs /** expansion).

    Glob patterns (containing * or ?) are treated as-is (no expansion).
    Concrete paths are checked on the filesystem; unknown or inaccessible
    paths default to directory (safer — more restrictive).
    """
    if "*" in pattern or "?" in pattern:
        return False
    if not pattern.startswith(("/", "~")):
        # Relative entries anchor at the agent's launch cwd, unknown here:
        # stat'ing them against twsrt's own cwd would be meaningless.
        return True
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


def _is_managed_allow(entry: str) -> bool:
    """Allow entries twsrt owns in its target and replaces on every write.

    Edit(...) is owned because generated grants must disappear when a path
    leaves the policy (ADR 0002). Claude records "don't ask again" approvals in
    .claude/settings.local.json, not in the user file twsrt writes.
    """
    return _is_webfetch_entry(entry) or entry.startswith("Edit(")


def _read_settings(target: Path) -> dict[str, Any]:
    """The existing settings.json, with every section twsrt reads well-formed."""
    settings = read_json_object(target)

    def section(parent: dict[str, Any], key: str, where: str) -> dict[str, Any]:
        value = parent.get(key, {})
        if not isinstance(value, dict):
            raise ValueError(f"{target}: {where} must be an object")
        return value

    def require_strings(parent: dict[str, Any], key: str, where: str) -> None:
        value = parent.get(key, [])
        if not isinstance(value, list) or not all(isinstance(v, str) for v in value):
            raise ValueError(f"{target}: {where} must be a list of strings")

    permissions = section(settings, "permissions", "permissions")
    for key in ("allow", "ask", "deny"):
        require_strings(permissions, key, f"permissions.{key}")
    sandbox = section(settings, "sandbox", "sandbox")
    network = section(sandbox, "network", "sandbox.network")
    require_strings(network, "allowedDomains", "sandbox.network.allowedDomains")
    section(sandbox, "filesystem", "sandbox.filesystem")
    return settings


def selective_merge(target: Path, generated: dict) -> dict:
    """Merge generated permissions into existing settings.json, if there is one.

    Selective merge rules:
    - permissions.deny: fully replaced
    - permissions.ask: fully replaced
    - permissions.allow: WebFetch(domain:*) entries replaced,
      blanket allows, mcp__ allows, and project-specific allows preserved
    - sandbox, sandbox.network: keys SRT defines are replaced, and removed when
      the policy has none; unmanaged and Claude-only keys preserved
    - sandbox.filesystem: key-by-key merge (preserves unmanaged keys)
    - hooks, plugins, additionalDirectories: preserved unchanged
    """
    existing = _read_settings(target)

    # Replace deny and ask fully
    existing.setdefault("permissions", {})
    existing["permissions"]["deny"] = generated["permissions"]["deny"]
    existing["permissions"]["ask"] = generated["permissions"]["ask"]

    # Selective merge for allow: strip twsrt-owned entries, keep everything else
    existing_allow = existing["permissions"].get("allow", [])
    preserved = [e for e in existing_allow if not _is_managed_allow(e)]
    generated_allow = generated["permissions"].get("allow", [])
    existing["permissions"]["allow"] = preserved + generated_allow

    # Merge sandbox sections key-by-key (preserves unmanaged/Claude-only keys)
    existing.setdefault("sandbox", {})
    gen_sandbox = generated.get("sandbox", {})

    existing["sandbox"].setdefault("network", {})
    # A pass-through key the policy does not set is absent from the generated
    # config, so an update alone would keep another profile's loosening.
    for key in _NETWORK_CONFIG_KEYS:
        existing["sandbox"]["network"].pop(key, None)
    for key in _SANDBOX_CONFIG_KEYS:
        existing["sandbox"].pop(key, None)
    existing["sandbox"]["network"].update(gen_sandbox.get("network", {}))

    if "filesystem" in gen_sandbox:
        existing["sandbox"].setdefault("filesystem", {})
        existing["sandbox"]["filesystem"].update(gen_sandbox["filesystem"])

    # Merge top-level sandbox keys (enabled, enableWeaker*, ignoreViolations)
    for key, value in gen_sandbox.items():
        if key not in ("network", "filesystem"):
            existing["sandbox"][key] = value

    return existing
