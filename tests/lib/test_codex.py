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
            _rule(Scope.WRITE, Action.DENY, "**/.env"),
            _rule(Scope.READ, Action.DENY, "~/.ssh"),
        ]

        generated = tomllib.loads(CodexGenerator().generate_config(rules, AppConfig()))

        assert generated["default_permissions"] == "twsrt"
        assert generated["approval_policy"] == "on-request"
        assert generated["approvals_reviewer"] == "user"
        assert generated["allow_login_shell"] is False
        profile = generated["permissions"]["twsrt"]
        assert profile["extends"] == ":read-only"
        assert profile["filesystem"][":workspace_roots"]["."] == "write"
        assert profile["filesystem"][":workspace_roots"]["**/.env"] == "deny"
        assert profile["filesystem"]["~/.gradle"] == "write"
        assert profile["filesystem"]["~/.ssh"] == "deny"

    def test_equal_path_uses_most_restrictive_access(self) -> None:
        rules = [
            _rule(Scope.WRITE, Action.ALLOW, "**/.env"),
            _rule(Scope.WRITE, Action.DENY, "**/.env"),
            _rule(Scope.READ, Action.DENY, "**/.env"),
        ]

        generated = tomllib.loads(CodexGenerator().generate_config(rules, AppConfig()))

        assert (
            generated["permissions"]["twsrt"]["filesystem"][":workspace_roots"][
                "**/.env"
            ]
            == "deny"
        )

    def test_maps_allowed_and_denied_network_domains(self) -> None:
        rules = [
            _rule(Scope.NETWORK, Action.ALLOW, "github.com"),
            _rule(Scope.NETWORK, Action.DENY, "evil.example"),
        ]

        generated = tomllib.loads(CodexGenerator().generate_config(rules, AppConfig()))
        network = generated["permissions"]["twsrt"]["network"]

        assert network["enabled"] is True
        assert network["mode"] == "limited"
        assert network["domains"] == {
            "github.com": "allow",
            "evil.example": "deny",
        }

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
        rules = [_rule(Scope.WRITE, Action.ALLOW, "/~/dev/private")]

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
    def test_generates_starlark_prefix_rules(self) -> None:
        rules = [
            _rule(Scope.EXECUTE, Action.DENY, "git reset --hard"),
            _rule(Scope.EXECUTE, Action.ASK, "git push"),
            _rule(Scope.EXECUTE, Action.ALLOW, "gh pr view"),
        ]

        generated = CodexGenerator().generate_rules(rules, AppConfig())

        assert 'pattern = ["git", "reset", "--hard"]' in generated
        assert 'decision = "forbidden"' in generated
        assert 'pattern = ["git", "push"]' in generated
        assert 'decision = "prompt"' in generated
        assert 'pattern = ["gh", "pr", "view"]' in generated
        assert 'decision = "allow"' in generated
        assert (
            'justification = "Generated from twsrt Bash intent.",\n'
            '    match = ["gh pr view"],'
        ) in generated

    def test_yolo_omits_prompt_rules(self) -> None:
        rules = [_rule(Scope.EXECUTE, Action.ASK, "git push")]

        generated = CodexGenerator().generate_rules(rules, AppConfig(yolo=True))

        assert "git" not in generated
        assert "prompt" not in generated

    def test_rejects_invalid_shell_syntax(self) -> None:
        rules = [_rule(Scope.EXECUTE, Action.DENY, "bash 'unterminated")]

        with pytest.raises(ValueError, match="Invalid Bash rule"):
            CodexGenerator().generate_rules(rules, AppConfig())


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
        config = AppConfig(
            codex_config_path=tmp_path / "config.toml",
            codex_rules_path=tmp_path / "rules" / "twsrt.rules",
        )
        rules = [_rule(Scope.EXECUTE, Action.DENY, "rm")]
        generator = CodexGenerator()
        generator.write(rules, config)

        with config.codex_config_path.open("a") as stream:
            stream.write('\n[foreign]\nmodel = "foreign"\n')
        assert generator.diff(rules, config.codex_config_path, config).matched is True

        config.codex_rules_path.write_text("")
        drift = generator.diff(rules, config.codex_config_path, config)
        assert drift.matched is False
        assert any("twsrt.rules" in entry for entry in drift.missing)
