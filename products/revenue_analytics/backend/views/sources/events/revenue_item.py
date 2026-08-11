from posthog.hogql import ast
from posthog.hogql.database.schema.exchange_rate import (
    currency_expression_for_events,
    revenue_comparison_and_value_exprs_for_events,
)

from products.revenue_analytics.backend.views.core import BuiltQuery, SourceHandle, view_prefix_for_event
from products.revenue_analytics.backend.views.sources.helpers import (
    currency_aware_amount,
    currency_aware_divider,
    events_expr_for_team,
    is_zero_decimal_in_stripe,
)


def build(handle: SourceHandle) -> BuiltQuery:
    team = handle.team
    event = handle.event

    if event is None:
        raise ValueError("Event is required")

    generic_team_expr = events_expr_for_team(team)

    comparison_expr, value_expr = revenue_comparison_and_value_exprs_for_events(
        team, event, do_currency_conversion=False
    )
    _, currency_aware_amount_expr = revenue_comparison_and_value_exprs_for_events(
        team,
        event,
        amount_expr=ast.Field(chain=["currency_aware_amount"]),
    )

    prefix = view_prefix_for_event(event.eventName)

    filter_exprs = [
        comparison_expr,
        generic_team_expr,
        ast.CompareOperation(
            op=ast.CompareOperationOp.NotEq,
            left=ast.Field(chain=["amount"]),  # refers to the Alias above
            right=ast.Constant(value=None),
        ),
    ]

    query = ast.SelectQuery(
        select=[
            ast.Alias(alias="id", expr=ast.Call(name="toString", args=[ast.Field(chain=["uuid"])])),
            ast.Alias(alias="invoice_item_id", expr=ast.Call(name="toString", args=[ast.Field(chain=["uuid"])])),
            ast.Alias(alias="source_label", expr=ast.Constant(value=prefix)),
            ast.Alias(alias="timestamp", expr=ast.Field(chain=["timestamp"])),
            ast.Alias(alias="created_at", expr=ast.Field(chain=["timestamp"])),
            ast.Alias(
                alias="is_recurring",
                expr=ast.Call(name="isNotNull", args=[ast.Field(chain=["properties", event.subscriptionProperty])])
                if event.subscriptionProperty
                else ast.Constant(value=False),
            ),
            ast.Alias(
                alias="product_id",
                expr=ast.Field(chain=["properties", event.productProperty])
                if event.productProperty
                else ast.Constant(value=None),
            ),
            ast.Alias(alias="customer_id", expr=ast.Call(name="toString", args=[ast.Field(chain=["person_id"])])),
            ast.Alias(alias="group_0_key", expr=ast.Field(chain=["$group_0"])),
            ast.Alias(alias="group_1_key", expr=ast.Field(chain=["$group_1"])),
            ast.Alias(alias="group_2_key", expr=ast.Field(chain=["$group_2"])),
            ast.Alias(alias="group_3_key", expr=ast.Field(chain=["$group_3"])),
            ast.Alias(alias="group_4_key", expr=ast.Field(chain=["$group_4"])),
            ast.Alias(alias="invoice_id", expr=ast.Constant(value=None)),
            ast.Alias(
                alias="subscription_id",
                expr=ast.Field(chain=["properties", event.subscriptionProperty])
                if event.subscriptionProperty
                else ast.Constant(value=None),
            ),
            ast.Alias(alias="session_id", expr=ast.Call(name="toString", args=[ast.Field(chain=["$session_id"])])),
            ast.Alias(alias="event_name", expr=ast.Field(chain=["event"])),
            ast.Alias(
                alias="coupon",
                expr=ast.Field(chain=["properties", event.couponProperty])
                if event.couponProperty
                else ast.Constant(value=None),
            ),
            ast.Alias(alias="coupon_id", expr=ast.Field(chain=["coupon"])),  # Same as above, just copy
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

    return BuiltQuery(key=event.eventName, prefix=prefix, query=query)
