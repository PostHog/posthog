from collections.abc import Iterator, Sequence
from typing import Optional, TypeVar

from posthog.schema import CachedWebGoalsQueryResponse, WebAnalyticsOrderByFields, WebGoalsQuery, WebGoalsQueryResponse

from posthog.hogql import ast
from posthog.hogql.parser import parse_select
from posthog.hogql.property import action_to_expr, get_property_type, property_to_expr
from posthog.hogql.query import execute_hogql_query

from products.actions.backend.models.action import Action
from products.web_analytics.backend.hogql_queries.web_analytics_query_runner import WebAnalyticsQueryRunner
from products.web_analytics.backend.hogql_queries.web_goals_lazy_precompute import (
    can_use_lazy_precompute,
    execute_lazy_precomputed_read,
)

# Returns an array `seq` split into chunks of size `size`
# Example:
# chunker([1, 2, 3, 4, 5], 2) -> [[1, 2], [3, 4], [5]]
T = TypeVar("T")


def chunker(seq: Sequence[T], size: int) -> Iterator[Sequence[T]]:
    for pos in range(0, len(seq), size):
        yield seq[pos : pos + size]


class NoActionsError(Exception):
    pass


class WebGoalsQueryRunner(WebAnalyticsQueryRunner[WebGoalsQueryResponse]):
    query: WebGoalsQuery
    cached_response: CachedWebGoalsQueryResponse

    def to_query(self) -> ast.SelectQuery | ast.SelectSetQuery:
        with self.timings.measure("actions"):
            actions = Action.objects.filter(team__project_id=self.team.project_id, deleted=False).order_by(
                "pinned_at", "-last_calculated_at"
            )[:5]
            if not actions:
                raise NoActionsError("No actions found")

        with self.timings.measure("date_expr"):
            current_period = self._current_period_expression("timestamp")
            previous_period = self._previous_period_expression("timestamp")

        with self.timings.measure("aliases"):
            inner_aliases: list[ast.Expr] = []
            outer_aliases: list[ast.Expr] = []
            action_exprs: list[ast.Expr] = []
            for n, action in enumerate(actions):
                expr = action_to_expr(action)
                action_exprs.append(expr)

                # Current/previous count
                inner_aliases.append(
                    ast.Alias(
                        alias=f"action_current_count_{n}",
                        expr=ast.Call(name="countIf", args=[ast.And(exprs=[expr, current_period])]),
                    )
                )
                inner_aliases.append(
                    ast.Alias(
                        alias=f"action_previous_count_{n}",
                        expr=ast.Call(name="countIf", args=[ast.And(exprs=[expr, previous_period])]),
                    )
                )

                # Current/Previous Person ID
                inner_aliases.append(
                    ast.Alias(
                        alias=f"action_current_person_id_{n}",
                        expr=ast.Call(
                            name="if",
                            args=[
                                ast.CompareOperation(
                                    op=ast.CompareOperationOp.Gt,
                                    left=ast.Field(chain=[f"action_current_count_{n}"]),
                                    right=ast.Constant(value=0),
                                ),
                                ast.Field(chain=["web_goals_person_id"]),
                                ast.Constant(value=None),
                            ],
                        ),
                    )
                )

                inner_aliases.append(
                    ast.Alias(
                        alias=f"action_previous_person_id_{n}",
                        expr=ast.Call(
                            name="if",
                            args=[
                                ast.CompareOperation(
                                    op=ast.CompareOperationOp.Gt,
                                    left=ast.Field(chain=[f"action_previous_count_{n}"]),
                                    right=ast.Constant(value=0),
                                ),
                                ast.Field(chain=["web_goals_person_id"]),
                                ast.Constant(value=None),
                            ],
                        ),
                    )
                )

                # Outer aliases
                outer_aliases.append(ast.Alias(alias=f"action_name_{n}", expr=ast.Constant(value=action.name)))
                outer_aliases.append(
                    ast.Alias(
                        alias=f"action_total_{n}",
                        expr=ast.Tuple(
                            exprs=[
                                ast.Call(name="sum", args=[ast.Field(chain=[f"action_current_count_{n}"])]),
                                ast.Call(name="sum", args=[ast.Field(chain=[f"action_previous_count_{n}"])])
                                if self.query_compare_to_date_range
                                else ast.Constant(value=None),
                            ]
                        ),
                    ),
                )

                outer_aliases.append(
                    ast.Alias(
                        alias=f"action_uniques_{n}",
                        expr=ast.Tuple(
                            exprs=[
                                ast.Call(name="uniq", args=[ast.Field(chain=[f"action_current_person_id_{n}"])]),
                                ast.Call(name="uniq", args=[ast.Field(chain=[f"action_previous_person_id_{n}"])])
                                if self.query_compare_to_date_range
                                else ast.Constant(value=None),
                            ]
                        ),
                    ),
                )

        with self.timings.measure("inner_select"):
            inner_select = parse_select(
                """
SELECT
    any(events.person_id) as web_goals_person_id,
    min(session.$start_timestamp) as start_timestamp
FROM events
WHERE and(
    {events_session_id} IS NOT NULL,
    event = '$pageview' OR event = '$screen' OR {action_where},
    {periods_expression},
    {event_properties},
    {session_properties}
)
GROUP BY {events_session_id}
        """,
                placeholders={
                    "periods_expression": self._periods_expression("timestamp"),
                    "event_properties": self.event_properties(),
                    "session_properties": self.session_properties(),
                    "action_where": ast.Or(exprs=action_exprs),
                    "events_session_id": self.events_session_property,
                },
            )
            assert isinstance(inner_select, ast.SelectQuery)
            for alias in inner_aliases:
                inner_select.select.append(alias)

        with self.timings.measure("outer_select"):
            outer_select = parse_select(
                """
SELECT
    uniqIf(web_goals_person_id, {current_period}) as current_total_people,
    uniqIf(web_goals_person_id, {previous_period}) as previous_total_people
FROM {inner_select}
WHERE {periods_expression}
                """,
                placeholders={
                    "inner_select": inner_select,
                    "periods_expression": self._periods_expression("start_timestamp"),
                    "current_period": self._current_period_expression("start_timestamp"),
                    "previous_period": self._previous_period_expression("start_timestamp"),
                },
            )

            assert isinstance(outer_select, ast.SelectQuery)
            for alias in outer_aliases:
                outer_select.select.append(alias)

        return outer_select

    def _calculate(self):
        lazy_response = self._maybe_calculate_via_lazy_precompute()
        if lazy_response is not None:
            return lazy_response

        try:
            query = self.to_query()
        except NoActionsError:
            return WebGoalsQueryResponse(results=[], samplingRate=self._sample_rate, modifiers=self.modifiers)

        response = execute_hogql_query(
            query_type="web_goals_query",
            query=query,
            team=self.team,
            user=self.user,
            timings=self.timings,
            modifiers=self.modifiers,
            limit_context=self.limit_context,
        )
        assert response.results

        row = response.results[0]
        current_visitors = row[0]
        previous_visitors = row[1]

        results = []
        for action_name, action_total, action_unique in chunker(row[2:], 3):
            action_unique_current, action_unique_previous = action_unique
            current_action_rate = (
                action_unique_current / current_visitors
                if current_visitors > 0
                else 0
                if action_unique_current is not None
                else None
            )
            previous_action_rate = (
                action_unique_previous / previous_visitors
                if previous_visitors > 0
                else 0
                if action_unique_previous is not None
                else None
            )
            results.append([action_name, action_unique, action_total, (current_action_rate, previous_action_rate)])

        if self.query.orderBy is not None:
            index = None
            if self.query.orderBy[0] == WebAnalyticsOrderByFields.CONVERTING_USERS:
                index = 1
            elif self.query.orderBy[0] == WebAnalyticsOrderByFields.TOTAL_CONVERSIONS:
                index = 2
            elif self.query.orderBy[0] == WebAnalyticsOrderByFields.CONVERSION_RATE:
                index = 3

            if index is not None:
                # Sort by the current-period scalar only — `x[index]` is a
                # `(current, previous)` tuple and `previous` is `None` when
                # `include_previous=False`. Python's stable sort falls
                # through to compare the second element on ties, and
                # `None < int` raises `TypeError`. Indexing `[0]` keeps the
                # comparison on the scalar current value only.
                results.sort(key=lambda x: x[index][0], reverse=self.query.orderBy[1] == "DESC")

        return WebGoalsQueryResponse(
            columns=[
                "context.columns.action_name",
                "context.columns.converting_users",
                "context.columns.total_conversions",
                "context.columns.conversion_rate",
            ],
            results=results,
            samplingRate=self._sample_rate,
            modifiers=self.modifiers,
        )

    def _maybe_calculate_via_lazy_precompute(self) -> Optional[WebGoalsQueryResponse]:
        """Short-circuit through the goals lazy precompute table when eligible.

        Returns None on ineligibility or any failure, in which case the caller
        falls through to the live HogQL path.

        The lazy precompute reads each top-5 action's `count` / `unique persons`
        plus the per-period denominator (`action_id = -1` carrying every
        qualifying session's person). We pivot those back into the runner's
        response shape — `[action_name, (cur_unique, prev_unique), (cur_total,
        prev_total), (cur_rate, prev_rate)]` per action — matching the live
        path's `_calculate` exactly so consumers can't tell the two apart.
        """
        if not can_use_lazy_precompute(self):
            return None
        result = execute_lazy_precomputed_read(self)
        if result is None:
            return None
        return self._build_response_from_lazy(result)

    def _build_response_from_lazy(self, result: dict) -> WebGoalsQueryResponse:
        include_previous = self.query_compare_to_date_range is not None
        actions = result["actions"]
        denominator = result["denominator"]
        per_action = result["per_action"]

        current_visitors = denominator["current"]
        previous_visitors = denominator["previous"]

        results: list = []
        for action in actions:
            metrics = per_action.get(int(action.id))
            current_total = metrics["current_total"] if metrics else 0
            previous_total = metrics["previous_total"] if metrics else 0
            current_unique = metrics["current_unique"] if metrics else 0
            previous_unique = metrics["previous_unique"] if metrics else 0

            action_total = (current_total, previous_total if include_previous else None)
            action_unique = (current_unique, previous_unique if include_previous else None)

            current_rate = current_unique / current_visitors if current_visitors > 0 else 0
            previous_rate = (
                (previous_unique / previous_visitors if previous_visitors > 0 else 0) if include_previous else None
            )

            results.append([action.name, action_unique, action_total, (current_rate, previous_rate)])

        if self.query.orderBy is not None:
            index = None
            if self.query.orderBy[0] == WebAnalyticsOrderByFields.CONVERTING_USERS:
                index = 1
            elif self.query.orderBy[0] == WebAnalyticsOrderByFields.TOTAL_CONVERSIONS:
                index = 2
            elif self.query.orderBy[0] == WebAnalyticsOrderByFields.CONVERSION_RATE:
                index = 3
            if index is not None:
                # Sort by the current-period scalar only — `x[index]` is a
                # `(current, previous)` tuple and `previous` is `None` when
                # `include_previous=False`. Python's stable sort falls
                # through to compare the second element on ties, and
                # `None < int` raises `TypeError`. Indexing `[0]` keeps the
                # comparison on the scalar current value only.
                results.sort(key=lambda x: x[index][0], reverse=self.query.orderBy[1] == "DESC")

        return WebGoalsQueryResponse(
            columns=[
                "context.columns.action_name",
                "context.columns.converting_users",
                "context.columns.total_conversions",
                "context.columns.conversion_rate",
            ],
            results=results,
            samplingRate=self._sample_rate,
            modifiers=self.modifiers,
            usedPreAggregatedTables=True,
            usedLazyPrecompute=True,
        )

    def event_properties(self) -> ast.Expr:
        properties = [
            p for p in self.query.properties + self._test_account_filters if get_property_type(p) in ["event", "person"]
        ]
        return property_to_expr(properties, team=self.team, scope="event")

    def session_properties(self) -> ast.Expr:
        properties = [
            p for p in self.query.properties + self._test_account_filters if get_property_type(p) == "session"
        ]
        return property_to_expr(properties, team=self.team, scope="event")
