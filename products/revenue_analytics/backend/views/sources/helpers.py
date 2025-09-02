from posthog.schema import CurrencyCode

from posthog.hogql import ast
from posthog.hogql.parser import parse_expr

from posthog.models.exchange_rate.sql import EXCHANGE_RATE_DECIMAL_PRECISION
from posthog.models.team.team import Team

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


def events_expr_for_team(team: Team) -> ast.Expr:
    from posthog.hogql.property import property_to_expr

    exprs = []
    if (
        team.revenue_analytics_config.filter_test_accounts
        and isinstance(team.test_account_filters, list)
        and len(team.test_account_filters) > 0
    ):
        exprs = [property_to_expr(filter, team) for filter in team.test_account_filters]

    if len(exprs) == 0:
        return ast.Constant(value=True)
    elif len(exprs) == 1:
        return exprs[0]
    else:
        return ast.And(exprs=exprs)


def get_cohort_expr(field: str) -> ast.Expr:
    return parse_expr(f"formatDateTime(toStartOfMonth({field}), '%Y-%m')")


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
