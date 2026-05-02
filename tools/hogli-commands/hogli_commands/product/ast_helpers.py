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
    total = 0
    for f in _collect_py_files(path):
        tree = ast_parse_safe(f)
        if not tree:
            continue
        total += sum(1 for node in ast.walk(tree) if isinstance(node, ast.Attribute) and node.attr == "objects")
    return total


def get_cross_product_internal_imports(product_dir: Path, product_name: str) -> list[str]:
    """
    Find imports from other products' internals (non-facade) within this product's own files.
    Handles both `from X import Y` and `import X` styles.
    Returns list of 'relpath: module' strings.
    """

    def _is_cross_product_violation(module: str) -> bool:
        if module.startswith(f"products.{product_name}"):
            return False
        if module.startswith("products.") and ".backend." in module:
            return "facade" not in module.split(".")
        return False

    violations: list[str] = []
    for py_file in product_dir.rglob("*.py"):
        tree = ast_parse_safe(py_file)
        if not tree:
            continue
        rel = str(py_file.relative_to(product_dir))
        for node in ast.walk(tree):
            if isinstance(node, ast.ImportFrom) and node.module and _is_cross_product_violation(node.module):
                violations.append(f"{rel}: {node.module}")
            elif isinstance(node, ast.Import):
                for alias in node.names:
                    if _is_cross_product_violation(alias.name):
                        violations.append(f"{rel}: {alias.name}")
    return violations


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
