"""CLI tests for per-project policy: `generate --project` writes to $PWD/.twsrt."""

import json
from pathlib import Path

import pytest
from typer.testing import CliRunner

from twsrt.bin.cli import app

runner = CliRunner()


def make_config(tmp_path: Path) -> tuple[Path, Path, Path]:
    """Profile `default` carries a cloud-credentials deny; `slim` leaves it out.

    Returns (config.toml, global Claude target, project directory).
    """
    fragments = tmp_path / "fragments"
    fragments.mkdir()
    (fragments / "srt-base.jsonc").write_text(
        '{"enabled": true, "filesystem": {"denyRead": ["~/.ssh"], "allowWrite": ["."]}}'
    )
    (fragments / "srt-cloud.jsonc").write_text(
        '{"filesystem": {"denyRead": ["~/.kube"]}}'
    )
    (fragments / "bash-base.jsonc").write_text(
        '{"allow": [], "ask": ["git push"], "deny": ["rm"]}'
    )
    claude_target = tmp_path / "claude" / "settings.json"
    config = tmp_path / "config.toml"
    config.write_text(
        f"""schema_version = 1
default_profile = "default"

[sources.srt]
output = "compiled/srt.json"
[sources.srt.fragments.base]
path = "fragments/srt-base.jsonc"
[sources.srt.fragments.cloud]
path = "fragments/srt-cloud.jsonc"

[sources.bash]
output = "compiled/bash.json"
[sources.bash.fragments.base]
path = "fragments/bash-base.jsonc"

[profiles.default]
srt = ["base", "cloud"]
bash = ["base"]

[profiles.slim]
srt = ["base"]
bash = ["base"]

[targets]
claude_settings = "{claude_target}"
"""
    )
    project = tmp_path / "repo"
    project.mkdir()
    return config, claude_target, project


def write_global_claude_settings(claude_target: Path, **extra: object) -> None:
    """Simulate a prior `generate -w claude`: the global file holds user keys."""
    claude_target.parent.mkdir(parents=True, exist_ok=True)
    settings = {
        "model": "opus",
        "hooks": {"Stop": [{"hooks": [{"type": "command", "command": "notify"}]}]},
        "permissions": {"deny": ["Read(~/.kube)"], "ask": [], "allow": []},
        **extra,
    }
    claude_target.write_text(json.dumps(settings))


def test_project_profile_without_a_fragment_drops_its_rules_from_both_outputs(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    config, claude_target, project = make_config(tmp_path)
    monkeypatch.chdir(project)
    write_global_claude_settings(claude_target)

    result = runner.invoke(
        app,
        [
            "-c",
            str(config),
            "generate",
            "claude",
            "-w",
            "-p",
            "slim",
            "--project",
        ],
    )

    assert result.exit_code == 0, result.output
    srt = json.loads((project / ".twsrt/slim/srt-settings.json").read_text())
    assert srt["filesystem"]["denyRead"] == ["~/.ssh"]
    claude = json.loads((project / ".twsrt/slim/claude-settings.json").read_text())
    assert not any(".kube" in rule for rule in claude["permissions"]["deny"])
    assert any(".ssh" in rule for rule in claude["permissions"]["deny"])


def test_project_claude_file_carries_user_settings_from_the_global_target(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # The project file is launched with --setting-sources project,local, which
    # skips ~/.claude/settings.json, so hooks and model must travel along.
    config, claude_target, project = make_config(tmp_path)
    monkeypatch.chdir(project)
    write_global_claude_settings(claude_target)

    result = runner.invoke(
        app,
        [
            "-c",
            str(config),
            "generate",
            "claude",
            "-w",
            "-p",
            "slim",
            "--project",
        ],
    )

    assert result.exit_code == 0, result.output
    claude = json.loads((project / ".twsrt/slim/claude-settings.json").read_text())
    assert claude["model"] == "opus"
    assert claude["hooks"]["Stop"][0]["hooks"][0]["command"] == "notify"


def test_project_mode_never_touches_global_outputs(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    config, claude_target, project = make_config(tmp_path)
    monkeypatch.chdir(project)
    write_global_claude_settings(claude_target)
    global_before = claude_target.read_text()

    result = runner.invoke(
        app,
        [
            "-c",
            str(config),
            "generate",
            "claude",
            "-w",
            "-p",
            "slim",
            "--project",
        ],
    )

    assert result.exit_code == 0, result.output
    assert claude_target.read_text() == global_before
    assert not (tmp_path / "compiled/srt.json").exists()
    assert not (tmp_path / "compiled/bash.json").exists()


def test_project_twsrt_directory_is_write_protected_in_both_outputs(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # The whole directory, not only the profile's: an agent able to write any of
    # it could loosen the policy of the next launch.
    config, claude_target, project = make_config(tmp_path)
    monkeypatch.chdir(project)
    write_global_claude_settings(claude_target)
    protected = str((project / ".twsrt").resolve())

    result = runner.invoke(
        app,
        ["-c", str(config), "generate", "claude", "-w", "--project"],
    )

    assert result.exit_code == 0, result.output
    srt = json.loads((project / ".twsrt/default/srt-settings.json").read_text())
    assert protected in srt["filesystem"]["denyWrite"]
    claude = json.loads((project / ".twsrt/default/claude-settings.json").read_text())
    assert any(
        rule.startswith("Edit(") and protected in rule
        for rule in claude["permissions"]["deny"]
    )


def test_project_mode_write_protects_the_global_policy_files(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # --project reroutes the outputs into .twsrt/, but config.toml, the
    # fragments and the global outputs still feed every later global launch.
    config, claude_target, project = make_config(tmp_path)
    monkeypatch.chdir(project)
    write_global_claude_settings(claude_target)

    result = runner.invoke(
        app,
        ["-c", str(config), "generate", "claude", "-w", "--project"],
    )

    assert result.exit_code == 0, result.output
    srt = json.loads((project / ".twsrt/default/srt-settings.json").read_text())
    for path in ("config.toml", "compiled/srt.json", "fragments/srt-cloud.jsonc"):
        assert str(tmp_path / path) in srt["filesystem"]["denyWrite"]
    claude = json.loads((project / ".twsrt/default/claude-settings.json").read_text())
    assert f"Edit(/{tmp_path / 'config.toml'})" in claude["permissions"]["deny"]


def test_project_twsrt_directory_ignores_itself_in_git(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    config, claude_target, project = make_config(tmp_path)
    monkeypatch.chdir(project)
    write_global_claude_settings(claude_target)

    result = runner.invoke(
        app,
        ["-c", str(config), "generate", "claude", "-w", "--project"],
    )

    assert result.exit_code == 0, result.output
    assert (project / ".twsrt/.gitignore").read_text() == "*\n"


def test_project_write_prints_only_the_profiles_directory_on_stdout(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # Launchers capture stdout: d=$(twsrt generate claude -w --project)
    config, claude_target, project = make_config(tmp_path)
    monkeypatch.chdir(project)
    write_global_claude_settings(claude_target)

    result = runner.invoke(
        app,
        ["-c", str(config), "generate", "claude", "-w", "--project"],
    )

    assert result.exit_code == 0, result.output
    assert result.stdout == f"{(project / '.twsrt' / 'default').resolve()}\n"


def test_project_without_profile_uses_default_profile_and_keeps_every_rule(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    config, claude_target, project = make_config(tmp_path)
    monkeypatch.chdir(project)
    write_global_claude_settings(claude_target)

    result = runner.invoke(
        app,
        ["-c", str(config), "generate", "claude", "-w", "--project"],
    )

    assert result.exit_code == 0, result.output
    srt = json.loads((project / ".twsrt/default/srt-settings.json").read_text())
    assert srt["filesystem"]["denyRead"] == ["~/.kube", "~/.ssh"]


def test_project_preview_writes_nothing(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    config, claude_target, project = make_config(tmp_path)
    monkeypatch.chdir(project)
    write_global_claude_settings(claude_target)

    result = runner.invoke(
        app,
        [
            "-c",
            str(config),
            "generate",
            "claude",
            "--project",
        ],
    )

    assert result.exit_code == 0, result.output
    assert "Would write agent target:" in result.stderr
    assert str(project / ".twsrt") in result.stderr
    assert not (project / ".twsrt").exists()


def test_project_mode_rejects_agents_without_a_per_launch_settings_file(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    config, claude_target, project = make_config(tmp_path)
    monkeypatch.chdir(project)
    write_global_claude_settings(claude_target)

    for agent in ("codex", "copilot"):
        result = runner.invoke(
            app,
            ["-c", str(config), "generate", agent, "-w", "--project"],
        )

        assert result.exit_code == 1, agent
        assert "not supported with --project" in result.stderr
    assert not (project / ".twsrt").exists()


def test_project_all_agents_means_claude_only(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    config, claude_target, project = make_config(tmp_path)
    monkeypatch.chdir(project)
    write_global_claude_settings(claude_target)

    result = runner.invoke(app, ["-c", str(config), "generate", "-w", "--project"])

    assert result.exit_code == 0, result.output
    assert (project / ".twsrt/default/claude-settings.json").exists()


def test_project_requires_the_global_claude_target_as_base(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    config, claude_target, project = make_config(tmp_path)
    monkeypatch.chdir(project)

    result = runner.invoke(
        app,
        ["-c", str(config), "generate", "claude", "-w", "--project"],
    )

    assert result.exit_code == 1
    assert str(claude_target) in result.stderr
    assert "twsrt generate claude -w" in result.stderr
    assert not (project / ".twsrt").exists()


def test_project_flag_takes_no_value_so_a_following_agent_is_not_swallowed(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    config, claude_target, project = make_config(tmp_path)
    monkeypatch.chdir(project)
    write_global_claude_settings(claude_target)

    result = runner.invoke(
        app, ["-c", str(config), "generate", "--project", "codex", "-w"]
    )

    assert result.exit_code == 1
    assert "'codex' is not supported with --project" in result.stderr


def test_project_writes_into_the_current_directory_even_below_a_repo_root(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    config, claude_target, project = make_config(tmp_path)
    subdir = project / "sub"
    subdir.mkdir()
    monkeypatch.chdir(subdir)
    write_global_claude_settings(claude_target)

    result = runner.invoke(
        app, ["-c", str(config), "generate", "claude", "-w", "--project"]
    )

    assert result.exit_code == 0, result.output
    assert (subdir / ".twsrt/default/claude-settings.json").exists()
    assert not (project / ".twsrt").exists()


def test_project_claude_file_grants_writes_via_edit_rules_not_raw_sandbox_paths(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    # ADR 0002: in a --settings file a raw sandbox.filesystem "." would anchor
    # at .twsrt/ (the settings-file root); Edit(.) anchors at the launch cwd.
    config, claude_target, project = make_config(tmp_path)
    monkeypatch.chdir(project)
    write_global_claude_settings(claude_target)

    result = runner.invoke(
        app, ["-c", str(config), "generate", "claude", "-w", "--project"]
    )

    assert result.exit_code == 0, result.output
    claude = json.loads((project / ".twsrt/default/claude-settings.json").read_text())
    assert "Edit(.)" in claude["permissions"]["allow"]
    assert claude["sandbox"]["filesystem"]["allowWrite"] == []


def test_project_mode_without_a_bash_source_writes_no_bash_rules(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    config, claude_target, project = make_config(tmp_path)
    srt_only = (
        config.read_text()
        .replace(
            '[sources.bash]\noutput = "compiled/bash.json"\n'
            '[sources.bash.fragments.base]\npath = "fragments/bash-base.jsonc"\n',
            "",
        )
        .replace('bash = ["base"]\n', "")
    )
    config.write_text(srt_only)
    monkeypatch.chdir(project)
    write_global_claude_settings(claude_target)

    result = runner.invoke(
        app, ["-c", str(config), "generate", "claude", "-w", "--project"]
    )

    assert result.exit_code == 0, result.output
    assert (project / ".twsrt/default/srt-settings.json").exists()
    assert not (project / ".twsrt/default/bash-rules.json").exists()
    claude = json.loads((project / ".twsrt/default/claude-settings.json").read_text())
    assert not any(rule.startswith("Bash(") for rule in claude["permissions"]["deny"])


def test_sessions_with_different_profiles_in_one_directory_do_not_share_files(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    config, claude_target, project = make_config(tmp_path)
    monkeypatch.chdir(project)
    write_global_claude_settings(claude_target)
    for profile in ("slim", "default"):
        result = runner.invoke(
            app,
            ["-c", str(config), "generate", "claude", "-w", "-p", profile, "--project"],
        )
        assert result.exit_code == 0, result.output

    def denies_kube(profile: str) -> bool:
        path = project / ".twsrt" / profile / "claude-settings.json"
        return ".kube" in str(json.loads(path.read_text())["permissions"]["deny"])

    assert denies_kube("default")
    assert not denies_kube("slim")
    assert sorted(path.name for path in (project / ".twsrt").iterdir()) == [
        ".gitignore",
        "default",
        "slim",
    ]


@pytest.mark.parametrize("write", [[], ["-w"]])
@pytest.mark.parametrize(
    "name",
    [
        "claude-settings.json",
        "claude-settings.yolo.json",
        "srt-settings.json",
        "bash-rules.json",
    ],
)
def test_project_refuses_while_a_3x_policy_file_is_left_in_the_twsrt_directory(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, name: str, write: list[str]
) -> None:
    # A launcher using the 3.x path would keep loading that frozen policy.
    config, claude_target, project = make_config(tmp_path)
    monkeypatch.chdir(project)
    write_global_claude_settings(claude_target)
    stale = project / ".twsrt" / name
    stale.parent.mkdir()
    stale.write_text("{}")

    result = runner.invoke(
        app, ["-c", str(config), "generate", "claude", "--project", *write]
    )

    assert result.exit_code == 1
    assert result.stdout == ""
    assert str(stale.resolve()) in result.stderr
    assert "3.x" in result.stderr
    assert stale.read_text() == "{}"
    assert not (project / ".twsrt/default").exists()


def test_a_profile_named_like_a_3x_file_is_not_mistaken_for_one(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    config, claude_target, project = make_config(tmp_path)
    config.write_text(
        config.read_text().replace(
            "[targets]",
            '[profiles."srt-settings.json"]\nextends = ["slim"]\n\n[targets]',
        )
    )
    monkeypatch.chdir(project)
    write_global_claude_settings(claude_target)
    command = ["-c", str(config), "generate", "claude", "-w", "--project"]

    for _ in range(2):
        result = runner.invoke(app, [*command, "-p", "srt-settings.json"])
        assert result.exit_code == 0, result.output


@pytest.mark.parametrize("write", [[], ["-w"]])
@pytest.mark.parametrize("link", [".twsrt", ".twsrt/slim"])
def test_project_refuses_to_write_through_a_symlink(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, link: str, write: list[str]
) -> None:
    # A cloned repository could ship the link and redirect the policy files,
    # e.g. onto the global ones or into a directory the agent may write.
    config, claude_target, project = make_config(tmp_path)
    monkeypatch.chdir(project)
    write_global_claude_settings(claude_target)
    victim = tmp_path / "victim"
    victim.mkdir()
    (project / link).parent.mkdir(exist_ok=True)
    (project / link).symlink_to(victim, target_is_directory=True)

    result = runner.invoke(
        app,
        ["-c", str(config), "generate", "claude", "-p", "slim", "--project", *write],
    )

    assert result.exit_code == 1
    assert str(project.resolve() / link) in result.stderr
    assert "symlink" in result.stderr
    assert list(victim.iterdir()) == []


def test_project_refuses_a_dangling_symlink(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    config, claude_target, project = make_config(tmp_path)
    monkeypatch.chdir(project)
    write_global_claude_settings(claude_target)
    (project / ".twsrt").symlink_to(tmp_path / "missing")

    result = runner.invoke(
        app, ["-c", str(config), "generate", "claude", "-w", "--project"]
    )

    assert result.exit_code == 1
    assert "symlink" in result.stderr
    assert not (tmp_path / "missing").exists()
