from typing import cast, Any, Optional
import posthoganalytics

from posthog.hogql import ast
from posthog.warehouse.models.external_data_source import ExternalDataSource
from posthog.warehouse.models.external_data_schema import ExternalDataSchema
from posthog.warehouse.models.table import DataWarehouseTable
from posthog.models.exchange_rate.sql import EXCHANGE_RATE_DECIMAL_PRECISION
from posthog.schema import CurrencyCode
from posthog.hogql.database.models import (
    BooleanDatabaseField,
    DateTimeDatabaseField,
    ExpressionField,
    IntegerDatabaseField,
    StringDatabaseField,
    Table,
    FieldOrTable,
)
from posthog.hogql.database.schema.exchange_rate import (
    DEFAULT_CURRENCY,
    convert_currency_call,
)


from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from posthog.hogql.context import HogQLContext

STRIPE_DATA_WAREHOUSE_CHARGE_IDENTIFIER = "Charge"

# Stripe represents most currencies with integer amounts multiplied by 100,
# since most currencies have its smallest unit as 1/100 of their base unit
# It just so happens that some currencies don't have that concept, so they're listed here
# https://docs.stripe.com/currencies#zero-decimal
ZERO_DECIMAL_CURRENCIES_IN_STRIPE: list[CurrencyCode] = [
    CurrencyCode.BIF,
    CurrencyCode.CLP,
    CurrencyCode.DJF,
    CurrencyCode.GNF,
    CurrencyCode.JPY,
    CurrencyCode.KMF,
    CurrencyCode.KRW,
    CurrencyCode.MGA,
    CurrencyCode.PYG,
    CurrencyCode.RWF,
    CurrencyCode.UGX,
    CurrencyCode.VND,
    CurrencyCode.VUV,
    CurrencyCode.XAF,
    CurrencyCode.XOF,
    CurrencyCode.XPF,
]

BASE_FIELDS: dict[str, FieldOrTable] = {
    "distinct_id": StringDatabaseField(name="id"),
    "__original_amount": IntegerDatabaseField(name="amount", hidden=True),
    "original_amount": ExpressionField(
        isolate_scope=True,
        expr=ast.Call(
            name="toDecimal",
            args=[
                ast.Field(chain=["__original_amount"]),
                ast.Constant(value=EXCHANGE_RATE_DECIMAL_PRECISION),
            ],
        ),
        name="original_amount",
    ),
    "is_refund": BooleanDatabaseField(name="refunded"),
    "__original_currency": StringDatabaseField(name="currency", hidden=True),
    "original_currency": ExpressionField(
        isolate_scope=True,
        expr=ast.Call(name="upper", args=[ast.Field(chain=["__original_currency"])]),
        name="original_currency",
    ),
    # As per above, Stripe represents most currencies with integer amounts multiplied by 100,
    # so we need to divide by 100 to get the actual amount
    "currency_is_zero_decimal": ExpressionField(
        isolate_scope=True,
        expr=ast.CompareOperation(
            op=ast.CompareOperationOp.In,
            left=ast.Field(chain=["original_currency"]),
            right=ast.Array(
                exprs=[ast.Constant(value=currency.value) for currency in ZERO_DECIMAL_CURRENCIES_IN_STRIPE]
            ),
        ),
        name="currency_is_zero_decimal",
        hidden=True,
    ),
    "amount_decimal_divider": ExpressionField(
        isolate_scope=True,
        expr=ast.Call(
            name="if",
            args=[
                ast.Field(chain=["currency_is_zero_decimal"]),
                ast.Call(
                    name="toDecimal", args=[ast.Constant(value=1), ast.Constant(value=EXCHANGE_RATE_DECIMAL_PRECISION)]
                ),
                ast.Call(
                    name="toDecimal",
                    args=[ast.Constant(value=100), ast.Constant(value=EXCHANGE_RATE_DECIMAL_PRECISION)],
                ),
            ],
        ),
        name="amount_decimal_divider",
        hidden=True,
    ),
    # Amount taking into consideration whether this was a refund or not
    # plus the decimal divider
    "adjusted_original_amount": ExpressionField(
        isolate_scope=True,
        expr=ast.Call(
            name="divideDecimal",
            args=[
                ast.Call(
                    name="if",
                    args=[
                        ast.Field(chain=["is_refund"]),
                        ast.Call(name="negate", args=[ast.Field(chain=["original_amount"])]),
                        ast.Field(chain=["original_amount"]),
                    ],
                ),
                ast.Field(chain=["amount_decimal_divider"]),
            ],
        ),
        name="adjusted_original_amount",
    ),
    # Allow us to sort by timestamp properly in insights (and split in buckets)
    "timestamp": DateTimeDatabaseField(name="created_at"),
}


class RevenueAnalyticsRevenueView(Table):
    data_warehouse_table: (
        Any  # Pydantic is complaining for reasons I dont understand, this should be DataWarehouseTable
    )

    @staticmethod
    def for_schema_source(source: ExternalDataSource) -> Optional["RevenueAnalyticsRevenueView"]:
        # Currently only works for stripe sources
        if not source.source_type == ExternalDataSource.Type.STRIPE:
            return None

        # The table we care about is the one with schema `Charge` since from there we can get
        # the data we need in our view
        try:
            schema: ExternalDataSchema = ExternalDataSchema.objects.get(
                source=source, name=STRIPE_DATA_WAREHOUSE_CHARGE_IDENTIFIER
            )
            table: Optional[DataWarehouseTable] = cast(
                Optional[DataWarehouseTable], schema.table
            )  # Weird cast because pydantic is weird
        except (ExternalDataSchema.DoesNotExist, DataWarehouseTable.DoesNotExist):
            return None

        if table is None:
            return None

        team = table.team
        revenue_config = team.revenue_config
        do_currency_conversion = posthoganalytics.feature_enabled(
            "web-analytics-revenue-tracking-conversion",
            str(team.organization_id),
            groups={"organization": str(team.organization_id)},
            group_properties={"organization": {"id": str(team.organization_id)}},
        )

        # Get most of the fields directly from the base fields,
        # but generate the converted currency and amounts dynamically
        # since we depend on the account's configuration
        fields: dict[str, FieldOrTable] = {
            **BASE_FIELDS,
            "currency": ExpressionField(
                isolate_scope=True,
                expr=ast.Constant(value=(revenue_config.baseCurrency or DEFAULT_CURRENCY).value),
                name="currency",
            )
            if do_currency_conversion
            else BASE_FIELDS["original_currency"],
            "amount": ExpressionField(
                isolate_scope=True,
                expr=convert_currency_call(
                    # Only doing the adjusted calculation here since this is after we've divided by 100
                    ast.Field(chain=["adjusted_original_amount"]),
                    ast.Field(chain=["original_currency"]),
                    ast.Field(chain=["currency"]),
                    ast.Call(
                        name="_toDate",
                        args=[
                            # Because timestamp columns are nullable, we need to handle that case
                            # by converting to a default value of 0
                            ast.Call(
                                name="ifNull",
                                args=[
                                    ast.Field(chain=["timestamp"]),
                                    ast.Call(name="toDateTime", args=[ast.Constant(value=0)]),
                                ],
                            )
                        ],
                    ),
                ),
                name="amount",
            )
            if do_currency_conversion
            else BASE_FIELDS["adjusted_original_amount"],
            # Required because we add a "team_id" where clause on every selected table
            "team_id": ExpressionField(
                isolate_scope=True,
                expr=ast.Constant(value=team.pk),
                name="team_id",
            ),
        }

        return RevenueAnalyticsRevenueView(fields=fields, data_warehouse_table=table)

    def to_printed_clickhouse(self, context: "HogQLContext") -> str:
        table = cast(DataWarehouseTable, self.data_warehouse_table)
        return table.name

    def to_printed_hogql(self) -> str:
        table = cast(DataWarehouseTable, self.data_warehouse_table)
        return table.name
