from posthog.hogql import ast

from posthog.models.exchange_rate.sql import EXCHANGE_RATE_DECIMAL_PRECISION

from products.revenue_analytics.backend.views.core import BuiltQuery, SourceHandle, view_prefix_for_source
from products.revenue_analytics.backend.views.schemas import (
    REVENUE_ITEM as REVENUE_ITEM_SCHEMA,
    SUBSCRIPTION as SUBSCRIPTION_SCHEMA,
)
from products.revenue_analytics.backend.views.sources.helpers import generate_mrr_start_and_end_date_expr
from products.revenue_analytics.backend.views.sources.stripe.revenue_item import build as build_revenue_items


def build(handle: SourceHandle) -> BuiltQuery:
    source = handle.source
    if source is None:
        raise ValueError("Source is required")

    prefix = view_prefix_for_source(source)

    revenue_item_base_query_name = f"{prefix}.{REVENUE_ITEM_SCHEMA.source_suffix}"
    subscription_base_query_name = f"{prefix}.{SUBSCRIPTION_SCHEMA.source_suffix}"

    start_date_expr, end_date_expr = generate_mrr_start_and_end_date_expr()

    revenue_item_table: ast.Field | ast.SelectQuery | ast.SelectSetQuery = ast.Field(
        chain=[revenue_item_base_query_name]
    )
    amount = ast.Call(name="sum", args=[ast.Field(chain=["revenue_item", "amount"])])
    if source.excluded_product_ids:
        # Keep excluded billing periods so argMax cannot fall back to an older product's MRR.
        unfiltered_revenue_items = build_revenue_items(handle, apply_product_exclusions=False).query
        assert isinstance(unfiltered_revenue_items, ast.SelectQuery | ast.SelectSetQuery)
        revenue_item_table = unfiltered_revenue_items
        amount = ast.Call(
            name="ifNull",
            args=[
                ast.Call(
                    name="sumIf",
                    args=[
                        ast.Field(chain=["revenue_item", "amount"]),
                        ast.CompareOperation(
                            op=ast.CompareOperationOp.NotIn,
                            left=ast.Field(chain=["revenue_item", "product_id"]),
                            right=ast.Tuple(
                                exprs=[ast.Constant(value=product_id) for product_id in source.excluded_product_ids]
                            ),
                        ),
                    ],
                ),
                ast.Call(
                    name="toDecimal",
                    args=[ast.Constant(value=0), ast.Constant(value=EXCHANGE_RATE_DECIMAL_PRECISION)],
                ),
            ],
        )

    # Make sure we group all revenue items from a single subscription and month together
    # because if they're from the same subscription then it's recurring amount
    revenue_item_query = ast.SelectQuery(
        select=[
            ast.Field(chain=["source_label"]),
            ast.Field(chain=["customer_id"]),
            ast.Field(chain=["subscription_id"]),
            ast.Alias(
                alias="timestamp",
                expr=ast.Call(name="toStartOfMonth", args=[ast.Field(chain=["revenue_item", "timestamp"])]),
            ),
            ast.Alias(alias="amount", expr=amount),
        ],
        select_from=ast.JoinExpr(
            alias="revenue_item",
            table=revenue_item_table,
        ),
        where=ast.And(
            exprs=[
                ast.Field(chain=["is_recurring"]),
                ast.Call(name="isNotNull", args=[ast.Field(chain=["subscription_id"])]),
                ast.CompareOperation(
                    op=ast.CompareOperationOp.GtEq,
                    left=ast.Field(chain=["timestamp"]),
                    right=start_date_expr,
                ),
                ast.CompareOperation(
                    op=ast.CompareOperationOp.LtEq,
                    left=ast.Field(chain=["timestamp"]),
                    right=end_date_expr,
                ),
            ]
        ),
        order_by=[ast.OrderExpr(expr=ast.Field(chain=["timestamp"]), order="DESC")],
        group_by=[
            ast.Field(chain=["source_label"]),
            ast.Field(chain=["customer_id"]),
            ast.Field(chain=["subscription_id"]),
            ast.Field(chain=["timestamp"]),
        ],
    )

    # We need to look at the subscription "end events" and consider them to be a charge of "0" value
    # to include them in the MRR calculation to "zero" the calculation
    subscription_query = ast.SelectQuery(
        select=[
            ast.Field(chain=["source_label"]),
            ast.Field(chain=["customer_id"]),
            ast.Alias(alias="subscription_id", expr=ast.Field(chain=["id"])),
            ast.Alias(alias="timestamp", expr=ast.Field(chain=["ended_at"])),
            ast.Alias(
                alias="amount",
                expr=ast.Call(
                    name="toDecimal",
                    args=[ast.Constant(value=0), ast.Constant(value=EXCHANGE_RATE_DECIMAL_PRECISION)],
                ),
            ),
        ],
        select_from=ast.JoinExpr(
            table=ast.Field(chain=[subscription_base_query_name]),
        ),
        where=ast.And(
            exprs=[
                ast.CompareOperation(
                    op=ast.CompareOperationOp.GtEq,
                    left=ast.Field(chain=["timestamp"]),
                    right=start_date_expr,
                ),
                ast.CompareOperation(
                    op=ast.CompareOperationOp.LtEq,
                    left=ast.Field(chain=["timestamp"]),
                    right=end_date_expr,
                ),
            ]
        ),
        order_by=[ast.OrderExpr(expr=ast.Field(chain=["timestamp"]), order="DESC")],
    )

    query = ast.SelectQuery(
        select=[
            ast.Alias(alias="source_label", expr=ast.Field(chain=["source_label"])),
            ast.Alias(alias="customer_id", expr=ast.Field(chain=["customer_id"])),
            ast.Alias(alias="subscription_id", expr=ast.Field(chain=["subscription_id"])),
            ast.Alias(
                alias="mrr",
                expr=ast.Call(name="argMax", args=[ast.Field(chain=["amount"]), ast.Field(chain=["timestamp"])]),
            ),
        ],
        select_from=ast.JoinExpr(
            alias="union",
            table=ast.SelectSetQuery.create_from_queries(
                queries=[revenue_item_query, subscription_query],
                set_operator="UNION ALL",
            ),
        ),
        order_by=[
            ast.OrderExpr(expr=ast.Field(chain=["customer_id"]), order="ASC"),
            ast.OrderExpr(expr=ast.Field(chain=["subscription_id"]), order="ASC"),
        ],
        group_by=[
            ast.Field(chain=["source_label"]),
            ast.Field(chain=["customer_id"]),
            ast.Field(chain=["subscription_id"]),
        ],
    )

    return BuiltQuery(key=f"{source.id}-mrr", prefix=prefix, query=query)
