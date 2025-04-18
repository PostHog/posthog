from typing import cast

from posthog.hogql import ast
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
from posthog.hogql.database.schema.exchange_rate import DEFAULT_CURRENCY, convert_currency_call


from typing import TYPE_CHECKING

if TYPE_CHECKING:
    pass

STRIPE_DATA_WAREHOUSE_CHARGE_IDENTIFIER = "Charge"
STRIPE_DATA_WAREHOUSE_CUSTOMER_IDENTIFIER = "Customer"
STRIPE_CHARGE_SUCCEEDED_STATUS = "succeeded"

# Keep in sync with `revenueAnalyticsLogic.ts`
CHARGE_REVENUE_VIEW_SUFFIX = "charge_revenue_view"
CUSTOMER_REVENUE_VIEW_SUFFIX = "customer_revenue_view"

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
    "id": StringDatabaseField(name="id"),
    "timestamp": DateTimeDatabaseField(name="timestamp"),
    "customer_id": StringDatabaseField(name="customer_id"),
    "original_amount": DecimalDatabaseField(name="original_amount"),
    "original_currency": StringDatabaseField(name="original_currency"),
    "currency_is_zero_decimal": BooleanDatabaseField(name="currency_is_zero_decimal"),
    "amount_decimal_divider": DecimalDatabaseField(name="amount_decimal_divider"),
    "adjusted_original_amount": DecimalDatabaseField(name="adjusted_original_amount"),
    "currency": StringDatabaseField(name="currency"),
    "amount": DecimalDatabaseField(name="amount"),
}

CUSTOMER_FIELDS: dict[str, FieldOrTable] = {
    "id": StringDatabaseField(name="id"),
    "timestamp": DateTimeDatabaseField(name="timestamp"),
    "name": StringDatabaseField(name="name"),
    "email": StringDatabaseField(name="email"),
    "phone": StringDatabaseField(name="phone"),
}


class RevenueAnalyticsRevenueView(SavedQuery):
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
    def __get_view_name_for(source: ExternalDataSource, view_name: str) -> str:
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
                # Compute the original currency, converting to uppercase to match the currency code in the `exchange_rate` table
                ast.Alias(
                    alias="original_currency",
                    expr=ast.Call(name="upper", args=[ast.Field(chain=["currency"])]),
                ),
                # Compute whether the original currency is a zero-decimal currency
                # by comparing it against a list of zero-decimal currencies
                ast.Alias(
                    alias="currency_is_zero_decimal",
                    expr=ast.Call(
                        name="in",
                        args=[
                            ast.Field(chain=["original_currency"]),
                            ast.Constant(value=ZERO_DECIMAL_CURRENCIES_IN_STRIPE),
                        ],
                    ),
                ),
                # Compute the amount decimal divider, which is 1 for zero-decimal currencies and 100 for others
                # This is used to convert the original amount to the adjusted amount
                ast.Alias(
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
                ),
                # Compute the adjusted original amount, which is the original amount divided by the amount decimal divider
                ast.Alias(
                    alias="adjusted_original_amount",
                    expr=ast.Call(
                        name="divideDecimal",
                        args=[
                            ast.Field(chain=["original_amount"]),
                            ast.Field(chain=["amount_decimal_divider"]),
                        ],
                    ),
                ),
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
            name=RevenueAnalyticsRevenueView.__get_view_name_for(source, CHARGE_REVENUE_VIEW_SUFFIX),
            query=query.to_hogql(),
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
            name=RevenueAnalyticsRevenueView.__get_view_name_for(source, CUSTOMER_REVENUE_VIEW_SUFFIX),
            query=query.to_hogql(),
            fields=CUSTOMER_FIELDS,
        )
