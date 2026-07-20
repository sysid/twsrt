"""Tests for canonical-source configuration and profile expansion."""

from pathlib import Path

import pytest

from twsrt.lib.config import load_config
from twsrt.lib.profiles import resolve_profile


def write_config(tmp_path: Path, body: str) -> Path:
    path = tmp_path / "config.toml"
    path.write_text(body)
    return path


def valid_config(tmp_path: Path, profiles: str | None = None) -> Path:
    profile_body = (
        profiles
        or """
[profiles.default]
srt = ["base"]
bash = ["base"]
"""
    )
    return write_config(
        tmp_path,
        f"""schema_version = 1
default_profile = "default"

[sources.srt]
output = "compiled/srt.json"
[sources.srt.fragments.base]
path = "fragments/srt-base.jsonc"
[sources.srt.fragments.work]
path = "fragments/srt-work.jsonc"

[sources.bash]
output = "compiled/bash.json"
[sources.bash.fragments.base]
path = "fragments/bash-base.jsonc"

{profile_body}
""",
    )


def test_load_config_builds_nested_source_registries_relative_to_config(
    tmp_path: Path,
) -> None:
    config = load_config(valid_config(tmp_path))

    assert config.default_profile == "default"
    assert config.sources["srt"].output_path == tmp_path / "compiled/srt.json"
    assert (
        config.sources["srt"].fragments["base"].path
        == tmp_path / "fragments/srt-base.jsonc"
    )


def test_load_config_rejects_old_string_source_shape(tmp_path: Path) -> None:
    path = write_config(
        tmp_path,
        '[sources]\nsrt = "~/.srt-settings.json"\n',
    )

    with pytest.raises(ValueError, match=r"legacy.*sources\.srt.*fragments"):
        load_config(path)


def test_load_config_rejects_unknown_schema_version(tmp_path: Path) -> None:
    path = valid_config(tmp_path)
    path.write_text(
        path.read_text().replace("schema_version = 1", "schema_version = 2")
    )

    with pytest.raises(ValueError, match="schema_version 2"):
        load_config(path)


def test_load_config_rejects_unknown_source_kind(tmp_path: Path) -> None:
    path = valid_config(tmp_path)
    path.write_text(path.read_text().replace("sources.srt", "sources.unknown"))

    with pytest.raises(ValueError, match="unknown canonical source kind 'unknown'"):
        load_config(path)


def test_load_config_rejects_duplicate_output_paths(tmp_path: Path) -> None:
    path = valid_config(tmp_path)
    path.write_text(path.read_text().replace("compiled/bash.json", "compiled/srt.json"))

    with pytest.raises(ValueError, match="same output path"):
        load_config(path)


def test_load_config_rejects_non_jsonc_fragment_path(tmp_path: Path) -> None:
    path = valid_config(tmp_path)
    path.write_text(path.read_text().replace("srt-base.jsonc", "srt-base.json"))

    with pytest.raises(ValueError, match=r"must end in \.jsonc"):
        load_config(path)


def test_resolve_profile_uses_explicit_profile_and_deduplicates_parent_first(
    tmp_path: Path,
) -> None:
    path = valid_config(
        tmp_path,
        """
[profiles.default]
srt = ["base"]
bash = ["base"]

[profiles.work]
extends = ["default"]
srt = ["base", "work"]
""",
    )
    config = load_config(path)

    resolved = resolve_profile(config, "work")

    assert [fragment.name for fragment in resolved.fragments["srt"]] == [
        "base",
        "work",
    ]
    assert [fragment.name for fragment in resolved.fragments["bash"]] == ["base"]


def test_resolve_profile_uses_configured_default(tmp_path: Path) -> None:
    config = load_config(valid_config(tmp_path))

    resolved = resolve_profile(config)

    assert resolved.name == "default"


def test_load_config_rejects_unknown_profile_parent(tmp_path: Path) -> None:
    path = valid_config(
        tmp_path,
        """
[profiles.default]
extends = ["missing"]
srt = ["base"]
bash = ["base"]
""",
    )

    with pytest.raises(ValueError, match="extends unknown profile 'missing'"):
        load_config(path)


def test_load_config_rejects_profile_cycle(tmp_path: Path) -> None:
    path = valid_config(
        tmp_path,
        """
[profiles.default]
extends = ["work"]
srt = ["base"]
bash = ["base"]
[profiles.work]
extends = ["default"]
""",
    )

    with pytest.raises(ValueError, match="cyclic extends chain"):
        load_config(path)


def test_resolve_profile_requires_every_source_kind(tmp_path: Path) -> None:
    path = valid_config(
        tmp_path,
        """
[profiles.default]
srt = ["base"]
""",
    )
    config = load_config(path)

    with pytest.raises(ValueError, match="selects no fragments for source kind 'bash'"):
        resolve_profile(config)


def test_load_config_rejects_unknown_fragment_reference(tmp_path: Path) -> None:
    path = valid_config(
        tmp_path,
        """
[profiles.default]
srt = ["missing"]
bash = ["base"]
""",
    )

    with pytest.raises(ValueError, match="unknown srt fragment 'missing'"):
        load_config(path)
