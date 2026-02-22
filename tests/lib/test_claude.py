"""Tests for Claude Code generation — rule mapping and selective merge."""

import json
from pathlib import Path

import pytest

from twsrt.lib.claude import ClaudeGenerator, selective_merge
from twsrt.lib.models import Action, AppConfig, Scope, SecurityRule, Source


@pytest.fixture
def gen() -> ClaudeGenerator:
    return ClaudeGenerator()


@pytest.fixture
def config() -> AppConfig:
    return AppConfig()


class TestClaudeGeneration:
    """Test rule mapping: SecurityRule → Claude permission entries."""

    def test_deny_read_directory_generates_bare_and_recursive(
        self, gen: ClaudeGenerator, config: AppConfig, tmp_path: Path
    ) -> None:
        """FR-006: denyRead on a directory generates bare + recursive deny."""
        aws_dir = tmp_path / ".aws"
        aws_dir.mkdir()
        rules = [
            SecurityRule(Scope.READ, Action.DENY, str(aws_dir), Source.SRT_FILESYSTEM),
        ]
        output = json.loads(gen.generate(rules, config))
        deny = output["permissions"]["deny"]
        assert f"Read({aws_dir})" in deny
        assert f"Read({aws_dir}/**)" in deny
        assert f"Write({aws_dir})" in deny
        assert f"Write({aws_dir}/**)" in deny
        assert f"Edit({aws_dir})" in deny
        assert f"Edit({aws_dir}/**)" in deny
        assert f"MultiEdit({aws_dir})" in deny
        assert f"MultiEdit({aws_dir}/**)" in deny

    def test_deny_read_file_generates_bare_only(
        self, gen: ClaudeGenerator, config: AppConfig, tmp_path: Path
    ) -> None:
        """denyRead on a file generates bare deny only (no /**)."""
        netrc = tmp_path / ".netrc"
        netrc.write_text("")
        rules = [
            SecurityRule(Scope.READ, Action.DENY, str(netrc), Source.SRT_FILESYSTEM),
        ]
        output = json.loads(gen.generate(rules, config))
        deny = output["permissions"]["deny"]
        assert f"Read({netrc})" in deny
        assert f"Write({netrc})" in deny
        assert f"Edit({netrc})" in deny
        assert f"MultiEdit({netrc})" in deny
        # No recursive patterns for files
        assert f"Read({netrc}/**)" not in deny
        assert f"Write({netrc}/**)" not in deny

    def test_deny_read_glob_pattern_generates_bare_only(
        self, gen: ClaudeGenerator, config: AppConfig
    ) -> None:
        """denyRead with glob patterns (e.g. **/.aws) generates bare deny only."""
        rules = [
            SecurityRule(Scope.READ, Action.DENY, "**/.aws", Source.SRT_FILESYSTEM),
        ]
        output = json.loads(gen.generate(rules, config))
        deny = output["permissions"]["deny"]
        assert "Read(**/.aws)" in deny
        assert "Write(**/.aws)" in deny
        # Glob patterns should not get /** appended
        assert "Read(**/.aws/**)" not in deny

    def test_deny_read_nonexistent_path_assumes_directory(
        self, gen: ClaudeGenerator, config: AppConfig, tmp_path: Path
    ) -> None:
        """Unknown paths default to directory treatment (safer)."""
        nonexistent = tmp_path / "doesnotexist"
        rules = [
            SecurityRule(
                Scope.READ, Action.DENY, str(nonexistent), Source.SRT_FILESYSTEM
            ),
        ]
        output = json.loads(gen.generate(rules, config))
        deny = output["permissions"]["deny"]
        # Should generate both bare and recursive (assume directory)
        assert f"Read({nonexistent})" in deny
        assert f"Read({nonexistent}/**)" in deny

    def test_deny_write_generates_write_tools(
        self, gen: ClaudeGenerator, config: AppConfig
    ) -> None:
        """FR-007: denyWrite generates deny for write tools only."""
        rules = [
            SecurityRule(Scope.WRITE, Action.DENY, "**/.env", Source.SRT_FILESYSTEM),
        ]
        output = json.loads(gen.generate(rules, config))
        deny = output["permissions"]["deny"]
        assert "Write(**/.env)" in deny
        assert "Edit(**/.env)" in deny
        assert "MultiEdit(**/.env)" in deny
        # Should NOT include Read for write-only deny
        assert "Read(**/.env)" not in deny

    def test_allow_write_no_output(
        self, gen: ClaudeGenerator, config: AppConfig
    ) -> None:
        """FR-008: allowWrite produces no Claude output (SRT enforces OS-level)."""
        rules = [
            SecurityRule(Scope.WRITE, Action.ALLOW, ".", Source.SRT_FILESYSTEM),
            SecurityRule(Scope.WRITE, Action.ALLOW, "/tmp", Source.SRT_FILESYSTEM),
        ]
        output = json.loads(gen.generate(rules, config))
        # allow should not contain any allowWrite-derived entries
        allow = output["permissions"].get("allow", [])
        assert "Write(.)" not in allow
        assert "Write(/tmp)" not in allow

    def test_allowed_domains_generate_webfetch_and_network(
        self, gen: ClaudeGenerator, config: AppConfig
    ) -> None:
        """FR-009: allowedDomains → WebFetch in allow + sandbox.network."""
        rules = [
            SecurityRule(Scope.NETWORK, Action.ALLOW, "github.com", Source.SRT_NETWORK),
            SecurityRule(Scope.NETWORK, Action.ALLOW, "pypi.org", Source.SRT_NETWORK),
        ]
        output = json.loads(gen.generate(rules, config))
        allow = output["permissions"]["allow"]
        assert "WebFetch(domain:github.com)" in allow
        assert "WebFetch(domain:pypi.org)" in allow
        network = output["sandbox"]["network"]["allowedDomains"]
        assert "github.com" in network
        assert "pypi.org" in network

    def test_bash_deny_generates_bash_deny(
        self, gen: ClaudeGenerator, config: AppConfig
    ) -> None:
        """FR-010: Bash deny → Bash(cmd) + Bash(cmd *) in deny."""
        rules = [
            SecurityRule(Scope.EXECUTE, Action.DENY, "rm", Source.BASH_RULES),
        ]
        output = json.loads(gen.generate(rules, config))
        deny = output["permissions"]["deny"]
        assert "Bash(rm)" in deny
        assert "Bash(rm *)" in deny

    def test_bash_ask_generates_bash_ask(
        self, gen: ClaudeGenerator, config: AppConfig
    ) -> None:
        """FR-011: Bash ask → Bash(cmd) + Bash(cmd *) in ask."""
        rules = [
            SecurityRule(Scope.EXECUTE, Action.ASK, "git push", Source.BASH_RULES),
        ]
        output = json.loads(gen.generate(rules, config))
        ask = output["permissions"]["ask"]
        assert "Bash(git push)" in ask
        assert "Bash(git push *)" in ask

    def test_deny_read_and_deny_write_overlap(
        self, gen: ClaudeGenerator, config: AppConfig
    ) -> None:
        """denyRead+denyWrite on same path: all applicable tools denied."""
        rules = [
            SecurityRule(Scope.READ, Action.DENY, "**/.env", Source.SRT_FILESYSTEM),
            SecurityRule(Scope.WRITE, Action.DENY, "**/.env", Source.SRT_FILESYSTEM),
        ]
        output = json.loads(gen.generate(rules, config))
        deny = output["permissions"]["deny"]
        # **/.env is a glob pattern → bare only, no /** expansion
        assert "Read(**/.env)" in deny
        assert "Write(**/.env)" in deny
        assert "Edit(**/.env)" in deny
        assert "MultiEdit(**/.env)" in deny

    def test_empty_rules_generate_empty_sections(
        self, gen: ClaudeGenerator, config: AppConfig
    ) -> None:
        output = json.loads(gen.generate([], config))
        assert output["permissions"]["deny"] == []
        assert output["permissions"]["ask"] == []
        assert output["permissions"]["allow"] == []
        assert output["sandbox"]["network"]["allowedDomains"] == []


class TestSelectiveMerge:
    """FR-018: Selective merge for Claude settings.json."""

    def test_deny_fully_replaced(self, tmp_path: Path) -> None:
        existing = {
            "permissions": {
                "deny": ["Bash(old:*)", "Read(**/.old/**)"],
                "ask": [],
                "allow": [],
            }
        }
        target = tmp_path / "settings.json"
        target.write_text(json.dumps(existing))

        generated = {
            "permissions": {
                "deny": ["Bash(rm)", "Bash(rm *)"],
                "ask": [],
                "allow": [],
            },
            "sandbox": {"network": {"allowedDomains": []}},
        }
        result = selective_merge(target, generated)
        assert result["permissions"]["deny"] == ["Bash(rm)", "Bash(rm *)"]

    def test_ask_fully_replaced(self, tmp_path: Path) -> None:
        existing = {
            "permissions": {
                "deny": [],
                "ask": ["Bash(old)", "Bash(old:*)"],
                "allow": [],
            }
        }
        target = tmp_path / "settings.json"
        target.write_text(json.dumps(existing))

        generated = {
            "permissions": {
                "deny": [],
                "ask": ["Bash(git push)", "Bash(git push *)"],
                "allow": [],
            },
            "sandbox": {"network": {"allowedDomains": []}},
        }
        result = selective_merge(target, generated)
        assert result["permissions"]["ask"] == ["Bash(git push)", "Bash(git push *)"]

    def test_allow_preserves_blanket_allows(self, tmp_path: Path) -> None:
        """Blanket tool allows (Read, Glob, etc.) must be preserved."""
        existing = {
            "permissions": {
                "deny": [],
                "ask": [],
                "allow": [
                    "Read",
                    "Glob",
                    "Grep",
                    "LS",
                    "Task",
                    "WebSearch",
                    "WebFetch(domain:old.com)",
                ],
            }
        }
        target = tmp_path / "settings.json"
        target.write_text(json.dumps(existing))

        generated = {
            "permissions": {
                "deny": [],
                "ask": [],
                "allow": ["WebFetch(domain:github.com)"],
            },
            "sandbox": {"network": {"allowedDomains": ["github.com"]}},
        }
        result = selective_merge(target, generated)
        allow = result["permissions"]["allow"]
        # Blanket allows preserved
        assert "Read" in allow
        assert "Glob" in allow
        assert "Grep" in allow
        assert "LS" in allow
        assert "Task" in allow
        assert "WebSearch" in allow
        # Old WebFetch replaced, new one present
        assert "WebFetch(domain:old.com)" not in allow
        assert "WebFetch(domain:github.com)" in allow

    def test_allow_preserves_mcp_allows(self, tmp_path: Path) -> None:
        """mcp__ prefixed allows must be preserved."""
        existing = {
            "permissions": {
                "deny": [],
                "ask": [],
                "allow": [
                    "mcp__memory__store",
                    "mcp__github__search",
                    "WebFetch(domain:old.com)",
                ],
            }
        }
        target = tmp_path / "settings.json"
        target.write_text(json.dumps(existing))

        generated = {
            "permissions": {
                "deny": [],
                "ask": [],
                "allow": ["WebFetch(domain:github.com)"],
            },
            "sandbox": {"network": {"allowedDomains": []}},
        }
        result = selective_merge(target, generated)
        allow = result["permissions"]["allow"]
        assert "mcp__memory__store" in allow
        assert "mcp__github__search" in allow

    def test_allow_preserves_project_specific(self, tmp_path: Path) -> None:
        """Project-specific allows like Bash(./gradlew:*) must be preserved."""
        existing = {
            "permissions": {
                "deny": [],
                "ask": [],
                "allow": [
                    "Bash(./gradlew:*)",
                    "WebFetch(domain:old.com)",
                ],
            }
        }
        target = tmp_path / "settings.json"
        target.write_text(json.dumps(existing))

        generated = {
            "permissions": {
                "deny": [],
                "ask": [],
                "allow": ["WebFetch(domain:github.com)"],
            },
            "sandbox": {"network": {"allowedDomains": []}},
        }
        result = selective_merge(target, generated)
        allow = result["permissions"]["allow"]
        assert "Bash(./gradlew:*)" in allow

    def test_sandbox_network_fully_replaced(self, tmp_path: Path) -> None:
        existing = {
            "permissions": {"deny": [], "ask": [], "allow": []},
            "sandbox": {"network": {"allowedDomains": ["old.com"]}},
        }
        target = tmp_path / "settings.json"
        target.write_text(json.dumps(existing))

        generated = {
            "permissions": {"deny": [], "ask": [], "allow": []},
            "sandbox": {"network": {"allowedDomains": ["github.com", "pypi.org"]}},
        }
        result = selective_merge(target, generated)
        assert result["sandbox"]["network"]["allowedDomains"] == [
            "github.com",
            "pypi.org",
        ]

    def test_hooks_preserved(self, tmp_path: Path) -> None:
        existing = {
            "permissions": {"deny": [], "ask": [], "allow": []},
            "hooks": {"PreToolUse": [{"matcher": "Bash"}]},
        }
        target = tmp_path / "settings.json"
        target.write_text(json.dumps(existing))

        generated = {
            "permissions": {"deny": ["Bash(rm:*)"], "ask": [], "allow": []},
            "sandbox": {"network": {"allowedDomains": []}},
        }
        result = selective_merge(target, generated)
        assert result["hooks"] == {"PreToolUse": [{"matcher": "Bash"}]}

    def test_additional_directories_preserved(self, tmp_path: Path) -> None:
        existing = {
            "permissions": {"deny": [], "ask": [], "allow": []},
            "additionalDirectories": ["/tmp/extra"],
        }
        target = tmp_path / "settings.json"
        target.write_text(json.dumps(existing))

        generated = {
            "permissions": {"deny": [], "ask": [], "allow": []},
            "sandbox": {"network": {"allowedDomains": []}},
        }
        result = selective_merge(target, generated)
        assert result["additionalDirectories"] == ["/tmp/extra"]
