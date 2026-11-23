"""CopilotJetbrainsGenerator — the Copilot native sandbox in JetBrains IDEs.

Target: `<IDE config>/options/github-copilot.xml`, one per product and version
(ADR 0009). The option names, list elements and defaults come from plugin
1.21.1 (`CopilotApplicationState`); see the research doc §3.2.
"""

from __future__ import annotations

import xml.etree.ElementTree as ET
from pathlib import Path

from twsrt.lib.copilot_sandbox import SandboxPolicy, build_policy
from twsrt.lib.models import AppConfig, DiffResult, SecurityRule

_COMPONENT = "github-copilot"
# IntelliJ omits an option whose value equals its default when it saves, so
# diff compares effective values against these.
OPTION_DEFAULTS = {
    "sandboxEnabled": False,
    "sandboxAddCurrentWorkingDirectory": True,
    "sandboxGitAuth": True,
    "sandboxGhAuth": True,
    "sandboxAllowDevToolAccess": True,
    "sandboxMcpServers": True,
    "sandboxAllowBypass": False,
    "sandboxAllowOutboundNetwork": True,
    "sandboxAllowLocalNetwork": True,
    "sandboxKeychainAccess": False,
}
_LISTS = (
    "sandboxReadwritePaths",
    "sandboxReadonlyPaths",
    "sandboxDeniedPaths",
    "sandboxAllowedHosts",
    "sandboxBlockedHosts",
)
JETBRAINS_WARNINGS = (
    "JetBrains Copilot has no URL rules: its web fetch tool is not restricted "
    "by deniedUrls",
    "JetBrains Copilot has no LSP or extension sandbox switch",
    "JetBrains Copilot has no environment-variable masking (credentials.envVars)",
)


class CopilotJetbrainsGenerator:
    @property
    def name(self) -> str:
        return "copilot-jetbrains"

    def generate(self, rules: list[SecurityRule], config: AppConfig) -> str:
        """Preview: the owned options for every configured file."""
        fragment = ET.Element("component", name=_COMPONENT)
        _append_owned(fragment, self._values(rules, config))
        ET.indent(fragment)
        text = ET.tostring(fragment, encoding="unicode")
        return "\n".join(
            f"--- jetbrains: {path} (managed options) ---\n{text}"
            for path in config.copilot_jetbrains_xml_paths
        )

    def render_write_files(
        self, rules: list[SecurityRule], config: AppConfig
    ) -> dict[Path, str]:
        """Every configured XML with the owned options replaced."""
        options, lists = self._values(rules, config)
        files: dict[Path, str] = {}
        for path in config.copilot_jetbrains_xml_paths:
            root = _read(path)
            component = _component(root, create=True)
            assert component is not None
            for child in list(component):
                if child.get("name") in OPTION_DEFAULTS or child.tag in _LISTS:
                    component.remove(child)
            _append_owned(component, (options, lists))
            ET.indent(root)
            files[path] = ET.tostring(root, encoding="unicode") + "\n"
        return files

    def compatibility_warnings(
        self, rules: list[SecurityRule], config: AppConfig
    ) -> list[str]:
        if not config.copilot_jetbrains_xml_paths:
            return []
        return [*build_policy(rules, config)[1], *JETBRAINS_WARNINGS]

    def diff(
        self, rules: list[SecurityRule], target: Path, config: AppConfig
    ) -> DiffResult:
        """Effective values of owned options and lists, per configured file.

        `target` is the first configured file; every file is compared.
        """
        options, lists = self._values(rules, config)
        missing: list[str] = []
        extra: list[str] = []
        for path in config.copilot_jetbrains_xml_paths:
            if not path.exists():
                missing.append(str(path))
                continue
            component = _component(_read(path), create=False)
            for name, expected in options.items():
                element = None if component is None else _find_option(component, name)
                actual = (
                    OPTION_DEFAULTS[name]
                    if element is None
                    else element.get("value") == "true"
                )
                if actual != expected:
                    missing.append(f"{path}:{name}")
                    if element is not None:
                        extra.append(f"{path}:{name}")
            for tag, expected_values in lists.items():
                element = None if component is None else component.find(tag)
                actual_values = (
                    []
                    if element is None
                    else [o.get("value", "") for o in element.findall("option")]
                )
                if sorted(actual_values) != sorted(expected_values):
                    missing.append(f"{path}:{tag}")
                    if element is not None:
                        extra.append(f"{path}:{tag}")
        return DiffResult(
            agent=self.name,
            missing=sorted(missing),
            extra=sorted(extra),
            matched=not missing and not extra,
        )

    def _values(
        self, rules: list[SecurityRule], config: AppConfig
    ) -> tuple[dict[str, bool], dict[str, list[str]]]:
        policy: SandboxPolicy = build_policy(rules, config)[0]
        options = {
            "sandboxEnabled": True,
            "sandboxAddCurrentWorkingDirectory": policy.add_cwd,
            "sandboxGitAuth": True,
            "sandboxGhAuth": True,
            "sandboxAllowDevToolAccess": True,
            "sandboxMcpServers": True,
            "sandboxAllowBypass": False,
            "sandboxAllowOutboundNetwork": policy.allow_outbound,
            "sandboxAllowLocalNetwork": policy.allow_local_network,
            "sandboxKeychainAccess": False,
        }
        lists = {
            "sandboxReadwritePaths": policy.readwrite,
            "sandboxReadonlyPaths": policy.readonly,
            "sandboxDeniedPaths": policy.denied,
            "sandboxAllowedHosts": policy.allowed_hosts,
            "sandboxBlockedHosts": policy.blocked_hosts,
        }
        return options, lists


def _append_owned(
    component: ET.Element, values: tuple[dict[str, bool], dict[str, list[str]]]
) -> None:
    options, lists = values
    for name, value in options.items():
        # Written explicitly even when equal to the default (robust to changes).
        ET.SubElement(component, "option", name=name, value=str(value).lower())
    for tag, entries in lists.items():
        if not entries:
            continue  # the IDE omits empty lists too
        element = ET.SubElement(component, tag)
        for entry in entries:
            ET.SubElement(element, "option", value=entry)


def locked(xml: Path) -> bool:
    """True while the IDE owning `<config>/options/<xml>` runs (`<config>/.lock`).

    A running IDE overrides external edits to its options files (P7, Tom).

    ponytail: a lock left behind by a crashed or killed IDE reads as "running"
    and blocks every `-w` until removed (the skip warning says so). Upgrade
    path: check that the PID recorded in `.lock` is alive.
    """
    return (xml.parent.parent / ".lock").exists()


def _read(path: Path) -> ET.Element:
    if not path.exists():
        return ET.Element("application")
    try:
        # Keep comments: FR-032 preserves everything outside the owned options.
        parser = ET.XMLParser(target=ET.TreeBuilder(insert_comments=True))
        root = ET.fromstring(path.read_text(), parser=parser)
    except ET.ParseError as exc:
        raise ValueError(f"{path} is not well-formed XML: {exc}") from exc
    if root.tag != "application":
        raise ValueError(f"{path}: expected an <application> root, got <{root.tag}>")
    return root


def _component(root: ET.Element, create: bool) -> ET.Element | None:
    component = root.find(f"component[@name='{_COMPONENT}']")
    if component is None and create:
        component = ET.SubElement(root, "component", name=_COMPONENT)
    return component


def _find_option(component: ET.Element, name: str) -> ET.Element | None:
    return component.find(f"option[@name='{name}']")
