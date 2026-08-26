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

Tests are out of scope. A test reaches concrete classes through testing doors on purpose, so counting
its fixtures would measure the fixture, not the coupling. That leaves `apps.get_model` in a test
fixture uncounted; it is still a dependency with the import edge removed, not a sanctioned door.
"""

from __future__ import annotations

import os
import re
import ast
import textwrap
from collections import Counter, defaultdict
from collections.abc import Iterable, Iterator
from dataclasses import dataclass
from pathlib import Path

from .ast_helpers import ast_parse_safe, get_model_names
from .isolation import MODEL_CROSSINGS, facade_model_crossings
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


def _is_out_of_scope_module(path: Path) -> bool:
    """Tests reach concrete classes through testing doors, so they are not consumers. A migration
    reaches a model through the historical registry, which is the only way a migration can."""
    if "test" in path.parts or "tests" in path.parts or "migrations" in path.parts:
        return True
    return path.name.startswith("test_") or path.name.endswith("_test.py") or path.name == "conftest.py"


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


def _candidates() -> list[_Candidate]:
    """Every scanned .py file, with its imports read.

    Reading imports only is what keeps the full AST pass — and so the repo-invariant test — small:
    a file is parsed whole only once its imports show it can reach a crossing class."""
    found = []
    for root in SCANNED_ROOTS:
        for path in sorted((REPO_ROOT / root).rglob("*.py")):
            if SKIPPED_DIRS.intersection(path.parts):
                continue
            source = path.read_bytes()
            dotted = _dotted_module(path)
            package = dotted if path.name == "__init__.py" else dotted.rsplit(".", 1)[0]
            found.append(_Candidate(path, dotted, _read_imports(source, package), b"get_model" in source))
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
    """Export -> crossing label, for every path an import of the class can take.

    Seeded with the defining module and grown to a fixpoint over re-exports, so `facade/models.py`,
    a package `__init__`, and a renaming alias all resolve back to the same class."""
    origins: dict[_Export, str] = {_Export(c.defining_module, c.class_name): c.label for c in classes}
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
            func = current.func
            name = func.id if isinstance(func, ast.Name) else getattr(func, "attr", None)
            if name:
                return str(name)
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
# Scan
# ---------------------------------------------------------------------------


def _reads_class_off_module(source: bytes, aliases: dict[str, str], class_names: set[str]) -> bool:
    """Whether `alias.ClassName` appears in the text at all, for any module alias and crossing class.

    Most files that alias a module handing out a crossing class never read the class off it, and
    this check spares them the full parse."""
    names = b"|".join(sorted(re.escape(n).encode() for n in class_names))
    locals_ = b"|".join(sorted(re.escape(a).encode() for a in aliases))
    return re.search(rb"\b(?:" + locals_ + rb")\.(?:" + names + rb")\b", source) is not None


def scan_crossing_uses(products: Iterable[str] | None = None) -> list[CrossingUse]:
    """Every use of every crossing class in consumer code, sorted, one entry per kind per module.

    Plus every `apps.get_model` reference to any product model from outside the owning product."""
    # Consumed twice below; a generator argument would silently empty the second pass.
    products = list(products) if products is not None else None
    classes = crossing_classes(products)
    owning_dir = {c.label: PRODUCTS_DIR / c.product for c in classes}
    owning_dir |= {label: PRODUCTS_DIR / product for label, product in product_model_labels(products).items()}
    if not owning_dir:
        return []
    class_names = {c.class_name for c in classes}
    candidates = _candidates()
    origins = _origins(candidates, classes)
    origin_modules = {export.module for export in origins}
    product_by_label = _app_labels()
    # Django resolves a model name case-insensitively, so the get_model scan matches on the lowered form.
    label_by_lower = {label.lower(): label for label in owning_dir}

    counts: dict[tuple[str, str, str], int] = defaultdict(int)
    for candidate in candidates:
        if _is_out_of_scope_module(candidate.path):
            continue
        names = _bound_names(candidate, origins)
        aliases = {a.alias: a.module for a in candidate.imports.module_aliases if a.module in origin_modules}
        if not names and not aliases and not candidate.mentions_get_model:
            continue
        try:
            source = candidate.path.read_bytes()
        except OSError:
            continue
        if not names and not candidate.mentions_get_model and not _reads_class_off_module(source, aliases, class_names):
            continue
        try:
            tree = ast.parse(source)
        except (SyntaxError, ValueError):
            continue
        class_nodes = _class_nodes(tree, names, aliases, origins)
        if class_nodes:
            parents = _parent_map(tree)
            for node, label in class_nodes:
                if candidate.path.is_relative_to(owning_dir[label]):
                    continue
                counts[(label, candidate.dotted, classify_use(node, parents))] += 1
        if candidate.mentions_get_model:
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
# Two channels land here. Name-level uses of a watched-models crossing class, in any kind the
# doctrine does not call instance-free. And the kind `get_model`: an `apps.get_model` reference
# from outside the owning product, which covers every product model, not only the allowance ones.
# Test modules and migrations are out of scope on both channels: a migration reaches a model
# through the historical registry, which is the only way a migration can.
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
