from __future__ import annotations

from abc import ABC, abstractmethod
from typing import TYPE_CHECKING

from posthog.hogql import ast
from posthog.hogql.parser import parse_expr, parse_select

from products.web_analytics.backend.hogql_queries.query_constants.stats_table_queries import (
    FRUSTRATION_METRICS_INNER_QUERY,
    MAIN_INNER_QUERY,
    PATH_BOUNCE_AND_AVG_TIME_QUERY,
    PATH_BOUNCE_QUERY,
)

if TYPE_CHECKING:
    from products.web_analytics.backend.hogql_queries.stats_table import WebStatsTableQueryRunner


class StatsTableQueryStrategy(ABC):
    """Each subclass represents a distinct SQL query structure.

    The runner delegates to the strategy returned by ``_get_strategy()``.
    Strategies call back into ``self.runner`` for shared helpers (breakdown
    values, property filters, period expressions, ordering, fill fractions).
    """

    def __init__(self, runner: WebStatsTableQueryRunner) -> None:
        self.runner = runner

    @abstractmethod
    def build_query(self) -> ast.SelectQuery: ...

    def _finalize_query(self, query: ast.SelectQuery) -> ast.SelectQuery:
        columns = [select.alias for select in query.select if isinstance(select, ast.Alias)]
        query.order_by = self.runner._order_by(columns)
        fill_fraction = self.runner._fill_fraction(query.order_by)
        if fill_fraction:
            query.select.append(fill_fraction)
        return query


class SimpleBreakdownStrategy(StatsTableQueryStrategy):
    """Default query for simple-dimension breakdowns.

    Used by UTM / device / browser / OS / geo / language / timezone
    breakdowns, PAGE with conversion goals or without special metrics,
    and INITIAL_PAGE with bounce rate (via *breakdown_override*).

    INITIAL_CHANNEL_TYPE has its own ``ChannelTypeStrategy`` subclass so
    the query tag can be attributed separately even though the SQL shape
    is identical.
    """

    def __init__(
        self,
        runner: WebStatsTableQueryRunner,
        breakdown_override: ast.Expr | None = None,
    ) -> None:
        super().__init__(runner)
        self.breakdown_override = breakdown_override

    def build_query(self) -> ast.SelectQuery:
        breakdown = self.breakdown_override or self.runner._counts_breakdown_value()

        with self.runner.timings.measure(self.runner.query_strategy()):
            selects: list[ast.Expr] = [
                ast.Alias(alias="context.columns.breakdown_value", expr=self.runner._processed_breakdown_value()),
                self.runner._period_comparison_tuple("filtered_person_id", "context.columns.visitors", "uniq"),
            ]

            if self.runner.query.conversionGoal is not None:
                selects.extend(
                    [
                        self.runner._period_comparison_tuple(
                            "conversion_count", "context.columns.total_conversions", "sum"
                        ),
                        self.runner._period_comparison_tuple(
                            "conversion_person_id", "context.columns.unique_conversions", "uniq"
                        ),
                        ast.Alias(
                            alias="context.columns.conversion_rate",
                            expr=ast.Tuple(
                                exprs=[
                                    parse_expr(
                                        "if(`context.columns.visitors`.1 = 0, NULL, `context.columns.unique_conversions`.1 / `context.columns.visitors`.1)"
                                    ),
                                    parse_expr(
                                        "if(`context.columns.visitors`.2 = 0, NULL, `context.columns.unique_conversions`.2 / `context.columns.visitors`.2)"
                                    ),
                                ]
                            ),
                        ),
                    ]
                )
            else:
                selects.append(
                    self.runner._period_comparison_tuple("filtered_pageview_count", "context.columns.views", "sum"),
                )

                if self.runner._include_extra_aggregation_value():
                    selects.append(self.runner._extra_aggregation_value())

                if self.runner.query.includeBounceRate:
                    selects.append(
                        self.runner._period_comparison_tuple("is_bounce", "context.columns.bounce_rate", "avg")
                    )

            order_by = self.runner._order_by(
                columns=[select.alias for select in selects if isinstance(select, ast.Alias)]
            )
            fill_fraction_expr = self.runner._fill_fraction(order_by)
            if fill_fraction_expr:
                selects.append(fill_fraction_expr)

            query = ast.SelectQuery(
                select=selects,
                select_from=ast.JoinExpr(table=self._inner_query(breakdown)),
                group_by=[ast.Field(chain=["context.columns.breakdown_value"])],
                order_by=order_by,
                having=self.runner.outer_where_breakdown(),
            )

        return query

    def _inner_query(self, breakdown: ast.Expr) -> ast.SelectQuery:
        query = parse_select(
            MAIN_INNER_QUERY,
            timings=self.runner.timings,
            placeholders={
                "breakdown_value": breakdown,
                "event_where": self.runner.event_type_expr,
                "all_properties": self.runner._all_properties(),
                "inside_periods": self.runner._periods_expression(),
            },
        )

        assert isinstance(query, ast.SelectQuery)

        if self.runner.conversion_count_expr and self.runner.conversion_person_id_expr:
            query.select.append(ast.Alias(alias="conversion_count", expr=self.runner.conversion_count_expr))
            query.select.append(ast.Alias(alias="conversion_person_id", expr=self.runner.conversion_person_id_expr))

        return query


class ChannelTypeStrategy(SimpleBreakdownStrategy):
    """INITIAL_CHANNEL_TYPE breakdown.

    Shares the ``MAIN_INNER_QUERY`` skeleton with ``SimpleBreakdownStrategy``,
    but the breakdown value ``session.$channel_type`` is NOT a single field
    lookup. In ``sessions_v2.py`` it unfolds via ``create_channel_type_expr``
    into a multi-input case expression composing ten entry-level session
    fields (``$entry_utm_{campaign,medium,source}``,
    ``$entry_{current_url,hostname,pathname,referring_domain,gad_source}``,
    plus ``isNotNull`` on ``$entry_{gclid,fbclid}``) and applies any
    ``customChannelTypeRules`` from the query modifiers. That makes
    per-row work materially heavier than other simple breakdowns, which
    is why this gets its own tag for attribution even though the outer
    SQL is the same template."""


class PathBounceStrategy(StatsTableQueryStrategy):
    """PAGE breakdown with bounce rate (no scroll depth or avg time)."""

    def build_query(self) -> ast.SelectQuery:
        with self.runner.timings.measure("stats_table_path_bounce"):
            query = parse_select(
                PATH_BOUNCE_QUERY,
                timings=self.runner.timings,
                placeholders={
                    "breakdown_value": self.runner._counts_breakdown_value(),
                    "session_properties": self.runner._session_properties(),
                    "event_properties": self.runner._event_properties(),
                    "bounce_event_properties": self.runner._event_properties_for_bounce_rate(),
                    "bounce_breakdown_value": self.runner._bounce_entry_pathname_breakdown(),
                    "current_period": self.runner._current_period_expression(),
                    "previous_period": self.runner._previous_period_expression(),
                    "inside_periods": self.runner._periods_expression(),
                },
            )
        assert isinstance(query, ast.SelectQuery)
        return self._finalize_query(query)


class PathBounceAvgTimeStrategy(StatsTableQueryStrategy):
    """PAGE breakdown with average time on page and bounce rate."""

    def build_query(self) -> ast.SelectQuery:
        with self.runner.timings.measure("stats_table_path_bounce_and_avg_time"):
            query = parse_select(
                PATH_BOUNCE_AND_AVG_TIME_QUERY,
                timings=self.runner.timings,
                placeholders={
                    "breakdown_value": self.runner._counts_breakdown_value(),
                    "session_properties": self.runner._session_properties(),
                    "event_properties": self.runner._event_properties(),
                    "time_on_page_event_properties": self.runner._event_properties_for_scroll(),
                    "time_on_page_breakdown_value": self.runner._scroll_prev_pathname_breakdown(),
                    "bounce_event_properties": self.runner._event_properties_for_bounce_rate(),
                    "bounce_breakdown_value": self.runner._bounce_entry_pathname_breakdown(),
                    "current_period": self.runner._current_period_expression(),
                    "previous_period": self.runner._previous_period_expression(),
                    "avg_current_period": self.runner._current_period_expression("timestamp"),
                    "avg_previous_period": self.runner._previous_period_expression("timestamp"),
                    "inside_periods": self.runner._periods_expression(),
                },
            )
        assert isinstance(query, ast.SelectQuery)
        return self._finalize_query(query)


class FrustrationMetricsStrategy(StatsTableQueryStrategy):
    """FRUSTRATION_METRICS breakdown: rage clicks, dead clicks, errors."""

    def build_query(self) -> ast.SelectQuery:
        with self.runner.timings.measure("stats_table_frustration_metrics"):
            selects: list[ast.Expr] = [
                ast.Alias(alias="context.columns.breakdown_value", expr=self.runner._processed_breakdown_value()),
                self.runner._period_comparison_tuple("rage_clicks_count", "context.columns.rage_clicks", "sum"),
                self.runner._period_comparison_tuple("dead_clicks_count", "context.columns.dead_clicks", "sum"),
                self.runner._period_comparison_tuple("errors_count", "context.columns.errors", "sum"),
            ]

            having_exprs: list[ast.Expr] = [self._having()]
            outer_breakdown = self.runner.outer_where_breakdown()
            if outer_breakdown:
                having_exprs.append(outer_breakdown)

            query = ast.SelectQuery(
                select=selects,
                select_from=ast.JoinExpr(table=self._inner_query()),
                group_by=[ast.Field(chain=["context.columns.breakdown_value"])],
                having=ast.And(exprs=having_exprs),
                order_by=self._order_by(),
            )

        return query

    def _inner_query(self) -> ast.SelectQuery:
        query = parse_select(
            FRUSTRATION_METRICS_INNER_QUERY,
            timings=self.runner.timings,
            placeholders={
                "breakdown_value": self.runner._counts_breakdown_value(),
                "event_where": parse_expr(
                    "events.event IN ('$pageview', '$screen', '$rageclick', '$dead_click', '$exception')"
                ),
                "all_properties": self.runner._all_properties(),
                "inside_periods": self.runner._periods_expression(),
            },
        )

        assert isinstance(query, ast.SelectQuery)
        return query

    def _having(self) -> ast.Expr:
        zero_tuple = ast.Tuple(exprs=[ast.Constant(value=0), ast.Constant(value=0)])
        return ast.Or(
            exprs=[
                ast.CompareOperation(
                    op=ast.CompareOperationOp.Gt,
                    left=ast.Field(chain=["context.columns.rage_clicks"]),
                    right=zero_tuple,
                ),
                ast.CompareOperation(
                    op=ast.CompareOperationOp.Gt,
                    left=ast.Field(chain=["context.columns.dead_clicks"]),
                    right=zero_tuple,
                ),
                ast.CompareOperation(
                    op=ast.CompareOperationOp.Gt,
                    left=ast.Field(chain=["context.columns.errors"]),
                    right=zero_tuple,
                ),
            ]
        )

    def _order_by(self) -> list[ast.OrderExpr]:
        return [
            ast.OrderExpr(expr=ast.Field(chain=["context.columns.errors"]), order="DESC"),
            ast.OrderExpr(expr=ast.Field(chain=["context.columns.rage_clicks"]), order="DESC"),
            ast.OrderExpr(expr=ast.Field(chain=["context.columns.dead_clicks"]), order="DESC"),
        ]
