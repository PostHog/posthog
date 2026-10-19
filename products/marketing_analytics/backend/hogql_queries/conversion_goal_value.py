from posthog.schema import ConversionGoalFilter1, ConversionGoalFilter2, ConversionGoalFilter3

from posthog.hogql import ast
from posthog.hogql.database.schema.exchange_rate import convert_currency_call

from posthog.models import Team


def conversion_goal_value_in_base_currency(
    goal: ConversionGoalFilter1 | ConversionGoalFilter2 | ConversionGoalFilter3,
    team: Team,
    property_field: ast.Expr,
    timestamp_expr: ast.Expr,
    *,
    warehouse_table_alias: str | None = None,
) -> ast.Expr:
    """Turn a raw revenue property into a float in the team's base currency.

    When the goal declares a math_property_revenue_currency, convert each value at the exchange
    rate of its own event day. Without it, the value is assumed to already be in the base currency
    and is only cast to float, which keeps goals that never set a currency behaving as before.
    """
    amount = ast.Call(name="toFloat", args=[property_field])
    currency = goal.math_property_revenue_currency
    if currency is None:
        return amount

    base_currency = ast.Constant(value=team.base_currency)
    date = ast.Call(name="_toDate", args=[timestamp_expr])

    if currency.property:
        if goal.kind == "DataWarehouseNode":
            currency_from: ast.Expr = ast.Field(
                chain=[warehouse_table_alias, currency.property] if warehouse_table_alias else [currency.property]
            )
        else:
            currency_from = ast.Field(chain=["events", "properties", currency.property])
        currency_from = ast.Call(
            name="nullIf", args=[ast.Call(name="upper", args=[currency_from]), ast.Constant(value="")]
        )
        # A row can be missing the currency property or carry an empty string; treat those as already
        # in the base currency rather than letting convertCurrency convert the whole amount to 0.
        return ast.Call(
            name="if",
            args=[
                ast.Call(name="isNull", args=[currency_from]),
                amount,
                ast.Call(name="toFloat", args=[convert_currency_call(amount, currency_from, base_currency, date)]),
            ],
        )

    if currency.static:
        currency_from = ast.Constant(value=currency.static.value)
        return ast.Call(name="toFloat", args=[convert_currency_call(amount, currency_from, base_currency, date)])

    return amount
