import json
from typing import Any, cast

from posthog.schema import (
    CachedRevenueExampleEventsQueryResponse,
    DatabaseSchemaManagedViewTableKind,
    RevenueExampleEventsQuery,
    RevenueExampleEventsQueryResponse,
)

from posthog.hogql import ast
from posthog.hogql.ast import CompareOperationOp
from posthog.hogql.constants import LimitContext
from posthog.hogql.database.models import UnknownDatabaseField

from posthog.hogql_queries.insights.paginators import HogQLHasMorePaginator
from posthog.hogql_queries.query_runner import QueryRunnerWithHogQLContext

from products.revenue_analytics.backend.hogql_queries.revenue_analytics_query_runner import RevenueAnalyticsQueryRunner
from products.revenue_analytics.backend.views.schemas import SCHEMAS as VIEW_SCHEMAS


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
        queries: list[ast.SelectQuery] = []
        views = RevenueAnalyticsQueryRunner.revenue_subqueries(
            VIEW_SCHEMAS[DatabaseSchemaManagedViewTableKind.REVENUE_ANALYTICS_CHARGE],
            self.database,
        )

        # Cap how many rows each per-view branch has to enrich. The outer query paginates with
        # `LIMIT limit + 1 OFFSET offset`, so any branch only needs to supply that many of its most
        # recent rows for the global ordering to be correct.
        per_view_limit = self.paginator.limit + self.paginator.offset + 1

        for view in views:
            if not view.is_event_view():
                continue

            # Only pull the most recent revenue events out of the view before enriching them.
            # Without this the join below would have to materialize every matching event.
            view_subquery = ast.SelectQuery(
                select=[ast.Field(chain=["*"])],
                select_from=ast.JoinExpr(table=ast.Field(chain=[view.name])),
                order_by=[ast.OrderExpr(expr=ast.Field(chain=["timestamp"]), order="DESC")],
                limit=ast.Constant(value=per_view_limit),
            )

            queries.append(
                ast.SelectQuery(
                    select=[
                        ast.Alias(
                            alias="event",
                            expr=ast.Call(
                                name="tuple",
                                args=[
                                    ast.Field(chain=["events", "uuid"]),
                                    ast.Field(chain=["events", "event"]),
                                    ast.Field(chain=["events", "distinct_id"]),
                                    ast.Field(chain=["events", "properties"]),
                                ],
                            ),
                        ),
                        ast.Alias(
                            alias="event_name",
                            expr=ast.Field(chain=["view", "event_name"]),
                        ),
                        ast.Alias(
                            alias="original_amount",
                            expr=ast.Field(chain=["view", "original_amount"]),
                        ),
                        ast.Alias(
                            alias="currency_aware_amount",
                            expr=ast.Field(chain=["view", "currency_aware_amount"]),
                        ),
                        ast.Alias(
                            alias="original_currency",
                            expr=ast.Field(chain=["view", "original_currency"]),
                        ),
                        ast.Alias(
                            alias="amount",
                            expr=ast.Field(chain=["view", "amount"]),
                        ),
                        ast.Alias(
                            alias="currency",
                            expr=ast.Field(chain=["view", "currency"]),
                        ),
                        ast.Alias(
                            alias="person",
                            expr=ast.Call(
                                name="tuple",
                                args=[
                                    ast.Field(chain=["events", "person", "id"]),
                                    ast.Field(chain=["events", "person", "created_at"]),
                                    ast.Field(chain=["events", "distinct_id"]),
                                    ast.Field(chain=["events", "person", "properties"]),
                                ],
                            ),
                        ),
                        ast.Alias(
                            alias="session_id",
                            expr=ast.Field(chain=["view", "session_id"]),
                        ),
                        ast.Alias(
                            alias="timestamp",
                            expr=ast.Field(chain=["view", "timestamp"]),
                        ),
                    ],
                    # `events` drives the join (probe side) while the already-capped view is the
                    # build side, so the hash table stays small. Filtering `events.event` prunes the
                    # scan using the events table sort key rather than reading every event.
                    select_from=ast.JoinExpr(
                        alias="events",
                        table=ast.Field(chain=["events"]),
                        next_join=ast.JoinExpr(
                            join_type="INNER JOIN",
                            alias="view",
                            table=view_subquery,
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
                    where=ast.CompareOperation(
                        op=CompareOperationOp.Eq,
                        left=ast.Field(chain=["events", "event"]),
                        right=ast.Constant(value=view.event_name),
                    ),
                    order_by=[ast.OrderExpr(expr=ast.Field(chain=["timestamp"]), order="DESC")],
                    limit=ast.Constant(value=per_view_limit),
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
            user=self.user,
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
