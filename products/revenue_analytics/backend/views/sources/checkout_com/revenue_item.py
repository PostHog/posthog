from posthog.hogql import ast

from products.revenue_analytics.backend.views.core import BuiltQuery, SourceHandle, view_prefix_for_source
from products.revenue_analytics.backend.views.schemas.revenue_item import SCHEMA
from products.revenue_analytics.backend.views.sources.checkout_com.helpers import (
    PAYMENT_ACTION_RESOURCE_NAME,
    PAYMENT_RESOURCE_NAME,
    approved_captures_join_expr,
    approved_captures_where_expr,
    currency_conversion_fields,
    customer_id_expr,
    parse_timestamp,
)


def build(handle: SourceHandle) -> BuiltQuery:
    """
    Revenue Analytics Revenue Item View for Checkout.com

    Checkout.com has no invoices, subscriptions or products, so there is nothing to
    split into billing periods: every approved `Capture` action is a single revenue
    item, the way invoiceless charges are for Stripe. `is_recurring` comes from the
    parent payment's own `payment_type` (e.g. `Recurring`), which is the only recurring
    signal Checkout.com carries; there is no subscription to attach it to.

    The underlying tables sync from the payments search API, which only reaches back
    90 days by default, so this view only covers full history when the source has a
    start date configured.
    """
    source = handle.source
    if source is None:
        raise ValueError("Source is required")

    prefix = view_prefix_for_source(source)

    # Get all schemas for the source, avoid calling `filter` and do the filtering on
    # Python-land to avoid n+1 queries
    schemas = source.schemas.all()
    payments_schema = next((schema for schema in schemas if schema.name == PAYMENT_RESOURCE_NAME), None)
    actions_schema = next((schema for schema in schemas if schema.name == PAYMENT_ACTION_RESOURCE_NAME), None)
    if payments_schema is None or actions_schema is None:
        return BuiltQuery(
            key=str(source.id),  # Using source rather than table because table hasn't been found yet
            prefix=prefix,
            query=ast.SelectQuery.empty(columns=SCHEMA.fields),
            test_comments="no_schema",
        )

    payments_table = payments_schema.table
    actions_table = actions_schema.table
    if payments_table is None or actions_table is None:
        return BuiltQuery(
            key=str(source.id),  # Using source rather than table because table hasn't been found
            prefix=prefix,
            query=ast.SelectQuery.empty(columns=SCHEMA.fields),
            test_comments="no_table",
        )

    query = ast.SelectQuery(
        select=[
            ast.Alias(alias="id", expr=ast.Field(chain=["action", "id"])),
            ast.Alias(alias="invoice_item_id", expr=ast.Field(chain=["action", "id"])),
            ast.Alias(alias="source_label", expr=ast.Constant(value=prefix)),
            # Revenue is recognized when the capture is processed; the payment request
            # time is when the record came into existence
            ast.Alias(alias="timestamp", expr=parse_timestamp(ast.Field(chain=["action", "processed_on"]))),
            ast.Alias(alias="created_at", expr=parse_timestamp(ast.Field(chain=["payment", "requested_on"]))),
            ast.Alias(
                alias="is_recurring",
                expr=ast.Call(
                    name="ifNull",
                    args=[
                        ast.CompareOperation(
                            left=ast.Call(name="lower", args=[ast.Field(chain=["payment", "payment_type"])]),
                            right=ast.Constant(value="recurring"),
                            op=ast.CompareOperationOp.Eq,
                        ),
                        ast.Constant(value=False),
                    ],
                ),
            ),
            ast.Alias(alias="product_id", expr=ast.Constant(value=None)),
            ast.Alias(alias="customer_id", expr=customer_id_expr()),
            ast.Alias(alias="group_0_key", expr=ast.Constant(value=None)),
            ast.Alias(alias="group_1_key", expr=ast.Constant(value=None)),
            ast.Alias(alias="group_2_key", expr=ast.Constant(value=None)),
            ast.Alias(alias="group_3_key", expr=ast.Constant(value=None)),
            ast.Alias(alias="group_4_key", expr=ast.Constant(value=None)),
            ast.Alias(alias="invoice_id", expr=ast.Constant(value=None)),
            ast.Alias(alias="subscription_id", expr=ast.Constant(value=None)),
            ast.Alias(alias="session_id", expr=ast.Constant(value=None)),
            ast.Alias(alias="event_name", expr=ast.Constant(value=None)),
            ast.Alias(alias="coupon", expr=ast.Constant(value=None)),
            ast.Alias(alias="coupon_id", expr=ast.Constant(value=None)),
            *currency_conversion_fields(handle.team),
        ],
        select_from=approved_captures_join_expr(actions_table, payments_table),
        where=approved_captures_where_expr(),
    )

    return BuiltQuery(key=str(payments_table.id), prefix=prefix, query=query)
