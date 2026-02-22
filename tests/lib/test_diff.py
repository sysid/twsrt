"""Tests for drift detection — Claude and Copilot."""

import json
from pathlib import Path

from twsrt.lib.claude import ClaudeGenerator
from twsrt.lib.copilot import CopilotGenerator
from twsrt.lib.models import Action, AppConfig, Scope, SecurityRule, Source


class TestClaudeDrift:
    def test_missing_rule_detected(self, tmp_path: Path) -> None:
        """Existing settings.json missing a denyRead-derived deny rule."""
        gen = ClaudeGenerator()
        rules = [
            SecurityRule(Scope.READ, Action.DENY, "**/.aws", Source.SRT_FILESYSTEM),
            SecurityRule(Scope.READ, Action.DENY, "**/.kube", Source.SRT_FILESYSTEM),
        ]
        # Existing only has .aws rules, missing .kube
        existing = {
            "permissions": {
                "deny": [
                    "Read(**/.aws/**)",
                    "Write(**/.aws/**)",
                    "Edit(**/.aws/**)",
                    "MultiEdit(**/.aws/**)",
                ],
                "ask": [],
                "allow": [],
            },
            "sandbox": {"network": {"allowedDomains": []}},
        }
        target = tmp_path / "settings.json"
        target.write_text(json.dumps(existing))

        result = gen.diff(rules, target)
        assert result.matched is False
        assert len(result.missing) > 0
        # .kube entries should be in missing
        assert any(".kube" in m for m in result.missing)

    def test_matching_config_no_drift(self, tmp_path: Path) -> None:
        """Existing settings.json matches generated → matched=True."""
        gen = ClaudeGenerator()
        config = AppConfig()
        rules = [
            SecurityRule(Scope.EXECUTE, Action.DENY, "rm", Source.BASH_RULES),
        ]
        generated = json.loads(gen.generate(rules, config))
        target = tmp_path / "settings.json"
        target.write_text(json.dumps(generated))

        result = gen.diff(rules, target)
        assert result.matched is True
        assert result.missing == []
        assert result.extra == []

    def test_extra_rule_detected(self, tmp_path: Path) -> None:
        """Existing settings.json with extra Bash deny not in sources."""
        gen = ClaudeGenerator()
        rules = [
            SecurityRule(Scope.EXECUTE, Action.DENY, "rm", Source.BASH_RULES),
        ]
        existing = {
            "permissions": {
                "deny": ["Bash(rm)", "Bash(rm *)", "Bash(docker run:*)"],
                "ask": [],
                "allow": [],
            },
            "sandbox": {"network": {"allowedDomains": []}},
        }
        target = tmp_path / "settings.json"
        target.write_text(json.dumps(existing))

        result = gen.diff(rules, target)
        assert result.matched is False
        assert "Bash(docker run:*)" in result.extra


class TestCopilotDrift:
    def test_extra_flag_detected(self, tmp_path: Path) -> None:
        """Existing flags with extra --deny-tool not in bash-rules."""
        gen = CopilotGenerator()
        rules = [
            SecurityRule(Scope.EXECUTE, Action.DENY, "rm", Source.BASH_RULES),
        ]
        target = tmp_path / "copilot-flags.txt"
        target.write_text("--deny-tool 'shell(rm)'\n--deny-tool 'shell(docker)'\n")

        result = gen.diff(rules, target)
        assert result.matched is False
        assert "--deny-tool 'shell(docker)'" in result.extra

    def test_matching_flags_no_drift(self, tmp_path: Path) -> None:
        """Existing flags match generated → matched=True."""
        gen = CopilotGenerator()
        config = AppConfig()
        rules = [
            SecurityRule(Scope.EXECUTE, Action.DENY, "rm", Source.BASH_RULES),
        ]
        output = gen.generate(rules, config)
        target = tmp_path / "copilot-flags.txt"
        target.write_text(output + "\n")

        result = gen.diff(rules, target)
        assert result.matched is True
