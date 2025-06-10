from posthog.schema import CurrencyCode
from posthog.models.exchange_rate.sql import EXCHANGE_RATE_DECIMAL_PRECISION
from posthog.hogql import ast
from posthog.hogql.database.models import (
    BooleanDatabaseField,
    DecimalDatabaseField,
    StringDatabaseField,
    FieldOrTable,
)

# Currency-related fields used to compute revenue
# It's used in more than one view, so it's a good idea to keep it here
BASE_CURRENCY_FIELDS: dict[str, FieldOrTable] = {
    "currency": StringDatabaseField(name="currency"),
    "amount": DecimalDatabaseField(name="amount"),
    # Mostly helper fields, shared with charges too
    "original_currency": StringDatabaseField(name="original_currency"),
    "original_amount": DecimalDatabaseField(name="original_amount"),
    "enable_currency_aware_divider": BooleanDatabaseField(name="enable_currency_aware_divider"),
    "currency_aware_divider": DecimalDatabaseField(name="currency_aware_divider"),
    "currency_aware_amount": DecimalDatabaseField(name="currency_aware_amount"),
}

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
