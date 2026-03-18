from typing import cast

from posthog.hogql import ast
from posthog.hogql.database.schema.exchange_rate import EXCHANGE_RATE_DECIMAL_PRECISION, convert_currency_call
from posthog.hogql.parser import parse_expr

from posthog.temporal.data_imports.sources.stripe.constants import (
    CHARGE_RESOURCE_NAME as STRIPE_CHARGE_RESOURCE_NAME,
    INVOICE_RESOURCE_NAME as STRIPE_INVOICE_RESOURCE_NAME,
)

from products.data_warehouse.backend.models.table import DataWarehouseTable
from products.revenue_analytics.backend.views.core import BuiltQuery, SourceHandle, view_prefix_for_source
from products.revenue_analytics.backend.views.schemas.revenue_item import SCHEMA
from products.revenue_analytics.backend.views.sources.helpers import (
    currency_aware_amount,
    currency_aware_divider,
    extract_json_string,
    extract_json_uint,
    is_zero_decimal_in_stripe,
)

AVERAGE_DAYS_PER_MONTH = 30.44
AVERAGE_DAYS_PER_MONTH_AST_CONSTANT = ast.Constant(value=AVERAGE_DAYS_PER_MONTH)
ONE_AST_CONSTANT = ast.Constant(value=1)


def _calculate_months_for_period(start_timestamp: ast.Expr, end_timestamp: ast.Expr) -> ast.Call:
    """
    Calculates the number of months between start and end timestamps using day-based calculation
    with rounding for more accurate revenue recognition.

    Examples:
        - Jan 1 -> Jan 7 (6 days): round(6/30.44) = 0 months (handled by `greatest` case, becomes 1)
        - Jan 1 → Jan 31 (30 days): round(30/30.44) = 1 month
        - Jan 1 → Feb 1 (31 days): round(31/30.44) = 1 month
        - Jan 1 → Mar 1 (60 days): round(60/30.44) = 2 months
        - Jan 1 → Dec 31 (365 days): round(365/30.44) = 12 months
        - Jan 8 → Feb 9 (32 days): round(32/30.44) = 1 month
        - Jan 1 → Feb 15 (45 days): round(45/30.44) = 1 month
        - Jan 1 → Feb 20 (50 days): round(50/30.44) = 2 months
        - Jan 1 → Mar 15 (74 days): round(74/30.44) = 2 months

    This is the same calculation used in generate_monthly_periods but returns just the count
    for use in amount splitting and filtering.
    """
    return ast.Call(
        name="greatest",
        args=[
            ast.Call(
                name="_toInt16",
                args=[
                    ast.Call(
                        name="round",
                        args=[
                            ast.Call(
                                name="divide",
                                args=[
                                    ast.Call(
                                        name="dateDiff",
                                        args=[
                                            ast.Constant(value="day"),
                                            start_timestamp,
                                            end_timestamp,
                                        ],
                                    ),
                                    AVERAGE_DAYS_PER_MONTH_AST_CONSTANT,
                                ],
                            ),
                        ],
                    )
                ],
            ),
            ONE_AST_CONSTANT,
        ],
    )


def build(handle: SourceHandle) -> BuiltQuery:
    """
    Revenue Analytics Revenue Item View with Revenue Recognition Support

    This view processes Stripe invoice items and applies revenue recognition rules
    for subscription-based billing. Annual and quarterly subscriptions are split
    into monthly periods for proper accounting. It will also include invoiceless
    charges that don't have an invoice.

    Example:
        Input: Annual subscription invoice for $1200
        - Invoice ID: in_123
        - Invoice Item ID: ii_456
        - Amount: $1200
        - Period: Jan 1, 2024 - Dec 31, 2024
        - Subscription: Annual (interval=year, interval_count=1)

        Output: 12 monthly revenue items
        - ii_456_0: $100, Period: Jan 1, 2024 - Jan 31, 2024
        - ii_456_1: $100, Period: Feb 1, 2024 - Feb 29, 2024
        - ...
        - ii_456_11: $100, Period: Dec 1, 2024 - Dec 31, 2024
    """
    source = handle.source
    if source is None:
        raise ValueError("Source is required")

    prefix = view_prefix_for_source(source)

    # Get all schemas for the source, avoid calling `filter` and do the filtering on Python-land
    # to avoid n+1 queries
    schemas = source.schemas.all()
    invoice_schema = next((schema for schema in schemas if schema.name == STRIPE_INVOICE_RESOURCE_NAME), None)
    charge_schema = next((schema for schema in schemas if schema.name == STRIPE_CHARGE_RESOURCE_NAME), None)

    if invoice_schema is None and charge_schema is None:
        return BuiltQuery(
            key=str(source.id),  # Using source rather than table because table hasn't been found yet
            prefix=prefix,
            query=ast.SelectQuery.empty(columns=SCHEMA.fields),
            test_comments="no_schema",
        )

    invoice_table: DataWarehouseTable | None = None
    charge_table: DataWarehouseTable | None = None

    if invoice_schema is not None and invoice_schema.table is not None:
        invoice_table = cast(DataWarehouseTable, invoice_schema.table)

    if charge_schema is not None and charge_schema.table is not None:
        charge_table = cast(DataWarehouseTable, charge_schema.table)

    if invoice_table is not None:
        team = invoice_table.team
    elif charge_table is not None:
        team = charge_table.team
    else:
        return BuiltQuery(
            key=str(source.id),  # Using source rather than table because table hasn't been found
            prefix=prefix,
            query=ast.SelectQuery.empty(columns=SCHEMA.fields),
            test_comments="no_table",
        )

    # Build the query for invoice items with revenue recognition splitting
    invoice_item_query: ast.SelectQuery | None = None
    if invoice_table is not None:
        invoice_item_query = ast.SelectQuery(
            select=[
                # Generate unique ID for each month by appending the month index
                # in case there are many months, or else just include the `invoice_item_id`
                ast.Alias(
                    alias="id",
                    expr=ast.Call(
                        name="if",
                        args=[
                            ast.CompareOperation(
                                op=ast.CompareOperationOp.Gt,
                                left=ast.Field(chain=["period_months"]),
                                right=ast.Constant(value=1),
                            ),
                            ast.Call(
                                name="concat",
                                args=[
                                    ast.Field(chain=["invoice_item_id"]),
                                    ast.Constant(value="_"),
                                    ast.Call(name="toString", args=[ast.Field(chain=["month_index"])]),
                                ],
                            ),
                            ast.Field(chain=["invoice_item_id"]),
                        ],
                    ),
                ),
                ast.Alias(alias="invoice_item_id", expr=ast.Field(chain=["invoice_item_id"])),
                ast.Alias(alias="source_label", expr=ast.Constant(value=prefix)),
                # Increment timestamp by month index for each generated row
                ast.Alias(
                    alias="timestamp",
                    expr=ast.Call(
                        name="addMonths",
                        args=[
                            ast.Field(chain=["timestamp"]),
                            ast.Field(chain=["month_index"]),
                        ],
                    ),
                ),
                ast.Alias(alias="created_at", expr=ast.Field(chain=["created_at"])),
                ast.Alias(
                    alias="is_recurring",
                    expr=ast.Call(
                        name="ifNull",
                        args=[
                            ast.Call(
                                name="notEmpty",
                                args=[ast.Field(chain=["subscription_id"])],
                            ),
                            ast.Constant(value=False),
                        ],
                    ),
                ),
                ast.Alias(alias="product_id", expr=ast.Field(chain=["product_id"])),
                ast.Alias(alias="customer_id", expr=ast.Field(chain=["customer_id"])),
                ast.Alias(alias="group_0_key", expr=ast.Constant(value=None)),
                ast.Alias(alias="group_1_key", expr=ast.Constant(value=None)),
                ast.Alias(alias="group_2_key", expr=ast.Constant(value=None)),
                ast.Alias(alias="group_3_key", expr=ast.Constant(value=None)),
                ast.Alias(alias="group_4_key", expr=ast.Constant(value=None)),
                ast.Alias(alias="invoice_id", expr=ast.Field(chain=["invoice", "id"])),
                ast.Alias(alias="subscription_id", expr=ast.Field(chain=["subscription_id"])),
                ast.Alias(alias="session_id", expr=ast.Constant(value=None)),
                ast.Alias(alias="event_name", expr=ast.Constant(value=None)),
                ast.Alias(alias="coupon", expr=extract_json_string("discount", "coupon", "name")),
                ast.Alias(alias="coupon_id", expr=extract_json_string("discount", "coupon", "id")),
                # Compute the original currency, converting to uppercase to match the currency code in the `exchange_rate` table
                ast.Alias(
                    alias="original_currency",
                    expr=ast.Call(name="upper", args=[ast.Field(chain=["currency"])]),
                ),
                # Compute the original amount in the original currency
                # by looking at the captured amount, effectively ignoring refunded value
                ast.Alias(
                    alias="original_amount",
                    expr=ast.Call(
                        name="toDecimal",
                        args=[
                            ast.Field(chain=["amount_captured"]),
                            ast.Constant(value=EXCHANGE_RATE_DECIMAL_PRECISION),
                        ],
                    ),
                ),
                # Compute whether the original currency is a zero-decimal currency
                # by comparing it against a list of known zero-decimal currencies
                # in Stripe's API
                ast.Alias(
                    alias="enable_currency_aware_divider",
                    expr=is_zero_decimal_in_stripe(ast.Field(chain=["original_currency"])),
                ),
                # Compute the amount decimal divider, which is 1 for zero-decimal currencies and 100 for others
                # This is used to convert the original amount to the adjusted amount
                currency_aware_divider(),
                # Compute the adjusted original amount, which is the original amount divided by the amount decimal divider
                currency_aware_amount(),
                # Expose the base/converted currency, which is the base currency from the team's revenue config
                ast.Alias(alias="currency", expr=ast.Constant(value=team.base_currency)),
                # Convert the adjusted original amount to the base currency and split by period_months
                ast.Alias(
                    alias="amount",
                    expr=ast.Call(
                        name="divideDecimal",
                        args=[
                            convert_currency_call(
                                amount=ast.Field(chain=["currency_aware_amount"]),
                                currency_from=ast.Field(chain=["original_currency"]),
                                currency_to=ast.Field(chain=["currency"]),
                                timestamp=ast.Call(
                                    name="_toDate",
                                    args=[
                                        ast.Call(
                                            name="ifNull",
                                            args=[
                                                ast.Field(chain=["timestamp"]),
                                                ast.Call(name="toDateTime", args=[ast.Constant(value=0)]),
                                            ],
                                        ),
                                    ],
                                ),
                            ),
                            ast.Call(
                                name="toDecimal",
                                args=[
                                    ast.Field(chain=["period_months"]),
                                    ast.Constant(value=EXCHANGE_RATE_DECIMAL_PRECISION),
                                ],
                            ),
                        ],
                    ),
                ),
            ],
            # Heavy work for this query is done here in the subquery
            # by exploding the `lines.data[].price.product` field
            select_from=ast.JoinExpr(
                alias="invoice",
                table=ast.SelectQuery(
                    select=[
                        ast.Field(chain=["id"]),
                        ast.Field(chain=["created_at"]),
                        ast.Field(chain=["customer_id"]),
                        ast.Field(chain=["subscription_id"]),
                        ast.Field(chain=["discount"]),
                        # Explode the `lines.data` field into an individual row per item
                        ast.Alias(
                            alias="data",
                            expr=ast.Call(
                                name="arrayJoin",
                                args=[
                                    ast.Call(
                                        name="JSONExtractArrayRaw",
                                        args=[
                                            ast.Call(name="assumeNotNull", args=[ast.Field(chain=["lines", "data"])])
                                        ],
                                    ),
                                ],
                            ),
                        ),
                        ast.Alias(alias="invoice_item_id", expr=extract_json_string("data", "id")),
                        # Make sure we're considering discounts here
                        ast.Alias(alias="amount_before_discount", expr=extract_json_uint("data", "amount")),
                        ast.Alias(
                            alias="discount_amount",
                            expr=parse_expr(
                                # `data.discount_amounts` looks like `[{"amount": 100, ...}, {"amount": 200, ...}, ...]`, sum all amounts
                                "coalesce(arraySum(arrayMap(x -> JSONExtractInt(x, 'amount'), JSONExtractArrayRaw(data, 'discount_amounts'))), 0)"
                            ),
                        ),
                        ast.Alias(
                            alias="amount_captured",
                            expr=ast.Call(
                                name="greatest",
                                args=[
                                    ast.ArithmeticOperation(
                                        op=ast.ArithmeticOperationOp.Sub,
                                        left=ast.Field(chain=["amount_before_discount"]),
                                        right=ast.Field(chain=["discount_amount"]),
                                    ),
                                    ast.Constant(value=0),
                                ],
                            ),
                        ),
                        ast.Alias(alias="currency", expr=extract_json_string("data", "currency")),
                        ast.Alias(alias="product_id", expr=extract_json_string("data", "price", "product")),
                        # Extract period information for revenue recognition
                        ast.Alias(
                            alias="period_start",
                            expr=ast.Call(
                                name="fromUnixTimestamp", args=[extract_json_uint("data", "period", "start")]
                            ),
                        ),
                        ast.Alias(
                            alias="period_end",
                            expr=ast.Call(name="fromUnixTimestamp", args=[extract_json_uint("data", "period", "end")]),
                        ),
                        ast.Alias(
                            alias="period_months",
                            expr=_calculate_months_for_period(
                                start_timestamp=ast.Call(
                                    name="ifNull",
                                    args=[ast.Field(chain=["period_start"]), ast.Field(chain=["created_at"])],
                                ),
                                end_timestamp=ast.Call(
                                    name="ifNull",
                                    args=[ast.Field(chain=["period_end"]), ast.Field(chain=["created_at"])],
                                ),
                            ),
                        ),
                        # Generate sequence from 0 to period_months-1 for arrayJoin
                        ast.Alias(
                            alias="month_index",
                            expr=ast.Call(
                                name="arrayJoin",
                                args=[
                                    ast.Call(
                                        name="range",
                                        args=[
                                            ast.Constant(value=0),
                                            ast.Field(chain=["period_months"]),
                                        ],
                                    ),
                                ],
                            ),
                        ),
                        # We try and use `period_start` as the timestamp for the revenue item
                        # but if it's not available, we fallback to `created_at`
                        ast.Alias(
                            alias="timestamp",
                            expr=ast.Call(
                                name="ifNull",
                                args=[ast.Field(chain=["period_start"]), ast.Field(chain=["created_at"])],
                            ),
                        ),
                    ],
                    select_from=ast.JoinExpr(table=ast.Field(chain=[invoice_table.name])),
                    # Only include paid invoices because they're the ones that represent revenue
                    where=ast.Field(chain=["paid"]),
                ),
            ),
        )

    # Include charges that don't have an invoice unless explictly disabled
    invoiceless_charges_query: ast.SelectQuery | None = None
    if charge_table is not None and source.revenue_analytics_config_safe.include_invoiceless_charges:
        invoiceless_charges_query = ast.SelectQuery(
            select=[
                ast.Alias(alias="id", expr=ast.Field(chain=["id"])),
                ast.Alias(alias="invoice_item_id", expr=ast.Field(chain=["id"])),
                ast.Alias(alias="source_label", expr=ast.Constant(value=prefix)),
                ast.Alias(alias="timestamp", expr=ast.Field(chain=["created_at"])),
                ast.Alias(alias="created_at", expr=ast.Field(chain=["created_at"])),
                ast.Alias(alias="is_recurring", expr=ast.Constant(value=False)),
                ast.Alias(alias="product_id", expr=ast.Constant(value=None)),
                ast.Alias(alias="customer_id", expr=ast.Field(chain=["customer_id"])),
                ast.Alias(alias="group_0_key", expr=ast.Constant(value=None)),
                ast.Alias(alias="group_1_key", expr=ast.Constant(value=None)),
                ast.Alias(alias="group_2_key", expr=ast.Constant(value=None)),
                ast.Alias(alias="group_3_key", expr=ast.Constant(value=None)),
                ast.Alias(alias="group_4_key", expr=ast.Constant(value=None)),
                ast.Alias(alias="invoice_id", expr=ast.Field(chain=["invoice_id"])),  # Will be empty
                ast.Alias(alias="subscription_id", expr=ast.Constant(value=None)),
                ast.Alias(alias="session_id", expr=ast.Constant(value=None)),
                ast.Alias(alias="event_name", expr=ast.Constant(value=None)),
                ast.Alias(alias="coupon", expr=ast.Constant(value=None)),
                ast.Alias(alias="coupon_id", expr=ast.Constant(value=None)),
                # Compute the original currency, converting to uppercase to match the currency code in the `exchange_rate` table
                ast.Alias(
                    alias="original_currency",
                    expr=ast.Call(name="upper", args=[ast.Field(chain=["currency"])]),
                ),
                # Compute the original amount in the original currency
                # by looking at the captured amount, effectively ignoring refunded value
                ast.Alias(
                    alias="original_amount",
                    expr=ast.Call(
                        name="toDecimal",
                        args=[
                            ast.Field(chain=["amount_captured"]),
                            ast.Constant(value=EXCHANGE_RATE_DECIMAL_PRECISION),
                        ],
                    ),
                ),
                # Compute whether the original currency is a zero-decimal currency
                # by comparing it against a list of known zero-decimal currencies
                # in Stripe's API
                ast.Alias(
                    alias="enable_currency_aware_divider",
                    expr=is_zero_decimal_in_stripe(ast.Field(chain=["original_currency"])),
                ),
                # Compute the amount decimal divider, which is 1 for zero-decimal currencies and 100 for others
                # This is used to convert the original amount to the adjusted amount
                currency_aware_divider(),
                # Compute the adjusted original amount, which is the original amount divided by the amount decimal divider
                currency_aware_amount(),
                # Expose the base/converted currency, which is the base currency from the team's revenue config
                ast.Alias(alias="currency", expr=ast.Constant(value=team.base_currency)),
                # Convert the adjusted original amount to the base currency
                ast.Alias(
                    alias="amount",
                    expr=convert_currency_call(
                        amount=ast.Field(chain=["currency_aware_amount"]),
                        currency_from=ast.Field(chain=["original_currency"]),
                        currency_to=ast.Field(chain=["currency"]),
                        timestamp=ast.Call(
                            name="_toDate",
                            args=[
                                ast.Call(
                                    name="ifNull",
                                    args=[
                                        ast.Field(chain=["timestamp"]),
                                        ast.Call(name="toDateTime", args=[ast.Constant(value=0)]),
                                    ],
                                ),
                            ],
                        ),
                    ),
                ),
            ],
            # Simple query, simply refer to the `stripe_charge` table
            select_from=ast.JoinExpr(table=ast.Field(chain=[charge_table.name])),
            # Only include succeeded charges because they're the ones that represent revenue
            # and only include charges that don't have an invoice (i.e. one-time charges via Payment Intents)
            where=ast.And(
                exprs=[
                    ast.Or(
                        exprs=[
                            ast.Call(name="isNull", args=[ast.Field(chain=["invoice_id"])]),
                            ast.Call(name="empty", args=[ast.Field(chain=["invoice_id"])]),
                        ]
                    ),
                    ast.CompareOperation(
                        left=ast.Field(chain=["status"]),
                        right=ast.Constant(value="succeeded"),
                        op=ast.CompareOperationOp.Eq,
                    ),
                ]
            ),
        )

    # Combine the queries into a single query
    queries: list[ast.SelectQuery] = [
        query for query in [invoice_item_query, invoiceless_charges_query] if query is not None
    ]
    if len(queries) == 0:
        return BuiltQuery(key=f"{prefix}.no_query", prefix=prefix, query=ast.SelectQuery.empty(columns=SCHEMA.fields))

    # Very cumbersome, but mypy won't be happy otherwise
    if invoice_table is not None:
        id = invoice_table.id
    elif charge_table is not None:
        id = charge_table.id
    else:
        id = None

    return BuiltQuery(
        key=str(id),
        prefix=prefix,
        query=ast.SelectSetQuery.create_from_queries(queries, set_operator="UNION ALL"),
    )
