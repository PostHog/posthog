"""Isolation baseline ratchet: the entry gate for new products.

`hogli product:bootstrap` emits a product that claims hoglint's Isolated level from its first
commit: its own turbo.json narrows the `backend:contract-check` inputs, and `hoglint check` fails
when a product that claims the level does not meet it. hoglint judges only the products that claim
the level, so a product built by hand that never narrows its inputs passes hoglint. This ratchet
closes that gap.

`products/isolation_baseline.txt` lists every backend product that does not claim the level. The
check is strict equality:

  - an unclaimed product missing from the baseline -> fail (a new product skipped the scaffold, or
    a product dropped its narrowed inputs)
  - a baseline entry that now claims the level     -> fail (regenerate to shrink)

Equality is what makes the file safe to trust. A baseline that may be stale is a standing
permission slip: a product could claim the level, keep its line, then drop the claim again and
still pass. Requiring both directions to match means a line exists only while it is earned.

The file is CODEOWNERS-owned by DevEx, so adding an exemption is a conversation. Removals are a
rubber stamp on a win.
"""

from __future__ import annotations

import re
import json
from pathlib import Path
from typing import Any

import click

from .paths import ISOLATION_BASELINE, PRODUCTS_DIR, backend_product_dirs

# hoglint's `[levels.isolated] claimed_by = { adapter = "turbo", task = "backend:contract-check" }`.
CLAIM_TASK = "backend:contract-check"
DEFAULT_MARKER = "$TURBO_DEFAULT$"
EXTENDS_MARKER = "$TURBO_EXTENDS$"
ROOT_TURBO_JSON = PRODUCTS_DIR.parent / "turbo.json"

HEADER = """\
# Products that do not claim hoglint's Isolated level: the full Django backend
# suite still runs on every change they make.
#
# DO NOT EDIT BY HAND. This file is the mechanical output of
# `hogli product:lint --regenerate-baseline`. Hand-editing turns a ratchet back
# into a curated allowlist, which is the thing it exists to prevent.
#
# Adding a line needs DevEx review (see .github/CODEOWNERS). New products should
# not need one: `hogli product:bootstrap <name>` scaffolds a product that claims
# the Isolated level from its first commit.
#
# Getting off this list: build the facade (contracts.py + real api.py), wire
# `backend:contract-check`, and narrow the task's inputs in the product's own
# turbo.json. That claims the level; `hoglint check` then names every file the
# inputs must watch. /isolating-product-facade-contracts walks the migration.
#
# Once a product claims the level, regenerate this file and its line drops out.
"""


def _strip_jsonc(text: str) -> str:
    """turbo.json is JSON with comments and trailing commas; drop both outside strings."""
    out: list[str] = []
    index = 0
    in_string = False
    while index < len(text):
        char = text[index]
        if in_string:
            out.append(char)
            if char == "\\":
                out.append(text[index + 1 : index + 2])
                index += 2
                continue
            in_string = char != '"'
            index += 1
            continue
        if char == '"':
            in_string = True
        elif text.startswith("//", index):
            end = text.find("\n", index)
            index = len(text) if end == -1 else end
            continue
        elif text.startswith("/*", index):
            end = text.find("*/", index + 2)
            index = len(text) if end == -1 else end + 2
            continue
        out.append(char)
        index += 1
    return re.sub(r",(\s*[}\]])", r"\1", "".join(out))


def _read_json(path: Path) -> dict[str, Any]:
    if not path.is_file():
        return {}
    data = json.loads(_strip_jsonc(path.read_text()))
    return data if isinstance(data, dict) else {}


def _task(config: dict[str, Any]) -> dict[str, Any] | None:
    task = config.get("tasks", {}).get(CLAIM_TASK)
    return task if isinstance(task, dict) else None


def claims_isolated_level(product_dir: Path, root_turbo_json: Path = ROOT_TURBO_JSON) -> bool:
    """Whether the product claims hoglint's Isolated level, read as hoglint's turbo adapter reads a
    claim (`TurboInputs.narrowed` in hoglint/adapters/turbo.py): the product's package.json has a
    `backend:contract-check` script, its own turbo.json decides the task's inputs, and those inputs
    leave out `$TURBO_DEFAULT$`."""
    manifest = _read_json(product_dir / "package.json")
    scripts = manifest.get("scripts", {})
    if not isinstance(scripts, dict) or CLAIM_TASK not in scripts:
        return False
    package = _read_json(product_dir / "turbo.json")
    own = _task(package)
    if own is None:
        return False
    root_tasks = _read_json(root_turbo_json).get("tasks", {})
    root = root_tasks.get(f"{manifest.get('name')}#{CLAIM_TASK}") or root_tasks.get(CLAIM_TASK)
    extends_root = "//" in package.get("extends", []) and isinstance(root, dict)
    if extends_root and "inputs" not in own:
        return False
    inputs = own.get("inputs", [DEFAULT_MARKER])
    if extends_root and isinstance(inputs, list) and EXTENDS_MARKER in inputs:
        inputs = [*root.get("inputs", [DEFAULT_MARKER]), *(item for item in inputs if item != EXTENDS_MARKER)]
    return isinstance(inputs, list) and DEFAULT_MARKER not in inputs


def unclaimed_products() -> list[str]:
    """Every backend product that does not claim hoglint's Isolated level."""
    return [product_dir.name for product_dir in backend_product_dirs() if not claims_isolated_level(product_dir)]


def read_baseline() -> set[str]:
    if not ISOLATION_BASELINE.exists():
        return set()
    lines = ISOLATION_BASELINE.read_text().splitlines()
    return {line.strip() for line in lines if line.strip() and not line.startswith("#")}


def write_baseline(names: list[str]) -> None:
    ISOLATION_BASELINE.write_text(HEADER + "\n" + "".join(f"{name}\n" for name in sorted(names)))


def regenerate_baseline() -> None:
    names = unclaimed_products()
    write_baseline(names)
    click.echo(f"  Regenerated {ISOLATION_BASELINE.relative_to(PRODUCTS_DIR.parent)}")
    click.echo(f"  {len(names)} product(s) do not claim the Isolated level.")


def baseline_issues(unclaimed: set[str], baseline: set[str]) -> list[str]:
    """Strict equality in both directions. Returns issues; empty means in sync."""
    issues = []
    for name in sorted(unclaimed - baseline):
        issues.append(
            f"{name} does not claim hoglint's Isolated level and is not in the baseline. Scaffold it with "
            f"`hogli product:bootstrap` (products claim the level from their first commit), or ask DevEx "
            f"to sign off on an exemption"
        )
    for name in sorted(baseline - unclaimed):
        issues.append(
            f"{name} is in the baseline but now claims the Isolated level. Run "
            f"`hogli product:lint --regenerate-baseline` to drop its line"
        )
    return issues


def check_baseline() -> list[str]:
    return baseline_issues(set(unclaimed_products()), read_baseline())
