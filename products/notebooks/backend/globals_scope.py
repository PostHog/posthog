import ast
from typing import Literal

from posthog.dataclasses import frozen

from products.notebooks.backend.ast_names import collect_arg_names, extract_target_names, match_capture_names


class LocalAssignmentCollector(ast.NodeVisitor):
    def __init__(self) -> None:
        self.locals: set[str] = set()
        self.global_names: set[str] = set()
        self.nonlocal_names: set[str] = set()

    def visit_Global(self, node: ast.Global) -> None:
        self.global_names.update(node.names)

    def visit_Nonlocal(self, node: ast.Nonlocal) -> None:
        self.nonlocal_names.update(node.names)

    def visit_Name(self, node: ast.Name) -> None:
        if isinstance(node.ctx, ast.Store):
            self.locals.add(node.id)

    def visit_FunctionDef(self, node: ast.FunctionDef) -> None:
        self.locals.add(node.name)

    def visit_AsyncFunctionDef(self, node: ast.AsyncFunctionDef) -> None:
        self.locals.add(node.name)

    def visit_ClassDef(self, node: ast.ClassDef) -> None:
        self.locals.add(node.name)

    def visit_Lambda(self, node: ast.Lambda) -> None:
        return

    def visit_ListComp(self, node: ast.ListComp) -> None:
        return

    def visit_SetComp(self, node: ast.SetComp) -> None:
        return

    def visit_DictComp(self, node: ast.DictComp) -> None:
        return

    def visit_GeneratorExp(self, node: ast.GeneratorExp) -> None:
        return

    def visit_Import(self, node: ast.Import) -> None:
        for alias in node.names:
            name = alias.asname or alias.name.split(".")[0]
            self.locals.add(name)

    def visit_ImportFrom(self, node: ast.ImportFrom) -> None:
        for alias in node.names:
            name = alias.asname or alias.name
            self.locals.add(name)


def collect_scope_locals(body: list[ast.stmt]) -> set[str]:
    collector = LocalAssignmentCollector()
    for statement in body:
        collector.visit(statement)
    locals_set = collector.locals - collector.global_names - collector.nonlocal_names
    return locals_set


ScopeKind = Literal["module", "function", "class", "lambda", "comprehension"]


@frozen
class Scope:
    kind: ScopeKind
    locals: set[str]


class GlobalAnalyzer(ast.NodeVisitor):
    def __init__(self, module_locals: set[str], builtins: set[str]) -> None:
        self.module_locals = module_locals
        self.builtins = builtins
        self.used: set[str] = set()
        self.scopes: list[Scope] = [Scope(kind="module", locals=module_locals)]
        # Module names bound so far in execution order. At module (exec) scope a name is a
        # local *from the point it is bound onwards* — reading it before that reads the injected
        # namespace, so a read-before-bind name (df.columns = ...; df = df.assign(...)) is a
        # genuine external input, unlike function scope where any assignment makes the name local.
        self.module_assigned: set[str] = set()

    def is_global_name(self, name: str) -> bool:
        current_scope = self.scopes[-1]
        if current_scope.kind == "class":
            if name in current_scope.locals:
                return False
            return True
        for scope in reversed(self.scopes):
            if name in scope.locals:
                return scope.kind == "module"
        return True

    def visit_Name(self, node: ast.Name) -> None:
        if isinstance(node.ctx, ast.Load):
            # A module-scope name already bound before this read is a local, not an input.
            if self.is_global_name(node.id) and node.id not in self.builtins and node.id not in self.module_assigned:
                self.used.add(node.id)

    def visit_Module(self, node: ast.Module) -> None:
        self._visit_module_children(node.body)

    def _visit_module_children(self, statements: list[ast.stmt]) -> None:
        for statement in statements:
            self._visit_module_statement(statement)

    def _visit_module_statement(self, statement: ast.stmt) -> None:
        # Walk top-level statements in execution order, visiting reads before recording the
        # bindings they introduce, so a name read before it is bound counts as an input.
        if isinstance(statement, ast.Assign | ast.AnnAssign | ast.AugAssign):
            self._module_assignment(statement)
        elif isinstance(statement, ast.Import | ast.ImportFrom):
            self._module_import(statement)
        elif isinstance(statement, ast.FunctionDef | ast.AsyncFunctionDef | ast.ClassDef):
            self.visit(statement)
            self.module_assigned.add(statement.name)
        elif isinstance(statement, ast.For | ast.AsyncFor):
            self._module_for(statement)
        elif isinstance(statement, ast.With | ast.AsyncWith):
            self._module_with(statement)
        elif isinstance(statement, ast.If | ast.While):
            self._module_branch(statement)
        elif isinstance(statement, ast.Try):
            self._module_try(statement)
        elif isinstance(statement, ast.Match):
            self._module_match(statement)
        else:
            self.visit(statement)

    def _module_assignment(self, statement: ast.Assign | ast.AnnAssign | ast.AugAssign) -> None:
        if isinstance(statement, ast.Assign):
            self.visit(statement.value)
            for target in statement.targets:
                self.visit(target)  # attribute/subscript targets still *read* their base object
            self._record_bindings(statement.targets)
        elif isinstance(statement, ast.AnnAssign):
            if statement.value is not None:
                self.visit(statement.value)
            self.visit(statement.annotation)
            self.visit(statement.target)
            if statement.value is not None:
                self._record_bindings([statement.target])
        else:
            self.visit(statement.value)
            self.visit(statement.target)
            self._record_bindings([statement.target])

    def _module_import(self, statement: ast.Import | ast.ImportFrom) -> None:
        if isinstance(statement, ast.Import):
            self.module_assigned.update(alias.asname or alias.name.split(".")[0] for alias in statement.names)
        else:
            self.module_assigned.update(alias.asname or alias.name for alias in statement.names)

    def _module_for(self, statement: ast.For | ast.AsyncFor) -> None:
        self.visit(statement.iter)
        self._record_bindings([statement.target])  # loop var is bound before the body runs
        self._visit_module_children([*statement.body, *statement.orelse])

    def _module_with(self, statement: ast.With | ast.AsyncWith) -> None:
        for item in statement.items:
            self.visit(item.context_expr)
            if item.optional_vars is not None:
                self._record_bindings([item.optional_vars])
        self._visit_module_children(statement.body)

    def _module_branch(self, statement: ast.If | ast.While) -> None:
        self.visit(statement.test)
        self._visit_module_children([*statement.body, *statement.orelse])

    def _module_try(self, statement: ast.Try) -> None:
        self._visit_module_children(statement.body)
        for handler in statement.handlers:
            if handler.type is not None:
                self.visit(handler.type)
            if handler.name is not None:
                self.module_assigned.add(handler.name)
            self._visit_module_children(handler.body)
        self._visit_module_children([*statement.orelse, *statement.finalbody])

    def _module_match(self, statement: ast.Match) -> None:
        self.visit(statement.subject)
        for case in statement.cases:
            # Capture patterns bind their names before the case body runs.
            self.module_assigned.update(match_capture_names(case.pattern))
            if case.guard is not None:
                self.visit(case.guard)
            self._visit_module_children(case.body)

    def visit_NamedExpr(self, node: ast.NamedExpr) -> None:
        # A walrus binds its target in the enclosing scope; at module scope record it so a later
        # read (print(rows) after `if (rows := ...)`) isn't mistaken for an external input.
        self.visit(node.value)
        if len(self.scopes) == 1:
            self.module_assigned.update(extract_target_names(node.target))
        self.visit(node.target)

    def _record_bindings(self, targets: list[ast.expr]) -> None:
        for target in targets:
            self.module_assigned.update(extract_target_names(target))

    def visit_FunctionDef(self, node: ast.FunctionDef) -> None:
        self._visit_function_like(node, "function")

    def visit_AsyncFunctionDef(self, node: ast.AsyncFunctionDef) -> None:
        self._visit_function_like(node, "function")

    def _visit_function_like(self, node: ast.FunctionDef | ast.AsyncFunctionDef, kind: ScopeKind) -> None:
        self._visit_function_signature(node)
        locals_set = collect_scope_locals(node.body)
        locals_set.update(collect_arg_names(node.args))
        self.scopes.append(Scope(kind=kind, locals=locals_set))
        for statement in node.body:
            self.visit(statement)
        self.scopes.pop()

    def _visit_function_signature(self, node: ast.FunctionDef | ast.AsyncFunctionDef) -> None:
        for decorator in node.decorator_list:
            self.visit(decorator)
        for default in node.args.defaults:
            self.visit(default)
        for kw_default in node.args.kw_defaults:
            if kw_default is not None:
                self.visit(kw_default)
        self._visit_arg_annotations(node.args)
        if node.returns:
            self.visit(node.returns)
        for param in getattr(node, "type_params", None) or []:
            self.visit(param)

    def _visit_arg_annotations(self, args: ast.arguments) -> None:
        for arg in args.args + args.posonlyargs + args.kwonlyargs:
            if arg.annotation:
                self.visit(arg.annotation)
        if args.vararg and args.vararg.annotation:
            self.visit(args.vararg.annotation)
        if args.kwarg and args.kwarg.annotation:
            self.visit(args.kwarg.annotation)

    def visit_ClassDef(self, node: ast.ClassDef) -> None:
        for base in node.bases:
            self.visit(base)
        for keyword in node.keywords:
            self.visit(keyword)
        for decorator in node.decorator_list:
            self.visit(decorator)
        if getattr(node, "type_params", None):
            for param in node.type_params:
                self.visit(param)

        locals_set = collect_scope_locals(node.body)
        self.scopes.append(Scope(kind="class", locals=locals_set))
        for statement in node.body:
            self.visit(statement)
        self.scopes.pop()

    def visit_Lambda(self, node: ast.Lambda) -> None:
        locals_set = collect_arg_names(node.args)
        self.scopes.append(Scope(kind="lambda", locals=locals_set))
        self.visit(node.body)
        self.scopes.pop()

    def visit_ListComp(self, node: ast.ListComp) -> None:
        self._visit_comprehension(node, "comprehension")

    def visit_SetComp(self, node: ast.SetComp) -> None:
        self._visit_comprehension(node, "comprehension")

    def visit_DictComp(self, node: ast.DictComp) -> None:
        self._visit_comprehension(node, "comprehension")

    def visit_GeneratorExp(self, node: ast.GeneratorExp) -> None:
        self._visit_comprehension(node, "comprehension")

    def _visit_comprehension(self, node: ast.AST, kind: ScopeKind) -> None:
        generators = getattr(node, "generators", [])
        locals_set: set[str] = set()
        for generator in generators:
            locals_set.update(extract_target_names(generator.target))
        self.scopes.append(Scope(kind=kind, locals=locals_set))
        if isinstance(node, ast.DictComp):
            self.visit(node.key)
            self.visit(node.value)
        elif hasattr(node, "elt"):
            self.visit(node.elt)
        for generator in generators:
            self.visit(generator.iter)
            for if_node in generator.ifs:
                self.visit(if_node)
        self.scopes.pop()
