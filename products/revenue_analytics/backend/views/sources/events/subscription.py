from collections.abc import Iterable

from posthog.schema import SubscriptionDropoffMode

from posthog.hogql import ast

from products.revenue_analytics.backend.views.core import BuiltQuery, SourceHandle, view_prefix_for_event
from products.revenue_analytics.backend.views.schemas.subscription import SCHEMA as SUBSCRIPTION_SCHEMA
from products.revenue_analytics.backend.views.sources.helpers import events_expr_for_team


def build(handle: SourceHandle) -> Iterable[BuiltQuery]:
    team = handle.team
    for event in team.revenue_analytics_config.events:
        prefix = view_prefix_for_event(event.eventName)

        if event.subscriptionProperty is None:
            yield BuiltQuery(
                key=f"{event.eventName}.no_property",
                prefix=prefix,
                query=ast.SelectQuery.empty(columns=list(SUBSCRIPTION_SCHEMA.fields.keys())),
            )
            continue

        events_query = ast.SelectQuery(
            select=[
                ast.Alias(alias="person_id", expr=ast.Field(chain=["person", "id"])),
                ast.Alias(alias="subscription_id", expr=ast.Field(chain=["properties", event.subscriptionProperty])),
                ast.Alias(
                    alias="product_id",
                    expr=ast.Call(name="min", args=[ast.Field(chain=["properties", event.productProperty])])
                    if event.productProperty
                    else ast.Constant(value=None),
                ),
                ast.Alias(alias="min_timestamp", expr=ast.Call(name="min", args=[ast.Field(chain=["timestamp"])])),
                ast.Alias(alias="max_timestamp", expr=ast.Call(name="max", args=[ast.Field(chain=["timestamp"])])),
                ast.Alias(
                    alias="max_timestamp_plus_dropoff_days",
                    expr=ast.Call(
                        name="addDays",
                        args=[
                            ast.Field(chain=["max_timestamp"]),
                            ast.Constant(value=event.subscriptionDropoffDays),
                        ],
                    ),
                ),
            ],
            select_from=ast.JoinExpr(table=ast.Field(chain=["events"])),
            where=events_expr_for_team(team),
            group_by=[
                ast.Field(chain=["subscription_id"]),
                ast.Field(chain=["person_id"]),
            ],
        )

        query = ast.SelectQuery(
            select=[
                ast.Alias(alias="id", expr=ast.Field(chain=["subscription_id"])),
                ast.Alias(alias="source_label", expr=ast.Constant(value=prefix)),
                ast.Alias(alias="plan_id", expr=ast.Constant(value=None)),
                ast.Alias(alias="product_id", expr=ast.Field(chain=["product_id"])),
                ast.Alias(alias="customer_id", expr=ast.Call(name="toString", args=[ast.Field(chain=["person_id"])])),
                ast.Alias(alias="status", expr=ast.Constant(value=None)),
                ast.Alias(alias="started_at", expr=ast.Field(chain=["min_timestamp"])),
                # If has an end date, but it's in the future, then just not include `ended_at`
                ast.Alias(
                    alias="ended_at",
                    expr=ast.Call(
                        name="if",
                        args=[
                            ast.CompareOperation(
                                op=ast.CompareOperationOp.Gt,
                                left=ast.Field(chain=["max_timestamp_plus_dropoff_days"]),
                                right=ast.Call(name="today", args=[]),
                            ),
                            ast.Constant(value=None),
                            ast.Field(chain=["max_timestamp"])
                            if event.subscriptionDropoffMode == SubscriptionDropoffMode.LAST_EVENT
                            else ast.Field(chain=["max_timestamp_plus_dropoff_days"]),
                        ],
                    ),
                ),
                ast.Alias(alias="metadata", expr=ast.Constant(value=None)),
            ],
            select_from=ast.JoinExpr(table=events_query),
            order_by=[ast.OrderExpr(expr=ast.Field(chain=["started_at"]), order="DESC")],
        )

        yield BuiltQuery(key=event.eventName, prefix=prefix, query=query)
