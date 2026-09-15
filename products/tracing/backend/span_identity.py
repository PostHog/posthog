"""Reading a span's PostHog session ID and person distinct ID out of its attribute maps.

Shared by the impact query runner and the operations aggregation, so the strip's counts and
the table's columns come from the same expression.
"""

from posthog.hogql import ast


def identity_value_expr(attribute_keys: list[str]) -> ast.Expr:
    """First non-empty value across the candidate keys, or NULL when a span carries none.

    Span attributes are checked before resource attributes for each key. That is the
    precedence `getSessionIdWithKey` applies in products/logs/frontend/utils.tsx, which the
    span attribute table and the trace drawer header resolve through, so the counts cover the
    spans the UI already renders as replay and person links.

    Span attribute keys carry the ingestion MV's `__str` type suffix, because the
    property-group resolver only rewrites suffixed keys to a map read and a bare key falls
    through to a JSON read that is illegal on the Map column. `resource_attributes` matches
    any key as-is. A missing key reads as '', which `nullIf` scrubs to NULL so the aggregates
    skip spans that carry no identity.
    """
    args: list[ast.Expr] = []
    for attribute_key in attribute_keys:
        chains: list[list[str | int]] = [
            ["attributes", f"{attribute_key}__str"],
            ["resource_attributes", attribute_key],
        ]
        for chain in chains:
            args.append(ast.Call(name="nullIf", args=[ast.Field(chain=chain), ast.Constant(value="")]))
    return ast.Call(name="coalesce", args=args)
