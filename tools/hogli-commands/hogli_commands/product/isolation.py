"""Shared isolation-seal predicates — single source of truth for both consumers.

The lint gate (checks.py) and the maturity report (maturity.py) both need to answer
"how isolated is this product, really?". Keeping that logic here means the gate and the
report can't drift apart.

Isolation has two independent seals:

  - external: nobody outside the product imports its internals. Enforced by tach's
    [[interfaces]] block — the product only exposes facade + presentation.views + routes.
  - internal: the product's own presentation reaches models/logic only through the facade.
    Enforced by import-linter, and only fully sealed once its ignore_imports allowlist for
    this product is empty (no deferred presentation-wave bypasses).

When both seals hold and the facade is real, the product earns isolated tests — the
backend:contract-check skip that keeps its Django suite off unrelated CI shards. That skip
is the reward for finishing, which is why it can't turn on while either seal is incomplete.
"""

from __future__ import annotations

import re
import json
import tomllib
from collections.abc import Iterator
from dataclasses import dataclass
from pathlib import Path

from .ast_helpers import has_any_function_defs
from .paths import REPO_ROOT, TACH_TOML, get_tach_block

# ---------------------------------------------------------------------------
# tach.toml parsing
# ---------------------------------------------------------------------------


def iter_interface_blocks(tach_content: str) -> Iterator[tuple[list[str], list[str]]]:
    """Yield (expose_patterns, from_patterns) for every [[interfaces]] block."""
    for match in re.finditer(r"\[\[interfaces\]\]\s*\n(.*?)(?=\[\[|\Z)", tach_content, re.DOTALL):
        block = match.group(1)
        expose_match = re.search(r"expose\s*=\s*\[(.*?)\]", block, re.DOTALL)
        from_match = re.search(r"from\s*=\s*\[(.*?)\]", block, re.DOTALL)
        if not expose_match or not from_match:
            continue
        expose_patterns = re.findall(r'"(.*?)"', expose_match.group(1))
        from_patterns = re.findall(r'"(.*?)"', from_match.group(1))
        yield expose_patterns, from_patterns


def pattern_targets_public_surface(pattern: str) -> bool:
    """True if a tach expose pattern targets a product's public surface.

    Public surface is backend.facade, backend.presentation, or backend.routes —
    the last being the product-local route registration entry point that core
    imports to assemble the API router. It is a public composition hook, not an
    internal leak, so it does not mark a product as un-isolatable.

    Strips backslashes first so it works on both the on-disk TOML form (`\\.`,
    two literal backslashes) and Python-string fixtures (single backslash).
    """
    normalized = pattern.replace("\\", "")
    return (
        normalized.startswith("backend.facade")
        or normalized.startswith("backend.presentation")
        or normalized.startswith("backend.routes")
    )


def names_from_pattern(pattern: str) -> set[str]:
    """Extract product short names from a tach `from` pattern.

    Handles three forms:
      - "products.experiments"                       -> {"experiments"}
      - "products\\.experiments"                     -> {"experiments"}
      - "products\\.(experiments|mcp_store|...)"     -> {"experiments", "mcp_store", ...}
    """
    normalized = pattern.replace("\\", "")
    m = re.match(r"^products\.\(([^)]+)\)$", normalized)
    if m:
        return {n.strip() for n in m.group(1).split("|") if n.strip()}
    m = re.match(r"^products\.([A-Za-z0-9_]+)$", normalized)
    if m:
        return {m.group(1)}
    return set()


# ---------------------------------------------------------------------------
# Low-level seal signals
# ---------------------------------------------------------------------------


def is_isolated_product(backend_dir: Path) -> bool:
    """A product is in the strict isolation regime once it has a contracts module."""
    return (backend_dir / "facade" / "contracts.py").exists() or (backend_dir / "facade" / "contracts").exists()


def has_real_facade(backend_dir: Path) -> bool:
    """A real facade defines functions; a re-export shim from logic does not count."""
    facade_api = backend_dir / "facade" / "api.py"
    return facade_api.exists() and has_any_function_defs(facade_api)


def has_tach_interface(name: str, tach_content: str | None = None) -> bool:
    """True if the product is named in a tach [[interfaces]] block (inline or global).

    Names are matched structurally against each block's `from` list. A loose regex
    over the whole file false-positives on any product whose name appears later (e.g.
    in its own [[modules]] block), which made nearly every product read as sealed.
    """
    block = get_tach_block(f"products.{name}")
    if block and "interfaces" in block and "interfaces = []" not in block:
        return True
    content = tach_content if tach_content is not None else (TACH_TOML.read_text() if TACH_TOML.exists() else "")
    return any(
        name in names_from_pattern(pattern)
        for _expose, from_patterns in iter_interface_blocks(content)
        for pattern in from_patterns
    )


def has_legacy_interface_leaks(tach_content: str, module_path: str) -> bool:
    """Check if a product has legacy interface leak blocks in tach.toml.

    These are products where core (posthog/ee) still imports internals directly,
    so they can't safely be tested in isolation via contract-check.

    Detected structurally: an [[interfaces]] block whose `from` is exactly this
    module and whose `expose` includes any non-facade/non-presentation pattern.
    """
    for expose_patterns, from_patterns in iter_interface_blocks(tach_content):
        normalized_from = [p.replace("\\", "") for p in from_patterns]
        if normalized_from != [module_path]:
            continue
        if any(not pattern_targets_public_surface(p) for p in expose_patterns):
            return True
    return False


def presentation_bypass_entries(name: str, pyproject_text: str | None = None) -> list[str]:
    """import-linter ignore_imports entries that still let this product's presentation
    reach its own internals directly — the deferred presentation-wave worklist.

    Each entry is one view -> internal edge to remove before the product is internally
    sealed (see the isolating-product-facade-contracts skill).
    """
    if pyproject_text is None:
        pyproject = REPO_ROOT / "pyproject.toml"
        if not pyproject.exists():
            return []
        pyproject_text = pyproject.read_text()
    try:
        contracts = tomllib.loads(pyproject_text)["tool"]["importlinter"]["contracts"]
    except (tomllib.TOMLDecodeError, KeyError):
        return []
    prefix = f"products.{name}.backend.presentation"
    return [entry for contract in contracts for entry in contract.get("ignore_imports", []) if entry.startswith(prefix)]


def has_contract_check_script(product_dir: Path) -> bool:
    package_json = product_dir / "package.json"
    if not package_json.exists():
        return False
    try:
        scripts = json.loads(package_json.read_text()).get("scripts", {})
    except json.JSONDecodeError:
        return False
    return "backend:contract-check" in scripts


def has_narrowed_turbo_inputs(product_dir: Path) -> bool:
    turbo_json = product_dir / "turbo.json"
    if not turbo_json.exists():
        return False
    try:
        tasks = json.loads(turbo_json.read_text()).get("tasks", {})
    except json.JSONDecodeError:
        return False
    contract_task = tasks.get("backend:contract-check")
    if not contract_task:
        return False
    inputs = contract_task.get("inputs", [])
    return any("facade" in i or "presentation" in i for i in inputs)


# ---------------------------------------------------------------------------
# High-level status — the synthesis both lint and maturity read
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class IsolationStatus:
    name: str
    is_isolated: bool  # has facade/contracts.py — in the strict regime
    has_real_facade: bool
    has_tach_interface: bool
    has_legacy_leaks: bool
    bypass_entries: list[str]  # presentation -> internals deferrals still open (the worklist)
    has_contract_check_script: bool
    has_narrowed_turbo: bool

    @property
    def deferred_count(self) -> int:
        return len(self.bypass_entries)

    @property
    def externally_sealed(self) -> bool:
        """External consumers can only reach the public surface: interface on, no leak block."""
        return self.has_tach_interface and not self.has_legacy_leaks

    @property
    def internally_sealed(self) -> bool:
        """Presentation reaches internals only through the facade — no open bypasses."""
        return self.is_isolated and self.deferred_count == 0

    @property
    def eligible_for_isolated_tests(self) -> bool:
        """Prerequisites for the contract-check skip. Mirrors the lint gate exactly."""
        return self.is_isolated and self.has_real_facade and not self.has_legacy_leaks and self.deferred_count == 0

    @property
    def isolated_tests_enabled(self) -> bool:
        """The skip is physically wired up right now (script present + turbo narrowed)."""
        return self.has_contract_check_script and self.has_narrowed_turbo


def compute_isolation_status(
    name: str,
    product_dir: Path,
    backend_dir: Path,
    *,
    is_isolated: bool | None = None,
    tach_content: str | None = None,
    pyproject_text: str | None = None,
) -> IsolationStatus:
    """Compute the full isolation seal status for one product."""
    if is_isolated is None:
        is_isolated = is_isolated_product(backend_dir)
    if tach_content is None:
        tach_content = TACH_TOML.read_text() if TACH_TOML.exists() else ""
    module_path = f"products.{name}"
    return IsolationStatus(
        name=name,
        is_isolated=is_isolated,
        has_real_facade=has_real_facade(backend_dir),
        has_tach_interface=has_tach_interface(name, tach_content),
        has_legacy_leaks=has_legacy_interface_leaks(tach_content, module_path),
        bypass_entries=presentation_bypass_entries(name, pyproject_text),
        has_contract_check_script=has_contract_check_script(product_dir),
        has_narrowed_turbo=has_narrowed_turbo_inputs(product_dir),
    )
