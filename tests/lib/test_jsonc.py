"""Tests for the local JSONC parser."""

from pathlib import Path

import pytest

from twsrt.lib.jsonc import JsoncError, loads


def test_loads_accepts_line_and_block_comments() -> None:
    document = loads(
        """{
        // line comment
        "url": "https://example.com/a//b",
        /* block comment */
        "marker": "/* not a comment */"
    }""",
        Path("settings.jsonc"),
    )

    assert document == {
        "url": "https://example.com/a//b",
        "marker": "/* not a comment */",
    }


def test_loads_handles_escaped_quotes_before_comment_markers() -> None:
    document = loads(
        r"""{"value": "escaped quote: \" // still a string", // comment
             "path": "C:\\tmp"}""",
        Path("settings.jsonc"),
    )

    assert document == {
        "value": 'escaped quote: " // still a string',
        "path": "C:\\tmp",
    }


def test_loads_accepts_line_comment_at_end_of_file() -> None:
    document = loads('{"enabled": true} // comment', Path("settings.jsonc"))

    assert document == {"enabled": True}


def test_loads_preserves_json_error_location_after_comments() -> None:
    with pytest.raises(JsoncError, match=r"settings\.jsonc:3:14"):
        loads(
            """{
  // comment
  "enabled": tru
}""",
            Path("settings.jsonc"),
        )


def test_loads_rejects_unterminated_block_comment_at_its_start() -> None:
    with pytest.raises(JsoncError, match=r"settings\.jsonc:2:3.*unterminated"):
        loads("{\n  /* never closed\n}", Path("settings.jsonc"))


def test_loads_rejects_duplicate_object_keys() -> None:
    with pytest.raises(JsoncError, match=r"settings\.jsonc.*duplicate key 'enabled'"):
        loads('{"enabled": true, "enabled": false}', Path("settings.jsonc"))


@pytest.mark.parametrize(
    "text",
    [
        '{"enabled": true,}',
        "{'enabled': true}",
        "{enabled: true}",
        '{"value": NaN}',
        '{"value": Infinity}',
        '{"value": -Infinity}',
    ],
)
def test_loads_rejects_non_json_syntax(text: str) -> None:
    with pytest.raises(JsoncError, match=r"settings\.jsonc"):
        loads(text, Path("settings.jsonc"))


def test_loads_requires_an_object_root() -> None:
    with pytest.raises(JsoncError, match="root must be an object"):
        loads('["not", "an", "object"]', Path("settings.jsonc"))
