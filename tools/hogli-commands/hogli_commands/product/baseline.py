"""Isolation baseline ratchet — the entry gate for new products.

`product:bootstrap` emits a product that is already sealed: real facade, contracts,
tach `[[interfaces]]`, narrowed `turbo.json`, `backend:contract-check`. So "new products
are isolated" costs a team nothing beyond using the scaffold, and every product that
isn't sealed is either pre-scaffold debt or a deliberate exemption.

`products/isolation_baseline.txt` records exactly that set. The check is strict equality:

  - unsealed product missing from the baseline  -> fail (a new product skipped the scaffold,
    or a sealed one regressed)
  - baseline entry that is now sealed           -> fail (regenerate to shrink)

Equality is what makes the file safe to trust. A baseline that may be stale is a standing
permission slip: a product could seal, keep its line, then lose its facade again and still
pass. Requiring both directions to match means a line exists only while it is earned.

The file is CODEOWNERS-owned by DevEx, so adding an exemption is a conversation. Removals
are a rubber stamp on a win.

A second ratchet lives here for the same reason. `products/facade_shape_baseline.txt` records what
the facades hand across the boundary today: signatures that name a Django or a DRF type, ORM names
a facade re-exports, and logic that sits in a capability submodule. Import linters cannot see any
of it, because the import of a model module and the return of a model instance look the same in the
graph. That file is the shape half of the seal, and it only shrinks.
"""

from __future__ import annotations

import functools

import click

from .isolation import compute_isolation_status, facade_shape_findings
from .paths import FACADE_SHAPE_BASELINE, ISOLATION_BASELINE, PRODUCTS_DIR, TACH_TOML, backend_product_dirs

HEADER = """\
# Products that are not isolated — the full Django backend suite still runs on
# every change they make.
#
# DO NOT EDIT BY HAND. This file is the mechanical output of
# `hogli product:lint --regenerate-baseline`. Hand-editing turns a ratchet back
# into a curated allowlist, which is the thing it exists to prevent.
#
# Adding a line needs DevEx review (see .github/CODEOWNERS). New products should
# not need one: `hogli product:bootstrap <name>` scaffolds a product that is
# sealed from its first commit.
#
# Getting off this list: build the facade (contracts.py + real api.py), add the
# tach [[interfaces]] block, then wire `backend:contract-check` and narrow
# turbo.json inputs. `hogli product:maturity <name>` names the remaining blocker
# at every step, and /isolating-product-facade-contracts walks the migration.
#
# Once a product is sealed, regenerate this file and its line drops out.
"""


def unsealed_products() -> list[str]:
    """Every backend product whose `backend:contract-check` skip is not live.

    Keyed on the skip actually being wired, not on the facade merely existing: a
    re-export shim with an empty contracts.py would otherwise buy its way off the
    list without sealing anything.
    """
    tach_content = TACH_TOML.read_text() if TACH_TOML.exists() else ""
    unsealed = []
    for product_dir in backend_product_dirs():
        status = compute_isolation_status(
            product_dir.name, product_dir, product_dir / "backend", tach_content=tach_content
        )
        if not status.isolated_tests_enabled:
            unsealed.append(product_dir.name)
    return unsealed


def read_baseline() -> set[str]:
    if not ISOLATION_BASELINE.exists():
        return set()
    lines = ISOLATION_BASELINE.read_text().splitlines()
    return {line.strip() for line in lines if line.strip() and not line.startswith("#")}


def write_baseline(names: list[str]) -> None:
    ISOLATION_BASELINE.write_text(HEADER + "\n" + "".join(f"{name}\n" for name in sorted(names)))


FACADE_SHAPE_HEADER = """\
# What every product facade hands across its boundary today, and where a capability submodule
# holds logic instead of a wiring re-export. One row per finding:
#
#   <product> <facade module> <symbol> <kind> <type>
#
# DO NOT EDIT BY HAND. This file is the mechanical output of
# `hogli product:lint --regenerate-baseline`. Hand-editing turns a ratchet back into a curated
# allowlist, which is the thing it exists to prevent.
#
# The list only shrinks. A finding that is not on it fails the lint, and a row whose finding is
# gone fails too, so regenerate in the same change that removes one. Adding a row needs DevEx
# review (see .github/CODEOWNERS).
#
# Getting a row off the list, by kind:
#
#   returns  Return a frozen contract from facade/contracts.py, not the ORM object.
#   accepts  Take ids and contracts, so the caller never holds a Django or a DRF object.
#            An `Any` row on team, request, or user hides such an object behind the annotation.
#   exports  Stop re-exporting the class, or move it to the wiring location that owns it.
#   logic    Move the body to the wiring location (backend/hogql_queries/, backend/max_tools.py,
#            backend/temporal/, backend/tasks/) and leave the re-export in the facade.
#
# See products/architecture.md for the doctrine, and /isolating-product-facade-contracts for the
# migration.
"""


def facade_shape_rows() -> list[str]:
    """Every facade shape finding in the tree, as sorted baseline rows."""
    return sorted(
        finding.as_baseline_line()
        for product_dir in backend_product_dirs()
        for finding in facade_shape_findings(product_dir / "backend", product_dir.name)
    )


@functools.cache
def read_facade_shape_baseline() -> frozenset[str]:
    """The recorded rows. Cached because `product:lint --all` reads it once per product."""
    if not FACADE_SHAPE_BASELINE.exists():
        return frozenset()
    lines = FACADE_SHAPE_BASELINE.read_text().splitlines()
    return frozenset(line.strip() for line in lines if line.strip() and not line.startswith("#"))


def write_facade_shape_baseline(rows: list[str]) -> None:
    FACADE_SHAPE_BASELINE.write_text(FACADE_SHAPE_HEADER + "\n" + "".join(f"{row}\n" for row in rows))
    read_facade_shape_baseline.cache_clear()


def orphaned_facade_shape_rows() -> list[str]:
    """Recorded rows for a product the facade shape scan no longer reaches.

    Every other row is checked per product by FacadeShapeCheck, which sees both directions for the
    product it runs on. A row whose product lost its backend or its facade gets no such run, so the
    repo-wide sweep is what catches it.
    """
    scanned = {d.name for d in backend_product_dirs() if (d / "backend" / "facade").is_dir()}
    return sorted(row for row in read_facade_shape_baseline() if row.split(" ", 1)[0] not in scanned)


def check_facade_shape_baseline() -> list[str]:
    return [
        f"'{row}' is in the facade shape baseline but its product no longer has a facade — run "
        f"`hogli product:lint --regenerate-baseline` to drop the row"
        for row in orphaned_facade_shape_rows()
    ]


def regenerate_baseline() -> None:
    names = unsealed_products()
    write_baseline(names)
    click.echo(f"  Regenerated {ISOLATION_BASELINE.relative_to(PRODUCTS_DIR.parent)}")
    click.echo(f"  {len(names)} product(s) not isolated.")
    rows = facade_shape_rows()
    write_facade_shape_baseline(rows)
    click.echo(f"  Regenerated {FACADE_SHAPE_BASELINE.relative_to(PRODUCTS_DIR.parent)}")
    click.echo(f"  {len(rows)} facade shape row(s).")


def baseline_issues(unsealed: set[str], baseline: set[str]) -> list[str]:
    """Strict equality in both directions. Returns issues; empty means in sync."""
    issues = []
    for name in sorted(unsealed - baseline):
        issues.append(
            f"{name} is not isolated and is not in the baseline — scaffold it with "
            f"`hogli product:bootstrap` (products are sealed from their first commit), or ask "
            f"DevEx to sign off on an exemption. `hogli product:maturity {name}` names the blocker"
        )
    for name in sorted(baseline - unsealed):
        issues.append(
            f"{name} is in the baseline but is now isolated — run "
            f"`hogli product:lint --regenerate-baseline` to drop its line"
        )
    return issues


def check_baseline() -> list[str]:
    return baseline_issues(set(unsealed_products()), read_baseline())
