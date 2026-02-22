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
            'bash_rules = "~/.twsrt/bash-rules.json"\n'
        )
        config = load_config(toml_file)
        assert "~" not in str(config.srt_path)
        assert "~" not in str(config.bash_rules_path)
