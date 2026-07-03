import ast
import json
from pathlib import Path

# Guards the backend:contract-check isolation of warehouse_sources.
# When only isolated-product internals change, turbo-discover.js skips the Django suite
# (Core/CorePOE) — sound only for sources NOT reverse-imported by Core/CorePOE-collected
# code. The ones that ARE reverse-imported must land in the product's turbo.json
# contract-check `inputs`, so a change to them counts as a contract change and re-runs
# Django. This test fails if a Core/CorePOE file gains a runtime import of a source vendor
# missing from those inputs — which would otherwise let a change to it silently skip the
# Core test that exercises it.
#
# Deliberately uses stdlib ast over a path walk, NOT the repo's `grimp` dependency: grimp
# does not descend products/warehouse_sources/backend/temporal/data_imports/ (an implicit namespace package — no
# __init__.py), so its graph contains zero source modules and the guard would pass blind.

# Only leaf imports (sources.<vendor>...) are counted. A bare
# `from ...sources import SourceRegistry / load_all_sources` is intentionally NOT flagged:
# the registry is lazy, so importing it loads no vendor module — only calling
# load_all_sources() does (at worker boot), which the Temporal registry-load test covers.
SOURCES_PKG = "products.warehouse_sources.backend.temporal.data_imports.sources."

# Roots collected by the Django Core/CorePOE segments. posthog/temporal is excluded — it is
# the Temporal segment, which always runs for a sources-only PR.
_SCAN_ROOTS = ("posthog", "ee", "products/product_analytics")


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


def _runtime_imported_sources(tree: ast.AST) -> set[str]:
    found: set[str] = set()

    class Visitor(ast.NodeVisitor):
        def visit_If(self, node: ast.If) -> None:
            # Type-only imports don't affect runtime test behavior — skip the
            # TYPE_CHECKING branch but still scan its else.
            if _is_type_checking(node.test):
                for stmt in node.orelse:
                    self.visit(stmt)
                return
            self.generic_visit(node)

        def visit_ImportFrom(self, node: ast.ImportFrom) -> None:
            module = node.module or ""
            if module.startswith(SOURCES_PKG):
                found.add(module[len(SOURCES_PKG) :].split(".")[0])

        def visit_Import(self, node: ast.Import) -> None:
            for alias in node.names:
                if alias.name.startswith(SOURCES_PKG):
                    found.add(alias.name[len(SOURCES_PKG) :].split(".")[0])

    Visitor().visit(tree)
    return found


_INPUTS_PREFIX = "backend/temporal/data_imports/sources/"


def _contract_covered_sources(root: Path) -> set[str]:
    turbo = json.loads((root / "products" / "warehouse_sources" / "turbo.json").read_text())
    inputs = turbo["tasks"]["backend:contract-check"]["inputs"]
    covered = {
        rest.split("/")[0]
        for entry in inputs
        if (rest := entry[len(_INPUTS_PREFIX) :]) and entry.startswith(_INPUTS_PREFIX) and "/" in rest
    }
    assert covered, "parsed no source-vendor inputs from turbo.json backend:contract-check"
    return covered


def test_core_coupled_sources_are_covered_by_contract_check():
    root = _repo_root()
    excluded = root / "posthog" / "temporal"  # the Temporal segment; always runs

    imported: set[str] = set()
    for rel in _SCAN_ROOTS:
        base = root / rel
        if not base.exists():
            continue
        for file in base.rglob("*.py"):
            if file.is_relative_to(excluded):
                continue
            text = file.read_text(errors="ignore")
            if "data_imports.sources" not in text:
                continue
            try:
                tree = ast.parse(text, filename=str(file))
            except SyntaxError:
                continue
            imported |= _runtime_imported_sources(tree)

    covered = _contract_covered_sources(root)
    missing = imported - covered
    assert not missing, (
        f"Core/CorePOE code runtime-imports warehouse sources {sorted(missing)} not covered by "
        f"products/warehouse_sources/turbo.json backend:contract-check inputs {sorted(covered)}. "
        f"A change to those sources would skip the Core tests that exercise them. Add "
        f"backend/temporal/data_imports/sources/<vendor>/** to the contract-check inputs."
    )
