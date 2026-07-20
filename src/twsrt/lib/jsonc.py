"""Strict JSON parsing with support for JavaScript-style comments."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any


class JsoncError(ValueError):
    """A JSONC document could not be parsed safely."""


def load(path: Path) -> dict[str, Any]:
    """Load a JSONC object from *path*."""
    if not path.exists():
        raise FileNotFoundError(f"JSONC source not found: {path}")
    return loads(path.read_text(), path)


def loads(text: str, source: Path) -> dict[str, Any]:
    """Parse strict JSON extended only with line and block comments."""
    uncommented = _replace_comments(text, source)

    def reject_duplicate_keys(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
        result: dict[str, Any] = {}
        for key, value in pairs:
            if key in result:
                raise JsoncError(f"{source}: duplicate key {key!r}")
            result[key] = value
        return result

    def reject_constant(value: str) -> Any:
        raise JsoncError(f"{source}: non-finite number {value!r} is not valid JSON")

    try:
        document = json.loads(
            uncommented,
            object_pairs_hook=reject_duplicate_keys,
            parse_constant=reject_constant,
        )
    except json.JSONDecodeError as exc:
        raise JsoncError(
            f"{source}:{exc.lineno}:{exc.colno}: invalid JSON: {exc.msg}"
        ) from exc

    if not isinstance(document, dict):
        raise JsoncError(f"{source}: JSONC root must be an object")
    return document


def _replace_comments(text: str, source: Path) -> str:
    """Replace comments with spaces without changing offsets or line endings."""
    output = list(text)
    index = 0
    in_string = False
    escaped = False

    while index < len(text):
        char = text[index]

        if in_string:
            if escaped:
                escaped = False
            elif char == "\\":
                escaped = True
            elif char == '"':
                in_string = False
            index += 1
            continue

        if char == '"':
            in_string = True
            index += 1
            continue

        if char != "/" or index + 1 >= len(text):
            index += 1
            continue

        marker = text[index + 1]
        if marker == "/":
            output[index] = " "
            output[index + 1] = " "
            index += 2
            while index < len(text) and text[index] not in "\r\n":
                output[index] = " "
                index += 1
            continue

        if marker == "*":
            start = index
            output[index] = " "
            output[index + 1] = " "
            index += 2
            while index + 1 < len(text) and text[index : index + 2] != "*/":
                if text[index] not in "\r\n":
                    output[index] = " "
                index += 1
            if index + 1 >= len(text):
                line = text.count("\n", 0, start) + 1
                line_start = text.rfind("\n", 0, start)
                column = start - line_start
                raise JsoncError(
                    f"{source}:{line}:{column}: unterminated block comment"
                )
            output[index] = " "
            output[index + 1] = " "
            index += 2
            continue

        index += 1

    return "".join(output)
