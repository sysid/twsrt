"""TOML config loading for twsrt."""

import tomllib
from pathlib import Path

from twsrt.lib.models import AppConfig


def load_config(config_path: Path) -> AppConfig:
    """Load AppConfig from a TOML file. Falls back to defaults if file is missing."""
    if not config_path.exists():
        return AppConfig()

    try:
        with open(config_path, "rb") as f:
            data = tomllib.load(f)
    except tomllib.TOMLDecodeError as e:
        raise ValueError(f"Invalid TOML in {config_path}: {e}") from e

    sources = data.get("sources", {})
    targets = data.get("targets", {})

    srt_path = Path(sources["srt"]).expanduser() if "srt" in sources else None
    bash_rules_path = (
        Path(sources["bash_rules"]).expanduser() if "bash_rules" in sources else None
    )
    claude_settings_path = (
        Path(targets["claude_settings"]).expanduser()
        if "claude_settings" in targets
        else None
    )
    copilot_output_path = (
        Path(targets["copilot_output"]).expanduser()
        if "copilot_output" in targets
        else None
    )

    config = AppConfig()
    if srt_path is not None:
        config.srt_path = srt_path
    if bash_rules_path is not None:
        config.bash_rules_path = bash_rules_path
    if claude_settings_path is not None:
        config.claude_settings_path = claude_settings_path
    if copilot_output_path is not None:
        config.copilot_output_path = copilot_output_path

    return config
