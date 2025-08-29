from collections.abc import Iterable

from posthog.hogql import ast

from products.revenue_analytics.backend.views.core import BuiltQuery, SourceHandle, view_prefix_for_event
from products.revenue_analytics.backend.views.sources.helpers import events_expr_for_team, get_cohort_expr


def build(handle: SourceHandle) -> Iterable[BuiltQuery]:
    team = handle.team
    for event in team.revenue_analytics_config.events:
        prefix = view_prefix_for_event(event.eventName)

        events_query = ast.SelectQuery(
            distinct=True,
            select=[ast.Alias(alias="person_id", expr=ast.Field(chain=["events", "person", "id"]))],
            select_from=ast.JoinExpr(table=ast.Field(chain=["events"])),
            where=events_expr_for_team(team),
        )

        query = ast.SelectQuery(
            select=[
                ast.Alias(alias="id", expr=ast.Call(name="toString", args=[ast.Field(chain=["id"])])),
                ast.Alias(alias="source_label", expr=ast.Constant(value=prefix)),
                ast.Alias(alias="timestamp", expr=ast.Field(chain=["created_at"])),
                ast.Alias(alias="name", expr=ast.Field(chain=["properties", "name"])),
                ast.Alias(alias="email", expr=ast.Field(chain=["properties", "email"])),
                ast.Alias(alias="phone", expr=ast.Field(chain=["properties", "phone"])),
                ast.Alias(alias="address", expr=ast.Field(chain=["properties", "address"])),
                ast.Alias(alias="metadata", expr=ast.Field(chain=["properties", "metadata"])),
                ast.Alias(alias="country", expr=ast.Field(chain=["properties", "$geoip_country_name"])),
                ast.Alias(alias="cohort", expr=get_cohort_expr("created_at")),
                ast.Alias(alias="initial_coupon", expr=ast.Constant(value=None)),
                ast.Alias(alias="initial_coupon_id", expr=ast.Constant(value=None)),
            ],
            select_from=ast.JoinExpr(
                table=ast.Field(chain=["persons"]),
                alias="persons",
                next_join=ast.JoinExpr(
                    table=events_query,
                    alias="events",
                    join_type="INNER JOIN",
                    constraint=ast.JoinConstraint(
                        constraint_type="ON",
                        expr=ast.CompareOperation(
                            left=ast.Field(chain=["id"]),
                            right=ast.Field(chain=["person_id"]),
                            op=ast.CompareOperationOp.Eq,
                        ),
                    ),
                ),
            ),
            order_by=[ast.OrderExpr(expr=ast.Field(chain=["created_at"]), order="DESC")],
        )

        yield BuiltQuery(key=event.eventName, prefix=prefix, query=query)
