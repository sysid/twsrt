"""CLI tests for composable canonical-source profiles."""

import json
from pathlib import Path
from unittest.mock import MagicMock, patch

from typer.testing import CliRunner

from twsrt.bin.cli import app
from twsrt.lib.config import load_config
from twsrt.lib.profiles import resolve_profile

runner = CliRunner()


def make_profile_config(tmp_path: Path, conflicting: bool = False) -> tuple[Path, Path]:
    fragments = tmp_path / "fragments"
    fragments.mkdir()
    (fragments / "srt-base.jsonc").write_text(
        '{"enabled": true, "filesystem": {"denyRead": ["~/.ssh"]}}'
    )
    (fragments / "srt-work.jsonc").write_text(
        '{"enabled": false}'
        if conflicting
        else '{"filesystem": {"denyRead": ["~/.aws"]}}'
    )
    (fragments / "bash-base.jsonc").write_text(
        '{"allow": [], "ask": [], "deny": ["rm"]}'
    )
    claude_target = tmp_path / "claude" / "settings.full.json"
    config = tmp_path / "config.toml"
    config.write_text(
        f"""schema_version = 1
default_profile = "base"

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

[profiles.base]
srt = ["base"]
bash = ["base"]

[profiles.work]
extends = ["base"]
srt = ["work"]

[targets]
claude_settings = "{claude_target}"
"""
    )
    return config, claude_target


def test_config_init_creates_starter_files_and_opens_config(
    tmp_path: Path, monkeypatch
) -> None:
    config = tmp_path / "config.toml"
    monkeypatch.setenv("EDITOR", "test-editor")

    with patch("twsrt.bin.cli.subprocess.run") as run:
        run.return_value = MagicMock(returncode=0)
        result = runner.invoke(app, ["-c", str(config), "config", "--init"])

    assert result.exit_code == 0
    assert config.exists()
    assert (tmp_path / "srt/base.jsonc").exists()
    assert (tmp_path / "bash/base.jsonc").exists()
    run.assert_called_once_with(["test-editor", str(config)])


def test_config_init_documents_all_supported_configuration_shapes(
    tmp_path: Path, monkeypatch
) -> None:
    config = tmp_path / "config.toml"
    monkeypatch.setenv("EDITOR", "test-editor")

    with patch("twsrt.bin.cli.subprocess.run") as run:
        run.return_value = MagicMock(returncode=0)
        result = runner.invoke(app, ["-c", str(config), "config", "--init"])

    assert result.exit_code == 0
    content = config.read_text()
    expected_documentation = (
        "# Canonical source kinds",
        "# Additional SRT fragment example:",
        "# Additional Bash fragment example:",
        "# Profile inheritance and additional selection example:",
        '# extends = ["default"]',
        "claude_settings =",
        "copilot_output =",
        "codex_config =",
        "codex_rules =",
        "# claude_settings_yolo =",
        "# copilot_output_yolo =",
        "# Known top-level sandbox keys accepted here:",
        "# Known nested network keys:",
        "# Known nested filesystem keys:",
        "# Nested network/filesystem overrides replace the entire compiled section.",
        "# For filesystem overrides, twsrt then restores denyRead and denyWrite as",
        (
            "# The same seven top-level and eight nested keys documented above "
            "are valid here."
        ),
        "# [sandbox_overrides.yolo.network]",
        "# [sandbox_overrides.yolo.filesystem]",
    )
    for expected in expected_documentation:
        assert expected in content

    loaded = load_config(config)
    assert resolve_profile(loaded).name == "default"


def test_config_missing_without_init_exits_2(tmp_path: Path) -> None:
    config = tmp_path / "missing.toml"

    result = runner.invoke(app, ["-c", str(config), "config"])

    assert result.exit_code == 2
    assert "Use --init" in result.output


def test_generate_write_compiles_canonical_outputs_and_agent_target(
    tmp_path: Path,
) -> None:
    config, claude_target = make_profile_config(tmp_path)

    result = runner.invoke(app, ["-c", str(config), "generate", "claude", "--write"])

    assert result.exit_code == 0, result.output
    assert json.loads((tmp_path / "compiled/srt.json").read_text())["enabled"] is True
    assert json.loads((tmp_path / "compiled/bash.json").read_text())["deny"] == ["rm"]
    assert claude_target.exists()


def test_generate_explicit_profile_changes_compiled_union(tmp_path: Path) -> None:
    config, _ = make_profile_config(tmp_path)

    result = runner.invoke(
        app,
        ["-c", str(config), "generate", "claude", "--profile", "work", "--write"],
    )

    assert result.exit_code == 0, result.output
    compiled = json.loads((tmp_path / "compiled/srt.json").read_text())
    assert compiled["filesystem"]["denyRead"] == ["~/.ssh", "~/.aws"]


def test_generate_conflict_fails_before_writing_any_output(tmp_path: Path) -> None:
    config, claude_target = make_profile_config(tmp_path, conflicting=True)

    result = runner.invoke(
        app,
        ["-c", str(config), "generate", "claude", "--profile", "work", "--write"],
    )

    assert result.exit_code == 1
    assert "conflict at /enabled" in result.output
    assert not (tmp_path / "compiled/srt.json").exists()
    assert not (tmp_path / "compiled/bash.json").exists()
    assert not claude_target.exists()


def test_diff_reports_canonical_output_drift(tmp_path: Path) -> None:
    config, _ = make_profile_config(tmp_path)
    generated = runner.invoke(app, ["-c", str(config), "generate", "claude", "--write"])
    assert generated.exit_code == 0, generated.output
    (tmp_path / "compiled/srt.json").write_text('{"enabled": false}\n')

    result = runner.invoke(app, ["-c", str(config), "diff", "claude"])

    assert result.exit_code == 1
    assert "srt canonical: drift" in result.output
