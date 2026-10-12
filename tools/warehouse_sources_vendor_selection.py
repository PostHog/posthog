"""Select the warehouse source vendors a pull request can affect.

Each directory under `sources/` is one vendor, except `sources/sdk`. A vendor imports shared
code only from `sources.sdk`, and tach and import-linter enforce that, so no vendor can change
what another vendor does. A diff that stays inside vendor directories can therefore only break
those vendors. Any other changed file (the SDK, a file at the top of `sources/`, the product,
a manifest, the workflow) can break every vendor, so it selects the full run.

Reads the changed files, one per line, on stdin and prints GitHub step outputs:

    git diff --name-only HEAD^1 HEAD | python3 tools/warehouse_sources_vendor_selection.py

`--full` skips the diff and selects the full run, for runs that have no pull request diff.
"""

from __future__ import annotations

import sys
import argparse
from collections.abc import Iterable
from dataclasses import dataclass
from pathlib import Path, PurePosixPath
from typing import Literal

REPO_ROOT = Path(__file__).parent.parent.resolve()
SOURCES_DIR = "sources"
SDK_DIR = "sdk"


@dataclass(frozen=True, kw_only=True)
class VendorSelection:
    mode: Literal["full", "vendors"]
    # Vendor directory names that exist in the checkout, so their tests can run.
    vendors: tuple[str, ...] = ()
    # Vendor directories the diff deleted. They have no tests left, but a baseline line
    # under them must still go, so the repo invariants scan them.
    deleted_vendors: tuple[str, ...] = ()

    def scan_scope(self) -> tuple[str, ...]:
        """The repo-relative directories a vendors-mode run scans with the repo invariants."""
        return tuple(f"{SOURCES_DIR}/{name}" for name in sorted(self.vendors + self.deleted_vendors))

    def github_output(self) -> str:
        return "\n".join(
            [
                f"mode={self.mode}",
                f"vendors={' '.join(self.vendors)}",
                f"scan_scope={' '.join(self.scan_scope())}",
            ]
        )


class VendorSelector:
    def __init__(self, repo_root: Path) -> None:
        self.sources_root = repo_root / SOURCES_DIR

    def _vendor_of(self, changed_file: str) -> str | None:
        """The vendor directory name a changed file sits in, or None when it sits in no vendor."""
        parts = PurePosixPath(changed_file).parts
        # A file directly under sources/ (conftest.py, __init__.py, owners.yaml) has only two parts.
        if len(parts) < 3 or parts[0] != SOURCES_DIR or parts[1] == SDK_DIR:
            return None
        return parts[1]

    def select(self, changed_files: Iterable[str]) -> VendorSelection:
        changed_files = list(changed_files)
        # The job runs only when its paths filter matched a file, so an empty diff means the
        # diff missed that file. A narrowed run would then test nothing.
        if not changed_files:
            return VendorSelection(mode="full")
        vendors: set[str] = set()
        for changed_file in changed_files:
            vendor = self._vendor_of(changed_file)
            if vendor is None:
                return VendorSelection(mode="full")
            vendors.add(vendor)
        present = tuple(sorted(name for name in vendors if (self.sources_root / name).is_dir()))
        deleted = tuple(sorted(vendors - set(present)))
        return VendorSelection(mode="vendors", vendors=present, deleted_vendors=deleted)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--full", action="store_true", help="select the full run without reading a diff")
    args = parser.parse_args()

    if args.full:
        selection = VendorSelection(mode="full")
    else:
        changed_files = [line.strip() for line in sys.stdin if line.strip()]
        selection = VendorSelector(REPO_ROOT).select(changed_files)
    sys.stdout.write(selection.github_output() + "\n")


if __name__ == "__main__":
    main()
