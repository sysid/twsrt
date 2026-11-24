"""Tests for CLI commands: init, version, generate, edit."""

import json
from pathlib import Path
from unittest.mock import MagicMock, patch

import click
import pytest
from typer.testing import CliRunner

from twsrt.bin.cli import __version__, _editor_argv, _resolve_editor, app
from twsrt.lib.config import load_config
from twsrt.lib.models import Action, Scope, SecurityRule, Source

runner = CliRunner()


def _help_text(*argv: str) -> str:
    """Rendered --help as plain words.

    Typer forces Rich styling at import time under GITHUB_ACTIONS/FORCE_COLOR,
    and NO_COLOR drops colour but not bold, so escape codes can split a phrase.
    Rich also wraps at terminal width, and a narrow one splits option help
    across table-cell borders: pin a wide terminal and compare words, not lines.
    """
    result = runner.invoke(app, [*argv, "--help"], env={"COLUMNS": "200"})
    assert result.exit_code == 0, result.output
    return " ".join(click.unstyle(result.output).split())


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
        assert "config" in result.output

    def test_top_level_help_explains_canonical_config_feeds_agent_translations(
        self,
    ) -> None:
        help_text = _help_text()

        assert "canonical config" in help_text
        assert "input for every agent translation" in help_text

    def test_show_help_says_its_output_is_the_input_for_agent_translations(
        self,
    ) -> None:
        help_text = _help_text("show")

        assert "input for every agent translation" in help_text


class TestDiagnosticOutput:
    def test_warning_is_yellow_on_stderr_without_coloring_generated_stdout(
        self, tmp_path: Path
    ) -> None:
        config = _make_config(tmp_path, {}, {"deny": [], "ask": ["git push"]})

        result = runner.invoke(
            app,
            ["-c", str(config), "generate", "copilot"],
            env={"NO_COLOR": None},
            color=True,
        )

        assert result.exit_code == 0, result.output
        assert "--deny-tool 'shell(git push)'" in result.stdout
        assert "\x1b[" not in result.stdout
        assert "Warning:" in result.stderr
        assert "\x1b[33m" in result.stderr

    def test_no_color_disables_ansi_even_for_color_capable_terminal(
        self, tmp_path: Path
    ) -> None:
        config = _make_config(tmp_path, {}, {"deny": [], "ask": ["git push"]})

        result = runner.invoke(
            app,
            ["-c", str(config), "generate", "copilot"],
            env={"NO_COLOR": ""},
            color=True,
        )

        assert result.exit_code == 0, result.output
        assert "Warning:" in result.stderr
        assert "\x1b[" not in result.stderr

    def test_error_is_red_on_stderr(self, tmp_path: Path) -> None:
        config = tmp_path / "missing.toml"

        result = runner.invoke(
            app,
            ["-c", str(config), "config"],
            env={"NO_COLOR": None},
            color=True,
        )

        assert result.exit_code == 2
        assert "Error:" in result.stderr
        assert "\x1b[31m" in result.stderr

    def test_verbose_reports_secret_safe_lifecycle_debug_to_stderr(
        self, tmp_path: Path
    ) -> None:
        config = _make_config(tmp_path, {}, {"deny": [], "ask": ["git push"]})

        result = runner.invoke(
            app,
            ["--verbose", "-c", str(config), "generate", "claude"],
            env={"NO_COLOR": None},
            color=True,
        )

        assert result.exit_code == 0, result.output
        assert "Debug:" in result.stderr
        assert "profile 'default'" in result.stderr
        assert "rules=" in result.stderr
        assert "git push" not in result.stderr
        assert "\x1b[36m" in result.stderr
        assert "Debug:" not in result.stdout

    def test_normal_execution_has_no_debug_output(self, tmp_path: Path) -> None:
        config = _make_config(tmp_path, {})

        result = runner.invoke(app, ["-c", str(config), "generate", "claude"])

        assert result.exit_code == 0, result.output
        assert "Debug:" not in result.stderr

    def test_verbose_error_includes_traceback_and_concise_error(
        self, tmp_path: Path
    ) -> None:
        config = _make_config(tmp_path, {})
        (tmp_path / "srt.jsonc").write_text("{invalid")

        result = runner.invoke(
            app,
            ["--verbose", "-c", str(config), "generate", "claude"],
        )

        assert result.exit_code == 1
        assert "Debug: Generation failed" in result.stderr
        assert "Traceback (most recent call last)" in result.stderr
        assert "Error:" in result.stderr

    def test_diff_styles_clean_and_drift_results(self, tmp_path: Path) -> None:
        config, claude_target, _ = _make_config_with_targets(
            tmp_path, {}, {"deny": ["rm"], "ask": []}
        )
        generated = runner.invoke(
            app,
            ["-c", str(config), "generate", "claude", "--write"],
        )
        assert generated.exit_code == 0, generated.output
        claude_target.write_text("{}")

        # color=True reaches click only; rich detects the terminal itself and
        # needs FORCE_COLOR. On a real TTY both decide alike.
        result = runner.invoke(
            app,
            ["-c", str(config), "diff", "claude"],
            env={"NO_COLOR": None, "FORCE_COLOR": "1"},
            color=True,
        )

        assert result.exit_code == 1
        assert "canonical: no drift" in result.stdout
        assert "\x1b[32m" in result.stdout
        assert "claude:" in result.stdout
        assert "\x1b[33m" in result.stdout


class TestInit:
    def test_init_creates_dir_and_files(self, tmp_path: Path) -> None:
        twsrt_dir = tmp_path / "config" / "twsrt"
        config = twsrt_dir / "config.toml"
        with patch("twsrt.bin.cli.subprocess.run") as run:
            run.return_value = MagicMock(returncode=0)
            result = runner.invoke(app, ["-c", str(config), "config", "--init"])
        assert result.exit_code == 0
        assert twsrt_dir.exists()
        assert config.exists()
        assert (twsrt_dir / "srt/base.jsonc").exists()
        assert (twsrt_dir / "bash/base.jsonc").exists()

    def test_init_existing_files_skips_with_warning(self, tmp_path: Path) -> None:
        twsrt_dir = tmp_path / "config" / "twsrt"
        twsrt_dir.mkdir(parents=True)
        (twsrt_dir / "config.toml").write_text("existing")
        config = twsrt_dir / "config.toml"
        with patch("twsrt.bin.cli.subprocess.run") as run:
            run.return_value = MagicMock(returncode=0)
            result = runner.invoke(app, ["-c", str(config), "config", "--init"])
        assert result.exit_code == 0
        assert config.read_text() == "existing"

    def test_init_creates_comprehensive_config_toml(self, tmp_path: Path) -> None:
        """US3: init creates config with a settings.json default, commented out."""
        twsrt_dir = tmp_path / "config" / "twsrt"
        config = twsrt_dir / "config.toml"
        with patch("twsrt.bin.cli.subprocess.run") as run:
            run.return_value = MagicMock(returncode=0)
            result = runner.invoke(app, ["-c", str(config), "config", "--init"])
        assert result.exit_code == 0
        content = config.read_text()
        # Default claude_settings is the file Claude Code reads
        assert 'claude_settings = "~/.claude/settings.json"' in content
        # Copilot should be commented out
        assert "# copilot_output" in content
        assert "[sources.srt.fragments.base]" in content
        assert "[profiles.default]" in content
        assert "[targets]" in content

    def test_init_force_overwrites(self, tmp_path: Path) -> None:
        twsrt_dir = tmp_path / "config" / "twsrt"
        twsrt_dir.mkdir(parents=True)
        (twsrt_dir / "config.toml").write_text("old")
        config = twsrt_dir / "config.toml"
        with patch("twsrt.bin.cli.subprocess.run") as run:
            run.return_value = MagicMock(returncode=0)
            result = runner.invoke(app, ["-c", str(config), "config", "--init"])
        assert result.exit_code == 0
        assert config.read_text() == "old"


class TestEdit:
    """`twsrt edit` opens the fragments the resolved profile is made of."""

    def test_dry_run_names_the_fragments_without_opening_an_editor(
        self, srt_file: Path, bash_rules_file: Path, config_toml_file: Path
    ) -> None:
        with patch("twsrt.bin.cli.subprocess.run") as run:
            result = runner.invoke(app, ["-c", str(config_toml_file), "edit", "-n"])

        assert result.exit_code == 0, result.output
        assert str(srt_file) in result.stdout
        assert str(bash_rules_file) in result.stdout
        run.assert_not_called()

    def test_every_fragment_opens_in_one_editor_invocation(
        self,
        srt_file: Path,
        bash_rules_file: Path,
        config_toml_file: Path,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        monkeypatch.setenv("EDITOR", "dummy-editor")
        with patch("twsrt.bin.cli.subprocess.run") as run:
            run.return_value = MagicMock(returncode=0)
            result = runner.invoke(app, ["-c", str(config_toml_file), "edit"])

        assert result.exit_code == 0, result.output
        run.assert_called_once()
        argv = run.call_args[0][0]
        # Source kind order follows config.toml: srt before bash.
        assert argv[1:] == [str(srt_file), str(bash_rules_file)]

    def test_one_source_kind_can_be_selected(
        self,
        srt_file: Path,
        bash_rules_file: Path,
        config_toml_file: Path,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        monkeypatch.setenv("EDITOR", "dummy-editor")
        with patch("twsrt.bin.cli.subprocess.run") as run:
            run.return_value = MagicMock(returncode=0)
            result = runner.invoke(app, ["-c", str(config_toml_file), "edit", "srt"])

        assert result.exit_code == 0, result.output
        assert run.call_args[0][0][1:] == [str(srt_file)]

    def test_an_unknown_kind_lists_the_available_ones(
        self, srt_file: Path, bash_rules_file: Path, config_toml_file: Path
    ) -> None:
        result = runner.invoke(app, ["-c", str(config_toml_file), "edit", "bogus"])

        assert result.exit_code == 1
        assert "bogus" in result.stderr
        assert "srt" in result.stderr and "bash" in result.stderr

    def test_an_editor_with_arguments_is_split_into_argv(
        self,
        srt_file: Path,
        bash_rules_file: Path,
        config_toml_file: Path,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        """EDITOR='nvim -p' must exec nvim, not a binary called 'nvim -p'."""
        monkeypatch.setenv("EDITOR", "nvim -p")

        with patch("twsrt.bin.cli.subprocess.run") as run:
            run.return_value = MagicMock(returncode=0)
            result = runner.invoke(app, ["-c", str(config_toml_file), "edit"])

        assert result.exit_code == 0, result.output
        assert run.call_args[0][0][:2] == ["nvim", "-p"]

    def test_the_editor_exit_code_is_passed_through(
        self, srt_file: Path, bash_rules_file: Path, config_toml_file: Path
    ) -> None:
        with patch("twsrt.bin.cli.subprocess.run") as run:
            run.return_value = MagicMock(returncode=3)
            result = runner.invoke(app, ["-c", str(config_toml_file), "edit"])

        assert result.exit_code == 3

    def test_a_missing_editor_is_reported(
        self,
        srt_file: Path,
        bash_rules_file: Path,
        config_toml_file: Path,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        monkeypatch.setenv("EDITOR", "definitely-not-an-editor")

        with patch("twsrt.bin.cli.subprocess.run", side_effect=FileNotFoundError):
            result = runner.invoke(app, ["-c", str(config_toml_file), "edit"])

        assert result.exit_code == 1
        assert "definitely-not-an-editor" in result.stderr

    def test_a_registered_fragment_missing_on_disk_is_info_and_still_opens(
        self, srt_file: Path, bash_rules_file: Path, config_toml_file: Path
    ) -> None:
        """Opening a not-yet-existing fragment is how you create one."""
        srt_file.unlink()

        with patch("twsrt.bin.cli.subprocess.run") as run:
            run.return_value = MagicMock(returncode=0)
            result = runner.invoke(app, ["-c", str(config_toml_file), "edit"])

        assert "Info: fragment does not exist yet" in result.stderr
        assert str(srt_file) in run.call_args[0][0]
        # The editor was mocked, so the fragment is still absent afterwards and
        # the policy still does not compile -- which the report must say.
        assert result.exit_code == 1
        assert "not found" in result.stderr.lower()

    def test_verbose_dry_run_shows_the_exact_editor_command(
        self,
        srt_file: Path,
        bash_rules_file: Path,
        config_toml_file: Path,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        """A dry run that hides the -p it would pass is not much of a dry run."""
        monkeypatch.setenv("EDITOR", "nvim")

        result = runner.invoke(
            app, ["--verbose", "-c", str(config_toml_file), "edit", "-n"]
        )

        assert result.exit_code == 0, result.output
        assert "nvim -p" in result.stderr

    def test_an_unstattable_fragment_warns_instead_of_crashing(
        self, srt_file: Path, bash_rules_file: Path, config_toml_file: Path
    ) -> None:
        """Path.exists() raises on EPERM; a sandbox or TCC-protected dir hits this."""
        real_exists = Path.exists

        def exists(self: Path, **kwargs) -> bool:
            if self == srt_file:
                raise PermissionError(1, "Operation not permitted")
            return real_exists(self, **kwargs)

        with patch.object(Path, "exists", exists):
            with patch("twsrt.bin.cli.subprocess.run") as run:
                run.return_value = MagicMock(returncode=0)
                result = runner.invoke(app, ["-c", str(config_toml_file), "edit", "-n"])

        assert result.exit_code == 0, result.output
        assert "Operation not permitted" in result.stderr
        assert str(srt_file) in result.stdout, "still offered for editing"

    def test_drift_after_editing_points_at_the_regenerate_command(
        self, srt_file: Path, bash_rules_file: Path, config_toml_file: Path
    ) -> None:
        with patch("twsrt.bin.cli.subprocess.run") as run:
            run.return_value = MagicMock(returncode=0)
            result = runner.invoke(app, ["-c", str(config_toml_file), "edit"])

        # No canonical output has ever been written, so the compiled srt
        # document cannot match disk.
        assert result.exit_code == 0, result.output
        assert "drift" in result.output
        assert "twsrt generate -w" in result.output

    def test_no_drift_is_reported_when_the_targets_are_current(
        self,
        srt_file: Path,
        bash_rules_file: Path,
        config_toml_file: Path,
        tmp_path: Path,
    ) -> None:
        with patch("twsrt.bin.cli.subprocess.run") as run:
            run.return_value = MagicMock(returncode=0)
            runner.invoke(app, ["-c", str(config_toml_file), "generate", "-w"])
            result = runner.invoke(app, ["-c", str(config_toml_file), "edit"])

        assert result.exit_code == 0, result.output
        assert "no drift" in result.output
        assert "twsrt generate -w" not in result.output

    def test_a_fragment_broken_during_editing_fails_loudly(
        self, srt_file: Path, bash_rules_file: Path, config_toml_file: Path
    ) -> None:
        """The editor still ran; the policy is now unusable and must say so."""

        def break_the_fragment(*args, **kwargs):
            srt_file.write_text("{ this is not json")
            return MagicMock(returncode=0)

        with patch("twsrt.bin.cli.subprocess.run", side_effect=break_the_fragment):
            result = runner.invoke(app, ["-c", str(config_toml_file), "edit"])

        assert result.exit_code == 1
        assert "Error" in result.stderr

    def test_a_broken_fragment_still_opens_so_it_can_be_fixed(
        self, srt_file: Path, bash_rules_file: Path, config_toml_file: Path
    ) -> None:
        """edit resolves the profile; it must not compile before opening."""
        srt_file.write_text("{ broken before we even start")

        with patch("twsrt.bin.cli.subprocess.run") as run:
            run.return_value = MagicMock(returncode=0)
            result = runner.invoke(app, ["-c", str(config_toml_file), "edit"])

        run.assert_called_once()
        assert str(srt_file) in run.call_args[0][0]
        assert result.exit_code == 1, "but the post-edit report still fails"


class TestEditorArgv:
    """One tab per file where the editor supports it; nothing clever elsewhere."""

    FILES = [Path("/tmp/a.jsonc"), Path("/tmp/b.jsonc")]

    def test_nvim_gets_a_tab_per_file(self) -> None:
        assert _editor_argv(["nvim"], self.FILES) == [
            "nvim",
            "-p",
            "/tmp/a.jsonc",
            "/tmp/b.jsonc",
        ]

    def test_the_whole_vim_family_gets_it(self) -> None:
        for name in ("vim", "gvim", "mvim"):
            assert _editor_argv([name], self.FILES)[:2] == [name, "-p"]

    def test_an_absolute_path_is_matched_on_its_basename(self) -> None:
        argv = _editor_argv(["/opt/homebrew/bin/nvim"], self.FILES)
        assert argv[:2] == ["/opt/homebrew/bin/nvim", "-p"]

    def test_an_editor_that_already_carries_arguments_is_left_alone(self) -> None:
        """`EDITOR='nvim -O'` is a stated preference; do not second-guess it."""
        assert _editor_argv(["nvim", "-O"], self.FILES) == [
            "nvim",
            "-O",
            "/tmp/a.jsonc",
            "/tmp/b.jsonc",
        ]

    def test_other_editors_just_get_the_files(self) -> None:
        assert _editor_argv(["code"], self.FILES) == [
            "code",
            "/tmp/a.jsonc",
            "/tmp/b.jsonc",
        ]

    def test_plain_vi_is_left_alone_for_portability(self) -> None:
        """vi is the fallback; a real POSIX vi has no -p."""
        assert _editor_argv(["vi"], self.FILES) == [
            "vi",
            "/tmp/a.jsonc",
            "/tmp/b.jsonc",
        ]


class TestGenerate:
    def test_generate_claude_prints_to_stdout(
        self, srt_file: Path, bash_rules_file: Path, config_toml_file: Path
    ) -> None:
        result = runner.invoke(app, ["-c", str(config_toml_file), "generate", "claude"])
        assert result.exit_code == 0, result.output
        output = json.loads(result.stdout)
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

    def test_generate_preview_lists_every_file_write_would_write(
        self, srt_file: Path, bash_rules_file: Path, config_toml_file: Path
    ) -> None:
        result = runner.invoke(app, ["-c", str(config_toml_file), "generate", "claude"])

        assert result.exit_code == 0, result.output
        assert "Would write canonical:" in result.stderr
        assert "Would write agent target:" in result.stderr
        assert "settings.json" in result.stderr
        assert "Would write" not in result.stdout

    def test_generate_preview_fails_where_write_would_fail(
        self, tmp_path: Path
    ) -> None:
        """Staging runs in the preview, so -w holds no surprises."""
        config = _make_config(tmp_path, {}, {"deny": ["rm"], "ask": []})
        claude_dir = tmp_path / ".claude"
        claude_dir.mkdir()
        (claude_dir / "settings.json").write_text("{broken")

        result = runner.invoke(app, ["-c", str(config), "generate", "claude"])

        assert result.exit_code == 1
        assert f"{claude_dir / 'settings.json'} is not valid JSON" in result.stderr
        assert (claude_dir / "settings.json").read_text() == "{broken"

    def test_generate_all_agents(
        self, srt_file: Path, bash_rules_file: Path, config_toml_file: Path
    ) -> None:
        result = runner.invoke(app, ["-c", str(config_toml_file), "generate"])
        assert result.exit_code == 0, result.output
        # Should produce valid output (JSON for claude at minimum)
        assert "permissions" in result.output

    def test_generate_without_write_says_as_info_that_nothing_was_written(
        self, srt_file: Path, bash_rules_file: Path, config_toml_file: Path
    ) -> None:
        result = runner.invoke(
            app,
            ["-c", str(config_toml_file), "generate", "claude"],
            env={"NO_COLOR": None},
            color=True,
        )

        assert result.exit_code == 0, result.output
        assert "Info: nothing written (preview only)" in result.stderr
        assert "--write" in result.stderr
        # Bold cyan like every Info line; red would read as an error.
        assert "\x1b[36m" in result.stderr
        assert "\x1b[1m" in result.stderr
        assert "\x1b[31m" not in result.stderr
        # The preview itself stays machine-readable on stdout.
        assert "nothing written" not in result.stdout
        assert json.loads(result.stdout)["permissions"]

    def test_generate_with_write_does_not_warn_about_nothing_written(
        self,
        srt_file: Path,
        bash_rules_file: Path,
        config_toml_file: Path,
        claude_settings_file: Path,
    ) -> None:
        result = runner.invoke(
            app, ["-c", str(config_toml_file), "generate", "claude", "--write"]
        )

        assert result.exit_code == 0, result.output
        assert "nothing written" not in result.output
        assert "nothing written" not in result.stderr

    def test_generate_has_no_dry_run_option(
        self, srt_file: Path, bash_rules_file: Path, config_toml_file: Path
    ) -> None:
        """The preview is the dry run; a second spelling was a no-op trap."""
        result = runner.invoke(
            app, ["-c", str(config_toml_file), "generate", "claude", "-n"]
        )

        assert result.exit_code == 2
        assert "No such option" in result.output

    def test_generate_help_names_exactly_two_modes(self) -> None:
        help_text = _help_text("generate")

        assert "Without -w nothing is written" in help_text
        assert "every file -w would write" in help_text
        assert "--dry-run" not in help_text

    def test_generate_help_says_who_decides_about_prompts(self) -> None:
        """ADR 0010: no modes; the profile lists asks, the launch answers them."""
        help_text = _help_text("generate")

        assert "The profile decides which commands ask" in help_text
        assert "the agent's own launch flags decide who answers" in help_text

    def test_generate_help_explains_staging(self) -> None:
        """The preview's strength is staging; the help must say what it is."""
        help_text = _help_text("generate")

        assert "Staging builds in memory the exact files -w writes" in help_text
        assert "only reads" in help_text

    def test_generate_help_says_write_also_rewrites_canonical_for_any_agent(
        self,
    ) -> None:
        """`generate copilot -w` rewriting ~/.srt-settings.json must not surprise."""
        help_text = _help_text("generate")

        assert "whichever agent is named" in help_text
        assert "translated from the canonical config" in help_text

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

    def test_generate_codex_previews_config_and_rules(
        self, config_toml_file: Path
    ) -> None:
        result = runner.invoke(app, ["-c", str(config_toml_file), "generate", "codex"])

        assert result.exit_code == 0, result.output
        assert 'default_permissions = "twsrt"' in result.output
        assert "twsrt.rules" in result.output
        assert 'decision = "forbidden"' in result.output
        assert "sandbox_mode" in result.output

    def test_generate_codex_write_uses_configured_user_targets(
        self, config_toml_file: Path, tmp_path: Path
    ) -> None:
        result = runner.invoke(
            app,
            ["-c", str(config_toml_file), "generate", "codex", "--write"],
        )

        assert result.exit_code == 0, result.output
        codex_config = tmp_path / ".codex" / "config.toml"
        codex_rules = tmp_path / ".codex" / "rules" / "twsrt.rules"
        assert codex_config.exists()
        assert codex_rules.exists()
        assert "Wrote:" in result.output
        assert "Restart Codex" in result.output

    def test_generate_codex_without_rules_target_writes_config_only(
        self, tmp_path: Path
    ) -> None:
        config = _make_config(
            tmp_path, {"enabled": True}, {"deny": ["rm"]}, targets=False
        )
        codex_config = tmp_path / ".codex" / "config.toml"
        config.write_text(
            config.read_text() + "\n[targets]\n" + f'codex_config = "{codex_config}"\n'
        )

        result = runner.invoke(app, ["-c", str(config), "generate", "codex", "--write"])

        assert result.exit_code == 0, result.output
        assert codex_config.exists()
        assert not (tmp_path / ".codex" / "rules").exists()
        assert "twsrt.rules" not in result.output

        diff_result = runner.invoke(app, ["-c", str(config), "diff", "codex"])
        assert diff_result.exit_code == 0, diff_result.output
        assert "codex: no drift" in diff_result.output

    def test_generate_codex_preview_does_not_write(
        self, config_toml_file: Path, tmp_path: Path
    ) -> None:
        result = runner.invoke(
            app,
            [
                "-c",
                str(config_toml_file),
                "generate",
                "codex",
            ],
        )

        assert result.exit_code == 0, result.output
        assert "Would write canonical:" in result.stderr
        assert "Would write agent target:" in result.stderr
        assert not (tmp_path / ".codex" / "config.toml").exists()


# --- US1 Acceptance Scenario Integration Tests ---


def _make_config(
    tmp_path: Path, srt: dict, bash_rules: dict | None = None, targets: bool = True
) -> Path:
    """Helper: write SRT + bash_rules + config.toml, return config path.

    targets=True configures every agent under tmp_path; pass False when the
    test appends its own [targets] table.
    """
    srt_file = tmp_path / "srt.jsonc"
    srt_file.write_text(json.dumps(srt))

    twsrt_dir = tmp_path / "config" / "twsrt"
    twsrt_dir.mkdir(parents=True)
    br_file = twsrt_dir / "bash-rules.jsonc"
    br_file.write_text(json.dumps(bash_rules or {"deny": [], "ask": []}))

    config = twsrt_dir / "config.toml"
    config.write_text(
        "schema_version = 1\n"
        'default_profile = "default"\n'
        "[sources.srt]\n"
        f'output = "{tmp_path / ".srt-settings.json"}"\n'
        "[sources.srt.fragments.base]\n"
        f'path = "{srt_file}"\n'
        "[sources.bash]\n"
        f'output = "{twsrt_dir / "bash-rules.json"}"\n'
        "[sources.bash.fragments.base]\n"
        f'path = "{br_file}"\n'
        "[profiles.default]\n"
        'srt = ["base"]\n'
        'bash = ["base"]\n'
    )
    if targets:
        config.write_text(
            config.read_text()
            + "[targets]\n"
            + f'claude_settings = "{tmp_path / ".claude" / "settings.json"}"\n'
            + f'copilot_output = "{tmp_path / "copilot-flags.txt"}"\n'
            + f'codex_config = "{tmp_path / ".codex" / "config.toml"}"\n'
        )
    return config


class TestUS1AcceptanceScenarios:
    """All 7 acceptance scenarios from spec.md US1."""

    def test_scenario_1_deny_read_all_file_tools(self, tmp_path: Path) -> None:
        """denyRead generates deny for reading and editing (Edit covers all file-editing tools)."""
        srt = {
            "filesystem": {
                "denyRead": ["~/.aws", "~/.ssh"],
            },
        }
        config = _make_config(tmp_path, srt)
        result = runner.invoke(app, ["-c", str(config), "generate", "claude"])
        assert result.exit_code == 0
        output = json.loads(result.stdout)
        deny = output["permissions"]["deny"]
        for path in ["~/.aws", "~/.ssh"]:
            assert f"Read({path})" in deny
            assert f"Read({path}/**)" in deny
            assert f"Edit({path})" in deny
            assert f"Edit({path}/**)" in deny
            # Only Edit(path) is matched by Claude Code's file permission
            # checks — Write and MultiEdit rules are dead config.
            assert f"Write({path})" not in deny
            assert f"Write({path}/**)" not in deny
            assert f"MultiEdit({path})" not in deny
            assert f"MultiEdit({path}/**)" not in deny

    def test_scenario_2_allow_write_becomes_edit_allow_rules(
        self, tmp_path: Path
    ) -> None:
        """ADR 0002: allowWrite → Edit allow rules; no raw sandbox path."""
        srt = {
            "filesystem": {
                "allowWrite": [".", "/tmp"],
            },
        }
        config = _make_config(tmp_path, srt)
        result = runner.invoke(app, ["-c", str(config), "generate", "claude"])
        assert result.exit_code == 0
        output = json.loads(result.stdout)
        # Only the always write-denied policy files; allowWrite adds no deny.
        policy = load_config(config).policy_files
        assert [
            rule
            for rule in output["permissions"]["deny"]
            if not any(path in rule for path in policy)
        ] == []
        assert output["permissions"]["allow"] == [
            "Edit(.)",
            "Edit(./**)",
            "Edit(//tmp)",
            "Edit(//tmp/**)",
        ]
        assert output["sandbox"]["filesystem"]["allowWrite"] == []

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
        output = json.loads(result.stdout)
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
        output = json.loads(result.stdout)
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
        output = json.loads(result.stdout)
        ask = output["permissions"]["ask"]
        assert "Bash(git push)" in ask
        assert "Bash(git push *)" in ask
        assert "Bash(git commit)" in ask
        assert "Bash(git commit *)" in ask
        assert "Bash(pip install)" in ask
        assert "Bash(pip install *)" in ask

    def test_scenario_6_deny_write(self, tmp_path: Path) -> None:
        """denyWrite → Edit in deny (no Read, no Write, no MultiEdit)."""
        srt = {
            "filesystem": {
                "denyWrite": ["**/.env", "**/*.pem"],
            },
        }
        config = _make_config(tmp_path, srt)
        result = runner.invoke(app, ["-c", str(config), "generate", "claude"])
        assert result.exit_code == 0
        output = json.loads(result.stdout)
        deny = output["permissions"]["deny"]
        assert "Edit(**/.env)" in deny
        assert "Edit(**/*.pem)" in deny
        assert "Write(**/.env)" not in deny
        assert "Write(**/*.pem)" not in deny
        assert "MultiEdit(**/.env)" not in deny
        assert "MultiEdit(**/*.pem)" not in deny

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
        config = _make_config(tmp_path, srt, bash_rules, targets=False)

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


class TestClaudeSettingsFile:
    """ADR 0010 decision 6: twsrt writes the one file Claude Code reads."""

    def test_a_fresh_write_creates_a_regular_settings_json(
        self, tmp_path: Path
    ) -> None:
        config = _make_config(tmp_path, {}, {"deny": ["rm"], "ask": ["git push"]})

        result = runner.invoke(app, ["-c", str(config), "generate", "claude", "-w"])

        assert result.exit_code == 0, result.output
        settings = tmp_path / ".claude" / "settings.json"
        assert not settings.is_symlink()
        assert [path.name for path in settings.parent.iterdir()] == ["settings.json"]
        written = json.loads(settings.read_text())
        assert "Bash(rm)" in written["permissions"]["deny"]
        assert "Bash(git push)" in written["permissions"]["ask"]

    def test_a_write_keeps_what_claude_code_and_the_user_put_into_the_file(
        self, tmp_path: Path
    ) -> None:
        config = _make_config(tmp_path, {}, {"deny": ["rm"], "ask": []})
        settings = tmp_path / ".claude" / "settings.json"
        settings.parent.mkdir()
        settings.write_text(
            json.dumps(
                {
                    "model": "opus",
                    "env": {"FOO": "1"},
                    "hooks": {"Stop": []},
                    "permissions": {"allow": ["mcp__memory__store"]},
                }
            )
        )

        result = runner.invoke(app, ["-c", str(config), "generate", "claude", "-w"])

        assert result.exit_code == 0, result.output
        written = json.loads(settings.read_text())
        assert written["model"] == "opus"
        assert written["env"] == {"FOO": "1"}
        assert written["hooks"] == {"Stop": []}
        assert "mcp__memory__store" in written["permissions"]["allow"]

    def test_a_3x_symlink_becomes_a_regular_file_with_the_active_modes_settings(
        self, tmp_path: Path
    ) -> None:
        """Migration: settings.json -> settings.yolo.json was written by twsrt 3.x."""
        config = _make_config(tmp_path, {}, {"deny": ["rm"], "ask": ["git push"]})
        claude_dir = tmp_path / ".claude"
        claude_dir.mkdir()
        yolo = claude_dir / "settings.yolo.json"
        yolo.write_text('{"model": "opus", "permissions": {"deny": ["Bash(old)"]}}')
        settings = claude_dir / "settings.json"
        settings.symlink_to("settings.yolo.json")
        yolo_before = yolo.read_text()

        result = runner.invoke(app, ["-c", str(config), "generate", "claude", "-w"])

        assert result.exit_code == 0, result.output
        assert not settings.is_symlink()
        written = json.loads(settings.read_text())
        assert written["model"] == "opus"
        assert "Bash(old)" not in written["permissions"]["deny"]
        assert "Bash(git push)" in written["permissions"]["ask"]
        assert yolo.read_text() == yolo_before

    def test_a_dangling_symlink_counts_as_a_missing_file(self, tmp_path: Path) -> None:
        config = _make_config(tmp_path, {}, {"deny": ["rm"], "ask": []})
        settings = tmp_path / ".claude" / "settings.json"
        settings.parent.mkdir()
        settings.symlink_to("settings.gone.json")

        result = runner.invoke(app, ["-c", str(config), "generate", "claude", "-w"])

        assert result.exit_code == 0, result.output
        assert not settings.is_symlink()
        assert "Bash(rm)" in json.loads(settings.read_text())["permissions"]["deny"]

    def test_diff_reports_an_emptied_deny_list_in_the_file_claude_reads(
        self, tmp_path: Path
    ) -> None:
        """twsrt 3.x compared the mode named on the command line and missed this."""
        config = _make_config(tmp_path, {}, {"deny": ["rm"], "ask": []})
        runner.invoke(app, ["-c", str(config), "generate", "claude", "-w"])
        settings = tmp_path / ".claude" / "settings.json"
        document = json.loads(settings.read_text())
        document["permissions"]["deny"] = []
        settings.write_text(json.dumps(document))

        result = runner.invoke(app, ["-c", str(config), "diff", "claude"])

        assert result.exit_code == 1
        assert "Bash(rm)" in result.stdout

    def test_diff_is_clean_right_after_a_write(self, tmp_path: Path) -> None:
        config = _make_config(
            tmp_path, {"network": {"allowedDomains": ["a.com"]}}, {"deny": ["rm"]}
        )
        runner.invoke(app, ["-c", str(config), "generate", "claude", "-w"])

        result = runner.invoke(app, ["-c", str(config), "diff", "claude"])

        assert result.exit_code == 0, result.output
        assert "claude: no drift" in result.stdout


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
    srt_file = tmp_path / "srt.jsonc"
    srt_file.write_text(json.dumps(srt))

    twsrt_dir = tmp_path / "config" / "twsrt"
    twsrt_dir.mkdir(parents=True)
    br_file = twsrt_dir / "bash-rules.jsonc"
    br_file.write_text(json.dumps(bash_rules or {"deny": [], "ask": []}))
    (twsrt_dir / "bash-rules.json").write_text(
        json.dumps(bash_rules or {"deny": [], "ask": []})
    )

    claude_target = tmp_path / ".claude" / "settings.json"
    claude_target.parent.mkdir(parents=True)

    copilot_target = tmp_path / "copilot-flags.txt"

    config_file = twsrt_dir / "config.toml"
    config_file.write_text(
        "schema_version = 1\n"
        'default_profile = "default"\n'
        "[sources.srt]\n"
        f'output = "{tmp_path / ".srt-settings.json"}"\n'
        "[sources.srt.fragments.base]\n"
        f'path = "{srt_file}"\n'
        "[sources.bash]\n"
        f'output = "{twsrt_dir / "bash-rules.json"}"\n'
        "[sources.bash.fragments.base]\n"
        f'path = "{br_file}"\n'
        "[profiles.default]\n"
        'srt = ["base"]\n'
        'bash = ["base"]\n'
        f'[targets]\nclaude_settings = "{claude_target}"\n'
        f'copilot_output = "{copilot_target}"\n'
    )
    # The compiled document, not the fragment verbatim: compilation adds
    # write denies (denyRead, policy files), and a raw copy would drift.
    shown = runner.invoke(app, ["-c", str(config_file), "show", "srt"])
    assert shown.exit_code == 0, shown.output
    (tmp_path / ".srt-settings.json").write_text(shown.stdout)
    return config_file, claude_target, copilot_target


def _policy_write_denies(config: Path) -> list[SecurityRule]:
    """The write denies every compile adds: config.toml and every [sources] path."""
    return [
        SecurityRule(Scope.WRITE, Action.DENY, str(path), Source.SRT_FILESYSTEM)
        for path in load_config(config).policy_files
    ]


def _policy_edit_denies(config: Path) -> list[str]:
    """Claude's form of _policy_write_denies; every policy file exists here."""
    return [f"Edit(/{rule.pattern})" for rule in _policy_write_denies(config)]


class TestDiffCommand:
    def test_diff_all_skips_codex_when_targets_are_not_configured(
        self, tmp_path: Path
    ) -> None:
        config = _make_config(tmp_path, {"enabled": True}, targets=False)
        claude_target = tmp_path / ".claude" / "settings.json"
        copilot_target = tmp_path / "copilot-flags.txt"
        config.write_text(
            config.read_text()
            + "\n[targets]\n"
            + f'claude_settings = "{claude_target}"\n'
            + f'copilot_output = "{copilot_target}"\n'
        )
        # One HOME for both steps: policy files under it are spelled ~/….
        for agent in ("claude", "copilot"):
            write_result = runner.invoke(
                app,
                ["-c", str(config), "generate", agent, "--write"],
                env={"HOME": str(tmp_path)},
            )
            assert write_result.exit_code == 0, write_result.output

        result = runner.invoke(
            app,
            ["-c", str(config), "diff"],
            env={"HOME": str(tmp_path)},
        )

        assert result.exit_code == 0, result.output
        assert "claude: no drift" in result.output
        assert "copilot: no drift" in result.output
        assert "codex: no drift" not in result.stdout
        assert "Info: codex skipped" in result.stderr

    def test_diff_codex_no_drift_exits_0(self, tmp_path: Path) -> None:
        config = _make_config(tmp_path, {"enabled": True}, targets=False)
        codex_config = tmp_path / ".codex" / "config.toml"
        codex_rules = tmp_path / ".codex" / "rules" / "twsrt.rules"
        config.write_text(
            config.read_text()
            + "\n[targets]\n"
            + f'codex_config = "{codex_config}"\n'
            + f'codex_rules = "{codex_rules}"\n'
        )
        write_result = runner.invoke(
            app, ["-c", str(config), "generate", "codex", "--write"]
        )
        assert write_result.exit_code == 0, write_result.output

        result = runner.invoke(app, ["-c", str(config), "diff", "codex"])

        assert result.exit_code == 0, result.output
        assert "codex: no drift" in result.output
        assert "sandbox_mode" in result.output

    def test_diff_codex_missing_rules_exits_2(self, tmp_path: Path) -> None:
        config = _make_config(tmp_path, {"enabled": True}, targets=False)
        codex_config = tmp_path / ".codex" / "config.toml"
        codex_config.parent.mkdir(parents=True)
        codex_config.write_text("")
        codex_rules = tmp_path / ".codex" / "rules" / "twsrt.rules"
        config.write_text(
            config.read_text()
            + "\n[targets]\n"
            + f'codex_config = "{codex_config}"\n'
            + f'codex_rules = "{codex_rules}"\n'
        )

        result = runner.invoke(app, ["-c", str(config), "diff", "codex"])

        assert result.exit_code == 2
        assert str(codex_rules) in result.output

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
        # Write existing that matches (incl. the managed-empty deny lists)
        existing = {
            "permissions": {
                "deny": ["Bash(rm)", "Bash(rm *)", *_policy_edit_denies(config)],
                "ask": [],
                "allow": [],
            },
            "sandbox": {
                "enabled": True,
                "allowUnsandboxedCommands": False,
                "network": {"allowedDomains": []},
                "filesystem": {"denyRead": [], "denyWrite": [], "allowWrite": []},
            },
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

    def test_drift_lists_bare_entries_under_a_target_header_and_one_legend(
        self, tmp_path: Path
    ) -> None:
        srt = {}
        bash_rules = {"deny": ["rm"], "ask": []}
        config, claude_target, _ = _make_config_with_targets(tmp_path, srt, bash_rules)
        # Bash(rm *) is missing, Bash(docker run:*) is extra.
        existing = {
            "permissions": {
                "deny": [
                    "Bash(rm)",
                    "Bash(docker run:*)",
                    *_policy_edit_denies(config),
                ],
                "ask": [],
                "allow": [],
            },
            "sandbox": {
                "enabled": True,
                "allowUnsandboxedCommands": False,
                "network": {"allowedDomains": []},
                "filesystem": {"denyRead": [], "denyWrite": [], "allowWrite": []},
            },
        }
        claude_target.write_text(json.dumps(existing))

        result = runner.invoke(app, ["-c", str(config), "diff", "claude"])

        assert result.exit_code == 1
        # The header names the drifted file; entries carry no per-line legend.
        assert result.stdout.splitlines()[2:] == [
            f"claude: 1 missing, 1 extra  {claude_target}",
            "  + Bash(rm *)",
            "  - Bash(docker run:*)",
            "",
            "+ missing from target   - in target, not in sources",
        ]

    def test_no_drift_prints_no_legend(self, tmp_path: Path) -> None:
        srt = {}
        bash_rules = {"deny": ["rm"], "ask": []}
        config, claude_target, _ = _make_config_with_targets(tmp_path, srt, bash_rules)
        existing = {
            "permissions": {
                "deny": ["Bash(rm)", "Bash(rm *)", *_policy_edit_denies(config)],
                "ask": [],
                "allow": [],
            },
            "sandbox": {
                "enabled": True,
                "allowUnsandboxedCommands": False,
                "network": {"allowedDomains": []},
                "filesystem": {"denyRead": [], "denyWrite": [], "allowWrite": []},
            },
        }
        claude_target.write_text(json.dumps(existing))

        result = runner.invoke(app, ["-c", str(config), "diff", "claude"])

        assert result.exit_code == 0, result.output
        assert "missing from target" not in result.stdout

    def test_no_drift_reports_clean(self, tmp_path: Path) -> None:
        srt = {}
        bash_rules = {"deny": ["rm"], "ask": []}
        config, claude_target, _ = _make_config_with_targets(tmp_path, srt, bash_rules)
        existing = {
            "permissions": {
                "deny": ["Bash(rm)", "Bash(rm *)", *_policy_edit_denies(config)],
                "ask": [],
                "allow": [],
            },
            "sandbox": {
                "enabled": True,
                "allowUnsandboxedCommands": False,
                "network": {"allowedDomains": []},
                "filesystem": {"denyRead": [], "denyWrite": [], "allowWrite": []},
            },
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
    """T001: _resolve_editor() matches twagent's $EDITOR → vi behavior."""

    def test_returns_editor_env(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("EDITOR", "nvim")
        assert _resolve_editor() == ["nvim"]

    def test_an_editor_carrying_arguments_is_split(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """`EDITOR="code -w"` is conventional; it is argv, not one binary name."""
        monkeypatch.setenv("EDITOR", "code -w")
        assert _resolve_editor() == ["code", "-w"]

    def test_falls_back_to_visual(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.delenv("EDITOR", raising=False)
        monkeypatch.setenv("VISUAL", "code")
        assert _resolve_editor() == ["vi"]

    def test_falls_back_to_vi(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.delenv("EDITOR", raising=False)
        monkeypatch.delenv("VISUAL", raising=False)
        assert _resolve_editor() == ["vi"]


class TestEditSrt:
    """T002-T004: the config command opens the active TOML."""

    def test_edit_srt_calls_editor_with_srt_path(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """T002: edit srt opens file in $EDITOR."""
        config = tmp_path / "config.toml"
        config.write_text("configured")
        monkeypatch.setenv("EDITOR", "test-editor")

        with patch("twsrt.bin.cli.subprocess") as mock_sub:
            mock_sub.run.return_value = MagicMock(returncode=0)
            result = runner.invoke(app, ["-c", str(config), "config"])

        assert result.exit_code == 0
        mock_sub.run.assert_called_once_with(["test-editor", str(config)])

    def test_edit_srt_missing_file_exits_1(self, tmp_path: Path) -> None:
        """T003: edit srt with nonexistent file reports error with path."""
        config = tmp_path / "config.toml"
        result = runner.invoke(app, ["-c", str(config), "config"])
        assert result.exit_code == 2
        assert "Use --init" in result.output

    def test_edit_srt_editor_nonzero_exit(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """T004: editor exits non-zero — warning and matching exit code."""
        config = tmp_path / "config.toml"
        config.write_text("configured")
        monkeypatch.setenv("EDITOR", "failing-editor")

        with patch("twsrt.bin.cli.subprocess") as mock_sub:
            mock_sub.run.return_value = MagicMock(returncode=2)
            result = runner.invoke(app, ["-c", str(config), "config"])

        assert result.exit_code == 2


class TestEditBash:
    """T008-T009: config --init manages starter fragments safely."""

    def test_edit_bash_calls_editor_with_bash_path(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """T008: edit bash opens file in editor."""
        config = tmp_path / "config.toml"
        monkeypatch.setenv("EDITOR", "test-editor")

        with patch("twsrt.bin.cli.subprocess") as mock_sub:
            mock_sub.run.return_value = MagicMock(returncode=0)
            result = runner.invoke(app, ["-c", str(config), "config", "--init"])

        assert result.exit_code == 0
        assert (tmp_path / "bash/base.jsonc").exists()
        mock_sub.run.assert_called_once_with(["test-editor", str(config)])

    def test_edit_bash_missing_file_exits_1(self, tmp_path: Path) -> None:
        """T009: edit bash with nonexistent file reports error."""
        config = tmp_path / "config.toml"
        config.write_text("existing")
        with patch("twsrt.bin.cli.subprocess.run") as run:
            run.return_value = MagicMock(returncode=0)
            result = runner.invoke(app, ["-c", str(config), "config", "--init"])
        assert result.exit_code == 0
        assert config.read_text() == "existing"


class TestRemovedCommands:
    """The obsolete bootstrap command stays removed.

    The sibling guard for `edit` is gone: `edit` is back, but inverted. The
    removed one opened the generated outputs (config.srt_path,
    config.bash_rules_path); TestEdit covers the replacement, which opens the
    source fragments a profile selects.
    """

    def test_init_is_not_a_command(self) -> None:
        result = runner.invoke(app, ["init"])
        assert result.exit_code == 2

    @pytest.mark.parametrize("command", ["generate", "diff"])
    def test_yolo_is_not_an_option(self, command: str) -> None:
        """ADR 0010: a profile selects policy, a launch flag selects prompting."""
        result = runner.invoke(app, [command, "--yolo"])
        assert result.exit_code == 2
        assert "No such option" in result.output


# --- Agents are opt-in: a missing [targets] key means "not configured" ---


def _make_config_for_agents(tmp_path: Path, *agents: str) -> Path:
    """Config whose [targets] configures exactly the named agents."""
    config = _make_config(tmp_path, {}, {"deny": ["rm"], "ask": []}, targets=False)
    keys = {
        "claude": f'claude_settings = "{tmp_path / ".claude" / "settings.json"}"',
        "copilot": f'copilot_output = "{tmp_path / "copilot-flags.txt"}"',
        "codex": f'codex_config = "{tmp_path / ".codex" / "config.toml"}"',
    }
    lines = "".join(f"{keys[agent]}\n" for agent in agents)
    config.write_text(config.read_text() + "[targets]\n" + lines)
    return config


class TestUnconfiguredAgents:
    @pytest.mark.parametrize(
        ("agent", "key"),
        [
            ("claude", "claude_settings"),
            # Either key configures Copilot (FR-026), so the note names both.
            ("copilot", "copilot_output or copilot_settings"),
            ("codex", "codex_config"),
        ],
    )
    @pytest.mark.parametrize("write", [False, True])
    def test_naming_an_unconfigured_agent_is_info_not_an_error(
        self, tmp_path: Path, agent: str, key: str, write: bool
    ) -> None:
        """Agents are optional: naming an absent one skips it, exit 0, for
        every agent, preview or write. No agent output is produced."""
        config = _make_config_for_agents(tmp_path)
        argv = ["-c", str(config), "generate", agent] + (["-w"] if write else [])

        result = runner.invoke(app, argv, env={"HOME": str(tmp_path / "home")})

        assert result.exit_code == 0, result.output
        assert result.stdout == ""
        assert (
            f"Info: {agent} skipped: [targets].{key} is not set in config.toml"
            in result.stderr
        )
        assert "Error" not in result.stderr
        assert not (tmp_path / "home").exists()

    def test_generate_all_previews_only_configured_agents(self, tmp_path: Path) -> None:
        config = _make_config_for_agents(tmp_path, "claude")

        result = runner.invoke(app, ["-c", str(config), "generate"])

        assert result.exit_code == 0, result.output
        assert json.loads(result.stdout)["permissions"]["deny"]
        assert "--deny-tool" not in result.stdout
        assert "default_permissions" not in result.stdout
        assert "Info: copilot skipped" in result.stderr
        assert "Info: codex skipped" in result.stderr

    def test_generate_all_write_writes_only_configured_agents(
        self, tmp_path: Path
    ) -> None:
        """An unconfigured copilot no longer dumps its flags to stdout."""
        config = _make_config_for_agents(tmp_path, "codex")

        result = runner.invoke(
            app,
            ["-c", str(config), "generate", "-w"],
            env={"HOME": str(tmp_path / "home")},
        )

        assert result.exit_code == 0, result.output
        assert result.stdout == ""
        assert (tmp_path / ".codex" / "config.toml").exists()
        assert not (tmp_path / ".claude").exists()
        assert not (tmp_path / "copilot-flags.txt").exists()
        assert not (tmp_path / "home").exists()

    def test_generate_all_without_any_agent_writes_only_canonical(
        self, tmp_path: Path
    ) -> None:
        config = _make_config_for_agents(tmp_path)

        result = runner.invoke(
            app,
            ["-c", str(config), "generate", "-w"],
            env={"HOME": str(tmp_path / "home")},
        )

        assert result.exit_code == 0, result.output
        assert result.stdout == ""
        assert "Info: no agent targets set" in result.stderr
        assert "only the canonical outputs" in result.stderr
        assert "Error" not in result.stderr
        assert (tmp_path / ".srt-settings.json").exists()
        assert not (tmp_path / "home").exists()

    def test_generate_all_preview_without_any_agent_prints_nothing(
        self, tmp_path: Path
    ) -> None:
        config = _make_config_for_agents(tmp_path)

        result = runner.invoke(app, ["-c", str(config), "generate"])

        assert result.exit_code == 0, result.output
        assert result.stdout == ""
        assert "Info: no agent targets set" in result.stderr

    def test_diff_all_skips_unconfigured_agents_with_a_note(
        self, tmp_path: Path
    ) -> None:
        config = _make_config_for_agents(tmp_path, "copilot")
        written = runner.invoke(app, ["-c", str(config), "generate", "-w"])
        assert written.exit_code == 0, written.output

        result = runner.invoke(app, ["-c", str(config), "diff"])

        assert result.exit_code == 0, result.output
        assert "copilot: no drift" in result.stdout
        assert "Info: claude skipped" in result.stderr
        assert "Info: codex skipped" in result.stderr

    def test_diff_of_an_unconfigured_agent_is_info_not_an_error(
        self, tmp_path: Path
    ) -> None:
        config = _make_config_for_agents(tmp_path)
        written = runner.invoke(app, ["-c", str(config), "generate", "-w"])
        assert written.exit_code == 0, written.output

        result = runner.invoke(app, ["-c", str(config), "diff", "claude"])

        assert result.exit_code == 0, result.output
        assert "Info: claude skipped" in result.stderr
        assert "Error" not in result.stderr

    def test_project_mode_requires_claude(self, tmp_path: Path) -> None:
        config = _make_config_for_agents(tmp_path)

        result = runner.invoke(app, ["-c", str(config), "generate", "-w", "--project"])

        # Unlike a plain skip, --project cannot run at all: it copies hooks
        # from the global Claude target.
        assert result.exit_code == 1
        assert "Error: claude is not configured" in result.stderr
        assert "Info:" not in result.stderr

    def test_doctor_runs_without_a_claude_target(self, tmp_path: Path) -> None:
        config = _make_config_for_agents(tmp_path)

        result = runner.invoke(app, ["-c", str(config), "doctor"])

        assert result.exit_code == 0, result.output


class TestInitMinimalConfig:
    def _init(self, tmp_path: Path) -> Path:
        config = tmp_path / "config" / "twsrt" / "config.toml"
        with patch("twsrt.bin.cli.subprocess.run") as run:
            run.return_value = MagicMock(returncode=0)
            result = runner.invoke(app, ["-c", str(config), "config", "--init"])
        assert result.exit_code == 0, result.output
        return config

    def test_every_target_key_is_commented_out_with_a_default(
        self, tmp_path: Path
    ) -> None:
        content = self._init(tmp_path).read_text()

        for line in (
            '# claude_settings = "~/.claude/settings.json"',
            '# copilot_output = "copilot-flags.txt"',
            '# codex_config = "~/.codex/config.toml"',
            '# codex_rules = "~/.codex/rules/twsrt.rules"',
        ):
            assert line in content

    def test_the_initial_config_configures_no_agent(self, tmp_path: Path) -> None:
        from twsrt.lib.config import load_config

        config = load_config(self._init(tmp_path))

        assert config.agent_target("claude") is None
        assert config.agent_target("copilot") is None
        assert config.agent_target("codex") is None

    def test_the_initial_config_writes_canonical_outputs_next_to_itself(
        self, tmp_path: Path
    ) -> None:
        """No output key is set: nothing lands in ~ until the user opts in."""
        from twsrt.lib.config import load_config

        config_path = self._init(tmp_path)
        config = load_config(config_path)

        assert config.sources["srt"].output_path == (
            config_path.parent / "srt-settings.json"
        )

    def test_the_bash_source_is_commented_out_with_its_defaults(
        self, tmp_path: Path
    ) -> None:
        content = self._init(tmp_path).read_text()

        for line in (
            "# [sources.bash]",
            '# output = "bash-rules.json"',
            "# [sources.bash.fragments.base]",
            '# path = "bash/base.jsonc"',
            '# bash = ["base"]',
        ):
            assert line in content

    def test_the_initial_config_configures_no_bash_source(self, tmp_path: Path) -> None:
        from twsrt.lib.config import load_config

        config = load_config(self._init(tmp_path))

        assert set(config.sources) == {"srt"}

    def test_uncommenting_the_bash_source_enables_it(self, tmp_path: Path) -> None:
        """The commented defaults are complete: removing `# ` is all it takes."""
        from twsrt.lib.config import load_config

        config_path = self._init(tmp_path)
        enabled = (
            config_path.read_text()
            .replace("# [sources.bash]\n", "[sources.bash]\n")
            .replace(
                "# [sources.bash.fragments.base]\n# path",
                "[sources.bash.fragments.base]\npath",
            )
            .replace('# bash = ["base"]', 'bash = ["base"]', 1)
        )
        config_path.write_text(enabled)

        config = load_config(config_path)

        assert config.sources["bash"].output_path == (
            config_path.parent / "bash-rules.json"
        )
        assert (config_path.parent / "bash/base.jsonc").exists()


def _make_copilot_native_config(
    tmp_path: Path, flags: bool = True, ides: tuple[str, ...] = ()
) -> Path:
    """Config with the Copilot CLI settings target and optional JetBrains IDEs."""
    srt = {
        "filesystem": {"denyRead": ["/secrets"], "allowWrite": ["."], "denyWrite": []},
        "network": {"allowedDomains": ["github.com"], "deniedDomains": ["evil.com"]},
    }
    config = _make_config(tmp_path, srt, {"deny": ["rm"], "ask": []}, targets=False)
    lines = f'copilot_settings = "{tmp_path / ".copilot" / "settings.json"}"\n'
    if flags:
        lines += f'copilot_output = "{tmp_path / "copilot-flags.txt"}"\n'
    if ides:
        xml_paths = ", ".join(
            f'"{tmp_path / ide / "options" / "github-copilot.xml"}"' for ide in ides
        )
        lines += f"copilot_jetbrains_xml = [{xml_paths}]\n"
    config.write_text(config.read_text() + "[targets]\n" + lines)
    return config


class TestCopilotNativeTargets:
    """ADR 0009: settings.json and github-copilot.xml through the CLI."""

    def test_write_merges_settings_and_drops_url_flags(self, tmp_path: Path) -> None:
        """FR-021, FR-023: foreign settings survive; URLs leave the flags."""
        config = _make_copilot_native_config(tmp_path)
        settings = tmp_path / ".copilot" / "settings.json"
        settings.parent.mkdir()
        settings.write_text(json.dumps({"model": "keep-me"}))

        result = runner.invoke(app, ["-c", str(config), "generate", "copilot", "-w"])

        assert result.exit_code == 0, result.output
        written = json.loads(settings.read_text())
        assert written["model"] == "keep-me"
        assert written["sandbox"]["userPolicy"]["filesystem"]["deniedPaths"] == [
            "/secrets"
        ]
        assert written["allowedUrls"] == ["github.com"]
        flags = (tmp_path / "copilot-flags.txt").read_text()
        assert "--deny-tool 'shell(rm)'" in flags
        assert "--allow-url" not in flags
        assert "settings:" not in flags

    def test_settings_only_config_writes_no_flags_file(self, tmp_path: Path) -> None:
        """FR-026."""
        config = _make_copilot_native_config(tmp_path, flags=False)

        result = runner.invoke(app, ["-c", str(config), "generate", "copilot", "-w"])

        assert result.exit_code == 0, result.output
        written = json.loads((tmp_path / ".copilot" / "settings.json").read_text())
        assert written["sandbox"]["enabled"] is True
        assert not (tmp_path / "copilot-flags.txt").exists()

    def test_all_writes_flags_settings_and_every_ide_file(self, tmp_path: Path) -> None:
        """FR-030."""
        config = _make_copilot_native_config(tmp_path, ides=("IdeaA", "PyCharmB"))

        result = runner.invoke(app, ["-c", str(config), "generate", "all", "-w"])

        assert result.exit_code == 0, result.output
        for ide in ("IdeaA", "PyCharmB"):
            xml = (tmp_path / ide / "options" / "github-copilot.xml").read_text()
            assert '<option name="sandboxEnabled" value="true" />' in xml

    def test_locked_ide_is_skipped_and_everything_else_written(
        self, tmp_path: Path
    ) -> None:
        """FR-033: a running IDE overrides external edits; skip it, warn, exit 0."""
        config = _make_copilot_native_config(tmp_path, ides=("IdeaA", "PyCharmB"))
        (tmp_path / "PyCharmB").mkdir()
        (tmp_path / "PyCharmB" / ".lock").write_text("")

        result = runner.invoke(app, ["-c", str(config), "generate", "all", "-w"])

        assert result.exit_code == 0, result.output
        locked_xml = tmp_path / "PyCharmB" / "options" / "github-copilot.xml"
        assert not locked_xml.exists()
        assert (tmp_path / "IdeaA" / "options" / "github-copilot.xml").exists()
        assert (tmp_path / ".srt-settings.json").exists()
        assert (tmp_path / ".copilot" / "settings.json").exists()
        assert "Warning" in result.stderr
        assert str(locked_xml) in result.stderr
        # A crashed IDE leaves its lock behind; the user must learn that too.
        assert "stale" in result.stderr

    def test_preview_names_the_ide_file_it_would_skip(self, tmp_path: Path) -> None:
        """FR-033: preview tells what -w would leave alone."""
        config = _make_copilot_native_config(tmp_path, ides=("IdeaA",))
        (tmp_path / "IdeaA").mkdir()
        (tmp_path / "IdeaA" / ".lock").write_text("")

        result = runner.invoke(
            app, ["-c", str(config), "generate", "copilot-jetbrains"]
        )

        assert result.exit_code == 0, result.output
        assert "skip" in result.stderr
        assert str(tmp_path / "IdeaA" / "options" / "github-copilot.xml") in (
            result.stderr
        )

    def test_diff_after_write_reports_no_drift(self, tmp_path: Path) -> None:
        """FR-024, FR-034 end to end."""
        config = _make_copilot_native_config(tmp_path, ides=("IdeaA",))
        runner.invoke(app, ["-c", str(config), "generate", "all", "-w"])

        result = runner.invoke(app, ["-c", str(config), "diff", "all"])

        assert result.exit_code == 0, result.output
        assert "copilot: no drift" in result.stdout
        assert "copilot-jetbrains: no drift" in result.stdout

    def test_diff_reports_a_missing_first_ide_file_as_drift(
        self, tmp_path: Path
    ) -> None:
        """FR-030: every listed file is compared, whatever its position."""
        config = _make_copilot_native_config(tmp_path, ides=("IdeaA", "PyCharmB"))
        runner.invoke(app, ["-c", str(config), "generate", "all", "-w"])
        missing = tmp_path / "IdeaA" / "options" / "github-copilot.xml"
        missing.unlink()

        result = runner.invoke(app, ["-c", str(config), "diff", "copilot-jetbrains"])

        assert result.exit_code == 1, result.output
        assert "Target file not found" not in result.stderr
        assert str(missing) in result.output

    def test_shared_policy_warnings_are_printed_once(self, tmp_path: Path) -> None:
        """Both Copilot generators build the same policy; one warning each."""
        config = _make_copilot_native_config(tmp_path, ides=("IdeaA",))

        result = runner.invoke(app, ["-c", str(config), "generate", "all"])

        assert result.exit_code == 0, result.output
        assert result.stderr.count("in-process") == 1

    def test_project_mode_rejects_copilot_jetbrains(self, tmp_path: Path) -> None:
        """FR-041: JetBrains settings are global to the IDE."""
        config = _make_copilot_native_config(tmp_path, ides=("IdeaA",))

        result = runner.invoke(
            app, ["-c", str(config), "generate", "--project", "copilot-jetbrains"]
        )

        assert result.exit_code == 1
        assert "copilot-jetbrains" in result.stderr
        assert "--project" in result.stderr

    def test_locked_ide_warning_is_red_unlike_other_warnings(
        self, tmp_path: Path
    ) -> None:
        """The skipped IDE keeps its old policy: make it stand out (still a
        Warning, exit 0), while ordinary warnings stay yellow."""
        config = _make_copilot_native_config(tmp_path, ides=("IdeaA",))
        (tmp_path / "IdeaA").mkdir()
        (tmp_path / "IdeaA" / ".lock").write_text("")

        result = runner.invoke(
            app,
            ["-c", str(config), "generate", "copilot-jetbrains"],
            env={"NO_COLOR": None},
            color=True,
        )

        assert result.exit_code == 0, result.output
        lock_line = next(ln for ln in result.stderr.splitlines() if ".lock" in ln)
        assert "Warning:" in lock_line
        assert "\x1b[31m" in lock_line
        other = [ln for ln in result.stderr.splitlines() if "in-process" in ln]
        assert other and "\x1b[33m" in other[0]
