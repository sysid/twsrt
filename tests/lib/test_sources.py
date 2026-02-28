"""Tests for sources.py: canonical source reading/validation."""

import json
from pathlib import Path

import pytest

from twsrt.lib.models import Action, Scope, Source
from twsrt.lib.sources import read_bash_rules, read_srt


class TestReadSrt:
    def test_deny_read_rules(self, srt_file: Path) -> None:
        rules = read_srt(srt_file).rules
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
        rules = read_srt(srt_file).rules
        deny_writes = [
            r for r in rules if r.scope == Scope.WRITE and r.action == Action.DENY
        ]
        # SAMPLE_SRT has 3 denyWithinAllow entries
        assert len(deny_writes) == 3
        patterns = {r.pattern for r in deny_writes}
        assert "**/.env" in patterns
        assert "**/*.pem" in patterns

    def test_allow_write_rules(self, srt_file: Path) -> None:
        rules = read_srt(srt_file).rules
        allow_writes = [
            r for r in rules if r.scope == Scope.WRITE and r.action == Action.ALLOW
        ]
        assert len(allow_writes) == 2
        patterns = {r.pattern for r in allow_writes}
        assert "." in patterns
        assert "/tmp" in patterns

    def test_allowed_domains(self, srt_file: Path) -> None:
        rules = read_srt(srt_file).rules
        network_allow = [
            r for r in rules if r.scope == Scope.NETWORK and r.action == Action.ALLOW
        ]
        assert len(network_allow) == 4
        domains = {r.pattern for r in network_allow}
        assert "github.com" in domains
        assert "pypi.org" in domains
        for r in network_allow:
            assert r.source == Source.SRT_NETWORK

    def test_all_rules_have_srt_source(self, srt_file: Path) -> None:
        rules = read_srt(srt_file).rules
        for r in rules:
            assert r.source in (Source.SRT_FILESYSTEM, Source.SRT_NETWORK)

    def test_non_security_fields_ignored(self, tmp_path: Path) -> None:
        """SRT fields like enabled, allowPty should not appear in rules."""
        srt = {
            "enabled": True,
            "allowPty": True,
            "filesystem": {
                "denyRead": ["**/.secret"],
            },
        }
        p = tmp_path / "srt.json"
        p.write_text(json.dumps(srt))
        result = read_srt(p)
        # Only filesystem deny rules, no rules for enabled/allowPty
        assert len(result.rules) == 1
        assert result.rules[0].pattern == "**/.secret"

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
            "filesystem": {
                "denyRead": ["~/.ssh"],
            },
        }
        p = tmp_path / "srt.json"
        p.write_text(json.dumps(srt))
        result = read_srt(p)
        assert result.rules[0].pattern == "~/.ssh"

    def test_denied_domains(self, srt_file: Path) -> None:
        """deniedDomains in SRT format produces NETWORK/DENY rules."""
        rules = read_srt(srt_file).rules
        denied = [
            r for r in rules if r.scope == Scope.NETWORK and r.action == Action.DENY
        ]
        assert len(denied) == 2
        patterns = {r.pattern for r in denied}
        assert "evil.com" in patterns
        assert "*.tracker.net" in patterns
        for r in denied:
            assert r.source == Source.SRT_NETWORK

    def test_flat_srt_denied_domains(self, tmp_path: Path) -> None:
        """Flat SRT format with deniedDomains produces NETWORK/DENY rules."""
        srt = {
            "network": {
                "allowedDomains": ["github.com"],
                "deniedDomains": ["evil.com", "*.tracker.net"],
            },
        }
        p = tmp_path / "srt.json"
        p.write_text(json.dumps(srt))
        rules = read_srt(p).rules
        denied = [
            r for r in rules if r.scope == Scope.NETWORK and r.action == Action.DENY
        ]
        assert len(denied) == 2
        assert {r.pattern for r in denied} == {"evil.com", "*.tracker.net"}

    def test_empty_denied_domains(self, tmp_path: Path) -> None:
        """Empty deniedDomains produces no NETWORK/DENY rules."""
        srt = {
            "network": {
                "allowedDomains": ["github.com"],
                "deniedDomains": [],
            },
        }
        p = tmp_path / "srt.json"
        p.write_text(json.dumps(srt))
        rules = read_srt(p).rules
        denied = [
            r for r in rules if r.scope == Scope.NETWORK and r.action == Action.DENY
        ]
        assert len(denied) == 0

    def test_flat_srt_format(self, tmp_path: Path) -> None:
        """Flat SRT format (top-level filesystem/network) is supported."""
        srt = {
            "filesystem": {
                "denyRead": ["**/.env", "**/.aws"],
                "denyWrite": ["**/*.pem"],
                "allowWrite": ["."],
            },
            "network": {
                "allowedDomains": ["github.com", "pypi.org"],
            },
        }
        p = tmp_path / "srt.json"
        p.write_text(json.dumps(srt))
        rules = read_srt(p).rules
        deny_reads = [
            r for r in rules if r.scope == Scope.READ and r.action == Action.DENY
        ]
        deny_writes = [
            r for r in rules if r.scope == Scope.WRITE and r.action == Action.DENY
        ]
        allow_writes = [
            r for r in rules if r.scope == Scope.WRITE and r.action == Action.ALLOW
        ]
        network_rules = [r for r in rules if r.scope == Scope.NETWORK]
        assert len(deny_reads) == 2
        assert len(deny_writes) == 1
        assert len(allow_writes) == 1
        assert len(network_rules) == 2
        assert {r.pattern for r in network_rules} == {"github.com", "pypi.org"}


class TestReadSrtNetworkConfig:
    """Tests for network_config extraction from SRT (FR-001, FR-003)."""

    def test_all_five_keys_present(self, tmp_path: Path) -> None:
        """All 5 pass-through network keys are extracted into network_config."""
        srt = {
            "network": {
                "allowedDomains": ["github.com"],
                "allowUnixSockets": ["/var/run/docker.sock"],
                "allowAllUnixSockets": True,
                "allowLocalBinding": True,
                "httpProxyPort": 8080,
                "socksProxyPort": 1080,
            },
        }
        p = tmp_path / "srt.json"
        p.write_text(json.dumps(srt))
        result = read_srt(p)
        assert result.network_config["allowUnixSockets"] == ["/var/run/docker.sock"]
        assert result.network_config["allowAllUnixSockets"] is True
        assert result.network_config["allowLocalBinding"] is True
        assert result.network_config["httpProxyPort"] == 8080
        assert result.network_config["socksProxyPort"] == 1080

    def test_partial_keys(self, tmp_path: Path) -> None:
        """Only present keys appear in network_config."""
        srt = {
            "network": {
                "allowedDomains": ["github.com"],
                "allowLocalBinding": True,
            },
        }
        p = tmp_path / "srt.json"
        p.write_text(json.dumps(srt))
        result = read_srt(p)
        assert result.network_config == {"allowLocalBinding": True}

    def test_no_network_config_keys(self, tmp_path: Path) -> None:
        """SRT with only allowedDomains produces empty network_config."""
        srt = {
            "network": {
                "allowedDomains": ["github.com"],
            },
        }
        p = tmp_path / "srt.json"
        p.write_text(json.dumps(srt))
        result = read_srt(p)
        assert result.network_config == {}

    def test_empty_unix_sockets_list(self, tmp_path: Path) -> None:
        """Empty allowUnixSockets list is preserved (not omitted)."""
        srt = {
            "network": {
                "allowUnixSockets": [],
            },
        }
        p = tmp_path / "srt.json"
        p.write_text(json.dumps(srt))
        result = read_srt(p)
        assert result.network_config["allowUnixSockets"] == []

    def test_falsy_port_zero(self, tmp_path: Path) -> None:
        """Port value 0 is valid and preserved (not omitted)."""
        srt = {
            "network": {
                "httpProxyPort": 0,
            },
        }
        p = tmp_path / "srt.json"
        p.write_text(json.dumps(srt))
        result = read_srt(p)
        assert result.network_config["httpProxyPort"] == 0

    def test_returns_srt_result_type(self, srt_file: Path) -> None:
        """read_srt returns SrtResult with rules attribute."""
        from twsrt.lib.models import SrtResult

        result = read_srt(srt_file)
        assert isinstance(result, SrtResult)
        assert len(result.rules) > 0

    def test_excluded_keys_not_in_config(self, tmp_path: Path) -> None:
        """deniedDomains and mitmProxy are NOT in network_config (FR-004)."""
        srt = {
            "network": {
                "allowedDomains": ["github.com"],
                "deniedDomains": ["evil.com"],
                "mitmProxy": True,
                "allowLocalBinding": True,
            },
        }
        p = tmp_path / "srt.json"
        p.write_text(json.dumps(srt))
        result = read_srt(p)
        assert "deniedDomains" not in result.network_config
        assert "mitmProxy" not in result.network_config
        assert "allowLocalBinding" in result.network_config


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
