"""AST-based helpers for inspecting product Python files."""

from __future__ import annotations

import re
import ast
import warnings
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


def _get_dunder_all(tree: ast.Module) -> list[str]:
    """Return the string entries of a module-level `__all__`, or [] if it has none."""
    for node in ast.iter_child_nodes(tree):
        if not isinstance(node, ast.Assign) or not isinstance(node.value, ast.List):
            continue
        if any(isinstance(t, ast.Name) and t.id == "__all__" for t in node.targets):
            return [e.value for e in node.value.elts if isinstance(e, ast.Constant) and isinstance(e.value, str)]
    return []


def _is_product_owned(source: str) -> bool:
    """True if an import source names one of this product's own modules.

    Only relative imports and `products.*` paths can. Third-party modules are excluded by
    this, which matters because a bare "models" segment test would also match
    `django.db.models` and flag every re-exported `Q` or `Prefetch`.
    """
    return source.startswith(".") or source.startswith("products.")


def _definition_kinds(backend_dir: Path, wanted: set[str]) -> dict[str, str]:
    """Classify each wanted name by how it is defined outside facade/ — class or function.

    One pass over the tree, dropping names as they're found. A name that is never found is a
    module-level assignment, which this walk cannot see — the caller reads it as a constant.
    """
    kinds: dict[str, str] = {}
    remaining = set(wanted)
    for py in sorted(backend_dir.rglob("*.py")):
        if not remaining:
            break
        if "facade" in py.parts or "__pycache__" in py.parts:
            continue
        tree = ast_parse_safe(py)
        if not tree:
            continue
        for node in ast.walk(tree):
            if not isinstance(node, (ast.ClassDef, ast.FunctionDef, ast.AsyncFunctionDef)):
                continue
            if node.name in remaining:
                kinds[node.name] = "class" if isinstance(node, ast.ClassDef) else "function"
                remaining.discard(node.name)
    return kinds


def get_facade_reexports(backend_dir: Path) -> list[tuple[str, str]]:
    """Names advertised in facade/api.py's `__all__` whose implementation lives outside facade/.

    Returns (name, kind) pairs sorted by name, kind being "class", "function" or "constant".

    A re-exported name puts behavior outside the contract-check inputs (facade/**,
    presentation/**): the object is defined under logic/ or models/, so its behavior can
    change while facade/** stays byte-identical and turbo-discover skips the Django suite on
    a change core can still observe. contracts/enums re-exports are fine — those files are
    contract-check inputs themselves.

    Classes are the worst case. A function export is one entry point with one signature, so
    "keep behavior tests in-product" is checkable; a class hands callers every method,
    including ones no in-product test pins.

    Keyed on `__all__`, which is the product's *advertised* surface. A facade with no `__all__`
    reads as clean here even though Python would still let a caller import its internals — the
    alternative (treating every public module-level binding as exported) flags the helpers a
    real facade imports in order to call them, so it demotes the correct products too.
    """
    facade_api = backend_dir / "facade" / "api.py"
    tree = ast_parse_safe(facade_api)
    if not tree:
        return []

    exported = _get_dunder_all(tree)
    if not exported:
        return []

    local = {
        node.name
        for node in ast.iter_child_nodes(tree)
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef))
    }
    sources = {
        alias.asname or alias.name: ("." * node.level) + (node.module or "")
        for node in ast.walk(tree)
        if isinstance(node, ast.ImportFrom)
        for alias in node.names
    }

    candidates = set()
    for name in exported:
        if name in local:
            continue
        source = sources.get(name)
        if source is None or not _is_product_owned(source):
            continue
        if "contracts" in source or "enums" in source:
            continue
        candidates.add(name)

    kinds = _definition_kinds(backend_dir, candidates)
    return sorted((name, kinds.get(name, "constant")) for name in candidates)


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
