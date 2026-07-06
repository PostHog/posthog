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


def has_routes_module(backend_dir: Path) -> bool:
    """The product-local route-registration entry point (a routes.py file or routes/ package).

    Core imports it to assemble the API router, so it is public contract surface — not an
    internal. That is why it does not mark a product as un-isolatable (see
    pattern_targets_public_surface), but it does need watching once turbo inputs are narrowed.
    """
    return (backend_dir / "routes.py").exists() or (backend_dir / "routes").is_dir()


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


def contract_check_inputs(product_dir: Path) -> list[str]:
    """The product's backend:contract-check `inputs` globs (empty if no override)."""
    turbo_json = product_dir / "turbo.json"
    if not turbo_json.exists():
        return []
    try:
        tasks = json.loads(turbo_json.read_text()).get("tasks", {})
    except json.JSONDecodeError:
        return []
    contract_task = tasks.get("backend:contract-check")
    if not contract_task:
        return []
    return contract_task.get("inputs", [])


# A contract-check input is "on the public surface" when it targets the facade, the presentation
# layer, or the routes registration module. Anchored on the path separator so a near-miss like
# backend/facade_legacy/** can't pass; removeprefix (not lstrip, which strips a char set) trims
# only a literal "./" so a "../escape/**" can't be normalized into a surface path.
_FACADE_PRESENTATION_PREFIXES = ("backend/facade/", "backend/presentation/")
_ROUTES_PREFIXES = ("backend/routes.py", "backend/routes/")


def _input_targets_facade_or_presentation(glob: str) -> bool:
    return glob.removeprefix("./").startswith(_FACADE_PRESENTATION_PREFIXES)


def _input_targets_surface(glob: str) -> bool:
    return glob.removeprefix("./").startswith(_FACADE_PRESENTATION_PREFIXES + _ROUTES_PREFIXES)


def has_narrowed_turbo_inputs(product_dir: Path) -> bool:
    """True only when contract-check inputs are confined to the public surface AND at least one
    targets facade/presentation. A broad glob like backend/** alongside a facade entry keeps the
    skip inert, and a routes-only narrowing isn't a real contract surface — both are rejected.
    Negated globs ('!...') are excluded from the surface test."""
    inputs = [i for i in contract_check_inputs(product_dir) if not i.startswith("!")]
    if not inputs:
        return False
    return all(_input_targets_surface(i) for i in inputs) and any(
        _input_targets_facade_or_presentation(i) for i in inputs
    )


def routes_in_turbo_inputs(product_dir: Path) -> bool:
    """True if contract-check inputs watch the routes module specifically — backend/routes.py or a
    backend/routes/ package. Anchored and negation-aware, so a glob that merely contains 'routes',
    or a negated exclusion like !backend/routes.py, doesn't falsely count the routes module as
    watched (without it, a routes-only change is invisible to the skip and runs no Django suite)."""
    return any(
        i.removeprefix("./").startswith(_ROUTES_PREFIXES)
        for i in contract_check_inputs(product_dir)
        if not i.startswith("!")
    )


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
    bypass_entries: tuple[str, ...]  # presentation -> internals deferrals still open (the worklist)
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
        """Prerequisites for the contract-check skip, mirroring the lint gate's package.json
        check exactly. Deliberately does NOT include `has_tach_interface` — the external
        boundary is required too, but it's enforced separately (TachCheck demands the
        interface; IsolationChainCheck blocks a script without it). Callers that gate a
        "ready" *display* should additionally require `externally_sealed`."""
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
        bypass_entries=tuple(presentation_bypass_entries(name, pyproject_text)),
        has_contract_check_script=has_contract_check_script(product_dir),
        has_narrowed_turbo=has_narrowed_turbo_inputs(product_dir),
    )
