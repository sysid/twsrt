"""TOML configuration loading and validation for twsrt."""

from __future__ import annotations

import tomllib
import unicodedata
from collections.abc import Iterable
from pathlib import Path
from typing import Any, cast

from twsrt.lib.models import (
    AppConfig,
    CanonicalSource,
    Profile,
    SourceFragment,
)

SCHEMA_VERSION = 1
SOURCE_KINDS = ("srt", "bash")
# srt is the sandbox itself. bash is optional: without it no command rules
# exist and every bash code path is skipped.
REQUIRED_SOURCE_KINDS = ("srt",)
# Canonical output file names: next to config.toml when [sources.<kind>].output
# is omitted, and inside ./.twsrt/<profile>/ under `generate --project`.
DEFAULT_OUTPUT_NAMES = {"srt": "srt-settings.json", "bash": "bash-rules.json"}


_TOP_LEVEL_KEYS = (
    "schema_version",
    "default_profile",
    "sources",
    "profiles",
    "targets",
)
# ADR 0010: keys of twsrt 3.x, with what replaced them.
_REMOVED_KEYS = {
    "sandbox_overrides": "Claude's sandbox is always enabled; for one session "
    "without it use claude --settings",
    "claude_sync": "there is one settings.json, so nothing is left to sync",
    "claude_settings_yolo": "select a profile instead of a mode",
    "copilot_output_yolo": "select a profile instead of a mode",
}


def source_kind_error(kind: str, configured: Iterable[str]) -> str:
    """Why *kind* cannot be used: it is not a source kind at all.

    A known but unconfigured kind is not an error: the CLI reports it as Info.
    """
    available = ", ".join(sorted(configured))
    return f"Unknown source kind {kind!r}; available: {available}"


def load_config(config_path: Path) -> AppConfig:
    """Load and validate the canonical twsrt configuration."""
    if not config_path.exists():
        raise FileNotFoundError(f"Config file not found: {config_path}")

    try:
        with open(config_path, "rb") as file:
            data = tomllib.load(file)
    except tomllib.TOMLDecodeError as exc:
        raise ValueError(f"Invalid TOML in {config_path}: {exc}") from exc

    raw_sources = _require_table(data.get("sources", {}), "sources")
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

    _reject_unknown_keys(data, _TOP_LEVEL_KEYS, config_path.name)

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

    targets = _require_table(data.get("targets", {}), "targets")
    config = AppConfig(
        sources=sources,
        policy_files=_policy_files(config_path, sources),
        profiles=profiles,
        default_profile=default_profile,
    )
    # These fields remain the agent-generation target model. Canonical-source
    # orchestration consumes config.sources instead of these compatibility
    # accessors.
    config.srt_path = sources["srt"].output_path
    if "bash" in sources:
        config.bash_rules_path = sources["bash"].output_path
    _apply_target_paths(config, targets, base_dir)
    return config


def _require_table(value: Any, where: str) -> dict[str, Any]:
    if not isinstance(value, dict):
        raise ValueError(f"{where} must be a table")
    return cast(dict[str, Any], value)


def _reject_unknown_keys(
    table: dict[str, Any], known: Iterable[str], where: str
) -> None:
    """A misspelled key would otherwise drop the policy it was meant to set."""
    known = set(known)
    unknown = sorted(set(table) - known)
    removed = [
        f"{key} was removed: {_REMOVED_KEYS[key]}"
        for key in unknown
        if key in _REMOVED_KEYS
    ]
    if removed:
        raise ValueError(f"{where}: {'; '.join(removed)} (ADR 0010)")
    if unknown:
        raise ValueError(
            f"{where}: unknown key(s): {', '.join(unknown)}; "
            f"known: {', '.join(sorted(known))}"
        )


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
        blob = _require_table(blob, f"sources.{kind}")
        _reject_unknown_keys(blob, ["output", "fragments"], f"sources.{kind}")
        output_path = _resolve_path(
            blob.get("output", DEFAULT_OUTPUT_NAMES[kind]), base_dir
        )
        if output_path in output_owners:
            raise ValueError(
                f"sources.{kind} and sources.{output_owners[output_path]} use the "
                f"same output path: {output_path}"
            )
        output_owners[output_path] = kind

        raw_fragments = _require_table(
            blob.get("fragments", {}), f"sources.{kind}.fragments"
        )
        if not raw_fragments:
            raise ValueError(f"sources.{kind} must define at least one fragment")
        fragments: dict[str, SourceFragment] = {}
        for name, fragment_blob in raw_fragments.items():
            if not isinstance(fragment_blob, dict) or "path" not in fragment_blob:
                raise ValueError(f"sources.{kind}.fragments.{name}.path is required")
            _reject_unknown_keys(
                fragment_blob, ["path"], f"sources.{kind}.fragments.{name}"
            )
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

    missing = [kind for kind in REQUIRED_SOURCE_KINDS if kind not in sources]
    if missing:
        raise ValueError(f"Missing canonical source kind(s): {', '.join(missing)}")
    return sources


def _policy_files(config_path: Path, sources: dict[str, CanonicalSource]) -> list[str]:
    """config.toml plus every [sources] output and fragment path, as rules.

    Absolute, because srt anchors a relative entry at its launch cwd, not at
    the config: `--config config.toml` would protect nothing elsewhere. A
    symlinked path also carries its real path: srt keeps a link spelling whose
    target leaves the link's tree (a stow-managed ~/.config), while Seatbelt
    matches the real path, so the link spelling alone would deny nothing.
    """
    paths = [config_path]
    for source in sources.values():
        paths.append(source.output_path)
        paths.extend(fragment.path for fragment in source.fragments.values())
    spellings = (
        _tilde(spelling)
        for path in paths
        for spelling in (path.absolute(), path.resolve())
    )
    return list(dict.fromkeys(spellings))


def _tilde(path: Path) -> str:
    """Spell a path under the home directory as ~/…, like hand-written rules.

    srt and every agent translation expand ~ themselves.
    """
    home = Path.home()
    if path.is_relative_to(home):
        return f"~/{path.relative_to(home)}"
    return str(path)


def _build_profiles(
    raw: Any, sources: dict[str, CanonicalSource]
) -> dict[str, Profile]:
    raw = _require_table(raw, "profiles")
    if not raw:
        raise ValueError("At least one profile must be configured")
    profiles: dict[str, Profile] = {}
    directory_owners: dict[str, str] = {}
    for name, blob in raw.items():
        # `generate --project` writes into ./.twsrt/<name>/.
        if (
            not name
            or name.startswith(".")
            or "/" in name
            or "\\" in name
            or not name.isprintable()
        ):
            raise ValueError(
                f"profiles: {name!r} is not a valid profile name; it must be usable "
                "as a directory name and not start with a dot"
            )
        # APFS and NTFS ignore case, APFS also Unicode normalization.
        directory = unicodedata.normalize("NFC", name.casefold())
        if directory in directory_owners:
            raise ValueError(
                f"profiles: {directory_owners[directory]!r} and {name!r} would share "
                "the same directory under ./.twsrt on a case-insensitive filesystem"
            )
        directory_owners[directory] = name
        profile_blob = _require_table(blob, f"profiles.{name}")
        unconfigured = set(profile_blob) & (set(SOURCE_KINDS) - set(sources))
        if unconfigured:
            kind = min(unconfigured)
            raise ValueError(
                f"profiles.{name}: source kind {kind!r} not configured; add "
                f"[sources.{kind}] or remove profiles.{name}.{kind}"
            )
        _reject_unknown_keys(profile_blob, ["extends", *sources], f"profiles.{name}")
        selections: dict[str, list[str]] = {}
        for kind in sources:
            values = profile_blob.get(kind, [])
            if not isinstance(values, list):
                raise ValueError(f"profiles.{name}.{kind} must be a list of names")
            selections[kind] = []
            for value in values:
                if not isinstance(value, str):
                    raise ValueError(f"profiles.{name}.{kind} must be a list of names")
                selections[kind].append(value)
        extends = profile_blob.get("extends", [])
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


_DEPENDENT_TARGETS = {
    "codex_rules": "codex_config",
}


def _apply_target_paths(
    config: AppConfig, targets: dict[str, Any], base_dir: Path
) -> None:
    fields = {
        "claude_settings": "claude_settings_path",
        "copilot_output": "copilot_output_path",
        "copilot_settings": "copilot_settings_path",
        "codex_config": "codex_config_path",
        "codex_rules": "codex_rules_path",
    }
    _reject_unknown_keys(targets, [*fields, "copilot_jetbrains_xml"], "targets")
    # A secondary path refines an agent; alone it would half-configure one.
    for dependent, primary in _DEPENDENT_TARGETS.items():
        if dependent in targets and primary not in targets:
            raise ValueError(f"targets.{dependent} requires {primary}")
    for key, field_name in fields.items():
        if key in targets:
            setattr(config, field_name, _resolve_path(targets[key], base_dir))
    if "copilot_jetbrains_xml" in targets:
        config.copilot_jetbrains_xml_paths = _resolve_path_list(
            "copilot_jetbrains_xml", targets["copilot_jetbrains_xml"], base_dir
        )

    if (
        config.claude_settings_path is not None
        and config.claude_settings_path.name != "settings.json"
    ):
        raise ValueError(
            "claude_settings must be named settings.json, the only file Claude Code "
            f"reads; got {config.claude_settings_path} (ADR 0010)"
        )


def _resolve_path_list(key: str, value: Any, base_dir: Path) -> list[Path]:
    if not isinstance(value, list) or not value:
        raise ValueError(f"targets.{key} must be a non-empty list of paths")
    try:
        return [_resolve_path(item, base_dir) for item in value]
    except ValueError as exc:
        raise ValueError(f"targets.{key}: {exc}") from exc


def _resolve_path(value: Any, base_dir: Path) -> Path:
    if not isinstance(value, str) or not value:
        raise ValueError(f"Expected a non-empty path string, got {value!r}")
    path = Path(value).expanduser()
    return path if path.is_absolute() else base_dir / path
