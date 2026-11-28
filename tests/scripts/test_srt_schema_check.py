"""Tests for scripts/srt-schema-check.py, the srt schema drift check."""

import importlib.util
from pathlib import Path

import pytest

SCRIPT = Path(__file__).parents[2] / "scripts" / "srt-schema-check.py"
_spec = importlib.util.spec_from_file_location("srt_schema_check", SCRIPT)
assert _spec is not None and _spec.loader is not None
srt_schema_check = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(srt_schema_check)

TREE = """\
network: object  # Network restrictions configuration
  allowedDomains: string[]  # List of allowed domains (e.g., "a:443")
  mitmProxy: object, optional  # Optional MITM proxy configuration.
    socketPath: string  # Unix socket path to the MITM proxy
filesystem: object  # Filesystem restrictions configuration
  denyRead: string | object[]  # Paths denied for reading
credentials: object, optional  # Credential handling configuration.
  files: object[], optional  # Credential files or directories to protect
allowPty: boolean, optional  # Allow pseudo-terminal (pty) operations (macOS only)
"""


def test_reads_top_level_network_and_filesystem_keys_from_the_tree() -> None:
    keys = srt_schema_check.schema_keys(TREE)

    assert keys == {
        "": {"network", "filesystem", "credentials", "allowPty"},
        "network": {"allowedDomains", "mitmProxy"},
        "filesystem": {"denyRead"},
    }


def test_no_drift_when_twsrt_knows_exactly_the_schema_keys() -> None:
    schema = {"": {"network", "allowPty"}, "network": {"allowedDomains"}}
    known = {"": {"network", "allowPty"}, "network": {"allowedDomains"}}

    assert srt_schema_check.drift(schema, known, twsrt_only=set()) == []


def test_reports_a_new_srt_key_twsrt_does_not_know() -> None:
    schema = {"": {"network"}, "network": {"allowedDomains", "strictAllowlist"}}
    known = {"": {"network"}, "network": {"allowedDomains"}}

    assert srt_schema_check.drift(schema, known, twsrt_only=set()) == [
        "new in srt, add to _SRT_SCHEMA_KEYS: network.strictAllowlist"
    ]


def test_reports_a_key_srt_dropped_that_twsrt_still_lists() -> None:
    schema = {"": {"network", "filesystem"}}
    known = {"": {"network", "filesystem", "allowPty"}}

    assert srt_schema_check.drift(schema, known, twsrt_only=set()) == [
        "gone from srt, remove from _SRT_SCHEMA_KEYS: allowPty"
    ]


def test_a_deliberate_twsrt_only_key_is_not_drift() -> None:
    schema = {"": {"network"}}
    known = {"": {"network", "enabled"}}

    assert srt_schema_check.drift(schema, known, twsrt_only={("", "enabled")}) == []


def test_a_failing_schema_dump_reports_node_stderr_and_exits_2(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    # The dump fails when srt is not installed or its schema module moved; the
    # cause is only in node's stderr, so it must reach the user.
    failing_dump = tmp_path / "srt-schema.mjs"
    failing_dump.write_text(
        'process.stderr.write("Cannot find package sandbox-runtime\\n");'
        "process.exit(1);"
    )
    monkeypatch.setattr(srt_schema_check, "DUMP", failing_dump)

    assert srt_schema_check.main() == 2
    assert "Cannot find package sandbox-runtime" in capsys.readouterr().err


def test_a_missing_node_binary_is_reported_and_exits_2(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    monkeypatch.setenv("PATH", str(tmp_path))

    assert srt_schema_check.main() == 2
    assert "node not found" in capsys.readouterr().err


def test_the_installed_srt_matching_the_pin_is_no_mismatch() -> None:
    assert srt_schema_check.pin_mismatch(installed="1.2.3", pinned="1.2.3") is None


def test_an_installed_srt_other_than_the_pin_is_reported() -> None:
    # The key table claims the pinned version; checking it against another
    # installed version would bless or flag the wrong schema.
    assert srt_schema_check.pin_mismatch(installed="9.9.9", pinned="1.2.3") == (
        "installed srt 9.9.9 is not the pinned 1.2.3: run `make install-srt`, "
        "or pass SRT_VERSION=9.9.9 while upgrading"
    )


def test_a_pin_mismatch_exits_2_before_the_schema_is_dumped(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    monkeypatch.setattr(srt_schema_check, "installed_version", lambda: "9.9.9")
    # A dump that would fail proves main stops before running it.
    monkeypatch.setattr(srt_schema_check, "DUMP", tmp_path / "absent.mjs")

    assert srt_schema_check.main(["--pin", "1.2.3"]) == 2
    assert "installed srt 9.9.9 is not the pinned 1.2.3" in capsys.readouterr().err


def test_a_missing_srt_binary_under_pin_is_reported_and_exits_2(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    # `make srt-schema-check` always passes --pin; without srt on PATH the
    # version lookup must fail cleanly, not with a traceback.
    monkeypatch.setenv("PATH", str(tmp_path))

    assert srt_schema_check.main(["--pin", "1.2.3"]) == 2
    assert "srt not found on PATH" in capsys.readouterr().err
