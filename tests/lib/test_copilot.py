"""Tests for Copilot CLI flag and settings.json generation."""

import json
from pathlib import Path

import pytest

from twsrt.lib.copilot import CopilotGenerator
from twsrt.lib.models import Action, AppConfig, Scope, SecurityRule, Source


@pytest.fixture
def gen() -> CopilotGenerator:
    return CopilotGenerator()


@pytest.fixture
def config() -> AppConfig:
    return AppConfig()


class TestCopilotGeneration:
    def test_bash_deny_generates_deny_tool(
        self, gen: CopilotGenerator, config: AppConfig
    ) -> None:
        rules = [
            SecurityRule(Scope.EXECUTE, Action.DENY, "rm", Source.BASH_RULES),
            SecurityRule(Scope.EXECUTE, Action.DENY, "sudo", Source.BASH_RULES),
        ]
        output = gen.generate(rules, config)
        assert "--deny-tool 'shell(rm)'" in output
        assert "--deny-tool 'shell(sudo)'" in output

    def test_allow_write_generates_allow_tools(
        self, gen: CopilotGenerator, config: AppConfig
    ) -> None:
        """FR-008: allowWrite → allow-tool flags for copilot."""
        rules = [
            SecurityRule(Scope.WRITE, Action.ALLOW, ".", Source.SRT_FILESYSTEM),
            SecurityRule(Scope.WRITE, Action.ALLOW, "/tmp", Source.SRT_FILESYSTEM),
        ]
        output = gen.generate(rules, config)
        assert "--allow-tool 'shell'" in output
        assert "--allow-tool 'read'" in output
        assert "--allow-tool 'edit'" in output
        assert "--allow-tool 'write'" in output

    def test_one_flag_per_line(self, gen: CopilotGenerator, config: AppConfig) -> None:
        rules = [
            SecurityRule(Scope.EXECUTE, Action.DENY, "rm", Source.BASH_RULES),
            SecurityRule(Scope.EXECUTE, Action.DENY, "sudo", Source.BASH_RULES),
        ]
        output = gen.generate(rules, config)
        lines = [line for line in output.strip().split("\n") if line.strip()]
        for line in lines:
            assert line.strip().rstrip(" \\").startswith("--")

    def test_lines_have_continuation_backslash(
        self, gen: CopilotGenerator, config: AppConfig
    ) -> None:
        """Each line ends with ' \\' for shell line continuation."""
        rules = [
            SecurityRule(Scope.EXECUTE, Action.DENY, "rm", Source.BASH_RULES),
            SecurityRule(Scope.EXECUTE, Action.DENY, "sudo", Source.BASH_RULES),
        ]
        output = gen.generate(rules, config)
        lines = [line for line in output.strip().split("\n") if line.strip()]
        for line in lines:
            assert line.endswith(" \\")

    def test_no_srt_wrapper(self, gen: CopilotGenerator, config: AppConfig) -> None:
        """FR-005: no wrapper function or srt -c in output."""
        rules = [
            SecurityRule(Scope.EXECUTE, Action.DENY, "rm", Source.BASH_RULES),
        ]
        output = gen.generate(rules, config)
        assert "srt" not in output.lower() or "srt" in "assert"  # avoid false positive
        assert "function" not in output.lower()

    def test_deny_read_no_copilot_output(
        self, gen: CopilotGenerator, config: AppConfig
    ) -> None:
        """denyRead: SRT handles at OS level, no Copilot flags."""
        rules = [
            SecurityRule(Scope.READ, Action.DENY, "**/.aws", Source.SRT_FILESYSTEM),
        ]
        output = gen.generate(rules, config)
        assert output.strip() == ""

    def test_deny_write_no_copilot_output(
        self, gen: CopilotGenerator, config: AppConfig
    ) -> None:
        """denyWrite: SRT handles at OS level, no Copilot flags."""
        rules = [
            SecurityRule(Scope.WRITE, Action.DENY, "**/.env", Source.SRT_FILESYSTEM),
        ]
        output = gen.generate(rules, config)
        assert output.strip() == ""

    def test_network_allow_generates_allow_url(
        self, gen: CopilotGenerator, config: AppConfig
    ) -> None:
        """FR-001: NETWORK/ALLOW → --allow-url flags."""
        rules = [
            SecurityRule(Scope.NETWORK, Action.ALLOW, "github.com", Source.SRT_NETWORK),
            SecurityRule(
                Scope.NETWORK, Action.ALLOW, "*.npmjs.org", Source.SRT_NETWORK
            ),
        ]
        output = gen.generate(rules, config)
        assert "--allow-url 'github.com'" in output
        assert "--allow-url '*.npmjs.org'" in output

    def test_allow_url_one_per_line(
        self, gen: CopilotGenerator, config: AppConfig
    ) -> None:
        """FR-002: each --allow-url on its own line."""
        rules = [
            SecurityRule(Scope.NETWORK, Action.ALLOW, "a.com", Source.SRT_NETWORK),
            SecurityRule(Scope.NETWORK, Action.ALLOW, "b.com", Source.SRT_NETWORK),
        ]
        output = gen.generate(rules, config)
        lines = [line for line in output.strip().split("\n") if line.strip()]
        allow_url_lines = [ln for ln in lines if "--allow-url" in ln]
        assert len(allow_url_lines) == 2

    def test_network_deny_generates_deny_url(
        self, gen: CopilotGenerator, config: AppConfig
    ) -> None:
        """FR-005: NETWORK/DENY → --deny-url flags."""
        rules = [
            SecurityRule(Scope.NETWORK, Action.DENY, "evil.com", Source.SRT_NETWORK),
            SecurityRule(
                Scope.NETWORK, Action.DENY, "*.tracker.net", Source.SRT_NETWORK
            ),
        ]
        output = gen.generate(rules, config)
        assert "--deny-url 'evil.com'" in output
        assert "--deny-url '*.tracker.net'" in output

    def test_deny_url_one_per_line(
        self, gen: CopilotGenerator, config: AppConfig
    ) -> None:
        """Each --deny-url on its own line."""
        rules = [
            SecurityRule(Scope.NETWORK, Action.DENY, "a.com", Source.SRT_NETWORK),
            SecurityRule(Scope.NETWORK, Action.DENY, "b.com", Source.SRT_NETWORK),
        ]
        output = gen.generate(rules, config)
        lines = [line for line in output.strip().split("\n") if line.strip()]
        deny_url_lines = [ln for ln in lines if "--deny-url" in ln]
        assert len(deny_url_lines) == 2


class TestCopilotLossyMapping:
    """FR-012: Bash ask mapped to deny-tool with warning."""

    def test_ask_mapped_to_deny_tool(
        self, gen: CopilotGenerator, config: AppConfig
    ) -> None:
        rules = [
            SecurityRule(Scope.EXECUTE, Action.ASK, "git push", Source.BASH_RULES),
            SecurityRule(Scope.EXECUTE, Action.ASK, "pip install", Source.BASH_RULES),
        ]
        output = gen.generate(rules, config)
        assert "--deny-tool 'shell(git push)'" in output
        assert "--deny-tool 'shell(pip install)'" in output

    def test_ask_emits_warning(
        self,
        gen: CopilotGenerator,
        config: AppConfig,
        capsys: pytest.CaptureFixture[str],
    ) -> None:
        rules = [
            SecurityRule(Scope.EXECUTE, Action.ASK, "git push", Source.BASH_RULES),
        ]
        gen.generate(rules, config)
        captured = capsys.readouterr()
        warnings = gen.compatibility_warnings(rules, config)

        assert captured.out == ""
        assert captured.err == ""
        assert any("no ask equivalent" in warning.lower() for warning in warnings)


class TestCopilotYoloGeneration:
    """T013-T015: Copilot YOLO mode generates --yolo + deny-only flags."""

    def test_yolo_output_starts_with_yolo_flag(
        self, gen: CopilotGenerator, config: AppConfig
    ) -> None:
        """T013: yolo output starts with --yolo, has --deny-tool for DENY only, no --allow-*."""
        config.yolo = True
        rules = [
            SecurityRule(Scope.EXECUTE, Action.DENY, "rm", Source.BASH_RULES),
            SecurityRule(Scope.EXECUTE, Action.ASK, "git push", Source.BASH_RULES),
            SecurityRule(Scope.WRITE, Action.ALLOW, ".", Source.SRT_FILESYSTEM),
            SecurityRule(Scope.NETWORK, Action.ALLOW, "github.com", Source.SRT_NETWORK),
        ]
        output = gen.generate(rules, config)
        lines = [line.strip() for line in output.strip().split("\n") if line.strip()]

        # First line must be --yolo
        assert lines[0].startswith("--yolo")

        # DENY rule present
        assert any("--deny-tool 'shell(rm)'" in line for line in lines)

        # ASK rule absent (not mapped to --deny-tool in yolo mode)
        assert not any("git push" in line for line in lines)

        # No --allow-tool or --allow-url (subsumed by --yolo)
        assert not any("--allow-tool" in line for line in lines)
        assert not any("--allow-url" in line for line in lines)

    def test_yolo_includes_deny_url(
        self, gen: CopilotGenerator, config: AppConfig
    ) -> None:
        """T014: yolo mode includes --deny-url for NETWORK/DENY rules."""
        config.yolo = True
        rules = [
            SecurityRule(Scope.NETWORK, Action.DENY, "evil.com", Source.SRT_NETWORK),
            SecurityRule(Scope.NETWORK, Action.ALLOW, "github.com", Source.SRT_NETWORK),
        ]
        output = gen.generate(rules, config)
        assert "--deny-url 'evil.com'" in output
        assert "--allow-url" not in output

    def test_yolo_no_ask_rules_no_warning(
        self,
        gen: CopilotGenerator,
        config: AppConfig,
        capsys: pytest.CaptureFixture[str],
    ) -> None:
        """T015: yolo mode with no ASK rules emits no lossy-mapping warning."""
        config.yolo = True
        rules = [
            SecurityRule(Scope.EXECUTE, Action.DENY, "rm", Source.BASH_RULES),
            SecurityRule(Scope.EXECUTE, Action.ASK, "git push", Source.BASH_RULES),
        ]
        output = gen.generate(rules, config)
        captured = capsys.readouterr()
        warnings = gen.compatibility_warnings(rules, config)

        # Should have --yolo flag and deny entries
        assert "--yolo" in output
        assert "--deny-tool 'shell(rm)'" in output

        # No lossy mapping warning
        assert captured.err == ""
        assert warnings == []


def _settings_config(tmp_path: Path, **kwargs) -> AppConfig:
    return AppConfig(copilot_settings_path=tmp_path / "settings.json", **kwargs)


def _sandbox_rules() -> list[SecurityRule]:
    return [
        SecurityRule(Scope.READ, Action.DENY, "/secrets", Source.SRT_FILESYSTEM),
        SecurityRule(Scope.WRITE, Action.ALLOW, ".", Source.SRT_FILESYSTEM),
        SecurityRule(Scope.NETWORK, Action.ALLOW, "github.com", Source.SRT_NETWORK),
        SecurityRule(Scope.NETWORK, Action.DENY, "pastebin.com", Source.SRT_NETWORK),
    ]


class TestCopilotSettings:
    """ADR 0009: the native sandbox in ~/.copilot/settings.json."""

    def test_settings_carry_the_policy_and_fixed_hardening(
        self, gen: CopilotGenerator, tmp_path: Path
    ) -> None:
        """FR-011, FR-020."""
        owned = gen.generate_settings(_sandbox_rules(), _settings_config(tmp_path))

        sandbox = owned["sandbox"]
        assert sandbox["enabled"] is True
        assert sandbox["allowBypass"] is False
        assert sandbox["addCurrentWorkingDirectory"] is True
        assert sandbox["allowDevToolAccess"] is True
        assert sandbox["sandboxMcpServers"] is True
        assert sandbox["sandboxLspServers"] is True
        assert sandbox["sandboxExtensions"] is True
        assert sandbox["auth"] == {"git": True, "gh": True}
        assert sandbox["userPolicy"]["seatbelt"] == {"keychainAccess": False}
        assert sandbox["userPolicy"]["filesystem"]["deniedPaths"] == ["/secrets"]
        assert sandbox["userPolicy"]["network"] == {
            "allowOutbound": True,
            "allowLocalNetwork": False,
            "allowedHosts": ["github.com"],
            "blockedHosts": ["pastebin.com"],
        }
        assert owned["allowedUrls"] == ["github.com"]
        assert owned["deniedUrls"] == ["pastebin.com"]

    def test_preview_shows_the_settings_fragment(
        self, gen: CopilotGenerator, tmp_path: Path
    ) -> None:
        """FR-020: the preview names the file and shows only owned keys."""
        config = _settings_config(tmp_path)

        output = gen.generate(_sandbox_rules(), config)

        assert f"settings: {tmp_path / 'settings.json'}" in output
        assert '"deniedPaths"' in output
        assert '"allowedUrls"' in output

    def test_write_merge_keeps_foreign_keys(
        self, gen: CopilotGenerator, tmp_path: Path
    ) -> None:
        """FR-021: model, theme and Copilot's own keys survive."""
        target = tmp_path / "settings.json"
        target.write_text(
            json.dumps(
                {
                    "model": "claude-opus-5-5",
                    "theme": "dark",
                    "sandbox": {"enabled": False, "stale": True},
                    "allowedUrls": ["approved-by-hand.example"],
                }
            )
        )

        files = gen.render_settings(_sandbox_rules(), _settings_config(tmp_path))

        merged = json.loads(files[target])
        assert merged["model"] == "claude-opus-5-5"
        assert merged["theme"] == "dark"
        assert merged["sandbox"]["enabled"] is True
        assert "stale" not in merged["sandbox"]
        assert merged["allowedUrls"] == ["github.com"]
        assert files[target].endswith("\n")

    def test_missing_settings_file_is_created_with_owned_keys_only(
        self, gen: CopilotGenerator, tmp_path: Path
    ) -> None:
        """FR-021."""
        files = gen.render_settings(_sandbox_rules(), _settings_config(tmp_path))

        merged = json.loads(files[tmp_path / "settings.json"])
        assert sorted(merged) == ["allowedUrls", "deniedUrls", "sandbox"]

    @pytest.mark.parametrize("content", ["[1, 2]", "{not json", "// c\n{}"])
    def test_settings_file_that_is_not_a_json_object_is_rejected(
        self, gen: CopilotGenerator, tmp_path: Path, content: str
    ) -> None:
        """FR-022: never overwrite a file twsrt cannot read back."""
        target = tmp_path / "settings.json"
        target.write_text(content)

        with pytest.raises(ValueError, match=str(target)):
            gen.render_settings(_sandbox_rules(), _settings_config(tmp_path))

    def test_yolo_writes_the_same_settings(
        self, gen: CopilotGenerator, tmp_path: Path
    ) -> None:
        """FR-025: one settings.json serves both modes; only flags differ."""
        full = gen.render_settings(_sandbox_rules(), _settings_config(tmp_path))
        yolo = gen.render_settings(
            _sandbox_rules(), _settings_config(tmp_path, yolo=True)
        )

        assert full == yolo

    def test_settings_only_config_previews_no_flags(
        self, gen: CopilotGenerator, tmp_path: Path
    ) -> None:
        """FR-026: without copilot_output there is no flag snippet."""
        rules = [SecurityRule(Scope.EXECUTE, Action.DENY, "rm", Source.BASH_RULES)]

        output = gen.generate(rules, _settings_config(tmp_path))

        assert "--deny-tool" not in output

    def test_settings_only_warns_that_shell_rules_are_not_enforced(
        self, gen: CopilotGenerator, tmp_path: Path
    ) -> None:
        """FR-026: without copilot_output no file carries --deny-tool, so the
        ask mapping must not be claimed; the gap is named instead."""
        config = _settings_config(tmp_path)
        rules = [
            SecurityRule(Scope.EXECUTE, Action.DENY, "rm", Source.BASH_RULES),
            SecurityRule(Scope.EXECUTE, Action.ASK, "git push", Source.BASH_RULES),
        ]

        warnings = gen.compatibility_warnings(rules, config)

        assert not any("--deny-tool for copilot" in w for w in warnings)
        gap = [w for w in warnings if "not enforced" in w]
        assert len(gap) == 1
        assert "copilot_output" in gap[0]
        assert "rm" in gap[0] and "git push" in gap[0]

    def test_settings_only_yolo_still_warns_about_deny_rules(
        self, gen: CopilotGenerator, tmp_path: Path
    ) -> None:
        config = _settings_config(tmp_path, yolo=True)
        rules = [
            SecurityRule(Scope.EXECUTE, Action.DENY, "rm", Source.BASH_RULES),
            SecurityRule(Scope.EXECUTE, Action.ASK, "git push", Source.BASH_RULES),
        ]

        gap = [
            w for w in gen.compatibility_warnings(rules, config) if "not enforced" in w
        ]

        assert len(gap) == 1
        assert "rm" in gap[0]
        assert "git push" not in gap[0]

    def test_settings_only_without_shell_rules_has_no_gap_warning(
        self, gen: CopilotGenerator, tmp_path: Path
    ) -> None:
        warnings = gen.compatibility_warnings([], _settings_config(tmp_path))

        assert not any("not enforced" in w for w in warnings)

    def test_settings_warnings_include_the_builder_warnings(
        self, gen: CopilotGenerator, tmp_path: Path
    ) -> None:
        """FR-040 reaches the user through compatibility_warnings, yolo too."""
        config = _settings_config(tmp_path, yolo=True)

        warnings = gen.compatibility_warnings([], config)

        assert any("in-process" in w for w in warnings)


class TestCopilotFlagsWithSettings:
    """FR-023, FR-026: URL rules move to settings.json when it is managed."""

    def test_url_flags_are_dropped_when_settings_are_managed(
        self, gen: CopilotGenerator, tmp_path: Path
    ) -> None:
        config = AppConfig(
            copilot_settings_path=tmp_path / "settings.json",
            copilot_output_path=tmp_path / "copilot-flags.txt",
        )
        rules = [
            *_sandbox_rules(),
            SecurityRule(Scope.EXECUTE, Action.DENY, "rm", Source.BASH_RULES),
        ]

        flags = gen.generate_flags(rules, config)

        assert "--allow-url" not in flags
        assert "--deny-url" not in flags
        assert "--deny-tool 'shell(rm)'" in flags
        assert "--allow-tool 'shell'" in flags

    def test_flags_only_config_keeps_url_flags(
        self, gen: CopilotGenerator, tmp_path: Path
    ) -> None:
        config = AppConfig(copilot_output_path=tmp_path / "copilot-flags.txt")

        flags = gen.generate_flags(_sandbox_rules(), config)

        assert "--allow-url 'github.com'" in flags
        assert "--deny-url 'pastebin.com'" in flags


class TestCopilotSettingsDiff:
    """FR-024: drift on owned keys only."""

    def test_freshly_written_settings_have_no_drift(
        self, gen: CopilotGenerator, tmp_path: Path
    ) -> None:
        config = _settings_config(tmp_path)
        for path, content in gen.render_settings(_sandbox_rules(), config).items():
            path.write_text(content)

        result = gen.diff(_sandbox_rules(), tmp_path / "settings.json", config)

        assert result.matched

    def test_foreign_key_change_is_not_drift(
        self, gen: CopilotGenerator, tmp_path: Path
    ) -> None:
        config = _settings_config(tmp_path)
        target = tmp_path / "settings.json"
        target.write_text(gen.render_settings(_sandbox_rules(), config)[target])
        document = json.loads(target.read_text())
        document["model"] = "something-else"
        target.write_text(json.dumps(document))

        result = gen.diff(_sandbox_rules(), target, config)

        assert result.matched

    def test_url_approved_inside_copilot_is_drift(
        self, gen: CopilotGenerator, tmp_path: Path
    ) -> None:
        """twsrt owns allowedUrls fully (decided 2026-11-23)."""
        config = _settings_config(tmp_path)
        target = tmp_path / "settings.json"
        target.write_text(gen.render_settings(_sandbox_rules(), config)[target])
        document = json.loads(target.read_text())
        document["allowedUrls"].append("approved-in-session.example")
        target.write_text(json.dumps(document))

        result = gen.diff(_sandbox_rules(), target, config)

        assert not result.matched
        assert result.missing == ["settings:allowedUrls"]
        assert result.extra == ["settings:allowedUrls"]

    def test_settings_only_config_does_not_read_target_as_flags(
        self, gen: CopilotGenerator, tmp_path: Path
    ) -> None:
        """With only copilot_settings, the CLI passes settings.json as target."""
        config = _settings_config(tmp_path)
        target = tmp_path / "settings.json"
        target.write_text(gen.render_settings(_sandbox_rules(), config)[target])

        result = gen.diff(_sandbox_rules(), target, config)

        assert result.missing == []
        assert result.extra == []

    def test_flags_and_settings_are_both_compared(
        self, gen: CopilotGenerator, tmp_path: Path
    ) -> None:
        flags_path = tmp_path / "copilot-flags.txt"
        config = _settings_config(tmp_path, copilot_output_path=flags_path)
        rules = [
            *_sandbox_rules(),
            SecurityRule(Scope.EXECUTE, Action.DENY, "rm", Source.BASH_RULES),
        ]
        flags_path.write_text("")
        settings = tmp_path / "settings.json"
        settings.write_text(gen.render_settings(rules, config)[settings])

        result = gen.diff(rules, flags_path, config)

        assert "--deny-tool 'shell(rm)'" in result.missing
        assert not any(entry.startswith("settings:") for entry in result.missing)
