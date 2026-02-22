# Research: Edit Canonical Sources

## R-001: Editor Resolution Strategy

**Decision**: Resolve editor via `$EDITOR` → `$VISUAL` → `vi` fallback chain.

**Rationale**: This is the standard Unix convention. `$EDITOR` is the
preferred variable for line-oriented editors, `$VISUAL` for
screen-oriented editors. Most modern setups only set `$EDITOR`.
Falling back to `vi` is safe — it's available on all Unix systems.

**Alternatives considered**:
- `$EDITOR` only (no fallback): Too strict, fails on minimal systems where only `vi` is available
- Using `sensible-editor` (Debian): Not portable to macOS
- `open` (macOS): Launches GUI app, not appropriate for JSON editing in terminal

## R-002: Editor Launch Mechanism

**Decision**: Use `subprocess.run([editor, filepath])` and check return code.

**Rationale**: `subprocess.run` blocks until the editor closes, returns
the exit code, and is the standard Python approach. Using `os.execvp`
would replace the current process, preventing post-edit actions or
error reporting.

**Alternatives considered**:
- `os.execvp`: Replaces process, cannot report errors after editor closes
- `os.system`: Less secure, no structured return code handling
- `subprocess.Popen`: Unnecessary complexity for a blocking call

## R-003: Source Name Mapping

**Decision**: Use a simple dict mapping source short names to `AppConfig` path attributes.

**Rationale**: Only two sources exist (`srt`, `bash`). A dict literal
is the simplest correct approach. No registry, no dynamic discovery.

**Alternatives considered**:
- Enum-based mapping: Overengineered for two entries
- Dynamic attribute lookup on AppConfig: Fragile, ties naming to attribute names
