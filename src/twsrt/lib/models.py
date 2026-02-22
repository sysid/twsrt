"""Core data models for twsrt."""

from dataclasses import dataclass, field
from enum import Enum
from pathlib import Path


class Scope(Enum):
    READ = "READ"
    WRITE = "WRITE"
    EXECUTE = "EXECUTE"
    NETWORK = "NETWORK"


class Action(Enum):
    DENY = "DENY"
    ASK = "ASK"
    ALLOW = "ALLOW"


class Source(Enum):
    SRT_FILESYSTEM = "SRT_FILESYSTEM"
    SRT_NETWORK = "SRT_NETWORK"
    BASH_RULES = "BASH_RULES"


@dataclass(frozen=True)
class SecurityRule:
    scope: Scope
    action: Action
    pattern: str
    source: Source

    def __post_init__(self) -> None:
        if not self.pattern:
            raise ValueError("pattern must not be empty")
        if self.scope == Scope.NETWORK and self.action != Action.ALLOW:
            raise ValueError("NETWORK scope requires ALLOW action")
        if self.scope == Scope.EXECUTE and self.source != Source.BASH_RULES:
            raise ValueError("EXECUTE scope requires BASH_RULES source")
        if self.scope in (Scope.READ, Scope.WRITE) and self.source not in (
            Source.SRT_FILESYSTEM,
        ):
            raise ValueError(f"{self.scope.value} scope requires SRT_FILESYSTEM source")


@dataclass
class AppConfig:
    srt_path: Path = field(
        default_factory=lambda: Path("~/.srt-settings.json").expanduser()
    )
    bash_rules_path: Path = field(
        default_factory=lambda: Path("~/.config/twsrt/bash-rules.json").expanduser()
    )
    claude_settings_path: Path = field(
        default_factory=lambda: Path("~/.claude/settings.json").expanduser()
    )
    copilot_output_path: Path | None = None


@dataclass
class DiffResult:
    agent: str
    missing: list[str]
    extra: list[str]
    matched: bool
