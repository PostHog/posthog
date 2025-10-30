import json
from typing import Any, cast

from posthog.schema import (
    CachedRevenueExampleEventsQueryResponse,
    RevenueExampleEventsQuery,
    RevenueExampleEventsQueryResponse,
)

from posthog.hogql import ast
from posthog.hogql.ast import CompareOperationOp
from posthog.hogql.constants import LimitContext
from posthog.hogql.database.models import UnknownDatabaseField

from posthog.hogql_queries.insights.paginators import HogQLHasMorePaginator
from posthog.hogql_queries.query_runner import QueryRunnerWithHogQLContext

from products.revenue_analytics.backend.views import RevenueAnalyticsChargeView


class RevenueExampleEventsQueryRunner(QueryRunnerWithHogQLContext):
    query: RevenueExampleEventsQuery
    response: RevenueExampleEventsQueryResponse
    cached_response: CachedRevenueExampleEventsQueryResponse
    paginator: HogQLHasMorePaginator

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.paginator = HogQLHasMorePaginator.from_limit_context(
            limit_context=LimitContext.QUERY, limit=self.query.limit if self.query.limit else None
        )

    def to_query(self) -> ast.SelectQuery:
        view_names = self.database.get_view_names()
        all_views = [self.database.get_table(view_name) for view_name in view_names]
        views = [
            view
            for view in all_views
            if isinstance(view, RevenueAnalyticsChargeView) and view.is_event_view() and not view.union_all
        ]

        queries: list[ast.SelectQuery] = []
        for view in views:
            queries.append(
                ast.SelectQuery(
                    select=[
                        ast.Call(
                            name="tuple",
                            args=[
                                ast.Field(chain=["events", "uuid"]),
                                ast.Field(chain=["events", "event"]),
                                ast.Field(chain=["events", "distinct_id"]),
                                ast.Field(chain=["events", "properties"]),
                            ],
                        ),
                        ast.Field(chain=["view", "event_name"]),
                        ast.Field(chain=["view", "original_amount"]),
                        ast.Field(chain=["view", "currency_aware_amount"]),
                        ast.Field(chain=["view", "original_currency"]),
                        ast.Field(chain=["view", "amount"]),
                        ast.Field(chain=["view", "currency"]),
                        ast.Call(
                            name="tuple",
                            args=[
                                ast.Field(chain=["events", "person", "id"]),
                                ast.Field(chain=["events", "person", "created_at"]),
                                ast.Field(chain=["events", "distinct_id"]),
                                ast.Field(chain=["events", "person", "properties"]),
                            ],
                        ),
                        ast.Field(chain=["view", "session_id"]),
                        ast.Alias(alias="timestamp", expr=ast.Field(chain=["view", "timestamp"])),
                    ],
                    select_from=ast.JoinExpr(
                        alias="view",
                        table=ast.Field(chain=[view.name]),
                        next_join=ast.JoinExpr(
                            join_type="INNER JOIN",
                            alias="events",
                            table=ast.Field(chain=["events"]),
                            constraint=ast.JoinConstraint(
                                constraint_type="ON",
                                expr=ast.CompareOperation(
                                    op=CompareOperationOp.Eq,
                                    left=ast.Call(name="toString", args=[ast.Field(chain=["events", "uuid"])]),
                                    right=ast.Field(chain=["view", "id"]),
                                ),
                            ),
                        ),
                    ),
                    order_by=[ast.OrderExpr(expr=ast.Field(chain=["timestamp"]), order="DESC")],
                )
            )

        if len(queries) == 0:
            columns = [
                "event",
                "event_name",
                "original_amount",
                "currency_aware_amount",
                "original_currency",
                "amount",
                "currency",
                "person",
                "session_id",
                "timestamp",
            ]
            return ast.SelectQuery.empty(columns={key: UnknownDatabaseField(name=key) for key in columns})
        elif len(queries) == 1:
            return queries[0]
        else:
            # Reorder by timestamp to ensure the most recent events are at the top across all event views
            return ast.SelectQuery(
                select=[ast.Field(chain=["*"])],
                select_from=ast.JoinExpr(table=ast.SelectSetQuery.create_from_queries(queries, "UNION ALL")),
                order_by=[ast.OrderExpr(expr=ast.Field(chain=["timestamp"]), order="DESC")],
            )

    def _calculate(self):
        response = self.paginator.execute_hogql_query(
            query_type="revenue_example_events_query",
            query=self.to_query(),
            team=self.team,
            timings=self.timings,
            modifiers=self.modifiers,
        )

        results = [
            (
                {
                    "uuid": row[0][0],
                    "event": row[0][1],
                    "distinct_id": row[0][2],
                    "properties": json.loads(row[0][3]),
                },
                row[1],
                row[2],
                row[3],
                row[4],
                row[5],
                row[6],
                {
                    "id": row[7][0],
                    "created_at": row[7][1],
                    "distinct_id": row[7][2],
                    "properties": json.loads(row[7][3]),
                },
                row[8],
                row[9],
            )
            for row in cast(list[tuple[Any, ...]], response.results)
        ]

        return RevenueExampleEventsQueryResponse(
            columns=[
                "*",
                "event",
                "original_amount",
                "currency_aware_amount",
                "original_currency",
                "amount",
                "currency",
                "person",
                "session_id",
                "timestamp",
            ],
            results=results,
            timings=response.timings,
            types=response.types,
            hogql=response.hogql,
            modifiers=self.modifiers,
            **self.paginator.response_params(),
        )
