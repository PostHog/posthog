"""Keeps the Depot CI mirrors of the local actions in sync with their canonical copies.

`.github/workflows/ci-depot-action-mirrors.yml` runs this file with the runner's python3 before any
dependency install, and `hogli ci:preflight` imports it, so it must stay standard library only.
"""

from __future__ import annotations

import re
import sys
import subprocess
from pathlib import Path

# These mirrors carry intentional deltas that each mirror's header documents.
# Every other mirror stays byte-identical to its canonical action.
DELTA_MIRRORS = frozenset({"commit-snapshots", "pnpm-install", "setup-pnpm", "setup-python-cached", "setup-sqlx-cli"})
# Depot resolves both `./.github/actions/<name>` and `./.depot/actions/<name>` from .depot/actions/<name>.
LOCAL_ACTION_USE = re.compile(r"""uses:\s*['"]?\./\.(?:github|depot)/actions/([A-Za-z0-9_.-]+)""")


def used_mirrors(root: Path) -> set[str]:
    return {name for path in (root / ".depot").rglob("*.y*ml") for name in LOCAL_ACTION_USE.findall(path.read_text())}


def _file_bytes(directory: Path) -> dict[Path, bytes]:
    return {path.relative_to(directory): path.read_bytes() for path in directory.rglob("*") if path.is_file()}


def mirror_violations(root: Path, changed: set[str]) -> list[str]:
    violations: list[str] = []
    for name in sorted(used_mirrors(root)):
        canonical = f".github/actions/{name}/"
        mirror = f".depot/actions/{name}/"
        if not (root / mirror).is_dir():
            violations.append(f"A Depot file uses the {name} action, but {mirror} does not exist.")
            continue
        violations.extend(
            f"{path} changed without a matching update to {mirror}{path.removeprefix(canonical)}."
            for path in sorted(changed)
            if path.startswith(canonical) and mirror + path.removeprefix(canonical) not in changed
        )
        if name not in DELTA_MIRRORS and _file_bytes(root / canonical) != _file_bytes(root / mirror):
            violations.append(f"{mirror} differs from its canonical copy {canonical}.")
    return violations


def main(base_sha: str) -> int:
    diff = subprocess.run(["git", "diff", "--name-only", base_sha, "HEAD"], check=True, capture_output=True, text=True)
    changed = set(diff.stdout.splitlines())
    violations = mirror_violations(Path.cwd(), changed)
    sys.stdout.writelines(f"::error::{violation}\n" for violation in violations)
    if not violations:
        sys.stdout.write("The Depot action mirrors are in sync.\n")
    return 1 if violations else 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1]))
