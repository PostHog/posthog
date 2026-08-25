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
"""

from __future__ import annotations

import click

from .isolation import compute_isolation_status
from .paths import ISOLATION_BASELINE, PRODUCTS_DIR, TACH_TOML, backend_product_dirs

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


def regenerate_baseline() -> None:
    names = unsealed_products()
    write_baseline(names)
    click.echo(f"  Regenerated {ISOLATION_BASELINE.relative_to(PRODUCTS_DIR.parent)}")
    click.echo(f"  {len(names)} product(s) not isolated.")


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
