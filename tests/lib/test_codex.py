"""Tests for Codex permission-profile and execution-rule generation."""

from __future__ import annotations

import tomllib
from pathlib import Path

import pytest

from twsrt.lib.codex import CodexGenerator
from twsrt.lib.models import Action, AppConfig, Scope, SecurityRule, Source


def _rule(scope: Scope, action: Action, pattern: str) -> SecurityRule:
    source = (
        Source.BASH_RULES
        if scope == Scope.EXECUTE
        else (Source.SRT_NETWORK if scope == Scope.NETWORK else Source.SRT_FILESYSTEM)
    )
    return SecurityRule(scope, action, pattern, source)


class TestCodexProfileGeneration:
    def test_generates_local_hardening_and_filesystem_profile(self) -> None:
        rules = [
            _rule(Scope.WRITE, Action.ALLOW, "."),
            _rule(Scope.WRITE, Action.ALLOW, "~/.gradle"),
            _rule(Scope.WRITE, Action.ALLOW, "/private/tmp"),
            _rule(Scope.WRITE, Action.ALLOW, "~/dev/private/**"),
            _rule(Scope.WRITE, Action.ALLOW, "~/dev/private"),
            _rule(Scope.WRITE, Action.DENY, "**/.env"),
            _rule(Scope.WRITE, Action.DENY, "~/notes.txt"),
            _rule(Scope.READ, Action.DENY, "~/.ssh"),
        ]

        generated = tomllib.loads(CodexGenerator().generate_config(rules, AppConfig()))

        assert generated["default_permissions"] == "twsrt"
        assert generated["approval_policy"] == "on-request"
        assert generated["approvals_reviewer"] == "user"
        assert generated["allow_login_shell"] is False
        profile = generated["permissions"]["twsrt"]
        assert profile["extends"] == ":workspace"
        assert profile["workspace_roots"] == {
            "~/.gradle": True,
            "/private/tmp": True,
            "~/dev/private": True,
        }
        assert profile["filesystem"][":workspace_roots"]["**/.env"] == "deny"
        assert "." not in profile["filesystem"][":workspace_roots"]
        assert profile["filesystem"]["~/notes.txt"] == "read"
        assert profile["filesystem"]["~/.ssh"] == "deny"

    def test_equal_path_uses_most_restrictive_access(self) -> None:
        rules = [
            _rule(Scope.WRITE, Action.DENY, "~/notes.txt"),
            _rule(Scope.READ, Action.DENY, "~/notes.txt"),
        ]

        generated = tomllib.loads(CodexGenerator().generate_config(rules, AppConfig()))

        assert generated["permissions"]["twsrt"]["filesystem"]["~/notes.txt"] == "deny"

    def test_supported_allow_write_paths_do_not_warn(self) -> None:
        rules = [
            _rule(Scope.WRITE, Action.ALLOW, "."),
            _rule(Scope.WRITE, Action.ALLOW, "~/dev"),
        ]

        warnings = CodexGenerator().compatibility_warnings(AppConfig(), rules)

        assert not any("allowWrite" in warning for warning in warnings)

    @pytest.mark.parametrize(
        "pattern", ["~/dev/*/cache", "~", "~/", "~/**", "/", "/**"]
    )
    def test_skips_unsupported_allow_write_shapes_with_warning(
        self, pattern: str
    ) -> None:
        rules = [_rule(Scope.WRITE, Action.ALLOW, pattern)]
        generator = CodexGenerator()

        generated = tomllib.loads(generator.generate_config(rules, AppConfig()))
        warnings = generator.compatibility_warnings(AppConfig(), rules)

        assert "workspace_roots" not in generated["permissions"]["twsrt"]
        assert any(
            "concrete directories" in warning and pattern in warning
            for warning in warnings
        )

    def test_normalizes_trailing_slash_and_glob_suffix_to_one_root(self) -> None:
        rules = [
            _rule(Scope.WRITE, Action.ALLOW, "~/dev/"),
            _rule(Scope.WRITE, Action.ALLOW, "~/dev/**"),
        ]

        generated = tomllib.loads(CodexGenerator().generate_config(rules, AppConfig()))

        assert generated["permissions"]["twsrt"]["workspace_roots"] == {"~/dev": True}

    def test_deny_rule_wins_over_allow_write_workspace_root(self) -> None:
        rules = [
            _rule(Scope.WRITE, Action.ALLOW, "~/dev"),
            _rule(Scope.READ, Action.DENY, "~/dev"),
        ]
        generator = CodexGenerator()

        generated = tomllib.loads(generator.generate_config(rules, AppConfig()))
        warnings = generator.compatibility_warnings(AppConfig(), rules)

        profile = generated["permissions"]["twsrt"]
        assert "workspace_roots" not in profile
        assert profile["filesystem"]["~/dev"] == "deny"
        assert any(
            "kept the deny" in warning and "~/dev" in warning for warning in warnings
        )

    def test_maps_allowed_and_denied_network_domains(self) -> None:
        rules = [
            _rule(Scope.NETWORK, Action.ALLOW, "github.com"),
            _rule(Scope.NETWORK, Action.DENY, "evil.example"),
        ]

        generated = tomllib.loads(CodexGenerator().generate_config(rules, AppConfig()))
        network = generated["permissions"]["twsrt"]["network"]

        assert network["enabled"] is True
        assert "mode" not in network
        assert network["domains"] == {
            "github.com": "allow",
            "evil.example": "deny",
        }

    def test_empty_domains_table_always_emitted(self) -> None:
        generated = tomllib.loads(CodexGenerator().generate_config([], AppConfig()))
        network = generated["permissions"]["twsrt"]["network"]

        assert network["enabled"] is True
        assert network["domains"] == {}

    def test_maps_only_exact_unix_socket_paths(self, tmp_path: Path) -> None:
        socket = tmp_path / "docker.sock"
        config = AppConfig(
            network_config={
                "allowUnixSockets": [str(socket), str(tmp_path)],
                "allowAllUnixSockets": False,
                "allowLocalBinding": True,
                "httpProxyPort": 3128,
            }
        )

        generated = tomllib.loads(CodexGenerator().generate_config([], config))
        network = generated["permissions"]["twsrt"]["network"]

        assert network["unix_sockets"] == {str(socket): "allow"}
        assert "allow_local_binding" not in network
        assert "proxy_url" not in network
        warnings = CodexGenerator().compatibility_warnings(config)
        assert any(str(tmp_path) in warning for warning in warnings)
        assert any("allowLocalBinding" in warning for warning in warnings)
        assert any("httpProxyPort" in warning for warning in warnings)

    def test_rejects_literal_root_tilde_path(self) -> None:
        rules = [_rule(Scope.WRITE, Action.DENY, "/~/dev/private")]

        with pytest.raises(ValueError, match=r"/~/"):
            CodexGenerator().generate_config(rules, AppConfig())

    def test_warns_when_deny_write_glob_must_also_deny_read(self) -> None:
        rules = [
            _rule(Scope.WRITE, Action.DENY, "**/*.pem"),
            _rule(Scope.WRITE, Action.DENY, "**/*.key"),
        ]

        warnings = CodexGenerator().compatibility_warnings(AppConfig(), rules)

        assert any(
            "2 denyWrite globs" in warning and "deny read and write" in warning
            for warning in warnings
        )

    def test_rejects_disabled_canonical_sandbox_but_ignores_claude_override(
        self,
    ) -> None:
        generator = CodexGenerator()
        disabled = AppConfig(srt_sandbox_enabled=False)
        with pytest.raises(ValueError, match="disabled"):
            generator.generate_config([], disabled)

        claude_override = AppConfig(
            srt_sandbox_enabled=True,
            sandbox_config={"enabled": False},
        )
        assert generator.generate_config([], claude_override)


class TestCodexExecutionRules:
    def test_generates_forbidden_rules_only(self) -> None:
        rules = [
            _rule(Scope.EXECUTE, Action.DENY, "git reset --hard"),
            _rule(Scope.EXECUTE, Action.ASK, "git push"),
            _rule(Scope.EXECUTE, Action.ALLOW, "gh pr view"),
        ]

        generated = CodexGenerator().generate_rules(rules, AppConfig())

        assert 'pattern = ["git", "reset", "--hard"]' in generated
        assert 'decision = "forbidden"' in generated
        assert (
            'justification = "Generated from twsrt Bash intent.",\n'
            '    match = ["git reset --hard"],'
        ) in generated
        assert 'decision = "prompt"' not in generated
        assert 'decision = "allow"' not in generated
        assert '"push"' not in generated
        assert '"gh"' not in generated

    def test_rules_identical_regardless_of_yolo(self) -> None:
        rules = [
            _rule(Scope.EXECUTE, Action.DENY, "rm"),
            _rule(Scope.EXECUTE, Action.ASK, "git push"),
        ]

        full = CodexGenerator().generate_rules(rules, AppConfig())
        yolo = CodexGenerator().generate_rules(rules, AppConfig(yolo=True))

        assert full == yolo

    def test_warns_about_skipped_allow_and_ask_rules(self) -> None:
        rules = [
            _rule(Scope.EXECUTE, Action.ALLOW, "gh pr view"),
            _rule(Scope.EXECUTE, Action.ASK, "git push"),
            _rule(Scope.EXECUTE, Action.DENY, "rm"),
        ]

        warnings = CodexGenerator().compatibility_warnings(AppConfig(), rules)

        assert any(
            "unsandboxed" in warning and "gh pr view" in warning for warning in warnings
        )
        assert any(
            "prompts" in warning and "1 ask rule" in warning for warning in warnings
        )

    def test_always_warns_about_silent_profile_deactivation(self) -> None:
        warnings = CodexGenerator().compatibility_warnings(AppConfig())

        assert any(
            "sandbox_mode" in warning and "config.toml" in warning
            for warning in warnings
        )

    def test_rejects_invalid_shell_syntax(self) -> None:
        rules = [_rule(Scope.EXECUTE, Action.DENY, "bash 'unterminated")]

        with pytest.raises(ValueError, match="Invalid Bash rule"):
            CodexGenerator().generate_rules(rules, AppConfig())


class TestCodexOptionalRules:
    def test_generate_without_rules_path_omits_rules_section(self) -> None:
        config = AppConfig(codex_rules_path=None)
        rules = [_rule(Scope.EXECUTE, Action.DENY, "rm")]

        preview = CodexGenerator().generate(rules, config)

        assert 'default_permissions = "twsrt"' in preview
        assert "prefix_rule" not in preview
        assert "--- rules:" not in preview

    def test_write_without_rules_path_writes_config_only(self, tmp_path: Path) -> None:
        config = AppConfig(
            codex_config_path=tmp_path / "config.toml",
            codex_rules_path=None,
        )
        rules = [_rule(Scope.EXECUTE, Action.DENY, "rm")]

        CodexGenerator().write(rules, config)

        assert config.codex_config_path.exists()
        assert not (tmp_path / "rules").exists()

    def test_diff_without_rules_path_ignores_rules(self, tmp_path: Path) -> None:
        config = AppConfig(
            codex_config_path=tmp_path / "config.toml",
            codex_rules_path=None,
        )
        rules = [_rule(Scope.EXECUTE, Action.DENY, "rm")]
        generator = CodexGenerator()
        generator.write(rules, config)

        result = generator.diff(rules, config.codex_config_path, config)

        assert result.matched is True


class TestCodexMergeAndDrift:
    def test_write_preserves_foreign_config_comments_and_secrets(
        self, tmp_path: Path
    ) -> None:
        config_path = tmp_path / "config.toml"
        rules_path = tmp_path / "rules" / "twsrt.rules"
        config_path.write_text(
            '# keep this comment\nmodel = "gpt-test"\n\n'
            '[mcp_servers.example]\nurl = "https://example.test"\n\n'
            "[mcp_servers.example.http_headers]\n"
            'Authorization = "sentinel-secret"\n'
        )
        config = AppConfig(
            codex_config_path=config_path,
            codex_rules_path=rules_path,
        )
        rules = [_rule(Scope.EXECUTE, Action.DENY, "rm")]

        preview = CodexGenerator().generate(rules, config)
        CodexGenerator().write(rules, config)

        written = config_path.read_text()
        assert "# keep this comment" in written
        assert 'model = "gpt-test"' in written
        assert 'Authorization = "sentinel-secret"' in written
        assert "sentinel-secret" not in preview
        assert rules_path.exists()
        assert 'decision = "forbidden"' in rules_path.read_text()

    def test_write_preserves_default_rules(self, tmp_path: Path) -> None:
        codex_dir = tmp_path / ".codex"
        default_rules = codex_dir / "rules" / "default.rules"
        default_rules.parent.mkdir(parents=True)
        default_rules.write_text("existing default\n")
        config = AppConfig(
            codex_config_path=codex_dir / "config.toml",
            codex_rules_path=codex_dir / "rules" / "twsrt.rules",
        )

        CodexGenerator().write([], config)

        assert default_rules.read_text() == "existing default\n"

    def test_write_rejects_legacy_sandbox_configuration(self, tmp_path: Path) -> None:
        target = tmp_path / "config.toml"
        target.write_text('sandbox_mode = "workspace-write"\n')
        config = AppConfig(
            codex_config_path=target,
            codex_rules_path=tmp_path / "twsrt.rules",
        )

        with pytest.raises(ValueError, match="sandbox_mode"):
            CodexGenerator().write([], config)

    def test_diff_compares_only_owned_config_and_rules(self, tmp_path: Path) -> None:
        rules_path = tmp_path / "rules" / "twsrt.rules"
        config = AppConfig(
            codex_config_path=tmp_path / "config.toml",
            codex_rules_path=rules_path,
        )
        rules = [_rule(Scope.EXECUTE, Action.DENY, "rm")]
        generator = CodexGenerator()
        generator.write(rules, config)

        with config.codex_config_path.open("a") as stream:
            stream.write('\n[foreign]\nmodel = "foreign"\n')
        assert generator.diff(rules, config.codex_config_path, config).matched is True

        rules_path.write_text("")
        drift = generator.diff(rules, config.codex_config_path, config)
        assert drift.matched is False
        assert any("twsrt.rules" in entry for entry in drift.missing)
