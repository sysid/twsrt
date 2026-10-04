#!/usr/bin/env -S uv run --script
# /// script
# requires-python = ">=3.12"
# ///
"""Print the key tree of Copilot CLI's sandbox config from the installed build.

Copilot ships a JSON Schema of its RPC API; its SandboxConfig definition is the
shape of the `sandbox` key in ~/.copilot/settings.json. Unlike srt, no package
import is needed, so plain Python reads it.
Usage: scripts/copilot-schema.py [path-to-api.schema.json]

ponytail: the npm package under node_modules is only a loader; the build that
runs is the auto-updated one under ~/.copilot/pkg/<platform>/<version>, so the
newest version there is taken. A build without SandboxConfig fails loudly.
"""

import json
import sys
from pathlib import Path

DEFINITION = "SandboxConfig"


def newest_schema(pkg_root: Path) -> Path:
    """The api.schema.json of the highest installed Copilot version."""
    candidates = [
        path
        for path in pkg_root.glob("*/*/schemas/api.schema.json")
        if all(part.isdigit() for part in path.parents[1].name.split("."))
    ]
    if not candidates:
        sys.exit(f"no Copilot CLI build with a schema under {pkg_root}")
    return max(
        candidates,
        key=lambda path: tuple(int(part) for part in path.parents[1].name.split(".")),
    )


def render(schema: dict) -> list[str]:
    definitions = schema["definitions"]
    if DEFINITION not in definitions:
        sys.exit(f"{DEFINITION} not in schema; did Copilot rename it?")

    def resolve(node: dict) -> dict:
        while "$ref" in node:
            node = definitions[node["$ref"].rsplit("/", 1)[-1]]
        return node

    def label(node: dict) -> str:
        node = resolve(node)
        if "enum" in node:
            return " | ".join(json.dumps(value) for value in node["enum"])
        if "const" in node:
            return json.dumps(node["const"])
        for union in ("anyOf", "oneOf"):
            if union in node:
                return " | ".join(label(option) for option in node[union])
        kind = node.get("type", "unknown")
        if isinstance(kind, list):
            return " | ".join(kind)
        if kind == "array":
            return f"{label(node.get('items', {}))}[]"
        values = node.get("additionalProperties")
        if kind == "object" and isinstance(values, dict) and "properties" not in node:
            return f"record<string, {label(values)}>"
        return kind

    lines: list[str] = []

    def walk(node: dict, indent: str) -> None:
        node = resolve(node)
        required = set(node.get("required", []))
        for key, child in node.get("properties", {}).items():
            # A $ref'd definition carries the description when the property does not.
            description = child.get("description") or resolve(child).get("description")
            meta = label(child) + ("" if key in required else ", optional")
            comment = f"  # {description.splitlines()[0]}" if description else ""
            lines.append(f"{indent}{key}: {meta}{comment}")
            inner = resolve(child)
            values = inner.get("additionalProperties")
            if "items" in inner:
                inner = inner["items"]
            elif isinstance(values, dict) and "properties" not in inner:
                inner = values
            walk(inner, indent + "  ")

    walk(definitions[DEFINITION], "")
    return lines


def main() -> None:
    path = (
        Path(sys.argv[1])
        if len(sys.argv) > 1
        else newest_schema(Path.home() / ".copilot" / "pkg")
    )
    print(f"# {path}")
    print("\n".join(render(json.loads(path.read_text()))))


if __name__ == "__main__":
    main()
