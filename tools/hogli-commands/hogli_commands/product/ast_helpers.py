"""AST-based helpers for inspecting product Python files."""

from __future__ import annotations

import re
import ast
import warnings
from collections.abc import Sequence
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


def get_model_names(backend_dir: Path) -> list[str]:
    """Return names of Django ORM model subclasses in backend/models.py and/or backend/models/.

    Only counts classes whose base name ends with 'Model' (e.g. Model, UUIDTModel)
    and only in files that import from django.db, to avoid false positives from
    Pydantic BaseModel or similar.
    """
    sources: list[Path] = []
    models_file = backend_dir / "models.py"
    models_dir = backend_dir / "models"
    if models_file.exists():
        sources.append(models_file)
    if models_dir.is_dir():
        sources.extend(models_dir.rglob("*.py"))

    names: list[str] = []
    for path in sources:
        tree = ast_parse_safe(path)
        if not tree:
            continue
        if not _file_imports_django_models(tree):
            continue
        for node in ast.walk(tree):
            if isinstance(node, ast.ClassDef):
                for base in node.bases:
                    base_name = (
                        base.id
                        if isinstance(base, ast.Name)
                        else base.attr
                        if isinstance(base, ast.Attribute)
                        else None
                    )
                    if base_name and base_name.endswith("Model"):
                        names.append(node.name)
                        break
    return names


def get_frozen_dataclass_names(file_path: Path) -> list[str]:
    """Return names of @dataclass(frozen=True) classes in a file."""
    tree = ast_parse_safe(file_path)
    if not tree:
        return []
    names: list[str] = []
    for node in ast.walk(tree):
        if not isinstance(node, ast.ClassDef):
            continue
        for dec in node.decorator_list:
            if not isinstance(dec, ast.Call):
                continue
            func = dec.func
            is_dc = (isinstance(func, ast.Name) and func.id == "dataclass") or (
                isinstance(func, ast.Attribute) and func.attr == "dataclass"
            )
            if is_dc and any(
                kw.arg == "frozen" and isinstance(kw.value, ast.Constant) and kw.value.value is True
                for kw in dec.keywords
            ):
                names.append(node.name)
    return names


def has_any_function_defs(file_path: Path) -> bool:
    """Return True if file contains any top-level function definitions (public or private)."""
    tree = ast_parse_safe(file_path)
    if not tree:
        return False
    return any(isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)) for node in ast.iter_child_nodes(tree))


def get_public_function_names(file_path: Path) -> list[str]:
    """Return names of public top-level and class-level functions/methods (not nested)."""
    tree = ast_parse_safe(file_path)
    if not tree:
        return []
    names: list[str] = []
    for node in ast.iter_child_nodes(tree):
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)) and not node.name.startswith("_"):
            names.append(node.name)
        elif isinstance(node, ast.ClassDef):
            for child in ast.iter_child_nodes(node):
                if isinstance(child, (ast.FunctionDef, ast.AsyncFunctionDef)) and not child.name.startswith("_"):
                    names.append(child.name)
    return names


def _module_assignment(tree: ast.Module, name: str) -> ast.expr | None:
    """Return the value assigned to a module-level `name`, or None."""
    for node in ast.iter_child_nodes(tree):
        if isinstance(node, ast.Assign) and any(isinstance(t, ast.Name) and t.id == name for t in node.targets):
            return node.value
    return None


def _str_dict(node: ast.expr | None) -> dict[str, str]:
    """Read a dict literal of string keys to string values, or {} for anything else."""
    if not isinstance(node, ast.Dict):
        return {}
    return {
        k.value: v.value
        for k, v in zip(node.keys, node.values)
        if isinstance(k, ast.Constant) and isinstance(k.value, str) and isinstance(v, ast.Constant)
        if isinstance(v.value, str)
    }


def _facade_exports(tree: ast.Module) -> tuple[list[str], dict[str, str]]:
    """Read a facade's `__all__` into (exported names, lazily-mapped name -> source module).

    Two shapes are in use. An eager facade assigns a list literal and imports each name at the
    top, so the source map comes from its ImportFrom nodes and this returns none. A lazy facade
    (PEP 562) assigns `__all__ = sorted(_LAZY)` and resolves names in `__getattr__`, which keeps
    heavy logic modules off the django.setup() path and breaks import cycles — there the `_LAZY`
    dict is the import map, so it answers what ImportFrom answers for the eager shape.
    """
    value = _module_assignment(tree, "__all__")
    if isinstance(value, ast.List):
        names = [e.value for e in value.elts if isinstance(e, ast.Constant) and isinstance(e.value, str)]
        return names, {}
    # __all__ = sorted(_LAZY) / list(_LAZY)
    if (
        isinstance(value, ast.Call)
        and isinstance(value.func, ast.Name)
        and value.func.id in {"sorted", "list"}
        and len(value.args) == 1
        and isinstance(value.args[0], ast.Name)
    ):
        lazy = _str_dict(_module_assignment(tree, value.args[0].id))
        return sorted(lazy), lazy
    return [], {}


def _is_product_owned(source: str) -> bool:
    """True if an import source names one of this product's own modules.

    Only relative imports and `products.*` paths can. Third-party modules are excluded by
    this, which matters because a bare "models" segment test would also match
    `django.db.models` and flag every re-exported `Q` or `Prefetch`.
    """
    return source.startswith(".") or source.startswith("products.")


def _class_kind(node: ast.ClassDef) -> str:
    """ "class" if the class carries behavior callers can reach, else "type".

    The concern is a caller driving methods the product never treated as its API. A class with
    public methods hands them over, and so does one inheriting a base that has them. An error
    marker or a plain data/result class carries none — its shape belongs in facade/contracts.py,
    but it is not a behavioral surface.
    """
    if any(isinstance(m, (ast.FunctionDef, ast.AsyncFunctionDef)) and not m.name.startswith("_") for m in node.body):
        return "class"
    # An exception hierarchy stays inert however deep it goes, so match the name rather than
    # only the builtin roots — a subclass of a product's own FooError is still a marker.
    bases = [ast.unparse(b) for b in node.bases]
    if bases and not all(b.endswith(("Error", "Exception")) for b in bases):
        return "class"
    return "type"


def _top_level_kind(tree: ast.Module, name: str) -> str | None:
    """Classify a module-level definition of `name`, or None if the module doesn't define it.

    Module-level only: a nested walk would match a method (a viewset action named `certify`
    shadowing the logic function of the same name) and resolve the re-export to the view.
    """
    for node in ast.iter_child_nodes(tree):
        if isinstance(node, ast.ClassDef) and node.name == name:
            return _class_kind(node)
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)) and node.name == name:
            return "function"
    return None


def _definitions(
    backend_dir: Path, wanted: Sequence[tuple[str, Path | None]]
) -> dict[tuple[str, Path | None], tuple[str, str]]:
    """Locate each (name, source module) pair, as the pair -> (kind, product-relative path).

    Keyed by the pair rather than the name because one name can have several definitions:
    data_modeling defines a distinct `NodeType` in both models/node.py and models/modeling.py
    and deliberately exposes one from each facade module. Keying by name would drop all but one
    and read coverage off a file the other export never came from.

    The source module is consulted first for the same reason — a bare name search across the
    backend is ambiguous. The fallback scan exists for re-export chains, where the immediate
    source (facade/models.py re-exporting an ORM class) defines nothing itself. A name found by
    neither is a module-level assignment, which this can't see; the caller reads it as a
    constant.
    """
    found: dict[tuple[str, Path | None], tuple[str, str]] = {}
    unresolved: list[tuple[str, Path | None]] = []
    for key in wanted:
        name, source = key
        tree = ast_parse_safe(source) if source else None
        kind = _top_level_kind(tree, name) if tree else None
        if kind and source and "facade" not in source.parts:
            found[key] = (kind, str(source.relative_to(backend_dir.parent)))
        else:
            unresolved.append(key)

    remaining = {name for name, _source in unresolved}
    fallback: dict[str, tuple[str, str]] = {}
    for py in sorted(backend_dir.rglob("*.py")):
        if not remaining:
            break
        if "facade" in py.parts or "__pycache__" in py.parts:
            continue
        tree = ast_parse_safe(py)
        if not tree:
            continue
        for name in sorted(remaining):
            kind = _top_level_kind(tree, name)
            if kind:
                fallback[name] = (kind, str(py.relative_to(backend_dir.parent)))
                remaining.discard(name)

    for key in unresolved:
        if key[0] in fallback:
            found[key] = fallback[key[0]]
    return found


def _resolve_module(dotted: str, anchor: Path) -> Path | None:
    """Turn a dotted module path into a file, relative to the package directory `anchor`."""
    target = anchor.joinpath(*dotted.split("."))
    for candidate in (target.with_suffix(".py"), target / "__init__.py"):
        if candidate.exists():
            return candidate
    return None


def _import_source(node: ast.ImportFrom, module: Path, backend_dir: Path) -> tuple[str, Path | None]:
    """The dotted source of an import, plus the file it resolves to.

    Relative imports climb from the facade module's own package; an absolute
    `products.<name>.backend.x.y` is anchored at the product's backend instead.
    """
    dotted = ("." * node.level) + (node.module or "")
    if node.level:
        anchor = module.parent
        for _ in range(node.level - 1):
            anchor = anchor.parent
        return dotted, _resolve_module(node.module or "", anchor)
    if node.module and node.module.startswith("products."):
        parts = node.module.split(".")
        if "backend" in parts:
            return dotted, _resolve_module(".".join(parts[parts.index("backend") + 1 :]), backend_dir)
    return dotted, None


def _module_reexports(module: Path, backend_dir: Path) -> dict[str, tuple[str, Path | None]]:
    """A facade module's advertised-but-not-defined names.

    Maps the advertised name to (name to look for, module it came from). The two names differ
    under an alias (`from ..logic.runner import Runner as PublicRunner`): the class to find is
    `Runner`, so carrying only the public name would search for a definition that doesn't exist
    and silently read the class as an unlocatable constant.
    """
    tree = ast_parse_safe(module)
    if not tree:
        return {}

    exported, lazy_sources = _facade_exports(tree)
    if not exported:
        return {}

    local = {
        node.name
        for node in ast.iter_child_nodes(tree)
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef))
    }
    # advertised name -> (original name, dotted source, resolved file)
    sources: dict[str, tuple[str, str, Path | None]] = {}
    for node in ast.walk(tree):
        if not isinstance(node, ast.ImportFrom):
            continue
        dotted, path = _import_source(node, module, backend_dir)
        for alias in node.names:
            sources[alias.asname or alias.name] = (alias.name, dotted, path)
    # A lazy facade resolves each name against its own backend package, so those entries are
    # owned by construction — mark them relative so they read like an eager relative import.
    for name, dotted in lazy_sources.items():
        sources[name] = (name, "." + dotted, _resolve_module(dotted, backend_dir))

    names: dict[str, tuple[str, Path | None]] = {}
    for name in exported:
        if name in local:
            continue
        entry = sources.get(name)
        if entry is None:
            continue
        original, source, path = entry
        if not _is_product_owned(source):
            continue
        if "contracts" in source or "enums" in source:
            continue
        names[name] = (original, path)
    return names


def get_facade_reexports(backend_dir: Path) -> list[tuple[str, str, str]]:
    """Names the facade advertises but defines outside facade/, as (name, kind, path).

    kind is "class" (carries behavior), "type" (an error marker or plain data class),
    "function", or "constant". path is where the name is actually defined, product-relative,
    and empty when the walk can't see it (a module-level assignment).

    A re-exported name's implementation sits outside facade/, so unless the product's
    contract-check inputs also watch the defining module, it can change while the watched
    inputs stay byte-identical and turbo-discover skips the Django suite on a change core can
    observe. Callers pair this with the input globs to decide — see
    IsolationStatus.leaked_facade_names.

    Every facade module is scanned, not just api.py: a product's public surface is the whole
    `backend/facade/` package (tach exposes `backend.facade.*`, and capability submodules like
    queries.py or temporal.py are what core registers and dispatches on). Reading api.py alone
    would miss most of it, and moving a name into a sibling module would evade the check.

    Keyed on `__all__`, the advertised surface. A facade module with no `__all__` reads as clean
    even though Python would still let a caller import its internals — the alternative (treating
    every public module-level binding as exported) flags the helpers a real facade imports in
    order to call them, so it would demote the correct products too.
    """
    facade_dir = backend_dir / "facade"
    if not facade_dir.is_dir():
        return []

    # (advertised name, name to look for, module it came from) — a list, because two facade
    # modules can advertise the same name from different modules (data_modeling's NodeType),
    # and keying by name would check only one of them.
    candidates: list[tuple[str, str, Path | None]] = []
    for module in sorted(facade_dir.glob("*.py")):
        if module.stem in {"contracts", "enums"}:
            continue
        for advertised, (original, source) in _module_reexports(module, backend_dir).items():
            candidates.append((advertised, original, source))

    definitions = _definitions(backend_dir, [(original, source) for _a, original, source in candidates])
    return sorted(
        {
            (advertised, *definitions.get((original, source), ("constant", "")))
            for advertised, original, source in candidates
        }
    )


def imports_any(file_path: Path, prefixes: list[str]) -> bool:
    """Return True if file imports from any of the given module prefixes."""
    tree = ast_parse_safe(file_path)
    if not tree:
        return False
    for node in ast.walk(tree):
        if isinstance(node, ast.ImportFrom) and node.module:
            if any(node.module == p or node.module.startswith(p + ".") for p in prefixes):
                return True
        elif isinstance(node, ast.Import):
            if any(alias.name == p or alias.name.startswith(p + ".") for alias in node.names for p in prefixes):
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


def _collect_py_files(path: Path) -> list[Path]:
    """Return list of .py files — the file itself if a file, or all *.py in dir (non-recursive)."""
    if path.is_file():
        return [path]
    if path.is_dir():
        return [f for f in path.glob("*.py") if f.name != "__init__.py"]
    return []
