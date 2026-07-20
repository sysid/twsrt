"""Tests for TOML configuration loading."""

from pathlib import Path

import pytest

from twsrt.lib.config import load_config
from twsrt.lib.models import AppConfig


def base_config(extra: str = "") -> str:
    return f"""schema_version = 1
default_profile = "default"

[sources.srt]
output = "~/.srt-settings.json"
[sources.srt.fragments.base]
path = "srt/base.jsonc"

[sources.bash]
output = "bash-rules.json"
[sources.bash.fragments.base]
path = "bash/base.jsonc"

[profiles.default]
srt = ["base"]
bash = ["base"]

{extra}
"""


class TestLoadConfig:
    def test_load_valid_toml(self, config_toml_file: Path) -> None:
        config = load_config(config_toml_file)
        assert isinstance(config, AppConfig)
        assert set(config.sources) == {"srt", "bash"}

    def test_missing_toml_fails_explicitly(self, tmp_path: Path) -> None:
        with pytest.raises(FileNotFoundError, match="Config file not found"):
            load_config(tmp_path / "nonexistent.toml")

    def test_invalid_toml_raises_error(self, tmp_path: Path) -> None:
        bad = tmp_path / "bad.toml"
        bad.write_text("this is not [valid toml !!!")
        with pytest.raises(ValueError, match="Invalid"):
            load_config(bad)

    def test_tilde_and_relative_path_expansion(self, tmp_twsrt_dir: Path) -> None:
        path = tmp_twsrt_dir / "config.toml"
        path.write_text(base_config())

        config = load_config(path)

        assert "~" not in str(config.sources["srt"].output_path)
        assert config.sources["bash"].output_path == tmp_twsrt_dir / "bash-rules.json"

    def test_codex_targets_have_user_level_defaults(self, tmp_twsrt_dir: Path) -> None:
        path = tmp_twsrt_dir / "config.toml"
        path.write_text(base_config())

        config = load_config(path)

        assert str(config.codex_config_path).endswith(".codex/config.toml")
        assert config.codex_rules_path is None
        assert config.codex_targets_configured is False

    def test_loads_codex_targets(self, tmp_twsrt_dir: Path, tmp_path: Path) -> None:
        codex_config = tmp_path / ".codex/config.toml"
        codex_rules = tmp_path / ".codex/rules/twsrt.rules"
        path = tmp_twsrt_dir / "config.toml"
        path.write_text(
            base_config(
                f'[targets]\ncodex_config = "{codex_config}"\n'
                f'codex_rules = "{codex_rules}"\n'
            )
        )

        config = load_config(path)

        assert config.codex_config_path == codex_config
        assert config.codex_rules_path == codex_rules
        assert config.codex_targets_configured is True

    def test_codex_rules_target_is_optional(
        self, tmp_twsrt_dir: Path, tmp_path: Path
    ) -> None:
        codex_config = tmp_path / ".codex/config.toml"
        path = tmp_twsrt_dir / "config.toml"
        path.write_text(base_config(f'[targets]\ncodex_config = "{codex_config}"\n'))

        config = load_config(path)

        assert config.codex_rules_path is None
        assert config.codex_targets_configured is True


class TestYoloConfigLoading:
    def test_yolo_paths_loaded_when_present(self, tmp_twsrt_dir: Path) -> None:
        path = tmp_twsrt_dir / "config.toml"
        path.write_text(
            base_config(
                "[targets]\n"
                'claude_settings_yolo = "~/.claude/settings.yolo.json"\n'
                'copilot_output_yolo = "~/.config/twsrt/copilot-flags.yolo.txt"\n'
            )
        )

        config = load_config(path)

        assert str(config.claude_yolo_path).endswith("settings.yolo.json")
        assert str(config.copilot_yolo_path).endswith("copilot-flags.yolo.txt")

    def test_claude_settings_rejects_anchor_name(self, tmp_twsrt_dir: Path) -> None:
        path = tmp_twsrt_dir / "config.toml"
        path.write_text(
            base_config('[targets]\nclaude_settings = "~/.claude/settings.json"\n')
        )

        with pytest.raises(ValueError, match="reserved.*symlink anchor"):
            load_config(path)

    def test_yolo_paths_none_when_absent(self, tmp_twsrt_dir: Path) -> None:
        path = tmp_twsrt_dir / "config.toml"
        path.write_text(base_config())

        config = load_config(path)

        assert config.claude_yolo_path is None
        assert config.copilot_yolo_path is None


class TestSandboxOverrides:
    def test_sandbox_overrides_loaded(self, tmp_twsrt_dir: Path) -> None:
        path = tmp_twsrt_dir / "config.toml"
        path.write_text(
            base_config(
                "[sandbox_overrides.yolo]\n"
                "enabled = true\n"
                "autoAllowBashIfSandboxed = true\n"
                "allowUnsandboxedCommands = false\n"
                "[sandbox_overrides.full]\n"
                "enabled = false\n"
            )
        )

        config = load_config(path)

        assert config.sandbox_overrides == {
            "yolo": {
                "enabled": True,
                "autoAllowBashIfSandboxed": True,
                "allowUnsandboxedCommands": False,
            },
            "full": {"enabled": False},
        }

    def test_sandbox_overrides_empty_when_absent(self, tmp_twsrt_dir: Path) -> None:
        path = tmp_twsrt_dir / "config.toml"
        path.write_text(base_config())
        assert load_config(path).sandbox_overrides == {}

    def test_sandbox_overrides_partial(self, tmp_twsrt_dir: Path) -> None:
        path = tmp_twsrt_dir / "config.toml"
        path.write_text(base_config("[sandbox_overrides.yolo]\nenabled = true\n"))
        assert load_config(path).sandbox_overrides == {"yolo": {"enabled": True}}
