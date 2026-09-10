"""AST-based helpers for inspecting product Python files."""

from __future__ import annotations

import re
import ast
import warnings
from collections.abc import Iterator, Sequence
from dataclasses import dataclass
from pathlib import Path

# Common suffixes/prefixes that contract dataclasses may use instead of mirroring the model name exactly.
_CONTRACT_STRIP_RE = re.compile(r"(Contract|Data|DTO|Out|In|Response|Request)$")


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


def _file_imports_django_models(tree: ast.Module) -> bool:
    """Check whether a file imports from django.db.models (or django.db)."""
    for node in ast.walk(tree):
        if isinstance(node, ast.ImportFrom) and node.module:
            if node.module.startswith("django.db"):
                return True
        elif isinstance(node, ast.Import):
            if any(alias.name.startswith("django.db") for alias in node.names):
                return True
    return False


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
    """One module-level class in a model module, with what decides whether it is a model."""

    name: str
    bases: tuple[str, ...]
    django_in_file: bool


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
    choices/enum/manager/queryset subclasses or an abstract model, so all of those are out here.
    """
    candidates: list[_ModelCandidate] = []
    for path in _model_source_files(backend_dir):
        tree = ast_parse_safe(path)
        if not tree:
            continue
        django_in_file = _file_imports_django_models(tree)
        for node in tree.body:
            if not isinstance(node, ast.ClassDef):
                continue
            bases = _base_names(node)
            if not bases:
                continue
            if any(base.endswith(_NON_MODEL_BASE_SUFFIXES) for base in bases):
                continue
            if _is_abstract_model(node):
                continue
            candidates.append(_ModelCandidate(node.name, tuple(bases), django_in_file))
    return candidates


def get_model_names(backend_dir: Path) -> list[str]:
    """Return names of Django ORM model classes in backend/models.py and/or backend/models/.

    A class counts when its file imports from django.db, or when one of its bases is already a
    model of this product. A proxy model subclasses its concrete model and needs no import of its
    own, and dropping such a class lets a crossing bypass the ratchet. The base rule reaches
    across model modules, so the resolution repeats until no further class turns into a model.

    Base-name matching cannot see that TeamScopedRootMixin or a meta-fields mixin ultimately
    reaches models.Model, so the django.db rule fails open: overcounting a helper class is
    harmless (apps.get_model can never resolve it). Excluded: abstract models (Meta.abstract =
    True) and choices/enum/manager/queryset subclasses, which the app registry never returns.
    """
    candidates = _model_candidates(backend_dir)
    names: list[str] = []
    known: set[str] = set()
    pending = True
    while pending:
        pending = False
        for candidate in candidates:
            if candidate.name in known:
                continue
            if not (candidate.django_in_file or any(base in known for base in candidate.bases)):
                continue
            known.add(candidate.name)
            names.append(candidate.name)
            pending = True
    return names


def decorator_name(node: ast.expr) -> str | None:
    """The bare name of a decorator, with any call and any module prefix stripped."""
    target = node.func if isinstance(node, ast.Call) else node
    if isinstance(target, ast.Name):
        return target.id
    if isinstance(target, ast.Attribute):
        return target.attr
    return None


def _keyword_is(node: ast.expr, name: str, value: bool) -> bool:
    if not isinstance(node, ast.Call):
        return False
    return any(
        kw.arg == name and isinstance(kw.value, ast.Constant) and kw.value.value is value for kw in node.keywords
    )


def _is_frozen_dataclass_decorator(node: ast.expr) -> bool:
    """True for @dataclass(frozen=True) and for the house decorator, which is frozen by default."""
    name = decorator_name(node)
    if name == "dataclass":
        return _keyword_is(node, "frozen", True)
    if name == "frozen":
        return not _keyword_is(node, "frozen", False)
    return False


def get_frozen_dataclass_names(file_path: Path) -> list[str]:
    """Return names of frozen dataclasses in a file."""
    tree = ast_parse_safe(file_path)
    if not tree:
        return []
    names: list[str] = []
    for node in ast.walk(tree):
        if not isinstance(node, ast.ClassDef):
            continue
        if any(_is_frozen_dataclass_decorator(dec) for dec in node.decorator_list):
            names.append(node.name)
    return names


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


def module_level_import_froms(tree: ast.Module) -> list[tuple[int, str | None, list[tuple[str, str | None]]]]:
    """Every module-level `from ... import ...` as (level, module, [(name, asname)]).

    asname is None when no alias is given; `import Foo as Foo` yields ("Foo", "Foo") so callers
    can tell the explicit self-alias re-export idiom apart from a plain import. Type-only imports
    are out: nothing crosses at runtime."""
    return [
        (node.level, node.module, [(alias.name, alias.asname) for alias in node.names])
        for node in module_level_import_nodes(tree)
        if isinstance(node, ast.ImportFrom)
    ]


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


def iter_public_callables(tree: ast.Module) -> Iterator[tuple[str, ast.FunctionDef | ast.AsyncFunctionDef]]:
    """(owning class, node) for every public callable a module defines at its top level or in a
    class body. The owning class is "" for a plain function, so a caller can spell a method as
    `Mapper.to_contract`. Nested definitions are not part of any call surface, so they are out."""
    for node in ast.iter_child_nodes(tree):
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)) and not node.name.startswith("_"):
            yield "", node
        elif isinstance(node, ast.ClassDef):
            for child in ast.iter_child_nodes(node):
                if isinstance(child, (ast.FunctionDef, ast.AsyncFunctionDef)) and not child.name.startswith("_"):
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


def imports_any(file_path: Path, prefixes: list[str]) -> bool:
    """Return True if file imports from any of the given module prefixes."""
    tree = ast_parse_safe(file_path)
    if not tree:
        return False
    for node in ast.walk(tree):
        if isinstance(node, ast.ImportFrom) and node.module:
            if module_has_prefix(node.module, prefixes):
                return True
        elif isinstance(node, ast.Import):
            if any(module_has_prefix(alias.name, prefixes) for alias in node.names):
                return True
    return False


def contract_coverage(model_names: list[str], dc_names: list[str]) -> tuple[list[str], list[str]]:
    """Returns (covered, uncovered) model names.

    Matches model names to frozen dataclass names using fuzzy matching:
    exact match first, then strips common suffixes (Contract, Data, DTO, Out, etc.)
    from the dataclass name and checks if it matches a model name.
    """
    dc_set = set(dc_names)
    # Build a mapping of stripped-dc-name -> original dc name for fuzzy matching
    stripped: dict[str, str] = {}
    for dc in dc_names:
        key = _CONTRACT_STRIP_RE.sub("", dc)
        if key != dc:
            stripped[key] = dc

    covered: list[str] = []
    uncovered: list[str] = []
    for m in model_names:
        if m in dc_set or m in stripped:
            covered.append(m)
        else:
            uncovered.append(m)
    return covered, uncovered


def get_orm_bound_serializer_names(file_path: Path) -> list[str]:
    """
    Return names of serializer classes that still have a Meta.model binding.
    These need to be reworked to accept/return contracts instead.
    """
    tree = ast_parse_safe(file_path)
    if not tree:
        return []
    names: list[str] = []
    for node in ast.walk(tree):
        if not isinstance(node, ast.ClassDef):
            continue
        is_serializer = any(
            (isinstance(b, ast.Name) and "Serializer" in b.id)
            or (isinstance(b, ast.Attribute) and "Serializer" in b.attr)
            for b in node.bases
        )
        if not is_serializer:
            continue
        for child in node.body:
            if isinstance(child, ast.ClassDef) and child.name == "Meta":
                for stmt in child.body:
                    if isinstance(stmt, ast.Assign) and any(
                        isinstance(t, ast.Name) and t.id == "model" for t in stmt.targets
                    ):
                        names.append(node.name)
    return names


def count_direct_orm_queries(path: Path) -> int:
    """Count .objects attribute accesses (approximate — may include non-ORM uses).

    Accepts a single file or a directory (package of ViewSet files).
    """
    return len(find_direct_orm_queries(path))


def find_direct_orm_queries(path: Path) -> list[str]:
    """Return file:line strings for every .objects attribute access under path.

    Same approximation caveats as count_direct_orm_queries — may include non-ORM uses.
    """
    locations: list[str] = []
    files = _collect_py_files(path)
    base = path if path.is_dir() else path.parent
    for f in files:
        tree = ast_parse_safe(f)
        if not tree:
            continue
        for node in ast.walk(tree):
            if isinstance(node, ast.Attribute) and node.attr == "objects":
                try:
                    rel = f.relative_to(base)
                except ValueError:
                    rel = f
                locations.append(f"{rel}:{node.lineno}")
    return locations


def view_facade_usage(views_path: Path) -> tuple[bool, bool]:
    """
    Returns (imports_facade, imports_models_directly).
    Handles both relative (from ..facade import ...) and absolute imports.
    Accepts a single file or a directory (package of ViewSet files).
    """
    files = _collect_py_files(views_path)
    imports_facade = False
    imports_models = False
    for f in files:
        tree = ast_parse_safe(f)
        if not tree:
            continue
        for node in ast.walk(tree):
            if not isinstance(node, ast.ImportFrom):
                continue
            parts = (node.module or "").split(".")
            if "facade" in parts:
                imports_facade = True
            if "models" in parts or node.module == "models":
                imports_models = True
    return imports_facade, imports_models


def count_viewset_files(directory: Path) -> int:
    """Count Python files in a directory that define ViewSet classes."""
    count = 0
    for f in _collect_py_files(directory):
        tree = ast_parse_safe(f)
        if not tree:
            continue
        for node in ast.walk(tree):
            if isinstance(node, ast.ClassDef) and any(
                ("ViewSet" in (b.id if isinstance(b, ast.Name) else b.attr if isinstance(b, ast.Attribute) else ""))
                for b in node.bases
            ):
                count += 1
                break
    return count


def module_import_targets(file_path: Path, package_root: Path, package_prefix: str) -> list[tuple[int, str]]:
    """(line, dotted module) for every absolute import in the file that names a module under
    `package_prefix` (e.g. "products.foo.backend"), resolved against `package_root` (the
    directory that prefix maps to) so `from a.b import c` yields `a.b.c` when c is a
    module or package and `a.b` when c is a name.

    Pure AST: unlike grimp it does not need __init__.py markers to see a module, which is
    what lets a lint hold an import-linter contract in directories grimp cannot descend into.
    """
    tree = ast_parse_safe(file_path)
    if not tree:
        return []
    prefix_dot = package_prefix + "."

    def is_module(dotted: str) -> bool:
        rel = Path(*dotted[len(prefix_dot) :].split("."))
        return (package_root / rel).is_dir() or (package_root / rel).with_suffix(".py").exists()

    targets: list[tuple[int, str]] = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            targets.extend((node.lineno, a.name) for a in node.names if a.name.startswith(prefix_dot))
        elif isinstance(node, ast.ImportFrom) and node.level == 0 and node.module:
            if node.module != package_prefix and not node.module.startswith(prefix_dot):
                continue
            for alias in node.names:
                candidate = f"{node.module}.{alias.name}"
                targets.append((node.lineno, candidate if is_module(candidate) else node.module))
    return [(line, dotted) for line, dotted in targets if dotted.startswith(prefix_dot)]


def _collect_py_files(path: Path) -> list[Path]:
    """Return list of .py files — the file itself if a file, or all *.py in dir (non-recursive)."""
    if path.is_file():
        return [path]
    if path.is_dir():
        return [f for f in path.glob("*.py") if f.name != "__init__.py"]
    return []
