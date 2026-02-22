"""Shared test fixtures for twsrt tests."""

import json
from pathlib import Path

import pytest


# --- Sample SRT JSON ---


SAMPLE_SRT = {
    "sandbox": {
        "enabled": True,
        "allowPty": True,
        "permissions": {
            "filesystem": {
                "read": {
                    "denyOnly": [
                        "**/.env",
                        "**/.env.*",
                        "**/.aws",
                        "~/.ssh",
                    ]
                },
                "write": {
                    "allowOnly": [".", "/tmp"],
                    "denyWithinAllow": [
                        "**/.env",
                        "**/*.pem",
                        "**/*.key",
                    ],
                },
            },
            "network": {
                "allowedHosts": [
                    "github.com",
                    "*.github.com",
                    "pypi.org",
                    "registry.npmjs.org",
                ]
            },
        },
    }
}


# --- Sample Bash Rules ---


SAMPLE_BASH_RULES = {
    "deny": ["rm", "sudo", "git push --force"],
    "ask": ["git push", "git commit", "pip install"],
}


# --- Sample Config TOML ---


SAMPLE_CONFIG_TOML = """\
[sources]
srt = "{srt_path}"
bash_rules = "{bash_rules_path}"

[targets]
claude_settings = "{claude_settings_path}"
"""


# --- Sample Claude settings.json ---


SAMPLE_CLAUDE_SETTINGS = {
    "permissions": {
        "allow": [
            "Read",
            "Glob",
            "Grep",
            "LS",
            "Task",
            "WebSearch",
            "WebFetch(domain:github.com)",
            "WebFetch(domain:pypi.org)",
            "mcp__memory__store",
            "Bash(./gradlew:*)",
        ],
        "deny": [
            "Bash(rm:*)",
            "Bash(sudo:*)",
            "Read(**/.aws/**)",
        ],
        "ask": [
            "Bash(git push)",
            "Bash(git push:*)",
        ],
    },
    "sandbox": {
        "network": {
            "allowedHosts": [
                "github.com",
                "pypi.org",
            ]
        }
    },
    "hooks": {
        "PreToolUse": [
            {"matcher": "Bash", "hooks": [{"type": "command", "command": "echo test"}]}
        ]
    },
    "additionalDirectories": ["/tmp/extra"],
}


# --- Fixtures ---


@pytest.fixture
def tmp_twsrt_dir(tmp_path: Path) -> Path:
    """Create an isolated ~/.twsrt/ equivalent for tests."""
    twsrt_dir = tmp_path / ".twsrt"
    twsrt_dir.mkdir()
    return twsrt_dir


@pytest.fixture
def srt_file(tmp_path: Path) -> Path:
    """Write sample SRT JSON to a temp file."""
    p = tmp_path / ".srt-settings.json"
    p.write_text(json.dumps(SAMPLE_SRT, indent=2))
    return p


@pytest.fixture
def bash_rules_file(tmp_twsrt_dir: Path) -> Path:
    """Write sample bash-rules.json to a temp file."""
    p = tmp_twsrt_dir / "bash-rules.json"
    p.write_text(json.dumps(SAMPLE_BASH_RULES, indent=2))
    return p


@pytest.fixture
def config_toml_file(
    tmp_twsrt_dir: Path,
    srt_file: Path,
    bash_rules_file: Path,
    tmp_path: Path,
) -> Path:
    """Write sample config.toml with correct paths."""
    claude_settings = tmp_path / ".claude" / "settings.json"
    claude_settings.parent.mkdir(parents=True, exist_ok=True)
    claude_settings.write_text(json.dumps(SAMPLE_CLAUDE_SETTINGS, indent=2))

    p = tmp_twsrt_dir / "config.toml"
    p.write_text(
        SAMPLE_CONFIG_TOML.format(
            srt_path=str(srt_file),
            bash_rules_path=str(bash_rules_file),
            claude_settings_path=str(claude_settings),
        )
    )
    return p


@pytest.fixture
def claude_settings_file(tmp_path: Path) -> Path:
    """Write sample Claude settings.json to a temp file."""
    p = tmp_path / ".claude" / "settings.json"
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(json.dumps(SAMPLE_CLAUDE_SETTINGS, indent=2))
    return p
