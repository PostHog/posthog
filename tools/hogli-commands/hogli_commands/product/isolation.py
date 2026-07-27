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
import ast
import json
import tomllib
import functools
from collections.abc import Iterator
from dataclasses import dataclass
from pathlib import Path

from .ast_helpers import (
    ast_parse_safe,
    get_imported_module_names,
    has_any_function_defs,
    lazy_reexport_map,
    module_dunder_all,
    module_level_import_froms,
    tree_has_top_level_functions,
)
from .paths import REPO_ROOT, TACH_TOML, get_tach_block

# ---------------------------------------------------------------------------
# tach.toml parsing
# ---------------------------------------------------------------------------


# A tach [[interfaces]] block carrying this marker in the comment lines directly above it
# exposes internals that core depends on *permanently* and outside the import-reroute path —
# ClickHouse DDL consumed by core's schema registry and frozen migrations, which can never be
# routed through the facade. Such a block is NOT a legacy leak: the modules stay walled off
# from every importer except the declared consumers, and turbo.json must re-run the Django
# suite on any change to them (enforced by IsolationChainCheck) so the skip stays sound.
PERMANENT_INTERFACE_MARKER = "isolation:permanent-interface"


def _block_is_permanent(tach_content: str, header_start: int) -> bool:
    """True if the [[interfaces]] header at header_start is preceded by the permanent marker.

    Scans the comment lines immediately above the header (blank lines allowed between the
    comment and the header), stopping at the first line of TOML content — which, between two
    blocks, is always the previous block's body, so a marker can't leak across block boundaries.
    """
    for line in reversed(tach_content[:header_start].splitlines()):
        stripped = line.strip()
        if not stripped:
            continue
        if stripped.startswith("#"):
            if PERMANENT_INTERFACE_MARKER in stripped:
                return True
            continue
        break
    return False


def _iter_interface_blocks_raw(tach_content: str) -> Iterator[tuple[list[str], list[str], bool]]:
    """Yield (expose_patterns, from_patterns, is_permanent) for every [[interfaces]] block."""
    for match in re.finditer(r"\[\[interfaces\]\]\s*\n(.*?)(?=\[\[|\Z)", tach_content, re.DOTALL):
        block = match.group(1)
        expose_match = re.search(r"expose\s*=\s*\[(.*?)\]", block, re.DOTALL)
        from_match = re.search(r"from\s*=\s*\[(.*?)\]", block, re.DOTALL)
        if not expose_match or not from_match:
            continue
        expose_patterns = re.findall(r'"(.*?)"', expose_match.group(1))
        from_patterns = re.findall(r'"(.*?)"', from_match.group(1))
        yield expose_patterns, from_patterns, _block_is_permanent(tach_content, match.start())


def iter_interface_blocks(tach_content: str) -> Iterator[tuple[list[str], list[str]]]:
    """Yield (expose_patterns, from_patterns) for every [[interfaces]] block."""
    for expose_patterns, from_patterns, _permanent in _iter_interface_blocks_raw(tach_content):
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

    A block carrying the PERMANENT_INTERFACE_MARKER is exempt — its exposure is a
    declared, irreducible non-import coupling (see permanent_interface_modules), not
    a leak to be drained.
    """
    for expose_patterns, from_patterns, is_permanent in _iter_interface_blocks_raw(tach_content):
        if is_permanent:
            continue
        normalized_from = [p.replace("\\", "") for p in from_patterns]
        if normalized_from != [module_path]:
            continue
        if any(not pattern_targets_public_surface(p) for p in expose_patterns):
            return True
    return False


def _normalize_exposed_module(pattern: str) -> str:
    """'backend\\.sql.*' -> 'backend.sql'; 'backend\\.embedding.*' -> 'backend.embedding'."""
    normalized = pattern.replace("\\", "")
    return normalized[:-2] if normalized.endswith(".*") else normalized


def permanent_interface_modules(tach_content: str, module_path: str) -> set[str]:
    """Module roots a product permanently exposes to core via a marked [[interfaces]] block.

    These are non-import-behavioral couplings — ClickHouse DDL imported by core's schema
    registry and frozen migrations — that cannot be rerouted through the facade. The marker
    keeps the external seal honest rather than leaving the block to read as a temporary leak:
    the modules stay walled off for every importer except the declared consumers, and the
    returned set is what turbo.json must keep in its contract-check inputs so a change to them
    still re-runs the Django suite (enforced by IsolationChainCheck).
    """
    modules: set[str] = set()
    for expose_patterns, from_patterns, is_permanent in _iter_interface_blocks_raw(tach_content):
        if not is_permanent:
            continue
        if [p.replace("\\", "") for p in from_patterns] != [module_path]:
            continue
        modules.update(_normalize_exposed_module(p) for p in expose_patterns if not pattern_targets_public_surface(p))
    return modules


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
# backend/facade_legacy/** can't pass.
_FACADE_PREFIX = "backend/facade/"
_FACADE_PRESENTATION_PREFIXES = (_FACADE_PREFIX, "backend/presentation/")
_ROUTES_PREFIXES = ("backend/routes.py", "backend/routes/")

# The wiring locations ("garages"). A garage prefix is either a directory (trailing slash) or a
# single-file module; a class re-exported from one of these is accepted wiring, everything else is
# a leak. See products/architecture.md § Wiring couplings.
GARAGE_PREFIXES: tuple[str, ...] = (
    "backend/hogql_queries/",
    "backend/max_tools.py",
    "backend/temporal/",
    "backend/tasks.py",
    "backend/tasks/",
)


def _glob_targets(glob: str, prefixes: tuple[str, ...]) -> bool:
    """Anchored prefix test for a contract-check input glob. removeprefix (not lstrip, which strips
    a char set) trims only a literal './' so a '../escape/**' can't be normalized into an accepted
    path."""
    return glob.removeprefix("./").startswith(prefixes)


def _module_input_prefixes(module: str) -> tuple[str, ...]:
    """A permanently-exposed module's accepted contract-check input forms.

    'backend.sql' -> ('backend/sql.py', 'backend/sql/') so either a single-file module or a
    package satisfies coverage."""
    path = module.replace(".", "/")
    return (f"{path}.py", f"{path}/")


def location_input_glob(location: str) -> str:
    """A backend-relative location -> the turbo input glob that watches it.

    'backend/tasks/' -> 'backend/tasks/**'; a single-file location stays itself."""
    return f"{location.rstrip('/')}/**" if location.endswith("/") else location


def has_narrowed_turbo_inputs(
    product_dir: Path,
    permanent_modules: frozenset[str] = frozenset(),
    carveout_modules: frozenset[str] = frozenset(),
) -> bool:
    """True only when contract-check inputs are confined to the public surface AND at least one
    targets facade/presentation. A broad glob like backend/** alongside a facade entry keeps the
    skip inert, and a routes-only narrowing isn't a real contract surface — both are rejected.
    Negated globs ('!...') are excluded from the surface test.

    Permanently-exposed modules, garage wiring locations, and carve-out modules all count as
    extended surface: a product may list them without forfeiting the narrowing, since core depends
    on each outside the plain facade->contracts channel and they must re-run the suite on change
    (see uncovered_permanent_modules, unwatched_garages, and the carve-out coverage check)."""
    inputs = [i for i in contract_check_inputs(product_dir) if not i.startswith("!")]
    if not inputs:
        return False
    permanent_prefixes = tuple(p for m in permanent_modules for p in _module_input_prefixes(m))
    accepted = (
        _FACADE_PRESENTATION_PREFIXES
        + _ROUTES_PREFIXES
        + GARAGE_PREFIXES
        + permanent_prefixes
        + tuple(carveout_modules)
    )
    return all(_glob_targets(i, accepted) for i in inputs) and any(
        _glob_targets(i, _FACADE_PRESENTATION_PREFIXES) for i in inputs
    )


def _input_covers(input_glob: str, accepted: str) -> bool:
    """A directory location (trailing slash) is covered by any input inside it; a single-file
    location only by an exact input — backend/tasks.py.bak must not count as watching
    backend/tasks.py."""
    if accepted.endswith("/"):
        return input_glob.startswith(accepted)
    return input_glob == accepted


def _uncovered_locations(product_dir: Path, targets_to_prefixes: dict[str, tuple[str, ...]]) -> set[str]:
    """Targets whose accepted input forms match no narrowed contract-check input.

    Empty when the product has no narrowing override — everything is watched, so nothing is
    uncovered. Shared by the permanent-exposure, garage, and carve-out coverage checks: same
    anchored predicate everywhere, the convention is location-level, no glob simulation."""
    if not targets_to_prefixes:
        return set()
    inputs = [i.removeprefix("./") for i in contract_check_inputs(product_dir) if not i.startswith("!")]
    if not inputs:
        return set()
    return {
        target
        for target, prefixes in targets_to_prefixes.items()
        if not any(_input_covers(i, p) for i in inputs for p in prefixes)
    }


def uncovered_permanent_modules(product_dir: Path, permanent_modules: frozenset[str]) -> set[str]:
    """Permanently-exposed modules with no matching contract-check input glob.

    Each such module is a non-import channel into core; if turbo.json doesn't re-run the suite
    on its change, the skip is unsound. IsolationChainCheck turns a non-empty result into a
    blocking issue, mirroring the routes-watching rule."""
    return _uncovered_locations(product_dir, {m: _module_input_prefixes(m) for m in permanent_modules})


# ---------------------------------------------------------------------------
# Permanent-interface qualification — the marker can only cover genuinely irreducible DDL
# ---------------------------------------------------------------------------


# Products whose permanent-interface marker is justified by a coupling channel other than
# ClickHouse DDL, so the DDL-qualification rule below doesn't apply. warehouse_sources: core's
# HogQL direct-SQL adapters and system tables reach source internals through the facade's lazy
# (PEP 562) re-exports; the exposed set is pinned by the product's own guard test
# (test_ci_core_coupled_sources.py) and stays watched via the turbo-input rule above. Extending
# this set requires a devex-reviewed change here — which is the point.
_QUALIFICATION_EXEMPT_PRODUCTS: frozenset[str] = frozenset({"products.warehouse_sources"})


@functools.cache
def _clickhouse_ddl_imports(repo_root: Path) -> frozenset[str]:
    """Dotted module paths imported by the consumers of a permanent DDL interface outside the
    import-reroute path: the frozen ClickHouse migrations and the schema registry.

    Extracted from real import statements via AST (get_imported_module_names), so a module path
    that only appears in a comment, docstring, or string literal can't qualify a marker.

    Cached per repo_root — product:lint runs the qualification check once per product, and
    re-parsing ~250 migration files each time would dominate the lint.
    """
    migrations_dir = repo_root / "posthog" / "clickhouse" / "migrations"
    schema_file = repo_root / "posthog" / "clickhouse" / "schema.py"
    files = sorted(migrations_dir.glob("*.py")) if migrations_dir.is_dir() else []
    if schema_file.exists():
        files.append(schema_file)
    imported: set[str] = set()
    for path in files:
        tree = ast_parse_safe(path)
        if tree is not None:
            imported.update(get_imported_module_names(tree))
    return frozenset(imported)


def _module_is_imported(imported: frozenset[str], full_dotted_path: str) -> bool:
    """True if the module itself or any of its submodules is imported."""
    return any(imp == full_dotted_path or imp.startswith(full_dotted_path + ".") for imp in imported)


def unqualified_permanent_modules(
    module_path: str, permanent_modules: frozenset[str], *, repo_root: Path = REPO_ROOT
) -> set[str]:
    """Permanently-exposed module roots that don't actually qualify as an irreducible interface.

    The permanent-interface marker is only legitimate for modules core depends on outside the
    import graph — ClickHouse DDL imported by a frozen migration or the schema registry. This is
    the mechanical guard against abusing it: a module (e.g. 'backend.sql') qualifies only if its
    full dotted path (e.g. 'products.error_tracking.backend.sql') is imported by one of those
    consumers. Any marked module with no such import is returned, and IsolationChainCheck turns
    a non-empty result into a blocking issue — the marker can't be used to smuggle 'backend.models'
    or 'backend.logic' past the isolation seal.
    """
    if not permanent_modules or module_path in _QUALIFICATION_EXEMPT_PRODUCTS:
        return set()
    imported = _clickhouse_ddl_imports(repo_root)
    return {root for root in permanent_modules if not _module_is_imported(imported, f"{module_path}.{root}")}


def routes_in_turbo_inputs(product_dir: Path) -> bool:
    """True if contract-check inputs watch the routes module specifically — backend/routes.py or a
    backend/routes/ package. Anchored and negation-aware, so a glob that merely contains 'routes',
    or a negated exclusion like !backend/routes.py, doesn't falsely count the routes module as
    watched (without it, a routes-only change is invisible to the skip and runs no Django suite)."""
    return any(_glob_targets(i, _ROUTES_PREFIXES) for i in contract_check_inputs(product_dir) if not i.startswith("!"))


# ---------------------------------------------------------------------------
# Wiring couplings — the facade's class-crossing surface
# ---------------------------------------------------------------------------
#
# A class only crosses the boundary soundly if it implements a core-owned base and lives in a
# wiring location ("garage", GARAGE_PREFIXES above) core keeps in the contract-check inputs. These
# checks catch the two ways that breaks: a facade re-exporting a class from somewhere that ISN'T a
# garage, and a garage that exists but isn't watched. See products/architecture.md § Wiring couplings.


# Sanctioned model-registry carve-outs, keyed (product, class). These model classes cross the
# facade for a core registry keyed by class identity (team-extension and the file-system unfiled
# registry) — the only classes allowed to cross that aren't wiring implementations. They are never
# flagged, but a narrowed product must still keep the defining module in its contract-check inputs.
# Bar for adding an entry: there must be a core registry keyed by class identity that needs it, AND
# a matching amendment to products/architecture.md § Wiring couplings naming the registry.
CARVE_OUTS: frozenset[tuple[str, str]] = frozenset(
    {
        ("customer_analytics", "TeamCustomerAnalyticsConfig"),
        ("tasks", "Task"),
    }
)


@dataclass(frozen=True)
class FacadeClassImport:
    """A class a facade module re-exports from a product-internal, non-garage module."""

    facade_module: str  # e.g. "queries.py"
    class_name: str  # e.g. "MetricsQueryRunner"
    source_path: str  # backend-relative, e.g. "backend/metrics_query_runner.py"


def _product_backend_root(backend_dir: Path) -> str:
    """The product's own backend package as a dotted prefix, e.g. 'products.metrics.backend'."""
    return f"products.{backend_dir.parent.name}.backend"


def _module_package_parts(source_path: str) -> list[str]:
    """The package a module belongs to, as backend-relative parts, for resolving relative imports.

    'backend/facade/queries.py' -> ['facade'] (its container); 'backend/logic/matrix/' (a package,
    trailing slash) -> ['logic', 'matrix'] (a package's relative imports are rooted at itself)."""
    trimmed = source_path.removeprefix("backend/")
    if trimmed.endswith("/"):
        return [p for p in trimmed.strip("/").split("/") if p]
    return trimmed.rsplit("/", 1)[0].split("/") if "/" in trimmed else []


def _resolve_relative(package_parts: list[str], level: int, module: str | None) -> str | None:
    """A relative import from a package -> its module path relative to backend, or None if it climbs
    above backend/ (nothing there is product-internal to this backend). level 1 is the package
    itself, level 2 its parent, etc."""
    climb = level - 1
    if climb > len(package_parts):
        return None
    remaining = package_parts[: len(package_parts) - climb]
    if module:
        remaining = remaining + module.split(".")
    return "/".join(remaining)


def _resolve_absolute_module(module: str, backend_dir: Path) -> str | None:
    """An absolute import -> its module path relative to backend_dir, or None if it's not this
    product's backend (third-party, core, or another product all return None)."""
    root = _product_backend_root(backend_dir)
    if module == root:
        return ""
    if module.startswith(root + "."):
        return module[len(root) + 1 :].replace(".", "/")
    return None


def _backend_rel_path(module_rel: str, backend_dir: Path) -> str | None:
    """A module path relative to backend_dir -> a backend-relative on-disk path, or None.

    Resolves to the file that actually holds definitions: 'models' -> 'backend/models.py' if that
    file exists, else 'backend/models/' for a package. The trailing slash on a package lets the
    result be prefix-tested against GARAGE_PREFIXES the same way an input glob is."""
    if module_rel == "":
        return "backend/"
    file_path = backend_dir / f"{module_rel}.py"
    if file_path.is_file():
        return f"backend/{module_rel}.py"
    dir_path = backend_dir / module_rel
    if dir_path.is_dir():
        return f"backend/{module_rel}/"
    return None


def _source_file(source_path: str, backend_dir: Path) -> Path:
    """The on-disk file for a backend-relative module path (a package resolves to its __init__.py)."""
    if source_path.endswith("/"):
        return backend_dir.parent / source_path.rstrip("/") / "__init__.py"
    return backend_dir.parent / source_path


def _name_is_class(
    source_path: str,
    name: str,
    backend_dir: Path,
    hops: int = 1,
    cache: dict[Path, ast.Module | None] | None = None,
) -> bool:
    """True if `name` resolves to a class in the module at source_path.

    Follows relative re-exports one hop by default, so a class defined in a submodule and surfaced
    through the package __init__ (the common `from .thing import Thing` shape) still counts. Never
    leaves this product's backend — an absolute or third-party re-export ends the chain.

    `cache` memoizes parses per source file for the duration of one facade traversal, so a
    multi-name import doesn't re-parse the same module once per alias."""
    if cache is None:
        cache = {}
    file_path = _source_file(source_path, backend_dir)
    if file_path not in cache:
        cache[file_path] = ast_parse_safe(file_path)
    tree = cache[file_path]
    if tree is None:
        return False
    if name in {n.name for n in ast.iter_child_nodes(tree) if isinstance(n, ast.ClassDef)}:
        return True
    if hops <= 0:
        return False
    package_parts = _module_package_parts(source_path)
    for level, module, aliases in module_level_import_froms(tree):
        if level == 0:
            continue
        for orig, asname in aliases:
            if (asname or orig) != name:
                continue
            module_rel = _resolve_relative(package_parts, level, module)
            if module_rel is None:
                continue
            nested = _backend_rel_path(module_rel, backend_dir)
            if nested is not None and _name_is_class(nested, orig, backend_dir, hops - 1, cache):
                return True
    return False


def _resolve_dotted_source(dotted: str, backend_dir: Path) -> str | None:
    """A lazy-map source value ('logic.crud' or 'products.x.backend.logic.crud') -> backend path."""
    module_rel = _resolve_absolute_module(dotted, backend_dir)
    if module_rel is None:
        # Lazy maps commonly store the value relative to the product's backend package.
        module_rel = dotted.replace(".", "/")
    return _backend_rel_path(module_rel, backend_dir)


def _is_facade_or_garage(source_path: str) -> bool:
    return source_path.startswith((_FACADE_PREFIX, *GARAGE_PREFIXES))


def _is_test_module(filename: str) -> bool:
    return filename.startswith("test_") or filename.endswith("_test.py")


def _iter_facade_class_reexports(backend_dir: Path) -> Iterator[FacadeClassImport]:
    """Every product-internal class a facade module hands out, from a non-facade, non-garage module —
    carve-outs included (callers filter). Three shapes are read:

      - a pure re-export module (no top-level function definitions) hands out every class it imports.
      - a data-capability module (api.py and its split-out siblings, which hold functions that
        convert models to contracts) legitimately imports internal classes for its own use, so only
        deliberate re-exports count as handed out: names in its literal `__all__`, plus names
        imported with the explicit self-alias idiom (`from ..x import Foo as Foo` — the shape that
        also suppresses ruff's F401, so it would otherwise be invisible to every lint).
      - a PEP 562 `_LAZY`/`_MODULES` map hands out every class it maps, read regardless of shape.
    """
    facade_dir = backend_dir / "facade"
    if not facade_dir.is_dir():
        return
    parse_cache: dict[Path, ast.Module | None] = {}
    for module_file in sorted(facade_dir.glob("*.py")):
        # contracts/enums are the sanctioned homes for data types; test modules that happen to sit
        # in facade/ are pytest files, not re-export surface. Neither is a wiring re-export.
        if module_file.name in ("contracts.py", "enums.py") or _is_test_module(module_file.name):
            continue
        tree = ast_parse_safe(module_file)
        if tree is None:
            continue
        # A pure re-export module hands out everything it imports; a data-capability module only
        # its deliberate re-exports (__all__ membership or the Foo-as-Foo self-alias).
        is_pure_reexport = not tree_has_top_level_functions(tree)
        allowed = None if is_pure_reexport else module_dunder_all(tree)
        for level, module, aliases in module_level_import_froms(tree):
            module_rel = (
                _resolve_relative(["facade"], level, module)
                if level > 0
                else _resolve_absolute_module(module or "", backend_dir)
            )
            if module_rel is None:
                continue
            source_path = _backend_rel_path(module_rel, backend_dir)
            if source_path is None or _is_facade_or_garage(source_path):
                continue
            for orig, asname in aliases:
                bound = asname or orig
                handed_out = is_pure_reexport or (allowed is not None and bound in allowed) or asname == orig
                if not handed_out:
                    continue
                if _name_is_class(source_path, orig, backend_dir, cache=parse_cache):
                    yield FacadeClassImport(module_file.name, orig, source_path)
        for name, dotted in lazy_reexport_map(tree).items():
            source_path = _resolve_dotted_source(dotted, backend_dir)
            if source_path is None or _is_facade_or_garage(source_path):
                continue
            if _name_is_class(source_path, name, backend_dir, cache=parse_cache):
                yield FacadeClassImport(module_file.name, name, source_path)


def _split_facade_reexports(backend_dir: Path, name: str) -> tuple[list[FacadeClassImport], set[str]]:
    """One facade traversal, split into (unsanctioned leaks, carve-out defining modules)."""
    leaks: list[FacadeClassImport] = []
    carveout_modules: set[str] = set()
    for f in _iter_facade_class_reexports(backend_dir):
        if (name, f.class_name) in CARVE_OUTS:
            carveout_modules.add(f.source_path)
        else:
            leaks.append(f)
    return leaks, carveout_modules


def facade_class_imports(backend_dir: Path, name: str) -> list[FacadeClassImport]:
    """Classes the facade re-exports from a non-garage internal module, minus sanctioned carve-outs.

    Each is a class the facade can hand out that the wiring doctrine doesn't sanction. The remedy is
    always one of three: move it to a garage (if it implements a core-owned base), to
    facade/contracts.py (if it's a data/error type), or drop the turbo.json narrowing.

    Division of labor: deliberate re-exports from a function-bearing facade module must surface via
    __all__ or the Foo-as-Foo self-alias idiom — both counted here — while an imported-and-unused
    leftover is ruff F401's job. The residual hole is therefore only a class that is imported plainly,
    genuinely used inside function bodies, AND separately imported by core anyway — core-side misuse
    this lint doesn't chase."""
    return _split_facade_reexports(backend_dir, name)[0]


def facade_carveout_modules(backend_dir: Path, name: str) -> set[str]:
    """Backend-relative modules that define the carve-out classes this product's facade re-exports.

    A narrowed product must keep these in its contract-check inputs, exactly like a garage."""
    return _split_facade_reexports(backend_dir, name)[1]


def unwatched_garages(product_dir: Path) -> set[str]:
    """Garage locations present in the product but missing from its (narrowed) contract-check inputs.

    The accepted prefix keeps the garage's trailing slash, so a directory garage is only covered
    by an input inside it — backend/tasks.py or backend/tasks_extra/** must not count as watching
    backend/tasks/ (same anchoring as _module_input_prefixes)."""
    present = {g for g in GARAGE_PREFIXES if (product_dir / g.rstrip("/")).exists()}
    return _uncovered_locations(product_dir, {g: (g,) for g in present})


def uncovered_carveout_modules(product_dir: Path, carveout_modules: frozenset[str]) -> set[str]:
    """Carve-out defining modules re-exported by the facade but absent from contract-check inputs.

    A carve-out class crosses the boundary for a class-identity registry, so a change to its
    defining module is a coupling change core must re-test — exactly like a permanent exposure."""
    return _uncovered_locations(product_dir, {m: (m,) for m in carveout_modules})


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
    # Module roots permanently exposed to core outside the import-reroute path (declared via the
    # permanent-interface marker in tach.toml). They are not leaks, but turbo.json must keep them
    # in its contract-check inputs — uncovered_permanent_exposures lists any that don't.
    permanent_exposures: tuple[str, ...] = ()
    uncovered_permanent_exposures: tuple[str, ...] = ()
    # Marked permanent modules that aren't imported by any frozen ClickHouse migration or the
    # schema registry — so they don't qualify as irreducible interfaces and the marker is being
    # abused to keep an internal (models/logic) walled off. IsolationChainCheck blocks on these.
    unqualified_permanent_exposures: tuple[str, ...] = ()
    # Classes the facade re-exports from a non-garage, non-carve-out internal module — behavior
    # crossing the boundary that the wiring doctrine doesn't sanction (see facade_class_imports).
    # Blocks narrowing; a warning-only signal while the product is still un-narrowed.
    facade_leaks: tuple[FacadeClassImport, ...] = ()
    # Garage wiring locations present in the product but missing from a narrowed product's inputs,
    # and carve-out modules missing the same way. Both keep the skip sound and block when narrowed.
    unwatched_garages: tuple[str, ...] = ()
    uncovered_carveout_modules: tuple[str, ...] = ()

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
    repo_root: Path | None = None,
) -> IsolationStatus:
    """Compute the full isolation seal status for one product."""
    if is_isolated is None:
        is_isolated = is_isolated_product(backend_dir)
    if tach_content is None:
        tach_content = TACH_TOML.read_text() if TACH_TOML.exists() else ""
    if repo_root is None:
        repo_root = REPO_ROOT
    module_path = f"products.{name}"
    permanent_modules = frozenset(permanent_interface_modules(tach_content, module_path))
    facade_leaks, carveout_module_set = _split_facade_reexports(backend_dir, name)
    carveout_modules = frozenset(carveout_module_set)
    return IsolationStatus(
        name=name,
        is_isolated=is_isolated,
        has_real_facade=has_real_facade(backend_dir),
        has_tach_interface=has_tach_interface(name, tach_content),
        has_legacy_leaks=has_legacy_interface_leaks(tach_content, module_path),
        bypass_entries=tuple(presentation_bypass_entries(name, pyproject_text)),
        has_contract_check_script=has_contract_check_script(product_dir),
        has_narrowed_turbo=has_narrowed_turbo_inputs(product_dir, permanent_modules, carveout_modules),
        permanent_exposures=tuple(sorted(permanent_modules)),
        uncovered_permanent_exposures=tuple(sorted(uncovered_permanent_modules(product_dir, permanent_modules))),
        unqualified_permanent_exposures=tuple(
            sorted(unqualified_permanent_modules(module_path, permanent_modules, repo_root=repo_root))
        ),
        facade_leaks=tuple(facade_leaks),
        unwatched_garages=tuple(sorted(unwatched_garages(product_dir))),
        uncovered_carveout_modules=tuple(sorted(uncovered_carveout_modules(product_dir, carveout_modules))),
    )
