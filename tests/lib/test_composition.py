"""Tests for structural canonical-source composition."""

from pathlib import Path

import pytest

from twsrt.lib.composition import CompositionError, compose_documents
from twsrt.lib.models import SourceFragment


def fragment(name: str) -> SourceFragment:
    return SourceFragment(name=name, path=Path(f"/config/{name}.jsonc"))


def test_compose_documents_recursively_unions_and_deduplicates() -> None:
    result = compose_documents(
        "work",
        "srt",
        [
            (
                fragment("base"),
                {
                    "enabled": True,
                    "filesystem": {"denyRead": ["~/.ssh", "~/.aws"]},
                },
            ),
            (
                fragment("work"),
                {
                    "enabled": True,
                    "filesystem": {"denyRead": ["~/.aws", "~/work/private"]},
                },
            ),
        ],
    )

    assert result == {
        "enabled": True,
        "filesystem": {"denyRead": ["~/.ssh", "~/.aws", "~/work/private"]},
    }


def test_compose_documents_sorts_string_lists_so_fragment_order_is_irrelevant() -> None:
    base = (
        fragment("base"),
        {
            "network": {"allowedDomains": ["pypi.org", "github.com"]},
            "ignoreViolations": {"*": ["/usr/bin", "/System"]},
        },
    )
    work = (
        fragment("work"),
        {"network": {"allowedDomains": ["bmw.ghe.com", "anthropic.com"]}},
    )

    set_paths = ("/network/allowedDomains", "/ignoreViolations/*")

    base_first = compose_documents("work", "srt", [base, work], set_paths=set_paths)
    work_first = compose_documents("work", "srt", [work, base], set_paths=set_paths)

    assert base_first == work_first
    assert base_first["network"]["allowedDomains"] == [
        "anthropic.com",
        "bmw.ghe.com",
        "github.com",
        "pypi.org",
    ]
    assert base_first["ignoreViolations"] == {"*": ["/System", "/usr/bin"]}


def test_compose_documents_keeps_order_of_lists_that_are_not_all_strings() -> None:
    result = compose_documents(
        "work",
        "srt",
        [(fragment("base"), {"ports": [8080, 1080], "mixed": ["b", 1, "a"]})],
        set_paths=("/ports", "/mixed"),
    )

    assert result == {"ports": [8080, 1080], "mixed": ["b", 1, "a"]}


def test_compose_documents_keeps_order_of_string_lists_outside_set_paths() -> None:
    """An argv-like list is a sequence, not a set: sorting would corrupt it."""
    result = compose_documents(
        "work",
        "srt",
        [
            (
                fragment("base"),
                {
                    "ripgrep": {"command": "rg", "args": ["--hidden", "-g", "!.git"]},
                    "network": {"allowedDomains": ["pypi.org", "github.com"]},
                },
            )
        ],
        set_paths=("/network/allowedDomains",),
    )

    assert result["ripgrep"]["args"] == ["--hidden", "-g", "!.git"]
    assert result["network"]["allowedDomains"] == ["github.com", "pypi.org"]


def test_compose_documents_rejects_scalar_conflict_with_both_origins() -> None:
    with pytest.raises(
        CompositionError,
        match=(r"profile 'work'.*source 'srt'.*/enabled.*base\.jsonc.*work\.jsonc"),
    ):
        compose_documents(
            "work",
            "srt",
            [
                (fragment("base"), {"enabled": True}),
                (fragment("work"), {"enabled": False}),
            ],
        )


def test_compose_documents_rejects_type_conflict() -> None:
    with pytest.raises(CompositionError, match=r"/network.*different types"):
        compose_documents(
            "work",
            "srt",
            [
                (fragment("base"), {"network": {}}),
                (fragment("work"), {"network": []}),
            ],
        )
