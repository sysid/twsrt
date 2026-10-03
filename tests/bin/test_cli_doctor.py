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
    lines = result.stdout.splitlines()
    assert lines[0].startswith("warning  subsumed-rule")
    assert "'~/.aws/sso'" in lines[0]
    assert lines[-1] == "doctor: 0 errors, 1 warning, 0 info"


def test_doctor_exits_one_when_any_profile_fails_to_compile(tmp_path: Path) -> None:
    config = write_config(tmp_path, '{"enabled": true}')

    result = runner.invoke(app, ["-c", str(config), "doctor"])

    assert result.exit_code == 1
    assert result.stdout.splitlines()[0].startswith("error    profile-compile")
    assert "profile 'off'" in result.stdout
    assert result.stdout.splitlines()[-1] == "doctor: 1 error, 0 warnings, 0 info"


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
