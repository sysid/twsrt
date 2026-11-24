"""CopilotGenerator — translate SecurityRules to Copilot CLI flags and the
native sandbox in settings.json (ADR 0009)."""

import json
from pathlib import Path
from typing import Any

from twsrt.lib.copilot_sandbox import build_policy
from twsrt.lib.jsonc import read_json_object
from twsrt.lib.models import (
    Action,
    AppConfig,
    DiffResult,
    Scope,
    SecurityRule,
)

# Top-level settings.json keys twsrt owns; every other key belongs to Copilot.
OWNED_SETTINGS_KEYS = ("sandbox", "allowedUrls", "deniedUrls")


class CopilotGenerator:
    @property
    def name(self) -> str:
        return "copilot"

    def generate(self, rules: list[SecurityRule], config: AppConfig) -> str:
        """Preview: the flag snippet and/or the owned settings.json fragment."""
        sections: list[str] = []
        settings_path = config.copilot_settings_path
        if settings_path is not None:
            owned = json.dumps(self.generate_settings(rules, config), indent=2)
            sections.append(
                f"--- settings: {settings_path} (managed keys) ---\n{owned}"
            )
        # A bare config (no target) keeps the historic flags-only behaviour.
        if config.copilot_output_path is not None or settings_path is None:
            sections.append(self.generate_flags(rules, config))
        return "\n".join(sections)

    def generate_settings(
        self, rules: list[SecurityRule], config: AppConfig
    ) -> dict[str, Any]:
        """The owned settings.json keys; fixed values per ADR 0009 decision 3."""
        policy, _ = build_policy(rules, config)
        return {
            "sandbox": {
                "enabled": True,
                "allowBypass": False,
                "addCurrentWorkingDirectory": policy.add_cwd,
                "allowDevToolAccess": True,
                "sandboxMcpServers": True,
                "sandboxLspServers": True,
                "sandboxExtensions": True,
                "auth": {"git": True, "gh": True},
                "userPolicy": {
                    "filesystem": {
                        "readwritePaths": policy.readwrite,
                        "readonlyPaths": policy.readonly,
                        "deniedPaths": policy.denied,
                    },
                    "network": {
                        "allowOutbound": policy.allow_outbound,
                        "allowLocalNetwork": policy.allow_local_network,
                        "allowedHosts": policy.allowed_hosts,
                        "blockedHosts": policy.blocked_hosts,
                    },
                    "seatbelt": {"keychainAccess": False},
                },
            },
            "allowedUrls": policy.allowed_urls,
            "deniedUrls": policy.denied_urls,
        }

    def render_settings(
        self, rules: list[SecurityRule], config: AppConfig
    ) -> dict[Path, str]:
        """settings.json with the owned keys replaced; {} when not configured."""
        target = config.copilot_settings_path
        if target is None:
            return {}
        document = read_json_object(target)
        document.update(self.generate_settings(rules, config))
        return {target: json.dumps(document, indent=2) + "\n"}

    def generate_flags(self, rules: list[SecurityRule], config: AppConfig) -> str:
        """Generate Copilot CLI flags from security rules."""
        flags: list[str] = []

        allow_write_seen = False
        # With managed settings.json the URL rules live there (allowedUrls /
        # deniedUrls); repeating them as flags would be a second source.
        url_flags = config.copilot_settings_path is None

        for rule in rules:
            if rule.scope == Scope.NETWORK and not url_flags:
                continue
            if rule.scope == Scope.EXECUTE and rule.action == Action.DENY:
                flags.append(f"--deny-tool 'shell({rule.pattern})'")

            elif rule.scope == Scope.EXECUTE and rule.action == Action.ASK:
                # FR-012: lossy mapping — ask → deny-tool
                flags.append(f"--deny-tool 'shell({rule.pattern})'")

            elif rule.scope == Scope.WRITE and rule.action == Action.ALLOW:
                # FR-008: allowWrite → allow-tool flags (deduplicated)
                if not allow_write_seen:
                    allow_write_seen = True
                    flags.append("--allow-tool 'shell'")
                    flags.append("--allow-tool 'read'")
                    flags.append("--allow-tool 'edit'")
                    flags.append("--allow-tool 'write'")

            elif rule.scope == Scope.NETWORK and rule.action == Action.ALLOW:
                flags.append(f"--allow-url '{rule.pattern}'")

            elif rule.scope == Scope.NETWORK and rule.action == Action.DENY:
                flags.append(f"--deny-url '{rule.pattern}'")

            # READ/DENY, WRITE/DENY: no flag form. Enforced by the native sandbox
            # (settings.json, ADR 0009) or, in flags-only mode, the SRT wrapper.

        return "\n".join(f"{flag} \\" for flag in flags)

    def compatibility_warnings(
        self, rules: list[SecurityRule], config: AppConfig
    ) -> list[str]:
        """Describe Copilot mappings that lose canonical intent."""
        warnings: list[str] = []
        if config.copilot_settings_path is not None:
            warnings.extend(build_policy(rules, config)[1])
        if config.copilot_output_path is None and config.copilot_settings_path:
            # Settings-only: --deny-tool is the sole shell-rule form and no
            # file carries it (FR-026).
            unenforced = [
                rule.pattern
                for rule in rules
                if rule.scope == Scope.EXECUTE
                and rule.action in (Action.DENY, Action.ASK)
            ]
            if unenforced:
                warnings.append(
                    "Copilot CLI Bash deny/ask rules are not enforced without "
                    "[targets].copilot_output (the --deny-tool flags file): "
                    + ", ".join(unenforced)
                )
            return warnings
        return warnings + [
            f"Bash ask rule {rule.pattern!r} mapped to --deny-tool for copilot "
            "(no ask equivalent)"
            for rule in rules
            if rule.scope == Scope.EXECUTE and rule.action == Action.ASK
        ]

    def diff(
        self, rules: list[SecurityRule], target: Path, config: AppConfig
    ) -> DiffResult:
        """Compare the flags file (target) and the owned settings.json keys.

        With only copilot_settings configured, target is settings.json itself
        and no flags comparison happens.
        """
        missing: list[str] = []
        extra: list[str] = []
        if (
            config.copilot_output_path is not None
            or config.copilot_settings_path is None
        ):
            generated_text = self.generate_flags(rules, config)
            gen_lines = {
                line.strip().rstrip(" \\")
                for line in generated_text.strip().split("\n")
                if line.strip()
            }
            ext_lines = {
                line.strip().rstrip(" \\")
                for line in target.read_text().strip().split("\n")
                if line.strip()
            }
            missing += sorted(gen_lines - ext_lines)
            extra += sorted(ext_lines - gen_lines)

        settings_path = config.copilot_settings_path
        if settings_path is not None:
            existing = read_json_object(settings_path)
            for key, expected in self.generate_settings(rules, config).items():
                if existing.get(key) != expected:
                    missing.append(f"settings:{key}")
                    if key in existing:
                        extra.append(f"settings:{key}")

        return DiffResult(
            agent=self.name,
            missing=missing,
            extra=extra,
            matched=len(missing) == 0 and len(extra) == 0,
        )
