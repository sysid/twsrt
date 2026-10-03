"""Configuration diagnostics: correctness, redundancy, and pattern traps.

Correctness reuses the real pipeline (JSONC loading, profile resolution,
compilation) over every profile, so doctor never disagrees with `generate`.
Redundancy and trap checks are lint: they flag rules that work but do less
than they look, or nothing at all. Pattern semantics follow
thoughts/research/2026-10-02-srt-wildcard-semantics.md.
"""

from __future__ import annotations

import os
import json
from collections.abc import Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from twsrt.lib.jsonc import load as load_jsonc
from twsrt.lib.models import AppConfig, ResolvedProfile
from twsrt.lib.profiles import resolve_profile
from twsrt.lib.sources import compile_sources

SEVERITIES = ("error", "warning", "info")

# Lists whose entries are compared for duplicates and subsumption.
_PATH_LISTS = ("allowWrite", "denyWrite", "denyRead", "allowRead")
_DOMAIN_LISTS = ("allowedDomains", "deniedDomains")
_BASH_LISTS = ("allow", "ask", "deny")
_ALLOW_PATH_LISTS = ("allowWrite", "allowRead")


@dataclass(frozen=True)
class Finding:
    severity: str
    code: str
    message: str


def diagnose(
    config: AppConfig, base_dir: Path, claude_files: Sequence[Path] = ()
) -> list[Finding]:
    """Run every check; findings are deduplicated and ordered by severity.

    claude_files are Claude Code settings files to scan for relative
    sandbox.filesystem entries (the twsrt target and the repo's .claude/
    files); missing or unparseable files are skipped.
    """
    findings: list[Finding] = []
    loaded, broken = _load_fragments(config, base_dir, findings)
    resolved = _resolve_profiles(config, findings)
    _compile_profiles(config, resolved, broken, findings)
    _check_profile_structure(config, findings)
    _check_unused_fragments(config, findings)
    for profile in resolved.values():
        _check_profile_lists(profile, loaded, base_dir, findings)
    _check_patterns(config, loaded, base_dir, findings)
    _check_symlinked_denies(config, loaded, base_dir, findings)
    _check_broad_allow_write(config, loaded, base_dir, findings)
    _check_claude_files(claude_files, findings)

    unique = list(dict.fromkeys(findings))
    return sorted(unique, key=lambda finding: SEVERITIES.index(finding.severity))


# --- A. correctness -------------------------------------------------------


def _load_fragments(
    config: AppConfig, base_dir: Path, findings: list[Finding]
) -> tuple[dict[Path, dict[str, Any]], set[Path]]:
    """Parse every registered fragment once, used or not."""
    loaded: dict[Path, dict[str, Any]] = {}
    broken: set[Path] = set()
    for source in config.sources.values():
        for fragment in source.fragments.values():
            try:
                loaded[fragment.path] = load_jsonc(fragment.path)
            except (OSError, ValueError) as exc:
                broken.add(fragment.path)
                findings.append(
                    Finding(
                        "error",
                        "fragment-load",
                        f"{_show(fragment.path, base_dir)}: {exc}",
                    )
                )
    return loaded, broken


def _resolve_profiles(
    config: AppConfig, findings: list[Finding]
) -> dict[str, ResolvedProfile]:
    resolved: dict[str, ResolvedProfile] = {}
    for name in sorted(config.profiles):
        try:
            resolved[name] = resolve_profile(config, name)
        except ValueError as exc:
            # A mixin meant only for `extends` is legitimate, but -p NAME fails.
            findings.append(
                Finding(
                    "warning",
                    "profile-incomplete",
                    f"profile {name!r} cannot be used on its own: {exc}",
                )
            )
    return resolved


def _compile_profiles(
    config: AppConfig,
    resolved: dict[str, ResolvedProfile],
    broken: set[Path],
    findings: list[Finding],
) -> None:
    for name, profile in resolved.items():
        if any(
            fragment.path in broken
            for fragments in profile.fragments.values()
            for fragment in fragments
        ):
            continue  # already reported as fragment-load
        try:
            compile_sources(config, profile)
        except (OSError, ValueError) as exc:
            findings.append(
                Finding("error", "profile-compile", f"profile {name!r}: {exc}")
            )


# --- B. redundancy --------------------------------------------------------


def _check_profile_structure(config: AppConfig, findings: list[Finding]) -> None:
    for name in sorted(config.profiles):
        profile = config.profiles[name]
        for parent in profile.extends:
            via = [
                other
                for other in profile.extends
                if other != parent and parent in _ancestors(config, other)
            ]
            if via:
                findings.append(
                    Finding(
                        "warning",
                        "redundant-extends",
                        f"profile {name!r}: extends {parent!r} is already "
                        f"inherited via {via[0]!r}",
                    )
                )
        inherited = _inherited_selections(config, name)
        for kind, selected in profile.selections.items():
            for fragment in selected:
                owner = inherited.get((kind, fragment))
                if owner is not None:
                    findings.append(
                        Finding(
                            "warning",
                            "inherited-fragment",
                            f"profile {name!r}: {kind} fragment {fragment!r} is "
                            f"already inherited from {owner!r}",
                        )
                    )


def _ancestors(config: AppConfig, name: str) -> set[str]:
    found: set[str] = set()
    for parent in config.profiles[name].extends:
        found |= {parent, *_ancestors(config, parent)}
    return found


def _inherited_selections(config: AppConfig, name: str) -> dict[tuple[str, str], str]:
    """(kind, fragment) -> the ancestor profile that selects it."""
    owners: dict[tuple[str, str], str] = {}
    for ancestor in sorted(_ancestors(config, name)):
        for kind, selected in config.profiles[ancestor].selections.items():
            for fragment in selected:
                owners.setdefault((kind, fragment), ancestor)
    return owners


def _check_unused_fragments(config: AppConfig, findings: list[Finding]) -> None:
    used = {
        (kind, fragment)
        for profile in config.profiles.values()
        for kind, selected in profile.selections.items()
        for fragment in selected
    }
    for kind, source in config.sources.items():
        for fragment in source.fragments:
            if (kind, fragment) not in used:
                findings.append(
                    Finding(
                        "warning",
                        "unused-fragment",
                        f"{kind} fragment {fragment!r} is selected by no profile",
                    )
                )


def _check_profile_lists(
    profile: ResolvedProfile,
    loaded: dict[Path, dict[str, Any]],
    base_dir: Path,
    findings: list[Finding],
) -> None:
    """Duplicates and subsumption within the union a profile compiles to."""
    for kind, fragments in profile.fragments.items():
        lists = _profile_lists(kind, fragments, loaded)
        for list_name, values in lists.items():
            key = list_name.rsplit(".", 1)[-1]
            # Grouped per contributing fragment: one finding per file and list.
            covered: dict[Path, list[str]] = {}
            for value, origins in values.items():
                if len(origins) > 1:
                    shown = ", ".join(_show(path, base_dir) for path in origins)
                    findings.append(
                        Finding(
                            "warning",
                            "duplicate-rule",
                            f"{list_name}: {value!r} appears in {shown}",
                        )
                    )
                for other, other_origins in values.items():
                    if _covers(key, other, value):
                        where = (
                            ""
                            if other_origins[0] == origins[0]
                            else f" ({_show(other_origins[0], base_dir)})"
                        )
                        covered.setdefault(origins[0], []).append(
                            f"{value!r} by {other!r}{where}"
                        )
                        break
            for origin, items in covered.items():
                findings.append(
                    Finding(
                        "warning",
                        "subsumed-rule",
                        f"{_show(origin, base_dir)}: {list_name}: "
                        f"{_count(items, 'entry', 'entries')} already covered: "
                        + ", ".join(items),
                    )
                )
            if key == "allowedDomains":
                _check_wildcard_apex(list_name, values, base_dir, findings)


def _profile_lists(
    kind: str, fragments: list, loaded: dict[Path, dict[str, Any]]
) -> dict[str, dict[str, list[Path]]]:
    """list name -> value -> fragments contributing it, in profile order."""
    if kind == "srt":
        locations = [("filesystem", key) for key in _PATH_LISTS] + [
            ("network", key) for key in _DOMAIN_LISTS
        ]
    else:
        locations = [("", key) for key in _BASH_LISTS]
    lists: dict[str, dict[str, list[Path]]] = {}
    for fragment in fragments:
        document = loaded.get(fragment.path, {})
        for section, key in locations:
            container = document.get(section, {}) if section else document
            entries = container.get(key, []) if isinstance(container, dict) else []
            if not isinstance(entries, list):
                continue
            list_name = f"{section}.{key}" if section else key
            for entry in entries:
                if isinstance(entry, str):
                    origins = lists.setdefault(list_name, {}).setdefault(entry, [])
                    if fragment.path not in origins:
                        origins.append(fragment.path)
    return lists


def _covers(key: str, parent: str, child: str) -> bool:
    if parent == child:
        return False
    if key in _PATH_LISTS:
        return _path_covers(parent, child)
    if key in _DOMAIN_LISTS:
        return _domain_covers(parent, child)
    # Claude emits Bash(cmd) and Bash(cmd *): a rule covers longer commands.
    return child.startswith(parent + " ")


def _path_covers(parent: str, child: str) -> bool:
    normal_parent, normal_child = _normalize_path(parent), _normalize_path(child)
    if "*" in normal_parent:
        return False  # ponytail: glob coverage is not modelled
    if normal_parent == normal_child:
        # `dir` and `dir/**` compile to the same rule: flag only the longer
        # spelling, so an equivalent pair yields one finding, not two.
        return (len(child), child) > (len(parent), parent)
    if normal_parent == ".":
        return not normal_child.startswith(("/", "~"))
    return normal_child.startswith(normal_parent.rstrip("/") + "/")


def _normalize_path(value: str) -> str:
    """srt strips one trailing /**; compare ~ and absolute forms alike."""
    value = value.removesuffix("/**").removeprefix("./") or "."
    return os.path.expanduser(value) if value.startswith("~") else value


def _domain_covers(parent: str, child: str) -> bool:
    if ":" in parent or ":" in child:
        return False  # ponytail: port-qualified entries are not compared
    if parent == "*":
        return True
    # *.x.com matches subdomains at any depth, never the apex x.com.
    return parent.startswith("*.") and child.endswith(parent[1:])


def _check_wildcard_apex(
    list_name: str,
    values: dict[str, list[Path]],
    base_dir: Path,
    findings: list[Finding],
) -> None:
    """Grouped by the wildcard's fragment, so profiles sharing it dedup."""
    missing: dict[Path, list[str]] = {}
    for value, origins in values.items():
        if value.startswith("*.") and ":" not in value and value[2:] not in values:
            missing.setdefault(origins[0], []).append(f"{value!r} ({value[2:]})")
    for origin, items in missing.items():
        findings.append(
            Finding(
                "info",
                "wildcard-apex",
                f"{_show(origin, base_dir)}: {list_name}: "
                f"{_count(items, 'wildcard', 'wildcards')} not matching the bare "
                "apex domain (add it where needed): " + ", ".join(items),
            )
        )


# --- C. pattern traps -----------------------------------------------------


# code -> (severity, description after "<n> entries ..."), in check order.
_PATTERN_TRAPS = {
    "cwd-anchored-glob": (
        "warning",
        "anchored at the launch directory, not global",
    ),
    "narrow-allow-glob": (
        "warning",
        "granting only exact matches on macOS (dir/* = direct children, "
        "a/*/b = the directory b itself) and dropped on Linux; list "
        "directories instead",
    ),
    "linux-drops-write-glob": (
        "info",
        "dropped by srt on Linux, so the deny holds on macOS only",
    ),
    "noop-glob-suffix": (
        "info",
        "ending in /**, which srt strips; the bare directory is the same rule",
    ),
}


def _check_patterns(
    config: AppConfig,
    loaded: dict[Path, dict[str, Any]],
    base_dir: Path,
    findings: list[Finding],
) -> None:
    """One finding per fragment, list and trap, naming every affected entry."""
    for fragment in config.sources["srt"].fragments.values():
        filesystem = loaded.get(fragment.path, {}).get("filesystem", {})
        if not isinstance(filesystem, dict):
            continue
        where = _show(fragment.path, base_dir)
        for key in _PATH_LISTS:
            entries = filesystem.get(key, [])
            if not isinstance(entries, list):
                continue
            hits: dict[str, list[str]] = {}
            for entry in entries:
                if isinstance(entry, str):
                    code = _path_trap(key, entry)
                    if code is not None:
                        hits.setdefault(code, []).append(repr(entry))
            for code, (severity, description) in _PATTERN_TRAPS.items():
                if code in hits:
                    findings.append(
                        Finding(
                            severity,
                            code,
                            f"{where}: filesystem.{key}: "
                            f"{_count(hits[code], 'entry', 'entries')} "
                            f"{description}: " + ", ".join(hits[code]),
                        )
                    )


def _path_trap(key: str, entry: str) -> str | None:
    stem = entry.removesuffix("/**")
    if entry.startswith("**/"):
        return "cwd-anchored-glob"
    if "*" in stem and key in _ALLOW_PATH_LISTS:
        return "narrow-allow-glob"
    if "*" in stem and key == "denyWrite":
        return "linux-drops-write-glob"
    if entry.endswith("/**"):
        return "noop-glob-suffix"
    return None


def _count(items: list[str], singular: str, plural: str) -> str:
    return f"{len(items)} {singular if len(items) == 1 else plural}"


# --- D. checks added with ADR 0002 ----------------------------------------


def _srt_entries(
    config: AppConfig, loaded: dict[Path, dict[str, Any]], key: str
) -> list[tuple[Path, str]]:
    """(fragment path, entry) for one filesystem list across all srt fragments."""
    found: list[tuple[Path, str]] = []
    for fragment in config.sources["srt"].fragments.values():
        filesystem = loaded.get(fragment.path, {}).get("filesystem", {})
        entries = filesystem.get(key, []) if isinstance(filesystem, dict) else []
        if isinstance(entries, list):
            found += [(fragment.path, e) for e in entries if isinstance(e, str)]
    return found


def _concrete_path(entry: str) -> str | None:
    """Absolute expanded path of a non-glob ~ or / entry; None otherwise."""
    if "*" in entry or "?" in entry or "[" in entry:
        return None
    if not entry.startswith(("/", "~")):
        return None  # relative: anchored at a launch cwd unknown here
    return os.path.normpath(os.path.expanduser(entry.removesuffix("/**")))


def _check_symlinked_denies(
    config: AppConfig,
    loaded: dict[Path, dict[str, Any]],
    base_dir: Path,
    findings: list[Finding],
) -> None:
    """A deny on a symlinked path is a no-op unless its real path is denied too.

    srt keeps the unresolved spelling while Seatbelt matches the real vnode
    path (bkmr 3686); Claude folds the same paths into the same library.
    """
    for key in ("denyRead", "denyWrite"):
        entries = _srt_entries(config, loaded, key)
        listed = {path for _, e in entries if (path := _concrete_path(e))}
        hits: dict[Path, list[str]] = {}
        for origin, entry in entries:
            path = _concrete_path(entry)
            if path is None:
                continue
            real = os.path.realpath(path)
            if real == path:
                continue
            if any(real == item or real.startswith(item + "/") for item in listed):
                continue
            hits.setdefault(origin, []).append(f"{entry!r} (-> {real})")
        for origin, items in hits.items():
            findings.append(
                Finding(
                    "warning",
                    "symlinked-deny-path",
                    f"{_show(origin, base_dir)}: filesystem.{key}: "
                    f"{_count(items, 'entry', 'entries')} through a symlink; the "
                    "sandbox matches the real path, so list it too: "
                    + ", ".join(items),
                )
            )


def _broad_roots() -> list[str]:
    home = os.path.expanduser("~")
    return ["/", home, os.path.join(home, ".config"), os.path.join(home, "Library")]


def _check_broad_allow_write(
    config: AppConfig,
    loaded: dict[Path, dict[str, Any]],
    base_dir: Path,
    findings: list[Finding],
) -> None:
    """allowWrite on or above a broad root: with Claude Code (ADR 0002) every
    allowWrite path also auto-approves Claude's edit tools."""
    roots = _broad_roots()
    hits: dict[Path, list[str]] = {}
    for origin, entry in _srt_entries(config, loaded, "allowWrite"):
        path = _concrete_path(entry)
        if path is None:
            continue
        if any(
            root == path or root.startswith(path.rstrip("/") + "/") for root in roots
        ):
            hits.setdefault(origin, []).append(repr(entry))
    for origin, items in hits.items():
        findings.append(
            Finding(
                "warning",
                "broad-allow-write",
                f"{_show(origin, base_dir)}: filesystem.allowWrite: "
                f"{_count(items, 'entry', 'entries')} covering home, / or a config "
                "root; in Claude Code they also auto-approve edits (ADR 0002): "
                + ", ".join(items),
            )
        )


def _check_claude_files(claude_files: Sequence[Path], findings: list[Finding]) -> None:
    """Relative sandbox.filesystem entries anchor at the settings-file root.

    In ~/.claude/settings.json "." means ~/.claude, in a --settings file its
    directory (bkmr 3742). Read()/Edit() rules anchor at the launch cwd.
    """
    for path in dict.fromkeys(claude_files):
        try:
            data = json.loads(path.read_text())
        except (OSError, ValueError):
            continue
        sandbox = data.get("sandbox", {}) if isinstance(data, dict) else {}
        filesystem = sandbox.get("filesystem", {}) if isinstance(sandbox, dict) else {}
        if not isinstance(filesystem, dict):
            continue
        for key in ("allowWrite", "denyWrite", "denyRead", "allowRead"):
            entries = filesystem.get(key, [])
            if not isinstance(entries, list):
                continue
            relative = [
                repr(e)
                for e in entries
                if isinstance(e, str) and not e.startswith(("/", "~"))
            ]
            if relative:
                findings.append(
                    Finding(
                        "warning",
                        "claude-relative-sandbox-path",
                        f"{path}: sandbox.filesystem.{key}: "
                        f"{_count(relative, 'entry', 'entries')} anchored at the "
                        "settings-file root, not the launch directory; use "
                        "Read()/Edit() rules instead: " + ", ".join(relative),
                    )
                )


def _show(path: Path, base_dir: Path) -> str:
    try:
        return str(path.relative_to(base_dir))
    except ValueError:
        return str(path)
