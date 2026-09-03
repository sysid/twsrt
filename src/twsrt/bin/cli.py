"""twsrt CLI — agent security configuration generator."""

from __future__ import annotations

import json
import logging
import os
import subprocess
import tempfile
from pathlib import Path

import typer

from twsrt.lib.models import AppConfig, CompilationResult, yolo_path

__version__ = "1.3.1"

app = typer.Typer(
    name="twsrt",
    help="Agent security configuration generator.",
    no_args_is_help=True,
)
log = logging.getLogger("twsrt")


def _error(message: str) -> None:
    typer.secho(f"Error: {message}", fg=typer.colors.RED, bold=True, err=True)


def _warning(message: str) -> None:
    typer.secho(f"Warning: {message}", fg=typer.colors.YELLOW, err=True)


def _info(message: str) -> None:
    typer.secho(message, fg=typer.colors.CYAN)


def _success(message: str) -> None:
    typer.secho(message, fg=typer.colors.GREEN)


def _drift(message: str) -> None:
    typer.secho(message, fg=typer.colors.YELLOW)


def _extra(message: str) -> None:
    typer.secho(message, fg=typer.colors.RED)


def _debug(message: str) -> None:
    typer.secho(f"Debug: {message}", fg=typer.colors.CYAN, dim=True, err=True)


class _CliLogHandler(logging.Handler):
    def emit(self, record: logging.LogRecord) -> None:
        _debug(self.format(record))


def _configure_logging(verbose: bool) -> None:
    log.handlers.clear()
    log.propagate = False
    if verbose:
        log.setLevel(logging.DEBUG)
        log.addHandler(_CliLogHandler())
    else:
        log.setLevel(logging.WARNING)


def _version_callback(value: bool) -> None:
    if value:
        typer.echo(f"twsrt version: {__version__}")
        raise typer.Exit()


@app.callback()
def main(
    ctx: typer.Context,
    verbose: bool = typer.Option(False, "--verbose", "-v", help="Enable DEBUG logging"),
    version: bool = typer.Option(
        False,
        "--version",
        "-V",
        callback=_version_callback,
        is_eager=True,
        help="Print version and exit",
    ),
    config: Path = typer.Option(
        Path("~/.config/twsrt/config.toml"),
        "--config",
        "-c",
        help="Config file path",
    ),
) -> None:
    if "NO_COLOR" in os.environ:
        ctx.color = False
    _configure_logging(verbose)
    ctx.ensure_object(dict)
    ctx.obj["config_path"] = config.expanduser()


DEFAULT_CONFIG_TOML = """\
# twsrt canonical-source registry and generation targets.
#
# Human-maintained policy lives in the registered *.jsonc fragments. twsrt
# resolves one profile, composes its fragments, and writes strict canonical JSON
# plus agent-specific configuration. Relative paths below resolve from this file.

# Required configuration schema. Unsupported versions fail instead of guessing.
schema_version = 1

# Profile used by generate/diff when --profile is omitted.
default_profile = "default"


# -----------------------------------------------------------------------------
# Canonical source kinds
# -----------------------------------------------------------------------------
# Both registered kinds, srt and bash, are required. Each kind has one generated
# strict-JSON output and one or more named JSONC fragments. Output paths must be
# distinct and must not be the same path as any input fragment.

[sources.srt]
# Compiled Sandbox Runtime configuration. This is generated; do not hand-edit it.
output = "~/.srt-settings.json"

[sources.srt.fragments.base]
# Fragment names are arbitrary profile-facing identifiers.
path = "srt/base.jsonc"

# Additional SRT fragment example:
# [sources.srt.fragments.work]
# path = "srt/work.jsonc"

[sources.bash]
# Compiled command-policy JSON consumed by the agent generators.
output = "bash-rules.json"

[sources.bash.fragments.base]
path = "bash/base.jsonc"

# Additional Bash fragment example:
# [sources.bash.fragments.work]
# path = "bash/work.jsonc"


# -----------------------------------------------------------------------------
# Profiles
# -----------------------------------------------------------------------------
# A resolved profile must select at least one fragment for every source kind.
# Parents resolve before children; repeated fragment names are deduplicated.
# Inheritance adds compatible fragments—it does not override conflicting values.

[profiles.default]
srt = ["base"]
bash = ["base"]

# Profile inheritance and additional selection example:
# [profiles.work]
# extends = ["default"]
# srt = ["work"]
# bash = ["work"]

# Multiple-parent example; parent order is significant and stable:
# [profiles.combined]
# extends = ["default", "work"]
# srt = []
# bash = []


# -----------------------------------------------------------------------------
# Generated agent targets
# -----------------------------------------------------------------------------
# Every supported target key is shown here. Home-relative and absolute paths are
# supported. Relative paths resolve from the directory containing config.toml.

[targets]
# Full-mode settings file. It must not be named settings.json because that path
# is reserved for twsrt's symlink anchor.
claude_settings = "~/.claude/settings.full.json"

# Optional. When omitted, generate prints flags to stdout instead of writing them.
# copilot_output = "copilot-flags.txt"

# Optional for generate-all writes. Setting it enables the Codex target there.
codex_config = "~/.codex/config.toml"

# Optional. Omit to disable generation of sandbox-escape escalation rules.
codex_rules = "~/.codex/rules/twsrt.rules"

# Optional explicit YOLO targets. When omitted, twsrt inserts ".yolo" before the
# final suffix of the corresponding full-mode target.
# claude_settings_yolo = "~/.claude/settings.yolo.json"
# copilot_output_yolo = "copilot-flags.yolo.txt"


# -----------------------------------------------------------------------------
# Invariant sync between the Claude full and yolo targets
# -----------------------------------------------------------------------------
# Claude Code writes runtime settings (model, theme, editorMode, hooks added via
# the UI, ...) into whatever settings.json points to. With this table present,
# generate -w claude first copies every key twsrt does not manage from that file
# (the donor) into the target being generated, so the two targets converge on
# each mode switch. Deletions propagate; last writer wins. Managed sections
# (permissions.deny/ask, WebFetch allows, sandbox.*) are never synced.
# Remove the table to disable the sync.
[claude_sync]
# Keys that legitimately differ between modes and are never synced.
# Dotted paths address nested keys, e.g. "hooks.PostToolUse".
mode_specific = [
  "skipDangerousModePermissionPrompt",
  "skipAutoPermissionPrompt",
]


# -----------------------------------------------------------------------------
# Mode-specific sandbox overrides
# -----------------------------------------------------------------------------
# These optional tables are shallow top-level overrides applied after compiled
# SRT values: [sandbox_overrides.yolo] for --yolo, otherwise
# [sandbox_overrides.full]. Prefer canonical SRT JSONC for shared policy.
#
# Known top-level sandbox keys accepted here:
#   enabled = true | false
#   enableWeakerNetworkIsolation = true | false
#   enableWeakerNestedSandbox = true | false
#   autoAllowBashIfSandboxed = true | false
#   allowUnsandboxedCommands = true | false
#   excludedCommands = ["command", ...]
#   ignoreViolations = { "executable" = ["path", ...] }
#
# Known nested network keys:
#   allowedDomains, deniedDomains, allowUnixSockets, allowAllUnixSockets,
#   allowLocalBinding, httpProxyPort, socksProxyPort
#
# Known nested filesystem keys:
#   allowWrite
#
# Nested network/filesystem overrides replace the entire compiled section.
# For filesystem overrides, twsrt then restores denyRead and denyWrite as
# empty arrays; canonical deny paths remain enforced through Claude permission
# rules. Prefer SRT JSONC unless complete replacement is intentional.

[sandbox_overrides.yolo]
# YOLO skips command confirmation, so keep the kernel sandbox enabled and forbid
# falling back to unsandboxed execution.
enabled = true
autoAllowBashIfSandboxed = true
allowUnsandboxedCommands = false

# Optional top-level examples:
# enableWeakerNetworkIsolation = false
# enableWeakerNestedSandbox = false
# excludedCommands = ["docker"]
# ignoreViolations = { "*" = ["/usr/bin"] }

# Complete nested replacement examples—normally keep these in SRT JSONC:
# [sandbox_overrides.yolo.network]
# allowedDomains = ["github.com"]
# deniedDomains = ["example.invalid"]
# allowUnixSockets = ["/tmp/example.sock"]
# allowAllUnixSockets = false
# allowLocalBinding = true
# httpProxyPort = 8080
# socksProxyPort = 1080
#
# [sandbox_overrides.yolo.filesystem]
# allowWrite = ["."]

[sandbox_overrides.full]
# Full mode retains interactive approval, so this profile intentionally disables
# the agent's native sandbox. Remove this override to inherit SRT's enabled value.
enabled = false

# The same seven top-level and eight nested keys documented above are valid here.
"""
DEFAULT_SRT_JSONC = """\
{
  // Canonical Sandbox Runtime policy. Add more fragments in config.toml.
  "enabled": true,
  "filesystem": {
    "allowWrite": [],
    "denyWrite": [],
    "denyRead": []
  },
  "network": {
    "allowedDomains": [],
    "deniedDomains": []
  }
}
"""
DEFAULT_BASH_JSONC = """\
{
  // Agent command policy.
  "allow": [],
  "ask": [],
  "deny": []
}
"""


@app.command(name="config")
def config_command(
    ctx: typer.Context,
    init: bool = typer.Option(
        False,
        "--init",
        help="Create a commented starter configuration before opening it.",
    ),
) -> None:
    """Open the canonical configuration in $EDITOR."""
    target: Path = ctx.obj["config_path"]
    if not target.exists():
        if not init:
            _error(f"Config not found: {target}. Use --init to create.")
            raise typer.Exit(2)
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(DEFAULT_CONFIG_TOML)
        starters = {
            target.parent / "srt/base.jsonc": DEFAULT_SRT_JSONC,
            target.parent / "bash/base.jsonc": DEFAULT_BASH_JSONC,
        }
        for path, content in starters.items():
            if not path.exists():
                path.parent.mkdir(parents=True, exist_ok=True)
                path.write_text(content)

    editor = _resolve_editor()
    try:
        result = subprocess.run([editor, str(target)])
    except FileNotFoundError:
        log.debug("Opening config in editor failed", exc_info=True)
        _error(f"Editor not found: {editor}")
        raise typer.Exit(1)
    raise typer.Exit(result.returncode)


@app.command()
def generate(
    ctx: typer.Context,
    agent: str = typer.Argument(
        "all", help="Target agent: claude, copilot, codex, or all"
    ),
    write: bool = typer.Option(False, "--write", "-w", help="Write target files"),
    dry_run: bool = typer.Option(False, "--dry-run", "-n", help="Show writes"),
    yolo: bool = typer.Option(False, "--yolo", help="Deny-only agent mode"),
    profile: str | None = typer.Option(
        None, "--profile", "-p", help="Canonical-source profile"
    ),
) -> None:
    """Compile canonical sources and generate agent-specific configuration."""
    try:
        config, compiled = _compile(ctx.obj["config_path"], profile, yolo)
        generators = _select_generators(agent, config, for_write=write)
        log.debug(
            "Generating agents=%s write=%s dry_run=%s",
            ",".join(generator.name for generator in generators),
            write,
            dry_run,
        )
        rendered = {
            generator.name: generator.generate(compiled.rules, config)
            for generator in generators
        }
        staged = (
            _stage_agent_files(generators, rendered, compiled, config) if write else {}
        )
    except (FileExistsError, FileNotFoundError, ValueError) as exc:
        log.debug("Generation failed", exc_info=True)
        _error(str(exc))
        raise typer.Exit(1)

    log.debug("Prepared generated artifacts: staged_targets=%d", len(staged))
    _print_generator_warnings(generators, compiled, config)
    if write and dry_run:
        for document in compiled.documents.values():
            _info(f"Would write canonical: {document.output_path}")
        for path in staged:
            _info(f"Would write agent target: {path}")
        for name, output in rendered.items():
            _info(f"--- Dry run: {name} ---")
            typer.echo(output)
        return

    if write:
        for document in compiled.documents.values():
            _atomic_write(document.output_path, _serialize(document.document))
            _success(f"Wrote canonical: {document.output_path}")
        _write_agent_files(staged, config)
        for path in staged:
            _success(f"Wrote: {path}")
        if "codex" in rendered:
            _info("Restart Codex to load the updated permission profile and rules.")
        for generator in generators:
            if generator.name == "copilot" and _resolve_copilot_target(config) is None:
                typer.echo(rendered[generator.name])
        return

    for name, output in rendered.items():
        if len(rendered) > 1:
            _info(f"--- {name} ---")
        typer.echo(output)


@app.command()
def diff(
    ctx: typer.Context,
    agent: str = typer.Argument(
        "all", help="Target agent: claude, copilot, codex, or all"
    ),
    yolo: bool = typer.Option(False, "--yolo", help="Diff yolo agent targets"),
    profile: str | None = typer.Option(
        None, "--profile", "-p", help="Canonical-source profile"
    ),
) -> None:
    """Compare compiled canonical and agent configuration with disk."""
    try:
        config, compiled = _compile(ctx.obj["config_path"], profile, yolo)
        generators = _select_generators(agent, config, for_write=True)
    except (FileNotFoundError, ValueError) as exc:
        log.debug("Diff setup failed", exc_info=True)
        _error(str(exc))
        raise typer.Exit(1)

    log.debug(
        "Diffing agents=%s",
        ",".join(generator.name for generator in generators),
    )
    has_drift = False
    for kind, document in compiled.documents.items():
        actual = _read_json_object(document.output_path)
        if actual == document.document:
            _success(f"{kind} canonical: no drift")
        else:
            has_drift = True
            _drift(f"{kind} canonical: drift")

    for generator in generators:
        target = _resolve_diff_target(generator.name, config)
        if target is None or not target.exists():
            _error(f"Target file not found for {generator.name}: {target}")
            raise typer.Exit(2)
        if (
            generator.name == "codex"
            and config.codex_rules_path is not None
            and not config.codex_rules_path.exists()
        ):
            _error(f"Target file not found for codex: {config.codex_rules_path}")
            raise typer.Exit(2)
        try:
            result = generator.diff(compiled.rules, target, config)
        except ValueError as exc:
            log.debug("Diff for agent %s failed", generator.name, exc_info=True)
            _error(str(exc))
            raise typer.Exit(1)
        log.debug(
            "Diff result agent=%s missing=%d extra=%d",
            generator.name,
            len(result.missing),
            len(result.extra),
        )
        if result.matched:
            _success(f"{generator.name}: no drift")
        else:
            has_drift = True
            _drift(
                f"{generator.name}: {len(result.missing)} missing, "
                f"{len(result.extra)} extra"
            )
            for entry in result.missing:
                _drift(f"  + {entry} (missing from existing)")
            for entry in result.extra:
                _extra(f"  - {entry} (in existing, not in sources)")

    _print_generator_warnings(generators, compiled, config)

    if has_drift:
        raise typer.Exit(1)


@app.command(name="test")
def test_command(
    ctx: typer.Context,
    profile: str | None = typer.Option(
        None, "--profile", "-p", help="Canonical-source profile"
    ),
    keyword: str | None = typer.Option(
        None, "--keyword", "-k", help="Run only probes whose kind or rule contains this"
    ),
    json_output: bool = typer.Option(
        False, "--json", help="Print a JSON report instead of the table"
    ),
    timeout: float = typer.Option(30.0, "--timeout", help="Seconds per command"),
) -> None:
    """Prove the effective SRT settings are enforced by probing the sandbox."""
    from twsrt.lib.probe import (
        ProbeError,
        derive_probes,
        preflight,
        run_probe,
        scratch_root,
    )
    from twsrt.lib.sources import read_srt

    try:
        config, compiled = _compile(ctx.obj["config_path"], profile, yolo=False)
        settings = config.srt_path
        if not settings.exists():
            raise FileNotFoundError(
                f"SRT settings not found: {settings}. Run `twsrt generate -w` first."
            )
        srt = read_srt(settings)
        if _read_json_object(settings) != compiled.documents["srt"].document:
            _warning(
                f"srt canonical drift: probing the on-disk {settings}; "
                "run `twsrt generate -w` to apply fragment changes"
            )
        version = preflight(settings)
    except (FileNotFoundError, ValueError, ProbeError) as exc:
        log.debug("Test setup failed", exc_info=True)
        _error(str(exc))
        raise typer.Exit(2)

    cwd, home = Path.cwd(), Path.home()
    with tempfile.TemporaryDirectory(
        dir=scratch_root(srt, cwd, home), prefix=".twsrt-test-"
    ) as scratch:
        probes = derive_probes(srt, cwd, home, Path(scratch))
        if keyword:
            probes = [p for p in probes if keyword in p.kind or keyword in p.rule]
        log.debug(
            "Derived %d probes (srt %s, settings %s)", len(probes), version, settings
        )
        widths = _probe_widths(probes)
        if not json_output:
            _info(f"srt {version}, settings {settings}, {len(probes)} probes")
            typer.echo(
                _probe_row(
                    "STATUS", "KIND", "RULE", "CTL", "SBX", "MS", "PROBE", widths
                )
            )
        results = []
        for probe in probes:
            log.debug(
                "Probe kind=%s rule=%s command=%s",
                probe.kind,
                probe.rule,
                probe.command,
            )
            result = run_probe(probe, settings, timeout)
            log.debug(
                "Result kind=%s rule=%s status=%s control=%s sandbox=%s",
                probe.kind,
                probe.rule,
                result.status.value,
                result.control_exit,
                result.sandbox_exit,
            )
            results.append(result)
            if not json_output:
                _print_probe_result(result, widths)

    summary = _summarize(results)
    if json_output:
        typer.echo(
            json.dumps(_probe_report(version, settings, summary, results), indent=2)
        )
    else:
        _print_probe_details(results)
        _print_probe_summary(results, widths)
        line = " ".join(
            f"{key}={value}" for key, value in summary.items() if key != "total"
        )
        (_success if _probes_clean(summary) else _extra)(line)
    if not _probes_clean(summary):
        raise typer.Exit(1)


_PROBE_STATUS_COLORS = {
    "PASS": typer.colors.GREEN,
    "SKIP": typer.colors.YELLOW,
    "FAIL": typer.colors.RED,
    "INVALID": typer.colors.RED,
    "ERROR": typer.colors.RED,
}


_PROBE_RULE_WIDTH_CAP = 48


def _probe_widths(probes: list) -> tuple[int, int]:
    """Column widths for the table; a long absolute rule overflows its own row
    instead of widening every row."""
    kind = max([len("KIND"), *(len(p.kind) for p in probes)])
    rule = max([len("RULE"), *(len(p.rule) for p in probes)])
    return kind, min(rule, _PROBE_RULE_WIDTH_CAP)


def _probe_row(
    status: str,
    kind: str,
    rule: str,
    control: str,
    sandbox: str,
    duration: str,
    probe: str,
    widths: tuple[int, int],
) -> str:
    kind_width, rule_width = widths
    return (
        f"{status:<8} {kind:<{kind_width}} {rule:<{rule_width}} "
        f"{control:>3} {sandbox:>3} {duration:>6}  {probe}"
    )


def _print_probe_result(result, widths: tuple[int, int]) -> None:
    from twsrt.lib.probe import Status

    probe = result.probe
    status = result.status.value
    if result.status is Status.SKIP:
        row = _probe_row(
            status, probe.kind, probe.rule, "-", "-", "-", result.reason, widths
        )
    else:
        row = _probe_row(
            status,
            probe.kind,
            probe.rule,
            "-" if result.control_exit is None else str(result.control_exit),
            "-" if result.sandbox_exit is None else str(result.sandbox_exit),
            str(result.duration_ms),
            probe.command,
            widths,
        )
    colored = typer.style(row[: len(status)], fg=_PROBE_STATUS_COLORS[status])
    typer.echo(colored + row[len(status) :])


def _print_probe_details(results: list) -> None:
    from twsrt.lib.probe import Status

    for result in results:
        if result.status in (Status.PASS, Status.SKIP):
            continue
        probe = result.probe
        _extra(f"--- {probe.kind} {probe.rule}: {result.status.value} ---")
        typer.echo(f"  {result.reason}")
        typer.echo(f"  command: {probe.command}")
        if result.sandbox_stderr.strip():
            typer.echo(f"  stderr: {result.sandbox_stderr.strip()}")


def _print_probe_summary(results: list, widths: tuple[int, int]) -> None:
    """One line per probe that did not pass, so a long table needs no scrolling."""
    from twsrt.lib.probe import Status

    flagged = [result for result in results if result.status is not Status.PASS]
    if not flagged:
        return
    kind_width, rule_width = widths
    _info("--- summary ---")
    for result in flagged:
        status = result.status.value
        probe = result.probe
        line = (
            f"{status:<8} {probe.kind:<{kind_width}} {probe.rule:<{rule_width}}  "
            f"{result.reason}"
        )
        typer.echo(
            typer.style(status, fg=_PROBE_STATUS_COLORS[status]) + line[len(status) :]
        )


def _summarize(results: list) -> dict[str, int]:
    from twsrt.lib.probe import Status

    def count(status: Status) -> int:
        return sum(1 for result in results if result.status is status)

    return {
        "total": len(results),
        "passed": count(Status.PASS),
        "failed": count(Status.FAIL),
        "invalid": count(Status.INVALID),
        "error": count(Status.ERROR),
        "skipped": count(Status.SKIP),
    }


def _probes_clean(summary: dict[str, int]) -> bool:
    return summary["failed"] + summary["invalid"] + summary["error"] == 0


def _probe_report(
    version: str, settings: Path, summary: dict[str, int], results: list
) -> dict:
    return {
        "srt_version": version,
        "settings": str(settings),
        "summary": summary,
        "results": [
            {
                "kind": result.probe.kind,
                "rule": result.probe.rule,
                "command": result.probe.command,
                "expect": result.probe.expect.value,
                "status": result.status.value,
                "control_exit": result.control_exit,
                "sandbox_exit": result.sandbox_exit,
                "sandbox_stderr": result.sandbox_stderr,
                "duration_ms": result.duration_ms,
                "reason": result.reason,
            }
            for result in results
        ],
    }


def _compile(
    config_path: Path, profile_name: str | None, yolo: bool
) -> tuple[AppConfig, CompilationResult]:
    from twsrt.lib.config import load_config
    from twsrt.lib.profiles import resolve_profile
    from twsrt.lib.sources import compile_sources

    config = load_config(config_path)
    resolved = resolve_profile(config, profile_name)
    compiled = compile_sources(config, resolved)
    log.debug(
        "Compiled profile %r: fragments=%d documents=%d rules=%d mode=%s",
        resolved.name,
        sum(len(fragments) for fragments in resolved.fragments.values()),
        len(compiled.documents),
        len(compiled.rules),
        "yolo" if yolo else "full",
    )
    srt = compiled.srt_result
    config.network_config = srt.network_config
    config.filesystem_config = srt.filesystem_config
    config.sandbox_config = srt.sandbox_config
    config.srt_sandbox_enabled = srt.sandbox_config.get("enabled")
    config.yolo = yolo
    config.apply_sandbox_overrides()
    return config, compiled


def _select_generators(agent: str, config: AppConfig, for_write: bool) -> list:
    from twsrt.lib.agent import GENERATORS

    if agent == "all":
        generators = list(GENERATORS.values())
        if for_write and not config.codex_targets_configured:
            generators = [
                generator for generator in generators if generator.name != "codex"
            ]
        return generators
    if agent not in GENERATORS:
        raise ValueError(f"Unknown agent {agent!r}. Available: {', '.join(GENERATORS)}")
    return [GENERATORS[agent]]


def _stage_agent_files(
    generators: list,
    rendered: dict[str, str],
    compiled: CompilationResult,
    config: AppConfig,
) -> dict[Path, str]:
    from twsrt.lib.claude import selective_merge
    from twsrt.lib.codex import CodexGenerator

    staged: dict[Path, str] = {}
    for generator in generators:
        if generator.name == "claude":
            target = _resolve_claude_target(config)
            existing = target
            anchor = config.symlink_anchor
            if anchor.exists() and not anchor.is_symlink() and target.exists():
                raise FileExistsError(
                    f"both {anchor} (regular file) and {target} exist. "
                    "Remove one before running generate -w."
                )
            if not existing.exists() and anchor.exists() and not anchor.is_symlink():
                existing = anchor
            generated = json.loads(rendered[generator.name])
            donor = _resolve_sync_donor(config, target)
            if donor is not None:
                _info(f"Synced invariant settings from {donor.name}")
            if existing.exists() or donor is not None:
                document = selective_merge(
                    existing if existing.exists() else None,
                    generated,
                    donor=donor,
                    mode_specific=(
                        config.claude_sync.mode_specific if config.claude_sync else ()
                    ),
                )
            else:
                document = generated
            staged[target] = json.dumps(document, indent=2) + "\n"
        elif generator.name == "copilot":
            target = _resolve_copilot_target(config)
            if target is not None:
                staged[target] = rendered[generator.name] + "\n"
        elif generator.name == "codex":
            assert isinstance(generator, CodexGenerator)
            staged.update(generator.render_write_files(compiled.rules, config))
    return staged


def _resolve_sync_donor(config: AppConfig, target: Path) -> Path | None:
    """The file settings.json currently points to, if it should feed the target.

    Staging runs before ensure_symlink repoints the anchor, so the anchor still
    names the previous mode's file — the one Claude Code has been writing to.
    None when sync is disabled, the anchor is not a symlink (fresh install or
    migration), the link dangles, or it already points at the target.
    """
    if config.claude_sync is None:
        return None
    anchor = config.symlink_anchor
    if not anchor.is_symlink():
        return None
    donor = anchor.resolve()
    if not donor.exists() or donor == target.resolve():
        return None
    return donor


def _write_agent_files(staged: dict[Path, str], config: AppConfig) -> None:
    from twsrt.lib.symlink import ensure_symlink, prepare_claude_target

    claude_target = _resolve_claude_target(config)
    if claude_target in staged:
        migration_message = prepare_claude_target(config.symlink_anchor, claude_target)
        if migration_message:
            _info(migration_message)
    for path, content in staged.items():
        _atomic_write(path, content)
    if claude_target in staged:
        warning = ensure_symlink(claude_target, config.symlink_anchor)
        if warning:
            _warning(warning)


def _print_generator_warnings(
    generators: list, compiled: CompilationResult, config: AppConfig
) -> None:
    for generator in generators:
        warnings = generator.compatibility_warnings(compiled.rules, config)
        log.debug(
            "Compatibility warnings agent=%s count=%d", generator.name, len(warnings)
        )
        for warning in warnings:
            _warning(warning)


def _resolve_claude_target(config: AppConfig) -> Path:
    if config.yolo:
        return config.claude_yolo_path or yolo_path(config.claude_settings_path)
    return config.claude_settings_path


def _resolve_copilot_target(config: AppConfig) -> Path | None:
    if config.yolo:
        if config.copilot_yolo_path:
            return config.copilot_yolo_path
        if config.copilot_output_path:
            return yolo_path(config.copilot_output_path)
        return None
    return config.copilot_output_path


def _resolve_diff_target(name: str, config: AppConfig) -> Path | None:
    if name == "claude":
        return _resolve_claude_target(config)
    if name == "copilot":
        return _resolve_copilot_target(config)
    if name == "codex":
        return config.codex_config_path
    return None


def _resolve_editor() -> str:
    """Resolve the editor exactly like twagent: $EDITOR, then vi."""
    return os.environ.get("EDITOR") or "vi"


def _serialize(document: dict) -> str:
    from twsrt.lib.sources import serialize_document

    return serialize_document(document)


def _read_json_object(path: Path) -> dict | None:
    if not path.exists():
        return None
    try:
        value = json.loads(path.read_text())
    except json.JSONDecodeError:
        log.debug("Canonical target is not valid JSON: %s", path)
        return None
    return value if isinstance(value, dict) else None


def _atomic_write(path: Path, content: str) -> None:
    log.debug("Writing target path=%s", path)
    path.parent.mkdir(parents=True, exist_ok=True)
    descriptor, temporary = tempfile.mkstemp(dir=path.parent, prefix=f".{path.name}.")
    try:
        with os.fdopen(descriptor, "w") as file:
            file.write(content)
        os.replace(temporary, path)
    except BaseException:
        try:
            os.unlink(temporary)
        except FileNotFoundError:
            pass
        raise


@app.command(hidden=True)
def version() -> None:
    """Print version string."""
    typer.echo(f"twsrt version: {__version__}")


if __name__ == "__main__":
    app()
