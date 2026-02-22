"""Tests for models: SecurityRule, enums, AppConfig, DiffResult."""

import pytest

from twsrt.lib.models import (
    Action,
    AppConfig,
    DiffResult,
    Scope,
    SecurityRule,
    Source,
)


class TestEnums:
    def test_scope_values(self) -> None:
        assert Scope.READ.value == "READ"
        assert Scope.WRITE.value == "WRITE"
        assert Scope.EXECUTE.value == "EXECUTE"
        assert Scope.NETWORK.value == "NETWORK"

    def test_action_values(self) -> None:
        assert Action.DENY.value == "DENY"
        assert Action.ASK.value == "ASK"
        assert Action.ALLOW.value == "ALLOW"

    def test_source_values(self) -> None:
        assert Source.SRT_FILESYSTEM.value == "SRT_FILESYSTEM"
        assert Source.SRT_NETWORK.value == "SRT_NETWORK"
        assert Source.BASH_RULES.value == "BASH_RULES"


class TestSecurityRule:
    def test_construction(self) -> None:
        rule = SecurityRule(
            scope=Scope.READ,
            action=Action.DENY,
            pattern="**/.aws",
            source=Source.SRT_FILESYSTEM,
        )
        assert rule.scope == Scope.READ
        assert rule.action == Action.DENY
        assert rule.pattern == "**/.aws"
        assert rule.source == Source.SRT_FILESYSTEM

    def test_empty_pattern_rejected(self) -> None:
        with pytest.raises(ValueError, match="pattern"):
            SecurityRule(
                scope=Scope.READ,
                action=Action.DENY,
                pattern="",
                source=Source.SRT_FILESYSTEM,
            )

    def test_network_requires_allow(self) -> None:
        with pytest.raises(ValueError, match="NETWORK.*ALLOW"):
            SecurityRule(
                scope=Scope.NETWORK,
                action=Action.DENY,
                pattern="github.com",
                source=Source.SRT_NETWORK,
            )

    def test_network_allow_is_valid(self) -> None:
        rule = SecurityRule(
            scope=Scope.NETWORK,
            action=Action.ALLOW,
            pattern="github.com",
            source=Source.SRT_NETWORK,
        )
        assert rule.scope == Scope.NETWORK

    def test_execute_requires_bash_rules(self) -> None:
        with pytest.raises(ValueError, match="EXECUTE.*BASH_RULES"):
            SecurityRule(
                scope=Scope.EXECUTE,
                action=Action.DENY,
                pattern="rm",
                source=Source.SRT_FILESYSTEM,
            )

    def test_read_requires_srt_filesystem(self) -> None:
        with pytest.raises(ValueError, match="READ.*SRT_FILESYSTEM"):
            SecurityRule(
                scope=Scope.READ,
                action=Action.DENY,
                pattern="**/.aws",
                source=Source.BASH_RULES,
            )

    def test_write_requires_srt_filesystem(self) -> None:
        with pytest.raises(ValueError, match="WRITE.*SRT_FILESYSTEM"):
            SecurityRule(
                scope=Scope.WRITE,
                action=Action.DENY,
                pattern="**/.env",
                source=Source.BASH_RULES,
            )


class TestAppConfig:
    def test_defaults(self) -> None:
        config = AppConfig()
        assert str(config.srt_path).endswith(".srt-settings.json")
        assert str(config.bash_rules_path).endswith("bash-rules.json")
        assert str(config.claude_settings_path).endswith("settings.json")
        assert config.copilot_output_path is None

    def test_tilde_expansion(self) -> None:
        config = AppConfig()
        # Paths should not contain literal ~
        assert "~" not in str(config.srt_path)
        assert "~" not in str(config.bash_rules_path)
        assert "~" not in str(config.claude_settings_path)


class TestDiffResult:
    def test_construction(self) -> None:
        result = DiffResult(
            agent="claude",
            missing=["Read(**/.kube/**)"],
            extra=["Bash(docker run:*)"],
            matched=False,
        )
        assert result.agent == "claude"
        assert len(result.missing) == 1
        assert len(result.extra) == 1
        assert result.matched is False

    def test_no_drift(self) -> None:
        result = DiffResult(agent="copilot", missing=[], extra=[], matched=True)
        assert result.matched is True
