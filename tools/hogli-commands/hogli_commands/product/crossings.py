"""Classify every use of a watched-models crossing class in consumer code, and rank it by kind.

Default-deny: a use is allowed only when this module recognizes it as one of the instance-free shapes
(annotation, `DoesNotExist`, a nested enum or class attribute, `_meta`, a scalar-terminated manager
chain, a chain embedded in `Exists`/`Subquery`); every other use is disallowed, including shapes
nobody has classified yet.

The allowance in `MODEL_CROSSINGS` says which model classes may leave their product at all. It says
nothing about what a consumer then does with them, so a sanctioned crossing still hides a
`ModelSerializer`, a soft-delete write, or a row lock sitting in the wrong product. This module reads
the other side of that coupling: for each crossing class it resolves the concrete module the class is
defined in, follows re-export chains so an import from any path counts, and buckets every name-level
use in consumer code by kind. `product:crossings` reports; the repo-invariant ratchet enforces.

The name-level scan stays on the allowance classes, because an import of any other product model is
already tach's to refuse. `apps.get_model('label', 'Class')` is the channel tach cannot refuse: it
resolves through the Django app registry, leaves no import edge, and so reaches any product model
from anywhere. That scan therefore runs over every model class a product registers, and each foreign
reference is counted as the disallowed kind `get_model`.

Tests are out of scope on both model channels. A test reaches concrete classes through testing doors
on purpose, so counting its fixtures would measure the fixture, not the coupling. That leaves
`apps.get_model` in a test fixture uncounted; it is still a dependency with the import edge removed,
not a sanctioned door.

The third channel reads tests only. Core runs a product's query runners by the query's kind string.
A test outside the product can therefore execute a runner in the wiring location
`backend/hogql_queries/` with no import. The isolated tests are sound for that location only while
no such test exists. Each such test is counted as the disallowed kind `drives(<Kind>)`, and
`hogli product:lint` keeps the location in the contract-check inputs while a line for it stands. A
test that imports anything the location defines, through the facade or directly, is counted as
`drives(<Name>)`.
"""

from __future__ import annotations

import os
import re
import ast
import textwrap
import warnings
import functools
from collections import Counter, defaultdict
from collections.abc import Callable, Iterable, Iterator, Mapping
from dataclasses import dataclass
from pathlib import Path

from .ast_helpers import ast_parse_safe, get_model_names, lazy_reexport_map
from .isolation import COMPUTED_WIRING_LOCATIONS, MODEL_CROSSINGS, facade_model_crossings
from .paths import PRODUCTS_DIR, REPO_ROOT

# Where Python that can consume a product model lives. Everything else at the repo root is
# frontend, infra, or standalone tooling that never imports Django product models.
SCANNED_ROOTS: tuple[str, ...] = ("posthog", "ee", "products", "common")
SKIPPED_DIRS: frozenset[str] = frozenset({"node_modules", ".venv", "venv", "__pycache__", ".git", ".mypy_cache"})

# Model manager attributes a crossing class exposes. A chain rooted at one of these is a queryset.
MANAGERS: frozenset[str] = frozenset(
    {
        "objects",
        "all_teams",
        "raw_objects",
        "objects_including_soft_deleted",
        "objects_with_deleted",
        "all_objects",
        "_default_manager",
        "_base_manager",
    }
)

# Queryset terminals that return scalars, tuples, or dicts — never model instances.
SCALAR_TERMINALS: frozenset[str] = frozenset({"values", "values_list", "count", "exists", "aggregate"})

# `_meta` attributes that lead back to a manager, so a chain through them is a queryset again.
META_MANAGERS: frozenset[str] = frozenset({"default_manager", "base_manager"})

# `_meta` attributes that hand the model class back, so the chain after them starts over.
META_CLASS_ATTRS: frozenset[str] = frozenset({"model", "concrete_model", "proxy_for_model"})

# Queryset terminals that return exactly one model instance.
SINGLE_TERMINALS: frozenset[str] = frozenset({"get", "first", "last", "earliest", "latest"})

# Queryset methods that write rows.
WRITE_METHODS: frozenset[str] = frozenset(
    {
        "create",
        "update",
        "delete",
        "get_or_create",
        "update_or_create",
        "bulk_create",
        "bulk_update",
        "acreate",
        "aupdate",
        "adelete",
        "abulk_create",
    }
)

# ORM wrappers that embed a queryset as a subquery — the rows never materialize in the consumer.
SUBQUERY_CALLS: frozenset[str] = frozenset({"Exists", "Subquery"})

ALLOWED_KIND_PREFIXES: tuple[str, ...] = (
    "annotation",
    "exception",
    "nested-class-attr",
    "_meta",
    "scalar-chain",
    "subquery",
)


def kind_is_allowed(kind: str) -> bool:
    """True for the instance-free shapes the doctrine recognizes. Everything else is disallowed."""
    return kind.startswith(ALLOWED_KIND_PREFIXES)


@dataclass(frozen=True)
class CrossingClass:
    """A watched-models crossing class, resolved to the module that defines it."""

    product: str
    class_name: str
    defining_module: str  # dotted, e.g. "products.alerts.backend.models.alert"

    @property
    def label(self) -> str:
        return f"{self.product}.{self.class_name}"


@dataclass(frozen=True)
class CrossingUse:
    """One kind of use of one crossing class in one consumer module, with how often it appears."""

    crossing: str  # CrossingClass.label
    consumer_module: str  # dotted, e.g. "products.product_analytics.backend.presentation.insight"
    kind: str
    count: int

    @property
    def is_allowed(self) -> bool:
        return kind_is_allowed(self.kind)

    def as_baseline_line(self) -> str:
        return f"{self.crossing} {self.consumer_module} {self.kind} {self.count}"


# ---------------------------------------------------------------------------
# Resolving crossing classes and the modules that hand them out
# ---------------------------------------------------------------------------


_REPO_PREFIX = f"{REPO_ROOT}{os.sep}"


def _dotted_module(path: Path) -> str:
    """Repo path -> dotted module name ('posthog/models/__init__.py' -> 'posthog.models').

    String work on purpose: `Path.relative_to` is too slow for every file in the repo."""
    parts = str(path).removeprefix(_REPO_PREFIX).removesuffix(".py").split(os.sep)
    if parts[-1] == "__init__":
        parts.pop()
    return ".".join(parts)


def _model_modules(product: str) -> Iterator[Path]:
    backend = PRODUCTS_DIR / product / "backend"
    flat = backend / "models.py"
    if flat.is_file():
        yield flat
    package = backend / "models"
    if package.is_dir():
        yield from sorted(package.rglob("*.py"))


def _defining_module(product: str, class_name: str) -> str | None:
    """The dotted module whose top level defines `class_name`, searched across the model surface."""
    for path in _model_modules(product):
        tree = ast_parse_safe(path)
        if tree is None:
            continue
        if any(isinstance(node, ast.ClassDef) and node.name == class_name for node in tree.body):
            return _dotted_module(path)
    return None


def crossing_classes(products: Iterable[str] | None = None) -> list[CrossingClass]:
    """Every crossing class of the requested products (all of them when `products` is None).

    `MODEL_CROSSINGS` is the register; a product's facade re-exports are read too, so a class the
    facade hands out is covered even before the register catches up."""
    wanted = set(products) if products is not None else {p for p, _ in MODEL_CROSSINGS}
    names: set[tuple[str, str]] = {(p, c) for p, c in MODEL_CROSSINGS if p in wanted}
    for product in sorted(wanted):
        backend_dir = PRODUCTS_DIR / product / "backend"
        if backend_dir.is_dir():
            names.update((product, f.class_name) for f in facade_model_crossings(backend_dir, product))
    resolved = []
    for product, class_name in sorted(names):
        module = _defining_module(product, class_name)
        if module is not None:
            resolved.append(CrossingClass(product, class_name, module))
    return resolved


def _app_labels() -> dict[str, str]:
    """Django app label -> product name, read off each product's AppConfig."""
    labels: dict[str, str] = {}
    for apps_py in sorted(PRODUCTS_DIR.glob("*/backend/apps.py")):
        product = apps_py.parents[1].name
        try:
            tree = ast.parse(apps_py.read_text(encoding="utf-8", errors="ignore"))
        except (SyntaxError, OSError):
            continue
        for node in ast.walk(tree):
            if not isinstance(node, ast.Assign):
                continue
            target = node.targets[0]
            if isinstance(target, ast.Name) and target.id == "label" and isinstance(node.value, ast.Constant):
                labels[str(node.value.value)] = product
    return labels


def product_model_labels(products: Iterable[str] | None = None) -> dict[str, str]:
    """`product.Class` -> owning product, for every model class a product's app registers.

    Wider than `crossing_classes` on purpose. `apps.get_model('label', 'Class')` reaches a model
    through the app registry, so neither tach nor import-linter sees the edge and the watched-models
    allowance never had to name the class. The label scan therefore covers every product model, not
    only the allowance ones. A product without an `apps.py` registers nothing and is skipped."""
    registered = set(_app_labels().values())
    wanted = registered if products is None else registered & set(products)
    return {
        f"{product}.{class_name}": product
        for product in sorted(wanted)
        for class_name in get_model_names(PRODUCTS_DIR / product / "backend")
    }


# ---------------------------------------------------------------------------
# Candidate files
# ---------------------------------------------------------------------------


def _is_test_module(path: Path) -> bool:
    if "test" in path.parts or "tests" in path.parts:
        return True
    return path.name.startswith("test_") or path.name.endswith("_test.py") or path.name == "conftest.py"


def _is_out_of_scope_module(path: Path) -> bool:
    """Tests reach concrete classes through testing doors, so they are not consumers. A migration
    reaches a model through the historical registry, which is the only way a migration can."""
    return _is_test_module(path) or "migrations" in path.parts


@dataclass(frozen=True, slots=True)
class _ImportEdge:
    """One `from module import exported as bound`."""

    module: str
    exported: str
    bound: str


@dataclass(frozen=True, slots=True)
class _ModuleAlias:
    """A module bound to a local name, by `import a.b as c` or by `from a import b` when `a.b` is a module."""

    alias: str
    module: str


@dataclass(frozen=True)
class _ImportTable:
    """Everything a file's import statements bind: names, and modules it may read names off."""

    edges: tuple[_ImportEdge, ...]
    module_aliases: tuple[_ModuleAlias, ...]


@dataclass(frozen=True)
class _Candidate:
    """A scanned file with its imports read but its body not yet parsed."""

    path: Path
    dotted: str
    imports: _ImportTable
    mentions_get_model: bool
    mentions_query_kind: bool = False


# One import statement, parenthesized or not. Imports are the only thing the first pass reads, and
# re-parsing just them is an order of magnitude cheaper than building the whole file's AST twice.
_IMPORT_STATEMENT_RE = re.compile(
    rb"^[ \t]*(?:from[ \t]+[.\w]+[ \t]+import[ \t]+(?:\([^)]*\)|[^\n]*)|import[ \t]+[\w., \t]*)",
    re.MULTILINE,
)


def _resolve_import_from(node: ast.ImportFrom, package: str) -> str | None:
    """The absolute dotted module an ImportFrom reads from, resolving relative levels."""
    if not node.level:
        return node.module
    parts = package.split(".")
    climb = node.level - 1
    if climb:
        parts = parts[:-climb]
    if not parts:
        return None
    base = ".".join(parts)
    return f"{base}.{node.module}" if node.module else base


def _read_imports(source: bytes, package: str) -> _ImportTable:
    """What a file's import statements bind, read from those statements alone.

    Deferred and `if TYPE_CHECKING` imports come along: the statements are lifted out of their
    block and re-parsed at top level, which is all the relative level needs to resolve.

    `from a.b import c` binds a module when `a.b.c` is one, so every such name is recorded as a
    module alias too; the scan keeps only the aliases whose module hands out a crossing class."""
    lifted = b"\n".join(match.group(0).lstrip() for match in _IMPORT_STATEMENT_RE.finditer(source))
    try:
        tree = ast.parse(lifted)
    except (SyntaxError, ValueError):
        return _ImportTable((), ())
    edges: list[_ImportEdge] = []
    aliases: list[_ModuleAlias] = []
    for node in tree.body:
        if isinstance(node, ast.ImportFrom):
            module = _resolve_import_from(node, package)
            if module is None:
                continue
            for alias in node.names:
                bound = alias.asname or alias.name
                edges.append(_ImportEdge(module, alias.name, bound))
                aliases.append(_ModuleAlias(bound, f"{module}.{alias.name}"))
        elif isinstance(node, ast.Import):
            aliases.extend(_ModuleAlias(alias.asname or alias.name, alias.name) for alias in node.names)
    return _ImportTable(tuple(edges), tuple(aliases))


def _candidates(kind_hint: _KindHint | None = None) -> list[_Candidate]:
    """Every scanned .py file, with its imports read.

    Reading imports only is what keeps the full AST pass — and so the repo-invariant test — small:
    a file is parsed whole only once its imports show it can reach a crossing class. The two
    textual hints (`get_model`, a product query kind) are read here too, while the bytes are in
    hand, so the scan never re-reads a file just to rule it out."""
    found = []
    for root in SCANNED_ROOTS:
        for path in sorted((REPO_ROOT / root).rglob("*.py")):
            if SKIPPED_DIRS.intersection(path.parts):
                continue
            source = path.read_bytes()
            dotted = _dotted_module(path)
            package = dotted if path.name == "__init__.py" else dotted.rsplit(".", 1)[0]
            mentions_kind = kind_hint is not None and _is_test_module(path) and kind_hint.matches(source)
            found.append(
                _Candidate(path, dotted, _read_imports(source, package), b"get_model" in source, mentions_kind)
            )
    return found


# ---------------------------------------------------------------------------
# Which local names are bound to a crossing class
# ---------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class _Export:
    """A name as one module hands it out."""

    module: str
    name: str


def _origins(candidates: list[_Candidate], classes: list[CrossingClass]) -> dict[_Export, str]:
    """Export -> crossing label, for every path an import of the class can take."""
    return _grow_origins(candidates, {_Export(c.defining_module, c.class_name): c.label for c in classes})


def _grow_origins(candidates: list[_Candidate], seeds: dict[_Export, str]) -> dict[_Export, str]:
    """Seeded with the defining module and grown to a fixpoint over re-exports, so `facade/models.py`,
    a package `__init__`, and a renaming alias all resolve back to the same label."""
    origins = dict(seeds)
    while True:
        grew = False
        for candidate in candidates:
            for edge in candidate.imports.edges:
                label = origins.get(_Export(edge.module, edge.exported))
                if label is None:
                    continue
                local = _Export(candidate.dotted, edge.bound)
                if origins.get(local) != label:
                    origins[local] = label
                    grew = True
        if not grew:
            return origins


def _bound_names(candidate: _Candidate, origins: dict[_Export, str]) -> dict[str, str]:
    """Local name -> crossing label, for every crossing class this file imported."""
    names = {}
    for edge in candidate.imports.edges:
        label = origins.get(_Export(edge.module, edge.exported))
        if label is not None:
            names[edge.bound] = label
    return names


def _dotted_of(node: ast.expr) -> str | None:
    if isinstance(node, ast.Name):
        return node.id
    if isinstance(node, ast.Attribute):
        base = _dotted_of(node.value)
        return f"{base}.{node.attr}" if base else None
    return None


def _callee_name(node: ast.Call) -> str | None:
    func = node.func
    if isinstance(func, ast.Name):
        return func.id
    if isinstance(func, ast.Attribute):
        return func.attr
    return None


def _class_nodes(
    tree: ast.Module, names: dict[str, str], module_aliases: dict[str, str], origins: dict[_Export, str]
) -> list[tuple[ast.expr, str]]:
    """Every expression node that names a crossing class, paired with its crossing label."""
    found: list[tuple[ast.expr, str]] = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Name) and node.id in names:
            found.append((node, names[node.id]))
        elif isinstance(node, ast.Attribute) and module_aliases:
            dotted = _dotted_of(node.value)
            module = module_aliases.get(dotted) if dotted else None
            label = origins.get(_Export(module, node.attr)) if module else None
            if label is not None:
                found.append((node, label))
    return found


# ---------------------------------------------------------------------------
# Classification
# ---------------------------------------------------------------------------


def _parent_map(tree: ast.Module) -> dict[int, ast.AST]:
    parents: dict[int, ast.AST] = {}
    for node in ast.walk(tree):
        for child in ast.iter_child_nodes(node):
            parents[id(child)] = node
    return parents


def _chain(node: ast.expr, parents: dict[int, ast.AST]) -> tuple[list[str], ast.AST]:
    """Attribute/call chain hanging off `node`: its method names, and the outermost node it reaches."""
    methods: list[str] = []
    current: ast.AST = node
    while True:
        parent = parents.get(id(current))
        if isinstance(parent, ast.Attribute) and parent.value is current:
            methods.append(parent.attr)
        elif isinstance(parent, ast.Call) and parent.func is current:
            pass
        else:
            return methods, current
        current = parent


def _enclosing_call_name(node: ast.AST, parents: dict[int, ast.AST]) -> str | None:
    """The callee name of the nearest enclosing call, not crossing a def/class boundary."""
    current = parents.get(id(node))
    while current is not None:
        if isinstance(current, ast.Call):
            name = _callee_name(current)
            if name:
                return name
        if isinstance(current, ast.FunctionDef | ast.AsyncFunctionDef | ast.ClassDef):
            return None
        current = parents.get(id(current))
    return None


def _in_annotation(node: ast.expr, parents: dict[int, ast.AST]) -> bool:
    child: ast.AST = node
    parent = parents.get(id(child))
    while parent is not None:
        if isinstance(parent, ast.arg) and parent.annotation is child:
            return True
        if isinstance(parent, ast.FunctionDef | ast.AsyncFunctionDef) and parent.returns is child:
            return True
        if isinstance(parent, ast.AnnAssign) and parent.annotation is child:
            return True
        if not isinstance(parent, ast.Subscript | ast.BinOp | ast.Tuple | ast.Attribute | ast.Constant):
            return False
        child = parent
        parent = parents.get(id(child))
    return False


def _manager_chain_kind(methods: list[str], outer: ast.AST, parents: dict[int, ast.AST]) -> str:
    """Classify a queryset chain. Row locking and prefetching win over whatever terminates the chain."""
    enclosing = _enclosing_call_name(outer, parents)
    terminal = methods[-1] if methods else "manager"
    if "select_for_update" in methods:
        return "lock"
    writes = [m for m in methods if m in WRITE_METHODS]
    if writes:
        return f"write({','.join(writes)})"
    if enclosing == "Prefetch":
        return "prefetch"
    if enclosing in SUBQUERY_CALLS:
        return f"subquery({enclosing})"
    if terminal in SCALAR_TERMINALS:
        return f"scalar-chain({terminal})"
    if enclosing is not None and enclosing.endswith("Field"):
        return "drf-field-queryset"
    if terminal in SINGLE_TERMINALS:
        return "instance-single"
    return f"instance-many({terminal})"


def _attribute_chain_kind(methods: list[str], outer: ast.AST, parents: dict[int, ast.AST]) -> str:
    """Classify an attribute chain hanging off the class; `methods` is non-empty."""
    head = methods[0]
    if head == "DoesNotExist":
        return "exception"
    if head == "_meta":
        if len(methods) == 1:
            return "_meta"
        if methods[1] in META_MANAGERS:
            return _manager_chain_kind(methods[2:], outer, parents)
        if methods[1] in META_CLASS_ATTRS:
            return _attribute_chain_kind(methods[2:], outer, parents) if len(methods) > 2 else "_meta"
        return "_meta" if methods[1] != "managers" else "other(Attribute:_meta.managers)"
    if head in MANAGERS:
        return _manager_chain_kind(methods[1:], outer, parents)
    if head[:1].isupper():
        return f"nested-class-attr({head})"
    return f"other(Attribute:{head})"


def classify_use(node: ast.expr, parents: dict[int, ast.AST]) -> str:
    """The kind of one name-level use of a crossing class."""
    if _in_annotation(node, parents):
        return "annotation"
    methods, outer = _chain(node, parents)
    if methods:
        return _attribute_chain_kind(methods, outer, parents)
    parent = parents.get(id(node))
    if isinstance(parent, ast.Call):
        if parent.func is node:
            return "construct"
        callee = _dotted_of(parent.func) or "?"
        callee = callee.rsplit(".", 1)[-1]
        return "isinstance" if callee == "isinstance" else f"passed-as-class({callee})"
    if isinstance(parent, ast.Assign) and any(isinstance(t, ast.Name) and t.id == "model" for t in parent.targets):
        return "drf-model-serializer"
    if isinstance(parent, ast.keyword) and parent.arg == "model":
        return "drf-model-serializer"
    if isinstance(parent, ast.Tuple | ast.List | ast.Dict | ast.Set | ast.Subscript):
        return "in-collection"
    return f"other({type(parent).__name__})"


def _get_model_uses(tree: ast.Module, product_by_label: dict[str, str], label_by_lower: dict[str, str]) -> Counter[str]:
    """`apps.get_model('label', 'Class')`, its `'label.Class'` and keyword forms, which no import reveals."""
    found: Counter[str] = Counter()
    for node in ast.walk(tree):
        if not isinstance(node, ast.Call) or getattr(node.func, "attr", None) != "get_model":
            continue
        strings = [a.value for a in node.args if isinstance(a, ast.Constant) and isinstance(a.value, str)]
        keywords = {
            k.arg: k.value.value
            for k in node.keywords
            if k.arg in ("app_label", "model_name")
            and isinstance(k.value, ast.Constant)
            and isinstance(k.value.value, str)
        }
        app_label = keywords.get("app_label", strings[0] if strings else None)
        class_name = keywords.get("model_name", strings[1] if len(strings) > 1 else None)
        if app_label is not None and class_name is None and "." in app_label:
            app_label, class_name = app_label.split(".", 1)
        if app_label is None or class_name is None:
            continue
        product = product_by_label.get(app_label)
        label = label_by_lower.get(f"{product}.{class_name}".lower()) if product is not None else None
        if label is not None:
            found[label] += 1
    return found


# ---------------------------------------------------------------------------
# Wiring locations that tests outside the product drive
# ---------------------------------------------------------------------------


# Core's query dispatch table: `if kind == "X": from products.<p>... import XRunner`, and the
# wiring location that holds the runners it dispatches to. The kind channel is what makes that
# location computable, so it must be in the computed set. Some branches compare against the
# `NodeKind` enum instead of a literal; the enum values are read off the generated module.
QUERY_DISPATCHER = REPO_ROOT / "posthog" / "hogql_queries" / "query_runner.py"
NODE_KIND_ENUM = REPO_ROOT / "posthog" / "schema_enums.py"
_NODE_KIND_CLASS_RE = re.compile(r"^class NodeKind\(.*?\):\n(.*?)(?=^class |\Z)", re.MULTILINE | re.DOTALL)
_ENUM_MEMBER_RE = re.compile(r"^\s+(\w+)\s*=\s*[\"'](\w+)[\"']", re.MULTILINE)
QUERY_WIRING_LOCATION = "backend/hogql_queries/"
assert QUERY_WIRING_LOCATION in COMPUTED_WIRING_LOCATIONS

# The calls that hand a query to core's dispatcher, and so execute whichever runner owns its kind.
DISPATCH_CALLS: frozenset[str] = frozenset(
    {"process_query_dict", "process_query_model", "process_query", "get_query_runner", "get_query_runner_or_none"}
)

# The Django test client runs a request in-process, so a query posted to any endpoint that executes
# queries (query, insights, endpoints, exports) reaches the runner the same way.
TEST_CLIENT_METHODS: frozenset[str] = frozenset({"get", "post", "put", "patch", "delete"})


def wiring_location_label(product: str, location: str) -> str:
    """The baseline label of one product's wiring location, e.g. `product_analytics:backend/hogql_queries/`."""
    return f"{product}:{location}"


@dataclass(frozen=True, slots=True, order=True)
class _WiringLocation:
    """One computed wiring location of one product."""

    product: str
    location: str

    @property
    def label(self) -> str:
        return wiring_location_label(self.product, self.location)


@dataclass(frozen=True, slots=True)
class _KindDrive:
    """A product query kind a test both builds and runs."""

    product: str
    kind: str


def _node_kind_values(source: str) -> dict[str, str]:
    """`NodeKind` member name -> kind string, read off the enum's source without importing it."""
    match = _NODE_KIND_CLASS_RE.search(source)
    return dict(_ENUM_MEMBER_RE.findall(match.group(1))) if match else {}


def _kinds_in_dispatcher(source: str, node_kinds: Mapping[str, str] | None = None) -> dict[str, frozenset[str]]:
    """Query kind -> products whose runners its dispatch branch can reach.

    The whole branch is read, not only its direct statements: a core kind can hand off to a
    product runner under a nested condition (a trends query tagged for web analytics), and a test
    that runs that kind may then execute product code."""
    tree = ast.parse(source)
    kinds: dict[str, set[str]] = {}
    for node in ast.walk(tree):
        if not isinstance(node, ast.If):
            continue
        branch_kinds = _compared_kinds(node.test, node_kinds or {})
        if not branch_kinds:
            continue
        products = {
            statement.module.split(".")[1]
            for body_statement in node.body
            for statement in ast.walk(body_statement)
            if isinstance(statement, ast.ImportFrom) and statement.module and statement.module.startswith("products.")
        }
        for kind in branch_kinds:
            kinds.setdefault(kind, set()).update(products)
    return {kind: frozenset(products) for kind, products in kinds.items() if products}


def _compared_kinds(test: ast.expr, node_kinds: Mapping[str, str]) -> list[str]:
    """The kinds of `kind == "X"`, `kind == NodeKind.X`, or `kind in (...)`; empty for any other test."""
    if not (isinstance(test, ast.Compare) and isinstance(test.left, ast.Name) and test.left.id == "kind"):
        return []
    target = test.comparators[0]
    members = target.elts if isinstance(target, ast.Tuple) else [target]
    kinds = []
    for member in members:
        if isinstance(member, ast.Constant) and isinstance(member.value, str):
            kinds.append(member.value)
        elif isinstance(member, ast.Attribute) and isinstance(member.value, ast.Name) and member.value.id == "NodeKind":
            if member.attr in node_kinds:
                kinds.append(node_kinds[member.attr])
    return kinds


@dataclass(frozen=True)
class _QueryKinds:
    """The product query kinds core dispatches, by literal and by `NodeKind` member.

    A test names a kind either way (`"PathsQuery"` or `NodeKind.PATHS_QUERY`); both must count."""

    products: Mapping[str, frozenset[str]]  # kind -> products whose runners it can reach
    members: Mapping[str, str]  # NodeKind member -> kind, for the kinds in `products`

    def __bool__(self) -> bool:
        return bool(self.products)


def product_query_kinds(products: Iterable[str] | None = None) -> _QueryKinds:
    """The query kinds that reach product runners, read off core's dispatch table."""
    node_kinds = _node_kind_values(NODE_KIND_ENUM.read_text(encoding="utf-8"))
    kinds = _kinds_in_dispatcher(QUERY_DISPATCHER.read_text(encoding="utf-8"), node_kinds)
    if products is not None:
        wanted = frozenset(products)
        kinds = {kind: owners & wanted for kind, owners in kinds.items() if owners & wanted}
    return _QueryKinds(kinds, {member: kind for member, kind in node_kinds.items() if kind in kinds})


def _wiring_location_exports(product: str, location: str) -> dict[_Export, str]:
    """Every name a module in the wiring location defines at top level, labeled with the location.

    A facade module that hands those names out through a PEP 562 lazy map is an export path too,
    so an import through the facade resolves to the location like a static re-export would."""
    label = wiring_location_label(product, location)
    root = PRODUCTS_DIR / product / location.rstrip("/")
    paths = sorted(root.rglob("*.py")) if root.is_dir() else [root] if root.is_file() else []
    exports: dict[_Export, str] = {}
    for path in paths:
        tree = ast_parse_safe(path)
        if tree is None:
            continue
        module = _dotted_module(path)
        for node in tree.body:
            if isinstance(node, ast.ClassDef | ast.FunctionDef | ast.AsyncFunctionDef):
                exports[_Export(module, node.name)] = label
    for facade_path in sorted((PRODUCTS_DIR / product / "backend" / "facade").glob("*.py")):
        tree = ast_parse_safe(facade_path)
        if tree is None:
            continue
        for name, source in _lazy_reexports(tree, product, _module_exists).items():
            if (REPO_ROOT / source.replace(".", "/")).with_suffix(".py").is_relative_to(root):
                exports[_Export(_dotted_module(facade_path), name)] = label
    return exports


def _module_exists(dotted: str) -> bool:
    path = REPO_ROOT / dotted.replace(".", "/")
    return path.with_suffix(".py").is_file() or (path / "__init__.py").is_file()


def _lazy_reexports(tree: ast.Module, product: str, exists: Callable[[str], bool]) -> dict[str, str]:
    """Exported name -> absolute dotted source module, for a facade's PEP 562 lazy map.

    Lazy maps store their values relative to some package: absolute, relative to the product's
    backend package, or relative to a module-level prefix constant (`_B = "products....hogql_queries."`).
    The first candidate that names a real module wins."""
    prefixes = [
        node.value.value
        for node in tree.body
        if isinstance(node, ast.Assign)
        and isinstance(node.value, ast.Constant)
        and isinstance(node.value.value, str)
        and node.value.value.endswith(".")
    ]
    resolved: dict[str, str] = {}
    for name, value in lazy_reexport_map(tree).items():
        candidates = [value, *(prefix + value for prefix in prefixes), f"products.{product}.backend.{value}"]
        for candidate in candidates:
            if exists(candidate):
                resolved[name] = candidate
                break
    return resolved


def _is_test_client_call(node: ast.Call) -> bool:
    func = node.func
    if not isinstance(func, ast.Attribute) or func.attr not in TEST_CLIENT_METHODS:
        return False
    receiver = _dotted_of(func.value)
    return receiver is not None and receiver.endswith("client")


def _kind_mentions(tree: ast.Module, kinds: _QueryKinds) -> list[tuple[ast.AST, str]]:
    """Nodes where a product query kind enters a query: `{"kind": "X"}`, `{"kind": NodeKind.X}`, or
    the schema constructor `X(...)`.

    A bare string (a parametrize row, a URL segment) is not a query and is not counted."""
    found: list[tuple[ast.AST, str]] = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Dict):
            for key, value in zip(node.keys, node.values):
                if not (isinstance(key, ast.Constant) and key.value == "kind"):
                    continue
                kind = _kind_of(value, kinds)
                if kind is not None:
                    found.append((node, kind))
        elif isinstance(node, ast.Call):
            name = _callee_name(node)
            if name in kinds.products:
                found.append((node, name))
    return found


def _kind_of(value: ast.expr, kinds: _QueryKinds) -> str | None:
    if isinstance(value, ast.Constant) and value.value in kinds.products:
        return str(value.value)
    if isinstance(value, ast.Attribute) and isinstance(value.value, ast.Name) and value.value.id == "NodeKind":
        return kinds.members.get(value.attr)
    return None


_Function = ast.FunctionDef | ast.AsyncFunctionDef


def _enclosing(node: ast.AST, parents: dict[int, ast.AST]) -> tuple[_Function | None, ast.ClassDef | None]:
    """The nearest function and the nearest class around `node`; a decorator counts as inside its function."""
    function: _Function | None = None
    current = parents.get(id(node))
    while current is not None:
        if isinstance(current, _Function) and function is None:
            function = current
        if isinstance(current, ast.ClassDef):
            return function, current
        current = parents.get(id(current))
    return function, None


def _executes_directly(scope: ast.AST) -> bool:
    return any(
        isinstance(node, ast.Call) and (_callee_name(node) in DISPATCH_CALLS or _is_test_client_call(node))
        for node in ast.walk(scope)
    )


class _Executions:
    """Which functions of a module execute queries, directly or through a helper they call.

    A test method that builds a query and hands it to `self._run(...)` executes it one call away;
    following one hop by name covers that without walking a real call graph. Helpers resolve inside
    the function's own class (or the module for a plain function), so two classes with a method of
    the same name never answer for each other."""

    def __init__(self) -> None:
        self._direct: dict[int, bool] = {}

    def _executes_directly(self, function: _Function) -> bool:
        if id(function) not in self._direct:
            self._direct[id(function)] = _executes_directly(function)
        return self._direct[id(function)]

    def executes(self, function: _Function, scope: ast.AST) -> bool:
        if self._executes_directly(function):
            return True
        helpers = {node.name: node for node in ast.iter_child_nodes(scope) if isinstance(node, _Function)}
        called = {_callee_name(node) for node in ast.walk(function) if isinstance(node, ast.Call)}
        return any(self._executes_directly(helpers[name]) for name in called if name in helpers)


def kind_drives(tree: ast.Module, kinds: _QueryKinds) -> Counter[_KindDrive]:
    """Drive -> mentions, for every kind this module both builds and executes.

    Building alone is not a drive: a test that checks a schema or a formatter constructs the query
    and never runs it. Execution is a dispatcher call or a test-client request. A kind built inside
    a test function counts when that function executes (itself or through a helper it calls); a
    kind built elsewhere, a `setUp` fixture or a class attribute, counts when any function of the
    enclosing class (or of the module, outside a class) executes."""
    mentions = _kind_mentions(tree, kinds)
    if not mentions:
        return Counter()
    parents = _parent_map(tree)
    executions = _Executions()
    scope_executes: dict[int, bool] = {}
    found: Counter[_KindDrive] = Counter()
    for node, kind in mentions:
        function, class_def = _enclosing(node, parents)
        scope: ast.AST = class_def if class_def is not None else tree
        if function is not None and function.name.startswith("test"):
            executes = executions.executes(function, scope)
        else:
            if id(scope) not in scope_executes:
                scope_executes[id(scope)] = _executes_directly(scope)
            executes = scope_executes[id(scope)]
        if executes:
            for product in kinds.products[kind]:
                found[_KindDrive(product, kind)] += 1
    return found


def _wiring_location_targets(products: list[str] | None) -> set[_WiringLocation]:
    """Every computed wiring location that exists, in the products the scan covers.

    Every product with the directory counts, not only the products in the dispatch table. The
    import channel applies to all of them, and a location the scan did not read must not count as
    clean."""
    owners = [d.name for d in PRODUCTS_DIR.iterdir() if d.is_dir()] if products is None else products
    return {
        _WiringLocation(product, location)
        for location in COMPUTED_WIRING_LOCATIONS
        for product in owners
        if (PRODUCTS_DIR / product / location.rstrip("/")).exists()
    }


def driven_wiring_locations(product: str, path: Path | None = None) -> frozenset[str]:
    """The computed wiring locations of `product` that a test outside the product drives.

    Read from the crossings baseline. The baseline is the evidence the lint reads: the repo-invariant
    test keeps it equal to a fresh scan, so a location with no line here has no outside driver."""
    prefix = f"{product}:"
    return frozenset(
        line.split(" ", 1)[0].removeprefix(prefix)
        for line in _baseline_lines(path or BASELINE_PATH)
        if line.startswith(prefix)
    )


@functools.lru_cache(maxsize=4)
def _baseline_lines(path: Path) -> tuple[str, ...]:
    """Read once per process: `product:lint --all` asks for every product's locations in one run."""
    return tuple(read_baseline(path))


# ---------------------------------------------------------------------------
# Scan
# ---------------------------------------------------------------------------


def _alternation(names: Iterable[str]) -> bytes:
    return b"|".join(sorted(re.escape(n).encode() for n in names))


@dataclass(frozen=True)
class _KindHint:
    """A cheap test for the textual shapes `_kind_mentions` accepts, so a file that only names a
    kind in a parametrize row or a URL is never parsed.

    The alternation over every kind is slow at each position of a large file; the longest common
    suffix of the kinds ("Query" today) gates it with one substring search, and `NodeKind.` gates
    the enum form."""

    gate: bytes
    pattern: re.Pattern[bytes]

    @classmethod
    def for_kinds(cls, kinds: _QueryKinds) -> _KindHint:
        names = sorted(kinds.products)
        reversed_common = os.path.commonprefix([name[::-1] for name in names])
        alternation = _alternation(names)
        pattern = (
            rb"[\"']kind[\"']\s*:\s*[\"'](?:" + alternation + rb")[\"']|\b(?:" + alternation + rb")\("
            rb"|NodeKind\.(?:" + _alternation(kinds.members) + rb")\b"
        )
        return cls(reversed_common[::-1].encode(), re.compile(pattern))

    def matches(self, source: bytes) -> bool:
        return (self.gate in source or b"NodeKind." in source) and self.pattern.search(source) is not None


def _reads_class_off_module(source: bytes, aliases: dict[str, str], class_names: set[str]) -> bool:
    """Whether `alias.ClassName` appears in the text at all, for any module alias and crossing class.

    Most files that alias a module handing out a crossing class never read the class off it, and
    this check spares them the full parse. The alias pattern is small and per file; the class names
    are matched as a set so the thousands of them are never compiled into a regex."""
    pattern = rb"\b(?:" + _alternation(aliases) + rb")\.(\w+)"
    return any(match.group(1).decode() in class_names for match in re.finditer(pattern, source))


def scan_crossing_uses(products: Iterable[str] | None = None) -> list[CrossingUse]:
    """Every use of every crossing class in consumer code, sorted, one entry per kind per module.

    Plus every `apps.get_model` reference to any product model from outside the owning product.
    Plus, from test modules only, every drive of a computed wiring location: `drives(<Kind>)` for a
    query kind the test builds and runs (see `kind_drives`), `drives(<Name>)` for an import of
    anything the location defines, by any re-export path. One pass over the tree serves all three
    channels."""
    # Consumed more than once below; a generator argument would silently empty the later passes.
    products = list(products) if products is not None else None
    classes = crossing_classes(products)
    owning_dir = {c.label: PRODUCTS_DIR / c.product for c in classes}
    owning_dir |= {label: PRODUCTS_DIR / product for label, product in product_model_labels(products).items()}
    kinds = product_query_kinds(products)
    locations = _wiring_location_targets(products)
    owning_dir |= {location.label: PRODUCTS_DIR / location.product for location in locations}
    if not owning_dir:
        return []

    seeds = {_Export(c.defining_module, c.class_name): c.label for c in classes}
    for location in sorted(locations):
        seeds |= _wiring_location_exports(location.product, location.location)
    # Tests are read for wiring-location exports only, and consumer code for model classes only.
    # A test that imports a model class (most API tests do) is then never parsed for nothing.
    names_by_scope = {
        True: {export.name for export, label in seeds.items() if ":" in label},
        False: {export.name for export, label in seeds.items() if ":" not in label},
    }
    candidates = _candidates(_KindHint.for_kinds(kinds) if kinds else None)
    origins = _grow_origins(candidates, seeds)
    origin_modules = {export.module for export in origins}
    query_products = {location.product for location in locations if location.location == QUERY_WIRING_LOCATION}
    product_by_label = _app_labels()
    # Django resolves a model name case-insensitively, so the get_model scan matches on the lowered form.
    label_by_lower = {label.lower(): label for label in owning_dir}

    counts: dict[tuple[str, str, str], int] = defaultdict(int)
    for candidate in candidates:
        is_test = _is_test_module(candidate.path)
        if not is_test and _is_out_of_scope_module(candidate.path):
            continue
        names = {name: label for name, label in _bound_names(candidate, origins).items() if (":" in label) == is_test}
        aliases = {a.alias: a.module for a in candidate.imports.module_aliases if a.module in origin_modules}
        hinted = candidate.mentions_query_kind if is_test else candidate.mentions_get_model
        if not names and not aliases and not hinted:
            continue
        try:
            source = candidate.path.read_bytes()
        except OSError:
            continue
        if not names and not hinted and not _reads_class_off_module(source, aliases, names_by_scope[is_test]):
            continue
        try:
            with warnings.catch_warnings():
                warnings.simplefilter("ignore", SyntaxWarning)
                tree = ast.parse(source)
        except (SyntaxError, ValueError):
            continue
        parents: dict[int, ast.AST] | None = None
        for node, label in _class_nodes(tree, names, aliases, origins):
            if (":" in label) != is_test or candidate.path.is_relative_to(owning_dir[label]):
                continue
            # A test drives whatever it imports from a wiring location; a model class use is classified.
            if is_test:
                name = node.id if isinstance(node, ast.Name) else node.attr
                counts[(label, candidate.dotted, f"drives({name})")] += 1
            else:
                parents = parents or _parent_map(tree)
                counts[(label, candidate.dotted, classify_use(node, parents))] += 1
        if is_test and candidate.mentions_query_kind:
            for drive, count in kind_drives(tree, kinds).items():
                if drive.product in query_products and not candidate.path.is_relative_to(PRODUCTS_DIR / drive.product):
                    counts[
                        (
                            wiring_location_label(drive.product, QUERY_WIRING_LOCATION),
                            candidate.dotted,
                            f"drives({drive.kind})",
                        )
                    ] += count
        if not is_test and candidate.mentions_get_model:
            for label, count in _get_model_uses(tree, product_by_label, label_by_lower).items():
                if not candidate.path.is_relative_to(owning_dir[label]):
                    counts[(label, candidate.dotted, "get_model")] += count

    return [CrossingUse(label, module, kind, count) for (label, module, kind), count in sorted(counts.items())]


def disallowed_uses(uses: Iterable[CrossingUse]) -> list[CrossingUse]:
    return [use for use in uses if not use.is_allowed]


# ---------------------------------------------------------------------------
# Reporting
# ---------------------------------------------------------------------------


def _render_kind_block(kind: str, entries: list[CrossingUse]) -> list[str]:
    total = sum(use.count for use in entries)
    modules = [
        use.consumer_module if use.count == 1 else f"{use.consumer_module} x{use.count}"
        for use in sorted(entries, key=lambda u: (-u.count, u.consumer_module))
    ]
    wrapped = textwrap.wrap(", ".join(modules), width=112, initial_indent=" " * 6, subsequent_indent=" " * 6)
    return [f"  {kind}  {total}", *wrapped]


def render_report(uses: list[CrossingUse], class_labels: Iterable[str] = ()) -> str:
    """Per crossing class: disallowed kinds first, each with its count and the consumer modules.

    A class with no uses at all is still listed — an entry nothing consumes is one the register can
    drop."""
    by_crossing: dict[str, list[CrossingUse]] = {label: [] for label in sorted(class_labels)}
    for use in uses:
        by_crossing.setdefault(use.crossing, []).append(use)
    if not by_crossing:
        return "No crossing classes resolved — nothing to report."

    lines: list[str] = []
    for crossing, entries in sorted(
        by_crossing.items(), key=lambda item: (-sum(u.count for u in disallowed_uses(item[1])), item[0])
    ):
        bad = disallowed_uses(entries)
        good = [use for use in entries if use.is_allowed]
        lines.append(f"\n{crossing}  {sum(u.count for u in bad)} disallowed, {sum(u.count for u in good)} allowed")
        if not entries:
            lines.append("  no uses in consumer code")
        elif not bad:
            lines.append("  no disallowed uses")
        by_kind: dict[str, list[CrossingUse]] = defaultdict(list)
        for use in bad:
            by_kind[use.kind].append(use)
        for kind, kind_entries in sorted(by_kind.items(), key=lambda item: (-sum(u.count for u in item[1]), item[0])):
            lines.extend(_render_kind_block(kind, kind_entries))
        if good:
            summary: Counter[str] = Counter()
            for use in good:
                summary[use.kind] += use.count
            allowed = ", ".join(f"{kind} {count}" for kind, count in sorted(summary.items()))
            lines.extend(
                textwrap.wrap(f"allowed: {allowed}", width=112, initial_indent="  ", subsequent_indent=" " * 6)
            )

    total_bad = sum(use.count for use in uses if not use.is_allowed)
    total_good = sum(use.count for use in uses if use.is_allowed)
    lines.append(f"\nTotal: {total_bad} disallowed, {total_good} allowed, across {len(by_crossing)} crossing classes.")
    lines.append("Disallowed uses are ratcheted in products/model_crossing_uses_baseline.txt — they may only go down.")
    return "\n".join(lines)


BASELINE_PATH = REPO_ROOT / "products" / "model_crossing_uses_baseline.txt"

BASELINE_HEADER = """\
# Disallowed uses of product model classes in consumer code.
# One line per (product.Class, consumer module, kind, count); see products/architecture.md
# § Wiring couplings for which shapes are allowed.
#
# Three channels land here. Name-level uses of a watched-models crossing class, in any kind the
# doctrine does not call instance-free. The kind `get_model`: an `apps.get_model` reference
# from outside the owning product, which covers every product model, not only the allowance ones.
# Test modules and migrations are out of scope on both: a migration reaches a model through the
# historical registry, which is the only way a migration can.
# And the kind `drives(<Kind or Name>)`, read from tests only: a test outside the product that
# executes a query runner in the product's wiring location backend/hogql_queries/, by the query
# kind it builds and runs, or by the name it imports from there. While a line stands for a
# location, `hogli product:lint` keeps that location in the contract-check inputs.
#
# Counts may only go down, and a line that disappears must be deleted here too.
# A new line needs a doctrine amendment, not a baseline edit.
#
# Regenerate: bin/hogli product:crossings --all --write-baseline
"""


def render_baseline(uses: Iterable[CrossingUse]) -> str:
    lines = sorted(use.as_baseline_line() for use in disallowed_uses(uses))
    return BASELINE_HEADER + "\n".join(lines) + "\n"


def read_baseline(path: Path = BASELINE_PATH) -> list[str]:
    return [line for line in path.read_text().splitlines() if line.strip() and not line.startswith("#")]


def write_baseline(uses: Iterable[CrossingUse], path: Path = BASELINE_PATH) -> None:
    path.write_text(render_baseline(uses))
    _baseline_lines.cache_clear()
