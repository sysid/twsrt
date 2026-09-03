"""Tests for `twsrt test`: probing the effective SRT sandbox."""

from __future__ import annotations

import json
import subprocess
from pathlib import Path
from unittest.mock import patch

import pytest
from typer.testing import CliRunner

from twsrt.bin.cli import app

runner = CliRunner()

RUN = "twsrt.lib.probe.subprocess.run"


@pytest.fixture(autouse=True)
def no_installed_srt():
    """Version lookup must not depend on an srt installed on the test host."""
    with patch("twsrt.lib.probe.shutil.which", return_value=None):
        yield


class FakeRunner:
    """Stands in for subprocess.run. Sandboxed commands that mention a blocked
    substring fail with EPERM text; everything else exits 0."""

    def __init__(
        self, blocked: tuple[str, ...] = (), srt_failure: tuple[int, str] | None = None
    ) -> None:
        self.blocked = blocked
        self.srt_failure = srt_failure
        self.calls: list[list[str]] = []

    def __call__(self, argv: list[str], **kwargs) -> subprocess.CompletedProcess:
        self.calls.append(list(argv))
        if argv[0] != "srt":
            return subprocess.CompletedProcess(argv, 0, stdout="", stderr="")
        if argv[1] == "--version":
            return subprocess.CompletedProcess(argv, 0, stdout="0.0.75\n", stderr="")
        if self.srt_failure is not None:
            code, stderr = self.srt_failure
            return subprocess.CompletedProcess(argv, code, stdout="", stderr=stderr)
        command = argv[argv.index("-c") + 1]
        if any(marker in command for marker in self.blocked):
            return subprocess.CompletedProcess(
                argv, 1, stdout="", stderr="head: Operation not permitted\n"
            )
        return subprocess.CompletedProcess(argv, 0, stdout="", stderr="")


def _make_config(tmp_path: Path, srt: dict, write_settings: bool = True) -> Path:
    """Write fragment, config.toml and (optionally) the compiled settings file."""
    srt_file = tmp_path / "srt.jsonc"
    srt_file.write_text(json.dumps(srt))
    twsrt_dir = tmp_path / "config" / "twsrt"
    twsrt_dir.mkdir(parents=True)
    bash_file = twsrt_dir / "bash-rules.jsonc"
    bash_file.write_text(json.dumps({"deny": [], "ask": []}))
    settings = tmp_path / ".srt-settings.json"
    if write_settings:
        settings.write_text(json.dumps(srt, indent=2) + "\n")
    config = twsrt_dir / "config.toml"
    config.write_text(
        "schema_version = 1\n"
        'default_profile = "default"\n'
        "[sources.srt]\n"
        f'output = "{settings}"\n'
        "[sources.srt.fragments.base]\n"
        f'path = "{srt_file}"\n'
        "[sources.bash]\n"
        f'output = "{twsrt_dir / "bash-rules.json"}"\n'
        "[sources.bash.fragments.base]\n"
        f'path = "{bash_file}"\n'
        "[profiles.default]\n"
        'srt = ["base"]\n'
        'bash = ["base"]\n'
    )
    return config


def _secret_config(tmp_path: Path, **kwargs) -> tuple[Path, Path]:
    secret = tmp_path / "secret.txt"
    secret.write_text("hunter2\n")
    srt = {
        "enabled": True,
        "filesystem": {"denyRead": [str(secret)], "allowWrite": [], "denyWrite": []},
        "network": {"allowedDomains": [], "deniedDomains": []},
    }
    return _make_config(tmp_path, srt, **kwargs), secret


class TestExitCodes:
    def test_all_pass_exits_zero(self, tmp_path: Path) -> None:
        config, secret = _secret_config(tmp_path)
        fake = FakeRunner(blocked=(str(secret), "example.com"))

        with patch(RUN, fake):
            result = runner.invoke(app, ["-c", str(config), "test"])

        assert result.exit_code == 0, result.output
        assert "PASS" in result.stdout
        assert "FAIL" not in result.stdout

    def test_unblocked_probe_exits_one_and_reports_failure(
        self, tmp_path: Path
    ) -> None:
        config, secret = _secret_config(tmp_path)
        fake = FakeRunner(blocked=("example.com",))

        with patch(RUN, fake):
            result = runner.invoke(app, ["-c", str(config), "test"])

        assert result.exit_code == 1
        assert "FAIL" in result.stdout
        assert str(secret) in result.stdout
        assert "not blocked" in result.stdout

    def test_missing_settings_exits_two(self, tmp_path: Path) -> None:
        config, _ = _secret_config(tmp_path, write_settings=False)

        with patch(RUN, FakeRunner()) as fake:
            result = runner.invoke(app, ["-c", str(config), "test"])

        assert result.exit_code == 2
        assert "Error:" in result.stderr
        assert ".srt-settings.json" in result.stderr
        assert fake.calls == []

    def test_preflight_failure_exits_two_with_nested_sandbox_hint(
        self, tmp_path: Path
    ) -> None:
        config, _ = _secret_config(tmp_path)
        fake = FakeRunner(
            srt_failure=(71, "sandbox-exec: sandbox_apply: Operation not permitted\n")
        )

        with patch(RUN, fake):
            result = runner.invoke(app, ["-c", str(config), "test"])

        assert result.exit_code == 2
        assert "inside another sandbox" in result.stderr
        assert "PASS" not in result.stdout

    def test_invalid_config_exits_two(self, tmp_path: Path) -> None:
        result = runner.invoke(app, ["-c", str(tmp_path / "missing.toml"), "test"])

        assert result.exit_code == 2
        assert "Error:" in result.stderr


class TestHumanOutput:
    def test_table_has_header_rows_and_summary(self, tmp_path: Path) -> None:
        config, secret = _secret_config(tmp_path)
        fake = FakeRunner(blocked=(str(secret), "example.com"))

        with patch(RUN, fake):
            result = runner.invoke(app, ["-c", str(config), "test"])

        assert result.exit_code == 0, result.output
        lines = result.stdout.splitlines()
        assert any(line.startswith("STATUS") and "PROBE" in line for line in lines)
        assert any("read-deny" in line and "PASS" in line for line in lines)
        assert any("net-deny" in line and "PASS" in line for line in lines)
        assert "passed=2 failed=0 invalid=0 error=0 skipped=0" in result.stdout
        assert "srt 0.0.75" in result.stdout

    def test_skipped_rules_show_the_reason(self, tmp_path: Path) -> None:
        config, _ = (
            _make_config(
                tmp_path,
                {
                    "filesystem": {"denyRead": ["**/.env"]},
                    "network": {"allowedDomains": [], "deniedDomains": []},
                },
            ),
            None,
        )
        fake = FakeRunner(blocked=("example.com",))

        with patch(RUN, fake):
            result = runner.invoke(app, ["-c", str(config), "test"])

        assert result.exit_code == 0, result.output
        assert "SKIP" in result.stdout
        assert "glob" in result.stdout
        assert "skipped=1" in result.stdout

    def test_failure_detail_includes_sandbox_stderr(self, tmp_path: Path) -> None:
        config, _ = _secret_config(tmp_path)
        fake = FakeRunner(blocked=("example.com",))

        with patch(RUN, fake):
            result = runner.invoke(app, ["-c", str(config), "test"])

        assert result.exit_code == 1
        assert "read-deny" in result.stdout
        assert "not blocked" in result.stdout

    def test_statuses_are_colored_on_a_terminal(self, tmp_path: Path) -> None:
        config, secret = _secret_config(tmp_path)
        fake = FakeRunner(blocked=(str(secret),))

        with patch(RUN, fake):
            result = runner.invoke(
                app,
                ["-c", str(config), "test"],
                env={"NO_COLOR": None},
                color=True,
            )

        assert result.exit_code == 1
        assert "\x1b[32m" in result.stdout  # PASS
        assert "\x1b[31m" in result.stdout  # FAIL

    def test_keyword_filters_probes(self, tmp_path: Path) -> None:
        config, secret = _secret_config(tmp_path)
        fake = FakeRunner(blocked=(str(secret), "example.com"))

        with patch(RUN, fake):
            result = runner.invoke(app, ["-c", str(config), "test", "-k", "net-"])

        assert result.exit_code == 0, result.output
        assert "read-deny" not in result.stdout
        assert "net-deny" in result.stdout
        assert all("secret.txt" not in argv[-1] for argv in fake.calls[2:])

    def test_verbose_logs_each_command(self, tmp_path: Path) -> None:
        config, secret = _secret_config(tmp_path)
        fake = FakeRunner(blocked=(str(secret), "example.com"))

        with patch(RUN, fake):
            result = runner.invoke(app, ["-v", "-c", str(config), "test"])

        assert result.exit_code == 0, result.output
        assert "Debug:" in result.stderr
        assert "head -c 1" in result.stderr


class TestJsonOutput:
    def test_json_document_replaces_the_table(self, tmp_path: Path) -> None:
        config, secret = _secret_config(tmp_path)
        fake = FakeRunner(blocked=("example.com",))

        with patch(RUN, fake):
            result = runner.invoke(app, ["-c", str(config), "test", "--json"])

        assert result.exit_code == 1
        document = json.loads(result.stdout)
        assert document["srt_version"] == "0.0.75"
        assert document["settings"] == str(tmp_path / ".srt-settings.json")
        assert document["summary"] == {
            "total": 2,
            "passed": 1,
            "failed": 1,
            "invalid": 0,
            "error": 0,
            "skipped": 0,
        }
        failed = [r for r in document["results"] if r["status"] == "FAIL"]
        assert len(failed) == 1
        assert failed[0]["kind"] == "read-deny"
        assert failed[0]["rule"] == str(secret)
        assert failed[0]["expect"] == "deny"
        assert failed[0]["control_exit"] == 0
        assert failed[0]["sandbox_exit"] == 0
        assert "not blocked" in failed[0]["reason"]
        assert isinstance(failed[0]["duration_ms"], int)
        assert "STATUS" not in result.stdout

    def test_json_keeps_warnings_on_stderr(self, tmp_path: Path) -> None:
        config, secret = _secret_config(tmp_path)
        (tmp_path / "srt.jsonc").write_text(
            json.dumps(
                {
                    "enabled": True,
                    "filesystem": {"denyRead": [str(secret), "~/.ssh"]},
                    "network": {"allowedDomains": [], "deniedDomains": []},
                }
            )
        )
        fake = FakeRunner(blocked=(str(secret), "example.com"))

        with patch(RUN, fake):
            result = runner.invoke(app, ["-c", str(config), "test", "--json"])

        assert result.exit_code == 0, result.output
        json.loads(result.stdout)
        assert "drift" in result.stderr


class TestDriftWarning:
    def test_fragment_change_since_last_write_is_warned(self, tmp_path: Path) -> None:
        config, secret = _secret_config(tmp_path)
        (tmp_path / "srt.jsonc").write_text(
            json.dumps(
                {
                    "enabled": True,
                    "filesystem": {"denyRead": [str(secret), "~/.ssh"]},
                    "network": {"allowedDomains": [], "deniedDomains": []},
                }
            )
        )
        fake = FakeRunner(blocked=(str(secret), "example.com"))

        with patch(RUN, fake):
            result = runner.invoke(app, ["-c", str(config), "test"])

        assert result.exit_code == 0, result.output
        assert "Warning:" in result.stderr
        assert "drift" in result.stderr
        assert "generate -w" in result.stderr

    def test_no_warning_when_settings_match_fragments(self, tmp_path: Path) -> None:
        config, secret = _secret_config(tmp_path)
        fake = FakeRunner(blocked=(str(secret), "example.com"))

        with patch(RUN, fake):
            result = runner.invoke(app, ["-c", str(config), "test"])

        assert result.exit_code == 0, result.output
        assert "Warning:" not in result.stderr


class TestTableWidths:
    def test_rule_column_is_capped_so_one_long_path_does_not_widen_all_rows(
        self,
    ) -> None:
        from twsrt.bin.cli import _probe_widths
        from twsrt.lib.probe import Expect, Probe

        probes = [
            Probe("read-deny", "~/.ssh", "", Expect.DENY),
            Probe("read-deny", "/very/long/" + "x" * 200, "", Expect.DENY),
        ]

        kind_width, rule_width = _probe_widths(probes)

        assert kind_width == len("read-deny")
        assert rule_width == 48


class TestScratchDirectory:
    def test_scratch_dir_is_removed_after_the_run(self, tmp_path: Path) -> None:
        cwd = tmp_path / "project"
        cwd.mkdir()
        config, _ = (
            _make_config(
                tmp_path,
                {
                    "filesystem": {"allowWrite": ["."], "denyWrite": ["**/*.pem"]},
                    "network": {"allowedDomains": [], "deniedDomains": []},
                },
            ),
            None,
        )
        fake = FakeRunner(blocked=(".pem", "example.com"))

        with patch(RUN, fake), patch("twsrt.bin.cli.Path.cwd", return_value=cwd):
            result = runner.invoke(app, ["-c", str(config), "test"])

        assert result.exit_code == 0, result.output
        assert "write-deny" in result.stdout
        assert "write-allow" in result.stdout
        assert [p for p in cwd.iterdir()] == []
