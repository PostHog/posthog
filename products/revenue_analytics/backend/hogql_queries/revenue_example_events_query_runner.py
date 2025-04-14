import json

from posthog.hogql import ast
from posthog.hogql.ast import CompareOperationOp
from posthog.hogql.constants import LimitContext
from posthog.hogql_queries.insights.paginators import HogQLHasMorePaginator
from posthog.hogql.database.schema.exchange_rate import (
    DEFAULT_CURRENCY,
    revenue_expression_for_events,
    revenue_where_expr_for_events,
    currency_expression_for_all_events,
)
from posthog.schema import (
    RevenueExampleEventsQuery,
    RevenueExampleEventsQueryResponse,
    CachedRevenueExampleEventsQueryResponse,
)

from .revenue_analytics_query_runner import RevenueAnalyticsQueryRunner


class RevenueExampleEventsQueryRunner(RevenueAnalyticsQueryRunner):
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
        revenue_config = self.team.revenue_config

        select = ast.SelectQuery(
            select=[
                ast.Call(
                    name="tuple",
                    args=[
                        ast.Field(chain=["uuid"]),
                        ast.Field(chain=["event"]),
                        ast.Field(chain=["distinct_id"]),
                        ast.Field(chain=["properties"]),
                    ],
                ),
                ast.Field(chain=["event"]),
                ast.Alias(
                    alias="original_revenue",
                    expr=revenue_expression_for_events(revenue_config, do_currency_conversion=False),
                ),
                ast.Alias(alias="original_currency", expr=currency_expression_for_all_events(revenue_config)),
                ast.Alias(alias="revenue", expr=revenue_expression_for_events(revenue_config)),
                ast.Alias(
                    alias="currency", expr=ast.Constant(value=(revenue_config.baseCurrency or DEFAULT_CURRENCY).value)
                ),
                ast.Call(
                    name="tuple",
                    args=[
                        ast.Field(chain=["person", "id"]),
                        ast.Field(chain=["person", "created_at"]),
                        ast.Field(chain=["distinct_id"]),
                        ast.Field(chain=["person", "properties"]),
                    ],
                ),
                ast.Alias(alias="session_id", expr=ast.Field(chain=["properties", "$session_id"])),
                ast.Field(chain=["timestamp"]),
            ],
            select_from=ast.JoinExpr(table=ast.Field(chain=["events"])),
            where=ast.And(
                exprs=[
                    revenue_where_expr_for_events(revenue_config),
                    ast.CompareOperation(
                        op=CompareOperationOp.NotEq,
                        left=ast.Field(chain=["revenue"]),  # refers to the Alias above
                        right=ast.Constant(value=None),
                    ),
                ]
            ),
            order_by=[ast.OrderExpr(expr=ast.Field(chain=["timestamp"]), order="DESC")],
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
                "original_revenue",
                "original_currency",
                "revenue",
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
