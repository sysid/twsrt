"""Tests for the JetBrains Copilot sandbox target (github-copilot.xml, ADR 0009)."""

import xml.etree.ElementTree as ET
from pathlib import Path

import pytest

from twsrt.lib.agent import GENERATORS
from twsrt.lib.copilot_jetbrains import CopilotJetbrainsGenerator
from twsrt.lib.models import Action, AppConfig, Scope, SecurityRule, Source

# Shape of a live IntelliJ 2026.2 file (plugin 1.21.1), values sanitized.
LIVE_XML = """<application>
  <component name="github-copilot">
    <option name="signinNotificationShown" value="true" />
    <option name="authenticationProvider" value="ghe.example.com" />
    <option name="sandboxEnabled" value="true" />
    <option name="sandboxProxyUrl" value="http://proxy.example:3128" />
    <sandboxReadonlyPaths>
      <option value="~/.copilot" />
    </sandboxReadonlyPaths>
    <terminalAutoApprove>
      <map>
        <entry key="rm" value="false" />
      </map>
    </terminalAutoApprove>
  </component>
  <component name="other-plugin">
    <option name="x" value="1" />
  </component>
</application>
"""


@pytest.fixture
def gen() -> CopilotJetbrainsGenerator:
    return CopilotJetbrainsGenerator()


def _rules() -> list[SecurityRule]:
    return [
        SecurityRule(Scope.READ, Action.DENY, "/secrets", Source.SRT_FILESYSTEM),
        SecurityRule(Scope.WRITE, Action.ALLOW, ".", Source.SRT_FILESYSTEM),
        SecurityRule(Scope.WRITE, Action.ALLOW, "/scratch", Source.SRT_FILESYSTEM),
        SecurityRule(Scope.NETWORK, Action.ALLOW, "github.com", Source.SRT_NETWORK),
        SecurityRule(Scope.NETWORK, Action.DENY, "pastebin.com", Source.SRT_NETWORK),
    ]


def _component(xml_text: str, name: str = "github-copilot") -> ET.Element:
    root = ET.fromstring(xml_text)
    component = root.find(f"component[@name='{name}']")
    assert component is not None
    return component


def _option(component: ET.Element, name: str) -> str | None:
    element = component.find(f"option[@name='{name}']")
    return None if element is None else element.get("value")


def _list(component: ET.Element, tag: str) -> list[str]:
    return [e.get("value", "") for e in component.findall(f"{tag}/option")]


class TestRegistration:
    def test_generator_is_registered_under_its_agent_name(self) -> None:
        """FR-030."""
        assert GENERATORS["copilot-jetbrains"].name == "copilot-jetbrains"


class TestRender:
    def test_policy_and_fixed_values_use_the_plugin_option_names(
        self, gen: CopilotJetbrainsGenerator, tmp_path: Path
    ) -> None:
        """FR-011, FR-031."""
        xml = tmp_path / "github-copilot.xml"
        config = AppConfig(copilot_jetbrains_xml_paths=[xml])

        files = gen.render_write_files(_rules(), config)

        component = _component(files[xml])
        assert _option(component, "sandboxEnabled") == "true"
        assert _option(component, "sandboxAddCurrentWorkingDirectory") == "true"
        assert _option(component, "sandboxGitAuth") == "true"
        assert _option(component, "sandboxGhAuth") == "true"
        assert _option(component, "sandboxAllowDevToolAccess") == "true"
        assert _option(component, "sandboxMcpServers") == "true"
        assert _option(component, "sandboxAllowBypass") == "false"
        assert _option(component, "sandboxAllowOutboundNetwork") == "true"
        assert _option(component, "sandboxAllowLocalNetwork") == "false"
        assert _option(component, "sandboxKeychainAccess") == "false"
        assert _list(component, "sandboxDeniedPaths") == ["/secrets"]
        assert _list(component, "sandboxReadwritePaths") == ["/scratch"]
        assert _list(component, "sandboxReadonlyPaths") == [str(xml)]
        assert _list(component, "sandboxAllowedHosts") == ["github.com"]
        assert _list(component, "sandboxBlockedHosts") == ["pastebin.com"]

    def test_serialized_form_matches_the_ide(
        self, gen: CopilotJetbrainsGenerator, tmp_path: Path
    ) -> None:
        """FR-031: self-closing options, two-space indent, no XML declaration."""
        xml = tmp_path / "github-copilot.xml"
        config = AppConfig(copilot_jetbrains_xml_paths=[xml])

        text = gen.render_write_files(_rules(), config)[xml]

        assert text.startswith('<application>\n  <component name="github-copilot">')
        assert '    <option name="sandboxEnabled" value="true" />' in text
        assert "<?xml" not in text

    def test_preview_names_each_file(
        self, gen: CopilotJetbrainsGenerator, tmp_path: Path
    ) -> None:
        first, second = tmp_path / "a.xml", tmp_path / "b.xml"
        config = AppConfig(copilot_jetbrains_xml_paths=[first, second])

        output = gen.generate(_rules(), config)

        assert str(first) in output and str(second) in output
        assert "sandboxDeniedPaths" in output


class TestMerge:
    def test_foreign_options_and_components_survive(
        self, gen: CopilotJetbrainsGenerator, tmp_path: Path
    ) -> None:
        """FR-032: only the owned options and lists are replaced."""
        xml = tmp_path / "github-copilot.xml"
        xml.write_text(LIVE_XML)
        config = AppConfig(copilot_jetbrains_xml_paths=[xml])

        merged = gen.render_write_files(_rules(), config)[xml]

        component = _component(merged)
        assert _option(component, "authenticationProvider") == "ghe.example.com"
        assert _option(component, "sandboxProxyUrl") == "http://proxy.example:3128"
        assert component.find("terminalAutoApprove/map/entry[@key='rm']") is not None
        assert _option(_component(merged, "other-plugin"), "x") == "1"
        assert _list(component, "sandboxReadonlyPaths") == [str(xml)]
        assert len(component.findall("option[@name='sandboxEnabled']")) == 1
        assert len(component.findall("sandboxReadonlyPaths")) == 1

    def test_xml_comments_survive(
        self, gen: CopilotJetbrainsGenerator, tmp_path: Path
    ) -> None:
        """FR-032: all other content is preserved, user comments included."""
        xml = tmp_path / "github-copilot.xml"
        xml.write_text(
            LIVE_XML.replace(
                "<terminalAutoApprove>",
                "<!-- rm stays manual -->\n    <terminalAutoApprove>",
            )
        )
        config = AppConfig(copilot_jetbrains_xml_paths=[xml])

        merged = gen.render_write_files(_rules(), config)[xml]

        assert "<!-- rm stays manual -->" in merged

    def test_missing_component_is_added(
        self, gen: CopilotJetbrainsGenerator, tmp_path: Path
    ) -> None:
        xml = tmp_path / "github-copilot.xml"
        xml.write_text('<application>\n  <component name="other" />\n</application>\n')
        config = AppConfig(copilot_jetbrains_xml_paths=[xml])

        merged = gen.render_write_files(_rules(), config)[xml]

        assert _option(_component(merged), "sandboxEnabled") == "true"
        assert _component(merged, "other") is not None

    def test_empty_list_is_omitted_like_the_ide_does(
        self, gen: CopilotJetbrainsGenerator, tmp_path: Path
    ) -> None:
        """An owned list with no entries leaves no element behind."""
        xml = tmp_path / "github-copilot.xml"
        xml.write_text(LIVE_XML)
        config = AppConfig(copilot_jetbrains_xml_paths=[xml])

        merged = gen.render_write_files([], config)[xml]

        assert _component(merged).find("sandboxBlockedHosts") is None

    @pytest.mark.parametrize("content", ["<application>", "<project />"])
    def test_malformed_or_foreign_xml_is_rejected(
        self, gen: CopilotJetbrainsGenerator, tmp_path: Path, content: str
    ) -> None:
        """FR-042: never overwrite a file twsrt cannot read back."""
        xml = tmp_path / "github-copilot.xml"
        xml.write_text(content)
        config = AppConfig(copilot_jetbrains_xml_paths=[xml])

        with pytest.raises(ValueError, match=str(xml)):
            gen.render_write_files(_rules(), config)


class TestDiff:
    """FR-034: compare effective values; the IDE drops default-valued options."""

    def test_freshly_written_file_has_no_drift(
        self, gen: CopilotJetbrainsGenerator, tmp_path: Path
    ) -> None:
        xml = tmp_path / "github-copilot.xml"
        config = AppConfig(copilot_jetbrains_xml_paths=[xml])
        xml.write_text(gen.render_write_files(_rules(), config)[xml])

        result = gen.diff(_rules(), xml, config)

        assert result.matched

    def test_options_the_ide_dropped_as_defaults_are_not_drift(
        self, gen: CopilotJetbrainsGenerator, tmp_path: Path
    ) -> None:
        """After an IDE save, options equal to their default disappear."""
        xml = tmp_path / "github-copilot.xml"
        config = AppConfig(copilot_jetbrains_xml_paths=[xml])
        text = gen.render_write_files(_rules(), config)[xml]
        for default_valued in (
            '    <option name="sandboxMcpServers" value="true" />\n',
            '    <option name="sandboxAllowBypass" value="false" />\n',
            '    <option name="sandboxGitAuth" value="true" />\n',
        ):
            assert default_valued in text
            text = text.replace(default_valued, "")
        xml.write_text(text)

        result = gen.diff(_rules(), xml, config)

        assert result.matched

    def test_local_network_default_is_on_so_its_absence_is_drift(
        self, gen: CopilotJetbrainsGenerator, tmp_path: Path
    ) -> None:
        """IntelliJ defaults sandboxAllowLocalNetwork to true, the CLI to false."""
        xml = tmp_path / "github-copilot.xml"
        config = AppConfig(copilot_jetbrains_xml_paths=[xml])
        text = gen.render_write_files(_rules(), config)[xml]
        text = text.replace(
            '    <option name="sandboxAllowLocalNetwork" value="false" />\n', ""
        )
        xml.write_text(text)

        result = gen.diff(_rules(), xml, config)

        assert result.missing == [f"{xml}:sandboxAllowLocalNetwork"]

    def test_changed_list_is_drift_per_file(
        self, gen: CopilotJetbrainsGenerator, tmp_path: Path
    ) -> None:
        good, bad = tmp_path / "a.xml", tmp_path / "b.xml"
        config = AppConfig(copilot_jetbrains_xml_paths=[good, bad])
        files = gen.render_write_files(_rules(), config)
        good.write_text(files[good])
        bad.write_text(files[bad].replace("/secrets", "/other"))

        result = gen.diff(_rules(), good, config)

        assert result.missing == [f"{bad}:sandboxDeniedPaths"]
        assert result.extra == [f"{bad}:sandboxDeniedPaths"]

    def test_missing_file_is_drift(
        self, gen: CopilotJetbrainsGenerator, tmp_path: Path
    ) -> None:
        xml = tmp_path / "github-copilot.xml"
        config = AppConfig(copilot_jetbrains_xml_paths=[xml])

        result = gen.diff(_rules(), xml, config)

        assert result.missing == [str(xml)]


class TestWarnings:
    def test_jetbrains_specific_gaps_are_warned(
        self, gen: CopilotJetbrainsGenerator, tmp_path: Path
    ) -> None:
        """FR-035 plus the shared builder warnings (FR-040)."""
        config = AppConfig(copilot_jetbrains_xml_paths=[tmp_path / "x.xml"])

        warnings = gen.compatibility_warnings([], config)

        text = "\n".join(warnings)
        assert "URL" in text
        assert "LSP" in text
        assert "environment" in text
        assert "in-process" in text
