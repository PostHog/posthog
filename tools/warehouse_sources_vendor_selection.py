"""Select the warehouse source vendors a pull request can affect.

Each directory under `products/warehouse_sources/sources/` is one vendor, except `sdk`. A vendor
imports shared code only from the SDK, and tach, import-linter and a repo invariant enforce that,
so no vendor can change what another vendor does. A diff that stays inside vendor directories can
therefore only break those vendors. Any other changed file (the SDK, a file at the top of the
plugin directory, the product, a manifest, the workflow) can break every vendor, so it selects
the full run.

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
PLUGIN_DIR = "products/warehouse_sources/sources"
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
        return tuple(f"{PLUGIN_DIR}/{name}" for name in sorted(self.vendors + self.deleted_vendors))

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
        self.plugin_root = repo_root / PLUGIN_DIR

    def _vendor_of(self, changed_file: str) -> str | None:
        """The vendor directory name a changed file sits in, or None when it sits in no vendor."""
        path = PurePosixPath(changed_file)
        if not path.is_relative_to(PLUGIN_DIR):
            return None
        parts = path.relative_to(PLUGIN_DIR).parts
        # A file directly under the plugin directory (conftest.py, __init__.py, AGENTS.md) has
        # one part. The SDK is shared code, not a vendor.
        if len(parts) < 2 or parts[0] == SDK_DIR:
            return None
        return parts[0]

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
        present = tuple(sorted(name for name in vendors if (self.plugin_root / name).is_dir()))
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
