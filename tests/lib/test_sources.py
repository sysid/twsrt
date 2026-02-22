"""Tests for sources.py: canonical source reading/validation."""

import json
from pathlib import Path

import pytest

from twsrt.lib.models import Action, Scope, Source
from twsrt.lib.sources import read_bash_rules, read_srt


class TestReadSrt:
    def test_deny_read_rules(self, srt_file: Path) -> None:
        rules = read_srt(srt_file)
        deny_reads = [
            r for r in rules if r.scope == Scope.READ and r.action == Action.DENY
        ]
        # SAMPLE_SRT has 4 denyOnly entries
        assert len(deny_reads) == 4
        patterns = {r.pattern for r in deny_reads}
        assert "**/.env" in patterns
        assert "**/.aws" in patterns
        assert "~/.ssh" in patterns

    def test_deny_write_rules(self, srt_file: Path) -> None:
        rules = read_srt(srt_file)
        deny_writes = [
            r for r in rules if r.scope == Scope.WRITE and r.action == Action.DENY
        ]
        # SAMPLE_SRT has 3 denyWithinAllow entries
        assert len(deny_writes) == 3
        patterns = {r.pattern for r in deny_writes}
        assert "**/.env" in patterns
        assert "**/*.pem" in patterns

    def test_allow_write_rules(self, srt_file: Path) -> None:
        rules = read_srt(srt_file)
        allow_writes = [
            r for r in rules if r.scope == Scope.WRITE and r.action == Action.ALLOW
        ]
        assert len(allow_writes) == 2
        patterns = {r.pattern for r in allow_writes}
        assert "." in patterns
        assert "/tmp" in patterns

    def test_allowed_domains(self, srt_file: Path) -> None:
        rules = read_srt(srt_file)
        network_rules = [r for r in rules if r.scope == Scope.NETWORK]
        assert len(network_rules) == 4
        domains = {r.pattern for r in network_rules}
        assert "github.com" in domains
        assert "pypi.org" in domains
        for r in network_rules:
            assert r.action == Action.ALLOW
            assert r.source == Source.SRT_NETWORK

    def test_all_rules_have_srt_source(self, srt_file: Path) -> None:
        rules = read_srt(srt_file)
        for r in rules:
            assert r.source in (Source.SRT_FILESYSTEM, Source.SRT_NETWORK)

    def test_non_security_fields_ignored(self, tmp_path: Path) -> None:
        """SRT fields like enabled, allowPty should not appear in rules."""
        srt = {
            "sandbox": {
                "enabled": True,
                "allowPty": True,
                "permissions": {
                    "filesystem": {
                        "read": {"denyOnly": ["**/.secret"]},
                    },
                },
            }
        }
        p = tmp_path / "srt.json"
        p.write_text(json.dumps(srt))
        rules = read_srt(p)
        # Only filesystem deny rules, no rules for enabled/allowPty
        assert len(rules) == 1
        assert rules[0].pattern == "**/.secret"

    def test_missing_file_raises_error(self, tmp_path: Path) -> None:
        missing = tmp_path / "nonexistent.json"
        with pytest.raises(FileNotFoundError, match=str(missing)):
            read_srt(missing)

    def test_invalid_json_raises_error(self, tmp_path: Path) -> None:
        bad = tmp_path / "bad.json"
        bad.write_text("{not valid json!!!")
        with pytest.raises(ValueError, match="Invalid JSON"):
            read_srt(bad)

    def test_tilde_in_paths_handled(self, tmp_path: Path) -> None:
        """Tilde paths in SRT deny entries should be preserved as-is (they're patterns)."""
        srt = {
            "sandbox": {
                "permissions": {
                    "filesystem": {
                        "read": {"denyOnly": ["~/.ssh"]},
                    }
                }
            }
        }
        p = tmp_path / "srt.json"
        p.write_text(json.dumps(srt))
        rules = read_srt(p)
        assert rules[0].pattern == "~/.ssh"


class TestReadBashRules:
    def test_deny_rules(self, bash_rules_file: Path) -> None:
        rules = read_bash_rules(bash_rules_file)
        denies = [r for r in rules if r.action == Action.DENY]
        assert len(denies) == 3
        patterns = {r.pattern for r in denies}
        assert "rm" in patterns
        assert "sudo" in patterns
        assert "git push --force" in patterns

    def test_ask_rules(self, bash_rules_file: Path) -> None:
        rules = read_bash_rules(bash_rules_file)
        asks = [r for r in rules if r.action == Action.ASK]
        assert len(asks) == 3
        patterns = {r.pattern for r in asks}
        assert "git push" in patterns
        assert "git commit" in patterns

    def test_all_rules_are_execute_scope(self, bash_rules_file: Path) -> None:
        rules = read_bash_rules(bash_rules_file)
        for r in rules:
            assert r.scope == Scope.EXECUTE
            assert r.source == Source.BASH_RULES

    def test_missing_file_raises_error(self, tmp_path: Path) -> None:
        missing = tmp_path / "nonexistent.json"
        with pytest.raises(FileNotFoundError, match=str(missing)):
            read_bash_rules(missing)

    def test_invalid_json_raises_error(self, tmp_path: Path) -> None:
        bad = tmp_path / "bad.json"
        bad.write_text("not json")
        with pytest.raises(ValueError, match="Invalid JSON"):
            read_bash_rules(bad)
