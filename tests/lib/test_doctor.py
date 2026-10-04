"""Tests for `twsrt doctor` diagnostics: correctness, redundancy, pattern traps."""

from pathlib import Path

import pytest

from twsrt.lib.config import load_config
from twsrt.lib.doctor import Finding, diagnose


@pytest.fixture(autouse=True)
def isolated_home(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    """doctor inspects paths on disk (symlinks, home roots): never the host's."""
    home = tmp_path / "isolated-home"
    home.mkdir()
    monkeypatch.setenv("HOME", str(home))
    return home


def write_config(
    tmp_path: Path,
    srt: dict[str, str],
    bash: dict[str, str],
    profiles: str,
    default_profile: str = "default",
) -> Path:
    """Register every given fragment and write the profiles verbatim."""
    (tmp_path / "srt").mkdir()
    (tmp_path / "bash").mkdir()
    registry = ["[sources.srt]", 'output = "out/srt.json"']
    for name, body in srt.items():
        (tmp_path / f"srt/{name}.jsonc").write_text(body)
        registry += [f"[sources.srt.fragments.{name}]", f'path = "srt/{name}.jsonc"']
    registry += ["[sources.bash]", 'output = "out/bash.json"']
    for name, body in bash.items():
        (tmp_path / f"bash/{name}.jsonc").write_text(body)
        registry += [f"[sources.bash.fragments.{name}]", f'path = "bash/{name}.jsonc"']
    config = tmp_path / "config.toml"
    config.write_text(
        f'schema_version = 1\ndefault_profile = "{default_profile}"\n\n'
        + "\n".join(registry)
        + "\n\n"
        + profiles
    )
    return config


def run(config: Path) -> list[Finding]:
    return diagnose(load_config(config), config.parent)


def codes(findings: list[Finding]) -> list[str]:
    return [finding.code for finding in findings]


BASH_BASE = '{"allow": [], "ask": [], "deny": ["rm"]}'


# --- A. correctness -------------------------------------------------------


def test_clean_configuration_has_no_findings(tmp_path: Path) -> None:
    config = write_config(
        tmp_path,
        srt={"base": '{"enabled": true, "filesystem": {"denyRead": ["~/.ssh"]}}'},
        bash={"base": BASH_BASE},
        profiles='[profiles.default]\nsrt = ["base"]\nbash = ["base"]\n',
    )

    assert run(config) == []


def test_every_profile_is_compiled_not_only_the_default(tmp_path: Path) -> None:
    config = write_config(
        tmp_path,
        srt={
            "base": '{"enabled": true}',
            "off": '{"enabled": false}',
        },
        bash={"base": BASH_BASE},
        profiles=(
            '[profiles.default]\nsrt = ["base"]\nbash = ["base"]\n\n'
            '[profiles.broken]\nextends = ["default"]\nsrt = ["off"]\n'
        ),
    )

    findings = run(config)

    assert codes(findings) == ["profile-compile"]
    assert findings[0].severity == "error"
    assert findings[0].location == "profile 'broken'"
    assert "/enabled" in findings[0].message


def test_unparseable_fragment_is_an_error_even_when_unused(tmp_path: Path) -> None:
    config = write_config(
        tmp_path,
        srt={"base": '{"enabled": true}', "draft": '{"enabled": tru'},
        bash={"base": BASH_BASE},
        profiles='[profiles.default]\nsrt = ["base"]\nbash = ["base"]\n',
    )

    findings = run(config)

    assert ("error", "fragment-load") in [(f.severity, f.code) for f in findings]
    assert [f.location for f in findings if f.code == "fragment-load"] == [
        "srt/draft.jsonc"
    ]


def test_profile_using_a_broken_fragment_is_not_reported_twice(
    tmp_path: Path,
) -> None:
    config = write_config(
        tmp_path,
        srt={"base": '{"enabled": tru'},
        bash={"base": BASH_BASE},
        profiles='[profiles.default]\nsrt = ["base"]\nbash = ["base"]\n',
    )

    assert codes(run(config)) == ["fragment-load"]


def test_mixin_profile_that_cannot_stand_alone_is_a_warning(tmp_path: Path) -> None:
    config = write_config(
        tmp_path,
        srt={"base": '{"enabled": true}', "extra": "{}"},
        bash={"base": BASH_BASE},
        profiles=(
            '[profiles.default]\nsrt = ["base", "extra"]\nbash = ["base"]\n\n'
            '[profiles.mixin]\nsrt = ["extra"]\n'
        ),
    )

    findings = run(config)

    assert [(f.severity, f.code) for f in findings] == [
        ("warning", "profile-incomplete")
    ]
    assert findings[0].location == "profile 'mixin'"


# --- B. redundancy --------------------------------------------------------


def test_path_below_an_already_listed_directory_is_redundant(tmp_path: Path) -> None:
    config = write_config(
        tmp_path,
        srt={
            "base": '{"enabled": true, "filesystem": {"allowWrite": ["~/dev/los"]}}',
            "work": '{"filesystem": {"allowWrite": ["~/dev/los/instructions"]}}',
        },
        bash={"base": BASH_BASE},
        profiles='[profiles.default]\nsrt = ["base", "work"]\nbash = ["base"]\n',
    )

    findings = run(config)

    assert codes(findings) == ["subsumed-rule"]
    assert findings[0].severity == "warning"
    assert findings[0].location == "srt/work.jsonc"
    assert findings[0].message == "filesystem.allowWrite: 1 entry already covered"
    assert findings[0].items == (
        "'~/dev/los/instructions' by '~/dev/los' (srt/base.jsonc)",
    )


def test_sibling_with_a_shared_name_prefix_is_not_redundant(tmp_path: Path) -> None:
    config = write_config(
        tmp_path,
        srt={
            "base": (
                '{"enabled": true, "filesystem": '
                '{"denyRead": ["~/.aws", "~/.aws-vault"]}}'
            )
        },
        bash={"base": BASH_BASE},
        profiles='[profiles.default]\nsrt = ["base"]\nbash = ["base"]\n',
    )

    assert run(config) == []


def test_relative_path_is_covered_by_the_working_directory_entry(
    tmp_path: Path,
) -> None:
    config = write_config(
        tmp_path,
        srt={
            "base": (
                '{"enabled": true, "filesystem": {"allowWrite": [".", "./build"]}}'
            )
        },
        bash={"base": BASH_BASE},
        profiles='[profiles.default]\nsrt = ["base"]\nbash = ["base"]\n',
    )

    findings = run(config)

    assert codes(findings) == ["subsumed-rule"]
    assert findings[0].items == ("'./build' by '.'",)


def test_wildcard_covered_by_a_broader_wildcard_is_redundant(
    tmp_path: Path,
) -> None:
    config = write_config(
        tmp_path,
        srt={
            "base": (
                '{"enabled": true, "network": {"allowedDomains": '
                '["*.github.com", "*.api.github.com", "api.github.com", '
                '"github.com"]}}'
            )
        },
        bash={"base": BASH_BASE},
        profiles='[profiles.default]\nsrt = ["base"]\nbash = ["base"]\n',
    )

    findings = run(config)

    assert codes(findings) == ["subsumed-rule"]
    assert findings[0].items == ("'*.api.github.com' by '*.github.com'",)


def test_concrete_host_under_a_wildcard_is_kept_as_a_probe_target(
    tmp_path: Path,
) -> None:
    # `twsrt test` cannot dial a wildcard: a concrete host below it is the
    # only live probe of that rule, so it is not dead weight.
    config = write_config(
        tmp_path,
        srt={
            "base": (
                '{"enabled": true, "network": {'
                '"allowedDomains": ["*.github.com", "api.github.com", "github.com"], '
                '"deniedDomains": ["*", "evil.example"]}}'
            )
        },
        bash={"base": BASH_BASE},
        profiles='[profiles.default]\nsrt = ["base"]\nbash = ["base"]\n',
    )

    assert run(config) == []


def test_bash_command_covered_by_a_shorter_prefix_is_redundant(
    tmp_path: Path,
) -> None:
    config = write_config(
        tmp_path,
        srt={"base": '{"enabled": true}'},
        bash={"base": '{"allow": [], "ask": [], "deny": ["git", "git push", "gitk"]}'},
        profiles='[profiles.default]\nsrt = ["base"]\nbash = ["base"]\n',
    )

    findings = run(config)

    assert codes(findings) == ["subsumed-rule"]
    assert findings[0].message == "deny: 1 entry already covered"
    assert findings[0].items == ("'git push' by 'git'",)


def test_same_rule_in_two_fragments_of_one_profile_is_a_duplicate(
    tmp_path: Path,
) -> None:
    config = write_config(
        tmp_path,
        srt={
            "base": '{"enabled": true, "filesystem": {"denyRead": ["~/.ssh"]}}',
            "work": '{"filesystem": {"denyRead": ["~/.ssh"]}}',
        },
        bash={"base": BASH_BASE},
        profiles='[profiles.default]\nsrt = ["base", "work"]\nbash = ["base"]\n',
    )

    findings = run(config)

    assert codes(findings) == ["duplicate-rule"]
    # Reported at the later fragment: that copy is the redundant one.
    assert findings[0].location == "srt/work.jsonc"
    assert findings[0].message == "filesystem.denyRead: 1 entry also in srt/base.jsonc"
    assert findings[0].items == ("'~/.ssh'",)


def test_duplicates_between_the_same_fragments_are_grouped_per_list(
    tmp_path: Path,
) -> None:
    config = write_config(
        tmp_path,
        srt={
            "base": (
                '{"enabled": true, "filesystem": {"denyRead": ["~/.ssh", "~/.aws"]}}'
            ),
            "work": '{"filesystem": {"denyRead": ["~/.ssh", "~/.aws"]}}',
        },
        bash={"base": BASH_BASE},
        profiles='[profiles.default]\nsrt = ["base", "work"]\nbash = ["base"]\n',
    )

    findings = run(config)

    assert codes(findings) == ["duplicate-rule"]
    assert findings[0].location == "srt/work.jsonc"
    assert findings[0].message == (
        "filesystem.denyRead: 2 entries also in srt/base.jsonc"
    )
    assert findings[0].items == ("'~/.ssh'", "'~/.aws'")


def test_findings_shared_by_several_profiles_are_reported_once(
    tmp_path: Path,
) -> None:
    config = write_config(
        tmp_path,
        srt={
            "base": '{"enabled": true, "filesystem": {"denyRead": ["~/.ssh"]}}',
            "work": '{"filesystem": {"denyRead": ["~/.ssh"]}}',
        },
        bash={"base": BASH_BASE},
        profiles=(
            '[profiles.default]\nsrt = ["base", "work"]\nbash = ["base"]\n\n'
            '[profiles.other]\nextends = ["default"]\n'
        ),
    )

    assert codes(run(config)) == ["duplicate-rule"]


def test_fragment_selected_again_after_extends_is_redundant(tmp_path: Path) -> None:
    config = write_config(
        tmp_path,
        srt={"base": '{"enabled": true}', "work": "{}"},
        bash={"base": BASH_BASE},
        profiles=(
            '[profiles.default]\nsrt = ["base"]\nbash = ["base"]\n\n'
            '[profiles.work]\nextends = ["default"]\nsrt = ["base", "work"]\n'
        ),
    )

    findings = run(config)

    assert codes(findings) == ["inherited-fragment"]
    assert findings[0].location == "profile 'work'"
    assert findings[0].message == (
        "srt fragment 'base' is already inherited from 'default'"
    )


def test_parent_already_reached_through_another_parent_is_redundant(
    tmp_path: Path,
) -> None:
    config = write_config(
        tmp_path,
        srt={"base": '{"enabled": true}', "work": "{}"},
        bash={"base": BASH_BASE},
        profiles=(
            '[profiles.default]\nsrt = ["base"]\nbash = ["base"]\n\n'
            '[profiles.work]\nextends = ["default"]\nsrt = ["work"]\n\n'
            '[profiles.both]\nextends = ["default", "work"]\n'
        ),
    )

    findings = run(config)

    assert codes(findings) == ["redundant-extends"]
    assert findings[0].location == "profile 'both'"
    assert findings[0].message == "extends 'default' is already inherited via 'work'"


def test_registered_fragment_no_profile_selects_is_unused(tmp_path: Path) -> None:
    config = write_config(
        tmp_path,
        srt={"base": '{"enabled": true}', "old": "{}"},
        bash={"base": BASH_BASE},
        profiles='[profiles.default]\nsrt = ["base"]\nbash = ["base"]\n',
    )

    findings = run(config)

    assert codes(findings) == ["unused-fragment"]
    assert findings[0].location == "srt/old.jsonc"
    assert findings[0].message == "srt fragment 'old' is selected by no profile"


# --- C. pattern traps -----------------------------------------------------


def test_trailing_double_star_is_reported_as_a_no_op(tmp_path: Path) -> None:
    config = write_config(
        tmp_path,
        srt={"base": '{"enabled": true, "filesystem": {"denyRead": ["~/.kube/**"]}}'},
        bash={"base": BASH_BASE},
        profiles='[profiles.default]\nsrt = ["base"]\nbash = ["base"]\n',
    )

    findings = run(config)

    assert [(f.severity, f.code) for f in findings] == [("info", "noop-glob-suffix")]
    assert findings[0].items == ("'~/.kube/**'",)


def test_glob_in_an_allow_list_grants_less_than_it_looks(tmp_path: Path) -> None:
    config = write_config(
        tmp_path,
        srt={
            "base": (
                '{"enabled": true, "filesystem": '
                '{"allowWrite": ["~/work/*", "~/repos/*/build/**"]}}'
            )
        },
        bash={"base": BASH_BASE},
        profiles='[profiles.default]\nsrt = ["base"]\nbash = ["base"]\n',
    )

    findings = run(config)

    assert [(f.severity, f.code) for f in findings] == [
        ("warning", "narrow-allow-glob")
    ]
    assert findings[0].items == ("'~/work/*'", "'~/repos/*/build/**'")


def test_relative_recursive_glob_is_anchored_at_the_launch_directory(
    tmp_path: Path,
) -> None:
    config = write_config(
        tmp_path,
        srt={"base": '{"enabled": true, "filesystem": {"denyRead": ["**/.env"]}}'},
        bash={"base": BASH_BASE},
        profiles='[profiles.default]\nsrt = ["base"]\nbash = ["base"]\n',
    )

    findings = run(config)

    assert [(f.severity, f.code) for f in findings] == [
        ("warning", "cwd-anchored-glob")
    ]


def test_deny_write_glob_is_noted_as_dropped_on_linux(tmp_path: Path) -> None:
    config = write_config(
        tmp_path,
        srt={
            "base": '{"enabled": true, "filesystem": {"denyWrite": ["~/.config/*.toml"]}}'
        },
        bash={"base": BASH_BASE},
        profiles='[profiles.default]\nsrt = ["base"]\nbash = ["base"]\n',
    )

    findings = run(config)

    assert [(f.severity, f.code) for f in findings] == [
        ("info", "linux-drops-write-glob")
    ]


def test_wildcard_domain_without_its_apex_is_noted(tmp_path: Path) -> None:
    config = write_config(
        tmp_path,
        srt={
            "base": (
                '{"enabled": true, "network": '
                '{"allowedDomains": ["*.pypi.org", "*.npmjs.org", "*.github.com", '
                '"github.com"]}}'
            )
        },
        bash={"base": BASH_BASE},
        profiles='[profiles.default]\nsrt = ["base"]\nbash = ["base"]\n',
    )

    findings = run(config)

    assert [(f.severity, f.code) for f in findings] == [("info", "wildcard-apex")]
    assert findings[0].items == (
        "'*.pypi.org' (pypi.org)",
        "'*.npmjs.org' (npmjs.org)",
    )


def test_findings_are_ordered_errors_first(tmp_path: Path) -> None:
    config = write_config(
        tmp_path,
        srt={
            "base": '{"enabled": true, "filesystem": {"denyRead": ["~/.kube/**"]}}',
            "off": '{"enabled": false}',
            "old": "{}",
        },
        bash={"base": BASH_BASE},
        profiles=(
            '[profiles.default]\nsrt = ["base"]\nbash = ["base"]\n\n'
            '[profiles.broken]\nextends = ["default"]\nsrt = ["off"]\n'
        ),
    )

    assert codes(run(config)) == [
        "profile-compile",
        "unused-fragment",
        "noop-glob-suffix",
    ]


def test_home_relative_and_absolute_spellings_are_compared_alike(
    tmp_path: Path, monkeypatch
) -> None:
    home = tmp_path / "home"
    monkeypatch.setenv("HOME", str(home))
    config = write_config(
        tmp_path,
        srt={
            "base": (
                '{"enabled": true, "filesystem": '
                f'{{"denyRead": ["~/.aws", "{home}/.aws/sso"]}}}}'
            )
        },
        bash={"base": BASH_BASE},
        profiles='[profiles.default]\nsrt = ["base"]\nbash = ["base"]\n',
    )

    findings = run(config)

    assert codes(findings) == ["subsumed-rule"]
    # Same fragment on both sides: the covering entry needs no location.
    assert findings[0].items == (f"'{home}/.aws/sso' by '~/.aws'",)


def test_pattern_traps_are_grouped_per_fragment_and_list(tmp_path: Path) -> None:
    config = write_config(
        tmp_path,
        srt={
            "base": (
                '{"enabled": true, "filesystem": '
                '{"denyRead": ["**/.env", "**/*.pem", "**/id_rsa"]}}'
            ),
            "work": '{"filesystem": {"denyRead": ["**/.npmrc"]}}',
        },
        bash={"base": BASH_BASE},
        profiles='[profiles.default]\nsrt = ["base", "work"]\nbash = ["base"]\n',
    )

    findings = run(config)

    assert codes(findings) == ["cwd-anchored-glob", "cwd-anchored-glob"]
    assert [(f.location, f.items) for f in findings] == [
        ("srt/base.jsonc", ("'**/.env'", "'**/*.pem'", "'**/id_rsa'")),
        ("srt/work.jsonc", ("'**/.npmrc'",)),
    ]
    assert findings[0].message.startswith("filesystem.denyRead: 3 entries ")


def test_subsumed_rules_are_grouped_per_fragment_and_list(tmp_path: Path) -> None:
    config = write_config(
        tmp_path,
        srt={
            "base": (
                '{"enabled": true, "network": {"allowedDomains": '
                '["*.npmjs.org", "*.registry.npmjs.org", "*.crates.io", '
                '"*.static.crates.io", "crates.io", "npmjs.org", '
                '"registry.npmjs.org", "static.crates.io"]}}'
            )
        },
        bash={"base": BASH_BASE},
        profiles='[profiles.default]\nsrt = ["base"]\nbash = ["base"]\n',
    )

    findings = run(config)

    assert codes(findings) == ["subsumed-rule"]
    assert findings[0].location == "srt/base.jsonc"
    assert findings[0].message == "network.allowedDomains: 2 entries already covered"
    assert findings[0].items == (
        "'*.registry.npmjs.org' by '*.npmjs.org'",
        "'*.static.crates.io' by '*.crates.io'",
    )


def test_read_deny_inside_a_write_root_is_not_flagged_since_compile_implies_write_deny(
    tmp_path: Path,
) -> None:
    # The compiler adds every denyRead path to denyWrite, so a read deny below
    # an allowWrite root is no longer overwritable and needs no finding.
    config = write_config(
        tmp_path,
        srt={
            "base": (
                '{"enabled": true, "filesystem": {"allowWrite": [".", "~/xxx"], '
                '"denyRead": ["./secrets", "~/xxx/secret"]}}'
            )
        },
        bash={"base": BASH_BASE},
        profiles='[profiles.default]\nsrt = ["base"]\nbash = ["base"]\n',
    )

    assert run(config) == []


def test_write_only_path_surfaces_as_a_compile_error(tmp_path: Path) -> None:
    config = write_config(
        tmp_path,
        srt={
            "base": (
                '{"enabled": true, "filesystem": '
                '{"allowWrite": ["~/logs"], "denyRead": ["~/logs"]}}'
            )
        },
        bash={"base": BASH_BASE},
        profiles='[profiles.default]\nsrt = ["base"]\nbash = ["base"]\n',
    )

    findings = run(config)

    assert codes(findings) == ["profile-compile"]
    assert "~/logs" in findings[0].message
    assert "denyRead implies denyWrite" in findings[0].message


def test_equivalent_spellings_of_one_directory_are_reported_once(
    tmp_path: Path,
) -> None:
    config = write_config(
        tmp_path,
        srt={
            "base": (
                '{"enabled": true, "filesystem": '
                '{"allowWrite": ["~/.copilot/ide", "~/.copilot/ide/**"]}}'
            )
        },
        bash={"base": BASH_BASE},
        profiles='[profiles.default]\nsrt = ["base"]\nbash = ["base"]\n',
    )

    subsumed = [f for f in run(config) if f.code == "subsumed-rule"]

    assert len(subsumed) == 1
    assert subsumed[0].items == ("'~/.copilot/ide/**' by '~/.copilot/ide'",)


def test_wildcard_apex_is_reported_once_per_fragment_across_profiles(
    tmp_path: Path,
) -> None:
    config = write_config(
        tmp_path,
        srt={
            "base": '{"enabled": true, "network": {"allowedDomains": ["*.npmjs.org"]}}',
            "work": '{"network": {"allowedDomains": ["*.corp.example"]}}',
        },
        bash={"base": BASH_BASE},
        profiles=(
            '[profiles.default]\nsrt = ["base"]\nbash = ["base"]\n\n'
            '[profiles.work]\nextends = ["default"]\nsrt = ["work"]\n'
        ),
    )

    apex = [(f.location, f.items) for f in run(config) if f.code == "wildcard-apex"]

    assert apex == [
        ("srt/base.jsonc", ("'*.npmjs.org' (npmjs.org)",)),
        ("srt/work.jsonc", ("'*.corp.example' (corp.example)",)),
    ]


# --- symlinked deny paths (bkmr 3686) ------------------------------------


def test_symlinked_deny_path_without_its_real_path_is_flagged(
    tmp_path: Path, monkeypatch
) -> None:
    home = tmp_path / "home"
    real = tmp_path / "configs" / "dot-aws"
    real.mkdir(parents=True)
    home.mkdir()
    (home / ".aws").symlink_to(real)
    monkeypatch.setenv("HOME", str(home))
    config = write_config(
        tmp_path,
        srt={"base": '{"enabled": true, "filesystem": {"denyRead": ["~/.aws"]}}'},
        bash={"base": BASH_BASE},
        profiles='[profiles.default]\nsrt = ["base"]\nbash = ["base"]\n',
    )

    findings = [f for f in run(config) if f.code == "symlinked-deny-path"]

    assert len(findings) == 1
    assert findings[0].severity == "warning"
    assert findings[0].location == "srt/base.jsonc"
    assert findings[0].message.startswith("filesystem.denyRead: 1 entry through ")
    assert findings[0].items == (f"'~/.aws' (-> {real})",)


def test_symlinked_deny_path_with_its_real_path_listed_is_fine(
    tmp_path: Path, monkeypatch
) -> None:
    home = tmp_path / "home"
    real = tmp_path / "configs" / "dot-aws"
    real.mkdir(parents=True)
    home.mkdir()
    (home / ".aws").symlink_to(real)
    monkeypatch.setenv("HOME", str(home))
    config = write_config(
        tmp_path,
        srt={
            "base": (
                '{"enabled": true, "filesystem": '
                f'{{"denyRead": ["~/.aws", "{tmp_path}/configs"]}}}}'
            )
        },
        bash={"base": BASH_BASE},
        profiles='[profiles.default]\nsrt = ["base"]\nbash = ["base"]\n',
    )

    assert "symlinked-deny-path" not in codes(run(config))


# --- broad allowWrite (ADR 0002 auto-approval) ---------------------------


def test_allow_write_covering_home_or_config_roots_is_broad(
    tmp_path: Path, monkeypatch
) -> None:
    home = tmp_path / "home"
    home.mkdir()
    monkeypatch.setenv("HOME", str(home))
    config = write_config(
        tmp_path,
        srt={
            "base": (
                '{"enabled": true, "filesystem": '
                '{"allowWrite": ["~", "~/.config", "~/.cache", "/"]}}'
            )
        },
        bash={"base": BASH_BASE},
        profiles='[profiles.default]\nsrt = ["base"]\nbash = ["base"]\n',
    )

    findings = [f for f in run(config) if f.code == "broad-allow-write"]

    assert len(findings) == 1
    assert findings[0].location == "srt/base.jsonc"
    assert findings[0].message.startswith("filesystem.allowWrite: 3 entries ")
    assert findings[0].items == ("'~'", "'~/.config'", "'/'")


# --- relative entries in Claude sandbox.filesystem (bkmr 3742) -----------


def test_relative_entries_in_claude_sandbox_filesystem_are_flagged(
    tmp_path: Path,
) -> None:
    config = write_config(
        tmp_path,
        srt={"base": '{"enabled": true}'},
        bash={"base": BASH_BASE},
        profiles='[profiles.default]\nsrt = ["base"]\nbash = ["base"]\n',
    )
    repo_settings = tmp_path / "repo" / ".claude" / "settings.json"
    repo_settings.parent.mkdir(parents=True)
    repo_settings.write_text(
        '{"sandbox": {"filesystem": {"allowWrite": [".", "~/x", "/abs", "//abs2"],'
        ' "denyRead": ["**/.env"]}}}'
    )
    absent = tmp_path / "missing.json"

    findings = [
        f
        for f in diagnose(load_config(config), config.parent, [repo_settings, absent])
        if f.code == "claude-relative-sandbox-path"
    ]

    assert [f.severity for f in findings] == ["warning", "warning"]
    assert findings[0].location == str(repo_settings)
    assert findings[0].message.startswith("sandbox.filesystem.allowWrite: 1 entry ")
    assert findings[0].items == ("'.'",)
    assert findings[1].items == ("'**/.env'",)


def test_unreadable_claude_settings_file_is_skipped_not_fatal(tmp_path: Path) -> None:
    config = write_config(
        tmp_path,
        srt={"base": '{"enabled": true}'},
        bash={"base": BASH_BASE},
        profiles='[profiles.default]\nsrt = ["base"]\nbash = ["base"]\n',
    )
    broken = tmp_path / "broken.json"
    broken.write_text("{ not json")

    assert diagnose(load_config(config), config.parent, [broken]) == []


# --- E. doctor-ignore comments --------------------------------------------


def test_bare_doctor_ignore_silences_every_finding_for_that_line(
    tmp_path: Path,
) -> None:
    config = write_config(
        tmp_path,
        srt={
            "base": (
                '{"enabled": true, "filesystem": {"denyWrite": [\n'
                '  "**/.env",  // doctor-ignore\n'
                '  "**/*.pem"\n'
                "]}}"
            )
        },
        bash={"base": BASH_BASE},
        profiles='[profiles.default]\nsrt = ["base"]\nbash = ["base"]\n',
    )

    findings = run(config)

    assert codes(findings) == ["cwd-anchored-glob"]
    assert findings[0].items == ("'**/*.pem'",)


def test_doctor_ignore_text_after_the_colon_is_a_reason_not_a_filter(
    tmp_path: Path,
) -> None:
    # '~/x/**' is both subsumed by '~/x' and a no-op /** suffix: a reason that
    # happens to name one finding still silences both.
    config = write_config(
        tmp_path,
        srt={
            "base": (
                '{"enabled": true, "filesystem": {"allowWrite": [\n'
                '  "~/x",\n'
                '  "~/x/**"  // doctor-ignore: subsumed-rule, kept for readers\n'
                "]}}"
            )
        },
        bash={"base": BASH_BASE},
        profiles='[profiles.default]\nsrt = ["base"]\nbash = ["base"]\n',
    )

    assert run(config) == []


def test_doctor_ignore_works_in_bash_fragments(tmp_path: Path) -> None:
    config = write_config(
        tmp_path,
        srt={"base": '{"enabled": true}'},
        bash={
            "base": (
                '{"allow": [], "ask": [], "deny": [\n'
                '  "rm",\n'
                '  "rm -rf",  // doctor-ignore: explicit for readers\n'
                '  "rm -r"\n'
                "]}"
            )
        },
        profiles='[profiles.default]\nsrt = ["base"]\nbash = ["base"]\n',
    )

    findings = run(config)

    assert codes(findings) == ["subsumed-rule"]
    assert findings[0].items == ("'rm -r' by 'rm'",)


def test_doctor_ignore_silences_wildcard_apex_on_the_wildcard_line(
    tmp_path: Path,
) -> None:
    config = write_config(
        tmp_path,
        srt={
            "base": (
                '{"enabled": true, "network": {"allowedDomains": [\n'
                '  "*.pypi.org",  // doctor-ignore: no apex host exists\n'
                '  "*.npmjs.org"\n'
                "]}}"
            )
        },
        bash={"base": BASH_BASE},
        profiles='[profiles.default]\nsrt = ["base"]\nbash = ["base"]\n',
    )

    findings = run(config)

    assert codes(findings) == ["wildcard-apex"]
    assert findings[0].items == ("'*.npmjs.org' (npmjs.org)",)


def test_doctor_ignore_inside_a_string_or_plain_comment_is_not_a_directive(
    tmp_path: Path,
) -> None:
    config = write_config(
        tmp_path,
        srt={
            "base": (
                '{"enabled": true, "filesystem": {"denyWrite": [\n'
                '  "**/// doctor-ignore",\n'
                '  "**/.env"  // see doctor-ignore docs\n'
                "]}}"
            )
        },
        bash={"base": BASH_BASE},
        profiles='[profiles.default]\nsrt = ["base"]\nbash = ["base"]\n',
    )

    findings = run(config)

    assert codes(findings) == ["cwd-anchored-glob"]
    assert findings[0].message.startswith("filesystem.denyWrite: 2 entries ")
