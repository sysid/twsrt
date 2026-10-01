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
    set_paths: tuple[str, ...] = (),
) -> dict[str, Any]:
    """Union documents, rejecting every unequal scalar or type conflict.

    String lists at `set_paths` (JSON pointers; `*` matches any key) come back
    sorted, so the generated artifacts do not depend on fragment order and diff
    cleanly between profiles and runs. Every other list keeps first-seen order:
    an unknown pass-through list may be a sequence such as argv.
    """
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
    for set_path in set_paths:
        _sort_set(result, set_path.strip("/").split("/"))
    return result


def _sort_set(node: Any, segments: list[str]) -> None:
    if not isinstance(node, dict):
        return
    head, rest = segments[0], segments[1:]
    keys = list(node) if head == "*" else [head] if head in node else []
    for key in keys:
        if rest:
            _sort_set(node[key], rest)
        elif isinstance(node[key], list) and all(
            isinstance(item, str) for item in node[key]
        ):
            node[key] = sorted(node[key])


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
