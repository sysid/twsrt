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
