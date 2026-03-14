"""Symlink management for Claude settings files."""

import os
import shutil
import sys
import tempfile
from pathlib import Path


def ensure_symlink(target: Path, anchor: Path) -> None:
    """Create or update symlink from anchor → target (atomic).

    Uses relative path when target is in the same directory as anchor,
    absolute path otherwise. Atomic via temp symlink + os.replace().
    Falls back to direct copy on systems without symlink support (Windows).
    """
    if anchor.parent.resolve() == target.parent.resolve():
        link_value = target.name
    else:
        link_value = str(target.resolve())

    try:
        # Atomic: create temp symlink in same directory, then replace
        fd, tmp = tempfile.mkstemp(dir=anchor.parent)
        os.close(fd)
        os.remove(tmp)  # mkstemp creates a file; we need a symlink
        os.symlink(link_value, tmp)
        os.replace(tmp, str(anchor))
    except OSError:
        # Windows without Developer Mode or admin privileges
        print(
            f"Warning: cannot create symlink (unsupported OS). "
            f"Writing directly to {anchor} instead.",
            file=sys.stderr,
        )
        if anchor.resolve() != target.resolve():
            shutil.copy2(str(target), str(anchor))


def prepare_claude_target(anchor: Path, target: Path) -> str | None:
    """Handle migration logic before writing to target.

    Returns a migration message if a file was moved, None otherwise.
    Raises FileExistsError if both anchor (regular file) and target exist.
    """
    if not anchor.exists() and not anchor.is_symlink():
        # Anchor does not exist — nothing to do
        return None

    if anchor.is_symlink():
        # Already managed by twsrt — no migration needed
        return None

    # anchor is a regular file
    if target.exists():
        raise FileExistsError(
            f"Error: both {anchor} (regular file) and {target} exist. "
            f"Remove one before running generate -w."
        )

    # Move regular file to target
    target.parent.mkdir(parents=True, exist_ok=True)
    shutil.move(str(anchor), str(target))
    return f"Migrated: {anchor} → {target}"
