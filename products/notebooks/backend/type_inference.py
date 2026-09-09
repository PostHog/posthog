import ast

from products.notebooks.backend.ast_names import dotted_name, extract_target_names


def annotation_to_string(annotation: ast.AST) -> str:
    if hasattr(ast, "unparse"):
        return ast.unparse(annotation)
    return "unknown"


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
        if isinstance(statement, ast.Assign | ast.AnnAssign | ast.AugAssign):
            _record_assignment_export(statement, exported_types)
        elif isinstance(statement, ast.Import | ast.ImportFrom):
            _record_import_export(statement, exported_types)
    return exported_types


def _record_assignment_export(
    statement: ast.Assign | ast.AnnAssign | ast.AugAssign, exported_types: dict[str, str]
) -> None:
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
    else:
        for name in extract_target_names(statement.target):
            exported_types.setdefault(name, "unknown")


def _record_import_export(statement: ast.Import | ast.ImportFrom, exported_types: dict[str, str]) -> None:
    for alias in statement.names:
        if isinstance(statement, ast.Import):
            name = alias.asname or alias.name.split(".")[0]
        else:
            name = alias.asname or alias.name
        exported_types.setdefault(name, "module")
