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

    def test_omitted_outputs_default_to_the_config_directory(
        self, tmp_twsrt_dir: Path
    ) -> None:
        path = tmp_twsrt_dir / "config.toml"
        path.write_text(
            base_config()
            .replace('output = "~/.srt-settings.json"\n', "")
            .replace('output = "bash-rules.json"\n', "")
        )

        config = load_config(path)

        assert config.sources["srt"].output_path == tmp_twsrt_dir / "srt-settings.json"
        assert config.sources["bash"].output_path == tmp_twsrt_dir / "bash-rules.json"
        assert config.srt_path == tmp_twsrt_dir / "srt-settings.json"

    def test_an_explicit_output_overrides_the_default(
        self, tmp_twsrt_dir: Path
    ) -> None:
        path = tmp_twsrt_dir / "config.toml"
        path.write_text(base_config())

        config = load_config(path)

        assert config.sources["srt"].output_path == Path.home() / ".srt-settings.json"

    def test_policy_files_are_config_and_every_sources_path_as_absolute_paths(
        self, tmp_twsrt_dir: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Relative entries would anchor at srt's launch cwd, not the config."""
        (tmp_twsrt_dir / "config.toml").write_text(base_config())
        monkeypatch.chdir(tmp_twsrt_dir)

        config = load_config(Path("config.toml"))

        assert config.policy_files == [
            str(tmp_twsrt_dir / "config.toml"),
            "~/.srt-settings.json",
            str(tmp_twsrt_dir / "srt/base.jsonc"),
            str(tmp_twsrt_dir / "bash-rules.json"),
            str(tmp_twsrt_dir / "bash/base.jsonc"),
        ]

    def test_policy_files_under_home_are_spelled_with_tilde(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Generated files stay readable and match hand-written ~ entries."""
        home = tmp_path / "home"
        twsrt_dir = home / ".config" / "twsrt"
        twsrt_dir.mkdir(parents=True)
        (twsrt_dir / "config.toml").write_text(base_config())
        monkeypatch.setenv("HOME", str(home))

        config = load_config(twsrt_dir / "config.toml")

        assert config.policy_files == [
            "~/.config/twsrt/config.toml",
            "~/.srt-settings.json",
            "~/.config/twsrt/srt/base.jsonc",
            "~/.config/twsrt/bash-rules.json",
            "~/.config/twsrt/bash/base.jsonc",
        ]

    def test_policy_files_behind_a_symlink_carry_their_real_path_too(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """srt keeps a symlink spelling whose target leaves its tree (stow),
        while Seatbelt matches the real path: the deny must name both."""
        home = tmp_path / "home"
        real = home / "dotfiles" / "twsrt"
        real.mkdir(parents=True)
        (real / "config.toml").write_text(base_config())
        link = home / ".config" / "twsrt"
        link.parent.mkdir()
        link.symlink_to(real)
        monkeypatch.setenv("HOME", str(home))

        config = load_config(link / "config.toml")

        assert "~/.config/twsrt/config.toml" in config.policy_files
        assert "~/dotfiles/twsrt/config.toml" in config.policy_files
        assert "~/.config/twsrt/srt/base.jsonc" in config.policy_files
        assert "~/dotfiles/twsrt/srt/base.jsonc" in config.policy_files

    def test_no_targets_table_means_no_agent_is_configured(
        self, tmp_twsrt_dir: Path
    ) -> None:
        """An absent key never falls back to a real path under ~."""
        path = tmp_twsrt_dir / "config.toml"
        path.write_text(base_config())

        config = load_config(path)

        assert config.agent_target("claude") is None
        assert config.agent_target("copilot") is None
        assert config.agent_target("codex") is None
        assert config.codex_rules_path is None

    def test_each_primary_target_key_configures_its_agent(
        self, tmp_twsrt_dir: Path, tmp_path: Path
    ) -> None:
        path = tmp_twsrt_dir / "config.toml"
        path.write_text(
            base_config(
                "[targets]\n"
                f'claude_settings = "{tmp_path / "settings.full.json"}"\n'
                f'copilot_output = "{tmp_path / "copilot-flags.txt"}"\n'
                f'codex_config = "{tmp_path / "config.toml"}"\n'
            )
        )

        config = load_config(path)

        assert config.agent_target("claude") == tmp_path / "settings.full.json"
        assert config.agent_target("copilot") == tmp_path / "copilot-flags.txt"
        assert config.agent_target("codex") == tmp_path / "config.toml"

    def test_require_target_names_the_missing_key(self, tmp_twsrt_dir: Path) -> None:
        path = tmp_twsrt_dir / "config.toml"
        path.write_text(base_config())

        config = load_config(path)

        with pytest.raises(ValueError, match=r"copilot.*\[targets\]\.copilot_output"):
            config.require_target("copilot")

    @pytest.mark.parametrize(
        ("dependent", "primary"),
        [
            ("claude_settings_yolo", "claude_settings"),
            ("copilot_output_yolo", "copilot_output"),
            ("codex_rules", "codex_config"),
        ],
    )
    def test_secondary_target_without_its_primary_is_rejected(
        self, tmp_twsrt_dir: Path, dependent: str, primary: str
    ) -> None:
        """A yolo or rules path alone would half-configure an agent; fail loudly."""
        path = tmp_twsrt_dir / "config.toml"
        path.write_text(base_config(f'[targets]\n{dependent} = "x.txt"\n'))

        with pytest.raises(ValueError, match=rf"{dependent} requires {primary}"):
            load_config(path)

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

    def test_codex_rules_target_is_optional(
        self, tmp_twsrt_dir: Path, tmp_path: Path
    ) -> None:
        codex_config = tmp_path / ".codex/config.toml"
        path = tmp_twsrt_dir / "config.toml"
        path.write_text(base_config(f'[targets]\ncodex_config = "{codex_config}"\n'))

        config = load_config(path)

        assert config.codex_rules_path is None
        assert config.agent_target("codex") == codex_config


SRT_ONLY_CONFIG = """schema_version = 1
default_profile = "default"

[sources.srt]
[sources.srt.fragments.base]
path = "srt/base.jsonc"

[profiles.default]
srt = ["base"]
"""


class TestOptionalBashSource:
    def test_a_config_without_bash_loads_with_srt_as_its_only_source(
        self, tmp_twsrt_dir: Path
    ) -> None:
        path = tmp_twsrt_dir / "config.toml"
        path.write_text(SRT_ONLY_CONFIG)

        config = load_config(path)

        assert set(config.sources) == {"srt"}

    def test_without_bash_no_bash_path_is_write_protected(
        self, tmp_twsrt_dir: Path
    ) -> None:
        path = tmp_twsrt_dir / "config.toml"
        path.write_text(SRT_ONLY_CONFIG)

        config = load_config(path)

        assert {
            str(Path(entry).relative_to(tmp_twsrt_dir)) for entry in config.policy_files
        } == {"config.toml", "srt-settings.json", "srt/base.jsonc"}

    def test_srt_stays_required(self, tmp_twsrt_dir: Path) -> None:
        path = tmp_twsrt_dir / "config.toml"
        path.write_text(
            """schema_version = 1
default_profile = "default"

[sources.bash]
[sources.bash.fragments.base]
path = "bash/base.jsonc"

[profiles.default]
bash = ["base"]
"""
        )

        with pytest.raises(ValueError, match="Missing canonical source kind.*srt"):
            load_config(path)

    def test_a_profile_selecting_bash_without_a_bash_source_is_rejected(
        self, tmp_twsrt_dir: Path
    ) -> None:
        path = tmp_twsrt_dir / "config.toml"
        path.write_text(SRT_ONLY_CONFIG + 'bash = ["base"]\n')

        with pytest.raises(
            ValueError,
            match=r"profiles\.default: source kind 'bash' not configured",
        ):
            load_config(path)


class TestYoloConfigLoading:
    def test_yolo_paths_loaded_when_present(self, tmp_twsrt_dir: Path) -> None:
        path = tmp_twsrt_dir / "config.toml"
        path.write_text(
            base_config(
                "[targets]\n"
                'claude_settings = "~/.claude/settings.full.json"\n'
                'copilot_output = "~/.config/twsrt/copilot-flags.txt"\n'
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


class TestClaudeSync:
    def test_absent_table_disables_sync(self, tmp_twsrt_dir: Path) -> None:
        path = tmp_twsrt_dir / "config.toml"
        path.write_text(base_config())
        assert load_config(path).claude_sync is None

    def test_mode_specific_list_parsed(self, tmp_twsrt_dir: Path) -> None:
        path = tmp_twsrt_dir / "config.toml"
        path.write_text(
            base_config(
                "[claude_sync]\n"
                'mode_specific = ["skipDangerousModePermissionPrompt", "hooks.PostToolUse"]\n'
            )
        )
        config = load_config(path)
        assert config.claude_sync is not None
        assert config.claude_sync.mode_specific == [
            "skipDangerousModePermissionPrompt",
            "hooks.PostToolUse",
        ]

    def test_empty_table_enables_sync_with_no_exclusions(
        self, tmp_twsrt_dir: Path
    ) -> None:
        path = tmp_twsrt_dir / "config.toml"
        path.write_text(base_config("[claude_sync]\n"))
        config = load_config(path)
        assert config.claude_sync is not None
        assert config.claude_sync.mode_specific == []

    def test_mode_specific_must_be_list(self, tmp_twsrt_dir: Path) -> None:
        path = tmp_twsrt_dir / "config.toml"
        path.write_text(base_config('[claude_sync]\nmode_specific = "theme"\n'))
        with pytest.raises(
            ValueError, match="claude_sync.mode_specific must be a list"
        ):
            load_config(path)

    def test_mode_specific_entries_must_be_non_empty_strings(
        self, tmp_twsrt_dir: Path
    ) -> None:
        path = tmp_twsrt_dir / "config.toml"
        path.write_text(base_config('[claude_sync]\nmode_specific = ["theme", ""]\n'))
        with pytest.raises(ValueError, match="claude_sync.mode_specific"):
            load_config(path)

    def test_unknown_field_rejected(self, tmp_twsrt_dir: Path) -> None:
        path = tmp_twsrt_dir / "config.toml"
        path.write_text(base_config("[claude_sync]\nmode_specifc = []\n"))
        with pytest.raises(ValueError, match="claude_sync: unknown field"):
            load_config(path)
