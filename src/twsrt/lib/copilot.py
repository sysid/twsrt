"""CopilotGenerator — translate SecurityRules to Copilot CLI flags."""

import sys
from pathlib import Path

from twsrt.lib.models import (
    Action,
    AppConfig,
    DiffResult,
    Scope,
    SecurityRule,
)


class CopilotGenerator:
    @property
    def name(self) -> str:
        return "copilot"

    def generate(self, rules: list[SecurityRule], config: AppConfig) -> str:
        """Generate Copilot CLI flags from security rules."""
        flags: list[str] = []
        allow_write_seen = False

        for rule in rules:
            if rule.scope == Scope.EXECUTE and rule.action == Action.DENY:
                flags.append(f"--deny-tool 'shell({rule.pattern})'")

            elif rule.scope == Scope.EXECUTE and rule.action == Action.ASK:
                # FR-012: lossy mapping — ask → deny-tool with warning
                flags.append(f"--deny-tool 'shell({rule.pattern})'")
                print(
                    f"Warning: Bash ask rule '{rule.pattern}' mapped to "
                    f"--deny-tool for copilot (no ask equivalent)",
                    file=sys.stderr,
                )

            elif rule.scope == Scope.WRITE and rule.action == Action.ALLOW:
                # FR-008: allowWrite → allow-tool flags (deduplicated)
                if not allow_write_seen:
                    allow_write_seen = True
                    flags.append("--allow-tool 'shell(*)'")
                    flags.append("--allow-tool 'read'")
                    flags.append("--allow-tool 'edit'")
                    flags.append("--allow-tool 'write'")

            # READ/DENY, WRITE/DENY, NETWORK/ALLOW: SRT handles at OS level
            # No Copilot flags generated

        return "\n".join(flags)

    def diff(self, rules: list[SecurityRule], target: Path) -> DiffResult:
        """Compare generated flags against existing target file."""
        config = AppConfig()
        generated_text = self.generate(rules, config)
        gen_lines = {
            line.strip() for line in generated_text.strip().split("\n") if line.strip()
        }
        ext_lines = {
            line.strip()
            for line in target.read_text().strip().split("\n")
            if line.strip()
        }

        missing = sorted(gen_lines - ext_lines)
        extra = sorted(ext_lines - gen_lines)

        return DiffResult(
            agent=self.name,
            missing=missing,
            extra=extra,
            matched=len(missing) == 0 and len(extra) == 0,
        )
