"""Tests for symlink.py: ensure_symlink and prepare_claude_target."""

import os
from pathlib import Path

import pytest

from twsrt.lib.symlink import ensure_symlink, prepare_claude_target


class TestEnsureSymlink:
    """T002: Tests for ensure_symlink()."""

    def test_creates_relative_symlink_same_directory(self, tmp_path: Path) -> None:
        """When target and anchor are in the same directory, symlink is relative."""
        target = tmp_path / "settings.full.json"
        anchor = tmp_path / "settings.json"
        target.write_text("{}")

        ensure_symlink(target, anchor)

        assert anchor.is_symlink()
        # Relative link value (just the filename)
        link_value = os.readlink(str(anchor))
        assert link_value == "settings.full.json"
        # Resolves to target
        assert anchor.resolve() == target.resolve()

    def test_creates_absolute_symlink_different_directories(
        self, tmp_path: Path
    ) -> None:
        """When target and anchor are in different directories, symlink is absolute."""
        target_dir = tmp_path / "targets"
        target_dir.mkdir()
        target = target_dir / "settings.full.json"
        target.write_text("{}")

        anchor = tmp_path / "settings.json"

        ensure_symlink(target, anchor)

        assert anchor.is_symlink()
        link_value = os.readlink(str(anchor))
        # Should be absolute (or relative path containing directory component)
        assert "/" in link_value
        assert anchor.resolve() == target.resolve()

    def test_atomic_update_of_existing_symlink(self, tmp_path: Path) -> None:
        """Updating an existing symlink re-points it atomically."""
        full_target = tmp_path / "settings.full.json"
        yolo_target = tmp_path / "settings.yolo.json"
        anchor = tmp_path / "settings.json"
        full_target.write_text('{"mode": "full"}')
        yolo_target.write_text('{"mode": "yolo"}')

        # First: symlink to full
        ensure_symlink(full_target, anchor)
        assert anchor.resolve() == full_target.resolve()

        # Then: re-point to yolo
        ensure_symlink(yolo_target, anchor)
        assert anchor.resolve() == yolo_target.resolve()
        assert os.readlink(str(anchor)) == "settings.yolo.json"

    def test_idempotent_when_already_correct(self, tmp_path: Path) -> None:
        """Calling ensure_symlink when already correct is a no-op."""
        target = tmp_path / "settings.full.json"
        anchor = tmp_path / "settings.json"
        target.write_text("{}")

        ensure_symlink(target, anchor)

        ensure_symlink(target, anchor)
        # Should still be a valid symlink
        assert anchor.is_symlink()
        assert anchor.resolve() == target.resolve()


class TestPrepareclaudeTarget:
    """T003: Tests for prepare_claude_target()."""

    def test_noop_when_anchor_is_symlink(self, tmp_path: Path) -> None:
        """If anchor is already a symlink, prepare does nothing."""
        target = tmp_path / "settings.full.json"
        anchor = tmp_path / "settings.json"
        target.write_text("{}")
        anchor.symlink_to(target.name)

        # Should not raise or modify anything
        prepare_claude_target(anchor, target)

        assert anchor.is_symlink()
        assert target.read_text() == "{}"

    def test_moves_regular_file_when_target_missing(self, tmp_path: Path) -> None:
        """If anchor is a regular file and target does not exist, move it."""
        anchor = tmp_path / "settings.json"
        target = tmp_path / "settings.full.json"
        anchor.write_text('{"existing": true}')

        result_msg = prepare_claude_target(anchor, target)

        assert not anchor.exists() or anchor.is_symlink()
        assert target.exists()
        assert target.read_text() == '{"existing": true}'
        assert result_msg is not None  # Should return migration message

    def test_error_when_regular_file_and_target_exists(self, tmp_path: Path) -> None:
        """If anchor is a regular file AND target exists, raise error."""
        anchor = tmp_path / "settings.json"
        target = tmp_path / "settings.full.json"
        anchor.write_text('{"anchor": true}')
        target.write_text('{"target": true}')

        with pytest.raises(FileExistsError, match="both.*exist"):
            prepare_claude_target(anchor, target)

        # Neither file should have been modified
        assert anchor.read_text() == '{"anchor": true}'
        assert target.read_text() == '{"target": true}'

    def test_creates_parent_directories_for_target(self, tmp_path: Path) -> None:
        """prepare_claude_target creates parent dirs when moving."""
        anchor = tmp_path / "settings.json"
        target = tmp_path / "subdir" / "settings.full.json"
        anchor.write_text('{"existing": true}')

        result_msg = prepare_claude_target(anchor, target)

        assert target.exists()
        assert target.read_text() == '{"existing": true}'
        assert result_msg is not None

    def test_noop_when_anchor_does_not_exist(self, tmp_path: Path) -> None:
        """If anchor does not exist, prepare does nothing."""
        anchor = tmp_path / "settings.json"
        target = tmp_path / "settings.full.json"

        result_msg = prepare_claude_target(anchor, target)

        assert result_msg is None
        assert not anchor.exists()
        assert not target.exists()
