"""Tests for the Copilot native-sandbox policy builder (ADR 0009)."""

import os
from pathlib import Path

import pytest

from twsrt.lib.copilot_sandbox import build_policy
from twsrt.lib.models import Action, AppConfig, Scope, SecurityRule, Source

HOME = str(Path.home())


def deny_read(pattern: str) -> SecurityRule:
    return SecurityRule(Scope.READ, Action.DENY, pattern, Source.SRT_FILESYSTEM)


def deny_write(pattern: str) -> SecurityRule:
    return SecurityRule(Scope.WRITE, Action.DENY, pattern, Source.SRT_FILESYSTEM)


def allow_write(pattern: str) -> SecurityRule:
    return SecurityRule(Scope.WRITE, Action.ALLOW, pattern, Source.SRT_FILESYSTEM)


class TestDeniedPaths:
    def test_deny_read_literal_becomes_absolute_denied_path(self) -> None:
        """FR-001: ~ is expanded so diffs show one unambiguous spelling."""
        policy, _ = build_policy([deny_read("~/.ssh")], AppConfig())

        assert policy.denied == [f"{HOME}/.ssh"]

    def test_deny_read_keeps_paths_that_do_not_exist_yet(self) -> None:
        """FR-001: Copilot on macOS does not create missing denied paths, so a
        secret file created later is protected without regenerating."""
        missing = "/nonexistent-twsrt-probe/.netrc"

        policy, _ = build_policy([deny_read(missing)], AppConfig())

        assert policy.denied == [missing]

    def test_trailing_double_star_is_the_directory_itself(self) -> None:
        """FR-001: srt treats `dir/**` as `dir`; Copilot covers subtrees anyway."""
        policy, _ = build_policy([deny_read("~/.gnupg/**")], AppConfig())

        assert policy.denied == [f"{HOME}/.gnupg"]


class TestReadonlyPaths:
    def test_deny_write_literal_becomes_readonly(self) -> None:
        """FR-002."""
        policy, _ = build_policy([deny_write("~/.codex/config.toml")], AppConfig())

        assert policy.readonly == [f"{HOME}/.codex/config.toml"]

    def test_deny_write_implied_by_deny_read_is_not_repeated(self) -> None:
        """FR-002: denyRead already implies denyWrite (ADR 0001); a read-only
        entry would re-grant read access to a denied path."""
        rules = [deny_read("~/.ssh"), deny_write("~/.ssh")]

        policy, _ = build_policy(rules, AppConfig())

        assert policy.denied == [f"{HOME}/.ssh"]
        assert policy.readonly == []


class TestReadwritePaths:
    def test_allow_write_literal_becomes_readwrite(self) -> None:
        """FR-003."""
        rules = [allow_write("~/.cache"), allow_write("/tmp")]

        policy, _ = build_policy(rules, AppConfig())

        assert policy.readwrite == sorted(["/tmp", f"{HOME}/.cache"])

    def test_allow_write_dot_switches_on_the_working_directory_grant(self) -> None:
        """FR-003: Copilot's own cwd grant replaces the relative entry."""
        policy, _ = build_policy([allow_write(".")], AppConfig())

        assert policy.add_cwd is True
        assert policy.readwrite == []

    def test_without_allow_write_dot_the_working_directory_is_not_granted(
        self,
    ) -> None:
        policy, _ = build_policy([allow_write("/tmp")], AppConfig())

        assert policy.add_cwd is False

    def test_allow_write_dot_git_needs_no_entry(self) -> None:
        """FR-003: Copilot grants .git in a repository by itself."""
        policy, warnings = build_policy([allow_write(".git")], AppConfig())

        assert policy.readwrite == []
        assert not any(".git" in warning for warning in warnings)

    def test_dot_slash_spellings_count_as_the_working_directory(self) -> None:
        """FR-003: `./` and `./.git` mean `.` and `.git` to srt as well."""
        rules = [allow_write("./"), allow_write("./.git")]

        policy, warnings = build_policy(rules, AppConfig())

        assert policy.add_cwd is True
        assert policy.readwrite == []
        assert not any("skipped" in warning for warning in warnings)

    def test_readwrite_equal_to_a_denied_path_is_dropped_with_warning(self) -> None:
        """FR-004: the deny must win; an equal-specificity grant is ambiguous."""
        rules = [allow_write("~/.kube"), deny_read("~/.kube")]

        policy, warnings = build_policy(rules, AppConfig())

        assert policy.readwrite == []
        assert policy.denied == [f"{HOME}/.kube"]
        assert any(f"{HOME}/.kube" in w and "read/write" in w for w in warnings)

    def test_readwrite_equal_to_a_readonly_path_is_dropped_with_warning(
        self,
    ) -> None:
        """FR-004."""
        rules = [allow_write("~/.codex"), deny_write("~/.codex")]

        policy, warnings = build_policy(rules, AppConfig())

        assert policy.readwrite == []
        assert policy.readonly == [f"{HOME}/.codex"]
        assert any(f"{HOME}/.codex" in w and "read/write" in w for w in warnings)


class TestGlobs:
    def test_bounded_glob_is_expanded_to_existing_paths(self, tmp_path: Path) -> None:
        """FR-005: a wildcard below a concrete prefix can be snapshotted."""
        (tmp_path / "vaults" / "a" / "envs").mkdir(parents=True)
        (tmp_path / "vaults" / "b" / "envs").mkdir(parents=True)
        (tmp_path / "vaults" / "c").mkdir(parents=True)
        pattern = f"{tmp_path}/vaults/*/envs"

        policy, warnings = build_policy([deny_read(pattern)], AppConfig())

        assert policy.denied == [
            f"{tmp_path}/vaults/a/envs",
            f"{tmp_path}/vaults/b/envs",
        ]
        assert any(pattern in w and "snapshot" in w for w in warnings)

    def test_bounded_glob_expansion_includes_dot_entries(self, tmp_path: Path) -> None:
        """FR-005: srt's `*` matches dotfiles, so `secrets/*` must deny `.hidden`."""
        (tmp_path / "secrets").mkdir()
        (tmp_path / "secrets" / "token").write_text("")
        (tmp_path / "secrets" / ".hidden").write_text("")

        policy, _ = build_policy([deny_read(f"{tmp_path}/secrets/*")], AppConfig())

        assert policy.denied == [
            f"{tmp_path}/secrets/.hidden",
            f"{tmp_path}/secrets/token",
        ]

    def test_bounded_glob_in_deny_write_becomes_readonly(self, tmp_path: Path) -> None:
        """FR-005 follows FR-002 for its matches."""
        (tmp_path / "vaults" / "a" / "guarded").mkdir(parents=True)

        policy, _ = build_policy(
            [deny_write(f"{tmp_path}/vaults/*/guarded")], AppConfig()
        )

        assert policy.readonly == [f"{tmp_path}/vaults/a/guarded"]

    def test_bounded_glob_without_matches_still_warns(self, tmp_path: Path) -> None:
        """FR-005: the user must learn the pattern protects nothing today."""
        pattern = f"{tmp_path}/vaults/*/envs"

        policy, warnings = build_policy([deny_read(pattern)], AppConfig())

        assert policy.denied == []
        assert any(pattern in w for w in warnings)

    def test_unbounded_globs_and_relative_entries_are_dropped_with_one_warning(
        self,
    ) -> None:
        """FR-006: no path syntax says "this name anywhere"."""
        rules = [
            deny_write("/**/.env"),
            deny_write("/**/id_rsa"),
            deny_read("**/.twsrt/**"),
            deny_write(".git/config"),
            deny_write("~/*.pem"),
        ]

        policy, warnings = build_policy(rules, AppConfig())

        assert policy.denied == []
        assert policy.readonly == []
        dropped = [w for w in warnings if "skipped" in w]
        assert len(dropped) == 1
        for pattern in ("/**/.env", "/**/id_rsa", "**/.twsrt/**", ".git/config"):
            assert pattern in dropped[0]


class TestDeterminism:
    def test_shuffled_input_yields_identical_policy(self) -> None:
        """FR-013: stable output keeps diffs quiet."""
        rules = [deny_read("~/.ssh"), deny_read("~/.aws"), deny_read("~/.ssh")]

        first, _ = build_policy(rules, AppConfig())
        second, _ = build_policy(list(reversed(rules)), AppConfig())

        assert first == second
        assert first.denied == [f"{HOME}/.aws", f"{HOME}/.ssh"]


def allow_domain(pattern: str) -> SecurityRule:
    return SecurityRule(Scope.NETWORK, Action.ALLOW, pattern, Source.SRT_NETWORK)


def deny_domain(pattern: str) -> SecurityRule:
    return SecurityRule(Scope.NETWORK, Action.DENY, pattern, Source.SRT_NETWORK)


class TestNetwork:
    def test_allowed_domains_become_allowed_hosts_with_outbound_on(self) -> None:
        """FR-007: same *.x.com strict-subdomain syntax on both sides."""
        rules = [allow_domain("github.com"), allow_domain("*.github.com")]

        policy, _ = build_policy(rules, AppConfig())

        assert policy.allowed_hosts == ["*.github.com", "github.com"]
        assert policy.allow_outbound is True

    def test_port_suffix_is_removed_from_hosts_and_warned(self) -> None:
        """FR-007, FR-009: Copilot host rules take no port."""
        rules = [allow_domain("api.example.com:8443"), deny_domain("*:22")]

        policy, warnings = build_policy(rules, AppConfig())

        assert policy.allowed_hosts == ["api.example.com"]
        assert policy.blocked_hosts == ["*"]
        assert any("api.example.com:8443" in w for w in warnings)
        assert any("*:22" in w for w in warnings)

    def test_no_allowed_domains_switches_outbound_off(self) -> None:
        """FR-008: an empty Copilot allowlist means "no restriction" — the
        inverse of srt, so the empty case must turn the network off."""
        policy, _ = build_policy([deny_domain("evil.com")], AppConfig())

        assert policy.allowed_hosts == []
        assert policy.allow_outbound is False

    def test_denied_domains_become_blocked_hosts(self) -> None:
        """FR-009."""
        rules = [allow_domain("github.com"), deny_domain("pastebin.com")]

        policy, _ = build_policy(rules, AppConfig())

        assert policy.blocked_hosts == ["pastebin.com"]

    def test_url_rules_mirror_the_domains_unchanged(self) -> None:
        """FR-020: allowedUrls/deniedUrls keep the former flag values."""
        rules = [allow_domain("github.com"), deny_domain("pastebin.com")]

        policy, _ = build_policy(rules, AppConfig())

        assert policy.allowed_urls == ["github.com"]
        assert policy.denied_urls == ["pastebin.com"]

    def test_local_network_is_off_without_local_binding(self) -> None:
        """FR-010: written explicitly; JetBrains defaults it to on."""
        policy, warnings = build_policy([], AppConfig())

        assert policy.allow_local_network is False
        assert not any("allowLocalBinding" in w for w in warnings)

    def test_local_binding_maps_to_local_network_with_warning(self) -> None:
        """FR-010: bind-only in srt, connect-to-loopback in Copilot."""
        config = AppConfig(network_config={"allowLocalBinding": True})

        policy, warnings = build_policy([], config)

        assert policy.allow_local_network is True
        assert any("allowLocalBinding" in w for w in warnings)


class TestUntranslatedFieldWarnings:
    def test_each_untranslatable_srt_field_is_named(self) -> None:
        """FR-040: Copilot's own Seatbelt profile decides these; say so."""
        config = AppConfig(
            network_config={
                "allowUnixSockets": ["/tmp"],
                "allowMachLookup": ["com.apple.FSEvents"],
            },
            sandbox_config={
                "enabled": True,
                "enableWeakerNetworkIsolation": True,
                "ignoreViolations": {"*": ["/usr/bin"]},
            },
        )

        _, warnings = build_policy([], config)

        untranslated = [w for w in warnings if "no equivalent" in w]
        assert len(untranslated) == 1
        for key in (
            "allowUnixSockets",
            "allowMachLookup",
            "enableWeakerNetworkIsolation",
            "ignoreViolations",
        ):
            assert key in untranslated[0]
        assert "enabled" not in untranslated[0].split(":", 1)[1]
        assert "com.apple.FSEvents" not in untranslated[0]

    def test_no_untranslated_warning_without_such_fields(self) -> None:
        _, warnings = build_policy([], AppConfig())

        assert not any("no equivalent" in w for w in warnings)

    def test_software_only_enforcement_is_always_stated(self) -> None:
        """FR-040, G1: in-process tools have no OS backstop (accepted risk)."""
        _, warnings = build_policy([], AppConfig())

        assert any("software" in w and "in-process" in w for w in warnings)


class TestGuards:
    def test_disabled_canonical_sandbox_is_refused(self) -> None:
        """FR-012: never emit a native sandbox for a policy that disables srt."""
        config = AppConfig(sandbox_config={"enabled": False})

        with pytest.raises(ValueError, match="sandbox is disabled.*Copilot"):
            build_policy([], config)


class TestSelfProtection:
    def test_copilot_targets_are_readonly(self, tmp_path: Path) -> None:
        """FR-014: a session cannot rewrite the sandbox config it runs under."""
        settings = tmp_path / "settings.json"
        xml = tmp_path / "options" / "github-copilot.xml"
        config = AppConfig(
            copilot_settings_path=settings, copilot_jetbrains_xml_paths=[xml]
        )

        policy, _ = build_policy([], config)

        assert policy.readonly == sorted([str(settings), str(xml)])

    def test_symlinked_target_is_protected_under_both_spellings(
        self, tmp_path: Path
    ) -> None:
        """FR-014: Seatbelt matches the real path, the user sees the link."""
        real_dir = tmp_path / "dotfiles" / "dot-copilot"
        real_dir.mkdir(parents=True)
        link_dir = tmp_path / ".copilot"
        os.symlink(real_dir, link_dir)
        config = AppConfig(copilot_settings_path=link_dir / "settings.json")

        policy, _ = build_policy([], config)

        assert policy.readonly == sorted(
            [str(link_dir / "settings.json"), str(real_dir / "settings.json")]
        )
