"""AST-based helpers for inspecting product Python files."""

from __future__ import annotations

import ast
import warnings
import importlib.util
from collections.abc import Iterator, Sequence
from dataclasses import dataclass
from pathlib import Path


def ast_parse_safe(file_path: Path) -> ast.Module | None:
    try:
        with warnings.catch_warnings():
            warnings.simplefilter("ignore", SyntaxWarning)
            return ast.parse(file_path.read_text())
    except (SyntaxError, OSError):
        return None


def get_imported_module_names(tree: ast.Module) -> set[str]:
    """Every dotted module path the tree imports via real import statements.

    'from a.b import c' records both 'a.b' and 'a.b.c' (c may be a submodule); relative
    imports are skipped — they can't name a path outside the importing package."""
    imported: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            imported.update(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module and node.level == 0:
            imported.add(node.module)
            imported.update(f"{node.module}.{alias.name}" for alias in node.names)
    return imported


def product_app_labels(products_dir: Path) -> dict[str, str]:
    """Django app label -> product name, read off each product's AppConfig."""
    labels: dict[str, str] = {}
    for apps_py in sorted(products_dir.glob("*/backend/apps.py")):
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


# The bases a Django model reaches. `Model` is django.db.models.Model under both the bare and the
# `models.Model` spelling, because _base_names keeps the attribute and drops the module. The rest are
# the abstract bases posthog/models/utils.py and posthog/models/scoping/ export, every one of which
# subclasses models.Model itself. A base outside this list still counts once it resolves through
# another class of the product's own model modules, which is how a product's own abstract base and a
# proxy model are reached.
_DJANGO_MODEL_BASES: frozenset[str] = frozenset(
    {
        "BytecodeModelMixin",
        "CreatedMetaFields",
        "DeletedMetaFields",
        "Model",
        "ProductTeamModel",
        "RootTeamMixin",
        "TeamScopedRootMixin",
        "UpdatedMetaFields",
        "UUIDModel",
        "UUIDTClassicModel",
        "UUIDTModel",
    }
)

# Base-name suffixes whose subclasses are value/manager helpers, never registered models.
_NON_MODEL_BASE_SUFFIXES = ("Choices", "Enum", "Manager", "QuerySet")


def _base_names(node: ast.ClassDef) -> list[str]:
    names: list[str] = []
    for base in node.bases:
        if isinstance(base, ast.Name):
            names.append(base.id)
        elif isinstance(base, ast.Attribute):
            names.append(base.attr)
    return names


def _is_abstract_model(node: ast.ClassDef) -> bool:
    for item in node.body:
        if not (isinstance(item, ast.ClassDef) and item.name == "Meta"):
            continue
        for stmt in item.body:
            if (
                isinstance(stmt, ast.Assign)
                and any(isinstance(t, ast.Name) and t.id == "abstract" for t in stmt.targets)
                and isinstance(stmt.value, ast.Constant)
                and stmt.value.value is True
            ):
                return True
    return False


@dataclass(frozen=True)
class _ModelCandidate:
    """One module-level class in a model module, with what decides whether it is a model.

    An abstract class stays a candidate because it is how its subclasses reach a Django base, but
    the registry never returns it, so it never becomes a name of its own."""

    name: str
    bases: tuple[str, ...]
    is_abstract: bool


def _model_source_files(backend_dir: Path) -> list[Path]:
    """The product's model modules: backend/models.py, backend/models/, or both."""
    sources: list[Path] = []
    models_file = backend_dir / "models.py"
    models_dir = backend_dir / "models"
    if models_file.exists():
        sources.append(models_file)
    if models_dir.is_dir():
        sources.extend(sorted(models_dir.rglob("*.py")))
    return sources


def _model_candidates(backend_dir: Path) -> list[_ModelCandidate]:
    """Every module-level class in the model modules that could be a registered model.

    Nested classes (Meta, TextChoices) are never registered, and neither are the
    choices/enum/manager/queryset subclasses, so both are out here.
    """
    candidates: list[_ModelCandidate] = []
    for path in _model_source_files(backend_dir):
        tree = ast_parse_safe(path)
        if not tree:
            continue
        for node in tree.body:
            if not isinstance(node, ast.ClassDef):
                continue
            bases = _base_names(node)
            if not bases:
                continue
            if any(base.endswith(_NON_MODEL_BASE_SUFFIXES) for base in bases):
                continue
            candidates.append(_ModelCandidate(node.name, tuple(bases), _is_abstract_model(node)))
    return candidates


def get_model_names(backend_dir: Path) -> list[str]:
    """Return names of Django ORM model classes in backend/models.py and/or backend/models/.

    A class counts when one of its bases is a Django model base (_DJANGO_MODEL_BASES) or another
    class of these modules that already counts. The resolution repeats to a fixpoint, so it reaches
    a subclass of the product's own abstract base, and a proxy model, which sits in another module
    and names nothing but its concrete model as a base.

    Bases decide, and not the imports of the file, because a model module also holds classes that
    are not tables: the pydantic models a JSON field is validated against, the TypedDicts a query
    returns, and the errors the module raises. Excluded: abstract models (Meta.abstract = True) and
    choices/enum/manager/queryset subclasses, which the app registry never returns.
    """
    candidates = _model_candidates(backend_dir)
    reaches_model_base: set[str] = set()
    pending = True
    while pending:
        pending = False
        for candidate in candidates:
            if candidate.name in reaches_model_base:
                continue
            if not any(base in _DJANGO_MODEL_BASES or base in reaches_model_base for base in candidate.bases):
                continue
            reaches_model_base.add(candidate.name)
            pending = True
    return [c.name for c in candidates if c.name in reaches_model_base and not c.is_abstract]


def decorator_name(node: ast.expr) -> str | None:
    """The bare name of a decorator, with any call and any module prefix stripped."""
    target = node.func if isinstance(node, ast.Call) else node
    if isinstance(target, ast.Name):
        return target.id
    if isinstance(target, ast.Attribute):
        return target.attr
    return None


def has_any_function_defs(file_path: Path) -> bool:
    """Return True if file contains any top-level function definitions (public or private)."""
    tree = ast_parse_safe(file_path)
    if not tree:
        return False
    return tree_has_top_level_functions(tree)


def tree_has_top_level_functions(tree: ast.Module) -> bool:
    """True if the module has any top-level function definition (a re-export module has none)."""
    return any(isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)) for node in ast.iter_child_nodes(tree))


def _is_type_checking_guard(node: ast.stmt) -> bool:
    """True for an `if TYPE_CHECKING:` / `if typing.TYPE_CHECKING:` block header."""
    if not isinstance(node, ast.If):
        return False
    test = node.test
    return (isinstance(test, ast.Name) and test.id == "TYPE_CHECKING") or (
        isinstance(test, ast.Attribute) and test.attr == "TYPE_CHECKING"
    )


def module_dunder_all(tree: ast.Module) -> set[str] | None:
    """The names in a module-level `__all__` list/tuple of string literals, or None if absent.

    None (no __all__) and an empty set (explicitly empty __all__) are meaningfully different to
    callers, so they aren't collapsed. A non-literal `__all__` (e.g. `sorted(_LAZY)`) reads as
    None — its contents can't be known statically."""
    for node in ast.iter_child_nodes(tree):
        if not isinstance(node, ast.Assign):
            continue
        if not any(isinstance(t, ast.Name) and t.id == "__all__" for t in node.targets):
            continue
        if not isinstance(node.value, (ast.List, ast.Tuple)):
            return None
        return {e.value for e in node.value.elts if isinstance(e, ast.Constant) and isinstance(e.value, str)}
    return None


# What a module-level assignment may bind that can name a type. A call, a dict or a literal binds a
# value, and expanding one where an annotation names it would read data as a type.
_TYPE_ALIAS_VALUES: tuple[type[ast.expr], ...] = (ast.Name, ast.Attribute, ast.Subscript, ast.BinOp)


def _is_type_alias_annotation(node: ast.expr) -> bool:
    """True for the `TypeAlias` annotation, under both the bare and the `typing.TypeAlias` spelling."""
    return (isinstance(node, ast.Name) and node.id == "TypeAlias") or (
        isinstance(node, ast.Attribute) and node.attr == "TypeAlias"
    )


def module_type_aliases(tree: ast.Module) -> dict[str, ast.expr]:
    """Module-level type aliases: {the name a module binds -> the expression it stands for}.

    All three spellings count: a plain `Handler = Callable[[Thing], None]`, the explicit
    `Handler: TypeAlias = ...`, and the PEP 695 statement `type Handler = ...`. An annotated
    assignment with any other annotation binds an ordinary module variable
    (`_handlers: dict[str, Handler] = {}`), which is data and not a type."""
    aliases: dict[str, ast.expr] = {}
    for node in ast.iter_child_nodes(tree):
        if isinstance(node, ast.Assign) and len(node.targets) == 1 and isinstance(node.targets[0], ast.Name):
            bound = node.targets[0].id
        elif (
            isinstance(node, ast.AnnAssign)
            and isinstance(node.target, ast.Name)
            and _is_type_alias_annotation(node.annotation)
        ):
            bound = node.target.id
        elif isinstance(node, ast.TypeAlias) and isinstance(node.name, ast.Name):
            bound = node.name.id
        else:
            continue
        if isinstance(node.value, _TYPE_ALIAS_VALUES):
            aliases[bound] = node.value
    return aliases


def module_level_import_nodes(tree: ast.Module, *, type_checking: bool = False) -> list[ast.Import | ast.ImportFrom]:
    """Every module-level import statement, in source order.

    An import nested in a function or a class binds no module name, so it is skipped. An import in
    an `if TYPE_CHECKING:` block binds no runtime object either, but it still names the type a
    signature promises, so `type_checking=True` includes it."""
    nodes: list[ast.Import | ast.ImportFrom] = []
    for node in ast.iter_child_nodes(tree):
        if isinstance(node, (ast.Import, ast.ImportFrom)):
            nodes.append(node)
        elif type_checking and isinstance(node, ast.If) and _is_type_checking_guard(node):
            nodes.extend(child for child in node.body if isinstance(child, (ast.Import, ast.ImportFrom)))
    return nodes


def lazy_reexport_map(tree: ast.Module) -> dict[str, str]:
    """PEP 562 lazy re-export map: {exported name -> dotted source module}.

    Reads module-level dict literals whose values are all string module paths (the
    `_LAZY`/`_MODULES` convention), but only when the module also defines a top-level
    `__getattr__` — the hook that turns such a dict into real re-exports. Returns the
    merged mapping across all qualifying dicts."""
    has_getattr = any(
        isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)) and node.name == "__getattr__"
        for node in ast.iter_child_nodes(tree)
    )
    if not has_getattr:
        return {}
    mapping: dict[str, str] = {}
    for node in ast.iter_child_nodes(tree):
        if not isinstance(node, ast.Assign) or not isinstance(node.value, ast.Dict):
            continue
        entries: dict[str, str] = {}
        valid = bool(node.value.keys)
        for key, value in zip(node.value.keys, node.value.values):
            if (
                isinstance(key, ast.Constant)
                and isinstance(key.value, str)
                and isinstance(value, ast.Constant)
                and isinstance(value.value, str)
            ):
                entries[key.value] = value.value
            else:
                valid = False
                break
        if valid:
            mapping.update(entries)
    return mapping


def lazy_reexport_prefixes(tree: ast.Module) -> list[str]:
    """Module-level string constants a lazy map prepends to its values (`_B = "products.x.backend."`).

    A lazy map stores its source modules relative to some package, and the prefix constant is how
    the module says which. Every module-level string that ends in a dot is a candidate, so a caller
    tries each and keeps the one that names a real module."""
    return [
        node.value.value
        for node in ast.iter_child_nodes(tree)
        if isinstance(node, ast.Assign)
        and isinstance(node.value, ast.Constant)
        and isinstance(node.value.value, str)
        and node.value.value.endswith(".")
    ]


def iter_public_callables(
    tree: ast.Module, *, include_init: bool = False
) -> Iterator[tuple[str, ast.FunctionDef | ast.AsyncFunctionDef]]:
    """(owning class, node) for every public callable a module defines at its top level or in a
    class body. The owning class is "" for a plain function, so a caller can spell a method as
    `Mapper.to_contract`. Nested definitions are not part of any call surface, so they are out.

    `include_init` adds `__init__` on a public class. A constructor takes what the caller hands the
    class, so it is part of the call surface, while every other underscore name is a helper."""
    for node in ast.iter_child_nodes(tree):
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)) and not node.name.startswith("_"):
            yield "", node
        elif isinstance(node, ast.ClassDef):
            for child in ast.iter_child_nodes(node):
                if not isinstance(child, (ast.FunctionDef, ast.AsyncFunctionDef)):
                    continue
                if not child.name.startswith("_") or (include_init and child.name == "__init__"):
                    yield node.name, child


def get_public_function_names(file_path: Path) -> list[str]:
    """Return names of public top-level and class-level functions/methods (not nested)."""
    tree = ast_parse_safe(file_path)
    if not tree:
        return []
    return [node.name for _, node in iter_public_callables(tree)]


def module_has_prefix(module: str, prefixes: Sequence[str]) -> bool:
    """True when a dotted module name is one of `prefixes` or sits under one.

    Anchored on the dot, so `django.dbrouter` does not read as `django.db`."""
    return any(module == p or module.startswith(p + ".") for p in prefixes)


def import_from_module(node: ast.ImportFrom, package: str) -> str | None:
    """The absolute module an `ImportFrom` reads from, with relative forms resolved.

    None when the import climbs past the top of the package and so names nothing.
    """
    if node.level == 0:
        return node.module
    try:
        return importlib.util.resolve_name("." * node.level + (node.module or ""), package)
    except ImportError:
        return None
