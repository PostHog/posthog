import ast
import json
from pathlib import Path

# Guards the backend:contract-check isolation of warehouse_sources.
# When only isolated-product internals change, turbo-discover.js skips the Django suite
# (Core/CorePOE). That is sound only if every warehouse_sources source a Core/CorePOE file
# depends on is also a contract-check `input` in the product's turbo.json — otherwise a
# change to that source would skip the Core test that exercises it (a silent coverage hole).
#
# The coupling is NOT direct: dropping the backend.temporal.* tach interface means a direct
# runtime `import ...sources.<vendor>` from Core is now an interface violation tach already
# blocks. What remains is Core reaching source internals THROUGH the facade's lazy re-exports
# (facade/source_management.py's _LAZY map, facade/sources.py's imports). This test resolves
# every facade re-export a Core/CorePOE file actually consumes back to its source vendor and
# fails if that vendor is missing from the turbo.json contract-check inputs.
#
# Limitation: `SourceRegistry.get_source(<type>)` is a dynamic lookup — the vendor it resolves
# to at runtime isn't visible statically, so this guard can't cover it. Core's real coupling is
# the concrete `PostgresSource`/`MySQLSource`/... symbols, which it CAN see; the direct-SQL
# adapters import those explicitly alongside SourceRegistry.
#
# Deliberately uses stdlib ast over a path walk, NOT the repo's `grimp` dependency: grimp
# does not descend products/warehouse_sources/backend/temporal/data_imports/ (an implicit namespace package — no
# __init__.py), so its graph contains zero source modules and the guard would pass blind.

_FACADE_DIR = "products/warehouse_sources/backend/facade"
_SOURCE_MGMT = "products.warehouse_sources.backend.facade.source_management"
_SOURCES = "products.warehouse_sources.backend.facade.sources"
_FACADE_MODULES = frozenset({_SOURCE_MGMT, _SOURCES})

# Roots collected by the Django Core/CorePOE segments. posthog/temporal is excluded — it is
# the Temporal segment, which always runs alongside the product's own temporal job.
_SCAN_ROOTS = ("posthog", "ee", "products/product_analytics")

_INPUTS_PREFIX = "backend/temporal/data_imports/sources/"


def _repo_root() -> Path:
    for parent in Path(__file__).resolve().parents:
        if (parent / ".github" / "workflows" / "ci-backend.yml").exists():
            return parent
    raise RuntimeError("repo root not found")


def _is_type_checking(test: ast.expr) -> bool:
    if isinstance(test, ast.Name):
        return test.id == "TYPE_CHECKING"
    if isinstance(test, ast.Attribute):
        return test.attr == "TYPE_CHECKING"
    return False


def _vendor_from_target(dotted: str) -> str | None:
    """The source vendor a dotted module path re-exports, or None if it isn't a source module.
    The vendor is the path segment right after the ``sources`` package, so this works on both
    the relative _LAZY targets and the absolute imports in sources.py:

    "sources.postgres.source" / "...data_imports.sources.stripe.constants" -> "postgres" / "stripe";
    "sources" (the bare registry) / "cdc.adapters" / "...naming_convention" -> None.
    """
    parts = dotted.split(".")
    if "sources" in parts:
        i = parts.index("sources")
        if i + 1 < len(parts):
            return parts[i + 1]
    return None


def _facade_symbol_to_vendor(root: Path) -> dict[str, str]:
    """Map each facade re-exported symbol to the source vendor it resolves to, across the two
    facade modules that re-export source internals. Symbols whose target isn't a source module
    (SourceRegistry, cdc adapters, NamingConvention) are omitted."""
    mapping: dict[str, str] = {}

    # source_management.py: `_LAZY = {"Symbol": "sources.<vendor>...."}` (relative to the
    # data_imports package). Resolve each entry's target to its vendor.
    sm_tree = ast.parse((root / _FACADE_DIR / "source_management.py").read_text())
    for node in ast.walk(sm_tree):
        if not (
            isinstance(node, ast.Assign) and any(isinstance(t, ast.Name) and t.id == "_LAZY" for t in node.targets)
        ):
            continue
        assert isinstance(node.value, ast.Dict)
        for key, value in zip(node.value.keys, node.value.values):
            if not (
                isinstance(key, ast.Constant)
                and isinstance(key.value, str)
                and isinstance(value, ast.Constant)
                and isinstance(value.value, str)
            ):
                continue
            vendor = _vendor_from_target(value.value)
            if vendor:
                mapping[key.value] = vendor

    # sources.py: `from products.warehouse_sources...sources.<vendor>... import (A, B, ...)`.
    src_tree = ast.parse((root / _FACADE_DIR / "sources.py").read_text())
    for node in ast.walk(src_tree):
        if not isinstance(node, ast.ImportFrom) or not node.module:
            continue
        vendor = _vendor_from_target(node.module)
        if not vendor:
            continue
        for alias in node.names:
            mapping[alias.asname or alias.name] = vendor

    assert mapping, "parsed no source re-exports from the warehouse_sources facade"
    return mapping


def _core_consumed_facade_symbols(tree: ast.AST) -> set[str]:
    """Names a module imports from the source-re-exporting facade modules, excluding
    TYPE_CHECKING-only imports (those don't affect runtime test behavior)."""
    found: set[str] = set()

    class Visitor(ast.NodeVisitor):
        def visit_If(self, node: ast.If) -> None:
            if _is_type_checking(node.test):
                for stmt in node.orelse:
                    self.visit(stmt)
                return
            self.generic_visit(node)

        def visit_ImportFrom(self, node: ast.ImportFrom) -> None:
            if node.module in _FACADE_MODULES:
                for alias in node.names:
                    found.add(alias.name)

    Visitor().visit(tree)
    return found


def _contract_covered_sources(root: Path) -> set[str]:
    turbo = json.loads((root / "products" / "warehouse_sources" / "turbo.json").read_text())
    inputs = turbo["tasks"]["backend:contract-check"]["inputs"]
    covered = {
        rest.split("/")[0].removesuffix(".py")
        for entry in inputs
        if entry.startswith(_INPUTS_PREFIX) and (rest := entry[len(_INPUTS_PREFIX) :])
    }
    assert covered, "parsed no source-vendor inputs from turbo.json backend:contract-check"
    return covered


def test_core_facade_coupled_sources_are_covered_by_contract_check():
    root = _repo_root()
    excluded = root / "posthog" / "temporal"  # the Temporal segment; always runs
    symbol_to_vendor = _facade_symbol_to_vendor(root)

    consumed: set[str] = set()
    for rel in _SCAN_ROOTS:
        base = root / rel
        if not base.exists():
            continue
        for file in base.rglob("*.py"):
            if file.is_relative_to(excluded):
                continue
            text = file.read_text(errors="ignore")
            if "facade.source_management" not in text and "facade.sources" not in text:
                continue
            try:
                tree = ast.parse(text, filename=str(file))
            except SyntaxError:
                continue
            consumed |= _core_consumed_facade_symbols(tree)

    coupled_vendors = {symbol_to_vendor[s] for s in consumed if s in symbol_to_vendor}
    covered = _contract_covered_sources(root)
    missing = coupled_vendors - covered
    assert not missing, (
        f"Core/CorePOE reaches warehouse sources {sorted(missing)} through the facade, but they are "
        f"not covered by products/warehouse_sources/turbo.json backend:contract-check inputs "
        f"{sorted(covered)}. A change to those sources would skip the Core tests that exercise them. "
        f"Add backend/temporal/data_imports/sources/<vendor>/** to the contract-check inputs."
    )
