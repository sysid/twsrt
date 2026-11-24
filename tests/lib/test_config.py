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
                f'claude_settings = "{tmp_path / "settings.json"}"\n'
                f'copilot_output = "{tmp_path / "copilot-flags.txt"}"\n'
                f'codex_config = "{tmp_path / "config.toml"}"\n'
            )
        )

        config = load_config(path)

        assert config.agent_target("claude") == tmp_path / "settings.json"
        assert config.agent_target("copilot") == tmp_path / "copilot-flags.txt"
        assert config.agent_target("codex") == tmp_path / "config.toml"

    def test_copilot_settings_alone_configures_copilot(
        self, tmp_twsrt_dir: Path, tmp_path: Path
    ) -> None:
        """The native-sandbox target works without the flags file (FR-026)."""
        path = tmp_twsrt_dir / "config.toml"
        path.write_text(
            base_config(
                f'[targets]\ncopilot_settings = "{tmp_path / "settings.json"}"\n'
            )
        )

        config = load_config(path)

        assert config.copilot_settings_path == tmp_path / "settings.json"
        assert config.copilot_output_path is None
        assert config.agent_target("copilot") == tmp_path / "settings.json"

    def test_copilot_flags_alone_still_configure_copilot(
        self, tmp_twsrt_dir: Path, tmp_path: Path
    ) -> None:
        """The flags-only mode stays supported (FR-026)."""
        path = tmp_twsrt_dir / "config.toml"
        path.write_text(
            base_config(
                f'[targets]\ncopilot_output = "{tmp_path / "copilot-flags.txt"}"\n'
            )
        )

        config = load_config(path)

        assert config.copilot_settings_path is None
        assert config.agent_target("copilot") == tmp_path / "copilot-flags.txt"

    def test_jetbrains_xml_list_configures_copilot_jetbrains(
        self, tmp_twsrt_dir: Path, tmp_path: Path
    ) -> None:
        """Every listed IDE file is a target; relative entries resolve like others."""
        path = tmp_twsrt_dir / "config.toml"
        path.write_text(
            base_config(
                "[targets]\n"
                f'copilot_jetbrains_xml = ["{tmp_path / "idea.xml"}", "pycharm.xml"]\n'
            )
        )

        config = load_config(path)

        assert config.copilot_jetbrains_xml_paths == [
            tmp_path / "idea.xml",
            tmp_twsrt_dir / "pycharm.xml",
        ]
        assert config.agent_target("copilot-jetbrains") == tmp_path / "idea.xml"

    def test_copilot_jetbrains_unconfigured_names_its_key(
        self, tmp_twsrt_dir: Path
    ) -> None:
        path = tmp_twsrt_dir / "config.toml"
        path.write_text(base_config())

        config = load_config(path)

        assert config.agent_target("copilot-jetbrains") is None
        with pytest.raises(ValueError, match=r"\[targets\]\.copilot_jetbrains_xml"):
            config.require_target("copilot-jetbrains")

    @pytest.mark.parametrize("value", ['"idea.xml"', "[]", '[""]', "[1]"])
    def test_malformed_jetbrains_xml_value_is_rejected(
        self, tmp_twsrt_dir: Path, value: str
    ) -> None:
        """FR-042: anything but a non-empty list of path strings fails loudly."""
        path = tmp_twsrt_dir / "config.toml"
        path.write_text(base_config(f"[targets]\ncopilot_jetbrains_xml = {value}\n"))

        with pytest.raises(ValueError, match="copilot_jetbrains_xml"):
            load_config(path)

    def test_require_target_names_the_missing_key(self, tmp_twsrt_dir: Path) -> None:
        path = tmp_twsrt_dir / "config.toml"
        path.write_text(base_config())

        config = load_config(path)

        with pytest.raises(ValueError, match=r"copilot.*\[targets\]\.copilot_output"):
            config.require_target("copilot")

    def test_codex_rules_without_codex_config_is_rejected(
        self, tmp_twsrt_dir: Path
    ) -> None:
        """A rules path alone would half-configure an agent; fail loudly."""
        path = tmp_twsrt_dir / "config.toml"
        path.write_text(base_config('[targets]\ncodex_rules = "x.txt"\n'))

        with pytest.raises(ValueError, match="codex_rules requires codex_config"):
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


class TestUnknownKeys:
    """ADR 0010 decision 8: nothing in config.toml is silently ignored."""

    def test_a_misspelled_table_is_rejected_by_name(self, tmp_twsrt_dir: Path) -> None:
        path = tmp_twsrt_dir / "config.toml"
        path.write_text(base_config('[target]\ncopilot_output = "flags.txt"\n'))

        with pytest.raises(ValueError, match=r"config\.toml: unknown key\(s\): target"):
            load_config(path)

    def test_a_misspelled_target_is_rejected_and_the_known_ones_are_listed(
        self, tmp_twsrt_dir: Path
    ) -> None:
        path = tmp_twsrt_dir / "config.toml"
        path.write_text(
            base_config('[targets]\nclaude_setings = "~/.claude/settings.json"\n')
        )

        with pytest.raises(
            ValueError,
            match=r"targets: unknown key\(s\): claude_setings.*known: .*claude_settings",
        ):
            load_config(path)

    def test_a_misspelled_source_output_is_rejected(self, tmp_twsrt_dir: Path) -> None:
        """It would silently move the canonical srt settings to the default path."""
        path = tmp_twsrt_dir / "config.toml"
        path.write_text(base_config().replace('output = "~/.srt', 'outptu = "~/.srt'))

        with pytest.raises(ValueError, match=r"sources\.srt: unknown key.*outptu"):
            load_config(path)

    def test_an_unknown_fragment_key_is_rejected(self, tmp_twsrt_dir: Path) -> None:
        path = tmp_twsrt_dir / "config.toml"
        path.write_text(
            base_config().replace(
                'path = "srt/base.jsonc"', 'path = "srt/base.jsonc"\nenabled = false'
            )
        )

        with pytest.raises(
            ValueError, match=r"sources\.srt\.fragments\.base: unknown key.*enabled"
        ):
            load_config(path)

    def test_every_documented_target_key_is_known(self, tmp_twsrt_dir: Path) -> None:
        path = tmp_twsrt_dir / "config.toml"
        path.write_text(
            base_config(
                "[targets]\n"
                'claude_settings = "~/.claude/settings.json"\n'
                'copilot_settings = "~/.copilot/settings.json"\n'
                'copilot_output = "copilot-flags.txt"\n'
                'copilot_jetbrains_xml = ["~/idea/github-copilot.xml"]\n'
                'codex_config = "~/.codex/config.toml"\n'
                'codex_rules = "~/.codex/rules/twsrt.rules"\n'
            )
        )

        config = load_config(path)

        assert config.agent_target("claude") is not None
        assert config.agent_target("codex") is not None


class TestProfileNames:
    """ADR 0010 decision 7: a profile name is a directory below ./.twsrt/."""

    @pytest.mark.parametrize(
        "name", ["../evil", "a/b", "a\\b", "..", ".", ".gitignore", ""]
    )
    def test_a_name_that_is_not_one_path_component_is_rejected(
        self, tmp_twsrt_dir: Path, name: str
    ) -> None:
        path = tmp_twsrt_dir / "config.toml"
        path.write_text(base_config(f"[profiles.'{name}']\nsrt = ['base']\n"))

        with pytest.raises(ValueError, match="not a valid profile name"):
            load_config(path)

    @pytest.mark.parametrize("name", ["work", "personal-srt", "v1.2", "über"])
    def test_ordinary_names_are_accepted(self, tmp_twsrt_dir: Path, name: str) -> None:
        path = tmp_twsrt_dir / "config.toml"
        path.write_text(base_config(f'[profiles."{name}"]\nextends = ["default"]\n'))

        assert name in load_config(path).profiles

    @pytest.mark.parametrize("escape", ["\\n", "\\u0000", "\\u001b", "\\u200b"])
    def test_an_unprintable_character_is_rejected(
        self, tmp_twsrt_dir: Path, escape: str
    ) -> None:
        path = tmp_twsrt_dir / "config.toml"
        path.write_text(base_config(f'[profiles."a{escape}b"]\nsrt = ["base"]\n'))

        with pytest.raises(ValueError, match="not a valid profile name"):
            load_config(path)

    @pytest.mark.parametrize(
        ("first", "second"),
        [
            ("slim", "Slim"),
            ("straße", "STRASSE"),
            # Composed and decomposed u-umlaut: one directory on APFS.
            ("\u00fcber", "u\u0308ber"),
        ],
    )
    def test_names_sharing_a_directory_on_macos_are_rejected(
        self, tmp_twsrt_dir: Path, first: str, second: str
    ) -> None:
        path = tmp_twsrt_dir / "config.toml"
        path.write_text(
            base_config(
                f'[profiles."{first}"]\nsrt = ["base"]\n'
                f'[profiles."{second}"]\nsrt = ["base"]\n'
            )
        )

        with pytest.raises(ValueError, match="same directory") as error:
            load_config(path)
        assert repr(first) in str(error.value)
        assert repr(second) in str(error.value)


class TestRemovedKeys:
    """ADR 0010 decision 8: a 3.x config fails with the replacement named."""

    def test_sandbox_overrides(self, tmp_twsrt_dir: Path) -> None:
        path = tmp_twsrt_dir / "config.toml"
        path.write_text(base_config("[sandbox_overrides.yolo]\nenabled = true\n"))

        with pytest.raises(
            ValueError, match="sandbox_overrides was removed.*always enabled.*ADR 0010"
        ):
            load_config(path)

    def test_claude_sync(self, tmp_twsrt_dir: Path) -> None:
        path = tmp_twsrt_dir / "config.toml"
        path.write_text(base_config("[claude_sync]\nmode_specific = []\n"))

        with pytest.raises(
            ValueError, match="claude_sync was removed.*one settings.json.*ADR 0010"
        ):
            load_config(path)

    def test_every_removed_key_of_a_table_is_reported_at_once(
        self, tmp_twsrt_dir: Path
    ) -> None:
        path = tmp_twsrt_dir / "config.toml"
        path.write_text(
            base_config("[claude_sync]\n[sandbox_overrides.yolo]\nenabled = true\n")
        )

        with pytest.raises(ValueError, match="(?s)claude_sync was.*sandbox_overrides"):
            load_config(path)

    def test_claude_settings_must_be_the_file_claude_reads(
        self, tmp_twsrt_dir: Path
    ) -> None:
        """A 3.x value: -w would update a file no longer linked to settings.json,
        and Claude would keep running the old policy."""
        path = tmp_twsrt_dir / "config.toml"
        path.write_text(
            base_config('[targets]\nclaude_settings = "~/.claude/settings.full.json"\n')
        )

        with pytest.raises(
            ValueError, match=r"claude_settings must be named settings\.json.*ADR 0010"
        ):
            load_config(path)

    @pytest.mark.parametrize("key", ["claude_settings_yolo", "copilot_output_yolo"])
    def test_yolo_targets(self, tmp_twsrt_dir: Path, key: str) -> None:
        path = tmp_twsrt_dir / "config.toml"
        path.write_text(base_config(f'[targets]\n{key} = "x"\n'))

        with pytest.raises(
            ValueError, match=f"{key} was removed.*select a profile.*ADR 0010"
        ):
            load_config(path)


class TestTablesMustBeTables:
    """ADR 0010 decision 8: a wrongly typed table is neither ignored nor a crash."""

    @pytest.mark.parametrize(
        "targets",
        [
            "targets = []\n",
            'targets = ""\n',
            "targets = false\n",
        ],
    )
    def test_a_targets_value_is_rejected(
        self, tmp_twsrt_dir: Path, targets: str
    ) -> None:
        path = tmp_twsrt_dir / "config.toml"
        path.write_text(targets + base_config())

        with pytest.raises(ValueError, match="targets must be a table"):
            load_config(path)

    def test_a_targets_array_of_tables_is_rejected(self, tmp_twsrt_dir: Path) -> None:
        path = tmp_twsrt_dir / "config.toml"
        path.write_text(
            base_config('[[targets]]\nclaude_settings = "~/.claude/settings.json"\n')
        )

        with pytest.raises(ValueError, match="targets must be a table"):
            load_config(path)

    def test_a_profiles_array_of_tables_is_rejected(self, tmp_twsrt_dir: Path) -> None:
        path = tmp_twsrt_dir / "config.toml"
        path.write_text(base_config().replace("[profiles.default]", "[[profiles]]"))

        with pytest.raises(ValueError, match="profiles must be a table"):
            load_config(path)

    def test_a_sources_array_of_tables_is_rejected(self, tmp_twsrt_dir: Path) -> None:
        path = tmp_twsrt_dir / "config.toml"
        path.write_text(
            'schema_version = 1\ndefault_profile = "default"\n'
            '[[sources]]\noutput = "x"\n'
        )

        with pytest.raises(ValueError, match="sources must be a table"):
            load_config(path)

    def test_a_fragments_array_of_tables_is_rejected(self, tmp_twsrt_dir: Path) -> None:
        path = tmp_twsrt_dir / "config.toml"
        path.write_text(
            base_config().replace(
                "[sources.bash.fragments.base]", "[[sources.bash.fragments]]"
            )
        )

        with pytest.raises(
            ValueError, match=r"sources\.bash\.fragments must be a table"
        ):
            load_config(path)
