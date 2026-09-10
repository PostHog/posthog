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
from collections.abc import Iterator, Sequence
from dataclasses import dataclass
from pathlib import Path

from .ast_helpers import (
    ast_parse_safe,
    decorator_name,
    get_imported_module_names,
    get_model_names,
    has_any_function_defs,
    iter_public_callables,
    lazy_reexport_map,
    lazy_reexport_prefixes,
    module_dunder_all,
    module_has_prefix,
    module_level_import_froms,
    module_level_import_nodes,
    module_type_aliases,
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


def _importlinter_ignore_entries(pyproject_text: str | None = None) -> list[str]:
    """Every ignore_imports entry across the import-linter contracts, or [] if unreadable."""
    if pyproject_text is None:
        pyproject = REPO_ROOT / "pyproject.toml"
        if not pyproject.exists():
            return []
        pyproject_text = pyproject.read_text()
    try:
        contracts = tomllib.loads(pyproject_text)["tool"]["importlinter"]["contracts"]
    except (tomllib.TOMLDecodeError, KeyError):
        return []
    return [entry for contract in contracts for entry in contract.get("ignore_imports", [])]


def ignored_import_edges(pyproject_text: str | None = None) -> set[str]:
    """The exact edges the import-linter contracts ignore, normalized to "importer -> imported".

    Wildcard entries are dropped: they only ever allow the presentation/facade trees, which the
    AST surface check permits outright."""
    edges = set()
    for entry in _importlinter_ignore_entries(pyproject_text):
        if "*" in entry or "->" not in entry:
            continue
        importer, imported = entry.split("->", 1)
        edges.add(f"{importer.strip()} -> {imported.strip()}")
    return edges


def presentation_bypass_entries(name: str, pyproject_text: str | None = None) -> list[str]:
    """import-linter ignore_imports entries that still let this product's HTTP surface
    reach past the facade — the deferred presentation-wave worklist.

    Two contracts feed it: presentation reaching internals directly (one view -> internal
    edge per entry), and routes.py registering views that live outside presentation/ (one
    routes -> view-module edge per entry). Both mean presentation code the contract cannot
    see, so both block the internal seal until removed (see the
    isolating-product-facade-contracts skill).
    """
    prefixes = (f"products.{name}.backend.presentation", f"products.{name}.backend.routes ->")
    return [entry for entry in _importlinter_ignore_entries(pyproject_text) if entry.startswith(prefixes)]


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

# The wiring locations; the identifiers below call them garages. A prefix is either a directory
# (trailing slash) or a single-file module. A class re-exported from one of these is accepted
# wiring, everything else is a leak. See products/architecture.md § Wiring couplings.
GARAGE_PREFIXES: tuple[str, ...] = (
    "backend/hogql_queries/",
    "backend/max_tools.py",
    "backend/temporal/",
    "backend/tasks.py",
    "backend/tasks/",
)

# Wiring locations whose watch is computed, not presence-based. Core runs a query runner by the
# query's kind string, so `product:crossings` can read the dispatch table and find every test
# outside the product that executes a runner (the `drives(...)` lines in the crossings baseline).
# Such a location must stay in the inputs only while a line exists for it. The other locations are
# reached through channels the scan does not read yet (Celery task names, Temporal workflow names,
# Max tool names), so they stay watched by presence until their channel is scanned too.
COMPUTED_WIRING_LOCATIONS: frozenset[str] = frozenset({"backend/hogql_queries/"})


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
    model_surface: tuple[str, ...] = (),
) -> bool:
    """True only when contract-check inputs are confined to the public surface AND at least one
    targets facade/presentation. A broad glob like backend/** alongside a facade entry keeps the
    skip inert, and a routes-only narrowing isn't a real contract surface — both are rejected.
    Negated globs ('!...') are excluded from the surface test.

    Permanently-exposed modules, wiring locations, carve-out modules, and the model surface
    all count as extended surface: a product may list them without forfeiting the narrowing, since
    core depends on each outside the plain facade->contracts channel and they must re-run the suite
    on change (see uncovered_permanent_modules, unwatched_garages, and the carve-out/model coverage
    checks)."""
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
        + model_surface
    )
    return all(_glob_targets(i, accepted) for i in inputs) and any(
        _glob_targets(i, _FACADE_PRESENTATION_PREFIXES) for i in inputs
    )


def _input_covers(input_glob: str, accepted: str) -> bool:
    """A directory location (trailing slash) is covered by any input inside it; a single-file
    location by an exact input, or by a wildcard-free `dir/**` input whose directory contains it —
    backend/models/** watches backend/models/tcac.py, but backend/tasks.py.bak must not count as
    watching backend/tasks.py (and backend/tasks/** does not watch backend/tasks.py)."""
    if accepted.endswith("/"):
        return input_glob.startswith(accepted)
    if input_glob == accepted:
        return True
    directory = input_glob.removesuffix("/**")
    return directory != input_glob and "*" not in directory and accepted.startswith(directory + "/")


def _uncovered_locations(product_dir: Path, targets_to_prefixes: dict[str, tuple[str, ...]]) -> set[str]:
    """Targets whose accepted input forms match no narrowed contract-check input.

    Empty when the product has no narrowing override — everything is watched, so nothing is
    uncovered. Shared by the permanent-exposure, wiring-location, and carve-out coverage checks: same
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
# wiring location (GARAGE_PREFIXES above) core keeps in the contract-check inputs. These checks
# catch the two ways that breaks: a facade re-exporting a class from outside a wiring location,
# and a wiring location that exists but isn't watched. See products/architecture.md § Wiring couplings.


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


# The watched-models allowance, keyed (product, class) like CARVE_OUTS above. These facades may
# hand out the named Django model class defined under backend/models/, provided the whole model
# surface (models + migrations) stays in the narrowed contract-check inputs — the same soundness
# contract wiring locations have. Sanctioned interim debt, surfaced as a standing lint warning.
#
# Keyed per class, not per product, so a product on the list can't quietly grow a new crossing: an
# unlisted class is a leak again, and sanctioning it costs a doctrine amendment. The list only
# shrinks. The bar for an entry, and why these are load-bearing, live in
# products/architecture.md § Wiring couplings.
MODEL_CROSSINGS: frozenset[tuple[str, str]] = frozenset(
    {
        ("product_analytics", "Insight"),
        ("product_analytics", "InsightVariable"),
        ("warehouse_sources", "DataWarehouseCredential"),
        ("warehouse_sources", "DataWarehouseTable"),
        ("warehouse_sources", "ExternalDataDestination"),
        ("warehouse_sources", "ExternalDataJob"),
        ("warehouse_sources", "ExternalDataSchema"),
        ("warehouse_sources", "ExternalDataSchemaDestination"),
        ("warehouse_sources", "ExternalDataSource"),
        ("warehouse_sources", "ExternalDataSourceDestination"),
        ("warehouse_sources", "PendingSourceCredential"),
        ("warehouse_sources", "WarehouseColumnAnnotation"),
        ("warehouse_sources", "WarehouseColumnStatistics"),
    }
)

# Where a crossing model class must be defined to fall under the allowance.
_MODEL_SOURCE_PREFIXES: tuple[str, ...] = ("backend/models/", "backend/models.py")

# The input surface a model-crossing product must keep watched: the model package and its
# migrations (a data migration changes observable state without touching a model file).
MODEL_SURFACE_PREFIXES: tuple[str, ...] = (*_MODEL_SOURCE_PREFIXES, "backend/migrations/")


@dataclass(frozen=True)
class FacadeClassImport:
    """A class a facade module re-exports from a product-internal module outside a wiring location."""

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


def _resolve_dotted_source(dotted: str, backend_dir: Path, prefixes: Sequence[str] = ()) -> str | None:
    """A lazy-map source value ('logic.crud' or 'products.x.backend.logic.crud') -> backend path.

    A map may also store its values relative to a module-level prefix constant, so every prefix the
    module defines is tried after the bare value. The first candidate that names a real module wins."""
    for candidate in (dotted, *(prefix + dotted for prefix in prefixes)):
        module_rel = _resolve_absolute_module(candidate, backend_dir)
        if module_rel is None:
            # Lazy maps commonly store the value relative to the product's backend package.
            module_rel = candidate.replace(".", "/")
        source_path = _backend_rel_path(module_rel, backend_dir)
        if source_path is not None:
            return source_path
    return None


def _is_facade_or_garage(source_path: str) -> bool:
    return source_path.startswith((_FACADE_PREFIX, *GARAGE_PREFIXES))


def _is_test_module(filename: str) -> bool:
    return filename.startswith("test_") or filename.endswith("_test.py")


def _iter_facade_modules(backend_dir: Path) -> Iterator[Path]:
    """Every facade module the facade checks read, in name order.

    Flat by design: facade/ holds no packages, and both callers key a finding on the file name. Test
    modules that happen to sit here are pytest files, not part of the surface."""
    facade_dir = backend_dir / "facade"
    if not facade_dir.is_dir():
        return
    for path in sorted(facade_dir.glob("*.py")):
        if not _is_test_module(path.name):
            yield path


@dataclass(frozen=True)
class _HandedOutName:
    """A product-internal name one facade module hands out, and the module that defines it."""

    bound: str  # the name the facade hands out, which is what a consumer imports
    original: str  # the name at the source
    source_path: str  # backend-relative, e.g. "backend/logic/crud.py"


def _iter_handed_out_names(tree: ast.Module, backend_dir: Path) -> Iterator[_HandedOutName]:
    """Every product-internal name one facade module hands out, wiring locations included (callers
    filter). Three shapes are read:

      - a pure re-export module (no top-level function definitions) hands out every name it imports.
      - a data-capability module (api.py and its split-out siblings, which hold functions that
        convert models to contracts) legitimately imports internal names for its own use, so only
        deliberate re-exports count as handed out: names in its literal `__all__`, plus names
        imported with the explicit self-alias idiom (`from ..x import Foo as Foo` — the shape that
        also suppresses ruff's F401, so it would otherwise be invisible to every lint).
      - a PEP 562 `_LAZY`/`_MODULES` map hands out every name it maps, read regardless of shape.
    """
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
        if source_path is None:
            continue
        for orig, asname in aliases:
            bound = asname or orig
            handed_out = is_pure_reexport or (allowed is not None and bound in allowed) or asname == orig
            if handed_out:
                yield _HandedOutName(bound, orig, source_path)
    prefixes = lazy_reexport_prefixes(tree)
    for name, dotted in lazy_reexport_map(tree).items():
        source_path = _resolve_dotted_source(dotted, backend_dir, prefixes)
        if source_path is not None:
            yield _HandedOutName(name, name, source_path)


def _iter_facade_class_reexports(backend_dir: Path) -> Iterator[FacadeClassImport]:
    """Every product-internal class a facade module hands out, from a module that is neither facade
    nor wiring location — carve-outs included (callers filter)."""
    parse_cache: dict[Path, ast.Module | None] = {}
    for module_file in _iter_facade_modules(backend_dir):
        # contracts/enums are the sanctioned homes for data types, so neither is a wiring re-export.
        if module_file.name in ("contracts.py", "enums.py"):
            continue
        tree = ast_parse_safe(module_file)
        if tree is None:
            continue
        for handed in _iter_handed_out_names(tree, backend_dir):
            if _is_facade_or_garage(handed.source_path):
                continue
            if _name_is_class(handed.source_path, handed.original, backend_dir, cache=parse_cache):
                yield FacadeClassImport(module_file.name, handed.original, handed.source_path)


@dataclass(frozen=True)
class FacadeReexports:
    """One facade traversal, split by sanction: unsanctioned leaks, carve-out defining modules,
    and watched-models-allowance crossings."""

    leaks: tuple[FacadeClassImport, ...]
    carveout_modules: frozenset[str]
    model_crossings: tuple[FacadeClassImport, ...]


def _split_facade_reexports(backend_dir: Path, name: str) -> FacadeReexports:
    leaks: list[FacadeClassImport] = []
    carveout_modules: set[str] = set()
    model_crossings: list[FacadeClassImport] = []
    for f in _iter_facade_class_reexports(backend_dir):
        if (name, f.class_name) in CARVE_OUTS:
            carveout_modules.add(f.source_path)
        elif (name, f.class_name) in MODEL_CROSSINGS and f.source_path.startswith(_MODEL_SOURCE_PREFIXES):
            model_crossings.append(f)
        else:
            leaks.append(f)
    return FacadeReexports(tuple(leaks), frozenset(carveout_modules), tuple(model_crossings))


def facade_class_imports(backend_dir: Path, name: str) -> list[FacadeClassImport]:
    """Classes the facade re-exports from an internal module outside a wiring location, minus sanctioned carve-outs
    and watched-models-allowance crossings.

    Each is a class the facade can hand out that the wiring doctrine doesn't sanction. The remedy is
    always one of three: move it to a wiring location (if it implements a core-owned base), to
    facade/contracts.py (if it's a data/error type), or drop the turbo.json narrowing.

    Division of labor: deliberate re-exports from a function-bearing facade module must surface via
    __all__ or the Foo-as-Foo self-alias idiom — both counted here — while an imported-and-unused
    leftover is ruff F401's job. The residual hole is therefore only a class that is imported plainly,
    genuinely used inside function bodies, AND separately imported by core anyway — core-side misuse
    this lint doesn't chase."""
    return list(_split_facade_reexports(backend_dir, name).leaks)


def facade_carveout_modules(backend_dir: Path, name: str) -> set[str]:
    """Backend-relative modules that define the carve-out classes this product's facade re-exports.

    A narrowed product must keep these in its contract-check inputs, exactly like a wiring location."""
    return set(_split_facade_reexports(backend_dir, name).carveout_modules)


def facade_model_crossings(backend_dir: Path, name: str) -> list[FacadeClassImport]:
    """Model classes this product's facade hands out under the watched-models allowance.

    Sanctioned interim debt, never a leak. The model surface (MODEL_SURFACE_PREFIXES) is watched
    by every narrowed product regardless; see unwatched_model_surface."""
    return list(_split_facade_reexports(backend_dir, name).model_crossings)


def _unwatched_present_locations(product_dir: Path, prefixes: tuple[str, ...]) -> set[str]:
    """Locations from `prefixes` that exist in the product but are missing from its (narrowed)
    contract-check inputs.

    The accepted prefix keeps a directory's trailing slash, so a directory location is only covered
    by an input inside it — backend/tasks.py or backend/tasks_extra/** must not count as watching
    backend/tasks/ (same anchoring as _module_input_prefixes)."""
    present = {p for p in prefixes if (product_dir / p.rstrip("/")).exists()}
    return _uncovered_locations(product_dir, {p: (p,) for p in present})


def unwatched_garages(product_dir: Path, driven: frozenset[str] | None = None) -> set[str]:
    """Wiring locations present in the product but missing from its (narrowed) contract-check inputs.

    `driven` is the subset of COMPUTED_WIRING_LOCATIONS that a test outside the product executes, read
    from the crossings baseline. A computed location with no driver may leave the inputs. `None`
    means the caller has no evidence, so every present location counts as driven: the safe
    direction."""
    if driven is None:
        prefixes = GARAGE_PREFIXES
    else:
        prefixes = tuple(p for p in GARAGE_PREFIXES if p not in COMPUTED_WIRING_LOCATIONS or p in driven)
    return _unwatched_present_locations(product_dir, prefixes)


def uncovered_carveout_modules(product_dir: Path, carveout_modules: frozenset[str]) -> set[str]:
    """Carve-out defining modules re-exported by the facade but absent from contract-check inputs.

    A carve-out class crosses the boundary for a class-identity registry, so a change to its
    defining module is a coupling change core must re-test — exactly like a permanent exposure."""
    return _uncovered_locations(product_dir, {m: (m,) for m in carveout_modules})


def _literal_prefix_overlaps(glob: str, prefix: str) -> bool:
    """Whether a glob could reach inside `prefix`, judged only by its literal part."""
    literal = glob.split("*", 1)[0]
    return literal.startswith(prefix) or prefix.startswith(literal)


def unwatched_model_surface(product_dir: Path) -> set[str]:
    """Model-surface locations present in the product but not wholly watched by its (narrowed)
    contract-check inputs. Every narrowed product must watch its models and migrations: a model is
    reachable without an import (apps.get_model strings, migrations, admin, fixtures), so tach and
    the facade checks cannot prove nothing outside observes it, and a model or migration change has
    to re-run the full suite.

    Stricter than the wiring-location check on purpose: the WHOLE surface must be watched, so a directory
    location needs its full glob (backend/models/**) — an input inside it, or a negation that may
    carve files out of it, does not count. A wiring location may be watched piecemeal; the model
    surface may not, because any unwatched model file is a class core can observe without re-running
    the suite. There is no glob engine here, so a negation only passes when its literal prefix (up
    to the first wildcard) is provably disjoint from the surface — `!backend/**/x.py` could match a
    model file and is rejected."""
    raw = contract_check_inputs(product_dir)
    if not raw:
        return set()
    positive = [i.removeprefix("./") for i in raw if not i.startswith("!")]
    negations = [i.removeprefix("!").removeprefix("./") for i in raw if i.startswith("!")]
    uncovered = set()
    for p in MODEL_SURFACE_PREFIXES:
        # Migrations are required whether or not the directory exists yet: a product that narrows
        # before its first migration would otherwise carry an unwatched location the moment one lands.
        if p != "backend/migrations/" and not (product_dir / p.rstrip("/")).exists():
            continue
        negation_may_touch = any(_literal_prefix_overlaps(n, p) for n in negations)
        if location_input_glob(p) not in positive or negation_may_touch:
            uncovered.add(p)
    return uncovered


# ---------------------------------------------------------------------------
# Facade shape — what the boundary accepts, returns, and defines
# ---------------------------------------------------------------------------
#
# tach and import-linter read import edges only. They see that a facade imports a model module, but
# not that a facade function returns the model, takes a DRF request, or hides a Django object behind
# `Any`. The rules below read the signatures themselves, so publicness comes from the shape of the
# API and not from the location of the file. The kinds, and the move that clears each one, are in
# products/architecture.md § The shape check.

# Capability submodules re-export wiring and hold no logic of their own. A task body or a workflow
# definition here sits in the one package core imports, so the product cannot change it without
# changing what core runs. The implementation belongs in the wiring location, which the
# contract-check inputs watch.
#
# The names the doctrine spells out. A product may call the same wiring anything, so the stem list
# is a floor and _is_capability_module decides the rest from what a module hands out.
CAPABILITY_SUBMODULES: frozenset[str] = frozenset(
    {"dags", "hogql", "max_tools", "models", "queries", "tasks", "temporal"}
)

# Facade stems that are never capability submodules whatever they hand out. `api*.py` holds the
# data capabilities, so a body there is the designed shape; contracts and enums are the sanctioned
# homes for data types; products/architecture.md sanctions a facade/testing.py fixture helper.
_NON_CAPABILITY_FACADE_STEMS: frozenset[str] = frozenset({"contracts", "enums", "testing"})

# Parameters that name the tenant or the actor a call is for. `Any` on one of these hides a Django
# or a DRF object behind an annotation no check can read, which is how a leak survives review.
_UNTYPED_SUBJECT_PARAMS: frozenset[str] = frozenset({"request", "team", "user"})

# Libraries whose types must stay off a facade signature, and the name a ledger row gives each one.
# Core models are absent on purpose: every product may depend on core, so a core model in a facade
# signature adds no coupling the repo does not already have. typing_extensions exports the same
# names as typing and reports under the same source, so the spelling a module picks cannot decide
# whether its `Any` counts.
_LIBRARY_SOURCES: tuple[tuple[tuple[str, ...], str], ...] = (
    (("django.db.models", "django.http"), "django"),
    (("rest_framework",), "rest_framework"),
    (("typing", "typing_extensions"), "typing"),
)
_LIBRARY_NAMES: frozenset[str] = frozenset(source for _, source in _LIBRARY_SOURCES)

# Typing special forms whose subscript arguments are not all types: `Literal` holds values, and
# `Annotated` holds one type followed by metadata. Both modules that export them are named, so an
# import binds the name; a spelling nothing bound falls back to the bare name.
_LITERAL = "Literal"
_ANNOTATED = "Annotated"
_SPECIAL_FORMS: frozenset[str] = frozenset({_LITERAL, _ANNOTATED})
_SPECIAL_FORM_MODULES: frozenset[str] = frozenset({"typing", "typing_extensions"})

# The model surface as dotted module names, so an import path is tested against the same definition
# of "where a product's models live" that the input-coverage checks use.
_MODEL_SURFACE_MODULES: tuple[str, ...] = tuple(
    sorted({p.removeprefix("backend/").rstrip("/").removesuffix(".py") for p in MODEL_SURFACE_PREFIXES})
)
_PRODUCT_BACKEND_RE = re.compile(r"^products\.([A-Za-z0-9_]+)\.backend\.(.+)$")

# Dunder hooks of the PEP 562 lazy re-export map. Their body is the re-export mechanism itself.
_REEXPORT_DUNDERS: frozenset[str] = frozenset({"__getattr__", "__dir__"})


@dataclass(frozen=True)
class _ForbiddenType:
    """A type a facade module binds a name to, and must not put on the boundary."""

    source: str  # django | rest_framework | typing | the product that owns the model
    type_name: str  # the name at the source, so an alias still reports the real type


# `Any` is the one name typing contributes: it is how a Django or a DRF object crosses a signature
# without naming itself.
_ANY = _ForbiddenType("typing", "Any")


@dataclass(frozen=True)
class FacadeShapeFinding:
    """One place a facade breaks the contract-only boundary.

    A `returns` or an `accepts` finding sits on one symbol and names one type. A `logic` finding
    stands for a whole capability submodule and lists the bodies it still holds, so the ledger's
    count column says how much is left to move.
    """

    product: str
    facade_module: str  # facade-relative, e.g. "destinations.py"
    dotted_module: str  # e.g. "products.data_pipelines.backend.facade.destinations"
    kind: str  # returns | accepts | logic
    # The type the signature names, with the source that defines it: the owning product for a
    # product model, else the library. Both empty for `logic`, which is keyed by the module.
    source: str = ""
    type_name: str = ""
    symbol: str = ""  # the function or the method the type sits on, e.g. "Mapper.to_contract"
    parameter: str = ""  # the parameter an `accepts` finding names
    bodies: tuple[str, ...] = ()  # the definitions a `logic` finding counts

    @property
    def count(self) -> int:
        """A `logic` row counts the bodies its module holds; every other kind is one place."""
        return len(self.bodies) if self.kind == "logic" else 1


class _ModelNames:
    """The Django model class names of each product, parsed once per sweep.

    A models module also holds enums, choices and managers, so a name imported from one is an ORM
    object only when it is a registered model. Products resolve as siblings of the product under
    scan, so the sweep reads the tree it was pointed at.
    """

    def __init__(self, backend_dir: Path) -> None:
        self._products_dir = backend_dir.parent.parent
        self._names: dict[str, frozenset[str]] = {}

    def for_product(self, product: str) -> frozenset[str]:
        if product not in self._names:
            self._names[product] = frozenset(get_model_names(self._products_dir / product / "backend"))
        return self._names[product]


@dataclass(frozen=True)
class _FacadeImportEnv:
    """What one facade module's imports and type aliases bind, as far as the shape rules care."""

    types: dict[str, _ForbiddenType]  # local name -> the forbidden type it binds
    modules: dict[str, str]  # local module alias -> source, for a `models.QuerySet` annotation
    special_forms: dict[str, str]  # local name -> the typing special form it binds
    aliases: dict[str, ast.expr]  # local name -> the expression a module-level type alias stands for
    model_names: _ModelNames


def _reaches_model_surface(backend_module: str) -> bool:
    """True when a backend-relative dotted module is part of a product's model surface.

    The owner's facade.models shim counts: it re-exports the same classes, so it cannot be the
    spelling that gets a model past the check."""
    return module_has_prefix(backend_module.removeprefix("facade."), _MODEL_SURFACE_MODULES)


def _product_model_owner(module: str) -> str | None:
    """The product whose model surface an absolute import reaches, else None."""
    match = _PRODUCT_BACKEND_RE.match(module)
    if match is None:
        return None
    product, backend_module = match.groups()
    return product if _reaches_model_surface(backend_module) else None


def _import_source(module: str) -> str | None:
    """Where the names of an absolute import come from, or None when nothing there is off limits:
    the library for a Django, a DRF or a typing import, else the product whose model surface it
    reaches."""
    for prefixes, source in _LIBRARY_SOURCES:
        if module_has_prefix(module, prefixes):
            return source
    return _product_model_owner(module)


def _relative_import_source(level: int, module: str | None, product: str, package_parts: Sequence[str]) -> str | None:
    """The same, for a relative import inside the scanned module's own package: the module's own
    product when the import reaches its model surface, else None."""
    backend_module = _resolve_relative(list(package_parts), level, module)
    if backend_module is None:
        return None
    return product if _reaches_model_surface(backend_module.replace("/", ".")) else None


def _forbidden(source: str, name: str, model_names: _ModelNames) -> _ForbiddenType | None:
    """The forbidden type a name from `source` stands for, or None when that name is not one.

    typing contributes `Any` alone. A models module also holds enums, choices and managers, which a
    contract may carry, so only a registered model counts there."""
    if source == _ANY.source:
        return _ANY if name == _ANY.type_name else None
    if source in _LIBRARY_NAMES:
        return _ForbiddenType(source, name)
    return _ForbiddenType(source, name) if name in model_names.for_product(source) else None


def _submodule_of(module: str | None, name: str) -> str:
    """The module a `from <module> import <name>` names when `name` is a submodule.

    `from . import models` carries no module of its own, so the imported name is the whole path."""
    return f"{module}.{name}" if module else name


def _package_dir(level: int, module: str | None, backend_dir: Path, package_parts: Sequence[str]) -> Path | None:
    """The directory a `from <package> import ...` reads, for a package that is on disk here.

    That is this product's backend for a relative import and another product's backend for an
    absolute one. A library package is not in this tree, so it has no directory."""
    if level > 0:
        module_rel = _resolve_relative(list(package_parts), level, module)
        return None if module_rel is None else backend_dir / module_rel
    match = _PRODUCT_BACKEND_RE.match(module or "")
    if match is None:
        return None
    product, backend_module = match.groups()
    products_dir = backend_dir.parent.parent
    return products_dir / product / "backend" / backend_module.replace(".", "/")


def _binds_submodule(package_dir: Path | None, source: str, name: str) -> bool:
    """True when a `from <package> import <name>` binds a submodule rather than a type.

    A product package is in this tree, so the file or the directory on disk decides. A library
    package is not, so the PEP 8 spelling decides instead: `from rest_framework import request`
    binds a module and `from rest_framework.request import Request` binds a type.

    The on-disk test reads the directory rather than asking for the path, because a case-insensitive
    filesystem answers `Account.py` with `account.py` and would turn every model class into a
    module alias."""
    if package_dir is None:
        return source in _LIBRARY_NAMES and name[:1].islower()
    if not package_dir.is_dir():
        return False
    return any(
        (entry.name == f"{name}.py" and entry.is_file()) or (entry.name == name and entry.is_dir())
        for entry in package_dir.iterdir()
    )


def _facade_import_env(
    tree: ast.Module,
    product: str,
    model_names: _ModelNames,
    backend_dir: Path,
    package_parts: Sequence[str] = ("facade",),
) -> _FacadeImportEnv:
    types: dict[str, _ForbiddenType] = {}
    modules: dict[str, str] = {}
    special_forms: dict[str, str] = {}
    for node in module_level_import_nodes(tree, type_checking=True):
        if isinstance(node, ast.Import):
            for alias in node.names:
                source = _import_source(alias.name)
                if source is not None:
                    modules[alias.asname or alias.name.split(".")[0]] = source
            continue
        module = node.module or ""
        if node.level == 0 and module in _SPECIAL_FORM_MODULES:
            for alias in node.names:
                if alias.name in _SPECIAL_FORMS:
                    special_forms[alias.asname or alias.name] = alias.name
        source = (
            _relative_import_source(node.level, node.module, product, package_parts)
            if node.level > 0
            else _import_source(module)
        )
        for alias in node.names:
            bound = alias.asname or alias.name
            if source is None:
                # `from django.db import models` and `from . import models` both bind the namespace
                # and not a type, so the annotation spells `models.QuerySet`.
                submodule = _submodule_of(node.module, alias.name)
                submodule_source = (
                    _relative_import_source(node.level, submodule, product, package_parts)
                    if node.level > 0
                    else _import_source(submodule)
                )
                if submodule_source is not None:
                    modules[bound] = submodule_source
                continue
            if _binds_submodule(_package_dir(node.level, node.module, backend_dir, package_parts), source, alias.name):
                modules[bound] = source
                continue
            forbidden = _forbidden(source, alias.name, model_names)
            if forbidden is not None:
                types[bound] = forbidden
    return _FacadeImportEnv(
        types=types,
        modules=modules,
        special_forms=special_forms,
        aliases=module_type_aliases(tree),
        model_names=model_names,
    )


@dataclass(frozen=True)
class _TypeRef:
    """One type an annotation names: the name bound at module level, and the type it names.

    `QuerySet[Thing]` gives (QuerySet, QuerySet) and (Thing, Thing); `models.QuerySet` gives
    (models, QuerySet)."""

    root: str
    named: str


def _special_form(env: _FacadeImportEnv, node: ast.expr) -> str | None:
    """The typing special form the head of a subscript names, or None.

    Read from the import that bound the name, so `Literal as L` still resolves. A name nothing
    module-level bound falls back to the spelling, which covers the `typing.Literal` attribute form
    and a name bound somewhere this scan does not read."""
    if isinstance(node, ast.Name):
        bound = env.special_forms.get(node.id)
        if bound is not None:
            return bound
        return node.id if node.id in _SPECIAL_FORMS else None
    if isinstance(node, ast.Attribute):
        return node.attr if node.attr in _SPECIAL_FORMS else None
    return None


def _first_argument(node: ast.expr) -> ast.expr:
    """The first argument of a subscript, which is the whole slice when there is only one."""
    if isinstance(node, ast.Tuple) and node.elts:
        return node.elts[0]
    return node


def _annotation_refs(
    env: _FacadeImportEnv, node: ast.expr | None, expanding: frozenset[str] = frozenset()
) -> list[_TypeRef]:
    """Every type an annotation names.

    A quoted annotation is parsed and read the same way, which is how a TYPE_CHECKING import still
    counts. One that does not parse is skipped, because this is a ratchet and not a proof.

    A name a module-level type alias binds is read as the expression it stands for, so the spelling
    a facade picks for a type cannot decide whether it counts. `expanding` holds the aliases already
    open, because an alias may name another one and a pair may name each other.
    """
    if node is None:
        return []
    if isinstance(node, ast.Name):
        alias = env.aliases.get(node.id)
        if alias is not None and node.id not in expanding:
            return _annotation_refs(env, alias, expanding | {node.id})
        return [_TypeRef(node.id, node.id)]
    if isinstance(node, ast.Attribute):
        root: ast.expr = node
        while isinstance(root, ast.Attribute):
            root = root.value
        return [_TypeRef(root.id, node.attr)] if isinstance(root, ast.Name) else []
    if isinstance(node, ast.Constant):
        if not isinstance(node.value, str):
            return []
        try:
            parsed = ast.parse(node.value, mode="eval")
        except SyntaxError:
            return []
        return _annotation_refs(env, parsed.body, expanding)
    if isinstance(node, ast.Subscript):
        form = _special_form(env, node.value)
        if form == _LITERAL:
            # The arguments of a Literal are values. A string among them is data, so parsing it as
            # a forward reference reports a type that never crosses.
            return _annotation_refs(env, node.value, expanding)
        if form == _ANNOTATED:
            # Annotated is one type followed by metadata, and only the type is on the boundary.
            return _annotation_refs(env, node.value, expanding) + _annotation_refs(
                env, _first_argument(node.slice), expanding
            )
        return _annotation_refs(env, node.value, expanding) + _annotation_refs(env, node.slice, expanding)
    if isinstance(node, ast.BinOp):
        return _annotation_refs(env, node.left, expanding) + _annotation_refs(env, node.right, expanding)
    if isinstance(node, (ast.Tuple, ast.List)):
        return [ref for element in node.elts for ref in _annotation_refs(env, element, expanding)]
    return []


def _named_type(env: _FacadeImportEnv, root: str, named: str) -> _ForbiddenType | None:
    """The forbidden type one annotation reference stands for, or None."""
    bound = env.types.get(root)
    if bound is not None:
        # `Thing.Status` is a nested class attribute, which carries no instance of the outer class,
        # so only the bare name puts the type on the boundary.
        return bound if named == root else None
    source = env.modules.get(root)
    if source is None or named == root:
        return None
    return _forbidden(source, named, env.model_names)


def _forbidden_types_in(env: _FacadeImportEnv, annotation: ast.expr | None) -> list[_ForbiddenType]:
    """Every forbidden type one annotation names, first occurrence kept.

    Keyed by source and name together: two types can share a name across products, and collapsing
    them would let a sanctioned one hide an unsanctioned one behind it."""
    found: dict[tuple[str, str], _ForbiddenType] = {}
    for ref in _annotation_refs(env, annotation):
        forbidden = _named_type(env, ref.root, ref.named)
        if forbidden is not None:
            found.setdefault((forbidden.source, forbidden.type_name), forbidden)
    return list(found.values())


def _annotation_is_any(env: _FacadeImportEnv, annotation: ast.expr | None) -> bool:
    """True when the whole annotation is `Any`. `dict[str, Any]` is not: the data stays data."""
    refs = _annotation_refs(env, annotation)
    return len(refs) == 1 and _named_type(env, refs[0].root, refs[0].named) == _ANY


def _is_sanctioned(product: str, forbidden: _ForbiddenType) -> bool:
    """A class the doctrine already lets this product's facade hand out.

    The allowance covers the product's own class, so the source must be the product too: another
    product's same-named model is a crossing nobody sanctioned."""
    if forbidden.source != product:
        return False
    key = (product, forbidden.type_name)
    return key in CARVE_OUTS or key in MODEL_CROSSINGS


def _iter_accepts_findings(
    env: _FacadeImportEnv,
    product: str,
    facade_module: str,
    dotted_module: str,
    symbol: str,
    parameter: str,
    annotation: ast.expr | None,
) -> Iterator[FacadeShapeFinding]:
    """One `accepts` finding per forbidden type on one parameter.

    `Any` only counts on the tenant and actor names, because an `Any` payload says nothing about a
    Django object."""
    for forbidden in _forbidden_types_in(env, annotation):
        if _is_sanctioned(product, forbidden):
            continue
        if forbidden == _ANY and parameter not in _UNTYPED_SUBJECT_PARAMS:
            continue
        yield FacadeShapeFinding(
            product=product,
            facade_module=facade_module,
            dotted_module=dotted_module,
            kind="accepts",
            source=forbidden.source,
            type_name=forbidden.type_name,
            symbol=symbol,
            parameter=parameter,
        )


def _iter_signature_findings(
    node: ast.FunctionDef | ast.AsyncFunctionDef,
    env: _FacadeImportEnv,
    product: str,
    facade_module: str,
    dotted_module: str,
    symbol: str,
) -> Iterator[FacadeShapeFinding]:
    """One finding per forbidden type in one signature.

    A bare `-> Any` is a finding of its own: it promises nothing, which is the evasion the whole
    check exists to close."""
    for forbidden in _forbidden_types_in(env, node.returns):
        if _is_sanctioned(product, forbidden):
            continue
        if forbidden == _ANY and not _annotation_is_any(env, node.returns):
            continue
        yield FacadeShapeFinding(
            product=product,
            facade_module=facade_module,
            dotted_module=dotted_module,
            kind="returns",
            source=forbidden.source,
            type_name=forbidden.type_name,
            symbol=symbol,
        )
    args = node.args
    for arg in [*args.posonlyargs, *args.args, *args.kwonlyargs, args.vararg, args.kwarg]:
        if arg is None or arg.arg in ("self", "cls"):
            continue
        yield from _iter_accepts_findings(env, product, facade_module, dotted_module, symbol, arg.arg, arg.annotation)


# Decorators that generate a constructor out of the annotated class-level fields: the stdlib one
# under every spelling (`@dataclass`, `@dataclass(...)`, `@dataclasses.dataclass`) and the house
# `@frozen` of posthog.dataclasses.
_DATACLASS_DECORATORS: frozenset[str] = frozenset({"dataclass", "frozen"})


def _has_generated_constructor(node: ast.ClassDef) -> bool:
    return any(decorator_name(decorator) in _DATACLASS_DECORATORS for decorator in node.decorator_list)


def _annotation_head(node: ast.expr) -> str:
    """The bare name at the head of an annotation, with any module prefix dropped."""
    if isinstance(node, ast.Name):
        return node.id
    if isinstance(node, ast.Attribute):
        return node.attr
    return ""


def _is_class_var(annotation: ast.expr) -> bool:
    """True for `ClassVar[...]`, which is shared state rather than a field, so it takes no keyword."""
    return isinstance(annotation, ast.Subscript) and _annotation_head(annotation.value) == "ClassVar"


def _iter_dataclass_field_findings(
    tree: ast.Module, env: _FacadeImportEnv, product: str, facade_module: str, dotted_module: str
) -> Iterator[FacadeShapeFinding]:
    """Signature findings for the constructors a dataclass decorator generates.

    A field is a keyword of the generated `__init__`, so a model on one is a model the caller hands
    the class, exactly like an annotated parameter of a written constructor. Such a row names
    `<Class>.__init__` and carries the field as its parameter. facade/contracts.py is read like every
    other facade module, because a frozen contract is precisely what must never carry a model."""
    for node in ast.iter_child_nodes(tree):
        if not isinstance(node, ast.ClassDef) or node.name.startswith("_"):
            continue
        if not _has_generated_constructor(node):
            continue
        for statement in node.body:
            if not isinstance(statement, ast.AnnAssign) or not isinstance(statement.target, ast.Name):
                continue
            if _is_class_var(statement.annotation):
                continue
            yield from _iter_accepts_findings(
                env,
                product,
                facade_module,
                dotted_module,
                f"{node.name}.__init__",
                statement.target.id,
                statement.annotation,
            )


def _iter_module_signature_findings(
    tree: ast.Module, env: _FacadeImportEnv, product: str, facade_module: str, dotted_module: str
) -> Iterator[FacadeShapeFinding]:
    """Signature findings for the module's public call surface: its module-level functions, the
    public methods, constructor included, of the public classes it defines, and the constructors a
    dataclass decorator generates. A leading underscore marks a helper the facade keeps to itself,
    and converting a model to a contract is exactly what such a helper is for."""
    for owner, node in iter_public_callables(tree, include_init=True):
        if owner.startswith("_"):
            continue
        symbol = f"{owner}.{node.name}" if owner else node.name
        yield from _iter_signature_findings(node, env, product, facade_module, dotted_module, symbol)
    yield from _iter_dataclass_field_findings(tree, env, product, facade_module, dotted_module)


def _top_level_function(tree: ast.Module, name: str) -> ast.FunctionDef | ast.AsyncFunctionDef | None:
    for node in ast.iter_child_nodes(tree):
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)) and node.name == name:
            return node
    return None


def _cached_parse(cache: dict[str, ast.Module | None], source_path: str, backend_dir: Path) -> ast.Module | None:
    if source_path not in cache:
        cache[source_path] = ast_parse_safe(_source_file(source_path, backend_dir))
    return cache[source_path]


@dataclass(frozen=True)
class _ImportHop:
    """Where a module-level import says a name it binds comes from."""

    source_path: str  # backend-relative, e.g. "backend/logic/crud.py"
    name: str  # the name at that source, which an alias may rename


def _import_hop(tree: ast.Module, source_path: str, name: str, backend_dir: Path) -> _ImportHop | None:
    """The module-level import that binds `name` in this module, resolved to the module it names.

    None when nothing binds it, or when what binds it is outside this product's backend: a chain
    that leaves the product ends there, the same way the class walk ends."""
    package_parts = _module_package_parts(source_path)
    for level, module, aliases in module_level_import_froms(tree):
        for original, asname in aliases:
            if (asname or original) != name:
                continue
            module_rel = (
                _resolve_relative(package_parts, level, module)
                if level > 0
                else _resolve_absolute_module(module or "", backend_dir)
            )
            if module_rel is None:
                continue
            nested = _backend_rel_path(module_rel, backend_dir)
            if nested is not None:
                return _ImportHop(nested, original)
    return None


@dataclass(frozen=True)
class _ResolvedFunction:
    """A function a facade hands out, with the module that finally defines it."""

    node: ast.FunctionDef | ast.AsyncFunctionDef
    source_path: str  # backend-relative, e.g. "backend/logic/crud.py"


# How many re-export hops a name may take before the walk gives up. A package __init__ that surfaces
# a submodule is one hop, and a chain longer than a handful is a structure problem of its own.
_REEXPORT_HOPS = 5


def _resolve_function(
    source_path: str,
    name: str,
    backend_dir: Path,
    parse_cache: dict[str, ast.Module | None],
    hops: int = _REEXPORT_HOPS,
) -> _ResolvedFunction | None:
    """The function a name resolves to, following the re-exports of this product's own modules.

    A facade reaches its logic through a package (`from ..logic import fn`), and that package
    __init__ commonly surfaces the function from a submodule rather than defining it. Without the
    hop the real signature is never read, so the spelling would decide whether a type counts."""
    tree = _cached_parse(parse_cache, source_path, backend_dir)
    if tree is None:
        return None
    node = _top_level_function(tree, name)
    if node is not None:
        return _ResolvedFunction(node, source_path)
    if hops <= 0:
        return None
    hop = _import_hop(tree, source_path, name, backend_dir)
    if hop is None:
        return None
    return _resolve_function(hop.source_path, hop.name, backend_dir, parse_cache, hops - 1)


def _iter_reexport_signature_findings(
    tree: ast.Module,
    backend_dir: Path,
    product: str,
    facade_module: str,
    dotted_module: str,
    model_names: _ModelNames,
) -> Iterator[FacadeShapeFinding]:
    """Signature findings for the functions a facade hands out that another module defines.

    A re-export is part of the facade's own call surface: a consumer imports the name from the
    facade and another module answers, whether the facade spells that as an import it re-exports or
    as a PEP 562 lazy map. So the defining function is read under the facade name, and neither
    spelling can be what gets a type past the check. The chain is followed through the product's own
    modules, because a package __init__ commonly re-exports the function rather than defining it.
    Annotations are resolved in the defining module's own namespace, which is where they were
    written.

    A class is a re-export the wiring doctrine reads instead (facade_class_imports), and a name the
    facade module defines itself is already read by the module scan. A source outside this product's
    backend never resolves to a path, so nothing crosses in from core or a library.
    """
    defined_here = {
        node.name
        for node in ast.iter_child_nodes(tree)
        if isinstance(node, (ast.ClassDef, ast.FunctionDef, ast.AsyncFunctionDef))
    }
    parse_cache: dict[str, ast.Module | None] = {}
    env_cache: dict[str, _FacadeImportEnv] = {}
    handed_out = set(_iter_handed_out_names(tree, backend_dir))
    for handed in sorted(handed_out, key=lambda h: (h.bound, h.original, h.source_path)):
        # A real definition wins over a re-export, and the module scan already read it.
        if handed.bound.startswith("_") or handed.bound in defined_here:
            continue
        # A sibling facade module is scanned under its own name, so reading it again here would
        # record the same signature twice.
        if handed.source_path.startswith(_FACADE_PREFIX):
            continue
        resolved = _resolve_function(handed.source_path, handed.original, backend_dir, parse_cache)
        if resolved is None or resolved.source_path.startswith(_FACADE_PREFIX):
            continue
        source_tree = _cached_parse(parse_cache, resolved.source_path, backend_dir)
        if source_tree is None:
            continue
        if resolved.source_path not in env_cache:
            env_cache[resolved.source_path] = _facade_import_env(
                source_tree, product, model_names, backend_dir, _module_package_parts(resolved.source_path)
            )
        yield from _iter_signature_findings(
            resolved.node, env_cache[resolved.source_path], product, facade_module, dotted_module, handed.bound
        )


def _has_wiring_decorator(node: ast.FunctionDef | ast.AsyncFunctionDef | ast.ClassDef) -> bool:
    """True when a definition carries wiring core registers: a Celery task or a Temporal
    definition. Temporal is spelled `<module>.defn`, so its receiver is read too: a bare `defn` is
    some other decorator."""
    for decorator in node.decorator_list:
        if decorator_name(decorator) == "shared_task":
            return True
        target = decorator.func if isinstance(decorator, ast.Call) else decorator
        if isinstance(target, ast.Attribute) and target.attr == "defn" and isinstance(target.value, ast.Name):
            return True
    return False


def _is_passthrough_body(node: ast.FunctionDef | ast.AsyncFunctionDef | ast.ClassDef) -> bool:
    """True when the body holds only a docstring, `pass`, or `...`, which is a stub and not logic."""
    body = list(node.body)
    if (
        body
        and isinstance(body[0], ast.Expr)
        and isinstance(body[0].value, ast.Constant)
        and isinstance(body[0].value.value, str)
    ):
        body = body[1:]
    return all(
        isinstance(stmt, ast.Pass)
        or (isinstance(stmt, ast.Expr) and isinstance(stmt.value, ast.Constant) and stmt.value.value is Ellipsis)
        for stmt in body
    )


def _capability_finding(
    tree: ast.Module, product: str, facade_module: str, dotted_module: str
) -> FacadeShapeFinding | None:
    """The one `logic` finding for a capability submodule, naming every definition it holds beyond a
    re-export. One finding per module, so the count says how much is left to move."""
    bodies: list[str] = []
    for node in ast.iter_child_nodes(tree):
        if not isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
            continue
        if node.name in _REEXPORT_DUNDERS:
            continue
        if _has_wiring_decorator(node) or not _is_passthrough_body(node):
            bodies.append(node.name)
    if not bodies:
        return None
    return FacadeShapeFinding(
        product=product,
        facade_module=facade_module,
        dotted_module=dotted_module,
        kind="logic",
        bodies=tuple(bodies),
    )


def _is_capability_module(tree: ast.Module, filename: str, backend_dir: Path) -> bool:
    """True when a facade module is a capability submodule: one whose job is to hand out wiring or
    model classes.

    Read from what the module hands out rather than from its name, because a product may call the
    same wiring anything (`workflow_tasks.py`, `tools.py`) and a filename allowlist then misses it.
    The doctrine stems stay a floor, so such a module keeps the rule before it hands anything out."""
    stem = filename.removesuffix(".py")
    if stem in CAPABILITY_SUBMODULES:
        return True
    if stem.startswith("api") or stem in _NON_CAPABILITY_FACADE_STEMS:
        return False
    wiring = (*GARAGE_PREFIXES, *MODEL_SURFACE_PREFIXES)
    return any(handed.source_path.startswith(wiring) for handed in _iter_handed_out_names(tree, backend_dir))


def _facade_module_dotted(product: str, filename: str) -> str:
    """`products.<product>.backend.facade.<module>` for one facade file. A package __init__ names
    the package itself, the same rule the crossings scan uses for a repo path."""
    parts = ["products", product, "backend", "facade"]
    stem = filename.removesuffix(".py")
    if stem != "__init__":
        parts.append(stem)
    return ".".join(parts)


def facade_shape_findings(backend_dir: Path, name: str) -> list[FacadeShapeFinding]:
    """Every place this product's facade puts a Django, a DRF or an ORM type on its boundary, plus
    every capability submodule that holds a body rather than a re-export.

    crossings.py turns each finding into a `facade-*` line of the model-crossing ledger, which is
    where the ratchet holds it. products/architecture.md § The shape check carries the kinds and the
    move that clears each one.
    """
    findings: list[FacadeShapeFinding] = []
    model_names = _ModelNames(backend_dir)
    for path in _iter_facade_modules(backend_dir):
        tree = ast_parse_safe(path)
        if tree is None:
            continue
        dotted_module = _facade_module_dotted(name, path.name)
        env = _facade_import_env(tree, name, model_names, backend_dir)
        findings.extend(_iter_module_signature_findings(tree, env, name, path.name, dotted_module))
        findings.extend(
            _iter_reexport_signature_findings(tree, backend_dir, name, path.name, dotted_module, model_names)
        )
        if _is_capability_module(tree, path.name, backend_dir):
            logic = _capability_finding(tree, name, path.name, dotted_module)
            if logic is not None:
                findings.append(logic)
    return sorted(findings, key=lambda f: (f.facade_module, f.symbol, f.kind, f.type_name, f.parameter))


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
    # Classes the facade re-exports from an internal module that is neither wiring location nor carve-out — behavior
    # crossing the boundary that the wiring doctrine doesn't sanction (see facade_class_imports).
    # Blocks narrowing; a warning-only signal while the product is still un-narrowed.
    facade_leaks: tuple[FacadeClassImport, ...] = ()
    # Wiring locations present in the product but missing from a narrowed product's inputs, and
    # carve-out modules missing the same way. Both keep the skip sound and block when narrowed. A
    # location in COMPUTED_WIRING_LOCATIONS is listed only while an outside test drives it (driven_wiring_locations).
    unwatched_garages: tuple[str, ...] = ()
    driven_wiring_locations: tuple[str, ...] = ()
    uncovered_carveout_modules: tuple[str, ...] = ()
    # Model classes the facade hands out under the watched-models allowance (see
    # MODEL_CROSSINGS). uncovered_model_surface lists the model/migration locations a narrowed
    # product fails to keep in its contract-check inputs; every narrowed product must watch them.
    model_crossings: tuple[FacadeClassImport, ...] = ()
    uncovered_model_surface: tuple[str, ...] = ()

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
    driven_wiring_locations: frozenset[str] | None = None,
) -> IsolationStatus:
    """Compute the full isolation seal status for one product.

    `driven_wiring_locations` is the evidence `unwatched_garages` reads. Without it, every present wiring
    location must stay watched."""
    if is_isolated is None:
        is_isolated = is_isolated_product(backend_dir)
    if tach_content is None:
        tach_content = TACH_TOML.read_text() if TACH_TOML.exists() else ""
    if repo_root is None:
        repo_root = REPO_ROOT
    module_path = f"products.{name}"
    permanent_modules = frozenset(permanent_interface_modules(tach_content, module_path))
    reexports = _split_facade_reexports(backend_dir, name)
    carveout_modules = reexports.carveout_modules
    return IsolationStatus(
        name=name,
        is_isolated=is_isolated,
        has_real_facade=has_real_facade(backend_dir),
        has_tach_interface=has_tach_interface(name, tach_content),
        has_legacy_leaks=has_legacy_interface_leaks(tach_content, module_path),
        bypass_entries=tuple(presentation_bypass_entries(name, pyproject_text)),
        has_contract_check_script=has_contract_check_script(product_dir),
        has_narrowed_turbo=has_narrowed_turbo_inputs(
            product_dir, permanent_modules, carveout_modules, MODEL_SURFACE_PREFIXES
        ),
        permanent_exposures=tuple(sorted(permanent_modules)),
        uncovered_permanent_exposures=tuple(sorted(uncovered_permanent_modules(product_dir, permanent_modules))),
        unqualified_permanent_exposures=tuple(
            sorted(unqualified_permanent_modules(module_path, permanent_modules, repo_root=repo_root))
        ),
        facade_leaks=reexports.leaks,
        unwatched_garages=tuple(sorted(unwatched_garages(product_dir, driven_wiring_locations))),
        driven_wiring_locations=tuple(sorted(driven_wiring_locations or ())),
        uncovered_carveout_modules=tuple(sorted(uncovered_carveout_modules(product_dir, carveout_modules))),
        model_crossings=reexports.model_crossings,
        uncovered_model_surface=tuple(sorted(unwatched_model_surface(product_dir))),
    )
