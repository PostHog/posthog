"""AST-based helpers for inspecting product Python files."""

from __future__ import annotations

import ast
import warnings
from dataclasses import dataclass
from pathlib import Path


def ast_parse_safe(file_path: Path) -> ast.Module | None:
    try:
        with warnings.catch_warnings():
            warnings.simplefilter("ignore", SyntaxWarning)
            return ast.parse(file_path.read_text())
    except (SyntaxError, OSError):
        return None


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
