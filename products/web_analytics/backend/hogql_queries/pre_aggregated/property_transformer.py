from posthog.hogql import ast
from posthog.hogql.visitor import CloningVisitor

# The pre-aggregated tables store these columns as String, not Nullable(String), so a missing value is ''.
# An "is not set" filter compiles to `= NULL`, which matches no row there, so we compare with '' instead.
EMPTY_WHEN_UNSET_COLUMNS = frozenset(
    {
        "host",
        "device_type",
        "pathname",
        "entry_pathname",
        "end_pathname",
        "browser",
        "os",
        "referring_domain",
        "utm_source",
        "utm_medium",
        "utm_campaign",
        "utm_term",
        "utm_content",
        "country_code",
        "city_name",
        "region_code",
        "region_name",
    }
)


class PreAggregatedPropertyTransformer(CloningVisitor):
    """Transforms field chains to reference pre-aggregated table columns."""

    def __init__(self, table_name: str, supported_props_filters: dict):
        super().__init__()
        self.table_name = table_name
        self.supported_props_filters = supported_props_filters

    def visit_field(self, node: ast.Field) -> ast.Field:
        chain = node.chain

        prop_key = None
        if chain[:2] == ["events", "properties"] and len(chain) == 3:
            prop_key = chain[2]
        elif (chain[:1] == ["session"] or chain[:1] == ["properties"]) and len(chain) == 2:
            prop_key = chain[1]

        if prop_key and prop_key in self.supported_props_filters:
            # If the mapping is None (virtual fields like $channel_type), don't transform
            if self.supported_props_filters[prop_key] is None:
                return super().visit_field(node)
            return ast.Field(chain=[self.table_name, self.supported_props_filters[prop_key]])

        return super().visit_field(node)

    def visit_compare_operation(self, node: ast.CompareOperation) -> ast.CompareOperation:
        transformed = super().visit_compare_operation(node)
        if (
            transformed.op in (ast.CompareOperationOp.Eq, ast.CompareOperationOp.NotEq)
            and isinstance(transformed.right, ast.Constant)
            and transformed.right.value is None
            and isinstance(transformed.left, ast.Field)
            and len(transformed.left.chain) == 2
            and transformed.left.chain[0] == self.table_name
            and transformed.left.chain[1] in EMPTY_WHEN_UNSET_COLUMNS
        ):
            return ast.CompareOperation(op=transformed.op, left=transformed.left, right=ast.Constant(value=""))
        return transformed


class ChannelTypeReplacer(CloningVisitor):
    def __init__(self, channel_type_expr: ast.Expr):
        super().__init__()
        self.channel_type_expr = channel_type_expr

    def visit_field(self, node: ast.Field) -> ast.Expr | ast.Field:
        if node.chain == ["session", "$channel_type"] or node.chain == ["properties", "$channel_type"]:
            return self.channel_type_expr
        return super().visit_field(node)
