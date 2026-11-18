from collections.abc import Mapping

from posthog.hogql import ast
from posthog.hogql.errors import BaseHogQLError
from posthog.hogql.parser import parse_expr
from posthog.hogql.visitor import clone_expr


class FilterValidationError(ValueError):
    def __init__(self, code: str, message: str, node: ast.Expr | None = None) -> None:
        super().__init__(message)
        self.code = code
        self.start = node.start if node else None
        self.end = node.end if node else None


class FilterExpression:
    MAX_LENGTH = 4096
    MAX_NODES = 256
    MAX_DEPTH = 20
    MAX_LIST_ITEMS = 64
    MAX_LITERAL_LENGTH = 1024
    FIELD_TYPES = frozenset({"string", "integer", "array<string>"})

    def __init__(self, expression: str, fields: Mapping[str, str]) -> None:
        self._fields = dict(fields)
        for name, field_type in self._fields.items():
            if field_type not in self.FIELD_TYPES:
                raise FilterValidationError(
                    "unsupported_field_type", f"Catalog field {name} has unsupported type {field_type}."
                )
        self._nodes = 0
        self.referenced_fields: set[str] = set()
        self._expression: ast.Expr | None = None
        if len(expression) > self.MAX_LENGTH:
            raise FilterValidationError("expression_limit", "Use an expression of at most 4096 characters.")
        if not expression.strip():
            return
        try:
            parsed = parse_expr(expression)
        except (BaseHogQLError, RecursionError) as error:
            raise FilterValidationError("syntax", "Enter a boolean HogQL expression.") from error
        if self._validate(parsed, 0) != "boolean":
            raise FilterValidationError("boolean_required", "The expression must return a boolean.", parsed)
        self._expression = parsed

    def predicate(self) -> ast.Expr | None:
        return clone_expr(self._expression) if self._expression is not None else None

    def _require(self, valid: bool, node: ast.Expr, message: str) -> None:
        if not valid:
            raise FilterValidationError("type", message, node)

    def _field_type(self, node: ast.Field) -> str:
        if len(node.chain) != 1 or node.chain[0] not in self._fields:
            raise FilterValidationError("unknown_field", "Use an unqualified field from the filter catalog.", node)
        name = str(node.chain[0])
        self.referenced_fields.add(name)
        return self._fields[name]

    def _validate(self, node: ast.Expr, depth: int) -> str:
        self._nodes += 1
        if depth > self.MAX_DEPTH or self._nodes > self.MAX_NODES:
            raise FilterValidationError(
                "complexity_limit", "Simplify the expression's nesting or number of terms.", node
            )
        if isinstance(node, ast.Constant):
            return self._literal_type(node)
        if isinstance(node, ast.Field):
            return self._field_type(node)
        if isinstance(node, ast.Not):
            self._require(self._validate(node.expr, depth + 1) == "boolean", node, "NOT requires a boolean.")
            return "boolean"
        if isinstance(node, ast.And | ast.Or):
            for expr in node.exprs:
                self._require(self._validate(expr, depth + 1) == "boolean", expr, "AND and OR require boolean terms.")
            return "boolean"
        if isinstance(node, ast.Tuple | ast.Array):
            self._require(0 < len(node.exprs) <= self.MAX_LIST_ITEMS, node, "Use between 1 and 64 list items.")
            types = {self._validate(expr, depth + 1) for expr in node.exprs}
            self._require(len(types) == 1 and types <= {"string", "integer"}, node, "Use one scalar type of list item.")
            return f"array<{next(iter(types))}>"
        if isinstance(node, ast.CompareOperation):
            return self._comparison_type(node, depth)
        if isinstance(node, ast.Call):
            return self._call_type(node, depth)
        raise FilterValidationError("unsupported_expression", "This expression form is not supported in filters.", node)

    def _literal_type(self, node: ast.Constant) -> str:
        value = node.value
        if value is None:
            return "null"
        if isinstance(value, bool):
            return "boolean"
        if isinstance(value, int) and -(2**63) <= value < 2**63:
            return "integer"
        if isinstance(value, str) and len(value) <= self.MAX_LITERAL_LENGTH:
            return "string"
        raise FilterValidationError("literal_limit", "Use a bounded string, integer, boolean or null literal.", node)

    def _comparison_type(self, node: ast.CompareOperation, depth: int) -> str:
        if node.op in {ast.CompareOperationOp.In, ast.CompareOperationOp.NotIn} and isinstance(
            node.right, ast.Constant
        ):
            node.right = ast.Tuple(exprs=[node.right], start=node.right.start, end=node.right.end)
        left = self._validate(node.left, depth + 1)
        right = self._validate(node.right, depth + 1)
        if node.op in {ast.CompareOperationOp.In, ast.CompareOperationOp.NotIn}:
            if not isinstance(node.right, ast.Tuple | ast.Array):
                raise FilterValidationError("type", "IN requires a literal list.", node)
            self._require(
                all(isinstance(expr, ast.Constant) for expr in node.right.exprs), node, "IN requires literal values."
            )
            self._require(
                left in {"string", "integer"} and right == f"array<{left}>",
                node,
                "IN values must match the field type.",
            )
        elif node.op in {ast.CompareOperationOp.Eq, ast.CompareOperationOp.NotEq}:
            self._require(
                not left.startswith("array<") and not right.startswith("array<"), node, "Use has to inspect arrays."
            )
            self._require("null" in {left, right} or left == right, node, "Compare values of the same type.")
        elif node.op in {
            ast.CompareOperationOp.Gt,
            ast.CompareOperationOp.GtEq,
            ast.CompareOperationOp.Lt,
            ast.CompareOperationOp.LtEq,
        }:
            self._require(left in {"string", "integer"} and left == right, node, "Use compatible ordered values.")
        else:
            raise FilterValidationError("unsupported_operator", "This comparison operator is not supported.", node)
        return "boolean"

    def _call_type(self, node: ast.Call, depth: int) -> str:
        if node.params is not None or node.distinct or node.within_group or node.order_by or node.filter_expr:
            raise FilterValidationError("unsupported_function", "Function modifiers are not supported.", node)
        types = [self._validate(expr, depth + 1) for expr in node.args]
        name = node.name.lower()
        if name in {"isnull", "isnotnull"} and len(types) == 1:
            node.name = "isNull" if name == "isnull" else "isNotNull"
            return "boolean"
        if name == "not" and types == ["boolean"]:
            node.name = "not"
            return "boolean"
        if (
            name == "has"
            and types == ["array<string>", "string"]
            and isinstance(node.args[0], ast.Field)
            and isinstance(node.args[1], ast.Constant)
        ):
            node.name = "has"
            return "boolean"
        raise FilterValidationError(
            "unsupported_function", "Use a supported function with matching argument types.", node
        )
