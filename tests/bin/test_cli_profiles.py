"""CLI tests for composable canonical-source profiles."""

import json
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest
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


def test_generate_write_reports_written_files_on_stderr_not_stdout(
    tmp_path: Path,
) -> None:
    config, claude_target = make_profile_config(tmp_path)

    result = runner.invoke(app, ["-c", str(config), "generate", "claude", "--write"])

    assert result.exit_code == 0, result.output
    assert result.stdout == ""
    assert f"Wrote canonical: {tmp_path / 'compiled/srt.json'}" in result.stderr
    assert f"Wrote: {claude_target}" in result.stderr


def test_generate_dry_run_lists_planned_writes_on_stderr_and_config_on_stdout(
    tmp_path: Path,
) -> None:
    config, claude_target = make_profile_config(tmp_path)

    result = runner.invoke(
        app, ["-c", str(config), "generate", "claude", "--write", "--dry-run"]
    )

    assert result.exit_code == 0, result.output
    assert f"Would write agent target: {claude_target}" in result.stderr
    assert "Would write" not in result.stdout
    assert '"permissions"' in result.stdout
    assert not claude_target.exists()


def test_generate_explicit_profile_changes_compiled_union(tmp_path: Path) -> None:
    config, _ = make_profile_config(tmp_path)

    result = runner.invoke(
        app,
        ["-c", str(config), "generate", "claude", "--profile", "work", "--write"],
    )

    assert result.exit_code == 0, result.output
    compiled = json.loads((tmp_path / "compiled/srt.json").read_text())
    assert compiled["filesystem"]["denyRead"] == ["~/.aws", "~/.ssh"]


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


def test_profiles_prints_a_table_with_one_column_per_source_kind(
    tmp_path: Path,
) -> None:
    config, _ = make_profile_config(tmp_path)

    result = runner.invoke(app, ["-c", str(config), "profiles"], env={"COLUMNS": "200"})

    assert result.exit_code == 0, result.output
    header = next(line for line in result.stdout.splitlines() if "┃" in line)
    # Body rows are the lines drawn with the light vertical bar.
    rows = [
        [cell.strip() for cell in line.split("│")[1:-1]]
        for line in result.stdout.splitlines()
        if line.startswith("│")
    ]
    # config.sources order, so srt precedes bash as in config.toml.
    assert [cell.strip() for cell in header.split("┃")[1:-1]] == [
        "Profile",
        "Extends",
        "srt",
        "bash",
    ]
    assert rows == [
        ["base *", "", "base", "base"],
        ["work", "base", "base, work", "base"],
    ]


def test_profiles_explains_the_default_marker(tmp_path: Path) -> None:
    config, _ = make_profile_config(tmp_path)

    result = runner.invoke(app, ["-c", str(config), "profiles"], env={"COLUMNS": "200"})

    assert result.exit_code == 0, result.output
    assert "* default profile" in result.stdout


def test_profiles_reports_an_unresolvable_profile_without_hiding_the_others(
    tmp_path: Path,
) -> None:
    config, _ = make_profile_config(tmp_path)
    # A mixin profile that selects no bash fragment cannot be used on its own.
    config.write_text(
        config.read_text().replace(
            "[targets]", '[profiles.mixin]\nsrt = ["work"]\n\n[targets]'
        )
    )

    result = runner.invoke(app, ["-c", str(config), "profiles"], env={"COLUMNS": "200"})

    assert result.exit_code == 0, result.output
    rows = [
        [cell.strip() for cell in line.split("│")[1:-1]]
        for line in result.stdout.splitlines()
        if line.startswith("│")
    ]
    assert rows[0] == ["base *", "", "base", "base"]
    assert rows[1][0] == "mixin"
    assert rows[1][2].startswith("invalid: ")
    assert "selects no fragments for source kind 'bash'" in rows[1][2]
    assert rows[2] == ["work", "base", "base, work", "base"]


def test_profiles_fails_on_a_broken_config(tmp_path: Path) -> None:
    config = tmp_path / "config.toml"
    config.write_text("schema_version = 99\n")

    result = runner.invoke(app, ["-c", str(config), "profiles"])

    assert result.exit_code == 1
    assert "schema_version" in result.stderr


def test_edit_opens_the_fragments_the_profile_inherits(tmp_path: Path) -> None:
    """`work` extends `base`, so editing it opens both srt fragments, in order."""
    config, _ = make_profile_config(tmp_path)
    fragments = tmp_path / "fragments"

    with patch("twsrt.bin.cli.subprocess.run") as run:
        run.return_value = MagicMock(returncode=0)
        result = runner.invoke(app, ["-c", str(config), "edit", "-p", "work", "-n"])

    assert result.exit_code == 0, result.output
    opened = [line for line in result.stdout.splitlines() if line.strip()]
    assert opened == [
        str(fragments / "srt-base.jsonc"),
        str(fragments / "srt-work.jsonc"),
        str(fragments / "bash-base.jsonc"),
    ]
    run.assert_not_called()


def test_edit_without_profile_opens_every_registered_fragment(tmp_path: Path) -> None:
    """default_profile `base` selects no srt-work fragment, yet it still opens."""
    config, _ = make_profile_config(tmp_path)
    fragments = tmp_path / "fragments"

    result = runner.invoke(app, ["-c", str(config), "edit", "-n"])

    assert result.exit_code == 0, result.output
    opened = [line for line in result.stdout.splitlines() if line.strip()]
    assert opened == [
        str(fragments / "srt-base.jsonc"),
        str(fragments / "srt-work.jsonc"),
        str(fragments / "bash-base.jsonc"),
    ]


def test_edit_without_profile_narrows_to_one_source_kind(tmp_path: Path) -> None:
    config, _ = make_profile_config(tmp_path)
    fragments = tmp_path / "fragments"

    result = runner.invoke(app, ["-c", str(config), "edit", "srt", "-n"])

    assert result.exit_code == 0, result.output
    opened = [line for line in result.stdout.splitlines() if line.strip()]
    assert opened == [
        str(fragments / "srt-base.jsonc"),
        str(fragments / "srt-work.jsonc"),
    ]


def test_edit_with_profile_opens_only_that_profiles_fragments(tmp_path: Path) -> None:
    """`base` selects no srt-work fragment."""
    config, _ = make_profile_config(tmp_path)

    result = runner.invoke(app, ["-c", str(config), "edit", "-p", "base", "-n"])

    assert result.exit_code == 0, result.output
    assert "srt-work.jsonc" not in result.stdout
    assert "srt-base.jsonc" in result.stdout


def test_show_prints_the_compiled_srt_document_and_writes_nothing(
    tmp_path: Path,
) -> None:
    config, claude_target = make_profile_config(tmp_path)

    result = runner.invoke(app, ["-c", str(config), "show", "srt"])

    assert result.exit_code == 0, result.output
    assert json.loads(result.stdout) == {
        "enabled": True,
        # denyRead implies denyWrite; the policy files are always write-denied
        # (see sources.compile_sources).
        "filesystem": {
            "denyRead": ["~/.ssh"],
            "denyWrite": sorted(["~/.ssh", *load_config(config).policy_files]),
        },
    }
    assert not (tmp_path / "compiled").exists()
    assert not claude_target.exists()


def test_show_defaults_to_the_srt_document(tmp_path: Path) -> None:
    config, _ = make_profile_config(tmp_path)

    result = runner.invoke(app, ["-c", str(config), "show"])

    assert result.exit_code == 0, result.output
    assert json.loads(result.stdout)["enabled"] is True


def test_show_bash_prints_the_compiled_bash_rules(tmp_path: Path) -> None:
    config, _ = make_profile_config(tmp_path)

    result = runner.invoke(app, ["-c", str(config), "show", "bash"])

    assert result.exit_code == 0, result.output
    assert json.loads(result.stdout)["deny"] == ["rm"]


def test_show_explicit_profile_prints_that_profiles_union(tmp_path: Path) -> None:
    config, _ = make_profile_config(tmp_path)

    result = runner.invoke(app, ["-c", str(config), "show", "srt", "-p", "work"])

    assert result.exit_code == 0, result.output
    shown = json.loads(result.stdout)
    assert shown["filesystem"]["denyRead"] == ["~/.aws", "~/.ssh"]


def test_show_prints_exactly_what_generate_write_would_write(tmp_path: Path) -> None:
    """show is the preview of the canonical file, byte for byte."""
    config, _ = make_profile_config(tmp_path)
    shown = runner.invoke(app, ["-c", str(config), "show", "srt", "-p", "work"])
    generated = runner.invoke(
        app, ["-c", str(config), "generate", "claude", "-p", "work", "--write"]
    )
    assert generated.exit_code == 0, generated.output

    assert shown.stdout == (tmp_path / "compiled/srt.json").read_text()


def test_show_unknown_kind_exits_1_and_names_the_available_kinds(
    tmp_path: Path,
) -> None:
    config, _ = make_profile_config(tmp_path)

    result = runner.invoke(app, ["-c", str(config), "show", "claude"])

    assert result.exit_code == 1
    assert "Unknown source kind 'claude'" in result.stderr
    assert "bash, srt" in result.stderr


def test_show_conflicting_fragments_exits_1(tmp_path: Path) -> None:
    config, _ = make_profile_config(tmp_path, conflicting=True)

    result = runner.invoke(app, ["-c", str(config), "show", "srt", "-p", "work"])

    assert result.exit_code == 1
    assert "conflict at /enabled" in result.stderr


def test_generate_yolo_write_leaves_the_canonical_srt_document_unchanged(
    tmp_path: Path,
) -> None:
    """Canonical config depends on the profile only; yolo overrides stay agent-side."""
    config, claude_target = make_profile_config(tmp_path)
    with config.open("a") as handle:
        handle.write("\n[sandbox_overrides.yolo]\nenabled = false\n")

    result = runner.invoke(
        app, ["-c", str(config), "generate", "claude", "--yolo", "--write"]
    )

    assert result.exit_code == 0, result.output
    yolo_target = claude_target.parent / "settings.yolo.json"
    assert json.loads(yolo_target.read_text())["sandbox"]["enabled"] is False
    assert json.loads((tmp_path / "compiled/srt.json").read_text()) == {
        "enabled": True,
        # denyRead implies denyWrite; the policy files are always write-denied
        # (see sources.compile_sources).
        "filesystem": {
            "denyRead": ["~/.ssh"],
            "denyWrite": sorted(["~/.ssh", *load_config(config).policy_files]),
        },
    }


@pytest.mark.parametrize(
    ("argv", "exit_code"),
    [
        (["generate", "claude"], 1),
        (["generate", "claude", "--write"], 1),
        (["show", "srt"], 1),
        (["diff", "claude"], 1),
        (["test"], 2),
    ],
)
def test_unreadable_fragment_is_a_clean_error_not_a_traceback(
    tmp_path: Path, argv: list[str], exit_code: int
) -> None:
    """A sandbox deny or chmod 000 on a fragment names the file and exits."""
    config, _ = make_profile_config(tmp_path)
    fragment = tmp_path / "fragments" / "srt-base.jsonc"
    fragment.chmod(0)
    try:
        result = runner.invoke(app, ["-c", str(config), *argv])
    finally:
        fragment.chmod(0o644)

    assert result.exit_code == exit_code, result.output
    assert not isinstance(result.exception, PermissionError)
    assert "Permission denied" in result.stderr
    assert str(fragment) in result.stderr


def test_edit_reports_unreadable_fragment_after_the_editor_closes(
    tmp_path: Path,
) -> None:
    """The post-edit compile must also fail cleanly, e.g. after a chmod."""
    config, _ = make_profile_config(tmp_path)
    fragment = tmp_path / "fragments" / "srt-base.jsonc"
    fragment.chmod(0)
    try:
        with patch("twsrt.bin.cli.subprocess.run") as run:
            run.return_value = MagicMock(returncode=0)
            result = runner.invoke(app, ["-c", str(config), "edit", "srt"])
    finally:
        fragment.chmod(0o644)

    assert result.exit_code == 1, result.output
    assert not isinstance(result.exception, PermissionError)
    assert str(fragment) in result.stderr
