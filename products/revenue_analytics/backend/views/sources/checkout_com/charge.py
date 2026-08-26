from posthog.hogql import ast

from products.revenue_analytics.backend.views.core import BuiltQuery, SourceHandle, view_prefix_for_source
from products.revenue_analytics.backend.views.schemas.charge import SCHEMA
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
    Revenue Analytics Charge View for Checkout.com

    Checkout.com has no standalone charge object: a charge is an approved `Capture`
    action on a payment, so this view joins `payment_actions` with `payments` (the
    action carries the captured amount and time; the payment carries the currency and
    customer). Refund actions live in the same table and are deliberately not netted
    here, matching the gross-revenue semantics of the Stripe charge view.

    Both tables sync from the payments search API, which only reaches back 90 days by
    default, so this view only covers full history when the source has a start date
    configured.
    """
    source = handle.source
    if source is None:
        raise ValueError("Source is required")

    prefix = view_prefix_for_source(source)

    # Get all schemas for the source, avoid calling `filter` and do the filtering on Python-land
    # to avoid n+1 queries
    schemas = source.schemas
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
            # Base fields to allow insights to work (need `distinct_id` AND `timestamp` fields)
            ast.Alias(alias="id", expr=ast.Field(chain=["action", "id"])),
            ast.Alias(alias="source_label", expr=ast.Constant(value=prefix)),
            ast.Alias(alias="timestamp", expr=parse_timestamp(ast.Field(chain=["action", "processed_on"]))),
            # Useful for cross joins
            ast.Alias(alias="customer_id", expr=customer_id_expr()),
            # Checkout.com has no invoices; empty but required for the merged views to work
            ast.Alias(alias="invoice_id", expr=ast.Constant(value=None)),
            ast.Alias(alias="session_id", expr=ast.Constant(value=None)),
            ast.Alias(alias="event_name", expr=ast.Constant(value=None)),
            *currency_conversion_fields(handle.team),
        ],
        select_from=approved_captures_join_expr(actions_table, payments_table),
        where=approved_captures_where_expr(),
    )

    return BuiltQuery(key=str(actions_table.id), prefix=prefix, query=query)
