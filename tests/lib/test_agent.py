"""AgentGenerator Protocol contract tests — applied to each registered generator."""

from pathlib import Path

from twsrt.lib.agent import GENERATORS
from twsrt.lib.models import AppConfig, DiffResult


# These tests will fail until generators are registered (T016, T023)


class TestAgentGeneratorContract:
    def test_generators_registry_not_empty(self) -> None:
        assert len(GENERATORS) > 0, "GENERATORS registry is empty"

    def test_codex_generator_is_registered(self) -> None:
        assert "codex" in GENERATORS

    def test_each_generator_has_name(self) -> None:
        for name, gen in GENERATORS.items():
            assert isinstance(gen.name, str)
            assert gen.name == name

    def test_generate_returns_string(self, tmp_path: Path) -> None:
        """Generators only run for configured agents, so every target is set."""
        config = AppConfig(
            claude_settings_path=tmp_path / "settings.full.json",
            copilot_output_path=tmp_path / "copilot-flags.txt",
            codex_config_path=tmp_path / "config.toml",
        )
        for gen in GENERATORS.values():
            result = gen.generate([], config)
            assert isinstance(result, str)

    def test_compatibility_warnings_returns_strings(self) -> None:
        config = AppConfig()
        for gen in GENERATORS.values():
            warnings = gen.compatibility_warnings([], config)
            assert isinstance(warnings, list)
            assert all(isinstance(warning, str) for warning in warnings)

    def test_diff_returns_diff_result(self, tmp_path: Path) -> None:
        for gen in GENERATORS.values():
            target = tmp_path / f"target-{gen.name}"
            target.write_text("{}" if gen.name != "codex" else "")
            config = AppConfig(
                codex_config_path=target,
                codex_rules_path=tmp_path / "twsrt.rules",
            )
            result = gen.diff([], target, config)
            assert isinstance(result, DiffResult)
