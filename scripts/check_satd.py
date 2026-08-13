#!/usr/bin/env python3
"""Self-admitted technical debt gate.

Fails the build when the register and the source disagree about which debt exists.

Two directions, both of which matter:

  orphan comment   a ``TODO(TD-nn)`` in source with no row in the register.
                   Someone admitted debt and did not record it.

  orphan entry     a live row in the register with no ``TODO(TD-nn)`` anywhere in source.
                   Either the debt was repaid and the row was never struck through, or it was
                   never real. Both are worth catching: a register that overstates debt is as
                   misleading as one that hides it.

Rows struck through in the register (``~~TD-01~~``) are *resolved* and are expected to have no
source tag. They are not checked in either direction.

Usage::

    python scripts/check_satd.py            # from the repository root
    python scripts/check_satd.py --list     # print what was found, then check
"""

from __future__ import annotations

import argparse
import re
import sys
from pathlib import Path

REGISTER = Path("docs/TECHNICAL_DEBT.md")

SEARCH_ROOTS = (Path("backend"), Path("frontend/src"), Path("scripts"))
SEARCH_SUFFIXES = {".py", ".ts", ".tsx", ".js", ".jsx", ".yml", ".yaml"}
SKIP_DIRS = {
    ".git", ".venv", "venv", "__pycache__", "node_modules",
    ".pytest_cache", ".mypy_cache", "dist", "build", ".ruff_cache",
}

# A debt tag in a comment, anywhere on a line. Written here split so the checker does not
# admit debt it does not have: "TODO" "(TD-nn)".
SOURCE_TAG = re.compile(r"TODO\(\s*(TD-\d{2})\s*\)")
# A leading table cell: | TD-07 | ...   (resolved rows are ~~TD-01~~ and are matched separately)
REGISTER_LIVE = re.compile(r"^\|\s*(TD-\d{2})\s*\|")
REGISTER_RESOLVED = re.compile(r"^\|\s*~~\s*(TD-\d{2})\s*~~\s*\|")


def iter_source_files() -> list[Path]:
    files: list[Path] = []
    for root in SEARCH_ROOTS:
        if not root.exists():
            continue
        for path in root.rglob("*"):
            if path.suffix not in SEARCH_SUFFIXES:
                continue
            if any(part in SKIP_DIRS for part in path.parts):
                continue
            files.append(path)
    return sorted(files)


def scan_source() -> dict[str, list[str]]:
    """Map each debt ID to the ``path:line`` locations that admit it."""
    found: dict[str, list[str]] = {}
    for path in iter_source_files():
        try:
            text = path.read_text(encoding="utf-8")
        except (UnicodeDecodeError, OSError):
            continue
        for lineno, line in enumerate(text.splitlines(), start=1):
            for debt_id in SOURCE_TAG.findall(line):
                found.setdefault(debt_id, []).append(f"{path.as_posix()}:{lineno}")
    return found


def scan_register() -> tuple[set[str], set[str]]:
    """Return ``(live_ids, resolved_ids)`` from the register table."""
    if not REGISTER.exists():
        sys.exit(f"FAIL  register not found at {REGISTER} (run me from the repository root)")
    live: set[str] = set()
    resolved: set[str] = set()
    for line in REGISTER.read_text(encoding="utf-8").splitlines():
        if match := REGISTER_RESOLVED.match(line):
            resolved.add(match.group(1))
        elif match := REGISTER_LIVE.match(line):
            live.add(match.group(1))
    if not live and not resolved:
        sys.exit(f"FAIL  no debt rows parsed from {REGISTER}; has the table format changed?")
    return live, resolved


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--list", action="store_true", help="print every tag found before checking")
    args = parser.parse_args()

    in_source = scan_source()
    live, resolved = scan_register()

    if args.list:
        print(f"register:  {len(live)} live, {len(resolved)} resolved")
        for debt_id in sorted(in_source):
            print(f"  {debt_id}  {', '.join(in_source[debt_id])}")
        print()

    problems: list[str] = []

    for debt_id in sorted(set(in_source) - live):
        where = ", ".join(in_source[debt_id])
        if debt_id in resolved:
            problems.append(
                f"{debt_id} is marked resolved in the register but is still admitted in source "
                f"({where}). Remove the comment, or reopen the row."
            )
        else:
            problems.append(
                f"{debt_id} is admitted in source ({where}) but has no row in {REGISTER}. "
                f"Add it, with a cause, an impact and a repayment plan."
            )

    for debt_id in sorted(live - set(in_source)):
        problems.append(
            f"{debt_id} has a live row in {REGISTER} but no TODO({debt_id}) anywhere in source. "
            f"Either tag the code it applies to, or strike the row through if it was repaid."
        )

    if problems:
        print("FAIL  the technical-debt register and the source disagree.\n")
        for problem in problems:
            print(f"  - {problem}")
        print(f"\n{len(problems)} problem(s). See {REGISTER}.")
        return 1

    print(
        f"OK  {len(live)} live debt item(s), {len(resolved)} resolved, "
        f"all consistent between source and {REGISTER}."
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
