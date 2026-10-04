"""Tests for scripts/copilot-schema.py, the Copilot sandbox key-tree printer."""

import importlib.util
import json
from pathlib import Path

SCRIPT = Path(__file__).parents[2] / "scripts" / "copilot-schema.py"
_spec = importlib.util.spec_from_file_location("copilot_schema", SCRIPT)
assert _spec is not None and _spec.loader is not None
copilot_schema = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(copilot_schema)


def write_schema(directory: Path, definitions: dict) -> Path:
    path = directory / "schemas" / "api.schema.json"
    path.parent.mkdir(parents=True)
    path.write_text(json.dumps({"definitions": definitions}))
    return path


def test_prints_nested_keys_with_types_optionality_and_first_description_line(
    tmp_path: Path,
) -> None:
    schema = write_schema(
        tmp_path,
        {
            "SandboxConfig": {
                "type": "object",
                "required": ["enabled"],
                "properties": {
                    "enabled": {"type": "boolean", "description": "On.\nMore."},
                    "userPolicy": {"$ref": "#/definitions/Policy"},
                },
            },
            "Policy": {
                "type": "object",
                "description": "User policy.",
                "properties": {
                    "deniedPaths": {"type": "array", "items": {"type": "string"}},
                },
            },
        },
    )

    lines = copilot_schema.render(json.loads(schema.read_text()))

    assert lines == [
        "enabled: boolean  # On.",
        "userPolicy: object, optional  # User policy.",
        "  deniedPaths: string[], optional",
    ]


def test_labels_enums_unions_and_string_maps(tmp_path: Path) -> None:
    schema = write_schema(
        tmp_path,
        {
            "SandboxConfig": {
                "type": "object",
                "required": ["mode", "port", "envVars"],
                "properties": {
                    "mode": {"enum": ["strict", "loose"]},
                    "port": {"anyOf": [{"type": "number"}, {"type": "null"}]},
                    "envVars": {
                        "type": "object",
                        "additionalProperties": {"type": "string"},
                    },
                },
            }
        },
    )

    lines = copilot_schema.render(json.loads(schema.read_text()))

    assert lines == [
        'mode: "strict" | "loose"',
        "port: number | null",
        "envVars: record<string, string>",
    ]


def test_walks_into_the_value_shape_of_a_map(tmp_path: Path) -> None:
    schema = write_schema(
        tmp_path,
        {
            "SandboxConfig": {
                "type": "object",
                "properties": {
                    "envVars": {
                        "type": "object",
                        "additionalProperties": {"$ref": "#/definitions/Masked"},
                    },
                },
            },
            "Masked": {
                "type": "object",
                "required": ["hosts"],
                "properties": {
                    "hosts": {"type": "array", "items": {"type": "string"}},
                },
            },
        },
    )

    lines = copilot_schema.render(json.loads(schema.read_text()))

    assert lines == [
        "envVars: record<string, object>, optional",
        "  hosts: string[]",
    ]


def test_default_schema_is_the_newest_installed_copilot_build(tmp_path: Path) -> None:
    pkg = tmp_path / "pkg" / "darwin-arm64"
    for version in ("1.0.9", "1.0.10", "0.0.381"):
        write_schema(pkg / version, {})
    (pkg / "tmp").mkdir()

    found = copilot_schema.newest_schema(tmp_path / "pkg")

    assert found == pkg / "1.0.10" / "schemas" / "api.schema.json"


def test_no_installed_copilot_build_is_an_explicit_error(tmp_path: Path) -> None:
    try:
        copilot_schema.newest_schema(tmp_path / "pkg")
    except SystemExit as exc:
        assert "no Copilot CLI build" in str(exc)
    else:
        raise AssertionError("expected SystemExit")
