"""Which code a change to the generated query schema can reach.

A schema PR edits frontend/src/queries/schema.json and regenerates posthog/schema.py and
posthog/schema_enums.py. Python sees the change only through those two modules, and every
test imports them, so the import graph alone selects the whole suite. This module turns the
two diffs into the files whose behavior can change: the files that name a changed type, or a
type that contains one, plus every file whose use of the modules it cannot resolve to names.

It gives up rather than guess. A top-level change other than a class or alias definition, a
removed or renamed type, a module that does not parse, or a base version it cannot read
returns a fallback reason, and the caller runs the full suite.
"""

from __future__ import annotations

import ast
import subprocess
import importlib.util
from collections.abc import Iterable
from dataclasses import dataclass, field
from pathlib import Path
from types import ModuleType

SCHEMA_MODULE_PATHS = ("posthog/schema.py", "posthog/schema_enums.py")
SCHEMA_JSON_PATH = "frontend/src/queries/schema.json"
SCHEMA_SOURCE_PATHS = (*SCHEMA_MODULE_PATHS, SCHEMA_JSON_PATH)
SCHEMA_MODULE_NAMES = ("posthog.schema", "posthog.schema_enums")
SCANNER_PATH = Path(__file__).resolve().parents[1] / ".github" / "scripts" / "schema_usage_scan.py"


@dataclass(frozen=True)
class SchemaScope:
    """``fallback_reason`` is set when the change cannot be attributed to types. Otherwise
    ``referencing_files`` is every file that can see the change."""

    fallback_reason: str | None = None
    changed_types: tuple[str, ...] = ()
    affected_types: tuple[str, ...] = ()
    referencing_files: tuple[str, ...] = ()
    wildcard_files: tuple[str, ...] = ()


@dataclass
class _ModuleShape:
    definitions: dict[str, str] = field(default_factory=dict)
    references: dict[str, set[str]] = field(default_factory=dict)
    rebuilt: set[str] = field(default_factory=set)
    reexports: set[str] = field(default_factory=set)
    other_statements: list[str] = field(default_factory=list)


class _Unattributable(Exception):
    pass


def _defined_name(node: ast.stmt) -> str | None:
    if isinstance(node, ast.ClassDef):
        return node.name
    if isinstance(node, ast.Assign) and len(node.targets) == 1 and isinstance(node.targets[0], ast.Name):
        return node.targets[0].id
    if isinstance(node, ast.AnnAssign) and isinstance(node.target, ast.Name):
        return node.target.id
    return None


def _rebuilt_name(node: ast.stmt) -> str | None:
    """``Foo.model_rebuild()``: pydantic resolves Foo's forward references again."""
    if not isinstance(node, ast.Expr) or not isinstance(node.value, ast.Call):
        return None
    func = node.value.func
    if (
        isinstance(func, ast.Attribute)
        and func.attr == "model_rebuild"
        and isinstance(func.value, ast.Name)
        and not node.value.args
        and not node.value.keywords
    ):
        return func.value.id
    return None


def _module_shape(path: str, source: str) -> _ModuleShape:
    try:
        tree = ast.parse(source, filename=path)
    except SyntaxError as error:
        raise _Unattributable(f"{path} does not parse: {error.msg}") from error
    shape = _ModuleShape()
    for node in tree.body:
        name = _defined_name(node)
        if name is not None:
            if name in shape.definitions:
                raise _Unattributable(f"{path} defines {name} twice")
            shape.definitions[name] = ast.dump(node, include_attributes=False)
            shape.references[name] = {child.id for child in ast.walk(node) if isinstance(child, ast.Name)} - {name}
            continue
        rebuilt = _rebuilt_name(node)
        if rebuilt is not None:
            shape.rebuilt.add(rebuilt)
            continue
        if isinstance(node, ast.ImportFrom) and node.module == "posthog.schema_enums":
            # schema.py re-exports every enum, so the list grows with each new one.
            shape.reexports.update(alias.asname or alias.name for alias in node.names)
            continue
        shape.other_statements.append(ast.dump(node, include_attributes=False))
    return shape


def changed_schema_types(old_sources: dict[str, str], new_sources: dict[str, str]) -> tuple[set[str], set[str]]:
    """The types whose definition differs, and every type that contains one of them.

    Raises _Unattributable for any difference that is not a change to a type definition.
    """
    old_shapes = {path: _module_shape(path, source) for path, source in old_sources.items()}
    new_shapes = {path: _module_shape(path, source) for path, source in new_sources.items()}

    changed: set[str] = set()
    old_definitions: dict[str, str] = {}
    new_definitions: dict[str, str] = {}
    references: dict[str, set[str]] = {}
    for path in SCHEMA_MODULE_PATHS:
        old, new = old_shapes[path], new_shapes[path]
        if old.other_statements != new.other_statements:
            raise _Unattributable(f"{path} changed outside its type definitions")
        if old.reexports - new.reexports:
            raise _Unattributable(f"{path} stopped re-exporting {', '.join(sorted(old.reexports - new.reexports))}")
        changed.update(old.rebuilt ^ new.rebuilt)
        for name, dump in old.definitions.items():
            if name in old_definitions:
                raise _Unattributable(f"{name} is defined in both schema modules")
            old_definitions[name] = dump
        for name, dump in new.definitions.items():
            if name in new_definitions:
                raise _Unattributable(f"{name} is defined in both schema modules")
            new_definitions[name] = dump
        for shape in (old, new):
            for name, names in shape.references.items():
                references.setdefault(name, set()).update(names)

    removed = sorted(set(old_definitions) - set(new_definitions))
    if removed:
        raise _Unattributable(f"removed or renamed types: {', '.join(removed[:10])}")
    shadowed = sorted(
        name
        for name in set(new_definitions) - set(old_definitions)
        if name in old_shapes["posthog/schema.py"].reexports
    )
    if shadowed:
        raise _Unattributable(f"new definitions shadow re-exported names: {', '.join(shadowed)}")
    changed.update(name for name, dump in old_definitions.items() if new_definitions[name] != dump)

    affected = set(changed)
    dependents: dict[str, set[str]] = {}
    for name, names in references.items():
        for referenced in names:
            dependents.setdefault(referenced, set()).add(name)
    frontier = list(affected)
    while frontier:
        for dependent in dependents.get(frontier.pop(), ()):
            if dependent not in affected:
                affected.add(dependent)
                frontier.append(dependent)
    return changed, affected


def load_scanner() -> ModuleType:
    spec = importlib.util.spec_from_file_location("schema_usage_scan", SCANNER_PATH)
    if spec is None or spec.loader is None:
        raise ImportError(f"cannot load {SCANNER_PATH}")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _names_schema_module_in_a_string(tree: ast.AST) -> bool:
    """``mock.patch("posthog.schema.Foo")`` or ``import_module("posthog.schema")`` reach the
    module without an import statement, so the visitor cannot attribute them."""
    for node in ast.walk(tree):
        if isinstance(node, ast.Constant) and isinstance(node.value, str):
            value = node.value
            if any(value == module or value.startswith(f"{module}.") for module in SCHEMA_MODULE_NAMES):
                return True
    return False


def files_referencing(
    repo_root: Path, files: Iterable[str], types: set[str], scanner: ModuleType
) -> tuple[list[str], list[str]]:
    """The files that name one of ``types`` through posthog.schema or posthog.schema_enums,
    and the files whose use of those modules cannot be resolved to type names."""
    referencing: list[str] = []
    wildcard: list[str] = []
    for path in files:
        if path in SCHEMA_MODULE_PATHS:
            continue
        try:
            source = (repo_root / path).read_text(encoding="utf-8")
        except (OSError, UnicodeDecodeError):
            wildcard.append(path)
            continue
        if "schema" not in source:
            continue
        try:
            tree = ast.parse(source, filename=path)
        except SyntaxError:
            wildcard.append(path)
            continue
        named, opaque = scanner.tree_usage(tree)
        opaque = opaque or _names_schema_module_in_a_string(tree)
        if opaque:
            wildcard.append(path)
        elif named & types:
            referencing.append(path)
    return sorted(referencing), sorted(wildcard)


def _git(repo_root: Path, *args: str) -> str | None:
    result = subprocess.run(["git", *args], cwd=repo_root, capture_output=True, text=True, check=False)
    return result.stdout if result.returncode == 0 else None


def _read(repo_root: Path, path: str) -> str | None:
    try:
        return (repo_root / path).read_text(encoding="utf-8")
    except (OSError, UnicodeDecodeError):
        return None


def schema_scope(
    repo_root: Path,
    old_sources: dict[str, str | None],
    new_sources: dict[str, str | None],
    python_files: Iterable[str],
) -> SchemaScope:
    """Attribute a schema change to the files that can see it. ``old_sources`` and
    ``new_sources`` map each of SCHEMA_MODULE_PATHS to its text, or None if unreadable."""
    old: dict[str, str] = {}
    new: dict[str, str] = {}
    for label, sources, readable in (("base", old_sources, old), ("head", new_sources, new)):
        for path in SCHEMA_MODULE_PATHS:
            source = sources.get(path)
            if source is None:
                return SchemaScope(fallback_reason=f"cannot read the {label} {path}")
            readable[path] = source
    try:
        changed, affected = changed_schema_types(old, new)
        scanner = load_scanner()
    except (_Unattributable, ImportError, OSError) as error:
        return SchemaScope(fallback_reason=str(error))
    referencing, wildcard = files_referencing(repo_root, python_files, affected, scanner)
    return SchemaScope(
        changed_types=tuple(sorted(changed)),
        affected_types=tuple(sorted(affected)),
        referencing_files=tuple(sorted(set(referencing) | set(wildcard))),
        wildcard_files=tuple(wildcard),
    )


def schema_scope_for_diff(repo_root: Path, base_ref: str, python_files: Iterable[str]) -> SchemaScope:
    """schema_scope between the merge base with ``base_ref`` and the working tree, the two
    ends of the diff the backend test selector reads."""
    merge_base = (_git(repo_root, "merge-base", base_ref, "HEAD") or "").strip()
    if not merge_base:
        return SchemaScope(fallback_reason=f"no merge base with {base_ref}")
    old_sources = {path: _git(repo_root, "show", f"{merge_base}:{path}") for path in SCHEMA_MODULE_PATHS}
    new_sources = {path: _read(repo_root, path) for path in SCHEMA_MODULE_PATHS}
    return schema_scope(repo_root, old_sources, new_sources, python_files)
