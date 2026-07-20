"""TOML configuration loading and validation for twsrt."""

from __future__ import annotations

import tomllib
from pathlib import Path
from typing import Any

from twsrt.lib.models import (
    AppConfig,
    CanonicalSource,
    Profile,
    SourceFragment,
)

SCHEMA_VERSION = 1
SOURCE_KINDS = ("srt", "bash")


def load_config(config_path: Path) -> AppConfig:
    """Load and validate the canonical twsrt configuration."""
    if not config_path.exists():
        raise FileNotFoundError(f"Config file not found: {config_path}")

    try:
        with open(config_path, "rb") as file:
            data = tomllib.load(file)
    except tomllib.TOMLDecodeError as exc:
        raise ValueError(f"Invalid TOML in {config_path}: {exc}") from exc

    raw_sources = data.get("sources", {})
    if any(isinstance(value, str) for value in raw_sources.values()):
        raise ValueError(
            "The legacy [sources] path schema is not supported. Replace "
            "`sources.srt = ...` with `[sources.srt]`, `output = ...`, and "
            "`[sources.srt.fragments.<name>] path = ...`."
        )

    schema_version = data.get("schema_version")
    if schema_version != SCHEMA_VERSION:
        raise ValueError(
            f"Unsupported schema_version {schema_version!r}; expected {SCHEMA_VERSION}"
        )

    base_dir = config_path.parent
    sources = _build_sources(raw_sources, base_dir)
    profiles = _build_profiles(data.get("profiles", {}), sources)
    default_profile = data.get("default_profile")
    if not isinstance(default_profile, str) or not default_profile:
        raise ValueError("default_profile must name a configured profile")
    if default_profile not in profiles:
        raise ValueError(
            f"default_profile refers to unknown profile {default_profile!r}"
        )
    _validate_profiles(profiles, sources)

    targets = data.get("targets", {})
    config = AppConfig(
        sources=sources,
        profiles=profiles,
        default_profile=default_profile,
    )
    # These fields remain the agent-generation target model. Canonical-source
    # orchestration consumes config.sources instead of these compatibility
    # accessors.
    config.srt_path = sources["srt"].output_path
    config.bash_rules_path = sources["bash"].output_path
    config.codex_targets_configured = "codex_config" in targets
    _apply_target_paths(config, targets, base_dir)
    config.sandbox_overrides = dict(data.get("sandbox_overrides", {}))
    return config


def _build_sources(raw: dict[str, Any], base_dir: Path) -> dict[str, CanonicalSource]:
    if not raw:
        raise ValueError("At least one canonical source must be configured")

    sources: dict[str, CanonicalSource] = {}
    output_owners: dict[Path, str] = {}
    for kind, blob in raw.items():
        if kind not in SOURCE_KINDS:
            raise ValueError(
                f"unknown canonical source kind {kind!r}; available: "
                f"{', '.join(SOURCE_KINDS)}"
            )
        if not isinstance(blob, dict):
            raise ValueError(f"sources.{kind} must be a table")
        if "output" not in blob:
            raise ValueError(f"sources.{kind}.output is required")
        output_path = _resolve_path(blob["output"], base_dir)
        if output_path in output_owners:
            raise ValueError(
                f"sources.{kind} and sources.{output_owners[output_path]} use the "
                f"same output path: {output_path}"
            )
        output_owners[output_path] = kind

        raw_fragments = blob.get("fragments", {})
        if not raw_fragments:
            raise ValueError(f"sources.{kind} must define at least one fragment")
        fragments: dict[str, SourceFragment] = {}
        for name, fragment_blob in raw_fragments.items():
            if not isinstance(fragment_blob, dict) or "path" not in fragment_blob:
                raise ValueError(f"sources.{kind}.fragments.{name}.path is required")
            path = _resolve_path(fragment_blob["path"], base_dir)
            if path.suffix != ".jsonc":
                raise ValueError(
                    f"sources.{kind}.fragments.{name}.path must end in .jsonc: {path}"
                )
            if path == output_path:
                raise ValueError(
                    f"sources.{kind}.fragments.{name} must not overwrite its output"
                )
            fragments[name] = SourceFragment(name=name, path=path)
        sources[kind] = CanonicalSource(
            name=kind,
            output_path=output_path,
            fragments=fragments,
        )

    missing = [kind for kind in SOURCE_KINDS if kind not in sources]
    if missing:
        raise ValueError(f"Missing canonical source kind(s): {', '.join(missing)}")
    return sources


def _build_profiles(
    raw: dict[str, Any], sources: dict[str, CanonicalSource]
) -> dict[str, Profile]:
    if not raw:
        raise ValueError("At least one profile must be configured")
    profiles: dict[str, Profile] = {}
    for name, blob in raw.items():
        if not isinstance(blob, dict):
            raise ValueError(f"profiles.{name} must be a table")
        unknown = set(blob) - {"extends", *sources}
        if unknown:
            raise ValueError(
                f"profiles.{name}: unknown field(s): {', '.join(sorted(unknown))}"
            )
        selections: dict[str, list[str]] = {}
        for kind in sources:
            values = blob.get(kind, [])
            if not isinstance(values, list):
                raise ValueError(f"profiles.{name}.{kind} must be a list of names")
            selections[kind] = []
            for value in values:
                if not isinstance(value, str):
                    raise ValueError(f"profiles.{name}.{kind} must be a list of names")
                selections[kind].append(value)
        extends = blob.get("extends", [])
        if not isinstance(extends, list):
            raise ValueError(f"profiles.{name}.extends must be a list of names")
        typed_extends: list[str] = []
        for parent in extends:
            if not isinstance(parent, str):
                raise ValueError(f"profiles.{name}.extends must be a list of names")
            typed_extends.append(parent)
        profiles[name] = Profile(
            name=name, extends=typed_extends, selections=selections
        )
    return profiles


def _validate_profiles(
    profiles: dict[str, Profile], sources: dict[str, CanonicalSource]
) -> None:
    for profile in profiles.values():
        for parent in profile.extends:
            if parent not in profiles:
                raise ValueError(
                    f"profiles.{profile.name}: extends unknown profile {parent!r}"
                )
        for kind, names in profile.selections.items():
            for name in names:
                if name not in sources[kind].fragments:
                    raise ValueError(
                        f"profiles.{profile.name}: unknown {kind} fragment {name!r}"
                    )

    def visit(name: str, stack: list[str]) -> None:
        if name in stack:
            chain = " -> ".join([*stack, name])
            raise ValueError(f"profiles: cyclic extends chain: {chain}")
        for parent in profiles[name].extends:
            visit(parent, [*stack, name])

    for name in profiles:
        visit(name, [])


def _apply_target_paths(
    config: AppConfig, targets: dict[str, Any], base_dir: Path
) -> None:
    fields = {
        "claude_settings": "claude_settings_path",
        "copilot_output": "copilot_output_path",
        "codex_config": "codex_config_path",
        "codex_rules": "codex_rules_path",
        "claude_settings_yolo": "claude_yolo_path",
        "copilot_output_yolo": "copilot_yolo_path",
    }
    for key, field_name in fields.items():
        if key in targets:
            setattr(config, field_name, _resolve_path(targets[key], base_dir))

    if config.claude_settings_path.name == "settings.json":
        raise ValueError(
            "claude_settings must not be 'settings.json' — that path is reserved "
            "for the symlink anchor. Use 'settings.full.json' instead."
        )


def _resolve_path(value: Any, base_dir: Path) -> Path:
    if not isinstance(value, str) or not value:
        raise ValueError(f"Expected a non-empty path string, got {value!r}")
    path = Path(value).expanduser()
    return path if path.is_absolute() else base_dir / path
