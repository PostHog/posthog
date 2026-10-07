import re
import ast
import glob
import json
import functools
from pathlib import Path
from typing import NamedTuple

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
# Limitation: SourceRegistry lookups resolve vendors dynamically, so this guard cannot cover
# dependencies on their config fields. Dependent tests can be skipped on PRs and narrowed
# merge-queue runs; the hourly full master run is the backstop for those dependencies.
#
# Generated configs are watched per module, because watching the package re-runs the Django
# suite for every source. The second test holds that list to what the watched files refer to.
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

_CONTRACT_TASK = "backend:contract-check"
_INPUTS_PREFIX = "backend/temporal/data_imports/sources/"
_GENERATED_CONFIGS_DIR = f"{_INPUTS_PREFIX}generated_configs/"
_GENERATED_CONFIG_REFERENCE = re.compile(r"(?:[\w.]+\.)?sources\.generated_configs(?:\.(\w+))?(?:\.[\w.]+)?")


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


def _task_inputs(root: Path, task: str) -> list[str] | None:
    """The narrowed inputs of a turbo task, or None when turbo watches all of backend/."""
    turbo_path = root / "products" / "warehouse_sources" / "turbo.json"
    if not turbo_path.exists():
        return None
    turbo = json.loads(turbo_path.read_text())
    return turbo.get("tasks", {}).get(task, {}).get("inputs") or None


def _contract_covered_sources(root: Path) -> set[str] | None:
    """Vendor dirs the contract-check inputs watch, or None when every vendor is covered."""
    inputs = _task_inputs(root, _CONTRACT_TASK)
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


@functools.cache
def _input_patterns(inputs: tuple[str, ...]) -> tuple[re.Pattern[str] | None, re.Pattern[str] | None]:
    """The include and exclude globs of an input list, each compiled to one pattern."""

    def compiled(globs: list[str]) -> re.Pattern[str] | None:
        if not globs:
            return None
        return re.compile("|".join(glob.translate(pattern, recursive=True, include_hidden=True) for pattern in globs))

    return (
        compiled([pattern for pattern in inputs if not pattern.startswith("!")]),
        compiled([pattern.removeprefix("!") for pattern in inputs if pattern.startswith("!")]),
    )


def _is_watched(rel: Path, inputs: list[str]) -> bool:
    included, excluded = _input_patterns(tuple(inputs))
    path = rel.as_posix()
    return included is not None and included.match(path) is not None and not (excluded and excluded.match(path))


def _referenced_generated_configs(tree: ast.AST, config_modules: set[str]) -> set[str]:
    dotted: set[str] = set()
    for node in ast.walk(tree):
        match node:
            case ast.ImportFrom(module=str(module), names=names):
                dotted |= {module, *(f"{module}.{alias.name}" for alias in names)}
            case ast.Import(names=names):
                dotted |= {alias.name for alias in names}
            case ast.Constant(value=str(value)):
                dotted.add(value)
    # A name under the package that is not a config module comes from the hand-written __init__.
    return {
        match[1] if match[1] in config_modules else "__init__"
        for path in dotted
        if (match := _GENERATED_CONFIG_REFERENCE.fullmatch(path))
    }


def test_contract_check_watches_exactly_the_generated_configs_it_refers_to() -> None:
    root = _repo_root()
    product_dir = root / "products" / "warehouse_sources"
    configs_dir = product_dir / _GENERATED_CONFIGS_DIR
    inputs = _task_inputs(root, _CONTRACT_TASK)
    if inputs is None or f"{_GENERATED_CONFIGS_DIR}**" in inputs:
        return

    config_modules = {file.stem for file in configs_dir.glob("*.py")}
    referenced: set[str] = set()
    for file in (product_dir / "backend").rglob("*.py"):
        if _is_watched(file.relative_to(product_dir), inputs) and not file.is_relative_to(configs_dir):
            referenced |= _referenced_generated_configs(ast.parse(file.read_text(), filename=str(file)), config_modules)

    watched = {Path(glob).stem for glob in inputs if glob.startswith(_GENERATED_CONFIGS_DIR)}
    assert watched == referenced, (
        "products/warehouse_sources/turbo.json backend:contract-check inputs must list exactly the "
        "generated configs the watched files refer to"
    )


# Guards the backend:test-core-check split of the warehouse_sources suite.
# When a diff changes the product and leaves every core-check input untouched,
# turbo-discover.js runs the suite with the test files among those inputs ignored. That is
# sound only if no core file can execute a file outside the inputs, so the tests below hold
# the inputs closed: every backend file is a core input, a test, or part of a leaf source,
# no core file refers to a leaf source, and no core test iterates the whole catalog.
#
# A test file that is not an input runs on every change to the product. That is where a
# catalog-wide test belongs: sources/tests/, or a core test file the inputs exclude.
#
# Limitation: a core test can reach every source through production code that iterates the
# registry, such as the source wizard endpoint. That is not visible here, and those tests
# do not run on a leaf change.

_CORE_TASK = "backend:test-core-check"
_TYPES_MODULE = "products/warehouse_sources/backend/facade/types.py"
_TEST_DIR_NAMES = frozenset({"test", "tests"})
_CATALOG_WIDE_CALLS = frozenset({"get_all_sources", "get_registered_types", "load_all_sources"})


class _Catalog(NamedTuple):
    vendors: frozenset[str]
    # ExternalDataSourceType member name, member value, and source class name, each mapped
    # to the source directory it selects.
    by_member: dict[str, str]
    by_value: dict[str, str]
    by_class: dict[str, str]


@functools.cache
def _parsed(file: Path) -> ast.Module:
    return ast.parse(file.read_text(), filename=str(file))


@functools.cache
def _catalog(root: Path) -> _Catalog:
    sources_dir = root / "products" / "warehouse_sources" / _INPUTS_PREFIX
    vendors = frozenset(source.parent.name for source in sources_dir.glob("*/source.py"))
    by_squashed_name = {vendor.replace("_", ""): vendor for vendor in vendors}

    by_member: dict[str, str] = {}
    by_value: dict[str, str] = {}
    for node in ast.walk(_parsed(root / _TYPES_MODULE)):
        if not (isinstance(node, ast.ClassDef) and node.name == "ExternalDataSourceType"):
            continue
        for statement in node.body:
            match statement:
                case ast.Assign(
                    targets=[ast.Name(id=member)], value=ast.Tuple(elts=[ast.Constant(value=str(value)), *_])
                ) if vendor := by_squashed_name.get(member.lower()):
                    by_member[member] = vendor
                    by_value[value] = vendor
    assert by_member, "parsed no ExternalDataSourceType members"

    # sources/__init__.py re-exports every class that _load_all imports, so a core file can
    # import a source by class name without naming its directory.
    by_class = {
        alias.asname or alias.name: node.module.split(".")[0]
        for node in ast.walk(_parsed(sources_dir / "_load_all.py"))
        if isinstance(node, ast.ImportFrom) and node.module and node.module.split(".")[0] in vendors
        for alias in node.names
    }
    return _Catalog(vendors, by_member, by_value, by_class)


def _is_test_module(rel: Path) -> bool:
    return rel.name.startswith("test_") or rel.name.endswith("_test.py")


def _is_test_code(rel: Path) -> bool:
    return _is_test_module(rel) or rel.name == "conftest.py" or bool(_TEST_DIR_NAMES.intersection(rel.parts))


@functools.cache
def _backend_files(root: Path) -> tuple[Path, ...]:
    product_dir = root / "products" / "warehouse_sources"
    return tuple(file.relative_to(product_dir) for file in (product_dir / "backend").rglob("*.py"))


def _core_files(root: Path, inputs: list[str]) -> list[Path]:
    core = [rel for rel in _backend_files(root) if _is_watched(rel, inputs)]
    assert core, f"{_CORE_TASK} inputs match no file"
    return core


def _dotted_references(tree: ast.AST, package: str) -> set[str]:
    """Every module path a file imports or names in a string, with relative imports resolved."""
    dotted: set[str] = set()

    class Visitor(ast.NodeVisitor):
        def visit_If(self, node: ast.If) -> None:
            if _is_type_checking(node.test):
                for statement in node.orelse:
                    self.visit(statement)
                return
            self.generic_visit(node)

        def visit_ImportFrom(self, node: ast.ImportFrom) -> None:
            module = node.module or ""
            if node.level:
                parents = package.split(".")
                parents = parents[: len(parents) - (node.level - 1)]
                module = ".".join([*parents, module] if module else parents)
            dotted.add(module)
            dotted.update(f"{module}.{alias.name}" for alias in node.names)

        def visit_Import(self, node: ast.Import) -> None:
            dotted.update(alias.name for alias in node.names)

        def visit_Constant(self, node: ast.Constant) -> None:
            if isinstance(node.value, str):
                dotted.add(node.value)

    Visitor().visit(tree)
    return dotted


def _sources_named_by_type(tree: ast.AST, catalog: _Catalog) -> set[str]:
    """Sources a file selects by ExternalDataSourceType member or by the member's value."""
    named: set[str] = set()
    for node in ast.walk(tree):
        match node:
            case ast.Attribute(
                value=ast.Name(id="ExternalDataSourceType") | ast.Attribute(attr="ExternalDataSourceType"),
                attr=member,
            ) if member in catalog.by_member:
                named.add(catalog.by_member[member])
            case ast.Constant(value=str(value)) if value in catalog.by_value:
                named.add(catalog.by_value[value])
    return named


def _leaf_files_referenced(rel: Path, root: Path) -> set[str]:
    """Product-relative paths of the files outside the core a core file can execute."""
    product_dir = root / "products" / "warehouse_sources"
    catalog = _catalog(root)
    tree = _parsed(product_dir / rel)
    package = ".".join(("products", "warehouse_sources", *rel.parent.parts))
    referenced: set[str] = set()
    for dotted in _dotted_references(tree, package):
        if "sources" not in dotted:
            continue
        target = _vendor_from_target(dotted)
        vendor = target if target in catalog.vendors else catalog.by_class.get(target or "")
        if vendor:
            referenced.add(f"{_INPUTS_PREFIX}{vendor}/source.py")
        elif target == "_load_all" and rel != Path(_INPUTS_PREFIX, "__init__.py"):
            referenced.add(f"{_INPUTS_PREFIX}_load_all.py")
        elif match := _GENERATED_CONFIG_REFERENCE.fullmatch(dotted):
            if match[1] and (product_dir / _GENERATED_CONFIGS_DIR / f"{match[1]}.py").exists():
                referenced.add(f"{_GENERATED_CONFIGS_DIR}{match[1]}.py")
    # Production code compares source types without running the source. A test that names
    # one usually asks the registry for it.
    if _is_test_code(rel):
        referenced |= {f"{_INPUTS_PREFIX}{vendor}/source.py" for vendor in _sources_named_by_type(tree, catalog)}
    return referenced


def test_core_test_inputs_cover_every_file_outside_a_leaf_source() -> None:
    root = _repo_root()
    inputs = _task_inputs(root, _CORE_TASK)
    if inputs is None:
        return

    # The entries of sources/ that hold leaf files: each source, its generated config, and
    # the module that imports every source.
    leaf_entries = {*_catalog(root).vendors, "generated_configs", "_load_all.py"}
    sources_parts = Path(_INPUTS_PREFIX).parts
    unwatched = sorted(
        str(rel)
        for rel in _backend_files(root)
        if not _is_watched(rel, inputs)
        and not _is_test_module(rel)
        and not (rel.parts[: len(sources_parts)] == sources_parts and rel.parts[len(sources_parts)] in leaf_entries)
    )
    assert not unwatched, (
        f"{unwatched[:10]} are outside every source directory and are not {_CORE_TASK} inputs in "
        "products/warehouse_sources/turbo.json. A change to them would skip the product's core tests. "
        "Add them to the inputs."
    )

    contract_inputs = _task_inputs(root, _CONTRACT_TASK) or []
    contract_only = sorted(
        str(rel) for rel in _backend_files(root) if _is_watched(rel, contract_inputs) and not _is_watched(rel, inputs)
    )
    assert not contract_only, (
        f"{contract_only[:10]} are {_CONTRACT_TASK} inputs and are not {_CORE_TASK} inputs. "
        "A contract change must run the whole suite."
    )

    # The root turbo.json has full-line comments, which json.loads rejects.
    root_turbo = json.loads(re.sub(r"^\s*//.*$", "", (root / "turbo.json").read_text(), flags=re.MULTILINE))
    outside_product = {
        pattern for pattern in root_turbo["tasks"]["backend:test"]["inputs"] if pattern.startswith("../")
    }
    assert outside_product <= set(inputs), (
        f"{sorted(outside_product - set(inputs))} are backend:test inputs outside the product and are not "
        f"{_CORE_TASK} inputs. A change to them marks the product changed and must run the whole suite."
    )


def test_core_test_inputs_never_reach_a_leaf_source() -> None:
    root = _repo_root()
    inputs = _task_inputs(root, _CORE_TASK)
    if inputs is None:
        return

    unwatched: dict[str, str] = {}
    for rel in _core_files(root, inputs):
        for leaf in _leaf_files_referenced(rel, root):
            if not _is_watched(Path(leaf), inputs):
                unwatched.setdefault(leaf, str(rel))
    assert not unwatched, (
        f"Core files refer to files that are not {_CORE_TASK} inputs in products/warehouse_sources/turbo.json: "
        f"{dict(sorted(unwatched.items())[:10])}. A change to those files would skip the core tests that "
        "exercise them. Add each source directory and its generated config to the inputs."
    )


def test_core_tests_do_not_iterate_every_source() -> None:
    root = _repo_root()
    product_dir = root / "products" / "warehouse_sources"
    inputs = _task_inputs(root, _CORE_TASK)
    if inputs is None:
        return

    catalog_wide = sorted(
        str(rel)
        for rel in _core_files(root, inputs)
        if _is_test_module(rel)
        and any(
            (isinstance(node, ast.Attribute) and node.attr in _CATALOG_WIDE_CALLS)
            or (isinstance(node, ast.Name) and node.id in _CATALOG_WIDE_CALLS)
            for node in ast.walk(_parsed(product_dir / rel))
        )
    )
    assert not catalog_wide, (
        f"{catalog_wide} iterate every registered source and are {_CORE_TASK} inputs, so they do not run "
        "when a pull request changes only a leaf source. Move the catalog-wide test to "
        f"{_INPUTS_PREFIX}tests/, or exclude the file from the inputs."
    )
