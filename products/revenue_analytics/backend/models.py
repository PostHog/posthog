from typing import cast, Optional

from posthog.hogql import ast
from posthog.models.team.team import Team
from posthog.warehouse.models.external_data_source import ExternalDataSource
from posthog.warehouse.models.table import DataWarehouseTable
from posthog.warehouse.models.external_data_schema import ExternalDataSchema
from posthog.models.exchange_rate.sql import EXCHANGE_RATE_DECIMAL_PRECISION
from posthog.schema import CurrencyCode
from posthog.hogql.database.models import (
    SavedQuery,
    BooleanDatabaseField,
    DateTimeDatabaseField,
    DecimalDatabaseField,
    StringDatabaseField,
    FieldOrTable,
)
from posthog.hogql.database.schema.exchange_rate import (
    DEFAULT_CURRENCY,
    revenue_expression_for_events,
    revenue_where_expr_for_events,
    convert_currency_call,
    currency_expression_for_all_events,
)


from typing import TYPE_CHECKING

if TYPE_CHECKING:
    pass

STRIPE_DATA_WAREHOUSE_CHARGE_IDENTIFIER = "Charge"
STRIPE_DATA_WAREHOUSE_CUSTOMER_IDENTIFIER = "Customer"
STRIPE_CHARGE_SUCCEEDED_STATUS = "succeeded"

# Keep in sync with `revenueAnalyticsLogic.ts`
CHARGE_REVENUE_VIEW_SUFFIX = "charge_revenue_view"
CUSTOMER_REVENUE_VIEW_SUFFIX = "customer_revenue_view"
EVENTS_VIEW_SUFFIX = "events_revenue_view"

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

CHARGE_FIELDS: dict[str, FieldOrTable] = {
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
    "currency_is_zero_decimal": BooleanDatabaseField(name="currency_is_zero_decimal"),
    "amount_decimal_divider": DecimalDatabaseField(name="amount_decimal_divider"),
    "adjusted_original_amount": DecimalDatabaseField(name="adjusted_original_amount"),
}

CUSTOMER_FIELDS: dict[str, FieldOrTable] = {
    "id": StringDatabaseField(name="id"),
    "timestamp": DateTimeDatabaseField(name="timestamp"),
    "name": StringDatabaseField(name="name"),
    "email": StringDatabaseField(name="email"),
    "phone": StringDatabaseField(name="phone"),
}


def is_zero_decimal(field: ast.Field) -> ast.Alias:
    return ast.Alias(
        alias="currency_is_zero_decimal",
        expr=ast.Call(
            name="in",
            args=[field, ast.Constant(value=ZERO_DECIMAL_CURRENCIES_IN_STRIPE)],
        ),
    )


def amount_decimal_divider() -> ast.Alias:
    return ast.Alias(
        alias="amount_decimal_divider",
        expr=ast.Call(
            name="if",
            args=[
                ast.Field(chain=["currency_is_zero_decimal"]),
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


def adjusted_original_amount() -> ast.Alias:
    return ast.Alias(
        alias="adjusted_original_amount",
        expr=ast.Call(
            name="divideDecimal",
            args=[
                ast.Field(chain=["original_amount"]),
                ast.Field(chain=["amount_decimal_divider"]),
            ],
        ),
    )


class RevenueAnalyticsRevenueView(SavedQuery):
    source_id: Optional[str] = None
    is_events_view: bool = False

    @staticmethod
    def for_events(team: "Team") -> list["RevenueAnalyticsRevenueView"]:
        if len(team.revenue_config.events or []) == 0:
            return []

        revenue_config = team.revenue_config
        base_currency = (revenue_config.baseCurrency or DEFAULT_CURRENCY).value

        query = ast.SelectQuery(
            select=[
                ast.Alias(alias="id", expr=ast.Field(chain=["uuid"])),
                ast.Alias(alias="timestamp", expr=ast.Field(chain=["created_at"])),
                ast.Alias(alias="customer_id", expr=ast.Field(chain=["distinct_id"])),
                ast.Alias(alias="session_id", expr=ast.Field(chain=["properties", "$session_id"])),
                ast.Alias(alias="event_name", expr=ast.Field(chain=["event"])),
                ast.Alias(alias="original_currency", expr=currency_expression_for_all_events(revenue_config)),
                ast.Alias(
                    alias="original_amount",
                    expr=revenue_expression_for_events(revenue_config, do_currency_conversion=False),
                ),
                is_zero_decimal(ast.Field(chain=["original_currency"])),
                amount_decimal_divider(),
                adjusted_original_amount(),
                ast.Alias(alias="currency", expr=ast.Constant(value=base_currency)),
                ast.Alias(
                    alias="amount",
                    expr=revenue_expression_for_events(
                        revenue_config, amount_expr=ast.Field(chain=["adjusted_original_amount"])
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
            RevenueAnalyticsRevenueView(
                id=EVENTS_VIEW_SUFFIX,
                name=EVENTS_VIEW_SUFFIX,
                query=query.to_hogql(),
                fields=CHARGE_FIELDS,
                is_events_view=True,
            )
        ]

    @staticmethod
    def for_schema_source(source: ExternalDataSource) -> list["RevenueAnalyticsRevenueView"]:
        # Currently only works for stripe sources
        if not source.source_type == ExternalDataSource.Type.STRIPE:
            return []

        views: list[RevenueAnalyticsRevenueView] = []
        schema_dict = {schema.name: schema for schema in source.schemas.all()}

        charge_schema = schema_dict.get(STRIPE_DATA_WAREHOUSE_CHARGE_IDENTIFIER)
        if charge_schema is not None:
            charge_schema = cast(ExternalDataSchema, charge_schema)
            if charge_schema.table is not None:
                table = cast(DataWarehouseTable, charge_schema.table)
                views.append(RevenueAnalyticsRevenueView.__for_charge_table(source, table))

        customer_schema = schema_dict.get(STRIPE_DATA_WAREHOUSE_CUSTOMER_IDENTIFIER)
        if customer_schema is not None:
            customer_schema = cast(ExternalDataSchema, customer_schema)
            if customer_schema.table is not None:
                table = cast(DataWarehouseTable, customer_schema.table)
                views.append(RevenueAnalyticsRevenueView.__for_customer_table(source, table))

        return views

    @staticmethod
    def __get_view_name_for_source(source: ExternalDataSource, view_name: str) -> str:
        if not source.prefix:
            return f"{source.source_type.lower()}.{view_name}"
        else:
            prefix = source.prefix.strip("_")
            return f"{source.source_type.lower()}.{prefix}.{view_name}"

    @staticmethod
    def __for_charge_table(source: ExternalDataSource, table: DataWarehouseTable) -> "RevenueAnalyticsRevenueView":
        team = table.team
        revenue_config = team.revenue_config

        base_currency = (revenue_config.baseCurrency or DEFAULT_CURRENCY).value

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
                # by comparing it against a list of zero-decimal currencies
                is_zero_decimal(ast.Field(chain=["original_currency"])),
                # Compute the amount decimal divider, which is 1 for zero-decimal currencies and 100 for others
                # This is used to convert the original amount to the adjusted amount
                amount_decimal_divider(),
                # Compute the adjusted original amount, which is the original amount divided by the amount decimal divider
                adjusted_original_amount(),
                # Expose the base/converted currency, which is the base currency from the team's revenue config
                ast.Alias(alias="currency", expr=ast.Constant(value=base_currency)),
                # Convert the adjusted original amount to the base currency
                ast.Alias(
                    alias="amount",
                    expr=convert_currency_call(
                        amount=ast.Field(chain=["adjusted_original_amount"]),
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

        return RevenueAnalyticsRevenueView(
            id=str(table.id),
            name=RevenueAnalyticsRevenueView.__get_view_name_for_source(source, CHARGE_REVENUE_VIEW_SUFFIX),
            query=query.to_hogql(),
            source_id=str(source.id),
            fields=CHARGE_FIELDS,
        )

    @staticmethod
    def __for_customer_table(source: ExternalDataSource, table: DataWarehouseTable) -> "RevenueAnalyticsRevenueView":
        # Even though we need a string query for the view,
        # using an ast allows us to comment what each field means, and
        # avoid manual interpolation of constants, leaving that to the HogQL printer
        #
        # These are all pretty basic, they're simply here to allow future extensions
        # once we start adding fields from sources other than Stripe
        query = ast.SelectQuery(
            select=[
                ast.Alias(alias="id", expr=ast.Field(chain=["id"])),
                ast.Alias(alias="timestamp", expr=ast.Field(chain=["created_at"])),
                ast.Alias(alias="name", expr=ast.Field(chain=["name"])),
                ast.Alias(alias="email", expr=ast.Field(chain=["email"])),
                ast.Alias(alias="phone", expr=ast.Field(chain=["phone"])),
            ],
            select_from=ast.JoinExpr(table=ast.Field(chain=[table.name])),
        )

        return RevenueAnalyticsRevenueView(
            id=str(table.id),
            name=RevenueAnalyticsRevenueView.__get_view_name_for_source(source, CUSTOMER_REVENUE_VIEW_SUFFIX),
            query=query.to_hogql(),
            source_id=str(source.id),
            fields=CUSTOMER_FIELDS,
        )
