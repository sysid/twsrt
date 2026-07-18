"""Tests for config.py: TOML config loading."""

from pathlib import Path

import pytest

from twsrt.lib.config import load_config
from twsrt.lib.models import AppConfig


class TestLoadConfig:
    def test_load_valid_toml(self, config_toml_file: Path) -> None:
        config = load_config(config_toml_file)
        assert isinstance(config, AppConfig)
        assert config.srt_path.exists()
        assert config.bash_rules_path.exists()

    def test_missing_toml_uses_defaults(self, tmp_path: Path) -> None:
        missing = tmp_path / "nonexistent.toml"
        config = load_config(missing)
        assert isinstance(config, AppConfig)
        # Should use defaults
        assert str(config.srt_path).endswith(".srt-settings.json")

    def test_invalid_toml_raises_error(self, tmp_path: Path) -> None:
        bad = tmp_path / "bad.toml"
        bad.write_text("this is not [valid toml !!!")
        with pytest.raises(ValueError, match="Invalid"):
            load_config(bad)

    def test_tilde_expansion_in_paths(self, tmp_twsrt_dir: Path) -> None:
        toml_file = tmp_twsrt_dir / "config.toml"
        toml_file.write_text(
            '[sources]\nsrt = "~/.srt-settings.json"\n'
            'bash_rules = "~/.config/twsrt/bash-rules.json"\n'
        )
        config = load_config(toml_file)
        assert "~" not in str(config.srt_path)
        assert "~" not in str(config.bash_rules_path)

    def test_codex_targets_have_user_level_defaults(self, tmp_path: Path) -> None:
        config = load_config(tmp_path / "missing.toml")

        assert str(config.codex_config_path).endswith(".codex/config.toml")
        assert config.codex_rules_path is None
        assert config.codex_targets_configured is False

    def test_loads_codex_targets(self, tmp_twsrt_dir: Path, tmp_path: Path) -> None:
        config_path = tmp_twsrt_dir / "config.toml"
        codex_config = tmp_path / ".codex" / "config.toml"
        codex_rules = tmp_path / ".codex" / "rules" / "twsrt.rules"
        config_path.write_text(
            "[targets]\n"
            f'codex_config = "{codex_config}"\n'
            f'codex_rules = "{codex_rules}"\n'
        )

        config = load_config(config_path)

        assert config.codex_config_path == codex_config
        assert config.codex_rules_path == codex_rules
        assert config.codex_targets_configured is True

    def test_codex_rules_target_is_optional(
        self, tmp_twsrt_dir: Path, tmp_path: Path
    ) -> None:
        config_path = tmp_twsrt_dir / "config.toml"
        codex_config = tmp_path / ".codex" / "config.toml"
        config_path.write_text(
            "[targets]\n" + f'codex_config = "{codex_config}"\n'
        )

        config = load_config(config_path)

        assert config.codex_config_path == codex_config
        assert config.codex_rules_path is None
        assert config.codex_targets_configured is True


class TestYoloConfigLoading:
    def test_yolo_paths_loaded_when_present(self, tmp_twsrt_dir: Path) -> None:
        toml_file = tmp_twsrt_dir / "config.toml"
        toml_file.write_text(
            '[sources]\nsrt = "~/.srt-settings.json"\n'
            'bash_rules = "~/.config/twsrt/bash-rules.json"\n'
            "[targets]\n"
            'claude_settings_yolo = "~/.claude/settings.yolo.json"\n'
            'copilot_output_yolo = "~/.config/twsrt/copilot-flags.yolo.txt"\n'
        )
        config = load_config(toml_file)
        assert config.claude_yolo_path is not None
        assert str(config.claude_yolo_path).endswith("settings.yolo.json")
        assert "~" not in str(config.claude_yolo_path)
        assert config.copilot_yolo_path is not None
        assert str(config.copilot_yolo_path).endswith("copilot-flags.yolo.txt")
        assert "~" not in str(config.copilot_yolo_path)

    def test_claude_settings_rejects_anchor_name(self, tmp_twsrt_dir: Path) -> None:
        """claude_settings = 'settings.json' must be rejected — it's the symlink anchor."""
        toml_file = tmp_twsrt_dir / "config.toml"
        toml_file.write_text(
            '[sources]\nsrt = "~/.srt-settings.json"\n'
            'bash_rules = "~/.config/twsrt/bash-rules.json"\n'
            "[targets]\n"
            'claude_settings = "~/.claude/settings.json"\n'
        )
        with pytest.raises(ValueError, match="reserved.*symlink anchor"):
            load_config(toml_file)

    def test_yolo_paths_none_when_absent(self, tmp_twsrt_dir: Path) -> None:
        toml_file = tmp_twsrt_dir / "config.toml"
        toml_file.write_text(
            '[sources]\nsrt = "~/.srt-settings.json"\n'
            'bash_rules = "~/.config/twsrt/bash-rules.json"\n'
        )
        config = load_config(toml_file)
        assert config.claude_yolo_path is None
        assert config.copilot_yolo_path is None


class TestSandboxOverrides:
    def test_sandbox_overrides_loaded(self, tmp_twsrt_dir: Path) -> None:
        """sandbox_overrides sections are loaded from TOML."""
        toml_file = tmp_twsrt_dir / "config.toml"
        toml_file.write_text(
            '[sources]\nsrt = "~/.srt-settings.json"\n'
            'bash_rules = "~/.config/twsrt/bash-rules.json"\n'
            "\n"
            "[sandbox_overrides.yolo]\n"
            "enabled = true\n"
            "autoAllowBashIfSandboxed = true\n"
            "allowUnsandboxedCommands = false\n"
            "\n"
            "[sandbox_overrides.full]\n"
            "enabled = false\n"
        )
        config = load_config(toml_file)
        assert config.sandbox_overrides == {
            "yolo": {
                "enabled": True,
                "autoAllowBashIfSandboxed": True,
                "allowUnsandboxedCommands": False,
            },
            "full": {
                "enabled": False,
            },
        }

    def test_sandbox_overrides_empty_when_absent(self, tmp_twsrt_dir: Path) -> None:
        """No sandbox_overrides section → empty dict."""
        toml_file = tmp_twsrt_dir / "config.toml"
        toml_file.write_text(
            '[sources]\nsrt = "~/.srt-settings.json"\n'
            'bash_rules = "~/.config/twsrt/bash-rules.json"\n'
        )
        config = load_config(toml_file)
        assert config.sandbox_overrides == {}

    def test_sandbox_overrides_partial(self, tmp_twsrt_dir: Path) -> None:
        """Only yolo overrides, no full overrides."""
        toml_file = tmp_twsrt_dir / "config.toml"
        toml_file.write_text(
            '[sources]\nsrt = "~/.srt-settings.json"\n'
            'bash_rules = "~/.config/twsrt/bash-rules.json"\n'
            "\n"
            "[sandbox_overrides.yolo]\n"
            "enabled = true\n"
        )
        config = load_config(toml_file)
        assert config.sandbox_overrides == {"yolo": {"enabled": True}}
        assert "full" not in config.sandbox_overrides
