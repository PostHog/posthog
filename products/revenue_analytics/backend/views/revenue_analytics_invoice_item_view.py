from typing import cast

from posthog.hogql import ast
from posthog.models.team.team import Team
from posthog.schema import (
    DatabaseSchemaManagedViewTableKind,
    HogQLQueryModifiers,
)
from posthog.warehouse.models.external_data_source import ExternalDataSource
from posthog.warehouse.models.table import DataWarehouseTable
from posthog.warehouse.models.external_data_schema import ExternalDataSchema
from posthog.models.exchange_rate.sql import EXCHANGE_RATE_DECIMAL_PRECISION
from posthog.hogql.database.models import (
    BooleanDatabaseField,
    DateTimeDatabaseField,
    StringDatabaseField,
    FieldOrTable,
)
from posthog.hogql.database.schema.exchange_rate import (
    convert_currency_call,
)
from products.revenue_analytics.backend.views.currency_helpers import (
    BASE_CURRENCY_FIELDS,
    currency_aware_divider,
    currency_aware_amount,
    is_zero_decimal_in_stripe,
)
from .revenue_analytics_base_view import RevenueAnalyticsBaseView, events_expr_for_team
from posthog.temporal.data_imports.pipelines.stripe.constants import (
    INVOICE_RESOURCE_NAME as STRIPE_INVOICE_RESOURCE_NAME,
)
from posthog.hogql.database.schema.exchange_rate import (
    revenue_comparison_and_value_exprs_for_events,
    currency_expression_for_events,
)

SOURCE_VIEW_SUFFIX = "invoice_item_revenue_view"
EVENTS_VIEW_SUFFIX = "invoice_item_events_revenue_view"

FIELDS: dict[str, FieldOrTable] = {
    "id": StringDatabaseField(name="id"),
    "invoice_item_id": StringDatabaseField(name="invoice_item_id"),
    "source_label": StringDatabaseField(name="source_label"),
    "timestamp": DateTimeDatabaseField(name="timestamp"),  # When we should consider the revenue to be recognized
    "created_at": DateTimeDatabaseField(name="created_at"),  # When the invoice item was created
    "is_recurring": BooleanDatabaseField(name="is_recurring"),
    "product_id": StringDatabaseField(name="product_id"),
    "customer_id": StringDatabaseField(name="customer_id"),
    "invoice_id": StringDatabaseField(name="invoice_id"),
    "subscription_id": StringDatabaseField(name="subscription_id"),
    "session_id": StringDatabaseField(name="session_id"),
    "event_name": StringDatabaseField(name="event_name"),
    "coupon": StringDatabaseField(name="coupon"),
    "coupon_id": StringDatabaseField(name="coupon_id"),
    **BASE_CURRENCY_FIELDS,
}


def extract_json_string(field: str, *path: str) -> ast.Call:
    return ast.Call(
        name="JSONExtractString",
        args=[
            ast.Field(chain=[field]),
            *[ast.Constant(value=p) for p in path],
        ],
    )


def extract_json_uint(field: str, *path: str) -> ast.Call:
    return ast.Call(
        name="JSONExtractUInt",
        args=[
            ast.Field(chain=[field]),
            *[ast.Constant(value=p) for p in path],
        ],
    )


AVERAGE_DAYS_PER_MONTH = 30.44
AVERAGE_DAYS_PER_MONTH_AST_CONSTANT = ast.Constant(value=AVERAGE_DAYS_PER_MONTH)
ONE_AST_CONSTANT = ast.Constant(value=1)


def calculate_months_for_period(start_timestamp: ast.Expr, end_timestamp: ast.Expr) -> ast.Call:
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


class RevenueAnalyticsInvoiceItemView(RevenueAnalyticsBaseView):
    """
    Revenue Analytics Invoice Item View with Revenue Recognition Support

    This view processes Stripe invoice items and applies revenue recognition rules
    for subscription-based billing. Annual and quarterly subscriptions are split
    into monthly periods for proper accounting.

    Example:
        Input: Annual subscription invoice for $1200
        - Invoice ID: in_123
        - Invoice Item ID: ii_456
        - Amount: $1200
        - Period: Jan 1, 2024 - Dec 31, 2024
        - Subscription: Annual (interval=year, interval_count=1)

        Output: 12 monthly invoice items
        - ii_456_0: $100, Period: Jan 1, 2024 - Jan 31, 2024
        - ii_456_1: $100, Period: Feb 1, 2024 - Feb 29, 2024
        - ...
        - ii_456_11: $100, Period: Dec 1, 2024 - Dec 31, 2024
    """

    @classmethod
    def get_database_schema_table_kind(cls) -> DatabaseSchemaManagedViewTableKind:
        return DatabaseSchemaManagedViewTableKind.REVENUE_ANALYTICS_INVOICE_ITEM

    # NOTE: Very similar to charge views, but for individual invoice items
    @classmethod
    def for_events(cls, team: "Team", _modifiers: HogQLQueryModifiers) -> list["RevenueAnalyticsBaseView"]:
        if len(team.revenue_analytics_config.events) == 0:
            return []

        revenue_config = team.revenue_analytics_config
        generic_team_expr = events_expr_for_team(team)

        queries: list[tuple[str, str, ast.SelectQuery]] = []
        for event in revenue_config.events:
            comparison_expr, value_expr = revenue_comparison_and_value_exprs_for_events(
                team, event, do_currency_conversion=False
            )
            _, currency_aware_amount_expr = revenue_comparison_and_value_exprs_for_events(
                team,
                event,
                amount_expr=ast.Field(chain=["currency_aware_amount"]),
            )

            prefix = RevenueAnalyticsBaseView.get_view_prefix_for_event(event.eventName)

            filter_exprs = [
                comparison_expr,
                generic_team_expr,
                ast.CompareOperation(
                    op=ast.CompareOperationOp.NotEq,
                    left=ast.Field(chain=["amount"]),  # refers to the Alias above
                    right=ast.Constant(value=None),
                ),
            ]

            query = ast.SelectQuery(
                select=[
                    ast.Alias(alias="id", expr=ast.Call(name="toString", args=[ast.Field(chain=["uuid"])])),
                    ast.Alias(
                        alias="invoice_item_id", expr=ast.Call(name="toString", args=[ast.Field(chain=["uuid"])])
                    ),
                    ast.Alias(alias="source_label", expr=ast.Constant(value=prefix)),
                    ast.Alias(alias="timestamp", expr=ast.Field(chain=["timestamp"])),
                    ast.Alias(alias="created_at", expr=ast.Field(chain=["timestamp"])),
                    ast.Alias(alias="is_recurring", expr=ast.Constant(value=False)),
                    ast.Alias(alias="product_id", expr=ast.Constant(value=None)),
                    ast.Alias(
                        alias="customer_id", expr=ast.Call(name="toString", args=[ast.Field(chain=["person_id"])])
                    ),
                    ast.Alias(alias="invoice_id", expr=ast.Constant(value=None)),
                    ast.Alias(alias="subscription_id", expr=ast.Constant(value=None)),
                    ast.Alias(
                        alias="session_id", expr=ast.Call(name="toString", args=[ast.Field(chain=["$session_id"])])
                    ),
                    ast.Alias(alias="event_name", expr=ast.Field(chain=["event"])),
                    ast.Alias(alias="coupon", expr=ast.Constant(value=None)),
                    ast.Alias(alias="coupon_id", expr=ast.Constant(value=None)),
                    ast.Alias(alias="original_currency", expr=currency_expression_for_events(revenue_config, event)),
                    ast.Alias(alias="original_amount", expr=value_expr),
                    # Being zero-decimal implies we will NOT divide the original amount by 100
                    # We should only do that if we've tagged the event with `currencyAwareDecimal`
                    # Otherwise, we'll just assume it's a non-zero-decimal currency
                    ast.Alias(
                        alias="enable_currency_aware_divider",
                        expr=is_zero_decimal_in_stripe(ast.Field(chain=["original_currency"]))
                        if event.currencyAwareDecimal
                        else ast.Constant(value=True),
                    ),
                    currency_aware_divider(),
                    currency_aware_amount(),
                    ast.Alias(alias="currency", expr=ast.Constant(value=team.base_currency)),
                    ast.Alias(alias="amount", expr=currency_aware_amount_expr),
                ],
                select_from=ast.JoinExpr(table=ast.Field(chain=["events"])),
                where=ast.And(exprs=filter_exprs),
                order_by=[ast.OrderExpr(expr=ast.Field(chain=["timestamp"]), order="DESC")],
            )

            queries.append((event.eventName, prefix, query))

        return [
            RevenueAnalyticsInvoiceItemView(
                id=RevenueAnalyticsBaseView.get_view_name_for_event(event_name, EVENTS_VIEW_SUFFIX),
                name=RevenueAnalyticsBaseView.get_view_name_for_event(event_name, EVENTS_VIEW_SUFFIX),
                prefix=prefix,
                query=query.to_hogql(),
                fields=FIELDS,
            )
            for event_name, prefix, query in queries
        ]

    @classmethod
    def for_schema_source(
        cls, source: ExternalDataSource, _modifiers: HogQLQueryModifiers
    ) -> list["RevenueAnalyticsBaseView"]:
        # Currently only works for stripe sources
        if not source.source_type == ExternalDataSource.Type.STRIPE:
            return []

        # Get all schemas for the source, avoid calling `filter` and do the filtering on Python-land
        # to avoid n+1 queries
        schemas = source.schemas.all()
        invoice_schema = next((schema for schema in schemas if schema.name == STRIPE_INVOICE_RESOURCE_NAME), None)

        if invoice_schema is None:
            return []

        invoice_schema = cast(ExternalDataSchema, invoice_schema)
        if invoice_schema.table is None:
            return []

        invoice_table = cast(DataWarehouseTable, invoice_schema.table)

        team = invoice_table.team

        prefix = RevenueAnalyticsBaseView.get_view_prefix_for_source(source)

        # Build the query for invoice items with revenue recognition splitting
        query = ast.SelectQuery(
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
                            ast.Constant(value=0),
                        ],
                    ),
                ),
                ast.Field(chain=["product_id"]),
                ast.Field(chain=["customer_id"]),
                ast.Alias(alias="invoice_id", expr=ast.Field(chain=["id"])),
                ast.Field(chain=["subscription_id"]),
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
                        ast.Alias(alias="amount_captured", expr=extract_json_string("data", "amount")),
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
                            expr=calculate_months_for_period(
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
                        # We try and use `period_start` as the timestamp for the invoice item
                        # but if it's not available, we fallback to `created_at`
                        ast.Alias(
                            alias="timestamp",
                            expr=ast.Call(
                                name="ifNull", args=[ast.Field(chain=["period_start"]), ast.Field(chain=["created_at"])]
                            ),
                        ),
                    ],
                    select_from=ast.JoinExpr(table=ast.Field(chain=[invoice_table.name])),
                    # Only include paid invoices because they're the ones that represent revenue
                    where=ast.Field(chain=["paid"]),
                ),
            ),
        )

        return [
            RevenueAnalyticsInvoiceItemView(
                id=str(invoice_table.id),
                name=RevenueAnalyticsBaseView.get_view_name_for_source(source, SOURCE_VIEW_SUFFIX),
                prefix=prefix,
                query=query.to_hogql(),
                fields=FIELDS,
                source_id=str(source.id),
            )
        ]
