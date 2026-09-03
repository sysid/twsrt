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


def yolo_path(original: Path) -> Path:
    """Derive a yolo variant path: replace all suffixes except the last with '.yolo'.

    settings.full.json → settings.yolo.json
    settings.json      → settings.yolo.json
    copilot-flags.txt  → copilot-flags.yolo.txt
    config             → config.yolo
    """
    if not original.suffix:
        return original.with_name(f"{original.name}.yolo")
    root_stem = original.name.removesuffix("".join(original.suffixes))
    return original.with_name(f"{root_stem}.yolo{original.suffix}")


@dataclass
class ClaudeSync:
    """[claude_sync] table: sync unmanaged Claude settings between full and yolo.

    Extension point for further sync policy; today only the exclusion list.
    """

    # Dotted key paths that legitimately differ per mode and are never synced.
    mode_specific: list[str] = field(default_factory=list)


@dataclass
class AppConfig:
    sources: dict[str, CanonicalSource] = field(default_factory=dict)
    profiles: dict[str, Profile] = field(default_factory=dict)
    default_profile: str | None = None
    srt_path: Path = field(
        default_factory=lambda: Path("~/.srt-settings.json").expanduser()
    )
    bash_rules_path: Path = field(
        default_factory=lambda: Path("~/.config/twsrt/bash-rules.json").expanduser()
    )
    claude_settings_path: Path = field(
        default_factory=lambda: Path("~/.claude/settings.full.json").expanduser()
    )
    copilot_output_path: Path | None = None
    codex_config_path: Path = field(
        default_factory=lambda: Path("~/.codex/config.toml").expanduser()
    )
    # None = escalation-rules generation disabled (codex_rules unset in config.toml)
    codex_rules_path: Path | None = None
    codex_targets_configured: bool = False
    claude_yolo_path: Path | None = None
    copilot_yolo_path: Path | None = None
    network_config: dict[str, Any] = field(default_factory=dict)
    filesystem_config: dict[str, Any] = field(default_factory=dict)
    sandbox_config: dict[str, Any] = field(default_factory=dict)
    srt_sandbox_enabled: bool | None = None
    sandbox_overrides: dict[str, dict[str, Any]] = field(default_factory=dict)
    # None = [claude_sync] absent: invariant sync between full/yolo disabled.
    claude_sync: ClaudeSync | None = None
    yolo: bool = False

    def apply_sandbox_overrides(self) -> None:
        """Merge mode-specific sandbox overrides into sandbox_config.

        Selects "yolo" or "full" overrides based on self.yolo flag,
        then updates sandbox_config so overrides take precedence over SRT values.
        """
        mode = "yolo" if self.yolo else "full"
        overrides = self.sandbox_overrides.get(mode, {})
        self.sandbox_config.update(overrides)

    @property
    def symlink_anchor(self) -> Path:
        """The fixed path Claude Code reads — always settings.json in the target dir."""
        return self.claude_settings_path.parent / "settings.json"


@dataclass
class DiffResult:
    agent: str
    missing: list[str]
    extra: list[str]
    matched: bool
