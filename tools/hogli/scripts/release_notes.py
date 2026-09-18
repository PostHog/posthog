#!/usr/bin/env python3
"""Print one version's section of a Keep a Changelog file."""

from __future__ import annotations

import re
import sys
import argparse
from pathlib import Path

DEFAULT_CHANGELOG = Path(__file__).resolve().parent.parent / "CHANGELOG.md"


def extract_section(changelog: str, version: str) -> str:
    """Return the body under the ``## <version>`` heading, heading excluded.

    Accepts the Keep a Changelog heading variants: a bare version, a linked
    version, and either one followed by a release date.
    """
    heading = re.compile(rf"^##\s+\[?{re.escape(version)}\]?(\s|$)")
    body: list[str] = []
    in_section = False

    for line in changelog.splitlines():
        if in_section:
            if line.startswith("## "):
                break
            body.append(line)
        elif heading.match(line):
            in_section = True

    return "\n".join(body).strip()


def main() -> int:
    parser = argparse.ArgumentParser(description="Print one version's section of a changelog.")
    parser.add_argument("version", help="Version to extract, without a leading 'v'.")
    parser.add_argument("--changelog", type=Path, default=DEFAULT_CHANGELOG)
    args = parser.parse_args()

    section = extract_section(args.changelog.read_text(), args.version)
    if not section:
        sys.stderr.write(f"{args.changelog} has no section for version {args.version}\n")
        return 1

    sys.stdout.write(f"{section}\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
