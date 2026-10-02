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
    claude_target = tmp_path / "claude" / "settings.full.json"
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

[sandbox_overrides.yolo]
autoAllowBashIfSandboxed = true

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
    srt = json.loads((project / ".twsrt/srt-settings.json").read_text())
    assert srt["filesystem"]["denyRead"] == ["~/.ssh"]
    claude = json.loads((project / ".twsrt/claude-settings.json").read_text())
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
    claude = json.loads((project / ".twsrt/claude-settings.json").read_text())
    assert claude["model"] == "opus"
    assert claude["hooks"]["Stop"][0]["hooks"][0]["command"] == "notify"


def test_project_mode_never_touches_global_outputs_or_the_symlink(
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
    assert not (claude_target.parent / "settings.json").exists()
    assert not (tmp_path / "compiled/srt.json").exists()
    assert not (tmp_path / "compiled/bash.json").exists()


def test_project_twsrt_directory_is_write_protected_in_both_outputs(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # Claude hot-reloads --settings; an agent able to write .twsrt/ could
    # loosen its own policy.
    config, claude_target, project = make_config(tmp_path)
    monkeypatch.chdir(project)
    write_global_claude_settings(claude_target)
    protected = str((project / ".twsrt").resolve())

    result = runner.invoke(
        app,
        ["-c", str(config), "generate", "claude", "-w", "--project"],
    )

    assert result.exit_code == 0, result.output
    srt = json.loads((project / ".twsrt/srt-settings.json").read_text())
    assert protected in srt["filesystem"]["denyWrite"]
    claude = json.loads((project / ".twsrt/claude-settings.json").read_text())
    assert any(
        rule.startswith("Edit(") and protected in rule
        for rule in claude["permissions"]["deny"]
    )


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


def test_project_write_prints_only_the_twsrt_directory_on_stdout(
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
    assert result.stdout == f"{(project / '.twsrt').resolve()}\n"


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
    srt = json.loads((project / ".twsrt/srt-settings.json").read_text())
    assert srt["filesystem"]["denyRead"] == ["~/.kube", "~/.ssh"]


def test_project_yolo_uses_the_global_yolo_target_and_yolo_overrides(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    config, claude_target, project = make_config(tmp_path)
    monkeypatch.chdir(project)
    write_global_claude_settings(claude_target, model="opus-full")
    write_global_claude_settings(
        claude_target.parent / "settings.yolo.json", model="opus-yolo"
    )

    result = runner.invoke(
        app,
        [
            "-c",
            str(config),
            "generate",
            "claude",
            "-w",
            "--yolo",
            "--project",
        ],
    )

    assert result.exit_code == 0, result.output
    claude = json.loads((project / ".twsrt/claude-settings.yolo.json").read_text())
    assert claude["model"] == "opus-yolo"
    assert claude["sandbox"]["autoAllowBashIfSandboxed"] is True
    assert "ask" not in claude["permissions"] or claude["permissions"]["ask"] == []
    assert not (project / ".twsrt/claude-settings.json").exists()


def test_project_dry_run_writes_nothing(
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
            "-w",
            "-n",
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
    assert (project / ".twsrt/claude-settings.json").exists()


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
    assert (subdir / ".twsrt/claude-settings.json").exists()
    assert not (project / ".twsrt").exists()
