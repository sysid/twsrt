"""Tests for `twsrt doctor` diagnostics: correctness, redundancy, pattern traps."""

from pathlib import Path

from twsrt.lib.config import load_config
from twsrt.lib.doctor import Finding, diagnose


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
    assert "profile 'broken'" in findings[0].message
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
    assert any("srt/draft.jsonc" in f.message for f in findings)


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
    assert "mixin" in findings[0].message


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
    message = findings[0].message
    assert message.startswith("srt/work.jsonc: filesystem.allowWrite: ")
    assert "'~/dev/los/instructions' by '~/dev/los' (srt/base.jsonc)" in message


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
    assert "'./build'" in findings[0].message


def test_domain_covered_by_a_wildcard_is_redundant_but_the_apex_is_not(
    tmp_path: Path,
) -> None:
    config = write_config(
        tmp_path,
        srt={
            "base": (
                '{"enabled": true, "network": {"allowedDomains": '
                '["*.github.com", "api.github.com", "github.com"]}}'
            )
        },
        bash={"base": BASH_BASE},
        profiles='[profiles.default]\nsrt = ["base"]\nbash = ["base"]\n',
    )

    findings = run(config)

    assert codes(findings) == ["subsumed-rule"]
    assert "'api.github.com'" in findings[0].message
    assert "'*.github.com'" in findings[0].message


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
    assert "deny" in findings[0].message
    assert "'git push'" in findings[0].message


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
    assert "'~/.ssh'" in findings[0].message
    assert "srt/base.jsonc" in findings[0].message
    assert "srt/work.jsonc" in findings[0].message


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
    assert "profile 'work'" in findings[0].message
    assert "srt fragment 'base'" in findings[0].message
    assert "'default'" in findings[0].message


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
    assert "profile 'both'" in findings[0].message
    assert "'default'" in findings[0].message
    assert "'work'" in findings[0].message


def test_registered_fragment_no_profile_selects_is_unused(tmp_path: Path) -> None:
    config = write_config(
        tmp_path,
        srt={"base": '{"enabled": true}', "old": "{}"},
        bash={"base": BASH_BASE},
        profiles='[profiles.default]\nsrt = ["base"]\nbash = ["base"]\n',
    )

    findings = run(config)

    assert codes(findings) == ["unused-fragment"]
    assert "srt fragment 'old'" in findings[0].message


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
    assert "'~/.kube/**'" in findings[0].message


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
    assert "'~/work/*', '~/repos/*/build/**'" in findings[0].message


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
    assert "'*.pypi.org' (pypi.org)" in findings[0].message
    assert "'*.npmjs.org' (npmjs.org)" in findings[0].message
    assert "github" not in findings[0].message


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
    assert findings[0].message.endswith(f"'{home}/.aws/sso' by '~/.aws'")


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
    assert findings[0].message.startswith("srt/base.jsonc: filesystem.denyRead: 3 ")
    assert "'**/.env', '**/*.pem', '**/id_rsa'" in findings[0].message
    assert findings[1].message.startswith("srt/work.jsonc: filesystem.denyRead: 1 ")


def test_subsumed_rules_are_grouped_per_fragment_and_list(tmp_path: Path) -> None:
    config = write_config(
        tmp_path,
        srt={
            "base": (
                '{"enabled": true, "network": {"allowedDomains": '
                '["*.npmjs.org", "registry.npmjs.org", "*.crates.io", '
                '"static.crates.io", "crates.io", "npmjs.org"]}}'
            )
        },
        bash={"base": BASH_BASE},
        profiles='[profiles.default]\nsrt = ["base"]\nbash = ["base"]\n',
    )

    findings = run(config)

    assert codes(findings) == ["subsumed-rule"]
    message = findings[0].message
    assert message.startswith("srt/base.jsonc: network.allowedDomains: 2 ")
    assert "'registry.npmjs.org' by '*.npmjs.org'" in message
    assert "'static.crates.io' by '*.crates.io'" in message


def test_read_deny_inside_a_write_root_without_write_deny_is_flagged(
    tmp_path: Path,
) -> None:
    # srt turns denyRead into a read deny plus an unlink deny only: inside an
    # allowWrite root the agent can still overwrite and create files there.
    config = write_config(
        tmp_path,
        srt={
            "base": (
                '{"enabled": true, "filesystem": {"allowWrite": [".", "~/xxx"], '
                '"denyRead": ["**/.twsrt", "~/xxx/secret", "~/.ssh"]}}'
            )
        },
        bash={"base": BASH_BASE},
        profiles='[profiles.default]\nsrt = ["base"]\nbash = ["base"]\n',
    )

    findings = run(config)

    flagged = [f for f in findings if f.code == "read-deny-writable"]
    assert len(flagged) == 1
    assert flagged[0].severity == "warning"
    message = flagged[0].message
    assert message.startswith("srt/base.jsonc: filesystem.denyRead: 2 ")
    assert "'**/.twsrt' (under '.')" in message
    assert "'~/xxx/secret' (under '~/xxx')" in message
    assert "~/.ssh" not in message


def test_read_deny_also_listed_in_deny_write_is_not_flagged(tmp_path: Path) -> None:
    config = write_config(
        tmp_path,
        srt={
            "base": (
                '{"enabled": true, "filesystem": {"allowWrite": ["~/xxx"], '
                '"denyRead": ["~/xxx/secret", "~/xxx/vault/keys"], '
                '"denyWrite": ["~/xxx/secret", "~/xxx/vault"]}}'
            )
        },
        bash={"base": BASH_BASE},
        profiles='[profiles.default]\nsrt = ["base"]\nbash = ["base"]\n',
    )

    assert "read-deny-writable" not in codes(run(config))


def test_read_deny_write_check_sees_rules_from_other_fragments_of_the_profile(
    tmp_path: Path,
) -> None:
    config = write_config(
        tmp_path,
        srt={
            "base": '{"enabled": true, "filesystem": {"denyRead": ["~/xxx/secret"]}}',
            "work": '{"filesystem": {"allowWrite": ["~/xxx"]}}',
        },
        bash={"base": BASH_BASE},
        profiles=(
            '[profiles.default]\nsrt = ["base"]\nbash = ["base"]\n\n'
            '[profiles.work]\nextends = ["default"]\nsrt = ["work"]\n'
        ),
    )

    flagged = [f for f in run(config) if f.code == "read-deny-writable"]

    # Only profile `work` grants the write root; the finding names the fragment
    # holding the read deny.
    assert len(flagged) == 1
    assert flagged[0].message.startswith("srt/base.jsonc: filesystem.denyRead: 1 ")
