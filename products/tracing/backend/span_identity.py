"""Reading span attributes out of the physical attribute maps.

Shared by the impact query runner and the operations aggregation, so the strip's counts and the
table's columns come from the same expression.
"""

from posthog.hogql import ast


def str_attr_field(key: str) -> ast.Field:
    """A span attribute read, with the physical map's type suffix.

    Span attributes live in the typed str map; the property-group resolver rewrites a
    `__str`-suffixed key into a Map read. A bare key falls through to an illegal JSON read.
    """
    return ast.Field(chain=["attributes", f"{key}__str"])


def identity_value_expr(attribute_keys: list[str]) -> ast.Expr:
    """First non-empty value across the candidate keys, or NULL when a span carries none.

    Span attributes are checked before resource attributes for each key. That is the precedence
    `getSessionIdWithKey` applies in products/logs/frontend/utils.tsx, which the span attribute
    table and the trace drawer header resolve through, so the counts cover the spans the UI
    already renders as replay and person links.

    `resource_attributes` matches any key as-is. A missing key reads as '', which `nullIf` scrubs
    to NULL so the aggregates skip spans that carry no identity.
    """
    args: list[ast.Expr] = []
    for attribute_key in attribute_keys:
        resource_read: ast.Expr = ast.Field(chain=["resource_attributes", attribute_key])
        for read in (str_attr_field(attribute_key), resource_read):
            args.append(ast.Call(name="nullIf", args=[read, ast.Constant(value="")]))
    return ast.Call(name="coalesce", args=args)
