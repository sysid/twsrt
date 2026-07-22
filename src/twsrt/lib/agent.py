"""AgentGenerator Protocol and registry."""

from pathlib import Path
from typing import Protocol

from twsrt.lib.models import AppConfig, DiffResult, SecurityRule


class AgentGenerator(Protocol):
    @property
    def name(self) -> str: ...

    def generate(self, rules: list[SecurityRule], config: AppConfig) -> str:
        """Generate agent-specific config from security rules."""
        ...

    def compatibility_warnings(
        self, rules: list[SecurityRule], config: AppConfig
    ) -> list[str]:
        """Describe lossy or safety-relevant agent translations."""
        ...

    def diff(
        self, rules: list[SecurityRule], target: Path, config: AppConfig
    ) -> DiffResult:
        """Compare generated config against existing target file."""
        ...


def _build_registry() -> dict[str, AgentGenerator]:
    """Build the generators registry. Import here to avoid circular imports."""
    from twsrt.lib.claude import ClaudeGenerator
    from twsrt.lib.codex import CodexGenerator
    from twsrt.lib.copilot import CopilotGenerator

    return {
        "claude": ClaudeGenerator(),
        "copilot": CopilotGenerator(),
        "codex": CodexGenerator(),
    }


GENERATORS: dict[str, AgentGenerator] = _build_registry()
