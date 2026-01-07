import ast
import hashlib
from dataclasses import dataclass
from typing import Any


@dataclass(frozen=True)
class PythonGlobalsAnalysis:
    used: list[str]
    exported: list[str]
    exported_with_types: list[dict[str, str]]


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


def collect_arg_names(arguments: ast.arguments) -> set[str]:
    names = {arg.arg for arg in arguments.args}
    names.update({arg.arg for arg in arguments.posonlyargs})
    names.update({arg.arg for arg in arguments.kwonlyargs})
    if arguments.vararg:
        names.add(arguments.vararg.arg)
    if arguments.kwarg:
        names.add(arguments.kwarg.arg)
    return names


@dataclass
class Scope:
    kind: str
    locals: set[str]


class GlobalAnalyzer(ast.NodeVisitor):
    def __init__(self, module_locals: set[str], builtins: set[str]) -> None:
        self.module_locals = module_locals
        self.builtins = builtins
        self.used: set[str] = set()
        self.scopes: list[Scope] = [Scope(kind="module", locals=module_locals)]

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
            if self.is_global_name(node.id) and node.id not in self.builtins and node.id not in self.module_locals:
                self.used.add(node.id)

    def visit_FunctionDef(self, node: ast.FunctionDef) -> None:
        self._visit_function_like(node, "function")

    def visit_AsyncFunctionDef(self, node: ast.AsyncFunctionDef) -> None:
        self._visit_function_like(node, "function")

    def _visit_function_like(self, node: ast.AST, kind: str) -> None:
        if isinstance(node, ast.FunctionDef | ast.AsyncFunctionDef):
            for decorator in node.decorator_list:
                self.visit(decorator)
            for default in node.args.defaults:
                self.visit(default)
            for default in node.args.kw_defaults:
                if default is not None:
                    self.visit(default)
            for arg in node.args.args + node.args.posonlyargs + node.args.kwonlyargs:
                if arg.annotation:
                    self.visit(arg.annotation)
            if node.args.vararg and node.args.vararg.annotation:
                self.visit(node.args.vararg.annotation)
            if node.args.kwarg and node.args.kwarg.annotation:
                self.visit(node.args.kwarg.annotation)
            if node.returns:
                self.visit(node.returns)
            if getattr(node, "type_params", None):
                for param in node.type_params:
                    self.visit(param)

            locals_set = collect_scope_locals(node.body)
            locals_set.update(collect_arg_names(node.args))
            self.scopes.append(Scope(kind=kind, locals=locals_set))
            for statement in node.body:
                self.visit(statement)
            self.scopes.pop()

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

    def _visit_comprehension(self, node: ast.AST, kind: str) -> None:
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


def extract_target_names(target: ast.AST) -> set[str]:
    names: set[str] = set()
    if isinstance(target, ast.Name):
        names.add(target.id)
    elif isinstance(target, ast.Tuple | ast.List):
        for item in target.elts:
            names.update(extract_target_names(item))
    elif isinstance(target, ast.Starred):
        names.update(extract_target_names(target.value))
    return names


def annotation_to_string(annotation: ast.AST) -> str:
    if hasattr(ast, "unparse"):
        return ast.unparse(annotation)
    return "unknown"


def dotted_name(value: ast.AST) -> str | None:
    if isinstance(value, ast.Name):
        return value.id
    if isinstance(value, ast.Attribute):
        base = dotted_name(value.value)
        if base:
            return f"{base}.{value.attr}"
        return value.attr
    return None


def infer_value_type(value: ast.AST) -> str:
    if isinstance(value, ast.Constant):
        if value.value is None:
            return "None"
        return type(value.value).__name__
    if isinstance(value, ast.List | ast.ListComp):
        return "list"
    if isinstance(value, ast.Tuple):
        return "tuple"
    if isinstance(value, ast.Dict | ast.DictComp):
        return "dict"
    if isinstance(value, ast.Set | ast.SetComp):
        return "set"
    if isinstance(value, ast.GeneratorExp):
        return "generator"
    if isinstance(value, ast.Call):
        call_name = dotted_name(value.func)
        if call_name in {"list", "dict", "set", "tuple", "int", "float", "str", "bool"}:
            return call_name
    return "unknown"


def collect_exported_types(body: list[ast.stmt]) -> dict[str, str]:
    exported_types: dict[str, str] = {}

    for statement in body:
        if isinstance(statement, ast.Assign):
            type_name = infer_value_type(statement.value)
            for target in statement.targets:
                for name in extract_target_names(target):
                    exported_types[name] = type_name
        elif isinstance(statement, ast.AnnAssign):
            type_name = annotation_to_string(statement.annotation)
            if type_name == "unknown" and statement.value:
                type_name = infer_value_type(statement.value)
            for name in extract_target_names(statement.target):
                exported_types[name] = type_name
        elif isinstance(statement, ast.AugAssign):
            for name in extract_target_names(statement.target):
                exported_types.setdefault(name, "unknown")
        elif isinstance(statement, ast.Import):
            for alias in statement.names:
                name = alias.asname or alias.name.split(".")[0]
                exported_types.setdefault(name, "module")
        elif isinstance(statement, ast.ImportFrom):
            for alias in statement.names:
                name = alias.asname or alias.name
                exported_types.setdefault(name, "module")

    return exported_types


def analyze_python_globals(code: str) -> PythonGlobalsAnalysis:
    if not code or not code.strip():
        return PythonGlobalsAnalysis(used=[], exported=[], exported_with_types=[])

    try:
        tree = ast.parse(code)
    except SyntaxError:
        return PythonGlobalsAnalysis(used=[], exported=[], exported_with_types=[])

    module_locals = collect_scope_locals(tree.body)
    builtins_obj = __builtins__
    builtins = set(builtins_obj.keys()) if isinstance(builtins_obj, dict) else set(dir(builtins_obj))
    analyzer = GlobalAnalyzer(module_locals, builtins)
    analyzer.visit(tree)
    exported_types = collect_exported_types(tree.body)
    exported_with_types = [
        {"name": name, "type": exported_types.get(name, "unknown")} for name in sorted(module_locals)
    ]

    return PythonGlobalsAnalysis(
        used=sorted(analyzer.used),
        exported_with_types=exported_with_types,
    )


def compute_globals_analysis_hash(code: str) -> str:
    return hashlib.sha256(code.encode("utf-8")).hexdigest()


def annotate_python_nodes(content: dict[str, Any]) -> dict[str, Any]:
    if not isinstance(content, dict):
        return content

    def walk(node: Any) -> Any:
        if not isinstance(node, dict):
            return node

        node_type = node.get("type")
        if node_type == "ph-python":
            attrs = node.get("attrs")
            if isinstance(attrs, dict):
                code = attrs.get("code", "")
                if isinstance(code, str):
                    code_hash = compute_globals_analysis_hash(code)
                    existing_hash = attrs.get("globalsAnalysisHash")
                    has_cached_analysis = (
                        isinstance(existing_hash, str)
                        and existing_hash == code_hash
                        and "globalsUsed" in attrs
                        and "globalsExportedWithTypes" in attrs
                    )
                    if not has_cached_analysis:
                        analysis = analyze_python_globals(code)
                        attrs = {
                            **attrs,
                            "globalsUsed": analysis.used,
                            "globalsExportedWithTypes": analysis.exported_with_types,
                            "globalsAnalysisHash": code_hash,
                        }
                        node = {**node, "attrs": attrs}

        content_nodes = node.get("content")
        if isinstance(content_nodes, list):
            node = {**node, "content": [walk(child) for child in content_nodes]}

        return node

    return walk(content)
