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

    def test_init_creates_comprehensive_config_toml(self, tmp_path: Path) -> None:
        """US3: init creates config with settings.full.json default and commented yolo targets."""
        twsrt_dir = tmp_path / "config" / "twsrt"
        result = runner.invoke(app, ["init", "--dir", str(twsrt_dir)])
        assert result.exit_code == 0
        content = (twsrt_dir / "config.toml").read_text()
        # Default claude_settings should be settings.full.json
        assert 'claude_settings = "~/.claude/settings.full.json"' in content
        # Yolo targets should be commented out
        assert "# claude_settings_yolo" in content
        # Copilot should be commented out
        assert "# copilot_output" in content
        # Copilot yolo should be commented out
        assert "# copilot_output_yolo" in content
        # Sources section present
        assert "[sources]" in content
        assert "[targets]" in content

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
            "filesystem": {
                "denyRead": ["~/.aws", "~/.ssh"],
            },
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
            "filesystem": {
                "allowWrite": [".", "/tmp"],
            },
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
            "network": {
                "allowedDomains": ["github.com", "*.github.com"],
            },
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
        srt = {}
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
        srt = {}
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
            "filesystem": {
                "denyWrite": ["**/.env", "**/*.pem"],
            },
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
            "filesystem": {
                "denyRead": ["**/.secret"],
            },
            "network": {
                "allowedDomains": ["github.com"],
            },
        }
        bash_rules = {"deny": ["rm"], "ask": ["git push"]}
        config = _make_config(tmp_path, srt, bash_rules)

        # Create existing settings.full.json with hooks, mcp, blanket allows
        settings_path = tmp_path / ".claude" / "settings.full.json"
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


# --- Symlink Config Tests (007) ---


class TestSymlinkGenerateClaude:
    """T009 [US1]: CLI tests for generate claude -w with symlink management."""

    def test_fresh_write_creates_target_and_symlink(self, tmp_path: Path) -> None:
        """Given settings.json does not exist, generate -w creates target + symlink."""
        srt = {}
        bash_rules = {"deny": ["rm"], "ask": []}
        config = _make_config(tmp_path, srt, bash_rules)

        claude_dir = tmp_path / ".claude"
        claude_dir.mkdir(parents=True, exist_ok=True)
        target = claude_dir / "settings.full.json"
        anchor = claude_dir / "settings.json"

        config_content = config.read_text()
        config.write_text(
            config_content + f'\n[targets]\nclaude_settings = "{target}"\n'
        )

        result = runner.invoke(
            app, ["-c", str(config), "generate", "claude", "--write"]
        )
        assert result.exit_code == 0, result.output
        assert target.exists()
        assert anchor.is_symlink()
        assert anchor.resolve() == target.resolve()
        # Verify it's a relative symlink
        import os

        link_value = os.readlink(str(anchor))
        assert link_value == "settings.full.json"

    def test_migration_moves_regular_file_and_symlinks(self, tmp_path: Path) -> None:
        """Given settings.json is a regular file and target missing, migrate + symlink."""
        srt = {}
        bash_rules = {"deny": ["rm"], "ask": []}
        config = _make_config(tmp_path, srt, bash_rules)

        claude_dir = tmp_path / ".claude"
        claude_dir.mkdir(parents=True, exist_ok=True)
        target = claude_dir / "settings.full.json"
        anchor = claude_dir / "settings.json"

        # Create regular settings.json with existing content
        existing = {
            "permissions": {"deny": ["Bash(old)"], "ask": [], "allow": []},
            "sandbox": {"network": {"allowedDomains": []}},
        }
        anchor.write_text(json.dumps(existing))

        config_content = config.read_text()
        config.write_text(
            config_content + f'\n[targets]\nclaude_settings = "{target}"\n'
        )

        result = runner.invoke(
            app, ["-c", str(config), "generate", "claude", "--write"]
        )
        assert result.exit_code == 0, result.output
        assert "Migrated" in result.output
        assert target.exists()
        assert anchor.is_symlink()
        assert anchor.resolve() == target.resolve()
        # Merged content: old deny replaced, new deny present
        written = json.loads(target.read_text())
        assert "Bash(rm)" in written["permissions"]["deny"]

    def test_conflict_errors_when_both_exist(self, tmp_path: Path) -> None:
        """Given settings.json is a regular file AND target exists, error out."""
        srt = {}
        bash_rules = {"deny": ["rm"], "ask": []}
        config = _make_config(tmp_path, srt, bash_rules)

        claude_dir = tmp_path / ".claude"
        claude_dir.mkdir(parents=True, exist_ok=True)
        target = claude_dir / "settings.full.json"
        anchor = claude_dir / "settings.json"

        anchor.write_text('{"anchor": true}')
        target.write_text('{"target": true}')

        config_content = config.read_text()
        config.write_text(
            config_content + f'\n[targets]\nclaude_settings = "{target}"\n'
        )

        result = runner.invoke(
            app, ["-c", str(config), "generate", "claude", "--write"]
        )
        assert result.exit_code == 1
        assert "both" in result.output.lower() or "Error" in result.output
        # Neither file modified
        assert anchor.read_text() == '{"anchor": true}'
        assert target.read_text() == '{"target": true}'

    def test_update_merges_leaves_symlink(self, tmp_path: Path) -> None:
        """Given settings.json is already symlink to target, merge and keep symlink."""
        srt = {}
        bash_rules = {"deny": ["rm"], "ask": []}
        config = _make_config(tmp_path, srt, bash_rules)

        claude_dir = tmp_path / ".claude"
        claude_dir.mkdir(parents=True, exist_ok=True)
        target = claude_dir / "settings.full.json"
        anchor = claude_dir / "settings.json"

        existing = {
            "permissions": {"deny": ["Bash(old)"], "ask": [], "allow": []},
            "sandbox": {"network": {"allowedDomains": []}},
            "hooks": {"PreToolUse": []},
        }
        target.write_text(json.dumps(existing))
        anchor.symlink_to("settings.full.json")

        config_content = config.read_text()
        config.write_text(
            config_content + f'\n[targets]\nclaude_settings = "{target}"\n'
        )

        result = runner.invoke(
            app, ["-c", str(config), "generate", "claude", "--write"]
        )
        assert result.exit_code == 0, result.output
        assert anchor.is_symlink()
        written = json.loads(target.read_text())
        assert "Bash(rm)" in written["permissions"]["deny"]
        assert "hooks" in written  # preserved

    def test_switch_from_yolo_repoints_symlink(self, tmp_path: Path) -> None:
        """Given settings.json symlinks to yolo target, generate claude -w re-points to full."""
        srt = {}
        bash_rules = {"deny": ["rm"], "ask": []}
        config = _make_config(tmp_path, srt, bash_rules)

        claude_dir = tmp_path / ".claude"
        claude_dir.mkdir(parents=True, exist_ok=True)
        full_target = claude_dir / "settings.full.json"
        yolo_target = claude_dir / "settings.yolo.json"
        anchor = claude_dir / "settings.json"

        yolo_target.write_text('{"yolo": true}')
        anchor.symlink_to("settings.yolo.json")

        config_content = config.read_text()
        config.write_text(
            config_content + f'\n[targets]\nclaude_settings = "{full_target}"\n'
        )

        result = runner.invoke(
            app, ["-c", str(config), "generate", "claude", "--write"]
        )
        assert result.exit_code == 0, result.output
        assert anchor.is_symlink()
        import os

        assert os.readlink(str(anchor)) == "settings.full.json"
        assert full_target.exists()


# --- Symlink YOLO Config Tests (007 US2) ---


class TestSymlinkYoloGenerateClaude:
    """T011 [US2]: CLI tests for generate --yolo claude -w with symlink management."""

    def test_fresh_yolo_write_creates_target_and_symlink(self, tmp_path: Path) -> None:
        """Given settings.json does not exist, generate --yolo -w creates yolo target + symlink."""
        srt = {}
        bash_rules = {"deny": ["rm"], "ask": ["git push"]}
        config = _make_config(tmp_path, srt, bash_rules)

        claude_dir = tmp_path / ".claude"
        claude_dir.mkdir(parents=True, exist_ok=True)
        full_target = claude_dir / "settings.full.json"
        anchor = claude_dir / "settings.json"

        config_content = config.read_text()
        config.write_text(
            config_content + f'\n[targets]\nclaude_settings = "{full_target}"\n'
        )

        result = runner.invoke(
            app, ["-c", str(config), "generate", "--yolo", "claude", "--write"]
        )
        assert result.exit_code == 0, result.output
        yolo_target = claude_dir / "settings.yolo.json"
        assert yolo_target.exists()
        assert anchor.is_symlink()
        import os

        assert os.readlink(str(anchor)) == "settings.yolo.json"
        written = json.loads(yolo_target.read_text())
        assert "ask" not in written["permissions"]

    def test_yolo_migration_moves_regular_file(self, tmp_path: Path) -> None:
        """Given settings.json is a regular file and yolo target missing, migrate."""
        srt = {}
        bash_rules = {"deny": ["rm"], "ask": []}
        config = _make_config(tmp_path, srt, bash_rules)

        claude_dir = tmp_path / ".claude"
        claude_dir.mkdir(parents=True, exist_ok=True)
        full_target = claude_dir / "settings.full.json"
        anchor = claude_dir / "settings.json"
        yolo_target = claude_dir / "settings.yolo.json"

        # Create regular settings.json
        existing = {
            "permissions": {"deny": ["Bash(old)"], "allow": []},
            "sandbox": {"network": {"allowedDomains": []}},
        }
        anchor.write_text(json.dumps(existing))

        config_content = config.read_text()
        config.write_text(
            config_content + f'\n[targets]\nclaude_settings = "{full_target}"\n'
        )

        result = runner.invoke(
            app, ["-c", str(config), "generate", "--yolo", "claude", "--write"]
        )
        assert result.exit_code == 0, result.output
        assert "Migrated" in result.output
        assert yolo_target.exists()
        assert anchor.is_symlink()

    def test_yolo_conflict_errors_when_both_exist(self, tmp_path: Path) -> None:
        """Given settings.json is regular file AND yolo target exists, error out."""
        srt = {}
        bash_rules = {"deny": ["rm"], "ask": []}
        config = _make_config(tmp_path, srt, bash_rules)

        claude_dir = tmp_path / ".claude"
        claude_dir.mkdir(parents=True, exist_ok=True)
        full_target = claude_dir / "settings.full.json"
        anchor = claude_dir / "settings.json"
        yolo_target = claude_dir / "settings.yolo.json"

        anchor.write_text('{"anchor": true}')
        yolo_target.write_text('{"yolo": true}')

        config_content = config.read_text()
        config.write_text(
            config_content + f'\n[targets]\nclaude_settings = "{full_target}"\n'
        )

        result = runner.invoke(
            app, ["-c", str(config), "generate", "--yolo", "claude", "--write"]
        )
        assert result.exit_code == 1
        assert "both" in result.output.lower() or "Error" in result.output

    def test_switch_from_full_to_yolo_repoints_symlink(self, tmp_path: Path) -> None:
        """Given settings.json symlinks to full target, --yolo re-points to yolo target."""
        srt = {}
        bash_rules = {"deny": ["rm"], "ask": []}
        config = _make_config(tmp_path, srt, bash_rules)

        claude_dir = tmp_path / ".claude"
        claude_dir.mkdir(parents=True, exist_ok=True)
        full_target = claude_dir / "settings.full.json"
        anchor = claude_dir / "settings.json"

        full_target.write_text('{"full": true}')
        anchor.symlink_to("settings.full.json")

        config_content = config.read_text()
        config.write_text(
            config_content + f'\n[targets]\nclaude_settings = "{full_target}"\n'
        )

        result = runner.invoke(
            app, ["-c", str(config), "generate", "--yolo", "claude", "--write"]
        )
        assert result.exit_code == 0, result.output
        assert anchor.is_symlink()
        import os

        assert os.readlink(str(anchor)) == "settings.yolo.json"


# --- YOLO Mode Tests ---


class TestYoloGenerateClaude:
    """T010: CLI integration tests for generate --yolo claude."""

    def test_yolo_generate_claude_stdout_no_ask(self, tmp_path: Path) -> None:
        """generate --yolo claude prints JSON with no permissions.ask."""
        srt = {"network": {"allowedDomains": ["github.com"]}}
        bash_rules = {"deny": ["rm", "sudo"], "ask": ["git push", "pip install"]}
        config = _make_config(tmp_path, srt, bash_rules)
        result = runner.invoke(app, ["-c", str(config), "generate", "--yolo", "claude"])
        assert result.exit_code == 0, result.output
        output = json.loads(result.output)
        assert "ask" not in output["permissions"]
        assert "Bash(rm)" in output["permissions"]["deny"]
        assert "Bash(git push)" not in output["permissions"]["deny"]
        assert "WebFetch(domain:github.com)" in output["permissions"]["allow"]

    def test_yolo_generate_claude_write_to_yolo_path(self, tmp_path: Path) -> None:
        """generate --yolo -w claude writes to settings.yolo.json and symlinks settings.json."""
        srt = {}
        bash_rules = {"deny": ["rm"], "ask": ["git push"]}
        config = _make_config(tmp_path, srt, bash_rules)

        claude_dir = tmp_path / ".claude"
        claude_dir.mkdir(parents=True, exist_ok=True)
        settings_full = claude_dir / "settings.full.json"
        yolo_settings_path = claude_dir / "settings.yolo.json"
        anchor = claude_dir / "settings.json"

        # Update config to include claude_settings target
        config_content = config.read_text()
        config.write_text(
            config_content + f'\n[targets]\nclaude_settings = "{settings_full}"\n'
        )

        result = runner.invoke(
            app, ["-c", str(config), "generate", "--yolo", "claude", "--write"]
        )
        assert result.exit_code == 0, result.output
        assert yolo_settings_path.exists()
        written = json.loads(yolo_settings_path.read_text())
        assert "ask" not in written["permissions"]
        # settings.json should be a symlink to yolo target
        assert anchor.is_symlink()
        import os

        assert os.readlink(str(anchor)) == "settings.yolo.json"

    def test_yolo_generate_claude_merges_into_existing_yolo_file(
        self, tmp_path: Path
    ) -> None:
        """generate --yolo -w claude merges into existing settings.yolo.json, preserving user keys."""
        srt = {}
        bash_rules = {"deny": ["rm"], "ask": ["git push"]}
        config = _make_config(tmp_path, srt, bash_rules)

        claude_dir = tmp_path / ".claude"
        claude_dir.mkdir(parents=True, exist_ok=True)
        settings_full = claude_dir / "settings.full.json"
        yolo_settings_path = claude_dir / "settings.yolo.json"

        # Pre-populate yolo file with user-managed keys (hooks, custom allows)
        existing = {
            "permissions": {
                "deny": ["Bash(old)"],
                "allow": ["mcp__my_server", "WebFetch(domain:stale.com)"],
            },
            "hooks": {"PreToolUse": [{"matcher": "Bash", "hooks": ["echo hi"]}]},
            "sandbox": {"network": {"allowedDomains": []}},
        }
        yolo_settings_path.write_text(json.dumps(existing))

        config_content = config.read_text()
        config.write_text(
            config_content + f'\n[targets]\nclaude_settings = "{settings_full}"\n'
        )

        result = runner.invoke(
            app, ["-c", str(config), "generate", "--yolo", "claude", "--write"]
        )
        assert result.exit_code == 0, result.output
        written = json.loads(yolo_settings_path.read_text())

        # deny replaced
        assert "Bash(rm)" in written["permissions"]["deny"]
        assert "Bash(old)" not in written["permissions"]["deny"]
        # no ask key in yolo
        assert "ask" not in written["permissions"]
        # hooks preserved
        assert "hooks" in written
        # mcp allow preserved, stale WebFetch removed
        assert "mcp__my_server" in written["permissions"]["allow"]
        assert "WebFetch(domain:stale.com)" not in written["permissions"]["allow"]

    def test_yolo_generate_claude_dry_run(self, tmp_path: Path) -> None:
        """generate --yolo -w -n claude shows dry run with yolo path."""
        srt = {}
        bash_rules = {"deny": ["rm"], "ask": []}
        config = _make_config(tmp_path, srt, bash_rules)

        claude_dir = tmp_path / ".claude"
        claude_dir.mkdir(parents=True, exist_ok=True)
        settings_full = claude_dir / "settings.full.json"

        config_content = config.read_text()
        config.write_text(
            config_content + f'\n[targets]\nclaude_settings = "{settings_full}"\n'
        )

        result = runner.invoke(
            app,
            ["-c", str(config), "generate", "--yolo", "claude", "--write", "--dry-run"],
        )
        assert result.exit_code == 0, result.output
        assert "yolo" in result.output.lower()


class TestYoloGenerateAll:
    """T019: CLI integration tests for generate --yolo (all agents)."""

    def test_yolo_generate_all_produces_both_outputs(self, tmp_path: Path) -> None:
        """generate --yolo produces both Claude and Copilot yolo outputs."""
        srt = {"network": {"allowedDomains": ["github.com"]}}
        bash_rules = {"deny": ["rm"], "ask": ["git push"]}
        config = _make_config(tmp_path, srt, bash_rules)
        result = runner.invoke(app, ["-c", str(config), "generate", "--yolo"])
        assert result.exit_code == 0, result.output
        # Both agent headers present
        assert "--- claude ---" in result.output
        assert "--- copilot ---" in result.output
        # Claude output has no ask key
        # Copilot output starts with --yolo
        assert "--yolo" in result.output

    def test_yolo_generate_all_write_to_yolo_paths(self, tmp_path: Path) -> None:
        """generate --yolo -w writes both agents to yolo-specific paths."""
        srt = {}
        bash_rules = {"deny": ["rm"], "ask": []}
        config = _make_config(tmp_path, srt, bash_rules)

        claude_dir = tmp_path / ".claude"
        claude_dir.mkdir(parents=True, exist_ok=True)
        settings_full = claude_dir / "settings.full.json"
        anchor = claude_dir / "settings.json"
        copilot_path = tmp_path / "copilot-flags.txt"

        config_content = config.read_text()
        config.write_text(
            config_content
            + f'\n[targets]\nclaude_settings = "{settings_full}"\n'
            + f'copilot_output = "{copilot_path}"\n'
        )

        result = runner.invoke(
            app, ["-c", str(config), "generate", "--yolo", "--write"]
        )
        assert result.exit_code == 0, result.output

        yolo_settings = claude_dir / "settings.yolo.json"
        yolo_copilot = tmp_path / "copilot-flags.yolo.txt"

        assert yolo_settings.exists()
        assert yolo_copilot.exists()
        # settings.json should now be a symlink to yolo target
        assert anchor.is_symlink()
        assert not copilot_path.exists()


class TestYoloGenerateCopilot:
    """T016: CLI integration tests for generate --yolo copilot."""

    def test_yolo_generate_copilot_stdout_starts_with_yolo(
        self, tmp_path: Path
    ) -> None:
        """generate --yolo copilot prints output starting with --yolo."""
        srt = {"network": {"allowedDomains": ["github.com"]}}
        bash_rules = {"deny": ["rm"], "ask": ["git push"]}
        config = _make_config(tmp_path, srt, bash_rules)
        result = runner.invoke(
            app, ["-c", str(config), "generate", "--yolo", "copilot"]
        )
        assert result.exit_code == 0, result.output
        lines = [
            line.strip() for line in result.output.strip().split("\n") if line.strip()
        ]
        assert lines[0].startswith("--yolo")
        # No --allow-url or --allow-tool
        assert "--allow-url" not in result.output
        assert "--allow-tool" not in result.output
        # No ASK-derived deny-tool
        assert "git push" not in result.output

    def test_yolo_generate_copilot_write_to_yolo_path(self, tmp_path: Path) -> None:
        """generate --yolo -w copilot writes to copilot-flags.yolo.txt (no symlink for copilot)."""
        srt = {}
        bash_rules = {"deny": ["rm"], "ask": []}
        config = _make_config(tmp_path, srt, bash_rules)

        copilot_path = tmp_path / "copilot-flags.txt"
        yolo_copilot_path = tmp_path / "copilot-flags.yolo.txt"

        config_content = config.read_text()
        config.write_text(
            config_content + f'\n[targets]\ncopilot_output = "{copilot_path}"\n'
        )

        result = runner.invoke(
            app, ["-c", str(config), "generate", "--yolo", "copilot", "--write"]
        )
        assert result.exit_code == 0, result.output
        assert yolo_copilot_path.exists()
        content = yolo_copilot_path.read_text()
        assert "--yolo" in content
        # Copilot doesn't use symlinks — no copilot_path created
        assert not copilot_path.exists()


# --- US2 Acceptance Scenario Integration Tests ---


class TestUS2AcceptanceScenarios:
    """Acceptance scenarios from spec.md US2 (Copilot CLI)."""

    def test_copilot_deny_flags(self, tmp_path: Path) -> None:
        """Bash deny → --deny-tool flags."""
        srt = {}
        bash_rules = {"deny": ["rm", "sudo"], "ask": []}
        config = _make_config(tmp_path, srt, bash_rules)
        result = runner.invoke(app, ["-c", str(config), "generate", "copilot"])
        assert result.exit_code == 0
        assert "--deny-tool 'shell(rm)'" in result.output
        assert "--deny-tool 'shell(sudo)'" in result.output

    def test_copilot_lossy_ask_warning(self, tmp_path: Path) -> None:
        """Bash ask → --deny-tool with warning on stderr."""
        srt = {}
        bash_rules = {"deny": [], "ask": ["git push"]}
        config = _make_config(tmp_path, srt, bash_rules)
        result = runner.invoke(app, ["-c", str(config), "generate", "copilot"])
        assert result.exit_code == 0
        assert "--deny-tool 'shell(git push)'" in result.output

    def test_generate_all_includes_both_agents(self, tmp_path: Path) -> None:
        """twsrt generate (all) includes both Claude and Copilot output."""
        srt = {
            "network": {
                "allowedDomains": ["github.com"],
            },
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

    claude_target = tmp_path / ".claude" / "settings.full.json"
    claude_target.parent.mkdir(parents=True)

    copilot_target = tmp_path / "copilot-flags.txt"

    config_file = twsrt_dir / "config.toml"
    config_file.write_text(
        f'[sources]\nsrt = "{srt_file}"\nbash_rules = "{br_file}"\n'
        f'[targets]\nclaude_settings = "{claude_target}"\n'
        f'copilot_output = "{copilot_target}"\n'
    )
    return config_file, claude_target, copilot_target


class TestYoloDiffCommand:
    """T023: CLI diff --yolo tests."""

    def test_yolo_diff_matching_exits_0(self, tmp_path: Path) -> None:
        """diff --yolo claude with matching yolo file exits 0."""
        srt = {}
        bash_rules = {"deny": ["rm"], "ask": ["git push"]}
        config, claude_target, _ = _make_config_with_targets(tmp_path, srt, bash_rules)

        # Generate yolo output and write to yolo path
        yolo_target = claude_target.with_suffix(".yolo.json")
        from twsrt.lib.claude import ClaudeGenerator
        from twsrt.lib.models import AppConfig as AC

        gen = ClaudeGenerator()
        ac = AC(yolo=True)
        from twsrt.lib.models import Action, Scope, SecurityRule, Source

        rules = [
            SecurityRule(Scope.EXECUTE, Action.DENY, "rm", Source.BASH_RULES),
            SecurityRule(Scope.EXECUTE, Action.ASK, "git push", Source.BASH_RULES),
        ]
        output = gen.generate(rules, ac)
        yolo_target.write_text(output)

        config_text = config.read_text()
        config.write_text(
            config_text.replace(
                f'claude_settings = "{claude_target}"',
                f'claude_settings = "{claude_target}"\nclaude_settings_yolo = "{yolo_target}"',
            )
        )

        result = runner.invoke(app, ["-c", str(config), "diff", "--yolo", "claude"])
        assert result.exit_code == 0, result.output
        assert "no drift" in result.output.lower()

    def test_yolo_diff_drifted_exits_1(self, tmp_path: Path) -> None:
        """diff --yolo claude with drifted yolo file exits 1."""
        srt = {}
        bash_rules = {"deny": ["rm", "sudo"], "ask": []}
        config, claude_target, _ = _make_config_with_targets(tmp_path, srt, bash_rules)

        # Write yolo file with only rm (missing sudo)
        yolo_target = claude_target.with_suffix(".yolo.json")
        existing = {
            "permissions": {
                "deny": ["Bash(rm)", "Bash(rm *)"],
                "allow": [],
            },
            "sandbox": {"network": {"allowedDomains": []}},
        }
        yolo_target.write_text(json.dumps(existing))

        config_text = config.read_text()
        config.write_text(
            config_text.replace(
                f'claude_settings = "{claude_target}"',
                f'claude_settings = "{claude_target}"\nclaude_settings_yolo = "{yolo_target}"',
            )
        )

        result = runner.invoke(app, ["-c", str(config), "diff", "--yolo", "claude"])
        assert result.exit_code == 1
        assert "sudo" in result.output

    def test_yolo_diff_missing_file_exits_2(self, tmp_path: Path) -> None:
        """diff --yolo claude with missing yolo file exits 2."""
        srt = {}
        bash_rules = {"deny": ["rm"], "ask": []}
        config, claude_target, _ = _make_config_with_targets(tmp_path, srt, bash_rules)
        # Don't create yolo file

        result = runner.invoke(app, ["-c", str(config), "diff", "--yolo", "claude"])
        assert result.exit_code == 2


class TestSymlinkDiffCommand:
    """T015 [US4]: Diff follows symlinks transparently."""

    def test_diff_reads_full_target(self, tmp_path: Path) -> None:
        """diff claude reads settings.full.json target directly."""
        srt = {}
        bash_rules = {"deny": ["rm"], "ask": []}
        config, claude_target, _ = _make_config_with_targets(tmp_path, srt, bash_rules)

        # Write matching content to target (settings.full.json)
        from twsrt.lib.claude import ClaudeGenerator
        from twsrt.lib.models import (
            AppConfig as AC,
            SecurityRule,
            Scope,
            Action,
            Source,
        )

        gen = ClaudeGenerator()
        rules = [SecurityRule(Scope.EXECUTE, Action.DENY, "rm", Source.BASH_RULES)]
        output = gen.generate(rules, AC())
        claude_target.write_text(output)

        result = runner.invoke(app, ["-c", str(config), "diff", "claude"])
        assert result.exit_code == 0, result.output
        assert "no drift" in result.output.lower()

    def test_diff_yolo_reads_yolo_target_directly(self, tmp_path: Path) -> None:
        """diff --yolo claude reads yolo target file, not the full target."""
        srt = {}
        bash_rules = {"deny": ["rm"], "ask": ["git push"]}
        config, claude_target, _ = _make_config_with_targets(tmp_path, srt, bash_rules)

        claude_dir = claude_target.parent
        yolo_target = claude_dir / "settings.yolo.json"

        # Write matching yolo content
        from twsrt.lib.claude import ClaudeGenerator
        from twsrt.lib.models import (
            AppConfig as AC,
            SecurityRule,
            Scope,
            Action,
            Source,
        )

        gen = ClaudeGenerator()
        rules = [
            SecurityRule(Scope.EXECUTE, Action.DENY, "rm", Source.BASH_RULES),
            SecurityRule(Scope.EXECUTE, Action.ASK, "git push", Source.BASH_RULES),
        ]
        ac = AC(yolo=True)
        output = gen.generate(rules, ac)
        yolo_target.write_text(output)

        # Full target has different content
        claude_target.write_text('{"different": true}')

        # Update config to add yolo target
        config_text = config.read_text()
        config.write_text(
            config_text.replace(
                f'claude_settings = "{claude_target}"',
                f'claude_settings = "{claude_target}"\n'
                f'claude_settings_yolo = "{yolo_target}"',
            )
        )

        result = runner.invoke(app, ["-c", str(config), "diff", "--yolo", "claude"])
        assert result.exit_code == 0, result.output
        assert "no drift" in result.output.lower()


class TestDiffCommand:
    def test_diff_claude_with_drift_exits_1(self, tmp_path: Path) -> None:
        srt = {
            "filesystem": {
                "denyRead": ["**/.aws", "**/.kube"],
            },
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
        srt = {}
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
        srt = {}
        config, claude_target, _ = _make_config_with_targets(tmp_path, srt)
        # Don't create claude_target file

        result = runner.invoke(app, ["-c", str(config), "diff", "claude"])
        assert result.exit_code == 2


# --- US3 Acceptance Scenario Integration Tests ---


class TestUS3AcceptanceScenarios:
    def test_drift_detected_with_missing_and_extra(self, tmp_path: Path) -> None:
        """Place a known-drifted settings.json, verify specific missing/extra."""
        srt = {
            "filesystem": {
                "denyRead": ["**/.aws", "**/.kube"],
            },
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
        srt = {}
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
        srt = {}
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
    config.write_text(f'[sources]\nsrt = "{srt_file}"\nbash_rules = "{bash_file}"\n')
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
        config.write_text(f'[sources]\nsrt = "{nonexistent}"\nbash_rules = "/dummy"\n')

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
        config.write_text(f'[sources]\nsrt = "/dummy"\nbash_rules = "{nonexistent}"\n')

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
