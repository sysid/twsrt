"""Fail when doctor's _SRT_SCHEMA_KEYS drifts from the installed srt's schema.

Compares the top-level, network.* and filesystem.* key names printed by
scripts/srt-schema.mjs with the hand-copied table in twsrt.lib.doctor.
Run inside the project env (`make srt-schema-check`), not as a uv --script:
it imports twsrt to read the table it checks.
Usage: uv run python scripts/srt-schema-check.py [--pin VERSION]

--pin (the Makefile's SRT_VERSION) first checks that the installed srt is the
pinned one: the key table claims that version, so a check against any other
would bless or flag the wrong schema.

ponytail: compares key names only. A changed type, a newly required key or a
new entry form (e.g. 0.0.83's {path, literal} path entries) passes silently;
the REFERENCE "After an srt upgrade" checklist covers those by hand.
"""

import argparse
import shutil
import subprocess
import sys
from collections.abc import Sequence
from pathlib import Path

from twsrt.lib.doctor import _SRT_SCHEMA_KEYS, _TWSRT_ONLY_SRT_KEYS
from twsrt.lib.probe import _srt_version

DUMP = Path(__file__).parent / "srt-schema.mjs"


def schema_keys(tree: str) -> dict[str, set[str]]:
    """The key names per section of a srt-schema.mjs tree, as doctor groups them."""
    keys: dict[str, set[str]] = {"": set()}
    parent = ""
    for line in tree.splitlines():
        if not line.strip():
            continue
        indent = len(line) - len(line.lstrip(" "))
        key = line.strip().split(":", 1)[0]
        if indent == 0:
            keys[""].add(key)
            parent = key
        elif indent == 2 and parent in ("network", "filesystem"):
            keys.setdefault(parent, set()).add(key)
    return keys


def _dotted(section: str, key: str) -> str:
    return f"{section}.{key}" if section else key


def drift(
    schema: dict[str, set[str]],
    known: dict[str, set[str]],
    twsrt_only: set[tuple[str, str]],
) -> list[str]:
    """One line per key that srt and twsrt disagree on, sorted."""
    problems = []
    for section in sorted(schema.keys() | known.keys()):
        in_srt = schema.get(section, set())
        in_twsrt = known.get(section, set())
        problems += [
            f"new in srt, add to _SRT_SCHEMA_KEYS: {_dotted(section, key)}"
            for key in sorted(in_srt - in_twsrt)
        ]
        problems += [
            f"gone from srt, remove from _SRT_SCHEMA_KEYS: {_dotted(section, key)}"
            for key in sorted(in_twsrt - in_srt)
            if (section, key) not in twsrt_only
        ]
    return problems


def installed_version() -> str:
    """The installed srt's version, read as `twsrt test` reads it."""
    return _srt_version(subprocess.run, shutil.which)


def pin_mismatch(installed: str, pinned: str) -> str | None:
    """Why the installed srt cannot be checked against the pinned table, if so."""
    if installed == pinned:
        return None
    return (
        f"installed srt {installed} is not the pinned {pinned}: run `make install-srt`, "
        f"or pass SRT_VERSION={installed} while upgrading"
    )


def main(argv: Sequence[str] = ()) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--pin", help="srt version the key table claims")
    args = parser.parse_args(argv)
    if args.pin is not None:
        try:
            installed = installed_version()
        except (FileNotFoundError, subprocess.TimeoutExpired):
            # No srt on PATH: the version lookup falls back to running `srt`.
            print("srt not found on PATH (install: make install-srt)", file=sys.stderr)
            return 2
        mismatch = pin_mismatch(installed, args.pin)
        if mismatch:
            print(mismatch, file=sys.stderr)
            return 2
    try:
        tree = subprocess.run(
            ["node", str(DUMP)], check=True, capture_output=True, text=True
        ).stdout
    except FileNotFoundError:
        print("node not found on PATH; srt-schema.mjs needs it", file=sys.stderr)
        return 2
    except subprocess.CalledProcessError as exc:
        # The cause (srt missing, schema module moved) is only in node's stderr.
        print(f"srt schema dump failed:\n{exc.stderr}", file=sys.stderr)
        return 2
    problems = drift(schema_keys(tree), _SRT_SCHEMA_KEYS, _TWSRT_ONLY_SRT_KEYS)
    for problem in problems:
        print(problem)
    if not problems:
        print("srt schema keys match _SRT_SCHEMA_KEYS")
    return 1 if problems else 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
