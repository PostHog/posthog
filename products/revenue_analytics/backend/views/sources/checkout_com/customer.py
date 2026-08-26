from posthog.hogql import ast

from products.revenue_analytics.backend.views.core import BuiltQuery, SourceHandle, view_prefix_for_source
from products.revenue_analytics.backend.views.schemas.customer import SCHEMA
from products.revenue_analytics.backend.views.sources.checkout_com.helpers import (
    CUSTOMER_RESOURCE_NAME,
    PAYMENT_RESOURCE_NAME,
    extract_json_string_from,
    get_table,
    parse_timestamp,
)
from products.revenue_analytics.backend.views.sources.helpers import get_cohort_expr


def build(handle: SourceHandle) -> BuiltQuery:
    """
    Revenue Analytics Customer View for Checkout.com

    Customers sync as point lookups referenced by payments, so the only timestamp they
    carry is the request time of the payment that referenced them. Checkout.com customer
    records have no address or coupon data, so those fields stay empty.

    The cohort is the month of the customer's earliest synced payment. The payments
    table only reaches back 90 days unless the source has a start date configured, so
    without one the cohort reflects the earliest payment within that window rather than
    the customer's true first charge.
    """
    source = handle.source
    if source is None:
        raise ValueError("Source is required")

    prefix = view_prefix_for_source(source)

    # Get all schemas for the source, avoid calling `filter` and do the filtering on
    # Python-land to avoid n+1 queries
    schemas = source.schemas.all()
    customer_schema = next((schema for schema in schemas if schema.name == CUSTOMER_RESOURCE_NAME), None)
    if customer_schema is None:
        return BuiltQuery(
            key=str(source.id),  # Using source rather than table because table hasn't been found yet
            prefix=prefix,
            query=ast.SelectQuery.empty(columns=SCHEMA.fields),
            test_comments="no_schema",
        )

    customer_table = customer_schema.table
    if customer_table is None:
        return BuiltQuery(
            key=str(source.id),  # Using source rather than table because table hasn't been found
            prefix=prefix,
            query=ast.SelectQuery.empty(columns=SCHEMA.fields),
            test_comments="no_table",
        )

    payments_table = get_table(schemas, PAYMENT_RESOURCE_NAME)

    query = ast.SelectQuery(
        select=[
            ast.Alias(alias="id", expr=ast.Field(chain=["outer", "id"])),
            ast.Alias(alias="source_label", expr=ast.Constant(value=prefix)),
            ast.Alias(
                alias="timestamp",
                expr=parse_timestamp(ast.Field(chain=["outer", "payment_requested_on"])),
            ),
            ast.Alias(alias="name", expr=ast.Field(chain=["name"])),
            ast.Alias(alias="email", expr=ast.Field(chain=["email"])),
            ast.Alias(alias="phone", expr=ast.Field(chain=["phone"])),
            ast.Alias(alias="address", expr=ast.Constant(value=None)),
            ast.Alias(alias="metadata", expr=ast.Field(chain=["metadata"])),
            ast.Alias(alias="country", expr=ast.Constant(value=None)),
            ast.Alias(alias="cohort", expr=ast.Constant(value=None)),
            ast.Alias(alias="initial_coupon", expr=ast.Constant(value=None)),
            ast.Alias(alias="initial_coupon_id", expr=ast.Constant(value=None)),
        ],
        select_from=ast.JoinExpr(
            alias="outer",
            table=ast.Field(chain=[customer_table.name]),
        ),
        order_by=[ast.OrderExpr(expr=ast.Field(chain=["timestamp"]), order="DESC")],
        limit_by=ast.LimitByExpr(n=ast.Constant(value=1), exprs=[ast.Field(chain=["id"])]),
    )

    # If there's a payments table we can generate the cohort entry by looking at the
    # earliest synced payment for each customer
    if payments_table is not None and query.select_from is not None:
        cohort_alias = next(
            (alias for alias in query.select if isinstance(alias, ast.Alias) and alias.alias == "cohort"), None
        )
        if cohort_alias is not None:
            cohort_alias.expr = ast.Field(chain=["cohort"])

            query.select_from.next_join = ast.JoinExpr(
                alias="cohort_inner",
                table=ast.SelectQuery(
                    select=[
                        ast.Alias(
                            alias="customer_id",
                            expr=ast.Call(
                                name="nullIf",
                                args=[
                                    extract_json_string_from(["payment", "customer"], "id"),
                                    ast.Constant(value=""),
                                ],
                            ),
                        ),
                        ast.Alias(
                            alias="cohort",
                            expr=get_cohort_expr("min(parseDateTimeBestEffort(toString(requested_on)))"),
                        ),
                    ],
                    select_from=ast.JoinExpr(alias="payment", table=ast.Field(chain=[payments_table.name])),
                    group_by=[ast.Field(chain=["customer_id"])],
                ),
                join_type="LEFT JOIN",
                constraint=ast.JoinConstraint(
                    constraint_type="ON",
                    expr=ast.CompareOperation(
                        left=ast.Field(chain=["cohort_inner", "customer_id"]),
                        right=ast.Field(chain=["outer", "id"]),
                        op=ast.CompareOperationOp.Eq,
                    ),
                ),
            )

    return BuiltQuery(key=str(customer_table.id), prefix=prefix, query=query)
