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
# The generated source configs are watched one module at a time. Watching the whole package
# would re-run the Django suite for every source, including the ones only this product's tests
# exercise. A config is part of the contract when a watched file refers to it, by an import or
# by a lazy re-export string. The second test holds the watched configs to exactly that set.
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
_GENERATED_CONFIGS_DIR = f"{_INPUTS_PREFIX}generated_configs/"
_GENERATED_CONFIGS_PACKAGE = "sources.generated_configs"


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


def _contract_check_inputs(root: Path) -> list[str] | None:
    """The narrowed contract-check inputs, or None when the product has no narrowing override —
    turbo then falls back to watching all of backend/, so there is nothing to enumerate."""
    turbo_path = root / "products" / "warehouse_sources" / "turbo.json"
    if not turbo_path.exists():
        return None
    turbo = json.loads(turbo_path.read_text())
    return turbo.get("tasks", {}).get("backend:contract-check", {}).get("inputs") or None


def _contract_covered_sources(root: Path) -> set[str] | None:
    """Vendor dirs the narrowed contract-check inputs watch, or None when every vendor is
    covered."""
    inputs = _contract_check_inputs(root)
    if inputs is None:
        return None
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
    if covered is None:
        return
    missing = coupled_vendors - covered
    assert not missing, (
        f"Core/CorePOE reaches warehouse sources {sorted(missing)} through the facade, but they are "
        f"not covered by products/warehouse_sources/turbo.json backend:contract-check inputs "
        f"{sorted(covered)}. A change to those sources would skip the Core tests that exercise them. "
        f"Add backend/temporal/data_imports/sources/<vendor>/** to the contract-check inputs."
    )


def _input_matches(glob: str, rel: str) -> bool:
    return rel.startswith(glob.removesuffix("**")) if glob.endswith("/**") else rel == glob


def _watched_files(product_dir: Path, inputs: list[str]) -> list[Path]:
    """The Python files the contract-check inputs watch, outside the generated configs."""
    positive = [glob for glob in inputs if not glob.startswith("!")]
    negative = [glob.removeprefix("!") for glob in inputs if glob.startswith("!")]
    # _input_matches reads two shapes only: an exact file and `dir/**`.
    unsupported = [glob for glob in positive + negative if "*" in glob.removesuffix("/**")]
    assert not unsupported, f"contract-check inputs use a glob shape this guard cannot read: {unsupported}"
    watched = []
    for file in (product_dir / "backend").rglob("*.py"):
        rel = file.relative_to(product_dir).as_posix()
        if rel.startswith(_GENERATED_CONFIGS_DIR):
            continue
        if any(_input_matches(g, rel) for g in positive) and not any(_input_matches(g, rel) for g in negative):
            watched.append(file)
    return watched


def _generated_configs_referenced(tree: ast.AST, config_modules: set[str]) -> set[str]:
    """The generated config modules a file refers to: by `from`-import, by plain import, or by a
    dotted-path string such as a lazy re-export target. A reference to the package itself is the
    hand-written resolver, `__init__`."""
    dotted: list[str] = []
    for node in ast.walk(tree):
        if isinstance(node, ast.ImportFrom) and node.module:
            dotted.append(node.module)
            if node.module.endswith(_GENERATED_CONFIGS_PACKAGE):
                dotted.extend(f"{node.module}.{alias.name}" for alias in node.names)
        elif isinstance(node, ast.Import):
            dotted.extend(alias.name for alias in node.names)
        elif isinstance(node, ast.Constant) and isinstance(node.value, str) and " " not in node.value:
            dotted.append(node.value)

    referenced: set[str] = set()
    for path in dotted:
        _, found, rest = path.partition(_GENERATED_CONFIGS_PACKAGE)
        if not found or (rest and not rest.startswith(".")):
            continue
        module = rest.removeprefix(".").split(".")[0]
        referenced.add(module if module in config_modules else "__init__")
    return referenced


def test_watched_generated_configs_are_exactly_the_ones_the_contract_refers_to():
    product_dir = _repo_root() / "products" / "warehouse_sources"
    inputs = _contract_check_inputs(product_dir.parent.parent)
    if inputs is None:
        return
    watched_configs = {
        glob.removeprefix(_GENERATED_CONFIGS_DIR) for glob in inputs if glob.startswith(_GENERATED_CONFIGS_DIR)
    }
    if "**" in watched_configs:
        return

    config_modules = {file.stem for file in (product_dir / _GENERATED_CONFIGS_DIR).glob("*.py")}
    referred: set[str] = set()
    for file in _watched_files(product_dir, inputs):
        referred |= _generated_configs_referenced(ast.parse(file.read_text(), filename=str(file)), config_modules)
    assert referred, "found no generated config reference in the watched warehouse_sources files"

    expected = {f"{module}.py" for module in referred}
    missing = sorted(_GENERATED_CONFIGS_DIR + name for name in expected - watched_configs)
    stale = sorted(_GENERATED_CONFIGS_DIR + name for name in watched_configs - expected)
    assert not missing and not stale, (
        "products/warehouse_sources/turbo.json backend:contract-check inputs do not match the generated "
        "configs the watched files refer to. A missing config skips the Django suite when it changes. "
        f"A stale one re-runs the suite for nothing. Add: {missing}. Remove: {stale}."
    )
