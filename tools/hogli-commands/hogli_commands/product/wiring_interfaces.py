"""Whether a class implements an approved wiring interface, read from source.

products/architecture.md § Wiring couplings lets a behavior class cross a product boundary only when
it implements an approved core interface and lives in a wiring location. The location is a path
check. The interface is a property of the class, so this module follows the class through the
repository: a product query runner reaches QueryRunner through core's AnalyticsQueryRunner. It
parses source and never imports a module, because a lint run must not boot Django.
"""

from __future__ import annotations

import ast
import builtins
import functools
from collections.abc import Mapping
from enum import StrEnum
from pathlib import Path

from posthog.dataclasses import frozen

from .ast_helpers import ast_parse_safe, module_level_import_nodes

# Rule 1 of § Wiring couplings, by the qualified name a class reaches. A base counts through any
# depth of repository classes. A decorator counts only on the class itself.
APPROVED_WIRING_BASES: frozenset[str] = frozenset(
    {
        "ee.hogai.tool.MaxTool",
        "posthog.hogql_queries.query_runner.QueryRunner",
        "temporalio.worker.Interceptor",
    }
)
APPROVED_WIRING_DECORATORS: frozenset[str] = frozenset(
    {
        "celery.shared_task",
        "temporalio.activity.defn",
        "temporalio.workflow.defn",
    }
)

# Top-level packages whose modules sit in this repository. A name from any other package is a
# library, so it resolves without a file and never approves.
_REPOSITORY_PACKAGES: frozenset[str] = frozenset({"common", "ee", "posthog", "products"})


class WiringVerdict(StrEnum):
    APPROVED = "approved"
    UNAPPROVED = "unapproved"
    # A base or a re-export that the source does not name statically, such as a star import. The
    # lint cannot confirm an approved interface, so it reports the class like an unapproved one.
    UNRESOLVED = "unresolved"


@frozen
class _ModuleScope:
    """What one module binds at its top level."""

    module: str
    tree: ast.Module
    bindings: Mapping[str, str]  # each imported name and the qualified name it refers to
    classes: Mapping[str, ast.ClassDef]
    rebound: frozenset[str]  # names a top-level statement other than an import binds
    mutated: frozenset[str]  # names a top-level statement changes in place


@frozen
class _ClassSite:
    scope: _ModuleScope
    node: ast.ClassDef


def _rebound_names(tree: ast.Module) -> frozenset[str]:
    names: set[str] = set()
    for statement in tree.body:
        if isinstance(statement, (ast.ClassDef, ast.FunctionDef, ast.AsyncFunctionDef)):
            names.add(statement.name)
        elif isinstance(statement, ast.Assign):
            names.update(target.id for target in statement.targets if isinstance(target, ast.Name))
        elif isinstance(statement, (ast.AnnAssign, ast.AugAssign)) and isinstance(statement.target, ast.Name):
            names.add(statement.target.id)
    return frozenset(names)


# Methods that add to a list, set or dict in place.
_MUTATING_METHODS: frozenset[str] = frozenset({"append", "extend", "insert", "add", "update"})


def _mutated_names(tree: ast.Module) -> frozenset[str]:
    """Names a top-level statement changes in place, such as `FLOWS.append(Plain)` or `FLOWS += [Plain]`."""
    names: set[str] = set()
    for statement in tree.body:
        if (
            isinstance(statement, ast.Expr)
            and isinstance(statement.value, ast.Call)
            and isinstance(statement.value.func, ast.Attribute)
            and isinstance(statement.value.func.value, ast.Name)
            and statement.value.func.attr in _MUTATING_METHODS
        ):
            names.add(statement.value.func.value.id)
        elif isinstance(statement, ast.AugAssign) and isinstance(statement.target, ast.Name):
            names.add(statement.target.id)
        elif isinstance(statement, ast.Assign):
            names.update(
                target.value.id
                for target in statement.targets
                if isinstance(target, ast.Subscript) and isinstance(target.value, ast.Name)
            )
    return frozenset(names)


def _assigned_value(tree: ast.Module, name: str) -> ast.expr | None:
    """The expression the last top-level assignment binds to the name, which is the one Python keeps."""
    for statement in reversed(tree.body):
        if isinstance(statement, ast.Assign) and any(
            isinstance(target, ast.Name) and target.id == name for target in statement.targets
        ):
            return statement.value
        if isinstance(statement, ast.AnnAssign) and isinstance(statement.target, ast.Name):
            if statement.target.id == name and statement.value is not None:
                return statement.value
    return None


@functools.cache
def _parsed(path: Path) -> ast.Module | None:
    """One parse per file for the whole run, because many products reach the same core modules."""
    return ast_parse_safe(path)


class WiringInterfaceResolver:
    """Decides the wiring verdict of a class by its module and name.

    `roots` maps a dotted package prefix to the directory that holds it, so a product under test
    resolves from a temporary directory. Every other repository module resolves from `repo_root`.
    """

    def __init__(self, repo_root: Path, roots: Mapping[str, Path] | None = None) -> None:
        self._repo_root = repo_root
        self._roots = dict(roots or {})
        self._ancestor_verdicts: dict[str, WiringVerdict] = {}

    def is_class(self, qualified: str) -> bool:
        """Whether the name reaches a class definition through any chain of re-exports here."""
        return isinstance(self._locate(qualified, frozenset()), _ClassSite)

    def collection_members(self, qualified: str) -> list[str] | None:
        """The qualified names that a top-level list, tuple or set literal holds, such as WORKFLOWS.

        None when a later top-level statement changes the collection, such as `WORKFLOWS.append(Plain)`.
        The lint then cannot see which classes it holds."""
        return self._members(qualified, frozenset())

    def verdict(self, qualified: str) -> WiringVerdict:
        site = self._locate(qualified, frozenset())
        if isinstance(site, WiringVerdict):
            return site
        # Temporal registers a class by its own decorator only, so a decorator counts on the class
        # the facade hands out and never on one of its bases.
        if any(
            self._qualify(decorator, site.scope) in APPROVED_WIRING_DECORATORS for decorator in site.node.decorator_list
        ):
            return WiringVerdict.APPROVED
        return self._bases_verdict(site, frozenset({qualified}))

    def _module_file(self, module: str) -> tuple[Path, bool] | None:
        """The file of a dotted module and whether it is a package, or None when it is not here."""
        base: Path | None = None
        for prefix, directory in self._roots.items():
            if module == prefix or module.startswith(f"{prefix}."):
                relative = module.removeprefix(prefix).lstrip(".")
                base = directory.joinpath(*relative.split(".")) if relative else directory
                break
        if base is None:
            if module.split(".", 1)[0] not in _REPOSITORY_PACKAGES:
                return None
            base = self._repo_root.joinpath(*module.split("."))
        if base.with_suffix(".py").is_file():
            return base.with_suffix(".py"), False
        if (base / "__init__.py").is_file():
            return base / "__init__.py", True
        return None

    def _bindings(self, module: str, is_package: bool, tree: ast.Module) -> dict[str, str]:
        """The qualified name of each name the module-level imports bind."""
        package = module if is_package else module.rpartition(".")[0]
        bindings: dict[str, str] = {}
        for node in module_level_import_nodes(tree):
            if isinstance(node, ast.Import):
                for alias in node.names:
                    if alias.asname:
                        bindings[alias.asname] = alias.name
                    else:
                        head = alias.name.split(".", 1)[0]
                        bindings[head] = head
                continue
            if node.level:
                parts = package.split(".")
                if node.level - 1 >= len(parts):
                    continue
                source = ".".join(parts[: len(parts) - (node.level - 1)])
                if node.module:
                    source = f"{source}.{node.module}"
            else:
                source = node.module or ""
            for alias in node.names:
                if alias.name != "*":
                    bindings[alias.asname or alias.name] = f"{source}.{alias.name}"
        return bindings

    def _scope(self, module: str) -> _ModuleScope | None:
        located = self._module_file(module)
        if located is None:
            return None
        path, is_package = located
        tree = _parsed(path)
        if tree is None:
            return None
        return _ModuleScope(
            module=module,
            tree=tree,
            bindings=self._bindings(module, is_package, tree),
            classes={node.name: node for node in tree.body if isinstance(node, ast.ClassDef)},
            rebound=_rebound_names(tree),
            mutated=_mutated_names(tree),
        )

    def _qualify(self, node: ast.expr, scope: _ModuleScope) -> str | None:
        """The qualified name an expression in a base, decorator or collection refers to."""
        if isinstance(node, ast.Subscript):
            return self._qualify(node.value, scope)
        if isinstance(node, ast.Call):
            return self._qualify(node.func, scope)
        if isinstance(node, ast.Attribute):
            head = self._qualify(node.value, scope)
            return f"{head}.{node.attr}" if head else None
        if isinstance(node, ast.Name):
            # A module that imports a name and binds it again binds it by statement order, so the
            # lint leaves it unread rather than guess which binding a base refers to.
            if node.id in scope.bindings and node.id in scope.rebound:
                return None
            if node.id in scope.bindings:
                return scope.bindings[node.id]
            if node.id in scope.classes:
                return f"{scope.module}.{node.id}"
            if hasattr(builtins, node.id):
                return f"builtins.{node.id}"
        return None

    def _locate(self, qualified: str, seen: frozenset[str]) -> _ClassSite | WiringVerdict:
        """The class definition a qualified name reaches through re-exports.

        Where no definition stands at the end, the verdict stands in for it: an approved base, a
        library class, or a name the source does not resolve statically."""
        if qualified in APPROVED_WIRING_BASES:
            return WiringVerdict.APPROVED
        if qualified in seen:
            return WiringVerdict.UNRESOLVED
        module, _, name = qualified.rpartition(".")
        scope = self._scope(module) if module else None
        if scope is None:
            if qualified.split(".", 1)[0] in _REPOSITORY_PACKAGES:
                return WiringVerdict.UNRESOLVED
            return WiringVerdict.UNAPPROVED
        if name in scope.classes:
            return _ClassSite(scope=scope, node=scope.classes[name])
        # A name the module only re-exports is judged where it is defined.
        if name in scope.bindings:
            return self._locate(scope.bindings[name], seen | {qualified})
        # An alias such as `Handed = Plain` is judged as the class it names.
        value = _assigned_value(scope.tree, name)
        if isinstance(value, (ast.Name, ast.Attribute)) and (target := self._qualify(value, scope)) is not None:
            return self._locate(target, seen | {qualified})
        return WiringVerdict.UNRESOLVED

    def _members(self, qualified: str, seen: frozenset[str]) -> list[str] | None:
        if qualified in seen:
            return []
        module, _, name = qualified.rpartition(".")
        scope = self._scope(module) if module else None
        if scope is None:
            return []
        value = _assigned_value(scope.tree, name)
        if value is not None:
            if name in scope.mutated:
                return None
            return self._expression_members(value, scope, seen | {qualified})
        if name in scope.bindings:
            return self._members(scope.bindings[name], seen | {qualified})
        return []

    def _element_members(self, element: ast.expr, scope: _ModuleScope, seen: frozenset[str]) -> list[str] | None:
        """One entry of a collection literal: a class name, or a `*OTHER_FLOWS` that unpacks another collection."""
        if isinstance(element, ast.Starred):
            return self._expression_members(element.value, scope, seen)
        member = self._qualify(element, scope)
        return [member] if member is not None else []

    def _expression_members(self, node: ast.expr, scope: _ModuleScope, seen: frozenset[str]) -> list[str] | None:
        """The class names a collection expression holds, such as `[A, B]` or `FLOWS + OTHER_FLOWS`."""
        parts: list[list[str] | None]
        if isinstance(node, (ast.List, ast.Tuple, ast.Set)):
            parts = [self._element_members(element, scope, seen) for element in node.elts]
        elif isinstance(node, ast.BinOp) and isinstance(node.op, ast.Add):
            parts = [
                self._expression_members(node.left, scope, seen),
                self._expression_members(node.right, scope, seen),
            ]
        elif isinstance(node, (ast.Name, ast.Attribute)) and (operand := self._qualify(node, scope)) is not None:
            return self._members(operand, seen)
        else:
            return []
        if any(part is None for part in parts):
            return None
        return [member for part in parts if part is not None for member in part]

    def _ancestor_verdict(self, qualified: str, seen: frozenset[str]) -> WiringVerdict:
        if qualified not in self._ancestor_verdicts:
            site = self._locate(qualified, seen)
            if isinstance(site, WiringVerdict):
                self._ancestor_verdicts[qualified] = site
            else:
                self._ancestor_verdicts[qualified] = self._bases_verdict(site, seen | {qualified})
        return self._ancestor_verdicts[qualified]

    def _bases_verdict(self, site: _ClassSite, seen: frozenset[str]) -> WiringVerdict:
        verdicts = []
        for base in site.node.bases:
            base_name = self._qualify(base, site.scope)
            if base_name is None:
                verdicts.append(WiringVerdict.UNRESOLVED)
            else:
                verdicts.append(self._ancestor_verdict(base_name, seen))
        if WiringVerdict.APPROVED in verdicts:
            return WiringVerdict.APPROVED
        if WiringVerdict.UNRESOLVED in verdicts:
            return WiringVerdict.UNRESOLVED
        return WiringVerdict.UNAPPROVED
