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

        result = gen.diff(rules, target, AppConfig())
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

        result = gen.diff(rules, target, AppConfig())
        assert result.matched is True
        assert result.missing == []
        assert result.extra == []

    def test_diff_detects_missing_denied_domain_deny_entry(
        self, tmp_path: Path
    ) -> None:
        """Missing WebFetch(domain:...) deny entry for denied domain."""
        gen = ClaudeGenerator()
        rules = [
            SecurityRule(Scope.NETWORK, Action.DENY, "evil.com", Source.SRT_NETWORK),
            SecurityRule(
                Scope.NETWORK, Action.DENY, "*.tracker.net", Source.SRT_NETWORK
            ),
        ]
        # Existing only has one of two
        existing = {
            "permissions": {
                "deny": ["WebFetch(domain:evil.com)"],
                "ask": [],
                "allow": [],
            },
            "sandbox": {"network": {"allowedDomains": []}},
        }
        target = tmp_path / "settings.json"
        target.write_text(json.dumps(existing))

        result = gen.diff(rules, target, AppConfig())
        assert result.matched is False
        assert "WebFetch(domain:*.tracker.net)" in result.missing

    def test_diff_detects_extra_denied_domain_deny_entry(self, tmp_path: Path) -> None:
        """Extra WebFetch(domain:...) deny entry not in SRT."""
        gen = ClaudeGenerator()
        rules = [
            SecurityRule(Scope.NETWORK, Action.DENY, "evil.com", Source.SRT_NETWORK),
        ]
        existing = {
            "permissions": {
                "deny": ["WebFetch(domain:evil.com)", "WebFetch(domain:stale.com)"],
                "ask": [],
                "allow": [],
            },
            "sandbox": {"network": {"allowedDomains": []}},
        }
        target = tmp_path / "settings.json"
        target.write_text(json.dumps(existing))

        result = gen.diff(rules, target, AppConfig())
        assert result.matched is False
        assert "WebFetch(domain:stale.com)" in result.extra

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

        result = gen.diff(rules, target, AppConfig())
        assert result.matched is False
        assert "Bash(docker run:*)" in result.extra


class TestClaudeNetworkConfigDrift:
    """US3: Drift detection for pass-through network config keys."""

    def test_missing_network_config_key(self, tmp_path: Path) -> None:
        """Generated has allowLocalBinding but existing doesn't → missing."""
        gen = ClaudeGenerator()
        config = AppConfig(network_config={"allowLocalBinding": True})
        rules: list[SecurityRule] = []
        existing = {
            "permissions": {"deny": [], "ask": [], "allow": []},
            "sandbox": {"network": {"allowedDomains": []}},
        }
        target = tmp_path / "settings.json"
        target.write_text(json.dumps(existing))

        result = gen.diff(rules, target, config)
        assert result.matched is False
        assert "network.config:allowLocalBinding" in result.missing

    def test_extra_network_config_key(self, tmp_path: Path) -> None:
        """Existing has httpProxyPort but generated doesn't → extra."""
        gen = ClaudeGenerator()
        config = AppConfig()  # no network_config
        rules: list[SecurityRule] = []
        existing = {
            "permissions": {"deny": [], "ask": [], "allow": []},
            "sandbox": {"network": {"allowedDomains": [], "httpProxyPort": 8080}},
        }
        target = tmp_path / "settings.json"
        target.write_text(json.dumps(existing))

        result = gen.diff(rules, target, config)
        assert result.matched is False
        assert "network.config:httpProxyPort" in result.extra

    def test_matching_network_config_no_drift(self, tmp_path: Path) -> None:
        """Both sides have same network config keys → matched."""
        gen = ClaudeGenerator()
        config = AppConfig(
            network_config={"allowLocalBinding": True, "httpProxyPort": 8080}
        )
        rules: list[SecurityRule] = []
        generated = json.loads(gen.generate(rules, config))
        target = tmp_path / "settings.json"
        target.write_text(json.dumps(generated))

        result = gen.diff(rules, target, config)
        assert result.matched is True

    def test_value_mismatch_detected(self, tmp_path: Path) -> None:
        """Same key, different value → both missing and extra reported."""
        gen = ClaudeGenerator()
        config = AppConfig(network_config={"httpProxyPort": 8080})
        rules: list[SecurityRule] = []
        existing = {
            "permissions": {"deny": [], "ask": [], "allow": []},
            "sandbox": {"network": {"allowedDomains": [], "httpProxyPort": 9090}},
        }
        target = tmp_path / "settings.json"
        target.write_text(json.dumps(existing))

        result = gen.diff(rules, target, config)
        assert result.matched is False
        # Value mismatch: generated=8080, existing=9090
        assert (
            "network.config:httpProxyPort" in result.missing
            or "network.config:httpProxyPort" in result.extra
        )

    def test_mixed_drift_scenario(self, tmp_path: Path) -> None:
        """Mix of matching, missing, and extra network config keys."""
        gen = ClaudeGenerator()
        config = AppConfig(
            network_config={
                "allowLocalBinding": True,
                "httpProxyPort": 8080,
            }
        )
        rules: list[SecurityRule] = []
        existing = {
            "permissions": {"deny": [], "ask": [], "allow": []},
            "sandbox": {
                "network": {
                    "allowedDomains": [],
                    "allowLocalBinding": True,
                    "socksProxyPort": 1080,
                }
            },
        }
        target = tmp_path / "settings.json"
        target.write_text(json.dumps(existing))

        result = gen.diff(rules, target, config)
        assert result.matched is False
        assert "network.config:httpProxyPort" in result.missing
        assert "network.config:socksProxyPort" in result.extra


class TestClaudeFilesystemConfigDrift:
    """US5: Drift detection for filesystem sandbox keys."""

    def test_missing_filesystem_key(self, tmp_path: Path) -> None:
        """Generated has allowWrite but existing doesn't → missing."""
        gen = ClaudeGenerator()
        config = AppConfig(filesystem_config={"allowWrite": [".", "/tmp"]})
        existing = {
            "permissions": {"deny": [], "ask": [], "allow": []},
            "sandbox": {"network": {"allowedDomains": []}},
        }
        target = tmp_path / "settings.json"
        target.write_text(json.dumps(existing))

        result = gen.diff([], target, config)
        assert result.matched is False
        assert "filesystem.config:allowWrite" in result.missing

    def test_extra_filesystem_key(self, tmp_path: Path) -> None:
        """Existing has denyRead but generated doesn't → extra."""
        gen = ClaudeGenerator()
        config = AppConfig()
        existing = {
            "permissions": {"deny": [], "ask": [], "allow": []},
            "sandbox": {
                "network": {"allowedDomains": []},
                "filesystem": {"denyRead": ["~/.ssh"]},
            },
        }
        target = tmp_path / "settings.json"
        target.write_text(json.dumps(existing))

        result = gen.diff([], target, config)
        assert result.matched is False
        assert "filesystem.config:denyRead" in result.extra

    def test_value_mismatch_filesystem_key(self, tmp_path: Path) -> None:
        """Same key, different value → both missing and extra reported."""
        gen = ClaudeGenerator()
        config = AppConfig(filesystem_config={"denyRead": ["~/.ssh"]})
        existing = {
            "permissions": {"deny": [], "ask": [], "allow": []},
            "sandbox": {
                "network": {"allowedDomains": []},
                "filesystem": {"denyRead": ["~/.aws"]},
            },
        }
        target = tmp_path / "settings.json"
        target.write_text(json.dumps(existing))

        result = gen.diff([], target, config)
        assert result.matched is False
        assert "filesystem.config:denyRead" in result.missing
        assert "filesystem.config:denyRead" in result.extra


class TestClaudeSandboxConfigDrift:
    """US5: Drift detection for top-level sandbox keys."""

    def test_missing_sandbox_key(self, tmp_path: Path) -> None:
        """Generated has enabled but existing doesn't → missing."""
        gen = ClaudeGenerator()
        config = AppConfig(sandbox_config={"enabled": True})
        existing = {
            "permissions": {"deny": [], "ask": [], "allow": []},
            "sandbox": {"network": {"allowedDomains": []}},
        }
        target = tmp_path / "settings.json"
        target.write_text(json.dumps(existing))

        result = gen.diff([], target, config)
        assert result.matched is False
        assert "sandbox.config:enabled" in result.missing

    def test_extra_sandbox_key(self, tmp_path: Path) -> None:
        """Existing has ignoreViolations but generated doesn't → extra."""
        gen = ClaudeGenerator()
        config = AppConfig()
        existing = {
            "permissions": {"deny": [], "ask": [], "allow": []},
            "sandbox": {
                "network": {"allowedDomains": []},
                "ignoreViolations": {"*": ["/usr/bin"]},
            },
        }
        target = tmp_path / "settings.json"
        target.write_text(json.dumps(existing))

        result = gen.diff([], target, config)
        assert result.matched is False
        assert "sandbox.config:ignoreViolations" in result.extra

    def test_matching_all_sandbox_keys_no_drift(self, tmp_path: Path) -> None:
        """All sandbox keys match → no drift."""
        gen = ClaudeGenerator()
        config = AppConfig(
            filesystem_config={"denyRead": ["~/.ssh"]},
            sandbox_config={"enabled": True},
        )
        generated = json.loads(gen.generate([], config))
        target = tmp_path / "settings.json"
        target.write_text(json.dumps(generated))

        result = gen.diff([], target, config)
        assert result.matched is True


class TestClaudeYoloDiff:
    """T021: Claude diff in yolo mode compares against yolo config."""

    def test_yolo_diff_no_drift(self, tmp_path: Path) -> None:
        """Matching yolo config → matched=True."""
        gen = ClaudeGenerator()
        config = AppConfig(yolo=True)
        rules = [
            SecurityRule(Scope.EXECUTE, Action.DENY, "rm", Source.BASH_RULES),
            SecurityRule(Scope.EXECUTE, Action.ASK, "git push", Source.BASH_RULES),
        ]
        generated = json.loads(gen.generate(rules, config))
        target = tmp_path / "settings.yolo.json"
        target.write_text(json.dumps(generated))

        result = gen.diff(rules, target, config)
        assert result.matched is True

    def test_yolo_diff_detects_deny_drift(self, tmp_path: Path) -> None:
        """Missing deny rule in yolo config → drift detected."""
        gen = ClaudeGenerator()
        config = AppConfig(yolo=True)
        rules = [
            SecurityRule(Scope.EXECUTE, Action.DENY, "rm", Source.BASH_RULES),
            SecurityRule(Scope.EXECUTE, Action.DENY, "sudo", Source.BASH_RULES),
        ]
        # Existing only has rm
        existing = {
            "permissions": {
                "deny": ["Bash(rm)", "Bash(rm *)"],
                "allow": [],
            },
            "sandbox": {"network": {"allowedDomains": []}},
        }
        target = tmp_path / "settings.yolo.json"
        target.write_text(json.dumps(existing))

        result = gen.diff(rules, target, config)
        assert result.matched is False
        assert any("sudo" in m for m in result.missing)

    def test_yolo_diff_no_ask_comparison(self, tmp_path: Path) -> None:
        """Yolo diff ignores ask section — no ask key in generated or target."""
        gen = ClaudeGenerator()
        config = AppConfig(yolo=True)
        rules = [
            SecurityRule(Scope.EXECUTE, Action.ASK, "git push", Source.BASH_RULES),
            SecurityRule(Scope.EXECUTE, Action.DENY, "rm", Source.BASH_RULES),
        ]
        generated = json.loads(gen.generate(rules, config))
        assert "ask" not in generated["permissions"]

        target = tmp_path / "settings.yolo.json"
        target.write_text(json.dumps(generated))

        result = gen.diff(rules, target, config)
        assert result.matched is True


class TestCopilotYoloDiff:
    """T022: Copilot diff in yolo mode compares against yolo config."""

    def test_yolo_diff_no_drift(self, tmp_path: Path) -> None:
        gen = CopilotGenerator()
        config = AppConfig(yolo=True)
        rules = [
            SecurityRule(Scope.EXECUTE, Action.DENY, "rm", Source.BASH_RULES),
        ]
        output = gen.generate(rules, config)
        target = tmp_path / "copilot-flags.yolo.txt"
        target.write_text(output + "\n")

        result = gen.diff(rules, target, config)
        assert result.matched is True

    def test_yolo_diff_detects_missing_deny(self, tmp_path: Path) -> None:
        gen = CopilotGenerator()
        config = AppConfig(yolo=True)
        rules = [
            SecurityRule(Scope.EXECUTE, Action.DENY, "rm", Source.BASH_RULES),
            SecurityRule(Scope.EXECUTE, Action.DENY, "sudo", Source.BASH_RULES),
        ]
        # Target only has yolo + rm
        target = tmp_path / "copilot-flags.yolo.txt"
        target.write_text("--yolo \\\n--deny-tool 'shell(rm)' \\\n")

        result = gen.diff(rules, target, config)
        assert result.matched is False
        assert "--deny-tool 'shell(sudo)'" in result.missing


class TestCopilotDrift:
    def test_extra_flag_detected(self, tmp_path: Path) -> None:
        """Existing flags with extra --deny-tool not in bash-rules."""
        gen = CopilotGenerator()
        rules = [
            SecurityRule(Scope.EXECUTE, Action.DENY, "rm", Source.BASH_RULES),
        ]
        target = tmp_path / "copilot-flags.txt"
        target.write_text("--deny-tool 'shell(rm)'\n--deny-tool 'shell(docker)'\n")

        result = gen.diff(rules, target, AppConfig())
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

        result = gen.diff(rules, target, AppConfig())
        assert result.matched is True

    def test_diff_detects_missing_allow_url(self, tmp_path: Path) -> None:
        """Missing --allow-url line detected as drift."""
        gen = CopilotGenerator()
        rules = [
            SecurityRule(Scope.NETWORK, Action.ALLOW, "github.com", Source.SRT_NETWORK),
            SecurityRule(Scope.NETWORK, Action.ALLOW, "pypi.org", Source.SRT_NETWORK),
        ]
        # Target only has one of two
        target = tmp_path / "copilot-flags.txt"
        target.write_text("--allow-url 'github.com'\n")

        result = gen.diff(rules, target, AppConfig())
        assert result.matched is False
        assert "--allow-url 'pypi.org'" in result.missing

    def test_diff_detects_extra_allow_url(self, tmp_path: Path) -> None:
        """Extra --allow-url line not in SRT detected as drift."""
        gen = CopilotGenerator()
        rules = [
            SecurityRule(Scope.NETWORK, Action.ALLOW, "github.com", Source.SRT_NETWORK),
        ]
        target = tmp_path / "copilot-flags.txt"
        target.write_text("--allow-url 'github.com'\n--allow-url 'stale.com'\n")

        result = gen.diff(rules, target, AppConfig())
        assert result.matched is False
        assert "--allow-url 'stale.com'" in result.extra

    def test_diff_detects_missing_deny_url(self, tmp_path: Path) -> None:
        """Missing --deny-url line detected as drift."""
        gen = CopilotGenerator()
        rules = [
            SecurityRule(Scope.NETWORK, Action.DENY, "evil.com", Source.SRT_NETWORK),
            SecurityRule(
                Scope.NETWORK, Action.DENY, "*.tracker.net", Source.SRT_NETWORK
            ),
        ]
        target = tmp_path / "copilot-flags.txt"
        target.write_text("--deny-url 'evil.com'\n")

        result = gen.diff(rules, target, AppConfig())
        assert result.matched is False
        assert "--deny-url '*.tracker.net'" in result.missing
