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
            assert line.strip().rstrip(" \\").startswith("--")

    def test_lines_have_continuation_backslash(
        self, gen: CopilotGenerator, config: AppConfig
    ) -> None:
        """Each line ends with ' \\' for shell line continuation."""
        rules = [
            SecurityRule(Scope.EXECUTE, Action.DENY, "rm", Source.BASH_RULES),
            SecurityRule(Scope.EXECUTE, Action.DENY, "sudo", Source.BASH_RULES),
        ]
        output = gen.generate(rules, config)
        lines = [line for line in output.strip().split("\n") if line.strip()]
        for line in lines:
            assert line.endswith(" \\")

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

    def test_network_allow_generates_allow_url(
        self, gen: CopilotGenerator, config: AppConfig
    ) -> None:
        """FR-001: NETWORK/ALLOW → --allow-url flags."""
        rules = [
            SecurityRule(Scope.NETWORK, Action.ALLOW, "github.com", Source.SRT_NETWORK),
            SecurityRule(
                Scope.NETWORK, Action.ALLOW, "*.npmjs.org", Source.SRT_NETWORK
            ),
        ]
        output = gen.generate(rules, config)
        assert "--allow-url 'github.com'" in output
        assert "--allow-url '*.npmjs.org'" in output

    def test_allow_url_one_per_line(
        self, gen: CopilotGenerator, config: AppConfig
    ) -> None:
        """FR-002: each --allow-url on its own line."""
        rules = [
            SecurityRule(Scope.NETWORK, Action.ALLOW, "a.com", Source.SRT_NETWORK),
            SecurityRule(Scope.NETWORK, Action.ALLOW, "b.com", Source.SRT_NETWORK),
        ]
        output = gen.generate(rules, config)
        lines = [line for line in output.strip().split("\n") if line.strip()]
        allow_url_lines = [ln for ln in lines if "--allow-url" in ln]
        assert len(allow_url_lines) == 2

    def test_network_deny_generates_deny_url(
        self, gen: CopilotGenerator, config: AppConfig
    ) -> None:
        """FR-005: NETWORK/DENY → --deny-url flags."""
        rules = [
            SecurityRule(Scope.NETWORK, Action.DENY, "evil.com", Source.SRT_NETWORK),
            SecurityRule(
                Scope.NETWORK, Action.DENY, "*.tracker.net", Source.SRT_NETWORK
            ),
        ]
        output = gen.generate(rules, config)
        assert "--deny-url 'evil.com'" in output
        assert "--deny-url '*.tracker.net'" in output

    def test_deny_url_one_per_line(
        self, gen: CopilotGenerator, config: AppConfig
    ) -> None:
        """Each --deny-url on its own line."""
        rules = [
            SecurityRule(Scope.NETWORK, Action.DENY, "a.com", Source.SRT_NETWORK),
            SecurityRule(Scope.NETWORK, Action.DENY, "b.com", Source.SRT_NETWORK),
        ]
        output = gen.generate(rules, config)
        lines = [line for line in output.strip().split("\n") if line.strip()]
        deny_url_lines = [ln for ln in lines if "--deny-url" in ln]
        assert len(deny_url_lines) == 2


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
