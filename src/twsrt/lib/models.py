"""Core data models for twsrt."""

from dataclasses import dataclass, field
from enum import Enum
from pathlib import Path
from typing import Any


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
        if self.scope == Scope.NETWORK and self.action not in (
            Action.ALLOW,
            Action.DENY,
        ):
            raise ValueError("NETWORK scope requires ALLOW or DENY action")
        if self.scope == Scope.EXECUTE and self.source != Source.BASH_RULES:
            raise ValueError("EXECUTE scope requires BASH_RULES source")
        if self.scope in (Scope.READ, Scope.WRITE) and self.source not in (
            Source.SRT_FILESYSTEM,
        ):
            raise ValueError(f"{self.scope.value} scope requires SRT_FILESYSTEM source")


@dataclass
class SrtResult:
    """Result from parsing SRT settings: rules + pass-through config."""

    rules: list[SecurityRule]
    network_config: dict[str, Any] = field(default_factory=dict)
    filesystem_config: dict[str, Any] = field(default_factory=dict)
    sandbox_config: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class SourceFragment:
    """One named canonical-source fragment."""

    name: str
    path: Path


@dataclass(frozen=True)
class CanonicalSource:
    """A source kind, its compiled output, and its reusable fragments."""

    name: str
    output_path: Path
    fragments: dict[str, SourceFragment]


@dataclass(frozen=True)
class Profile:
    """Named fragment selections, keyed by canonical source kind."""

    name: str
    extends: list[str] = field(default_factory=list)
    selections: dict[str, list[str]] = field(default_factory=dict)


@dataclass(frozen=True)
class ResolvedProfile:
    """A profile after inheritance and fragment lookup."""

    name: str
    fragments: dict[str, list[SourceFragment]]


@dataclass(frozen=True)
class CompiledDocument:
    """One fully composed canonical source document."""

    source_kind: str
    output_path: Path
    document: dict[str, Any]


@dataclass(frozen=True)
class CompilationResult:
    """Canonical documents and the security rules derived from them."""

    profile_name: str
    documents: dict[str, CompiledDocument]
    rules: list[SecurityRule]
    srt_result: SrtResult


# The [targets] key whose presence configures each agent.
AGENT_TARGET_KEYS = {
    "claude": "claude_settings",
    # Either key configures Copilot: flags-only stays supported (ADR 0009).
    "copilot": "copilot_output or copilot_settings",
    "codex": "codex_config",
    "copilot-jetbrains": "copilot_jetbrains_xml",
}


@dataclass
class AppConfig:
    sources: dict[str, CanonicalSource] = field(default_factory=dict)
    # config.toml and every [sources] path as deny rules (absolute or ~/…),
    # captured at load: write-denied in every compile so an agent cannot
    # loosen the policy it runs under.
    policy_files: list[str] = field(default_factory=list)
    profiles: dict[str, Profile] = field(default_factory=dict)
    default_profile: str | None = None
    srt_path: Path = field(
        default_factory=lambda: Path("~/.srt-settings.json").expanduser()
    )
    bash_rules_path: Path = field(
        default_factory=lambda: Path("~/.config/twsrt/bash-rules.json").expanduser()
    )
    # Agent targets are opt-in: None = agent not configured ([targets] key unset).
    claude_settings_path: Path | None = None
    copilot_output_path: Path | None = None
    # Copilot CLI native sandbox: settings.json, independent of the flags file.
    copilot_settings_path: Path | None = None
    # One github-copilot.xml per JetBrains product and version; empty = unset.
    copilot_jetbrains_xml_paths: list[Path] = field(default_factory=list)
    codex_config_path: Path | None = None
    # None = escalation-rules generation disabled (codex_rules unset in config.toml)
    codex_rules_path: Path | None = None
    network_config: dict[str, Any] = field(default_factory=dict)
    filesystem_config: dict[str, Any] = field(default_factory=dict)
    sandbox_config: dict[str, Any] = field(default_factory=dict)

    def require_sandbox(self, agent: str) -> None:
        """No agent gets a config for a policy that switches the sandbox off."""
        if self.sandbox_config.get("enabled") is False:
            raise ValueError(
                "Canonical SRT sandbox is disabled; refusing to generate an "
                f"unsandboxed {agent} config"
            )

    def agent_target(self, agent: str) -> Path | None:
        """The agent's primary target; None means the agent is not configured."""
        return {
            "claude": self.claude_settings_path,
            "copilot": self.copilot_output_path or self.copilot_settings_path,
            "codex": self.codex_config_path,
            "copilot-jetbrains": next(iter(self.copilot_jetbrains_xml_paths), None),
        }[agent]

    def require_target(self, agent: str) -> Path:
        target = self.agent_target(agent)
        if target is None:
            raise ValueError(
                f"{agent} is not configured: set [targets].{AGENT_TARGET_KEYS[agent]} "
                "in config.toml"
            )
        return target


@dataclass
class DiffResult:
    agent: str
    missing: list[str]
    extra: list[str]
    matched: bool
