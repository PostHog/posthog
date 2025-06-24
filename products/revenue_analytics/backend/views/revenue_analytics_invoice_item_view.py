from typing import cast

from posthog.hogql import ast
from posthog.models.team.team import Team
from posthog.schema import DatabaseSchemaManagedViewTableKind
from posthog.warehouse.models.external_data_source import ExternalDataSource
from posthog.warehouse.models.table import DataWarehouseTable
from posthog.warehouse.models.external_data_schema import ExternalDataSchema
from posthog.models.exchange_rate.sql import EXCHANGE_RATE_DECIMAL_PRECISION
from posthog.hogql.database.models import (
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
from .revenue_analytics_base_view import RevenueAnalyticsBaseView, events_exprs_for_team
from posthog.temporal.data_imports.pipelines.stripe.constants import (
    INVOICE_RESOURCE_NAME as STRIPE_INVOICE_RESOURCE_NAME,
)
from posthog.hogql.database.schema.exchange_rate import (
    revenue_comparison_and_value_exprs_for_events,
    currency_expression_for_events,
)

SOURCE_VIEW_SUFFIX = "invoice_item_revenue_view"
EVENTS_VIEW_SUFFIX = "invoice_item_revenue_view_events"

FIELDS: dict[str, FieldOrTable] = {
    "id": StringDatabaseField(name="id"),
    "source_label": StringDatabaseField(name="source_label"),
    "timestamp": DateTimeDatabaseField(name="timestamp"),
    "product_id": StringDatabaseField(name="product_id"),
    "customer_id": StringDatabaseField(name="customer_id"),
    "invoice_id": StringDatabaseField(name="invoice_id"),
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


class RevenueAnalyticsInvoiceItemView(RevenueAnalyticsBaseView):
    @classmethod
    def get_database_schema_table_kind(cls) -> DatabaseSchemaManagedViewTableKind:
        return DatabaseSchemaManagedViewTableKind.REVENUE_ANALYTICS_INVOICE_ITEM

    # NOTE: Very similar to charge views, but for individual invoice items
    @classmethod
    def for_events(cls, team: "Team") -> list["RevenueAnalyticsBaseView"]:
        if len(team.revenue_analytics_config.events) == 0:
            return []

        revenue_config = team.revenue_analytics_config
        generic_team_exprs = events_exprs_for_team(team)

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
                *generic_team_exprs,
                ast.CompareOperation(
                    op=ast.CompareOperationOp.NotEq,
                    left=ast.Field(chain=["amount"]),  # refers to the Alias above
                    right=ast.Constant(value=None),
                ),
            ]

            query = ast.SelectQuery(
                select=[
                    ast.Alias(alias="id", expr=ast.Call(name="toString", args=[ast.Field(chain=["uuid"])])),
                    ast.Alias(alias="source_label", expr=ast.Constant(value=prefix)),
                    ast.Alias(alias="timestamp", expr=ast.Field(chain=["timestamp"])),
                    ast.Alias(alias="product_id", expr=ast.Constant(value=None)),
                    ast.Alias(alias="customer_id", expr=ast.Field(chain=["distinct_id"])),
                    ast.Alias(
                        alias="invoice_id", expr=ast.Constant(value=None)
                    ),  # Helpful for sources, not helpful for events
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
    def for_schema_source(cls, source: ExternalDataSource) -> list["RevenueAnalyticsBaseView"]:
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

        # Even though we need a string query for the view,
        # using an ast allows us to comment what each field means, and
        # avoid manual interpolation of constants, leaving that to the HogQL printer
        query = ast.SelectQuery(
            select=[
                # Base fields to allow insights to work (need `distinct_id` AND `timestamp` fields)
                ast.Alias(alias="id", expr=ast.Field(chain=["invoice_item_id"])),
                ast.Alias(alias="source_label", expr=ast.Constant(value=prefix)),
                ast.Alias(alias="timestamp", expr=ast.Field(chain=["created_at"])),
                ast.Field(chain=["product_id"]),
                ast.Field(chain=["customer_id"]),
                ast.Alias(alias="invoice_id", expr=ast.Field(chain=["id"])),
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
            # Heavy work for this query is done here in the subquery
            # by exploding the `lines.data[].price.product` field
            select_from=ast.JoinExpr(
                alias="invoice",
                table=ast.SelectQuery(
                    select=[
                        ast.Field(chain=["id"]),
                        ast.Field(chain=["created_at"]),
                        ast.Field(chain=["customer_id"]),
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
