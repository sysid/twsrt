"""ClaudeGenerator — translate SecurityRules to Claude Code settings.json format."""

import copy
import json
from collections.abc import Sequence
from pathlib import Path
from typing import Any

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
                # FR-011: Bash ask — bare command + wildcard (skip in yolo mode)
                if not config.yolo:
                    ask.append(f"Bash({rule.pattern})")
                    ask.append(f"Bash({rule.pattern} *)")

        network: dict = {"allowedDomains": domains}
        network.update(config.network_config)

        sandbox: dict = {"network": network}

        # denyRead/denyWrite are managed-empty: every canonical deny path is
        # already emitted as a Read/Edit deny rule above, and Claude Code
        # merges those into the OS sandbox profile with identical anchoring
        # (documented, and probe-verified for literals, absolutes, relative
        # globs, and move-protection). Emitting the paths here too duplicated
        # the Seatbelt profile's clause expansion past ARG_MAX (E2BIG).
        filesystem = {
            key: value
            for key, value in config.filesystem_config.items()
            if key not in ("denyRead", "denyWrite")
        }
        sandbox["filesystem"] = filesystem

        sandbox.update(config.sandbox_config)
        sandbox["filesystem"]["denyRead"] = []
        sandbox["filesystem"]["denyWrite"] = []

        permissions: dict = {"deny": deny, "allow": allow}
        if not config.yolo:
            permissions["ask"] = ask

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
        from twsrt.lib.sources import (
            _FILESYSTEM_CONFIG_KEYS,
            _NETWORK_CONFIG_KEYS,
            _SANDBOX_CONFIG_KEYS,
        )

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
        for key in _SANDBOX_CONFIG_KEYS:
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


# Sections owned by generate; sync_invariants never takes these from the donor.
# `sandbox` as a whole stays with the target because [sandbox_overrides.*] and
# the key-by-key merge below already define it per mode.
_MANAGED_PATHS = ("permissions.deny", "permissions.ask", "sandbox")


def sync_invariants(existing: dict, donor: dict, mode_specific: Sequence[str]) -> dict:
    """Replace the target's invariant keys with the donor's.

    The donor is the file Claude Code has been writing runtime settings to,
    so its invariants are the freshest. Wholesale replacement means deletions
    propagate too (last writer wins). Managed sections and declared
    mode-specific paths keep the target's value, or stay absent.
    """
    result = copy.deepcopy(donor)
    for path in (*_MANAGED_PATHS, *mode_specific):
        found, value = _get_path(existing, path)
        if found:
            _set_path(result, path, copy.deepcopy(value))
        else:
            _delete_path(result, path)
    return result


# ponytail: dotted paths cannot address keys containing a literal '.'; no such
# key exists in Claude settings today. An escape syntax is the upgrade path.
def _get_path(doc: dict, path: str) -> tuple[bool, Any]:
    node: Any = doc
    for part in path.split("."):
        if not isinstance(node, dict) or part not in node:
            return False, None
        node = node[part]
    return True, node


def _set_path(doc: dict, path: str, value: Any) -> None:
    *parents, leaf = path.split(".")
    node = doc
    for part in parents:
        child = node.get(part)
        if not isinstance(child, dict):
            child = {}
            node[part] = child
        node = child
    node[leaf] = value


def _delete_path(doc: dict, path: str) -> None:
    *parents, leaf = path.split(".")
    node: Any = doc
    for part in parents:
        node = node.get(part) if isinstance(node, dict) else None
        if node is None:
            return
    if isinstance(node, dict):
        node.pop(leaf, None)


def selective_merge(
    target: Path | None,
    generated: dict,
    donor: Path | None = None,
    mode_specific: Sequence[str] = (),
) -> dict:
    """Merge generated permissions into existing settings.json.

    Selective merge rules:
    - permissions.deny: fully replaced
    - permissions.ask: fully replaced
    - permissions.allow: WebFetch(domain:*) entries replaced,
      blanket allows, mcp__ allows, and project-specific allows preserved
    - sandbox.network: key-by-key merge (preserves unmanaged keys)
    - sandbox.filesystem: key-by-key merge (preserves unmanaged keys)
    - sandbox top-level keys: dict.update() (preserves Claude-only keys)
    - hooks, plugins, additionalDirectories: preserved unchanged, unless a
      donor is given — then every unmanaged key not listed in mode_specific
      is taken from the donor (see sync_invariants)

    target may be None (not yet created); with a donor the target is then
    bootstrapped from the donor's invariants.
    """
    existing = json.loads(target.read_text()) if target is not None else {}
    if donor is not None:
        existing = sync_invariants(
            existing, json.loads(donor.read_text()), mode_specific
        )

    # Replace deny and ask fully
    existing.setdefault("permissions", {})
    existing["permissions"]["deny"] = generated["permissions"]["deny"]
    if "ask" in generated["permissions"]:
        existing["permissions"]["ask"] = generated["permissions"]["ask"]
    else:
        existing["permissions"].pop("ask", None)

    # Selective merge for allow: strip WebFetch entries, keep everything else
    existing_allow = existing["permissions"].get("allow", [])
    preserved = [e for e in existing_allow if not _is_webfetch_entry(e)]
    generated_allow = generated["permissions"].get("allow", [])
    existing["permissions"]["allow"] = preserved + generated_allow

    # Merge sandbox sections key-by-key (preserves unmanaged/Claude-only keys)
    existing.setdefault("sandbox", {})
    gen_sandbox = generated.get("sandbox", {})

    existing["sandbox"].setdefault("network", {})
    existing["sandbox"]["network"].update(gen_sandbox.get("network", {}))

    if "filesystem" in gen_sandbox:
        existing["sandbox"].setdefault("filesystem", {})
        existing["sandbox"]["filesystem"].update(gen_sandbox["filesystem"])

    # Merge top-level sandbox keys (enabled, enableWeaker*, ignoreViolations)
    for key, value in gen_sandbox.items():
        if key not in ("network", "filesystem"):
            existing["sandbox"][key] = value

    return existing
