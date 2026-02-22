"""Tests for CLI commands: init, version, generate, edit."""

import json
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest
from typer.testing import CliRunner

from twsrt.bin.cli import __version__, _resolve_editor, app

runner = CliRunner()


class TestVersion:
    def test_version_flag(self) -> None:
        result = runner.invoke(app, ["-V"])
        assert result.exit_code == 0
        assert __version__ in result.output

    def test_version_command(self) -> None:
        result = runner.invoke(app, ["version"])
        assert result.exit_code == 0
        assert __version__ in result.output


class TestBareInvocation:
    def test_no_args_shows_help(self) -> None:
        result = runner.invoke(app, [])
        # typer exits 2 for no_args_is_help, but help text is shown
        assert "Usage" in result.output
        assert "init" in result.output


class TestInit:
    def test_init_creates_dir_and_files(self, tmp_path: Path) -> None:
        twsrt_dir = tmp_path / "config" / "twsrt"
        result = runner.invoke(app, ["init", "--dir", str(twsrt_dir)])
        assert result.exit_code == 0
        assert twsrt_dir.exists()
        assert (twsrt_dir / "config.toml").exists()
        assert (twsrt_dir / "bash-rules.json").exists()

    def test_init_existing_files_skips_with_warning(self, tmp_path: Path) -> None:
        twsrt_dir = tmp_path / "config" / "twsrt"
        twsrt_dir.mkdir(parents=True)
        (twsrt_dir / "config.toml").write_text("existing")
        (twsrt_dir / "bash-rules.json").write_text("existing")

        result = runner.invoke(app, ["init", "--dir", str(twsrt_dir)])
        assert result.exit_code == 0
        assert "skip" in result.output.lower() or "exists" in result.output.lower()
        # Should NOT overwrite
        assert (twsrt_dir / "config.toml").read_text() == "existing"

    def test_init_force_overwrites(self, tmp_path: Path) -> None:
        twsrt_dir = tmp_path / "config" / "twsrt"
        twsrt_dir.mkdir(parents=True)
        (twsrt_dir / "config.toml").write_text("old")
        (twsrt_dir / "bash-rules.json").write_text("old")

        result = runner.invoke(app, ["init", "--force", "--dir", str(twsrt_dir)])
        assert result.exit_code == 0
        # Should overwrite with defaults
        assert (twsrt_dir / "config.toml").read_text() != "old"


class TestGenerate:
    def test_generate_claude_prints_to_stdout(
        self, srt_file: Path, bash_rules_file: Path, config_toml_file: Path
    ) -> None:
        result = runner.invoke(app, ["-c", str(config_toml_file), "generate", "claude"])
        assert result.exit_code == 0, result.output
        output = json.loads(result.output)
        assert "permissions" in output
        assert "deny" in output["permissions"]

    def test_generate_claude_write_mode(
        self,
        srt_file: Path,
        bash_rules_file: Path,
        config_toml_file: Path,
        claude_settings_file: Path,
        tmp_path: Path,
    ) -> None:
        result = runner.invoke(
            app, ["-c", str(config_toml_file), "generate", "claude", "--write"]
        )
        assert result.exit_code == 0, result.output
        # Verify file was written
        written = json.loads(claude_settings_file.read_text())
        assert "permissions" in written

    def test_generate_claude_dry_run(
        self, srt_file: Path, bash_rules_file: Path, config_toml_file: Path
    ) -> None:
        result = runner.invoke(
            app,
            ["-c", str(config_toml_file), "generate", "claude", "--dry-run", "--write"],
        )
        assert result.exit_code == 0, result.output
        assert "dry run" in result.output.lower() or "would" in result.output.lower()

    def test_generate_all_agents(
        self, srt_file: Path, bash_rules_file: Path, config_toml_file: Path
    ) -> None:
        result = runner.invoke(app, ["-c", str(config_toml_file), "generate"])
        assert result.exit_code == 0, result.output
        # Should produce valid output (JSON for claude at minimum)
        assert "permissions" in result.output

    def test_generate_missing_source_exits_1(self, tmp_path: Path) -> None:
        config = tmp_path / "config.toml"
        config.write_text(
            '[sources]\nsrt = "/nonexistent/srt.json"\n'
            'bash_rules = "/nonexistent/bash.json"\n'
        )
        result = runner.invoke(app, ["-c", str(config), "generate", "claude"])
        assert result.exit_code == 1

    def test_generate_with_custom_config(
        self, srt_file: Path, bash_rules_file: Path, config_toml_file: Path
    ) -> None:
        result = runner.invoke(app, ["-c", str(config_toml_file), "generate", "claude"])
        assert result.exit_code == 0


# --- US1 Acceptance Scenario Integration Tests ---


def _make_config(tmp_path: Path, srt: dict, bash_rules: dict | None = None) -> Path:
    """Helper: write SRT + bash_rules + config.toml, return config path."""
    srt_file = tmp_path / "srt.json"
    srt_file.write_text(json.dumps(srt))

    twsrt_dir = tmp_path / "config" / "twsrt"
    twsrt_dir.mkdir(parents=True)
    br_file = twsrt_dir / "bash-rules.json"
    br_file.write_text(json.dumps(bash_rules or {"deny": [], "ask": []}))

    config = twsrt_dir / "config.toml"
    config.write_text(f'[sources]\nsrt = "{srt_file}"\nbash_rules = "{br_file}"\n')
    return config


class TestUS1AcceptanceScenarios:
    """All 7 acceptance scenarios from spec.md US1."""

    def test_scenario_1_deny_read_all_file_tools(self, tmp_path: Path) -> None:
        """denyRead generates deny for ALL file tools."""
        srt = {
            "sandbox": {
                "permissions": {
                    "filesystem": {
                        "read": {"denyOnly": ["~/.aws", "~/.ssh"]},
                    }
                }
            }
        }
        config = _make_config(tmp_path, srt)
        result = runner.invoke(app, ["-c", str(config), "generate", "claude"])
        assert result.exit_code == 0
        output = json.loads(result.output)
        deny = output["permissions"]["deny"]
        for path in ["~/.aws", "~/.ssh"]:
            assert f"Read({path})" in deny
            assert f"Read({path}/**)" in deny
            assert f"Write({path})" in deny
            assert f"Write({path}/**)" in deny
            assert f"Edit({path})" in deny
            assert f"Edit({path}/**)" in deny
            assert f"MultiEdit({path})" in deny
            assert f"MultiEdit({path}/**)" in deny

    def test_scenario_2_allow_write_no_output(self, tmp_path: Path) -> None:
        """allowWrite produces no Claude output."""
        srt = {
            "sandbox": {
                "permissions": {
                    "filesystem": {
                        "write": {"allowOnly": [".", "/tmp"]},
                    }
                }
            }
        }
        config = _make_config(tmp_path, srt)
        result = runner.invoke(app, ["-c", str(config), "generate", "claude"])
        assert result.exit_code == 0
        output = json.loads(result.output)
        assert output["permissions"]["deny"] == []
        assert output["permissions"]["allow"] == []

    def test_scenario_3_allowed_domains(self, tmp_path: Path) -> None:
        """allowedDomains → WebFetch allow + sandbox.network."""
        srt = {
            "sandbox": {
                "permissions": {
                    "network": {
                        "allowedHosts": ["github.com", "*.github.com"],
                    }
                }
            }
        }
        config = _make_config(tmp_path, srt)
        result = runner.invoke(app, ["-c", str(config), "generate", "claude"])
        assert result.exit_code == 0
        output = json.loads(result.output)
        allow = output["permissions"]["allow"]
        assert "WebFetch(domain:github.com)" in allow
        assert "WebFetch(domain:*.github.com)" in allow
        domains = output["sandbox"]["network"]["allowedDomains"]
        assert "github.com" in domains
        assert "*.github.com" in domains

    def test_scenario_4_bash_deny(self, tmp_path: Path) -> None:
        """Bash deny → Bash(cmd) + Bash(cmd *) in deny."""
        srt = {"sandbox": {"permissions": {}}}
        bash_rules = {"deny": ["rm", "sudo", "git push --force"], "ask": []}
        config = _make_config(tmp_path, srt, bash_rules)
        result = runner.invoke(app, ["-c", str(config), "generate", "claude"])
        assert result.exit_code == 0
        output = json.loads(result.output)
        deny = output["permissions"]["deny"]
        assert "Bash(rm)" in deny
        assert "Bash(rm *)" in deny
        assert "Bash(sudo)" in deny
        assert "Bash(sudo *)" in deny
        assert "Bash(git push --force)" in deny
        assert "Bash(git push --force *)" in deny

    def test_scenario_5_bash_ask(self, tmp_path: Path) -> None:
        """Bash ask → Bash(cmd) + Bash(cmd *) in ask."""
        srt = {"sandbox": {"permissions": {}}}
        bash_rules = {"deny": [], "ask": ["git push", "git commit", "pip install"]}
        config = _make_config(tmp_path, srt, bash_rules)
        result = runner.invoke(app, ["-c", str(config), "generate", "claude"])
        assert result.exit_code == 0
        output = json.loads(result.output)
        ask = output["permissions"]["ask"]
        assert "Bash(git push)" in ask
        assert "Bash(git push *)" in ask
        assert "Bash(git commit)" in ask
        assert "Bash(git commit *)" in ask
        assert "Bash(pip install)" in ask
        assert "Bash(pip install *)" in ask

    def test_scenario_6_deny_write(self, tmp_path: Path) -> None:
        """denyWrite → Write/Edit/MultiEdit in deny (no Read)."""
        srt = {
            "sandbox": {
                "permissions": {
                    "filesystem": {
                        "write": {"denyWithinAllow": ["**/.env", "**/*.pem"]},
                    }
                }
            }
        }
        config = _make_config(tmp_path, srt)
        result = runner.invoke(app, ["-c", str(config), "generate", "claude"])
        assert result.exit_code == 0
        output = json.loads(result.output)
        deny = output["permissions"]["deny"]
        assert "Write(**/.env)" in deny
        assert "Edit(**/.env)" in deny
        assert "Write(**/*.pem)" in deny
        assert "Edit(**/*.pem)" in deny

    def test_scenario_7_selective_merge(self, tmp_path: Path) -> None:
        """Selective merge preserves hooks, mcp__, blanket allows."""
        srt = {
            "sandbox": {
                "permissions": {
                    "filesystem": {
                        "read": {"denyOnly": ["**/.secret"]},
                    },
                    "network": {"allowedHosts": ["github.com"]},
                }
            }
        }
        bash_rules = {"deny": ["rm"], "ask": ["git push"]}
        config = _make_config(tmp_path, srt, bash_rules)

        # Create existing settings.json with hooks, mcp, blanket allows
        settings_path = tmp_path / ".claude" / "settings.json"
        settings_path.parent.mkdir(parents=True)
        existing = {
            "permissions": {
                "allow": [
                    "Read",
                    "Glob",
                    "Grep",
                    "LS",
                    "Task",
                    "WebSearch",
                    "mcp__memory__store",
                    "WebFetch(domain:old.com)",
                    "Bash(./gradlew:*)",
                ],
                "deny": ["Bash(old:*)"],
                "ask": ["Bash(old)"],
            },
            "hooks": {"PreToolUse": [{"matcher": "Bash"}]},
            "additionalDirectories": ["/tmp"],
        }
        settings_path.write_text(json.dumps(existing))

        # Update config to include claude_settings target
        config_content = config.read_text()
        config.write_text(
            config_content + f'\n[targets]\nclaude_settings = "{settings_path}"\n'
        )

        result = runner.invoke(
            app, ["-c", str(config), "generate", "claude", "--write"]
        )
        assert result.exit_code == 0

        merged = json.loads(settings_path.read_text())
        # deny/ask fully replaced
        assert "Bash(old:*)" not in merged["permissions"]["deny"]
        assert "Bash(rm)" in merged["permissions"]["deny"]
        assert "Bash(rm *)" in merged["permissions"]["deny"]
        assert "Bash(old)" not in merged["permissions"]["ask"]
        assert "Bash(git push)" in merged["permissions"]["ask"]
        # allow: blanket and mcp preserved, WebFetch replaced
        allow = merged["permissions"]["allow"]
        assert "Read" in allow
        assert "Glob" in allow
        assert "mcp__memory__store" in allow
        assert "Bash(./gradlew:*)" in allow
        assert "WebFetch(domain:old.com)" not in allow
        assert "WebFetch(domain:github.com)" in allow
        # hooks preserved
        assert merged["hooks"] == {"PreToolUse": [{"matcher": "Bash"}]}
        # additionalDirectories preserved
        assert merged["additionalDirectories"] == ["/tmp"]
        # sandbox.network replaced
        assert "github.com" in merged["sandbox"]["network"]["allowedDomains"]


# --- US2 Acceptance Scenario Integration Tests ---


class TestUS2AcceptanceScenarios:
    """Acceptance scenarios from spec.md US2 (Copilot CLI)."""

    def test_copilot_deny_flags(self, tmp_path: Path) -> None:
        """Bash deny → --deny-tool flags."""
        srt = {"sandbox": {"permissions": {}}}
        bash_rules = {"deny": ["rm", "sudo"], "ask": []}
        config = _make_config(tmp_path, srt, bash_rules)
        result = runner.invoke(app, ["-c", str(config), "generate", "copilot"])
        assert result.exit_code == 0
        assert "--deny-tool 'shell(rm)'" in result.output
        assert "--deny-tool 'shell(sudo)'" in result.output

    def test_copilot_lossy_ask_warning(self, tmp_path: Path) -> None:
        """Bash ask → --deny-tool with warning on stderr."""
        srt = {"sandbox": {"permissions": {}}}
        bash_rules = {"deny": [], "ask": ["git push"]}
        config = _make_config(tmp_path, srt, bash_rules)
        result = runner.invoke(app, ["-c", str(config), "generate", "copilot"])
        assert result.exit_code == 0
        assert "--deny-tool 'shell(git push)'" in result.output

    def test_generate_all_includes_both_agents(self, tmp_path: Path) -> None:
        """twsrt generate (all) includes both Claude and Copilot output."""
        srt = {
            "sandbox": {
                "permissions": {
                    "network": {
                        "allowedHosts": ["github.com"],
                    }
                }
            }
        }
        bash_rules = {"deny": ["rm"], "ask": []}
        config = _make_config(tmp_path, srt, bash_rules)
        result = runner.invoke(app, ["-c", str(config), "generate"])
        assert result.exit_code == 0
        # Should show headers for both agents
        assert "--- claude ---" in result.output
        assert "--- copilot ---" in result.output


# --- Diff Command Tests ---


def _make_config_with_targets(
    tmp_path: Path,
    srt: dict,
    bash_rules: dict | None = None,
) -> tuple[Path, Path, Path]:
    """Helper: write SRT + bash_rules + config + targets, return (config, claude_target, copilot_target)."""
    srt_file = tmp_path / "srt.json"
    srt_file.write_text(json.dumps(srt))

    twsrt_dir = tmp_path / "config" / "twsrt"
    twsrt_dir.mkdir(parents=True)
    br_file = twsrt_dir / "bash-rules.json"
    br_file.write_text(json.dumps(bash_rules or {"deny": [], "ask": []}))

    claude_target = tmp_path / ".claude" / "settings.json"
    claude_target.parent.mkdir(parents=True)

    copilot_target = tmp_path / "copilot-flags.txt"

    config_file = twsrt_dir / "config.toml"
    config_file.write_text(
        f'[sources]\nsrt = "{srt_file}"\nbash_rules = "{br_file}"\n'
        f'[targets]\nclaude_settings = "{claude_target}"\n'
        f'copilot_output = "{copilot_target}"\n'
    )
    return config_file, claude_target, copilot_target


class TestDiffCommand:
    def test_diff_claude_with_drift_exits_1(self, tmp_path: Path) -> None:
        srt = {
            "sandbox": {
                "permissions": {
                    "filesystem": {
                        "read": {"denyOnly": ["**/.aws", "**/.kube"]},
                    }
                }
            }
        }
        config, claude_target, _ = _make_config_with_targets(tmp_path, srt)
        # Write existing with only .aws rules (missing .kube)
        existing = {
            "permissions": {
                "deny": [
                    "Read(**/.aws/**)",
                    "Write(**/.aws/**)",
                    "Edit(**/.aws/**)",
                    "MultiEdit(**/.aws/**)",
                ],
                "ask": [],
                "allow": [],
            },
            "sandbox": {"network": {"allowedDomains": []}},
        }
        claude_target.write_text(json.dumps(existing))

        result = runner.invoke(app, ["-c", str(config), "diff", "claude"])
        assert result.exit_code == 1
        assert "missing" in result.output.lower() or ".kube" in result.output

    def test_diff_no_drift_exits_0(self, tmp_path: Path) -> None:
        srt = {"sandbox": {"permissions": {}}}
        bash_rules = {"deny": ["rm"], "ask": []}
        config, claude_target, _ = _make_config_with_targets(tmp_path, srt, bash_rules)
        # Write existing that matches
        existing = {
            "permissions": {
                "deny": ["Bash(rm)", "Bash(rm *)"],
                "ask": [],
                "allow": [],
            },
            "sandbox": {"network": {"allowedDomains": []}},
        }
        claude_target.write_text(json.dumps(existing))

        result = runner.invoke(app, ["-c", str(config), "diff", "claude"])
        assert result.exit_code == 0

    def test_diff_missing_target_exits_2(self, tmp_path: Path) -> None:
        srt = {"sandbox": {"permissions": {}}}
        config, claude_target, _ = _make_config_with_targets(tmp_path, srt)
        # Don't create claude_target file

        result = runner.invoke(app, ["-c", str(config), "diff", "claude"])
        assert result.exit_code == 2


# --- US3 Acceptance Scenario Integration Tests ---


class TestUS3AcceptanceScenarios:
    def test_drift_detected_with_missing_and_extra(self, tmp_path: Path) -> None:
        """Place a known-drifted settings.json, verify specific missing/extra."""
        srt = {
            "sandbox": {
                "permissions": {
                    "filesystem": {
                        "read": {"denyOnly": ["**/.aws", "**/.kube"]},
                    }
                }
            }
        }
        bash_rules = {"deny": ["rm"], "ask": []}
        config, claude_target, _ = _make_config_with_targets(tmp_path, srt, bash_rules)
        # Existing has .aws + docker but NOT .kube
        existing = {
            "permissions": {
                "deny": [
                    "Read(**/.aws/**)",
                    "Write(**/.aws/**)",
                    "Edit(**/.aws/**)",
                    "MultiEdit(**/.aws/**)",
                    "Bash(rm)",
                    "Bash(rm *)",
                    "Bash(docker run:*)",
                ],
                "ask": [],
                "allow": [],
            },
            "sandbox": {"network": {"allowedDomains": []}},
        }
        claude_target.write_text(json.dumps(existing))

        result = runner.invoke(app, ["-c", str(config), "diff", "claude"])
        assert result.exit_code == 1
        # .kube should be missing, docker should be extra
        assert ".kube" in result.output
        assert "docker" in result.output

    def test_no_drift_reports_clean(self, tmp_path: Path) -> None:
        srt = {"sandbox": {"permissions": {}}}
        bash_rules = {"deny": ["rm"], "ask": []}
        config, claude_target, _ = _make_config_with_targets(tmp_path, srt, bash_rules)
        existing = {
            "permissions": {
                "deny": ["Bash(rm)", "Bash(rm *)"],
                "ask": [],
                "allow": [],
            },
            "sandbox": {"network": {"allowedDomains": []}},
        }
        claude_target.write_text(json.dumps(existing))

        result = runner.invoke(app, ["-c", str(config), "diff", "claude"])
        assert result.exit_code == 0
        assert "no drift" in result.output.lower()

    def test_missing_target_file_exits_2(self, tmp_path: Path) -> None:
        srt = {"sandbox": {"permissions": {}}}
        config, _, copilot_target = _make_config_with_targets(tmp_path, srt)
        # Don't create copilot_target

        result = runner.invoke(app, ["-c", str(config), "diff", "copilot"])
        assert result.exit_code == 2


# --- Edit Command Tests (002-add-srt-domain) ---


class TestResolveEditor:
    """T001: _resolve_editor() returns $EDITOR, falls back to $VISUAL, then vi."""

    def test_returns_editor_env(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("EDITOR", "nvim")
        assert _resolve_editor() == "nvim"

    def test_falls_back_to_visual(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.delenv("EDITOR", raising=False)
        monkeypatch.setenv("VISUAL", "code")
        assert _resolve_editor() == "code"

    def test_falls_back_to_vi(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.delenv("EDITOR", raising=False)
        monkeypatch.delenv("VISUAL", raising=False)
        assert _resolve_editor() == "vi"


def _make_edit_config(tmp_path: Path) -> tuple[Path, Path, Path]:
    """Helper: create SRT + bash-rules files and config, return (config, srt_file, bash_file)."""
    srt_file = tmp_path / "srt.json"
    srt_file.write_text("{}")

    bash_file = tmp_path / "bash-rules.json"
    bash_file.write_text('{"deny": [], "ask": []}')

    config = tmp_path / "config.toml"
    config.write_text(
        f'[sources]\nsrt = "{srt_file}"\nbash_rules = "{bash_file}"\n'
    )
    return config, srt_file, bash_file


class TestEditSrt:
    """T002-T004: twsrt edit srt — happy path, missing file, editor failure."""

    def test_edit_srt_calls_editor_with_srt_path(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """T002: edit srt opens file in $EDITOR."""
        config, srt_file, _ = _make_edit_config(tmp_path)
        monkeypatch.setenv("EDITOR", "test-editor")

        with patch("twsrt.bin.cli.subprocess") as mock_sub:
            mock_sub.run.return_value = MagicMock(returncode=0)
            result = runner.invoke(app, ["-c", str(config), "edit", "srt"])

        assert result.exit_code == 0
        mock_sub.run.assert_called_once_with(["test-editor", str(srt_file)])

    def test_edit_srt_missing_file_exits_1(self, tmp_path: Path) -> None:
        """T003: edit srt with nonexistent file reports error with path."""
        config = tmp_path / "config.toml"
        nonexistent = tmp_path / "nonexistent.json"
        config.write_text(
            f'[sources]\nsrt = "{nonexistent}"\n'
            f'bash_rules = "/dummy"\n'
        )

        result = runner.invoke(app, ["-c", str(config), "edit", "srt"])
        assert result.exit_code == 1
        assert str(nonexistent) in result.output

    def test_edit_srt_editor_nonzero_exit(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """T004: editor exits non-zero — warning and matching exit code."""
        config, srt_file, _ = _make_edit_config(tmp_path)
        monkeypatch.setenv("EDITOR", "failing-editor")

        with patch("twsrt.bin.cli.subprocess") as mock_sub:
            mock_sub.run.return_value = MagicMock(returncode=2)
            result = runner.invoke(app, ["-c", str(config), "edit", "srt"])

        assert result.exit_code == 2


class TestEditBash:
    """T008-T009: twsrt edit bash — happy path and missing file."""

    def test_edit_bash_calls_editor_with_bash_path(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """T008: edit bash opens file in editor."""
        config, _, bash_file = _make_edit_config(tmp_path)
        monkeypatch.setenv("EDITOR", "test-editor")

        with patch("twsrt.bin.cli.subprocess") as mock_sub:
            mock_sub.run.return_value = MagicMock(returncode=0)
            result = runner.invoke(app, ["-c", str(config), "edit", "bash"])

        assert result.exit_code == 0
        mock_sub.run.assert_called_once_with(["test-editor", str(bash_file)])

    def test_edit_bash_missing_file_exits_1(self, tmp_path: Path) -> None:
        """T009: edit bash with nonexistent file reports error."""
        config = tmp_path / "config.toml"
        nonexistent = tmp_path / "nonexistent.json"
        config.write_text(
            f'[sources]\nsrt = "/dummy"\n'
            f'bash_rules = "{nonexistent}"\n'
        )

        result = runner.invoke(app, ["-c", str(config), "edit", "bash"])
        assert result.exit_code == 1
        assert str(nonexistent) in result.output


class TestEditNoArgument:
    """T012-T013: twsrt edit with no/invalid argument."""

    def test_edit_no_argument_shows_sources(self, tmp_path: Path) -> None:
        """T012: edit with no argument lists available sources."""
        config, _, _ = _make_edit_config(tmp_path)
        result = runner.invoke(app, ["-c", str(config), "edit"])
        assert result.exit_code == 0
        assert "srt" in result.output
        assert "bash" in result.output

    def test_edit_invalid_source_exits_1(self, tmp_path: Path) -> None:
        """T013: edit with invalid source shows error and valid sources."""
        config, _, _ = _make_edit_config(tmp_path)
        result = runner.invoke(app, ["-c", str(config), "edit", "foo"])
        assert result.exit_code == 1
        assert "foo" in result.output
        assert "srt" in result.output
        assert "bash" in result.output
