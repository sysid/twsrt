"""Compile canonical twsrt rules into Copilot's native sandbox policy (ADR 0009).

One builder serves both Copilot surfaces: the CLI (`~/.copilot/settings.json`) and
JetBrains IDEs (`github-copilot.xml`). Renderers only map field names.
"""

from __future__ import annotations

import glob
import os
from dataclasses import dataclass, field
from pathlib import Path

from twsrt.lib.codex import _classify_path, _has_glob
from twsrt.lib.models import Action, AppConfig, Scope, SecurityRule


SOFTWARE_ONLY_WARNING = (
    "Copilot confines shell, MCP and LSP processes at OS level; its in-process "
    "file tools and web fetch are checked in software only (ADR 0009)"
)
# Pass-through SRT fields (sources.py) with no Copilot setting.
_UNTRANSLATED_NETWORK_KEYS = (
    "allowUnixSockets",
    "allowAllUnixSockets",
    "allowMachLookup",
    "httpProxyPort",
    "socksProxyPort",
)
_UNTRANSLATED_SANDBOX_KEYS = (
    "enableWeakerNetworkIsolation",
    "enableWeakerNestedSandbox",
    "ignoreViolations",
)


@dataclass(frozen=True)
class SandboxPolicy:
    """Copilot sandbox content; every path list is absolute, deduplicated, sorted."""

    readwrite: list[str] = field(default_factory=list)
    readonly: list[str] = field(default_factory=list)
    denied: list[str] = field(default_factory=list)
    add_cwd: bool = False
    allowed_hosts: list[str] = field(default_factory=list)
    blocked_hosts: list[str] = field(default_factory=list)
    allow_outbound: bool = False
    allow_local_network: bool = False
    # CLI only: web-fetch URL rules, the former --allow-url/--deny-url values.
    allowed_urls: list[str] = field(default_factory=list)
    denied_urls: list[str] = field(default_factory=list)


def build_policy(
    rules: list[SecurityRule], config: AppConfig
) -> tuple[SandboxPolicy, list[str]]:
    """Translate rules into a policy plus warnings for every lossy mapping."""
    if config.srt_sandbox_enabled is False:
        raise ValueError(
            "Canonical SRT sandbox is disabled; refusing to generate a Copilot "
            "sandbox without restrictions"
        )
    warnings: list[str] = []
    denied: set[str] = set()
    readonly: set[str] = set()
    readwrite: set[str] = set()
    add_cwd = False
    skipped: set[str] = set()

    for rule in rules:
        if rule.scope not in (Scope.READ, Scope.WRITE):
            continue
        pattern = _strip_subtree_suffix(rule.pattern)
        is_allow = rule.scope == Scope.WRITE and rule.action == Action.ALLOW
        bucket = (
            readwrite if is_allow else denied if rule.scope == Scope.READ else readonly
        )

        normalized, relative = _classify_path(pattern)
        if relative:
            if is_allow and normalized in (".", ".git"):
                # Copilot grants the cwd (switch) and a repository's .git itself.
                add_cwd = add_cwd or normalized == "."
            else:
                skipped.add(rule.pattern)
        elif not _has_glob(pattern):
            bucket.add(_absolute(pattern))
        elif _is_bounded_glob(pattern):
            # srt's `*` matches dot-entries; glob's does not by default.
            matches = sorted(
                glob.glob(os.path.expanduser(pattern), include_hidden=True)
            )
            bucket.update(matches)
            warnings.append(
                f"Copilot paths have no wildcards: {rule.pattern} expanded to "
                f"{len(matches)} existing path(s) as a snapshot; regenerate when "
                "they change"
            )
        else:
            skipped.add(rule.pattern)

    # denyRead implies denyWrite (ADR 0001); a read-only entry would re-grant read.
    readonly -= denied
    readonly |= _target_files(config) - denied

    for path in sorted(readwrite & (denied | readonly)):
        warnings.append(
            f"Copilot read/write path {path} equals a denied or read-only path; "
            "kept the deny and skipped the read/write grant"
        )
    readwrite -= denied | readonly

    if skipped:
        warnings.append(
            "Copilot paths have no unbounded wildcards or cwd-relative form; "
            f"skipped {len(skipped)} entr(ies): " + ", ".join(sorted(skipped))
        )

    allowed = sorted({r.pattern for r in rules if _is_network(r, Action.ALLOW)})
    blocked = sorted({r.pattern for r in rules if _is_network(r, Action.DENY)})
    for domain in [*allowed, *blocked]:
        if _strip_port(domain) != domain:
            warnings.append(
                f"Copilot host rules take no port; {domain} applies to every port "
                f"as {_strip_port(domain)}"
            )
    local_network = config.network_config.get("allowLocalBinding") is True
    if local_network:
        warnings.append(
            "SRT allowLocalBinding only permits binding; Copilot allowLocalNetwork "
            "also permits connecting to loopback"
        )
    untranslated = sorted(
        [k for k in _UNTRANSLATED_NETWORK_KEYS if k in config.network_config]
        # The compiled srt fields, not sandbox_config: [sandbox_overrides.*]
        # target Claude and are no srt policy Copilot could miss.
        + [k for k in _UNTRANSLATED_SANDBOX_KEYS if k in config.srt_sandbox_config]
    )
    if untranslated:
        warnings.append(
            "Copilot has no equivalent for SRT fields (its own Seatbelt profile "
            "decides): " + ", ".join(untranslated)
        )
    warnings.append(SOFTWARE_ONLY_WARNING)

    policy = SandboxPolicy(
        readwrite=sorted(readwrite),
        readonly=sorted(readonly),
        denied=sorted(denied),
        add_cwd=add_cwd,
        allowed_hosts=sorted({_strip_port(d) for d in allowed}),
        blocked_hosts=sorted({_strip_port(d) for d in blocked}),
        # Copilot reads an empty allowlist as "no restriction", srt as "no
        # network": the empty case must switch outbound off.
        allow_outbound=bool(allowed),
        allow_local_network=local_network,
        allowed_urls=allowed,
        denied_urls=blocked,
    )
    return policy, warnings


def _is_network(rule: SecurityRule, action: Action) -> bool:
    return rule.scope == Scope.NETWORK and rule.action == action


def _strip_port(domain: str) -> str:
    host, sep, port = domain.rpartition(":")
    return host if sep and port.isdigit() and ":" not in host else domain


def _strip_subtree_suffix(pattern: str) -> str:
    """srt reads `dir/**` as `dir`; Copilot entries cover subtrees anyway."""
    stripped = pattern.removesuffix("/**")
    return stripped or pattern


def _absolute(pattern: str) -> str:
    path = os.path.expanduser(pattern)
    return path.rstrip("/") or "/"


def _is_bounded_glob(pattern: str) -> bool:
    """A wildcard below at least one literal component under `/` or `~`.

    ponytail: expansion is a generate-time snapshot; new matches stay unprotected
    until the next `generate -w` (warned).
    """
    if "**" in pattern:
        return False
    parts = Path(pattern).parts
    literal_below_root = 0
    for part in parts[1:]:  # parts[0] is "/" or "~"
        if _has_glob(part):
            return literal_below_root > 0
        literal_below_root += 1
    return False


def _target_files(config: AppConfig) -> set[str]:
    """Copilot's own config files, under the configured and the real spelling."""
    targets = [config.copilot_settings_path, *config.copilot_jetbrains_xml_paths]
    paths: set[str] = set()
    for target in targets:
        if target is None:
            continue
        paths.add(str(target))
        paths.add(str(target.resolve()))
    return paths
