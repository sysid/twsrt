"""Tests for compiling resolved canonical-source profiles."""

import json
from pathlib import Path

import pytest

from twsrt.lib.config import load_config
from twsrt.lib.models import Action, Scope
from twsrt.lib.profiles import resolve_profile
from twsrt.lib.sources import compile_sources, serialize_document


def configured_profile(tmp_path: Path, srt_work: str, bash_work: str) -> Path:
    fragments = tmp_path / "fragments"
    fragments.mkdir()
    (fragments / "srt-base.jsonc").write_text(
        """{
  // Base sandbox policy
  "enabled": true,
  "filesystem": {"denyRead": ["~/.ssh"]},
  "network": {"allowedDomains": ["github.com"]}
}"""
    )
    (fragments / "srt-work.jsonc").write_text(srt_work)
    (fragments / "bash-base.jsonc").write_text(
        '{"allow": ["git status"], "ask": [], "deny": []}'
    )
    (fragments / "bash-work.jsonc").write_text(bash_work)
    config = tmp_path / "config.toml"
    config.write_text(
        """schema_version = 1
default_profile = "work"

[sources.srt]
output = "compiled/srt.json"
[sources.srt.fragments.base]
path = "fragments/srt-base.jsonc"
[sources.srt.fragments.work]
path = "fragments/srt-work.jsonc"

[sources.bash]
output = "compiled/bash.json"
[sources.bash.fragments.base]
path = "fragments/bash-base.jsonc"
[sources.bash.fragments.work]
path = "fragments/bash-work.jsonc"

[profiles.work]
srt = ["base", "work"]
bash = ["base", "work"]
"""
    )
    return config


def test_compile_sources_unions_documents_and_derives_rules(tmp_path: Path) -> None:
    config = load_config(
        configured_profile(
            tmp_path,
            '{"filesystem": {"denyRead": ["~/.aws"]}}',
            '{"allow": ["git status"], "ask": ["git push"]}',
        )
    )

    compiled = compile_sources(config, resolve_profile(config))

    assert compiled.documents["srt"].document["filesystem"]["denyRead"] == [
        "~/.aws",
        "~/.ssh",
    ]
    assert compiled.documents["bash"].document == {
        "allow": ["git status"],
        "ask": ["git push"],
        "deny": [],
    }
    assert any(
        rule.scope == Scope.EXECUTE
        and rule.action == Action.ASK
        and rule.pattern == "git push"
        for rule in compiled.rules
    )


def test_compile_sources_write_denies_config_and_every_sources_path(
    tmp_path: Path,
) -> None:
    """An agent able to edit the policy could loosen the next compile.

    Fragments the profile does not select are protected too: switching
    profiles must not activate a fragment an agent has already rewritten.
    """
    config_path = configured_profile(tmp_path, "{}", "{}")
    config_path.write_text(
        config_path.read_text().replace('srt = ["base", "work"]', 'srt = ["base"]')
    )
    config = load_config(config_path)

    compiled = compile_sources(config, resolve_profile(config))

    deny_write = compiled.documents["srt"].document["filesystem"]["denyWrite"]
    for path in (
        "config.toml",
        "compiled/srt.json",
        "fragments/srt-base.jsonc",
        "fragments/srt-work.jsonc",
        "compiled/bash.json",
        "fragments/bash-base.jsonc",
        "fragments/bash-work.jsonc",
    ):
        assert str(tmp_path / path) in deny_write


def test_compile_sources_sorts_schema_sets_but_keeps_pass_through_list_order(
    tmp_path: Path,
) -> None:
    """Known rule lists are sets; an unknown pass-through list may be argv."""
    config = load_config(
        configured_profile(
            tmp_path,
            """{
  "network": {"allowedDomains": ["anthropic.com"], "allowUnixSockets": ["/tmp/b", "/tmp/a"]},
  "ignoreViolations": {"*": ["/usr/bin", "/System"]},
  "ripgrep": {"command": "rg", "args": ["--hidden", "-g", "!.git"]}
}""",
            '{"allow": ["ls"], "deny": ["sudo", "rm"]}',
        )
    )

    compiled = compile_sources(config, resolve_profile(config))

    srt = compiled.documents["srt"].document
    assert srt["network"]["allowedDomains"] == ["anthropic.com", "github.com"]
    assert srt["network"]["allowUnixSockets"] == ["/tmp/a", "/tmp/b"]
    assert srt["ignoreViolations"] == {"*": ["/System", "/usr/bin"]}
    assert srt["ripgrep"]["args"] == ["--hidden", "-g", "!.git"]
    bash = compiled.documents["bash"].document
    assert bash["allow"] == ["git status", "ls"]
    assert bash["deny"] == ["rm", "sudo"]


def test_claude_output_covers_every_denied_path_via_rules(tmp_path: Path) -> None:
    """Coverage invariant behind the empty sandbox deny lists.

    Every canonical denyRead/denyWrite path must surface as Read/Edit deny
    rules in Claude output (they reach the OS sandbox via Claude's documented
    permission-rule merge), while sandbox.filesystem carries only allowWrite
    plus managed-empty deny lists.
    """
    from twsrt.lib.claude import ClaudeGenerator
    from twsrt.lib.models import AppConfig

    config = load_config(
        configured_profile(
            tmp_path,
            json.dumps(
                {
                    "filesystem": {
                        "denyRead": ["~/.aws"],
                        "denyWrite": ["**/.env", "/etc/ssl/certs"],
                        "allowWrite": ["."],
                    }
                }
            ),
            '{"allow": [], "ask": []}',
        )
    )
    compiled = compile_sources(config, resolve_profile(config))
    srt = compiled.srt_result
    app = AppConfig(
        network_config=srt.network_config,
        filesystem_config=srt.filesystem_config,
        sandbox_config=srt.sandbox_config,
    )
    output = json.loads(ClaudeGenerator().generate(compiled.rules, app))

    deny = output["permissions"]["deny"]
    # Read denies: bare + recursive, Read and Edit ("~/.ssh" from base, "~/.aws" added)
    for path in ("~/.ssh", "~/.aws"):
        assert f"Read({path})" in deny
        assert f"Edit({path})" in deny
    # Write denies, including the //-anchored absolute path
    assert "Edit(**/.env)" in deny
    assert "Edit(//etc/ssl/certs)" in deny

    # allowWrite travels as Edit allow rules (ADR 0002)
    assert "Edit(.)" in output["permissions"]["allow"]
    fs = output["sandbox"]["filesystem"]
    assert fs["allowWrite"] == []
    assert fs["denyRead"] == []
    assert fs["denyWrite"] == []


def test_compile_sources_rejects_srt_allow_deny_conflict_with_origins(
    tmp_path: Path,
) -> None:
    config = load_config(
        configured_profile(
            tmp_path,
            '{"network": {"deniedDomains": ["github.com"]}}',
            "{}",
        )
    )

    with pytest.raises(
        ValueError,
        match=r"github\.com.*allowedDomains.*srt-base\.jsonc.*deniedDomains.*srt-work\.jsonc",
    ):
        compile_sources(config, resolve_profile(config))


def test_compile_sources_rejects_bash_action_conflict_with_origins(
    tmp_path: Path,
) -> None:
    config = load_config(configured_profile(tmp_path, "{}", '{"deny": ["git status"]}'))

    with pytest.raises(
        ValueError,
        match=r"git status.*allow.*bash-base\.jsonc.*deny.*bash-work\.jsonc",
    ):
        compile_sources(config, resolve_profile(config))


def test_compile_sources_rejects_unknown_bash_key(tmp_path: Path) -> None:
    config = load_config(
        configured_profile(tmp_path, "{}", '{"unknown": ["git status"]}')
    )

    with pytest.raises(ValueError, match="unknown Bash rule key 'unknown'"):
        compile_sources(config, resolve_profile(config))


def test_serialize_document_is_strict_canonical_json() -> None:
    serialized = serialize_document({"enabled": True, "items": ["one"]})

    assert serialized == '{\n  "enabled": true,\n  "items": [\n    "one"\n  ]\n}\n'
    assert json.loads(serialized) == {"enabled": True, "items": ["one"]}


def test_compile_sources_adds_extra_deny_write_to_document_and_rules(
    tmp_path: Path,
) -> None:
    config = load_config(
        configured_profile(
            tmp_path,
            '{"filesystem": {"denyWrite": ["/z/existing"]}}',
            "{}",
        )
    )

    compiled = compile_sources(
        config, resolve_profile(config), extra_deny_write=["/a/repo/.twsrt"]
    )

    # ~/.ssh is the base fragment's denyRead, implied as a write deny too.
    policy = set(config.policy_files)
    deny_write = compiled.documents["srt"].document["filesystem"]["denyWrite"]
    assert [path for path in deny_write if path not in policy] == [
        "/a/repo/.twsrt",
        "/z/existing",
        "~/.ssh",
    ]
    assert any(
        rule.scope == Scope.WRITE
        and rule.action == Action.DENY
        and rule.pattern == "/a/repo/.twsrt"
        for rule in compiled.rules
    )


def test_compile_sources_extra_deny_write_creates_missing_filesystem_section(
    tmp_path: Path,
) -> None:
    config = load_config(
        configured_profile(tmp_path, '{"network": {"allowedDomains": []}}', "{}")
    )
    (tmp_path / "fragments/srt-base.jsonc").write_text(
        '{"enabled": true, "network": {"allowedDomains": ["x.io"]}}'
    )

    compiled = compile_sources(
        config, resolve_profile(config), extra_deny_write=["/a/repo/.twsrt"]
    )

    assert compiled.documents["srt"].document["filesystem"] == {
        "denyWrite": sorted(["/a/repo/.twsrt", *config.policy_files])
    }


def test_every_read_deny_is_also_compiled_as_a_write_deny(tmp_path: Path) -> None:
    # srt compiles denyRead to a read deny only; inside an allowWrite root the
    # file would stay overwritable. A secret must not be writable either.
    config = load_config(
        configured_profile(
            tmp_path,
            '{"filesystem": {"denyRead": ["**/.env", "~/.aws"], '
            '"denyWrite": ["/z/existing"]}}',
            "{}",
        )
    )

    compiled = compile_sources(config, resolve_profile(config))

    policy = set(config.policy_files)
    deny_write = compiled.documents["srt"].document["filesystem"]["denyWrite"]
    assert [path for path in deny_write if path not in policy] == [
        "**/.env",
        "/z/existing",
        "~/.aws",
        "~/.ssh",
    ]
    write_denies = {
        rule.pattern
        for rule in compiled.rules
        if rule.scope == Scope.WRITE and rule.action == Action.DENY
    }
    assert {"**/.env", "~/.aws", "~/.ssh"} <= write_denies


def test_without_a_bash_source_only_srt_compiles_and_no_command_rules_exist(
    tmp_path: Path,
) -> None:
    (tmp_path / "srt-base.jsonc").write_text(
        '{"enabled": true, "filesystem": {"denyRead": ["~/.ssh"]}}'
    )
    config_path = tmp_path / "config.toml"
    config_path.write_text(
        """schema_version = 1
default_profile = "default"

[sources.srt]
[sources.srt.fragments.base]
path = "srt-base.jsonc"

[profiles.default]
srt = ["base"]
"""
    )
    config = load_config(config_path)

    compiled = compile_sources(config, resolve_profile(config))

    assert set(compiled.documents) == {"srt"}
    assert not [rule for rule in compiled.rules if rule.scope == Scope.EXECUTE]
    assert any(rule.pattern == "~/.ssh" for rule in compiled.rules)


def test_read_deny_on_a_write_allowed_path_is_a_conflict(tmp_path: Path) -> None:
    # Write-only (denyRead + allowWrite of the same path) contradicts the
    # implied write deny; it must be a loud error, never a silent hole.
    config = load_config(
        configured_profile(
            tmp_path,
            '{"filesystem": {"denyRead": ["~/logs"], "allowWrite": ["~/logs"]}}',
            "{}",
        )
    )

    with pytest.raises(ValueError, match=r"~/logs.*denyRead.*allowWrite"):
        compile_sources(config, resolve_profile(config))
