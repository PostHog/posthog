from collections.abc import Iterable

from posthog.hogql import ast

from products.revenue_analytics.backend.views.core import BuiltQuery, SourceHandle, view_prefix_for_event
from products.revenue_analytics.backend.views.sources.helpers import (
    events_expr_for_team,
    is_zero_decimal_in_stripe,
    currency_aware_divider,
    currency_aware_amount,
)
from posthog.hogql.database.schema.exchange_rate import (
    revenue_comparison_and_value_exprs_for_events,
    currency_expression_for_events,
)


def build(handle: SourceHandle) -> Iterable[BuiltQuery]:
    team = handle.team

    if len(team.revenue_analytics_config.events) == 0:
        return

    generic_team_expr = events_expr_for_team(team)

    for event in team.revenue_analytics_config.events:
        prefix = view_prefix_for_event(event.eventName)

        comparison_expr, value_expr = revenue_comparison_and_value_exprs_for_events(
            team, event, do_currency_conversion=False
        )
        _, currency_aware_amount_expr = revenue_comparison_and_value_exprs_for_events(
            team,
            event,
            amount_expr=ast.Field(chain=["currency_aware_amount"]),
        )

        filter_exprs = [
            comparison_expr,
            generic_team_expr,
            ast.CompareOperation(
                op=ast.CompareOperationOp.NotEq,
                left=ast.Field(chain=["amount"]),
                right=ast.Constant(value=None),
            ),
        ]

        query = ast.SelectQuery(
            select=[
                ast.Alias(alias="id", expr=ast.Call(name="toString", args=[ast.Field(chain=["uuid"])])),
                ast.Alias(alias="source_label", expr=ast.Constant(value=prefix)),
                ast.Alias(alias="timestamp", expr=ast.Field(chain=["timestamp"])),
                ast.Alias(alias="customer_id", expr=ast.Field(chain=["distinct_id"])),
                ast.Alias(
                    alias="invoice_id", expr=ast.Constant(value=None)
                ),  # Helpful for sources, not helpful for events
                ast.Alias(alias="session_id", expr=ast.Call(name="toString", args=[ast.Field(chain=["$session_id"])])),
                ast.Alias(alias="event_name", expr=ast.Field(chain=["event"])),
                ast.Alias(alias="original_currency", expr=currency_expression_for_events(team, event)),
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

        yield BuiltQuery(key=event.eventName, prefix=prefix, query=query)
