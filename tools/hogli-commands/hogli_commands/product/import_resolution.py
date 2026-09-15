"""Where an imported name lives.

Every facade scan asks one question of an import: which module the alias comes from, whether it
names a submodule or a symbol, and which file holds it when the module is the product's own. One
answer here keeps the scans from disagreeing about the same import.
"""

from __future__ import annotations

import re
import ast
import functools
from collections.abc import Iterator, Sequence
from dataclasses import dataclass
from pathlib import Path

from .ast_helpers import module_level_import_nodes

# An absolute import into any product's backend package, with the module inside it. The tail is
# optional so that the backend package itself resolves: `from products.x.backend import tasks`
# reads that directory.
PRODUCT_BACKEND_RE = re.compile(r"^products\.([A-Za-z0-9_]+)\.backend(?:\.(.+))?$")


def product_backend_root(backend_dir: Path) -> str:
    """The product's own backend package as a dotted prefix, e.g. 'products.metrics.backend'."""
    return f"products.{backend_dir.parent.name}.backend"


def module_package_parts(source_path: str) -> list[str]:
    """The package a module belongs to, as backend-relative parts, for resolving relative imports.

    'backend/facade/queries.py' -> ['facade'] (its container); 'backend/logic/matrix/' (a package,
    trailing slash) -> ['logic', 'matrix'] (a package's relative imports are rooted at itself)."""
    trimmed = source_path.removeprefix("backend/")
    if trimmed.endswith("/"):
        return [p for p in trimmed.strip("/").split("/") if p]
    return trimmed.rsplit("/", 1)[0].split("/") if "/" in trimmed else []


def resolve_relative(package_parts: Sequence[str], level: int, module: str | None) -> str | None:
    """A relative import from a package -> its module path relative to backend, or None if it climbs
    above backend/ (nothing there is product-internal to this backend). level 1 is the package
    itself, level 2 its parent, etc."""
    climb = level - 1
    if climb > len(package_parts):
        return None
    remaining = list(package_parts[: len(package_parts) - climb])
    if module:
        remaining = remaining + module.split(".")
    return "/".join(remaining)


def resolve_absolute_module(module: str, backend_dir: Path) -> str | None:
    """An absolute import -> its module path relative to backend_dir, or None if it's not this
    product's backend (third-party, core, or another product all return None)."""
    root = product_backend_root(backend_dir)
    if module == root:
        return ""
    if module.startswith(root + "."):
        return module[len(root) + 1 :].replace(".", "/")
    return None


def backend_rel_path(module_rel: str, backend_dir: Path) -> str | None:
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


def source_file(source_path: str, backend_dir: Path) -> Path:
    """The on-disk file for a backend-relative module path (a package resolves to its __init__.py)."""
    if source_path.endswith("/"):
        return backend_dir.parent / source_path.rstrip("/") / "__init__.py"
    return backend_dir.parent / source_path


@functools.cache
def _submodule_names(directory: Path) -> frozenset[str]:
    """The submodule names a package directory holds, read once per directory.

    The listing is read rather than the path asked for, because a case-insensitive filesystem
    answers `Account.py` with `account.py` and would turn every model class into a module alias.
    One run of a scan never writes to the tree it reads, so the listing is memoized for the process.
    """
    if not directory.is_dir():
        return frozenset()
    names = set()
    for entry in directory.iterdir():
        if entry.is_dir():
            names.add(entry.name)
        elif entry.name.endswith(".py"):
            names.add(entry.name.removesuffix(".py"))
    return frozenset(names)


def _package_directory(package: str, backend_dir: Path) -> Path | None:
    """The directory a `from <package> import ...` reads, for a package that is on disk here.

    That is any product's backend, the scanned one included. A library package is not in this tree,
    so it has no directory."""
    match = PRODUCT_BACKEND_RE.match(package)
    if match is None:
        return None
    product, backend_module = match.groups()
    products_dir = backend_dir.parent.parent
    return products_dir / product / "backend" / (backend_module or "").replace(".", "/")


def _package_module(level: int, module: str | None, package_parts: Sequence[str], backend_dir: Path) -> str | None:
    """The dotted module an import reads, with a relative one resolved to its absolute spelling.

    None when a relative import climbs above the product's backend, where nothing is
    product-internal to this backend."""
    if level == 0:
        return module or ""
    module_rel = resolve_relative(package_parts, level, module)
    if module_rel is None:
        return None
    root = product_backend_root(backend_dir)
    return f"{root}.{module_rel.replace('/', '.')}" if module_rel else root


def _binds_submodule(package: str, name: str, backend_dir: Path) -> bool:
    """True when a `from <package> import <name>` binds a submodule rather than a symbol.

    A package in this tree is decided by its directory listing. A library package is not here, so
    the PEP 8 spelling decides instead: `from rest_framework import request` binds a module and
    `from rest_framework.request import Request` binds a type."""
    directory = _package_directory(package, backend_dir)
    if directory is None:
        return name[:1].islower()
    return name in _submodule_names(directory)


def _alias_source_path(package: str, name: str, binds_submodule: bool, backend_dir: Path) -> str | None:
    """The backend-relative path of what an alias names, for the scanned product's backend only.

    Another product's module and a library both resolve to None, so a scan that follows a name
    stops at the product boundary."""
    module_rel = resolve_absolute_module(package, backend_dir)
    if module_rel is None:
        return None
    if binds_submodule:
        module_rel = f"{module_rel}/{name}" if module_rel else name
    return backend_rel_path(module_rel, backend_dir)


@dataclass(frozen=True)
class ImportedName:
    """One alias of one module-level `from ... import ...`, resolved to where it lives."""

    original: str  # the name at the source
    asname: str | None  # the alias as written; `import Foo as Foo` is the explicit re-export idiom
    package: str  # the dotted module the import reads, e.g. "django.db" or "products.x.backend.logic"
    binds_submodule: bool  # the alias names a module of that package rather than a symbol
    source_path: str | None  # backend-relative path of what the alias names, this backend only

    @property
    def bound(self) -> str:
        """The name the importing module binds, which is what a consumer imports from it."""
        return self.asname or self.original

    @property
    def submodule(self) -> str:
        """The dotted module the alias names if it names a submodule, spelled whether it does or not.

        `from django.db import models` names a package that is not on disk here, so a caller that
        must decide module-ness from the dotted name alone reads this instead of binds_submodule."""
        return f"{self.package}.{self.original}"


def iter_imported_names(
    node: ast.ImportFrom, package_parts: Sequence[str], backend_dir: Path
) -> Iterator[ImportedName]:
    """Every name one `from ... import ...` binds, resolved to the module that holds it.

    A relative import that climbs above the product's backend binds nothing any scan here reads, so
    it yields nothing at all."""
    package = _package_module(node.level, node.module, package_parts, backend_dir)
    if package is None:
        return
    for alias in node.names:
        binds_submodule = _binds_submodule(package, alias.name, backend_dir)
        yield ImportedName(
            original=alias.name,
            asname=alias.asname,
            package=package,
            binds_submodule=binds_submodule,
            source_path=_alias_source_path(package, alias.name, binds_submodule, backend_dir),
        )


def iter_module_imported_names(
    tree: ast.Module, package_parts: Sequence[str], backend_dir: Path
) -> Iterator[ImportedName]:
    """Every name the module-level `from ... import ...` statements of a module bind."""
    for node in module_level_import_nodes(tree):
        if isinstance(node, ast.ImportFrom):
            yield from iter_imported_names(node, package_parts, backend_dir)
