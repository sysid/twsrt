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
        "~/.ssh",
        "~/.aws",
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

    fs = output["sandbox"]["filesystem"]
    assert fs["allowWrite"] == ["."]
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
