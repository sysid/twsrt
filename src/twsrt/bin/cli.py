"""twsrt CLI — agent security configuration generator."""

from __future__ import annotations

import json
import logging
import os
import subprocess
from pathlib import Path
from typing import Optional

import typer

from twsrt.lib.models import AppConfig, yolo_path

__version__ = "0.4.3"

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


# Default config.toml content
DEFAULT_CONFIG_TOML = """\
[sources]
srt = "~/.srt-settings.json"
bash_rules = "~/.config/twsrt/bash-rules.json"

[targets]
claude_settings = "~/.claude/settings.full.json"
# copilot_output = "~/.config/twsrt/copilot-flags.txt"    # optional, stdout if omitted

# YOLO target overrides (optional — defaults to inserting .yolo before extension)
# claude_settings_yolo = "~/.claude/settings.yolo.json"
# copilot_output_yolo = "~/.config/twsrt/copilot-flags.yolo.txt"  # optional, stdout if omitted
"""

# Default bash-rules.json content
DEFAULT_BASH_RULES = json.dumps({"deny": [], "ask": []}, indent=2)


@app.command()
def init(
    force: bool = typer.Option(False, "--force", "-f", help="Overwrite existing files"),
    dir: Optional[Path] = typer.Option(
        None,
        "--dir",
        help="Target directory (default: ~/.config/twsrt)",
    ),
) -> None:
    """Initialize ~/.config/twsrt/ config directory with default files."""
    twsrt_dir = (dir or Path("~/.config/twsrt")).expanduser()
    twsrt_dir.mkdir(parents=True, exist_ok=True)

    config_file = twsrt_dir / "config.toml"
    bash_rules_file = twsrt_dir / "bash-rules.json"

    for filepath, content in [
        (config_file, DEFAULT_CONFIG_TOML),
        (bash_rules_file, DEFAULT_BASH_RULES),
    ]:
        if filepath.exists() and not force:
            typer.echo(f"  Exists, skipping: {filepath}")
        else:
            filepath.write_text(content)
            typer.echo(f"  Created: {filepath}")

    typer.echo("Init complete.")


@app.command()
def generate(
    ctx: typer.Context,
    agent: str = typer.Argument("all", help="Target agent: claude, copilot, or all"),
    write: bool = typer.Option(False, "--write", "-w", help="Write to target files"),
    dry_run: bool = typer.Option(
        False, "--dry-run", "-n", help="Show what would be written"
    ),
    yolo: bool = typer.Option(
        False, "--yolo", help="YOLO mode: deny-only config, no ask rules"
    ),
) -> None:
    """Generate agent-specific security config from canonical sources."""
    from twsrt.lib.agent import GENERATORS
    from twsrt.lib.claude import selective_merge
    from twsrt.lib.config import load_config
    from twsrt.lib.sources import read_bash_rules, read_srt

    config_path = ctx.obj["config_path"]
    config = load_config(config_path)

    try:
        srt_result = read_srt(config.srt_path)
        bash_rules = read_bash_rules(config.bash_rules_path)
    except (FileNotFoundError, ValueError) as e:
        typer.echo(f"Error: {e}", err=True)
        raise typer.Exit(1)

    all_rules = srt_result.rules + bash_rules
    config.network_config = srt_result.network_config
    config.filesystem_config = srt_result.filesystem_config
    config.sandbox_config = srt_result.sandbox_config
    config.yolo = yolo

    if agent == "all":
        generators = list(GENERATORS.values())
    elif agent in GENERATORS:
        generators = [GENERATORS[agent]]
    else:
        typer.echo(
            f"Error: Unknown agent '{agent}'. Available: {', '.join(GENERATORS)}",
            err=True,
        )
        raise typer.Exit(1)

    for gen in generators:
        output = gen.generate(all_rules, config)

        if write and not dry_run:
            if gen.name == "claude":
                target = _resolve_claude_target(config)
                anchor = config.symlink_anchor

                from twsrt.lib.symlink import (
                    ensure_symlink,
                    prepare_claude_target,
                )

                try:
                    migration_msg = prepare_claude_target(anchor, target)
                    if migration_msg:
                        typer.echo(migration_msg)
                except FileExistsError as e:
                    typer.echo(str(e), err=True)
                    raise typer.Exit(1)

                if target.exists():
                    generated = json.loads(output)
                    merged = selective_merge(target, generated)
                    target.write_text(json.dumps(merged, indent=2) + "\n")
                else:
                    target.parent.mkdir(parents=True, exist_ok=True)
                    target.write_text(output + "\n")

                ensure_symlink(target, anchor)

                typer.echo(f"Wrote: {target}")
            elif gen.name == "copilot":
                target = _resolve_copilot_target(config)
                if target:
                    target.parent.mkdir(parents=True, exist_ok=True)
                    target.write_text(output + "\n")
                    typer.echo(f"Wrote: {target}")
                else:
                    typer.echo(output)
        elif dry_run and write:
            typer.echo(f"--- Dry run: {gen.name} ---")
            if gen.name == "claude":
                typer.echo(f"Would write to: {_resolve_claude_target(config)}")
            elif gen.name == "copilot":
                target = _resolve_copilot_target(config)
                if target:
                    typer.echo(f"Would write to: {target}")
            typer.echo(output)
        else:
            if len(generators) > 1:
                typer.echo(f"--- {gen.name} ---")
            typer.echo(output)


def _resolve_claude_target(config: AppConfig) -> Path:
    """Resolve Claude target path: yolo path in yolo mode, standard otherwise."""
    if config.yolo:
        return config.claude_yolo_path or yolo_path(config.claude_settings_path)
    return config.claude_settings_path


def _resolve_copilot_target(config: AppConfig) -> Path | None:
    """Resolve Copilot target path: yolo path in yolo mode, standard otherwise."""
    if config.yolo:
        if config.copilot_yolo_path:
            return config.copilot_yolo_path
        if config.copilot_output_path:
            return yolo_path(config.copilot_output_path)
        return None
    return config.copilot_output_path


def _resolve_diff_target(gen_name: str, config: AppConfig) -> Path | None:
    """Resolve target path for diff: yolo path in yolo mode, standard otherwise."""
    if gen_name == "claude":
        return _resolve_claude_target(config)
    elif gen_name == "copilot":
        return _resolve_copilot_target(config)
    return None


@app.command()
def diff(
    ctx: typer.Context,
    agent: str = typer.Argument("all", help="Target agent: claude, copilot, or all"),
    yolo: bool = typer.Option(
        False, "--yolo", help="YOLO mode: diff against yolo-specific config files"
    ),
) -> None:
    """Compare generated config against existing agent config files."""
    from twsrt.lib.agent import GENERATORS
    from twsrt.lib.config import load_config
    from twsrt.lib.sources import read_bash_rules, read_srt

    config_path = ctx.obj["config_path"]
    config = load_config(config_path)

    try:
        srt_result = read_srt(config.srt_path)
        bash_rules = read_bash_rules(config.bash_rules_path)
    except (FileNotFoundError, ValueError) as e:
        typer.echo(f"Error: {e}", err=True)
        raise typer.Exit(1)

    all_rules = srt_result.rules + bash_rules
    config.network_config = srt_result.network_config
    config.filesystem_config = srt_result.filesystem_config
    config.sandbox_config = srt_result.sandbox_config
    config.yolo = yolo

    if agent == "all":
        generators = list(GENERATORS.values())
    elif agent in GENERATORS:
        generators = [GENERATORS[agent]]
    else:
        typer.echo(
            f"Error: Unknown agent '{agent}'. Available: {', '.join(GENERATORS)}",
            err=True,
        )
        raise typer.Exit(1)

    has_drift = False
    for gen in generators:
        target = _resolve_diff_target(gen.name, config)
        if target is None or not target.exists():
            typer.echo(
                f"Error: Target file not found for {gen.name}: {target}", err=True
            )
            raise typer.Exit(2)

        result = gen.diff(all_rules, target, config)

        if result.matched:
            typer.echo(f"{gen.name}: no drift")
        else:
            has_drift = True
            typer.echo(
                f"{gen.name}: {len(result.missing)} missing, {len(result.extra)} extra"
            )
            for entry in result.missing:
                typer.echo(f"  + {entry} (missing from existing)")
            for entry in result.extra:
                typer.echo(f"  - {entry} (in existing, not in sources)")

    if has_drift:
        raise typer.Exit(1)


def _resolve_editor() -> str:
    """Resolve editor: $EDITOR → $VISUAL → vi."""
    return os.environ.get("EDITOR") or os.environ.get("VISUAL") or "vi"


# Canonical source short names mapped to AppConfig field names
_SOURCE_NAMES = ("srt", "bash")


@app.command()
def edit(
    ctx: typer.Context,
    source: Optional[str] = typer.Argument(None, help="Source to edit: srt, bash"),
) -> None:
    """Open a canonical source file in your editor."""
    from twsrt.lib.config import load_config

    config = load_config(ctx.obj["config_path"])
    sources = {
        "srt": config.srt_path,
        "bash": config.bash_rules_path,
    }

    if source is None:
        typer.echo(f"Available sources: {', '.join(sources)}")
        raise typer.Exit(0)

    if source not in sources:
        typer.echo(
            f"Error: Unknown source '{source}'. Available: {', '.join(sources)}",
            err=True,
        )
        raise typer.Exit(1)

    path = sources[source]
    if not path.exists():
        typer.echo(f"Error: File not found: {path}", err=True)
        raise typer.Exit(1)

    editor = _resolve_editor()
    result = subprocess.run([editor, str(path)])
    if result.returncode != 0:
        typer.echo(f"Warning: Editor exited with code {result.returncode}", err=True)
        raise typer.Exit(result.returncode)


@app.command(hidden=True)
def version() -> None:
    """Print version string."""
    typer.echo(f"twsrt version: {__version__}")


if __name__ == "__main__":
    app()
