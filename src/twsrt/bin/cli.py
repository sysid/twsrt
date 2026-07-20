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

__version__ = "0.8.0"

app = typer.Typer(
    name="twsrt",
    help="Agent security configuration generator.",
    no_args_is_help=True,
)
log = logging.getLogger("twsrt")


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
    if verbose:
        logging.basicConfig(level=logging.DEBUG)
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
#   allowWrite, denyWrite, denyRead
#
# WARNING: a nested [sandbox_overrides.<mode>.network] or .filesystem table
# replaces that entire compiled section because overrides are shallow. Configure
# those keys in SRT JSONC fragments unless complete replacement is intentional.

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
# denyWrite = ["**/.env"]
# denyRead = ["~/.ssh"]

[sandbox_overrides.full]
# Full mode retains interactive approval, so this profile intentionally disables
# the agent's native sandbox. Remove this override to inherit SRT's enabled value.
enabled = false

# The same seven top-level and ten nested keys documented above are valid here.
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
            typer.echo(f"Config not found: {target}. Use --init to create.", err=True)
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
        typer.echo(f"Editor not found: {editor}", err=True)
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
        rendered = {
            generator.name: generator.generate(compiled.rules, config)
            for generator in generators
        }
        staged = (
            _stage_agent_files(generators, rendered, compiled, config) if write else {}
        )
    except (FileExistsError, FileNotFoundError, ValueError) as exc:
        typer.echo(f"Error: {exc}", err=True)
        raise typer.Exit(1)

    _print_codex_warnings(generators, compiled, config)
    if write and dry_run:
        for document in compiled.documents.values():
            typer.echo(f"Would write canonical: {document.output_path}")
        for path in staged:
            typer.echo(f"Would write agent target: {path}")
        for name, output in rendered.items():
            typer.echo(f"--- Dry run: {name} ---")
            typer.echo(output)
        return

    if write:
        for document in compiled.documents.values():
            _atomic_write(document.output_path, _serialize(document.document))
            typer.echo(f"Wrote canonical: {document.output_path}")
        _write_agent_files(staged, config)
        for path in staged:
            typer.echo(f"Wrote: {path}")
        if "codex" in rendered:
            typer.echo(
                "Restart Codex to load the updated permission profile and rules."
            )
        for generator in generators:
            if generator.name == "copilot" and _resolve_copilot_target(config) is None:
                typer.echo(rendered[generator.name])
        return

    for name, output in rendered.items():
        if len(rendered) > 1:
            typer.echo(f"--- {name} ---")
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
        typer.echo(f"Error: {exc}", err=True)
        raise typer.Exit(1)

    has_drift = False
    for kind, document in compiled.documents.items():
        actual = _read_json_object(document.output_path)
        if actual == document.document:
            typer.echo(f"{kind} canonical: no drift")
        else:
            has_drift = True
            typer.echo(f"{kind} canonical: drift")

    for generator in generators:
        target = _resolve_diff_target(generator.name, config)
        if target is None or not target.exists():
            typer.echo(
                f"Error: Target file not found for {generator.name}: {target}", err=True
            )
            raise typer.Exit(2)
        if (
            generator.name == "codex"
            and config.codex_rules_path is not None
            and not config.codex_rules_path.exists()
        ):
            typer.echo(
                f"Error: Target file not found for codex: {config.codex_rules_path}",
                err=True,
            )
            raise typer.Exit(2)
        try:
            result = generator.diff(compiled.rules, target, config)
        except ValueError as exc:
            typer.echo(f"Error: {exc}", err=True)
            raise typer.Exit(1)
        if result.matched:
            typer.echo(f"{generator.name}: no drift")
        else:
            has_drift = True
            typer.echo(
                f"{generator.name}: {len(result.missing)} missing, "
                f"{len(result.extra)} extra"
            )
            for entry in result.missing:
                typer.echo(f"  + {entry} (missing from existing)")
            for entry in result.extra:
                typer.echo(f"  - {entry} (in existing, not in sources)")
        if generator.name == "codex":
            from twsrt.lib.codex import SILENT_DEACTIVATION_WARNING

            typer.echo(f"Warning: {SILENT_DEACTIVATION_WARNING}", err=True)

    if has_drift:
        raise typer.Exit(1)


def _compile(
    config_path: Path, profile_name: str | None, yolo: bool
) -> tuple[AppConfig, CompilationResult]:
    from twsrt.lib.config import load_config
    from twsrt.lib.profiles import resolve_profile
    from twsrt.lib.sources import compile_sources

    config = load_config(config_path)
    compiled = compile_sources(config, resolve_profile(config, profile_name))
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
            document = (
                selective_merge(existing, generated) if existing.exists() else generated
            )
            staged[target] = json.dumps(document, indent=2) + "\n"
        elif generator.name == "copilot":
            target = _resolve_copilot_target(config)
            if target is not None:
                staged[target] = rendered[generator.name] + "\n"
        elif generator.name == "codex":
            assert isinstance(generator, CodexGenerator)
            staged.update(generator.render_write_files(compiled.rules, config))
    return staged


def _write_agent_files(staged: dict[Path, str], config: AppConfig) -> None:
    from twsrt.lib.symlink import ensure_symlink, prepare_claude_target

    claude_target = _resolve_claude_target(config)
    if claude_target in staged:
        migration_message = prepare_claude_target(config.symlink_anchor, claude_target)
        if migration_message:
            typer.echo(migration_message)
    for path, content in staged.items():
        _atomic_write(path, content)
    if claude_target in staged:
        ensure_symlink(claude_target, config.symlink_anchor)


def _print_codex_warnings(
    generators: list, compiled: CompilationResult, config: AppConfig
) -> None:
    from twsrt.lib.codex import CodexGenerator

    if not any(generator.name == "codex" for generator in generators):
        return
    for warning in CodexGenerator().compatibility_warnings(config, compiled.rules):
        typer.echo(f"Warning: {warning}", err=True)
    typer.echo(
        "Warning: Codex execution rules apply only to requests to run outside "
        "the sandbox.",
        err=True,
    )


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
        return None
    return value if isinstance(value, dict) else None


def _atomic_write(path: Path, content: str) -> None:
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
