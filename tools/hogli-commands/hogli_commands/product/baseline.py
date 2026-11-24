"""Isolation baseline ratchet: the entry gate for new products.

hoglint judges hoglint's Isolated level for every product, and `hoglint check --write-ledger`
records each product that passes as a `level:isolated <product>` line in `hoglint.ledger`. A product
that passes gets the test skip. Nothing stops a new product from failing the level, so this ratchet
makes that a reviewed decision.

`products/isolation_baseline.txt` lists every backend product that the ledger does not record as
passing the level. The check is strict equality:

  - a product that does not pass, missing from the baseline -> fail (a new product that fails the
    level, or a product that stopped passing it)
  - a baseline entry that now passes the level              -> fail (regenerate to shrink)

Equality is what makes the file safe to trust. A baseline that may be stale is a standing
permission slip: a product could pass the level, keep its line, then stop passing and still pass
this check. Requiring both directions to match means a line exists only while it is earned.

The file is CODEOWNERS-owned by DevEx, so adding an exemption is a conversation. Removals are a
rubber stamp on a win.
"""

from __future__ import annotations

import click

from .hoglint_status import IsolatedPasses
from .paths import ISOLATION_BASELINE, PRODUCTS_DIR, REPO_ROOT, backend_product_dirs

HEADER = """\
# Products that do not pass hoglint's Isolated level: the full Django backend
# suite still runs on every change they make.
#
# DO NOT EDIT BY HAND. This file is the mechanical output of
# `hogli product:lint --regenerate-baseline`, which reads the `level:isolated`
# lines of hoglint.ledger. Hand-editing turns a ratchet back into a curated
# allowlist, which is the thing it exists to prevent.
#
# Adding a line needs DevEx review (see .github/CODEOWNERS). New products should
# not need one: `hogli product:bootstrap <name>` scaffolds a product that passes
# the Isolated level from its first commit.
#
# Getting off this list: build the facade (contracts.py + real api.py) and fix
# what `hoglint watched --level isolated` names under the product's reasons.
# /isolating-product-facade-contracts walks the migration.
#
# Once `hoglint check --write-ledger` records the product as passing, regenerate
# this file and its line drops out.
"""


def products_not_passing() -> list[str]:
    """Every backend product the ledger does not record as passing hoglint's Isolated level."""
    passes = IsolatedPasses.read(REPO_ROOT).products
    return [product_dir.name for product_dir in backend_product_dirs() if product_dir.name not in passes]


def read_baseline() -> set[str]:
    if not ISOLATION_BASELINE.exists():
        return set()
    lines = ISOLATION_BASELINE.read_text().splitlines()
    return {line.strip() for line in lines if line.strip() and not line.startswith("#")}


def write_baseline(names: list[str]) -> None:
    ISOLATION_BASELINE.write_text(HEADER + "\n" + "".join(f"{name}\n" for name in sorted(names)))


def regenerate_baseline() -> None:
    names = products_not_passing()
    write_baseline(names)
    click.echo(f"  Regenerated {ISOLATION_BASELINE.relative_to(PRODUCTS_DIR.parent)}")
    click.echo(f"  {len(names)} product(s) do not pass the Isolated level.")


def baseline_issues(not_passing: set[str], baseline: set[str]) -> list[str]:
    """Strict equality in both directions. Returns issues; empty means in sync."""
    issues = []
    for name in sorted(not_passing - baseline):
        issues.append(
            f"{name} does not pass hoglint's Isolated level and is not in the baseline. Fix what "
            f"`hoglint watched --level isolated` names for it, or ask DevEx to sign off on an exemption"
        )
    for name in sorted(baseline - not_passing):
        issues.append(
            f"{name} is in the baseline but now passes the Isolated level. Run "
            f"`hogli product:lint --regenerate-baseline` to drop its line"
        )
    return issues


def check_baseline() -> list[str]:
    return baseline_issues(set(products_not_passing()), read_baseline())
