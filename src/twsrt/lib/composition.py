"""Structural union for parsed canonical-source fragments."""

from __future__ import annotations

from copy import deepcopy
from typing import Any

from twsrt.lib.models import SourceFragment


class CompositionError(ValueError):
    """Selected fragments contain incompatible values."""


def compose_documents(
    profile_name: str,
    source_kind: str,
    fragments: list[tuple[SourceFragment, dict[str, Any]]],
) -> dict[str, Any]:
    """Union documents, rejecting every unequal scalar or type conflict."""
    result: dict[str, Any] = {}
    origins: dict[str, SourceFragment] = {}
    for fragment, document in fragments:
        _merge(
            result,
            document,
            "",
            origins,
            fragment,
            profile_name,
            source_kind,
        )
    return result


def _merge(
    current: dict[str, Any],
    incoming: dict[str, Any],
    path: str,
    origins: dict[str, SourceFragment],
    incoming_origin: SourceFragment,
    profile_name: str,
    source_kind: str,
) -> None:
    for key, incoming_value in incoming.items():
        child_path = f"{path}/{_escape_pointer(key)}"
        if key not in current:
            current[key] = deepcopy(incoming_value)
            _record_origins(incoming_value, child_path, origins, incoming_origin)
            continue

        current_value = current[key]
        existing_origin = origins.get(child_path, incoming_origin)
        if type(current_value) is not type(incoming_value):
            raise CompositionError(
                _conflict_message(
                    profile_name,
                    source_kind,
                    child_path,
                    existing_origin,
                    incoming_origin,
                    "have different types",
                )
            )
        if isinstance(current_value, dict):
            _merge(
                current_value,
                incoming_value,
                child_path,
                origins,
                incoming_origin,
                profile_name,
                source_kind,
            )
        elif isinstance(current_value, list):
            for item in incoming_value:
                if item not in current_value:
                    current_value.append(deepcopy(item))
        elif current_value != incoming_value:
            raise CompositionError(
                _conflict_message(
                    profile_name,
                    source_kind,
                    child_path,
                    existing_origin,
                    incoming_origin,
                    "contain unequal values",
                )
            )


def _record_origins(
    value: Any,
    path: str,
    origins: dict[str, SourceFragment],
    origin: SourceFragment,
) -> None:
    origins[path] = origin
    if isinstance(value, dict):
        for key, child in value.items():
            _record_origins(child, f"{path}/{_escape_pointer(key)}", origins, origin)


def _conflict_message(
    profile_name: str,
    source_kind: str,
    path: str,
    existing: SourceFragment,
    incoming: SourceFragment,
    reason: str,
) -> str:
    return (
        f"profile {profile_name!r} source {source_kind!r} conflict at {path}: "
        f"{existing.path} and {incoming.path} {reason}"
    )


def _escape_pointer(value: str) -> str:
    return value.replace("~", "~0").replace("/", "~1")
