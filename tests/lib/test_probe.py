"""Tests for sandbox probe derivation, execution, and verdicts."""

from __future__ import annotations

import json
import logging
import os
import subprocess
from collections.abc import Iterator
from pathlib import Path

import pytest

from twsrt.lib.models import SrtResult
from twsrt.lib.probe import (
    Expect,
    Probe,
    ProbeError,
    Status,
    derive_probes,
    judge,
    preflight,
    run_probe,
    scratch_root,
)
from twsrt.lib.sources import parse_srt_document

SETTINGS = Path("/settings/.srt-settings.json")


def _srt(filesystem: dict | None = None, network: dict | None = None) -> SrtResult:
    return parse_srt_document(
        {"filesystem": filesystem or {}, "network": network or {}}
    )


def _by_kind(probes: list[Probe], kind: str) -> list[Probe]:
    return [probe for probe in probes if probe.kind == kind]


class FakeRunner:
    """subprocess.run stand-in: sandboxed commands mentioning a blocked
    substring fail with EPERM text; everything else succeeds."""

    def __init__(
        self,
        blocked: tuple[str, ...] = (),
        control_failures: tuple[str, ...] = (),
        control_denied: tuple[str, ...] = (),
        srt_failure: tuple[int, str] | None = None,
        raise_for_srt: Exception | None = None,
    ) -> None:
        self.blocked = blocked
        self.control_failures = control_failures
        self.control_denied = control_denied
        self.srt_failure = srt_failure
        self.raise_for_srt = raise_for_srt
        self.calls: list[tuple[list[str], dict]] = []

    def __call__(self, argv: list[str], **kwargs) -> subprocess.CompletedProcess:
        self.calls.append((list(argv), kwargs))
        if argv[0] == "srt":
            if self.raise_for_srt is not None:
                raise self.raise_for_srt
            if argv[1] == "--version":
                return subprocess.CompletedProcess(
                    argv, 0, stdout="0.0.75\n", stderr=""
                )
            if self.srt_failure is not None:
                code, stderr = self.srt_failure
                return subprocess.CompletedProcess(argv, code, stdout="", stderr=stderr)
            command = argv[argv.index("-c") + 1]
            if any(marker in command for marker in self.blocked):
                return subprocess.CompletedProcess(
                    argv, 1, stdout="", stderr="head: x: Operation not permitted\n"
                )
            return subprocess.CompletedProcess(argv, 0, stdout="", stderr="")
        command = argv[2]
        if any(marker in command for marker in self.control_denied):
            return subprocess.CompletedProcess(
                argv, 1, stdout="", stderr="sh: line 1: x: Operation not permitted\n"
            )
        if any(marker in command for marker in self.control_failures):
            return subprocess.CompletedProcess(
                argv, 1, stdout="", stderr="head: x: No such file or directory\n"
            )
        return subprocess.CompletedProcess(argv, 0, stdout="", stderr="")


class TestJudge:
    @pytest.mark.parametrize(
        ("expect", "control", "denied", "sandbox", "status", "reason_part"),
        [
            # control failed for another reason (missing file, host down)
            (Expect.DENY, 1, False, 1, Status.INVALID, "without sandbox"),
            (Expect.DENY, 1, False, 0, Status.INVALID, "without sandbox"),
            # control was refused by the OS itself: the deny intent is met
            (Expect.DENY, 1, True, 1, Status.PASS, "outside the sandbox"),
            (Expect.DENY, 1, True, 0, Status.FAIL, "not blocked"),
            (Expect.DENY, 0, False, 0, Status.FAIL, "not blocked"),
            (Expect.DENY, 0, False, 1, Status.PASS, ""),
            # an allow rule cannot be verified when the OS refuses anyway
            (Expect.ALLOW, 1, True, 1, Status.INVALID, "without sandbox"),
            (Expect.ALLOW, 1, False, 0, Status.INVALID, "without sandbox"),
            (Expect.ALLOW, 0, False, 1, Status.FAIL, "should be allowed"),
            (Expect.ALLOW, 0, False, 0, Status.PASS, ""),
        ],
    )
    def test_truth_table(
        self,
        expect: Expect,
        control: int,
        denied: bool,
        sandbox: int,
        status: Status,
        reason_part: str,
    ) -> None:
        verdict, reason = judge(expect, control, sandbox, control_denied=denied)

        assert verdict is status
        assert reason_part in reason
        if reason_part == "":
            assert reason == ""

    def test_os_denial_is_a_pass_that_says_so(self) -> None:
        verdict, reason = judge(Expect.DENY, 1, 1, control_denied=True)

        assert verdict is Status.PASS
        assert "OS" in reason or "permission" in reason


class TestDeriveReadDeny:
    def test_file_rule_probes_the_file_with_head(self, tmp_path: Path) -> None:
        secret = tmp_path / ".netrc"
        secret.write_text("machine x login y\n")

        probes = derive_probes(
            _srt({"denyRead": ["~/.netrc"]}), tmp_path, tmp_path, tmp_path / "s"
        )

        [probe] = _by_kind(probes, "read-deny")
        assert probe.rule == "~/.netrc"
        assert probe.command == f"head -c 1 -- {secret}"
        assert probe.expect is Expect.DENY
        assert probe.skip_reason is None

    def test_directory_rule_probes_first_regular_file_inside(
        self, tmp_path: Path
    ) -> None:
        ssh = tmp_path / ".ssh"
        (ssh / "nested").mkdir(parents=True)
        (ssh / "nested" / "id_ed25519").write_text("key")
        (ssh / "config").write_text("Host x")

        probes = derive_probes(
            _srt({"denyRead": ["~/.ssh"]}), tmp_path, tmp_path, tmp_path / "s"
        )

        [probe] = _by_kind(probes, "read-deny")
        assert probe.command == f"head -c 1 -- {ssh / 'config'}"

    def test_empty_directory_falls_back_to_listing(self, tmp_path: Path) -> None:
        (tmp_path / ".gnupg").mkdir()

        probes = derive_probes(
            _srt({"denyRead": ["~/.gnupg"]}), tmp_path, tmp_path, tmp_path / "s"
        )

        [probe] = _by_kind(probes, "read-deny")
        assert probe.command == f"ls -- {tmp_path / '.gnupg'}"

    def test_symlinked_directory_adds_realpath_probe(self, tmp_path: Path) -> None:
        real = tmp_path / "configs" / "dot-aws"
        (real / "sso").mkdir(parents=True)
        (real / "sso" / "cache.json").write_text("{}")
        os.symlink(real, tmp_path / ".aws")

        probes = derive_probes(
            _srt({"denyRead": ["~/.aws"]}), tmp_path, tmp_path, tmp_path / "s"
        )

        via_link, via_real = _by_kind(probes, "read-deny")
        assert via_link.rule == "~/.aws"
        assert (
            via_link.command
            == f"head -c 1 -- {tmp_path / '.aws' / 'sso' / 'cache.json'}"
        )
        assert via_real.rule == "~/.aws (realpath)"
        assert via_real.command == (
            f"head -c 1 -- {Path(os.path.realpath(real)) / 'sso' / 'cache.json'}"
        )
        assert via_real.expect is Expect.DENY

    def test_plain_path_has_no_realpath_probe(self, tmp_path: Path) -> None:
        (tmp_path / ".netrc").write_text("x")

        probes = derive_probes(
            _srt({"denyRead": ["~/.netrc"]}), tmp_path, tmp_path, tmp_path / "s"
        )

        assert len(_by_kind(probes, "read-deny")) == 1

    def test_glob_rule_is_skipped_with_reason(self, tmp_path: Path) -> None:
        probes = derive_probes(
            _srt({"denyRead": ["**/.env"]}), tmp_path, tmp_path, tmp_path / "s"
        )

        [probe] = _by_kind(probes, "read-deny")
        assert probe.skip_reason is not None
        assert "glob" in probe.skip_reason

    def test_absent_path_is_skipped_with_reason(self, tmp_path: Path) -> None:
        probes = derive_probes(
            _srt({"denyRead": ["~/.kube"]}), tmp_path, tmp_path, tmp_path / "s"
        )

        [probe] = _by_kind(probes, "read-deny")
        assert probe.skip_reason is not None
        assert "not present" in probe.skip_reason

    def test_absolute_path_is_used_verbatim(self, tmp_path: Path) -> None:
        secret = tmp_path / "secret.txt"
        secret.write_text("x")

        probes = derive_probes(
            _srt({"denyRead": [str(secret)]}), tmp_path, tmp_path, tmp_path / "s"
        )

        [probe] = _by_kind(probes, "read-deny")
        assert probe.command == f"head -c 1 -- {secret}"

    def test_paths_with_spaces_are_shell_quoted(self, tmp_path: Path) -> None:
        secret = tmp_path / "my secret.txt"
        secret.write_text("x")

        probes = derive_probes(
            _srt({"denyRead": [str(secret)]}), tmp_path, tmp_path, tmp_path / "s"
        )

        [probe] = _by_kind(probes, "read-deny")
        assert probe.command == f"head -c 1 -- '{secret}'"


class TestDeriveWriteDeny:
    @pytest.mark.parametrize(
        ("pattern", "relative"),
        [
            ("**/.env", ".env"),
            ("**/*.pem", "probe.pem"),
            ("**/serviceAccount*.json", "serviceAccountprobe.json"),
            ("**/id_rsa", "id_rsa"),
            ("**/secrets/**", "secrets/probe"),
            ("**/.github/workflows/**", ".github/workflows/probe"),
            ("**/*.??", "probe.xx"),
        ],
    )
    def test_glob_becomes_a_file_inside_the_scratch_dir(
        self, tmp_path: Path, pattern: str, relative: str
    ) -> None:
        scratch = tmp_path / "scratch"
        scratch.mkdir()

        probes = derive_probes(
            _srt({"denyWrite": [pattern]}), tmp_path, tmp_path, scratch
        )

        [probe] = _by_kind(probes, "write-deny")
        target = scratch / relative
        assert probe.rule == pattern
        assert probe.command == f": >> {target}"
        assert probe.artifact == target
        assert probe.expect is Expect.DENY
        assert target.parent.is_dir(), "parent directories are pre-created on host"
        assert not target.exists()

    @pytest.mark.parametrize(
        "pattern",
        ["/etc/*.conf", "~/keys/*.pem", "**/*/secret", "**/[ab].txt"],
    )
    def test_unconvertible_glob_is_skipped(self, tmp_path: Path, pattern: str) -> None:
        scratch = tmp_path / "scratch"
        scratch.mkdir()

        probes = derive_probes(
            _srt({"denyWrite": [pattern]}), tmp_path, tmp_path, scratch
        )

        [probe] = _by_kind(probes, "write-deny")
        assert probe.skip_reason is not None
        assert probe.artifact is None


class TestDeriveWriteAllow:
    def test_dot_probes_the_working_directory(self, tmp_path: Path) -> None:
        cwd = tmp_path / "project"
        cwd.mkdir()

        probes = derive_probes(
            _srt({"allowWrite": ["."]}), cwd, tmp_path, tmp_path / "s"
        )

        [probe] = _by_kind(probes, "write-allow")
        assert probe.rule == "."
        assert probe.expect is Expect.ALLOW
        assert probe.artifact is not None
        assert probe.artifact.parent == cwd
        assert probe.command == f": >> {probe.artifact}"

    def test_home_relative_directory(self, tmp_path: Path) -> None:
        (tmp_path / "xxx").mkdir()

        probes = derive_probes(
            _srt({"allowWrite": ["~/xxx"]}), tmp_path, tmp_path, tmp_path / "s"
        )

        [probe] = _by_kind(probes, "write-allow")
        assert probe.artifact is not None
        assert probe.artifact.parent == tmp_path / "xxx"

    def test_absent_directory_and_glob_are_skipped(self, tmp_path: Path) -> None:
        probes = derive_probes(
            _srt({"allowWrite": ["~/missing", "~/*/build"]}),
            tmp_path,
            tmp_path,
            tmp_path / "s",
        )

        absent, glob = _by_kind(probes, "write-allow")
        assert absent.skip_reason is not None and "not present" in absent.skip_reason
        assert glob.skip_reason is not None and "glob" in glob.skip_reason

    def test_file_entry_opens_for_append_without_touching_it(
        self, tmp_path: Path
    ) -> None:
        target = tmp_path / ".claude.json"
        target.write_text("{}")

        probes = derive_probes(
            _srt({"allowWrite": ["~/.claude.json"]}), tmp_path, tmp_path, tmp_path / "s"
        )

        [probe] = _by_kind(probes, "write-allow")
        assert probe.command == f": >> {target}"
        assert probe.expect is Expect.ALLOW
        assert probe.artifact is None, "an existing file is never deleted"
        assert probe.skip_reason is None

    def test_append_open_probe_leaves_the_file_byte_for_byte_and_mtime_intact(
        self, tmp_path: Path
    ) -> None:
        target = tmp_path / "notes.txt"
        target.write_text("original\n")
        before = target.stat()
        [probe] = _by_kind(
            derive_probes(
                _srt({"allowWrite": [str(target)]}), tmp_path, tmp_path, tmp_path / "s"
            ),
            "write-allow",
        )

        completed = subprocess.run(["sh", "-c", probe.command])

        assert completed.returncode == 0
        assert target.read_text() == "original\n"
        assert target.stat().st_mtime_ns == before.st_mtime_ns
        assert target.stat().st_size == before.st_size


class TestDeriveWriteDenyConcretePaths:
    def test_existing_file_opens_for_append_and_expects_denial(
        self, tmp_path: Path
    ) -> None:
        target = tmp_path / "prod.env"
        target.write_text("SECRET=1\n")

        probes = derive_probes(
            _srt({"denyWrite": ["~/prod.env"]}), tmp_path, tmp_path, tmp_path / "s"
        )

        [probe] = _by_kind(probes, "write-deny")
        assert probe.command == f": >> {target}"
        assert probe.expect is Expect.DENY
        assert probe.artifact is None
        assert probe.skip_reason is None

    def test_existing_directory_probes_a_new_file_inside(self, tmp_path: Path) -> None:
        (tmp_path / "vault").mkdir()

        probes = derive_probes(
            _srt({"denyWrite": ["~/vault"]}), tmp_path, tmp_path, tmp_path / "s"
        )

        [probe] = _by_kind(probes, "write-deny")
        assert probe.artifact is not None
        assert probe.artifact.parent == tmp_path / "vault"
        assert probe.command == f": >> {probe.artifact}"
        assert probe.expect is Expect.DENY

    def test_absent_concrete_path_is_skipped(self, tmp_path: Path) -> None:
        probes = derive_probes(
            _srt({"denyWrite": ["~/missing.env"]}), tmp_path, tmp_path, tmp_path / "s"
        )

        [probe] = _by_kind(probes, "write-deny")
        assert probe.skip_reason is not None
        assert "not present" in probe.skip_reason


class TestDeriveNetwork:
    def test_concrete_allowed_domain_expects_success(self, tmp_path: Path) -> None:
        probes = derive_probes(
            _srt(network={"allowedDomains": ["github.com"]}),
            tmp_path,
            tmp_path,
            tmp_path / "s",
        )

        [probe] = _by_kind(probes, "net-allow")
        assert probe.rule == "github.com"
        assert probe.command == "curl -sS -m 10 -o /dev/null -I https://github.com/"
        assert probe.expect is Expect.ALLOW

    def test_wildcard_domain_is_skipped(self, tmp_path: Path) -> None:
        probes = derive_probes(
            _srt(network={"allowedDomains": ["*.github.com"]}),
            tmp_path,
            tmp_path,
            tmp_path / "s",
        )

        [probe] = _by_kind(probes, "net-allow")
        assert probe.skip_reason is not None
        assert "wildcard" in probe.skip_reason

    def test_denied_domain_expects_failure(self, tmp_path: Path) -> None:
        probes = derive_probes(
            _srt(network={"deniedDomains": ["evil.com"]}),
            tmp_path,
            tmp_path,
            tmp_path / "s",
        )

        denied = [p for p in _by_kind(probes, "net-deny") if p.rule == "evil.com"]
        assert len(denied) == 1
        assert denied[0].expect is Expect.DENY
        assert denied[0].command == "curl -sS -m 10 -o /dev/null -I https://evil.com/"

    def test_allowlist_canary_uses_a_domain_outside_the_allowlist(
        self, tmp_path: Path
    ) -> None:
        probes = derive_probes(
            _srt(network={"allowedDomains": ["example.com"]}),
            tmp_path,
            tmp_path,
            tmp_path / "s",
        )

        [canary] = _by_kind(probes, "net-deny")
        assert canary.rule == "example.org (not allowlisted)"
        assert canary.expect is Expect.DENY
        assert "https://example.org/" in canary.command

    def test_canary_is_always_present_even_without_network_rules(
        self, tmp_path: Path
    ) -> None:
        probes = derive_probes(_srt(), tmp_path, tmp_path, tmp_path / "s")

        [canary] = _by_kind(probes, "net-deny")
        assert canary.rule == "example.com (not allowlisted)"


class TestScratchRoot:
    def test_first_existing_allow_write_directory_wins(self, tmp_path: Path) -> None:
        (tmp_path / "xxx").mkdir()

        root = scratch_root(
            _srt({"allowWrite": ["~/missing", "~/*/glob", "~/xxx", "."]}),
            tmp_path / "cwd",
            tmp_path,
        )

        assert root == tmp_path / "xxx"

    def test_falls_back_to_cwd(self, tmp_path: Path) -> None:
        root = scratch_root(_srt(), tmp_path / "cwd", tmp_path)

        assert root == tmp_path / "cwd"


class TestDeriveOrdering:
    def test_kinds_are_grouped_in_stable_order(self, tmp_path: Path) -> None:
        (tmp_path / ".netrc").write_text("x")
        scratch = tmp_path / "scratch"
        scratch.mkdir()

        probes = derive_probes(
            _srt(
                {
                    "denyRead": ["~/.netrc"],
                    "denyWrite": ["**/.env"],
                    "allowWrite": ["."],
                },
                {"allowedDomains": ["github.com"], "deniedDomains": ["evil.com"]},
            ),
            tmp_path,
            tmp_path,
            scratch,
        )

        assert [p.kind for p in probes] == [
            "read-deny",
            "write-deny",
            "write-allow",
            "net-allow",
            "net-deny",
            "net-deny",
        ]


class TestRunProbe:
    def _probe(self, command: str = "head -c 1 -- /x", **kwargs) -> Probe:
        return Probe(
            kind="read-deny", rule="/x", command=command, expect=Expect.DENY, **kwargs
        )

    def test_control_runs_under_sh_and_sandbox_under_srt_with_settings(self) -> None:
        runner = FakeRunner(blocked=("/x",))

        result = run_probe(self._probe(), SETTINGS, timeout=5, run=runner)

        control, sandbox = runner.calls
        assert control[0] == ["sh", "-c", "head -c 1 -- /x"]
        assert sandbox[0] == ["srt", "-s", str(SETTINGS), "-c", "head -c 1 -- /x"]
        assert result.status is Status.PASS
        assert result.control_exit == 0
        assert result.sandbox_exit == 1

    def test_stdout_is_never_captured(self) -> None:
        runner = FakeRunner(blocked=("/x",))

        run_probe(self._probe(), SETTINGS, timeout=5, run=runner)

        for _, kwargs in runner.calls:
            assert kwargs["stdout"] is subprocess.DEVNULL

    def test_timeout_is_passed_through(self) -> None:
        runner = FakeRunner(blocked=("/x",))

        run_probe(self._probe(), SETTINGS, timeout=7.5, run=runner)

        assert all(kwargs["timeout"] == 7.5 for _, kwargs in runner.calls)

    def test_unblocked_deny_probe_fails_and_keeps_sandbox_stderr(self) -> None:
        runner = FakeRunner()

        result = run_probe(self._probe(), SETTINGS, timeout=5, run=runner)

        assert result.status is Status.FAIL
        assert "not blocked" in result.reason

    def test_sandbox_stderr_is_kept_and_truncated(self) -> None:
        runner = FakeRunner(blocked=("/x",))

        result = run_probe(self._probe(), SETTINGS, timeout=5, run=runner)

        assert "Operation not permitted" in result.sandbox_stderr

        long = FakeRunner(srt_failure=(1, "e" * 2000))
        result = run_probe(self._probe(), SETTINGS, timeout=5, run=long)
        assert len(result.sandbox_stderr) <= 400

    def test_control_failure_yields_invalid(self) -> None:
        runner = FakeRunner(blocked=("/x",), control_failures=("/x",))

        result = run_probe(self._probe(), SETTINGS, timeout=5, run=runner)

        assert result.status is Status.INVALID
        assert "No such file" in result.control_stderr

    @pytest.mark.parametrize(
        "stderr",
        [
            "sh: line 1: /Library/Keychains/.twsrt-probe-1: Operation not permitted\n",
            "sh: line 1: /root/x: Permission denied\n",
            "sh: line 1: /Volumes/ro/x: Read-only file system\n",
        ],
    )
    def test_deny_probe_refused_by_the_os_itself_passes(self, stderr: str) -> None:
        # /Library/Keychains is root-owned: the intent "cannot write here" is
        # met before srt is even involved.
        def runner(argv: list[str], **kwargs) -> subprocess.CompletedProcess:
            return subprocess.CompletedProcess(argv, 1, stdout="", stderr=stderr)

        result = run_probe(self._probe(": >> /x"), SETTINGS, timeout=5, run=runner)

        assert result.status is Status.PASS
        assert result.control_exit == 1
        assert result.sandbox_exit == 1
        assert "outside the sandbox" in result.reason

    def test_allow_probe_refused_by_the_os_is_invalid(self) -> None:
        runner = FakeRunner(control_denied=("/x",), blocked=("/x",))
        probe = Probe("write-allow", "/x", ": >> /x", Expect.ALLOW)

        result = run_probe(probe, SETTINGS, timeout=5, run=runner)

        assert result.status is Status.INVALID

    def test_control_stdout_is_still_never_captured(self) -> None:
        runner = FakeRunner(control_denied=("/x",), blocked=("/x",))

        run_probe(self._probe(), SETTINGS, timeout=5, run=runner)

        control_kwargs = runner.calls[0][1]
        assert control_kwargs["stdout"] is subprocess.DEVNULL
        assert control_kwargs["stderr"] is subprocess.PIPE

    def test_control_can_be_disabled_per_probe(self) -> None:
        runner = FakeRunner(blocked=("/x",))

        result = run_probe(self._probe(control=False), SETTINGS, timeout=5, run=runner)

        assert len(runner.calls) == 1
        assert runner.calls[0][0][0] == "srt"
        assert result.control_exit is None
        assert result.status is Status.PASS

    def test_skipped_probe_is_not_executed(self) -> None:
        runner = FakeRunner()

        result = run_probe(
            self._probe(skip_reason="glob pattern"), SETTINGS, timeout=5, run=runner
        )

        assert runner.calls == []
        assert result.status is Status.SKIP
        assert result.reason == "glob pattern"

    def test_artifact_is_removed_after_each_run(self, tmp_path: Path) -> None:
        artifact = tmp_path / "probe.pem"

        def runner(argv: list[str], **kwargs) -> subprocess.CompletedProcess:
            artifact.write_text("x")
            code = 1 if argv[0] == "srt" else 0
            return subprocess.CompletedProcess(argv, code, stdout="", stderr="")

        probe = Probe(
            kind="write-deny",
            rule="**/*.pem",
            command=f": >> {artifact}",
            expect=Expect.DENY,
            artifact=artifact,
        )

        result = run_probe(probe, SETTINGS, timeout=5, run=runner)

        assert result.status is Status.PASS
        assert not artifact.exists()

    def test_no_probe_command_can_truncate_a_file(self, tmp_path: Path) -> None:
        # Defense in depth: every write probe uses append-open, so even a wrong
        # target path could never lose content.
        (tmp_path / ".ssh").mkdir()
        (tmp_path / ".ssh" / "config").write_text("Host x")
        scratch = tmp_path / "scratch"
        scratch.mkdir()

        probes = derive_probes(
            _srt(
                {
                    "denyRead": ["~/.ssh"],
                    "denyWrite": ["**/*.pem", "~/.ssh", "~/.ssh/config"],
                    "allowWrite": [".", "~/.ssh/config"],
                }
            ),
            tmp_path,
            tmp_path,
            scratch,
        )

        for probe in probes:
            assert " > " not in probe.command, probe
            assert "printf" not in probe.command, probe

    def test_artifact_that_existed_before_the_run_is_never_removed(
        self, tmp_path: Path
    ) -> None:
        artifact = tmp_path / "existing.pem"
        artifact.write_text("keep me\n")
        probe = Probe(
            "write-deny",
            "**/*.pem",
            f": >> {artifact}",
            Expect.DENY,
            artifact=artifact,
        )

        run_probe(probe, SETTINGS, timeout=5, run=FakeRunner(blocked=(".pem",)))

        assert artifact.read_text() == "keep me\n"

    def test_timeout_yields_error(self) -> None:
        def runner(argv: list[str], **kwargs) -> subprocess.CompletedProcess:
            raise subprocess.TimeoutExpired(argv, kwargs["timeout"])

        result = run_probe(self._probe(), SETTINGS, timeout=5, run=runner)

        assert result.status is Status.ERROR
        assert "timed out" in result.reason

    def test_sandbox_apply_failure_yields_error_not_pass(self) -> None:
        runner = FakeRunner(
            srt_failure=(71, "sandbox-exec: sandbox_apply: Operation not permitted\n")
        )

        result = run_probe(self._probe(), SETTINGS, timeout=5, run=runner)

        assert result.status is Status.ERROR
        assert "sandbox" in result.reason

    def test_duration_is_measured(self) -> None:
        result = run_probe(self._probe(), SETTINGS, timeout=5, run=FakeRunner())

        assert result.duration_ms >= 0


class _Records(logging.Handler):
    """Collects debug messages from the probe logger without depending on
    propagation, which the CLI switches off for the parent logger."""

    def __init__(self) -> None:
        super().__init__(logging.DEBUG)
        self.messages: list[str] = []

    def emit(self, record: logging.LogRecord) -> None:
        self.messages.append(record.getMessage())


@pytest.fixture
def probe_log() -> Iterator[list[str]]:
    logger = logging.getLogger("twsrt.probe")
    handler = _Records()
    previous = logger.level
    logger.setLevel(logging.DEBUG)
    logger.addHandler(handler)
    try:
        yield handler.messages
    finally:
        logger.removeHandler(handler)
        logger.setLevel(previous)


class TestObservability:
    def test_every_subprocess_is_logged_as_a_copyable_command_with_exit_code(
        self, probe_log: list[str]
    ) -> None:
        runner = FakeRunner(blocked=("my secret",))
        probe = Probe("read-deny", "/x", "head -c 1 -- '/my secret'", Expect.DENY)

        run_probe(probe, SETTINGS, timeout=5, run=runner)

        assert "exec: sh -c 'head -c 1 -- '\"'\"'/my secret'\"'\"''" in probe_log
        assert (
            "exec: srt -s /settings/.srt-settings.json -c "
            "'head -c 1 -- '\"'\"'/my secret'\"'\"''" in probe_log
        )
        exits = [m for m in probe_log if m.startswith("exit=")]
        assert len(exits) == 2
        assert exits[0].startswith("exit=0 ")
        assert exits[1].startswith("exit=1 ")
        assert "Operation not permitted" in exits[1]

    def test_preflight_logs_binary_version_source_and_check(
        self, probe_log: list[str], tmp_path: Path
    ) -> None:
        package_dir = tmp_path / "node_modules" / "@anthropic-ai" / "sandbox-runtime"
        (package_dir / "dist").mkdir(parents=True)
        (package_dir / "package.json").write_text(json.dumps({"version": "0.0.99"}))
        binary = package_dir / "dist" / "cli.js"
        binary.write_text("")

        preflight(SETTINGS, run=FakeRunner(), which=lambda _: str(binary))

        assert f"srt binary: {binary}" in probe_log
        assert any("0.0.99" in m and "package.json" in m for m in probe_log)
        assert "exec: srt -s /settings/.srt-settings.json -c true" in probe_log

    def test_derivation_decisions_are_logged(
        self, probe_log: list[str], tmp_path: Path
    ) -> None:
        real = tmp_path / "configs" / "dot-aws"
        real.mkdir(parents=True)
        (real / "config").write_text("x")
        os.symlink(real, tmp_path / ".aws")

        derive_probes(
            _srt({"denyRead": ["~/.aws", "~/.kube", "**/.env"]}),
            tmp_path,
            tmp_path,
            tmp_path / "s",
        )

        assert any(
            "read-deny ~/.aws" in m and str(real / "config") in m for m in probe_log
        )
        assert any("symlink" in m and str(real) in m for m in probe_log)
        assert any(
            "skip read-deny ~/.kube" in m and "not present" in m for m in probe_log
        )
        assert any("skip read-deny **/.env" in m and "glob" in m for m in probe_log)

    def test_artifact_removal_is_logged(
        self, probe_log: list[str], tmp_path: Path
    ) -> None:
        artifact = tmp_path / "probe.pem"

        def runner(argv: list[str], **kwargs) -> subprocess.CompletedProcess:
            artifact.write_text("x")
            return subprocess.CompletedProcess(argv, 0, stdout="", stderr="")

        probe = Probe(
            "write-deny", "**/*.pem", ": >> x", Expect.DENY, artifact=artifact
        )

        run_probe(probe, SETTINGS, timeout=5, run=runner)

        assert probe_log.count(f"removed artifact {artifact}") == 2

    def test_timeout_is_logged(self, probe_log: list[str]) -> None:
        def runner(argv: list[str], **kwargs) -> subprocess.CompletedProcess:
            raise subprocess.TimeoutExpired(argv, kwargs["timeout"])

        run_probe(
            Probe("read-deny", "/x", "sleep 99", Expect.DENY), SETTINGS, 5, run=runner
        )

        assert any(m.startswith("timeout after 5s: sh -c") for m in probe_log)


class TestPreflight:
    def test_returns_srt_version_when_sandbox_applies(self) -> None:
        runner = FakeRunner()

        version = preflight(SETTINGS, run=runner, which=lambda _: None)

        assert version == "0.0.75"
        argv = [call[0] for call in runner.calls]
        assert ["srt", "--version"] in argv
        assert ["srt", "-s", str(SETTINGS), "-c", "true"] in argv

    def test_version_prefers_package_json_next_to_the_binary(
        self, tmp_path: Path
    ) -> None:
        # `srt --version` reports a hardcoded 1.0.0 upstream; package.json is truthful.
        package_dir = tmp_path / "node_modules" / "@anthropic-ai" / "sandbox-runtime"
        (package_dir / "dist").mkdir(parents=True)
        (package_dir / "package.json").write_text(json.dumps({"version": "0.0.99"}))
        binary = package_dir / "dist" / "cli.js"
        binary.write_text("")
        runner = FakeRunner()

        version = preflight(SETTINGS, run=runner, which=lambda _: str(binary))

        assert version == "0.0.99"
        assert ["srt", "--version"] not in [call[0] for call in runner.calls]

    def test_missing_srt_binary(self) -> None:
        runner = FakeRunner(raise_for_srt=FileNotFoundError("srt"))

        with pytest.raises(ProbeError, match="srt not found"):
            preflight(SETTINGS, run=runner)

    def test_nested_sandbox_gets_a_hint(self) -> None:
        runner = FakeRunner(
            srt_failure=(71, "sandbox-exec: sandbox_apply: Operation not permitted\n")
        )

        with pytest.raises(ProbeError, match="inside another sandbox"):
            preflight(SETTINGS, run=runner)

    def test_unloadable_settings_surface_srt_stderr(self) -> None:
        runner = FakeRunner(
            srt_failure=(1, "Error: Could not load settings from /settings/x\n")
        )

        with pytest.raises(ProbeError, match="Could not load settings"):
            preflight(SETTINGS, run=runner)
