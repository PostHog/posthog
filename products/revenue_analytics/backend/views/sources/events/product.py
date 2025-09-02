from collections.abc import Iterable

from posthog.hogql import ast

from products.revenue_analytics.backend.views.core import BuiltQuery, SourceHandle, view_prefix_for_event
from products.revenue_analytics.backend.views.schemas.product import SCHEMA as PRODUCT_SCHEMA
from products.revenue_analytics.backend.views.sources.helpers import events_expr_for_team


def build(handle: SourceHandle) -> Iterable[BuiltQuery]:
    team = handle.team
    for event in team.revenue_analytics_config.events:
        prefix = view_prefix_for_event(event.eventName)

        if not event.productProperty:
            yield BuiltQuery(
                key=f"{event.eventName}.no_property",
                prefix=prefix,
                query=ast.SelectQuery.empty(columns=list(PRODUCT_SCHEMA.fields.keys())),
            )
            continue

        events_query = ast.SelectQuery(
            distinct=True,
            select=[
                ast.Alias(alias="product_id", expr=ast.Field(chain=["events", "properties", event.productProperty]))
            ],
            select_from=ast.JoinExpr(table=ast.Field(chain=["events"])),
            where=events_expr_for_team(team),
        )

        query = ast.SelectQuery(
            select=[
                ast.Alias(alias="id", expr=ast.Field(chain=["product_id"])),
                ast.Alias(alias="source_label", expr=ast.Constant(value=prefix)),
                ast.Alias(alias="name", expr=ast.Field(chain=["product_id"])),
            ],
            select_from=ast.JoinExpr(table=events_query),
            order_by=[ast.OrderExpr(expr=ast.Field(chain=["id"]), order="ASC")],
        )

        yield BuiltQuery(key=event.eventName, prefix=prefix, query=query)
