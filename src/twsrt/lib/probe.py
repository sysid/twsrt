"""Derive and execute probes that prove the SRT sandbox enforces the effective rules.

A probe is one shell command derived from a compiled SRT rule. It runs twice: once
plainly (control) and once under ``srt -s <settings> -c``. The control run proves the
probe itself is valid — a missing file or an unreachable host must not count as
"protected". Nothing here writes to the terminal; the CLI owns presentation.
"""

from __future__ import annotations

import json
import os
import shlex
import shutil
import subprocess
import time
from collections.abc import Callable
from dataclasses import dataclass
from enum import Enum
from pathlib import Path

from twsrt.lib.models import Action, Scope, SrtResult

Runner = Callable[..., subprocess.CompletedProcess]

_CURL = "curl -sS -m 10 -o /dev/null -I https://{host}/"
_CANARY_DOMAINS = ("example.com", "example.org", "example.net")
_WALK_DEPTH = 4
_STDERR_LIMIT = 400
_PREFLIGHT_TIMEOUT = 30.0
_NESTED_HINT = (
    "srt cannot apply a sandbox inside another sandbox, e.g. Claude Code; "
    "run twsrt test from a plain terminal"
)


class ProbeError(Exception):
    """The probe run cannot start: srt missing, settings unloadable, no sandbox."""


class Expect(Enum):
    DENY = "deny"
    ALLOW = "allow"


class Status(Enum):
    PASS = "PASS"
    FAIL = "FAIL"
    INVALID = "INVALID"
    SKIP = "SKIP"
    ERROR = "ERROR"


@dataclass(frozen=True)
class Probe:
    kind: str
    rule: str
    command: str
    expect: Expect
    control: bool = True
    # File the command creates; removed after every run so control and sandbox
    # start from the same state and nothing is left behind.
    artifact: Path | None = None
    # Set when no concrete command can be derived; reported, never executed.
    skip_reason: str | None = None


@dataclass
class ProbeResult:
    probe: Probe
    status: Status
    control_exit: int | None = None
    sandbox_exit: int | None = None
    sandbox_stderr: str = ""
    duration_ms: int = 0
    reason: str = ""


# --- derivation -------------------------------------------------------------


def derive_probes(srt: SrtResult, cwd: Path, home: Path, scratch: Path) -> list[Probe]:
    """Turn the effective SRT rules into concrete probes, grouped by kind."""
    read_deny = _patterns(srt, Scope.READ, Action.DENY)
    write_deny = _patterns(srt, Scope.WRITE, Action.DENY)
    write_allow = _patterns(srt, Scope.WRITE, Action.ALLOW)
    net_allow = _patterns(srt, Scope.NETWORK, Action.ALLOW)
    net_deny = _patterns(srt, Scope.NETWORK, Action.DENY)

    probes: list[Probe] = []
    for pattern in read_deny:
        probes.extend(_read_deny(pattern, cwd, home))
    probes.extend(_write_deny(pattern, scratch) for pattern in write_deny)
    probes.extend(_write_allow(pattern, cwd, home) for pattern in write_allow)
    probes.extend(_network(host, "net-allow", Expect.ALLOW) for host in net_allow)
    probes.extend(_network(host, "net-deny", Expect.DENY) for host in net_deny)
    probes.append(_allowlist_canary(net_allow))
    return probes


def scratch_root(srt: SrtResult, cwd: Path, home: Path) -> Path:
    """Where write-deny probe files go: the first concrete allowWrite directory.

    A deny glob can only be witnessed where writing is otherwise allowed;
    falling back to cwd keeps the run going when no allowWrite entry exists.
    """
    for pattern in _patterns(srt, Scope.WRITE, Action.ALLOW):
        if _is_glob(pattern):
            continue
        directory = _expand(pattern, cwd, home)
        if directory.is_dir():
            return directory
    return cwd


def _patterns(srt: SrtResult, scope: Scope, action: Action) -> list[str]:
    return [
        rule.pattern
        for rule in srt.rules
        if rule.scope is scope and rule.action is action
    ]


def _read_deny(pattern: str, cwd: Path, home: Path) -> list[Probe]:
    if _is_glob(pattern):
        return [
            _skip("read-deny", pattern, Expect.DENY, "glob pattern: no concrete probe")
        ]
    path = _expand(pattern, cwd, home)
    if not path.exists():
        return [_skip("read-deny", pattern, Expect.DENY, "path not present on host")]

    subject = path if path.is_file() else _first_file(path)
    probes = [Probe("read-deny", pattern, _read_command(path, subject), Expect.DENY)]

    # srt keeps symlinked deny paths unresolved while Seatbelt matches the real
    # vnode path, so a deny on a symlink can be a silent no-op. Probing the
    # realpath as well makes that gap visible per rule.
    target = subject or path
    real = Path(os.path.realpath(target))
    if real != target:
        command = _read_command(real, None if subject is None else real)
        probes.append(Probe("read-deny", f"{pattern} (realpath)", command, Expect.DENY))
    return probes


def _read_command(directory_or_file: Path, subject: Path | None) -> str:
    if subject is None:
        return f"ls -- {shlex.quote(str(directory_or_file))}"
    return f"head -c 1 -- {shlex.quote(str(subject))}"


def _first_file(directory: Path) -> Path | None:
    """First regular file below *directory*, deterministic, bounded depth."""
    base_depth = len(directory.parts)
    for root, dirs, files in os.walk(directory):
        dirs.sort()
        for name in sorted(files):
            candidate = Path(root) / name
            if candidate.is_file() and not candidate.is_symlink():
                return candidate
        if len(Path(root).parts) - base_depth >= _WALK_DEPTH:
            dirs[:] = []
    return None


def _write_deny(pattern: str, scratch: Path) -> Probe:
    relative = _glob_probe_name(pattern)
    if relative is None:
        return _skip(
            "write-deny",
            pattern,
            Expect.DENY,
            "pattern cannot be turned into a probe file",
        )
    target = scratch / relative
    # Parents are created on the host so the sandboxed write fails only because
    # of the deny glob, not because of a missing directory.
    target.parent.mkdir(parents=True, exist_ok=True)
    return Probe(
        "write-deny",
        pattern,
        f"printf x > {shlex.quote(str(target))}",
        Expect.DENY,
        artifact=target,
    )


def _glob_probe_name(pattern: str) -> Path | None:
    """Relative file name that matches a ``**/``-anchored deny glob.

    ponytail: only patterns anchored with ``**/`` are convertible — those match
    anywhere, so a file inside the scratch directory is a valid witness. Absolute,
    home-relative, and mid-path wildcards are reported as skipped; a matcher that
    understands SRT's anchoring would be the upgrade path.
    """
    if not pattern.startswith("**/"):
        return None
    parts = pattern.removeprefix("**/").split("/")
    if not parts or "" in parts:
        return None
    if parts[-1] == "**":
        literal = parts[:-1]
        if not literal or any(_is_glob(part) for part in literal):
            return None
        return Path(*literal, "probe")
    if any(_is_glob(part) for part in parts[:-1]):
        return None
    last = parts[-1]
    if "**" in last or "[" in last:
        return None
    return Path(*parts[:-1], last.replace("*", "probe").replace("?", "x"))


def _write_allow(pattern: str, cwd: Path, home: Path) -> Probe:
    if _is_glob(pattern):
        return _skip(
            "write-allow", pattern, Expect.ALLOW, "glob pattern: no concrete probe"
        )
    directory = _expand(pattern, cwd, home)
    if not directory.is_dir():
        return _skip(
            "write-allow", pattern, Expect.ALLOW, "directory not present on host"
        )
    artifact = directory / f".twsrt-probe-{os.getpid()}"
    return Probe(
        "write-allow",
        pattern,
        f"printf x > {shlex.quote(str(artifact))}",
        Expect.ALLOW,
        artifact=artifact,
    )


def _network(host: str, kind: str, expect: Expect) -> Probe:
    if _is_glob(host):
        return _skip(kind, host, expect, "wildcard domain: no concrete host")
    return Probe(kind, host, _CURL.format(host=host), expect)


def _allowlist_canary(allowed: list[str]) -> Probe:
    """A host outside the allowlist must be blocked; proves allowlist mode is on."""
    host = next(
        (domain for domain in _CANARY_DOMAINS if domain not in allowed),
        _CANARY_DOMAINS[-1],
    )
    return Probe(
        "net-deny", f"{host} (not allowlisted)", _CURL.format(host=host), Expect.DENY
    )


def _skip(kind: str, rule: str, expect: Expect, reason: str) -> Probe:
    return Probe(kind, rule, "", expect, skip_reason=reason)


def _is_glob(pattern: str) -> bool:
    return any(char in pattern for char in "*?[")


def _expand(pattern: str, cwd: Path, home: Path) -> Path:
    if pattern == "~":
        return home
    if pattern.startswith("~/"):
        return home / pattern[2:]
    path = Path(pattern)
    return path if path.is_absolute() else cwd / path


# --- execution --------------------------------------------------------------


def judge(expect: Expect, control_exit: int, sandbox_exit: int) -> tuple[Status, str]:
    """Verdict from the two exit codes. Control failure invalidates the probe."""
    if control_exit != 0:
        return Status.INVALID, f"probe fails even without sandbox (exit {control_exit})"
    if expect is Expect.DENY:
        if sandbox_exit == 0:
            return Status.FAIL, "not blocked: command succeeded inside the sandbox"
        return Status.PASS, ""
    if sandbox_exit != 0:
        return Status.FAIL, f"blocked but should be allowed (exit {sandbox_exit})"
    return Status.PASS, ""


def run_probe(
    probe: Probe, settings: Path, timeout: float, run: Runner | None = None
) -> ProbeResult:
    """Execute control and sandboxed run; stdout is discarded, never captured."""
    run = run or subprocess.run
    if probe.skip_reason is not None:
        return ProbeResult(probe, Status.SKIP, reason=probe.skip_reason)

    started = time.monotonic()
    control_exit: int | None = None
    try:
        if probe.control:
            control_exit = _execute(
                run, ["sh", "-c", probe.command], timeout, capture=False
            ).returncode
            _remove(probe.artifact)
        completed = _execute(
            run,
            ["srt", "-s", str(settings), "-c", probe.command],
            timeout,
            capture=True,
        )
        _remove(probe.artifact)
    except subprocess.TimeoutExpired:
        _remove(probe.artifact)
        return ProbeResult(
            probe,
            Status.ERROR,
            control_exit=control_exit,
            duration_ms=_elapsed_ms(started),
            reason=f"timed out after {timeout:g}s",
        )

    stderr = (completed.stderr or "")[-_STDERR_LIMIT:]
    if "sandbox_apply" in stderr:
        status, reason = Status.ERROR, "srt could not apply the sandbox"
    else:
        status, reason = judge(
            probe.expect,
            0 if control_exit is None else control_exit,
            completed.returncode,
        )
    return ProbeResult(
        probe,
        status,
        control_exit=control_exit,
        sandbox_exit=completed.returncode,
        sandbox_stderr=stderr,
        duration_ms=_elapsed_ms(started),
        reason=reason,
    )


def preflight(
    settings: Path,
    run: Runner | None = None,
    which: Callable[[str], str | None] = shutil.which,
) -> str:
    """Verify srt is present and can sandbox a trivial command; return its version."""
    run = run or subprocess.run
    try:
        version = _srt_version(run, which)
        check = _execute(
            run,
            ["srt", "-s", str(settings), "-c", "true"],
            _PREFLIGHT_TIMEOUT,
            capture=True,
        )
    except FileNotFoundError:
        raise ProbeError("srt not found on PATH (install: make install-srt)") from None
    except subprocess.TimeoutExpired:
        raise ProbeError("srt preflight timed out") from None
    if check.returncode != 0:
        stderr = (check.stderr or "").strip()
        hint = f" Hint: {_NESTED_HINT}." if "sandbox_apply" in stderr else ""
        raise ProbeError(
            f"srt preflight failed (exit {check.returncode}): {stderr}{hint}"
        )
    return version


def _srt_version(run: Runner, which: Callable[[str], str | None]) -> str:
    # `srt --version` reports a hardcoded 1.0.0 upstream; package.json next to
    # the resolved binary is the truthful source, --version the fallback.
    binary = which("srt")
    if binary is not None:
        package = Path(os.path.realpath(binary)).parent.parent / "package.json"
        try:
            version = json.loads(package.read_text()).get("version")
            if isinstance(version, str) and version:
                return version
        except (OSError, ValueError):
            pass
    completed = run(
        ["srt", "--version"],
        stdin=subprocess.DEVNULL,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
        timeout=_PREFLIGHT_TIMEOUT,
    )
    return (completed.stdout or "").strip() or "unknown"


def _execute(
    run: Runner, argv: list[str], timeout: float, capture: bool
) -> subprocess.CompletedProcess:
    return run(
        argv,
        stdin=subprocess.DEVNULL,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.PIPE if capture else subprocess.DEVNULL,
        text=True,
        timeout=timeout,
    )


def _remove(artifact: Path | None) -> None:
    if artifact is None:
        return
    try:
        artifact.unlink()
    except FileNotFoundError:
        pass


def _elapsed_ms(started: float) -> int:
    return int((time.monotonic() - started) * 1000)
