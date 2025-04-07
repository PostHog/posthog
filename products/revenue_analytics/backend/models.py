from typing import cast, Optional

from posthog.warehouse.models.external_data_source import ExternalDataSource
from posthog.warehouse.models.external_data_schema import ExternalDataSchema
from posthog.warehouse.models.table import DataWarehouseTable
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
from posthog.hogql.database.schema.exchange_rate import DEFAULT_CURRENCY


from typing import TYPE_CHECKING

if TYPE_CHECKING:
    pass

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

FIELDS: dict[str, FieldOrTable] = {
    "id": StringDatabaseField(name="id"),
    "timestamp": DateTimeDatabaseField(name="timestamp"),
    "original_amount": DecimalDatabaseField(name="original_amount", hidden=True),
    "original_currency": StringDatabaseField(name="original_currency", hidden=True),
    "currency_is_zero_decimal": BooleanDatabaseField(name="currency_is_zero_decimal", hidden=True),
    "amount_decimal_divider": DecimalDatabaseField(name="amount_decimal_divider", hidden=True),
    "adjusted_original_amount": DecimalDatabaseField(name="adjusted_original_amount", hidden=True),
    "currency": StringDatabaseField(name="currency"),
    "amount": DecimalDatabaseField(name="amount"),
}


class RevenueAnalyticsRevenueView(SavedQuery):
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

        zero_decimal_currencies = ", ".join([f"'{currency.value}'" for currency in ZERO_DECIMAL_CURRENCIES_IN_STRIPE])
        base_currency = (revenue_config.baseCurrency or DEFAULT_CURRENCY).value

        query = f"""
    SELECT
        id AS id,
        created_at AS timestamp,
        toDecimal(amount, {EXCHANGE_RATE_DECIMAL_PRECISION}) AS original_amount,
        upper(currency) AS original_currency,
        original_currency IN ({zero_decimal_currencies}) AS currency_is_zero_decimal,
        if(currency_is_zero_decimal, toDecimal(1, {EXCHANGE_RATE_DECIMAL_PRECISION}), toDecimal(100, {EXCHANGE_RATE_DECIMAL_PRECISION})) AS amount_decimal_divider,
        divideDecimal(original_amount, amount_decimal_divider) AS adjusted_original_amount,
        '{base_currency}' AS currency,
        convertCurrency(original_currency, currency, adjusted_original_amount, _toDate(ifNull(timestamp, toDateTime(0)))) AS amount
    FROM
        {table.name}
"""

        return RevenueAnalyticsRevenueView(
            id=str(table.id),
            name=f"stripe_{source.prefix or source.id}_revenue",
            query=query,
            fields=FIELDS,
        )
