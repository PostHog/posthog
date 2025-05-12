from typing import cast

from posthog.hogql import ast
from posthog.models.team.team import Team
from posthog.warehouse.models.external_data_source import ExternalDataSource
from posthog.warehouse.models.table import DataWarehouseTable
from posthog.warehouse.models.external_data_schema import ExternalDataSchema
from posthog.models.exchange_rate.sql import EXCHANGE_RATE_DECIMAL_PRECISION
from posthog.schema import CurrencyCode
from posthog.hogql.database.models import (
    BooleanDatabaseField,
    DateTimeDatabaseField,
    DecimalDatabaseField,
    StringDatabaseField,
    FieldOrTable,
)
from posthog.hogql.database.schema.exchange_rate import (
    revenue_expression_for_events,
    revenue_where_expr_for_events,
    convert_currency_call,
    currency_expression_for_all_events,
)
from .revenue_analytics_base_view import RevenueAnalyticsBaseView
from posthog.temporal.data_imports.pipelines.stripe.constants import (
    CHARGE_RESOURCE_NAME as STRIPE_CHARGE_RESOURCE_NAME,
)

# Keep in sync with `revenueAnalyticsLogic.ts`
SOURCE_VIEW_SUFFIX = "charge_revenue_view"
EVENTS_VIEW_SUFFIX = "events_revenue_view"
STRIPE_CHARGE_SUCCEEDED_STATUS = "succeeded"

# Stripe represents most currencies with integer amounts multiplied by 100,
# since most currencies have its smallest unit as 1/100 of their base unit
# It just so happens that some currencies don't have that concept, so they're listed here
# https://docs.stripe.com/currencies#zero-decimal
ZERO_DECIMAL_CURRENCIES_IN_STRIPE: list[str] = [
    CurrencyCode.BIF.value,
    CurrencyCode.CLP.value,
    CurrencyCode.DJF.value,
    CurrencyCode.GNF.value,
    CurrencyCode.JPY.value,
    CurrencyCode.KMF.value,
    CurrencyCode.KRW.value,
    CurrencyCode.MGA.value,
    CurrencyCode.PYG.value,
    CurrencyCode.RWF.value,
    CurrencyCode.UGX.value,
    CurrencyCode.VND.value,
    CurrencyCode.VUV.value,
    CurrencyCode.XAF.value,
    CurrencyCode.XOF.value,
    CurrencyCode.XPF.value,
]

FIELDS: dict[str, FieldOrTable] = {
    # Helpers so that we can properly join across views when necessary
    # Some of these are here only to power `events` views while others
    # are here to support data warehouse tables, check below for more details
    "id": StringDatabaseField(name="id"),
    "timestamp": DateTimeDatabaseField(name="timestamp"),
    "customer_id": StringDatabaseField(name="customer_id"),
    "session_id": StringDatabaseField(name="session_id"),
    "event_name": StringDatabaseField(name="event_name"),
    # Most important fields
    "currency": StringDatabaseField(name="currency"),
    "amount": DecimalDatabaseField(name="amount"),
    # Mostly helper fields
    "original_currency": StringDatabaseField(name="original_currency"),
    "original_amount": DecimalDatabaseField(name="original_amount"),
    "enable_currency_aware_divider": BooleanDatabaseField(name="enable_currency_aware_divider"),
    "currency_aware_divider": DecimalDatabaseField(name="currency_aware_divider"),
    "currency_aware_amount": DecimalDatabaseField(name="currency_aware_amount"),
}


def is_zero_decimal_in_stripe(field: ast.Field) -> ast.Call:
    return ast.Call(
        name="in",
        args=[field, ast.Constant(value=ZERO_DECIMAL_CURRENCIES_IN_STRIPE)],
    )


def currency_aware_divider() -> ast.Alias:
    return ast.Alias(
        alias="currency_aware_divider",
        expr=ast.Call(
            name="if",
            args=[
                ast.Field(chain=["enable_currency_aware_divider"]),
                ast.Call(
                    name="toDecimal",
                    args=[ast.Constant(value=1), ast.Constant(value=EXCHANGE_RATE_DECIMAL_PRECISION)],
                ),
                ast.Call(
                    name="toDecimal",
                    args=[ast.Constant(value=100), ast.Constant(value=EXCHANGE_RATE_DECIMAL_PRECISION)],
                ),
            ],
        ),
    )


def currency_aware_amount() -> ast.Alias:
    return ast.Alias(
        alias="currency_aware_amount",
        expr=ast.Call(
            name="divideDecimal",
            args=[
                ast.Field(chain=["original_amount"]),
                ast.Field(chain=["currency_aware_divider"]),
            ],
        ),
    )


class RevenueAnalyticsChargeView(RevenueAnalyticsBaseView):
    @staticmethod
    def for_events(team: "Team") -> list["RevenueAnalyticsBaseView"]:
        if len(team.revenue_analytics_config.events) == 0:
            return []

        revenue_config = team.revenue_analytics_config

        currency_aware_event_names = [event.eventName for event in revenue_config.events if event.currencyAwareDecimal]

        query = ast.SelectQuery(
            select=[
                ast.Alias(alias="id", expr=ast.Field(chain=["uuid"])),
                ast.Alias(alias="timestamp", expr=ast.Field(chain=["created_at"])),
                ast.Alias(alias="customer_id", expr=ast.Field(chain=["distinct_id"])),
                ast.Alias(alias="session_id", expr=ast.Call(name="toString", args=[ast.Field(chain=["$session_id"])])),
                ast.Alias(alias="event_name", expr=ast.Field(chain=["event"])),
                ast.Alias(alias="original_currency", expr=currency_expression_for_all_events(revenue_config)),
                ast.Alias(
                    alias="original_amount",
                    expr=revenue_expression_for_events(revenue_config, do_currency_conversion=False),
                ),
                # Being zero-decimal implies we will NOT divide the original amount by 100
                # We should only do that if we've tagged the event with `currencyAwareDecimal`
                # Otherwise, we'll just assume it's a non-zero-decimal currency
                # There's a small optimization here in case NONE of the events have `currencyAwareDecimal`
                # in which case we can just return True for all rows
                ast.Alias(
                    alias="enable_currency_aware_divider",
                    expr=ast.Constant(value=True)
                    if not currency_aware_event_names
                    else ast.Call(
                        name="if",
                        args=[
                            ast.Call(
                                name="in",
                                args=[
                                    ast.Field(chain=["event_name"]),
                                    ast.Constant(value=currency_aware_event_names),
                                ],
                            ),
                            is_zero_decimal_in_stripe(ast.Field(chain=["original_currency"])),
                            ast.Constant(value=True),
                        ],
                    ),
                ),
                currency_aware_divider(),
                currency_aware_amount(),
                ast.Alias(alias="currency", expr=ast.Constant(value=revenue_config.base_currency)),
                ast.Alias(
                    alias="amount",
                    expr=revenue_expression_for_events(
                        revenue_config, amount_expr=ast.Field(chain=["currency_aware_amount"])
                    ),
                ),
            ],
            select_from=ast.JoinExpr(table=ast.Field(chain=["events"])),
            where=ast.And(
                exprs=[
                    revenue_where_expr_for_events(revenue_config),
                    ast.CompareOperation(
                        op=ast.CompareOperationOp.NotEq,
                        left=ast.Field(chain=["amount"]),  # refers to the Alias above
                        right=ast.Constant(value=None),
                    ),
                ]
            ),
            order_by=[ast.OrderExpr(expr=ast.Field(chain=["timestamp"]), order="DESC")],
        )

        return [
            RevenueAnalyticsChargeView(
                id=EVENTS_VIEW_SUFFIX,
                name=EVENTS_VIEW_SUFFIX,
                query=query.to_hogql(),
                fields=FIELDS,
            )
        ]

    @staticmethod
    def for_schema_source(source: ExternalDataSource) -> list["RevenueAnalyticsBaseView"]:
        # Currently only works for stripe sources
        if not source.source_type == ExternalDataSource.Type.STRIPE:
            return []

        # Get all schemas for the source, avoid calling `filter` and do the filtering on Python-land
        # to avoid n+1 queries
        schemas = source.schemas.all()
        charge_schema = next((schema for schema in schemas if schema.name == STRIPE_CHARGE_RESOURCE_NAME), None)
        if charge_schema is None:
            return []

        charge_schema = cast(ExternalDataSchema, charge_schema)
        if charge_schema.table is None:
            return []

        table = cast(DataWarehouseTable, charge_schema.table)
        team = table.team
        revenue_config = team.revenue_analytics_config

        # Even though we need a string query for the view,
        # using an ast allows us to comment what each field means, and
        # avoid manual interpolation of constants, leaving that to the HogQL printer
        query = ast.SelectQuery(
            select=[
                # Base fields to allow insights to work (need `distinct_id` AND `timestamp` fields)
                ast.Alias(alias="id", expr=ast.Field(chain=["id"])),
                ast.Alias(alias="timestamp", expr=ast.Field(chain=["created_at"])),
                # Useful for cross joins
                ast.Alias(alias="customer_id", expr=ast.Field(chain=["customer_id"])),
                # Empty, but required for the `events` view to work
                ast.Alias(alias="session_id", expr=ast.Constant(value=None)),
                ast.Alias(alias="event_name", expr=ast.Constant(value=None)),
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
                ast.Alias(alias="currency", expr=ast.Constant(value=revenue_config.base_currency)),
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
            select_from=ast.JoinExpr(table=ast.Field(chain=[table.name])),
            # Only include succeeded charges because they're the ones that represent revenue
            where=ast.CompareOperation(
                left=ast.Field(chain=["status"]),
                right=ast.Constant(value=STRIPE_CHARGE_SUCCEEDED_STATUS),
                op=ast.CompareOperationOp.Eq,
            ),
        )

        return [
            RevenueAnalyticsChargeView(
                id=str(table.id),
                name=RevenueAnalyticsBaseView.get_view_name_for_source(source, SOURCE_VIEW_SUFFIX),
                query=query.to_hogql(),
                fields=FIELDS,
                source_id=str(source.id),
            )
        ]
