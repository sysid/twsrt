# Research: Symlink-Based Config Management

## R1: Relative vs Absolute Symlinks in Python

**Decision**: Use `os.path.relpath()` when target is in same directory as anchor, absolute path otherwise.
**Rationale**: Relative symlinks are portable (survive home directory renames, dotfile syncing). `os.symlink()` accepts both relative and absolute targets. `os.path.relpath(target, anchor_dir)` computes the relative path.
**Alternatives considered**:
- Always absolute: simpler but breaks dotfile sync (e.g. chezmoi, stow)
- Always relative: fails when target is in a different directory tree

## R2: Atomic Symlink Update

**Decision**: Use `os.replace()` with a temporary symlink for atomic updates.
**Rationale**: `os.symlink()` fails if the path already exists. `os.remove()` + `os.symlink()` is not atomic — if the process dies between them, `settings.json` is gone. Instead: create temp symlink, then `os.replace(temp, anchor)` which is atomic on POSIX.
**Alternatives considered**:
- `os.remove()` + `os.symlink()`: not atomic, risk of dangling period
- `pathlib.Path.symlink_to()`: same non-atomic issue, no `replace` equivalent

**Implementation pattern**:
```python
import os
import tempfile

def atomic_symlink(target: Path, anchor: Path) -> None:
    """Atomically create/update a symlink."""
    link_value = _compute_link_value(target, anchor)
    # Create temp symlink in same directory (same filesystem for rename)
    fd, tmp = tempfile.mkstemp(dir=anchor.parent)
    os.close(fd)
    os.remove(tmp)  # mkstemp creates a file, we need a symlink
    os.symlink(link_value, tmp)
    os.replace(tmp, anchor)
```

## R3: Detecting Regular File vs Symlink

**Decision**: Use `Path.is_symlink()` to distinguish. This does NOT follow the symlink — it checks the path entry itself.
**Rationale**: `Path.exists()` follows symlinks (returns False for dangling symlinks). `Path.is_file()` follows symlinks. `Path.is_symlink()` checks the entry type without following.
**Alternatives considered**: `os.lstat()` — lower level, same result, less readable.

## R4: Windows Symlink Support

**Decision**: Catch `OSError` from `os.symlink()` and fall back to direct write with warning.
**Rationale**: Windows requires either admin privileges or Developer Mode for symlinks. Python's `os.symlink()` raises `OSError` when unavailable. Falling back to direct write (current behavior) is safe.
**Alternatives considered**:
- Hard links: can't cross filesystems, confusing semantics
- Junction points: Windows-only, overkill

## R5: Migration — Moving Regular File

**Decision**: Use `shutil.move()` to move `settings.json` → target path, then create symlink.
**Rationale**: `shutil.move()` handles cross-filesystem moves (copies then deletes). `os.rename()` fails across filesystems.
**Alternatives considered**: `Path.rename()` — same cross-filesystem limitation as `os.rename()`.

## R6: Init Config Template

**Decision**: Expand `DEFAULT_CONFIG_TOML` in cli.py to include all keys with comments.
**Rationale**: The init command already writes a hardcoded TOML string. Adding commented-out lines with explanatory text is the simplest approach.
**Alternatives considered**: Jinja2 template — overkill for a static string.
