import hashlib

from posthog.hogql import ast
from posthog.hogql.functions.mapping import find_hogql_aggregation
from posthog.hogql.parser import parse_expr
from posthog.hogql.visitor import TraversingVisitor

# A recognized source prefix selects the lowering strategy (source-driven):
# flat map lookup for attribute maps, JSON dig for the body string.
FLAT_MAP_SOURCES = ("attributes", "resource_attributes")
JSON_BODY_SOURCE = "body"


def path_to_expr(source: str, path: str) -> ast.Expr:
    """Lower a custom-column descriptor `(source, path)` into a HogQL AST expression.

    - `attributes` / `resource_attributes`: the whole `path` is a single map key
      (dots are part of the OTel key, never split) -> `attributes['http.url']`.
    - `body`: `path` is a dot-separated JSON path -> `JSONExtractString(body, 'user', 'id')`.

    `path` is always carried as a bound chain member / Constant, so it cannot escape
    the map-index or JSONExtract boundary as interpolated SQL.
    """
    if source in FLAT_MAP_SOURCES:
        return ast.Field(chain=[source, path])

    if source == JSON_BODY_SOURCE:
        segments = path.split(".")
        if any(segment == "" for segment in segments):
            raise ValueError(f"Body path {path!r} contains an empty segment")
        keys = [ast.Constant(value=segment) for segment in segments]
        return ast.Call(name="JSONExtractString", args=[ast.Field(chain=[JSON_BODY_SOURCE]), *keys])

    raise ValueError(f"Unknown custom-column source: {source!r}")


def parse_shorthand(text: str) -> ast.Expr | None:
    """Lower `<source>.<path>` shorthand, or return `None` if `text` has no recognized prefix.

    A bare source name with no path (`attributes`) is not shorthand — it falls through
    to full-expression parsing like any other field.
    """
    source, dot, path = text.partition(".")
    if not dot or not path:
        return None
    if source not in FLAT_MAP_SOURCES and source != JSON_BODY_SOURCE:
        return None
    return path_to_expr(source, path)


class _ScalarValidator(TraversingVisitor):
    def visit_select_query(self, node: ast.SelectQuery) -> None:
        raise ValueError("Custom columns cannot contain subqueries")

    def visit_select_set_query(self, node: ast.SelectSetQuery) -> None:
        raise ValueError("Custom columns cannot contain subqueries")

    def visit_placeholder(self, node: ast.Placeholder) -> None:
        raise ValueError("Custom columns cannot contain placeholders")

    def visit_call(self, node: ast.Call) -> None:
        if find_hogql_aggregation(node.name) is not None:
            raise ValueError(f"Custom columns must be per-row: aggregation {node.name!r} is not allowed")
        super().visit_call(node)


def _validate_scalar(expr: ast.Expr) -> None:
    """Reject subqueries, aggregations, and unresolved placeholders anywhere in `expr`.

    Scalar function calls, field access, arithmetic, conditionals, and constants all
    pass. This is an AST check — the expression is never inspected as a string.
    """
    _ScalarValidator().visit(expr)


def column_to_expr(text: str) -> ast.Expr:
    """Resolve a custom-column string into a validated per-row HogQL AST expression.

    Recognized source prefix -> shorthand lowering; otherwise the whole string is
    parsed as HogQL (`parse_expr`, so input is never interpolated as SQL). Raises
    `ValueError` for non-scalar expressions and HogQL syntax errors for unparsable input.
    """
    text = text.strip()
    expr = parse_shorthand(text)
    if expr is None:
        expr = parse_expr(text)
    _validate_scalar(expr)
    return expr


def canonical_key(text: str) -> str:
    """Derive a stable `col_<hash>` alias from the expression string.

    Independent of any client-generated uuid so identical column setups hash to the
    same query (and therefore the same query cache key).
    """
    digest = hashlib.sha256(text.strip().encode()).hexdigest()
    return f"col_{digest[:12]}"
