"""Compile, validate, and translate canonical security sources."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from twsrt.lib.composition import compose_documents
from twsrt.lib.jsonc import load as load_jsonc
from twsrt.lib.models import (
    Action,
    AppConfig,
    CompilationResult,
    CompiledDocument,
    ResolvedProfile,
    Scope,
    SecurityRule,
    Source,
    SourceFragment,
    SrtResult,
)

_NETWORK_CONFIG_KEYS = (
    "allowUnixSockets",
    "allowAllUnixSockets",
    "allowLocalBinding",
    "httpProxyPort",
    "socksProxyPort",
)
_FILESYSTEM_CONFIG_KEYS = ("allowWrite", "denyWrite", "denyRead")
_SANDBOX_CONFIG_KEYS = (
    "enabled",
    "enableWeakerNetworkIsolation",
    "enableWeakerNestedSandbox",
    "ignoreViolations",
)
_SRT_LISTS = {
    "filesystem": ("allowWrite", "denyWrite", "denyRead"),
    "network": ("allowedDomains", "deniedDomains"),
}
_BASH_ACTIONS = ("allow", "ask", "deny")


def compile_sources(config: AppConfig, profile: ResolvedProfile) -> CompilationResult:
    """Compile all source kinds selected by a resolved profile."""
    documents: dict[str, CompiledDocument] = {}
    loaded_by_kind: dict[str, list[tuple[SourceFragment, dict[str, Any]]]] = {}

    for kind, fragments in profile.fragments.items():
        loaded = [(fragment, load_jsonc(fragment.path)) for fragment in fragments]
        _validate_loaded_fragments(profile.name, kind, loaded)
        document = compose_documents(profile.name, kind, loaded)
        loaded_by_kind[kind] = loaded
        documents[kind] = CompiledDocument(
            source_kind=kind,
            output_path=config.sources[kind].output_path,
            document=document,
        )

    srt_result = parse_srt_document(documents["srt"].document)
    bash_rules = parse_bash_document(documents["bash"].document)
    return CompilationResult(
        profile_name=profile.name,
        documents=documents,
        rules=[*srt_result.rules, *bash_rules],
        srt_result=srt_result,
    )


def serialize_document(document: dict[str, Any]) -> str:
    """Serialize a compiled canonical document as strict, stable JSON."""
    return json.dumps(document, indent=2, allow_nan=False) + "\n"


def read_srt(srt_path: Path) -> SrtResult:
    """Read a strict compiled SRT JSON file."""
    return parse_srt_document(_read_strict_json(srt_path, "SRT settings"))


def read_bash_rules(bash_rules_path: Path) -> list[SecurityRule]:
    """Read a strict compiled Bash-rules JSON file."""
    return parse_bash_document(_read_strict_json(bash_rules_path, "Bash rules"))


def parse_srt_document(data: dict[str, Any]) -> SrtResult:
    """Translate a compiled SRT document into rules and pass-through config."""
    _validate_srt_document(data, "compiled SRT document")
    filesystem = data.get("filesystem", {})
    network = data.get("network", {})
    rules: list[SecurityRule] = []

    for pattern in filesystem.get("denyRead", []):
        rules.append(
            SecurityRule(Scope.READ, Action.DENY, pattern, Source.SRT_FILESYSTEM)
        )
    for pattern in filesystem.get("denyWrite", []):
        rules.append(
            SecurityRule(Scope.WRITE, Action.DENY, pattern, Source.SRT_FILESYSTEM)
        )
    for pattern in filesystem.get("allowWrite", []):
        rules.append(
            SecurityRule(Scope.WRITE, Action.ALLOW, pattern, Source.SRT_FILESYSTEM)
        )
    for domain in network.get("allowedDomains", []):
        rules.append(
            SecurityRule(Scope.NETWORK, Action.ALLOW, domain, Source.SRT_NETWORK)
        )
    for domain in network.get("deniedDomains", []):
        rules.append(
            SecurityRule(Scope.NETWORK, Action.DENY, domain, Source.SRT_NETWORK)
        )

    return SrtResult(
        rules=rules,
        network_config={
            key: network[key] for key in _NETWORK_CONFIG_KEYS if key in network
        },
        filesystem_config={
            key: filesystem[key] for key in _FILESYSTEM_CONFIG_KEYS if key in filesystem
        },
        sandbox_config={key: data[key] for key in _SANDBOX_CONFIG_KEYS if key in data},
    )


def parse_bash_document(data: dict[str, Any]) -> list[SecurityRule]:
    """Translate a compiled Bash document into execution rules."""
    _validate_bash_document(data, "compiled Bash document")
    actions = {
        "allow": Action.ALLOW,
        "ask": Action.ASK,
        "deny": Action.DENY,
    }
    return [
        SecurityRule(Scope.EXECUTE, actions[key], command, Source.BASH_RULES)
        for key in _BASH_ACTIONS
        for command in data.get(key, [])
    ]


def _validate_loaded_fragments(
    profile_name: str,
    kind: str,
    loaded: list[tuple[SourceFragment, dict[str, Any]]],
) -> None:
    for fragment, document in loaded:
        if kind == "srt":
            _validate_srt_document(document, str(fragment.path))
        elif kind == "bash":
            _validate_bash_document(document, str(fragment.path))

    if kind == "srt":
        _reject_cross_action_conflicts(
            profile_name,
            kind,
            loaded,
            (
                ("network", "allowedDomains"),
                ("network", "deniedDomains"),
            ),
        )
        _reject_cross_action_conflicts(
            profile_name,
            kind,
            loaded,
            (
                ("filesystem", "allowWrite"),
                ("filesystem", "denyWrite"),
            ),
        )
    elif kind == "bash":
        _reject_cross_action_conflicts(
            profile_name,
            kind,
            loaded,
            tuple(("", action) for action in _BASH_ACTIONS),
        )


def _reject_cross_action_conflicts(
    profile_name: str,
    kind: str,
    loaded: list[tuple[SourceFragment, dict[str, Any]]],
    buckets: tuple[tuple[str, str], ...],
) -> None:
    seen: dict[str, tuple[str, SourceFragment]] = {}
    for fragment, document in loaded:
        for section, key in buckets:
            values = (
                document.get(section, {}).get(key, [])
                if section
                else document.get(key, [])
            )
            label = f"{section}.{key}" if section else key
            for value in values:
                previous = seen.get(value)
                if previous is not None and previous[0] != label:
                    raise ValueError(
                        f"profile {profile_name!r} source {kind!r}: {value!r} appears "
                        f"in {previous[0]} ({previous[1].path}) and {label} "
                        f"({fragment.path})"
                    )
                seen[value] = (label, fragment)


def _validate_srt_document(data: dict[str, Any], source: str) -> None:
    for section, keys in _SRT_LISTS.items():
        section_value = data.get(section, {})
        if not isinstance(section_value, dict):
            raise ValueError(f"{source}: {section} must be an object")
        for key in keys:
            if key in section_value:
                _require_string_list(section_value[key], f"{source}: {section}.{key}")


def _validate_bash_document(data: dict[str, Any], source: str) -> None:
    for key in data:
        if key not in _BASH_ACTIONS:
            raise ValueError(f"{source}: unknown Bash rule key {key!r}")
    for key in _BASH_ACTIONS:
        if key in data:
            _require_string_list(data[key], f"{source}: {key}")


def _require_string_list(value: Any, field: str) -> None:
    if not isinstance(value, list) or not all(isinstance(item, str) for item in value):
        raise ValueError(f"{field} must be a list of strings")


def _read_strict_json(path: Path, label: str) -> dict[str, Any]:
    if not path.exists():
        raise FileNotFoundError(f"{label} not found: {path}")
    try:
        data = json.loads(path.read_text())
    except json.JSONDecodeError as exc:
        raise ValueError(f"Invalid JSON in {path}: {exc}") from exc
    if not isinstance(data, dict):
        raise ValueError(f"Invalid JSON in {path}: root must be an object")
    return data
