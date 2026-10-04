"""CLI tests for `twsrt doctor`."""

from pathlib import Path

import pytest
from typer.testing import CliRunner

from twsrt.bin.cli import app

runner = CliRunner()


@pytest.fixture(autouse=True)
def isolated_home(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    """doctor inspects paths on disk (symlinks, home roots): never the host's."""
    home = tmp_path / "isolated-home"
    home.mkdir()
    monkeypatch.setenv("HOME", str(home))
    return home


def write_config(tmp_path: Path, srt_base: str, extra_profiles: str = "") -> Path:
    (tmp_path / "base.jsonc").write_text(srt_base)
    (tmp_path / "off.jsonc").write_text('{"enabled": false}')
    (tmp_path / "bash.jsonc").write_text('{"allow": [], "ask": [], "deny": ["rm"]}')
    config = tmp_path / "config.toml"
    config.write_text(
        """schema_version = 1
default_profile = "default"

[sources.srt]
output = "out/srt.json"
[sources.srt.fragments.base]
path = "base.jsonc"
[sources.srt.fragments.off]
path = "off.jsonc"

[sources.bash]
output = "out/bash.json"
[sources.bash.fragments.base]
path = "bash.jsonc"

[profiles.default]
srt = ["base"]
bash = ["base"]

[profiles.off]
extends = ["default"]
srt = ["off"]
"""
        + extra_profiles
    )
    return config


def test_doctor_with_only_warnings_exits_zero_and_lists_them_on_stdout(
    tmp_path: Path,
) -> None:
    config = write_config(
        tmp_path,
        '{"enabled": true, "filesystem": {"denyRead": ["~/.aws", "~/.aws/sso"]}}',
    )
    # Make profile `off` compile cleanly: no scalar conflict.
    (tmp_path / "off.jsonc").write_text("{}")

    result = runner.invoke(app, ["-c", str(config), "doctor"])

    assert result.exit_code == 0, result.output
    # Grouped under the file to fix; each affected entry on its own line,
    # aligned under the message.
    assert result.stdout == (
        "base.jsonc\n"
        "  warning  subsumed-rule  filesystem.denyRead: 1 entry already covered\n"
        "                          • '~/.aws/sso' by '~/.aws'\n"
        "\n"
        "doctor: 0 errors, 1 warning, 0 info\n"
    )


def test_doctor_exits_one_when_any_profile_fails_to_compile(tmp_path: Path) -> None:
    config = write_config(tmp_path, '{"enabled": true}')

    result = runner.invoke(app, ["-c", str(config), "doctor"])

    assert result.exit_code == 1
    lines = result.stdout.splitlines()
    assert lines[0] == "profile 'off'"
    assert lines[1].startswith("  error    profile-compile  ")
    assert lines[-1] == "doctor: 1 error, 0 warnings, 0 info"


def test_doctor_colors_findings_on_a_color_terminal(tmp_path: Path) -> None:
    """Control for the NO_COLOR test below: FORCE_COLOR does produce ANSI."""
    config = write_config(tmp_path, ALL_SEVERITIES)

    result = runner.invoke(app, ["-c", str(config), "doctor"], env={"FORCE_COLOR": "1"})

    assert "\x1b[" in result.stdout


def test_doctor_empty_no_color_disables_ansi_like_every_other_command(
    tmp_path: Path,
) -> None:
    """NO_COLOR counts when set at all, even empty (doc/REFERENCE.md);
    rich alone would only honour a non-empty value."""
    config = write_config(tmp_path, ALL_SEVERITIES)

    result = runner.invoke(
        app, ["-c", str(config), "doctor"], env={"FORCE_COLOR": "1", "NO_COLOR": ""}
    )

    assert "\x1b[" not in result.stdout


def test_doctor_on_a_clean_configuration_says_so(tmp_path: Path) -> None:
    config = write_config(tmp_path, '{"enabled": true}')
    (tmp_path / "off.jsonc").write_text("{}")

    result = runner.invoke(app, ["-c", str(config), "doctor"])

    assert result.exit_code == 0, result.output
    assert result.stdout == "doctor: no findings\n"


def test_doctor_reports_an_unloadable_config_as_an_error(tmp_path: Path) -> None:
    config = tmp_path / "config.toml"
    config.write_text("schema_version = 99\n")

    result = runner.invoke(app, ["-c", str(config), "doctor"])

    assert result.exit_code == 1
    assert "schema_version" in result.stderr


def test_doctor_scans_the_repo_claude_settings_for_relative_sandbox_paths(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    config = write_config(tmp_path, '{"enabled": true}')
    (tmp_path / "off.jsonc").write_text("{}")
    repo = tmp_path / "repo"
    (repo / ".claude").mkdir(parents=True)
    (repo / ".claude" / "settings.local.json").write_text(
        '{"sandbox": {"filesystem": {"allowWrite": ["./build"]}}}'
    )
    monkeypatch.chdir(repo)

    result = runner.invoke(app, ["-c", str(config), "doctor"])

    assert result.exit_code == 0, result.output
    assert "claude-relative-sandbox-path" in result.stdout
    assert "'./build'" in result.stdout


# One finding per severity: profile `off` conflicts with `enabled: true`
# (error), ~/.aws/sso sits below ~/.aws (warning), ~/x/** is a no-op suffix
# (info).
ALL_SEVERITIES = (
    '{"enabled": true, "filesystem": {"denyRead": ["~/.aws", "~/.aws/sso"], '
    '"allowWrite": ["~/x/**"]}}'
)


def severities(stdout: str) -> list[str]:
    """Severity column of every finding line.

    Finding lines are indented two spaces; location headers are not indented,
    item lines are indented further, and the summary line is excluded.
    """
    return [
        line.split()[0]
        for line in stdout.splitlines()
        if line.startswith("  ") and not line.startswith("   ")
    ]


def test_doctor_without_a_level_option_hides_info_but_still_counts_it(
    tmp_path: Path,
) -> None:
    config = write_config(tmp_path, ALL_SEVERITIES)

    result = runner.invoke(app, ["-c", str(config), "doctor"])

    assert result.exit_code == 1
    assert severities(result.stdout) == ["error", "warning"]
    assert result.stdout.splitlines()[-1] == "doctor: 1 error, 1 warning, 1 info"


def test_doctor_all_shows_every_level(tmp_path: Path) -> None:
    config = write_config(tmp_path, ALL_SEVERITIES)

    result = runner.invoke(app, ["-c", str(config), "doctor", "--all"])

    assert severities(result.stdout) == ["error", "warning", "info"]


def test_doctor_groups_findings_by_location_most_severe_location_first(
    tmp_path: Path,
) -> None:
    config = write_config(tmp_path, ALL_SEVERITIES)

    result = runner.invoke(app, ["-c", str(config), "doctor", "--all"])

    headers = [line for line in result.stdout.splitlines() if line and line[0] != " "][
        :-1
    ]
    # The error sits in profile 'off'; base.jsonc holds the warning and the
    # info, listed once under a single header.
    assert headers == ["profile 'off'", "base.jsonc"]


@pytest.mark.parametrize(
    ("options", "shown"),
    [
        (["--error"], ["error"]),
        (["--warn"], ["warning"]),
        (["--info"], ["info"]),
        (["--error", "--info"], ["error", "info"]),
    ],
)
def test_doctor_level_options_show_exactly_those_levels(
    tmp_path: Path, options: list[str], shown: list[str]
) -> None:
    config = write_config(tmp_path, ALL_SEVERITIES)

    result = runner.invoke(app, ["-c", str(config), "doctor", *options])

    assert severities(result.stdout) == shown


def test_doctor_exits_one_on_errors_even_when_they_are_not_shown(
    tmp_path: Path,
) -> None:
    config = write_config(tmp_path, ALL_SEVERITIES)

    result = runner.invoke(app, ["-c", str(config), "doctor", "--info"])

    assert result.exit_code == 1
    assert "error" not in severities(result.stdout)


def test_doctor_with_only_hidden_info_prints_just_the_summary(tmp_path: Path) -> None:
    config = write_config(
        tmp_path, '{"enabled": true, "filesystem": {"allowWrite": ["~/x/**"]}}'
    )
    (tmp_path / "off.jsonc").write_text("{}")

    result = runner.invoke(app, ["-c", str(config), "doctor"])

    assert result.exit_code == 0, result.output
    assert result.stdout == "doctor: 0 errors, 0 warnings, 1 info\n"
