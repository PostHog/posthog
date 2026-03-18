from posthog.hogql import ast

from products.revenue_analytics.backend.views.core import BuiltQuery, SourceHandle, view_prefix_for_event
from products.revenue_analytics.backend.views.schemas.product import SCHEMA as PRODUCT_SCHEMA
from products.revenue_analytics.backend.views.sources.helpers import events_expr_for_team


def build(handle: SourceHandle) -> BuiltQuery:
    team = handle.team
    event = handle.event

    if event is None:
        raise ValueError("Event is required")

    prefix = view_prefix_for_event(event.eventName)

    if not event.productProperty:
        return BuiltQuery(
            key=event.eventName,
            prefix=prefix,
            query=ast.SelectQuery.empty(columns=PRODUCT_SCHEMA.fields),
            test_comments="no_property",
        )

    events_query = ast.SelectQuery(
        distinct=True,
        select=[ast.Alias(alias="product_id", expr=ast.Field(chain=["events", "properties", event.productProperty]))],
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

    return BuiltQuery(key=event.eventName, prefix=prefix, query=query)
