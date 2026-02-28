"""AgentGenerator Protocol contract tests — applied to each registered generator."""

from pathlib import Path

from twsrt.lib.agent import GENERATORS
from twsrt.lib.models import AppConfig, DiffResult


# These tests will fail until generators are registered (T016, T023)


class TestAgentGeneratorContract:
    def test_generators_registry_not_empty(self) -> None:
        assert len(GENERATORS) > 0, "GENERATORS registry is empty"

    def test_each_generator_has_name(self) -> None:
        for name, gen in GENERATORS.items():
            assert isinstance(gen.name, str)
            assert gen.name == name

    def test_generate_returns_string(self) -> None:
        config = AppConfig()
        for gen in GENERATORS.values():
            result = gen.generate([], config)
            assert isinstance(result, str)

    def test_diff_returns_diff_result(self, tmp_path: Path) -> None:
        target = tmp_path / "target.json"
        target.write_text("{}")
        config = AppConfig()
        for gen in GENERATORS.values():
            result = gen.diff([], target, config)
            assert isinstance(result, DiffResult)
