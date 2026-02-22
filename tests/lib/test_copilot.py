"""Tests for Copilot CLI flag generation."""

import pytest

from twsrt.lib.copilot import CopilotGenerator
from twsrt.lib.models import Action, AppConfig, Scope, SecurityRule, Source


@pytest.fixture
def gen() -> CopilotGenerator:
    return CopilotGenerator()


@pytest.fixture
def config() -> AppConfig:
    return AppConfig()


class TestCopilotGeneration:
    def test_bash_deny_generates_deny_tool(
        self, gen: CopilotGenerator, config: AppConfig
    ) -> None:
        rules = [
            SecurityRule(Scope.EXECUTE, Action.DENY, "rm", Source.BASH_RULES),
            SecurityRule(Scope.EXECUTE, Action.DENY, "sudo", Source.BASH_RULES),
        ]
        output = gen.generate(rules, config)
        assert "--deny-tool 'shell(rm)'" in output
        assert "--deny-tool 'shell(sudo)'" in output

    def test_allow_write_generates_allow_tools(
        self, gen: CopilotGenerator, config: AppConfig
    ) -> None:
        """FR-008: allowWrite → allow-tool flags for copilot."""
        rules = [
            SecurityRule(Scope.WRITE, Action.ALLOW, ".", Source.SRT_FILESYSTEM),
            SecurityRule(Scope.WRITE, Action.ALLOW, "/tmp", Source.SRT_FILESYSTEM),
        ]
        output = gen.generate(rules, config)
        assert "--allow-tool 'shell(*)'" in output
        assert "--allow-tool 'read'" in output
        assert "--allow-tool 'edit'" in output
        assert "--allow-tool 'write'" in output

    def test_one_flag_per_line(self, gen: CopilotGenerator, config: AppConfig) -> None:
        rules = [
            SecurityRule(Scope.EXECUTE, Action.DENY, "rm", Source.BASH_RULES),
            SecurityRule(Scope.EXECUTE, Action.DENY, "sudo", Source.BASH_RULES),
        ]
        output = gen.generate(rules, config)
        lines = [line for line in output.strip().split("\n") if line.strip()]
        for line in lines:
            assert line.strip().startswith("--")

    def test_no_srt_wrapper(self, gen: CopilotGenerator, config: AppConfig) -> None:
        """FR-005: no wrapper function or srt -c in output."""
        rules = [
            SecurityRule(Scope.EXECUTE, Action.DENY, "rm", Source.BASH_RULES),
        ]
        output = gen.generate(rules, config)
        assert "srt" not in output.lower() or "srt" in "assert"  # avoid false positive
        assert "function" not in output.lower()

    def test_deny_read_no_copilot_output(
        self, gen: CopilotGenerator, config: AppConfig
    ) -> None:
        """denyRead: SRT handles at OS level, no Copilot flags."""
        rules = [
            SecurityRule(Scope.READ, Action.DENY, "**/.aws", Source.SRT_FILESYSTEM),
        ]
        output = gen.generate(rules, config)
        assert output.strip() == ""

    def test_deny_write_no_copilot_output(
        self, gen: CopilotGenerator, config: AppConfig
    ) -> None:
        """denyWrite: SRT handles at OS level, no Copilot flags."""
        rules = [
            SecurityRule(Scope.WRITE, Action.DENY, "**/.env", Source.SRT_FILESYSTEM),
        ]
        output = gen.generate(rules, config)
        assert output.strip() == ""

    def test_network_no_copilot_output(
        self, gen: CopilotGenerator, config: AppConfig
    ) -> None:
        """Network rules: SRT handles, no Copilot flags."""
        rules = [
            SecurityRule(Scope.NETWORK, Action.ALLOW, "github.com", Source.SRT_NETWORK),
        ]
        output = gen.generate(rules, config)
        assert output.strip() == ""


class TestCopilotLossyMapping:
    """FR-012: Bash ask mapped to deny-tool with warning."""

    def test_ask_mapped_to_deny_tool(
        self, gen: CopilotGenerator, config: AppConfig
    ) -> None:
        rules = [
            SecurityRule(Scope.EXECUTE, Action.ASK, "git push", Source.BASH_RULES),
            SecurityRule(Scope.EXECUTE, Action.ASK, "pip install", Source.BASH_RULES),
        ]
        output = gen.generate(rules, config)
        assert "--deny-tool 'shell(git push)'" in output
        assert "--deny-tool 'shell(pip install)'" in output

    def test_ask_emits_warning(
        self,
        gen: CopilotGenerator,
        config: AppConfig,
        capsys: pytest.CaptureFixture[str],
    ) -> None:
        rules = [
            SecurityRule(Scope.EXECUTE, Action.ASK, "git push", Source.BASH_RULES),
        ]
        gen.generate(rules, config)
        captured = capsys.readouterr()
        assert (
            "no ask equivalent" in captured.err.lower() or "ask" in captured.err.lower()
        )
