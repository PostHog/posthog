"""What hoglint says about each product: the Isolated level and the debt it carries.

The Isolated level comes from files: `level:isolated <product>` lines in `hoglint.ledger` say the
product passed when the ledger was last written, and `baseline.claims_isolated_level` says whether
it claims the level, read the way hoglint's turbo adapter reads a claim. The debt comes from `hoglint query --by package --json`, which groups
finding rows by the source module's `package` label, hoglint's own attribution. A row's status is
`accepted` (in the ledger), `new` (blocks) or `advisory` (its rule never blocks, so it is no debt).
"""

from __future__ import annotations

import sys
import json
import subprocess
from dataclasses import dataclass, field
from pathlib import Path

from .baseline import claims_isolated_level

LEDGER_FILE = "hoglint.ledger"
ISOLATED_LEVEL_RULE = "level:isolated"
QUERY_COMMAND = ("query", "--by", "package", "--json")


@dataclass(frozen=True)
class IsolatedPasses:
    """The products the ledger records as passing the Isolated level. `exists` is False on a branch
    without a ledger, so the level is unknown there."""

    products: frozenset[str]
    exists: bool

    @staticmethod
    def read(repo_root: Path) -> IsolatedPasses:
        ledger = repo_root / LEDGER_FILE
        if not ledger.is_file():
            return IsolatedPasses(frozenset(), exists=False)
        products: set[str] = set()
        for line in ledger.read_text().splitlines():
            columns = line.split("\t")
            if len(columns) >= 2 and columns[0] == ISOLATED_LEVEL_RULE:
                products.add(columns[1])
        return IsolatedPasses(frozenset(products), exists=True)


@dataclass(frozen=True)
class IsolatedLevel:
    claims: bool
    passes: bool
    known: bool = True

    @property
    def detail(self) -> str:
        if not self.known:
            return f"unknown: no {LEDGER_FILE}"
        if self.claims and self.passes:
            return "claims and passes"
        if self.claims:
            return "claims and fails"
        if self.passes:
            return "passes without claiming"
        return "neither claims nor passes"

    @property
    def short(self) -> str:
        if not self.known:
            return "?"
        if self.claims and self.passes:
            return "yes"
        if self.claims:
            return "FAIL"
        if self.passes:
            return "free"
        return "-"

    @staticmethod
    def of(product: str, product_dir: Path, passes: IsolatedPasses) -> IsolatedLevel:
        return IsolatedLevel(
            claims=claims_isolated_level(product_dir),
            passes=product in passes.products,
            known=passes.exists,
        )


@dataclass(frozen=True)
class PackageDebt:
    """One package's finding rows: accepted rows per rule, the count of new rows, and the rows of
    advisory rules per rule, which are kept apart from the debt."""

    accepted: dict[str, int] = field(default_factory=dict)
    new_total: int = 0
    advisory: dict[str, int] = field(default_factory=dict)

    @property
    def accepted_total(self) -> int:
        return sum(self.accepted.values())

    @property
    def advisory_total(self) -> int:
        return sum(self.advisory.values())


@dataclass(frozen=True)
class HoglintDebt:
    """The debt per package, or why it is unavailable."""

    packages: dict[str, PackageDebt] = field(default_factory=dict)
    unavailable: str = ""

    def of(self, product: str) -> PackageDebt:
        return self.packages.get(product, PackageDebt())

    @staticmethod
    def parse(text: str) -> HoglintDebt:
        try:
            data = json.loads(text)
        except json.JSONDecodeError:
            return HoglintDebt(unavailable="hoglint printed no valid JSON")
        if not isinstance(data, dict) or data.get("by") != "package" or not isinstance(data.get("groups"), list):
            return HoglintDebt(unavailable="hoglint printed JSON without package groups")
        packages: dict[str, PackageDebt] = {}
        try:
            for group in data["groups"]:
                counts = group["counts"]
                accepted = {str(rule): int(rows) for rule, rows in counts.get("accepted", {}).items()}
                new_total = sum(int(rows) for rows in counts.get("new", {}).values())
                advisory = {str(rule): int(rows) for rule, rows in counts.get("advisory", {}).items()}
                packages[str(group["key"])] = PackageDebt(accepted=accepted, new_total=new_total, advisory=advisory)
        except (AttributeError, KeyError, TypeError, ValueError):
            return HoglintDebt(unavailable="hoglint printed a group in an unknown shape")
        return HoglintDebt(packages)

    @staticmethod
    def load(repo_root: Path) -> HoglintDebt:
        """Run the query once for every product."""
        result = subprocess.run(
            # -P keeps the checkout off sys.path, so a stray hoglint module in it cannot replace the pinned package.
            [sys.executable, "-P", "-m", "hoglint", *QUERY_COMMAND],
            cwd=repo_root,
            capture_output=True,
            text=True,
            check=False,
        )
        if result.returncode != 0:
            last_line = (result.stderr.strip().splitlines() or [f"exit code {result.returncode}"])[-1]
            return HoglintDebt(unavailable=last_line)
        return HoglintDebt.parse(result.stdout)
