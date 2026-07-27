"""Shared inputs handed to every derivation source."""

from __future__ import annotations

from dataclasses import dataclass
from functools import cached_property
from pathlib import Path

from .join import Join, join_to_product, load_aliases


@dataclass
class DerivationContext:
    repo_root: Path
    products_dir: Path
    # Product directory names, in the same sense `hogli product:lint` uses: a directory
    # under products/ with an __init__.py. Sources must return a fact for each of these.
    product_dirs: set[str]

    @cached_property
    def aliases(self) -> dict[str, str]:
        return load_aliases(self.products_dir)

    def join(self, token: str) -> Join:
        return join_to_product(token, self.product_dirs, self.aliases)

    def rel(self, path: Path) -> str:
        """Repo-relative path string, for the `from` provenance list."""
        return str(path.relative_to(self.repo_root))
