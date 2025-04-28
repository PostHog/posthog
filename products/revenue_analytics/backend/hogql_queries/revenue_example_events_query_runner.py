import json

from posthog.hogql import ast
from posthog.hogql.ast import CompareOperationOp
from posthog.hogql.constants import LimitContext
from posthog.hogql_queries.query_runner import QueryRunnerWithHogQLContext
from posthog.hogql_queries.insights.paginators import HogQLHasMorePaginator
from posthog.schema import (
    RevenueExampleEventsQuery,
    RevenueExampleEventsQueryResponse,
    CachedRevenueExampleEventsQueryResponse,
)
from ..models import EVENTS_VIEW_SUFFIX


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
        if not self.database.has_table(EVENTS_VIEW_SUFFIX):
            return ast.SelectQuery.empty()

        select = ast.SelectQuery(
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
                ast.Field(chain=["view", "adjusted_original_amount"]),
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
                ast.Field(chain=["view", "timestamp"]),
            ],
            select_from=ast.JoinExpr(
                alias="view",
                table=ast.Field(chain=[EVENTS_VIEW_SUFFIX]),
                next_join=ast.JoinExpr(
                    join_type="INNER JOIN",
                    table=ast.Field(chain=["events"]),
                    alias="events",
                    constraint=ast.JoinConstraint(
                        constraint_type="ON",
                        expr=ast.CompareOperation(
                            op=CompareOperationOp.Eq,
                            left=ast.Field(chain=["events", "event"]),
                            right=ast.Field(chain=["view", "event_name"]),
                        ),
                    ),
                ),
            ),
            order_by=[ast.OrderExpr(expr=ast.Field(chain=["view", "timestamp"]), order="DESC")],
        )

        return select

    def calculate(self):
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
                {
                    "id": row[6][0],
                    "created_at": row[6][1],
                    "distinct_id": row[6][2],
                    "properties": json.loads(row[6][3]),
                },
                row[7],
                row[8],
            )
            for row in response.results
        ]

        return RevenueExampleEventsQueryResponse(
            columns=[
                "*",
                "event",
                "original_amount",
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
