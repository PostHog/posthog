"""Conversion paths: the most common touchpoint sequences that end in a conversion.

The attribution table answers "how much credit does each channel deserve"; this runner answers "what do
the journeys actually look like". Each conversion contributes one path — its in-window touchpoints in
time order, mapped to the selected breakdown dimension — and identical paths are grouped and ranked by
how many conversions they produced.

Consecutive repeats are deliberately preserved (a path of Direct, Direct is not the same journey as one
Direct visit): the frontend collapses them to "Direct ×2" for display, but grouping happens on the raw
sequence. Touchpoint definitions, exclusions and the person-array collection are shared with the
attribution table via `AttributionQueryRunnerBase`, so a journey shown here is exactly the journey the
models credited there.
"""

from typing import Any

from posthog.schema import (
    CachedMarketingAnalyticsAttributionPathsQueryResponse,
    MarketingAnalyticsAttributionPathRow,
    MarketingAnalyticsAttributionPathsQuery,
    MarketingAnalyticsAttributionPathsQueryResponse,
)

from posthog.hogql import ast
from posthog.hogql.constants import LimitContext
from posthog.hogql.query import execute_hogql_query

from .attribution_base import PERSON_ARRAYS_CTE, AttributionQueryRunnerBase
from .constants import PAGINATION_EXTRA

# Paths longer than this are grouped on their most recent steps — the same truncation direction as
# MAX_TOUCHPOINTS_PER_PERSON, and for the same reason: the touches nearest the conversion are the ones
# every model agrees matter. Untruncated grouping would also shatter heavy users' journeys into
# hundreds of singleton rows that can never rank.
PATH_MAX_LENGTH = 10

# Fewer than the table's DEFAULT_LIMIT: paths are a long-tail distribution and row 51 is almost always
# a singleton.
PATHS_DEFAULT_LIMIT = 50

# CTE names.
_PER_CONVERSION_PATH_CTE = "per_conversion_path"
_PATH_ROWS_CTE = "path_rows"
_FOOTER_CTE = "paths_footer"

_PATH = "path"
_CONVERSIONS = "conversions"
_CONVERSION_VALUE = "conversion_value"
_PATH_TRUNCATED = "path_truncated"
_TOTAL_CONVERSIONS = "total_conversions"
_ATTRIBUTED_CONVERSIONS = "attributed_conversions"
_JOIN_KEY = "footer_key"
# ARRAY JOIN index identifying a conversion within its person.
_CONVERSION_INDEX = "i"


class MarketingAnalyticsAttributionPathsQueryRunner(
    AttributionQueryRunnerBase[MarketingAnalyticsAttributionPathsQueryResponse]
):
    query: MarketingAnalyticsAttributionPathsQuery
    response: MarketingAnalyticsAttributionPathsQueryResponse
    cached_response: CachedMarketingAnalyticsAttributionPathsQueryResponse

    def _validated_touchpoint_bounds(self) -> tuple[int | None, int | None]:
        """The min/max filter, checked because the schema types them as plain integers.

        Bounds are judged on the journey's original length, before truncation, so "4+" keeps meaning
        what it says for a 30-touch journey.
        """
        minimum, maximum = self.query.minTouchpoints, self.query.maxTouchpoints
        if minimum is not None and minimum < 1:
            raise ValueError("minTouchpoints must be at least 1")
        if maximum is not None and maximum < 1:
            raise ValueError("maxTouchpoints must be at least 1")
        if minimum is not None and maximum is not None and minimum > maximum:
            raise ValueError("minTouchpoints can't exceed maxTouchpoints")
        return minimum, maximum

    # ------------------------------------------------------------------ CTEs

    def _build_per_conversion_path_select(self) -> ast.SelectQuery:
        """One row per conversion, carrying its path and pre-truncation length.

        `orig_len` travels alongside the truncated path so both the touchpoint-count filter and the
        footer can see the journey's true size after the path itself has been capped.
        """
        conversion = ast.ArrayAccess(
            array=ast.Field(chain=["conversions"]), property=ast.Field(chain=[_CONVERSION_INDEX])
        )

        return ast.SelectQuery(
            select=[
                ast.Alias(alias="conv_value", expr=ast.TupleAccess(tuple=conversion, index=2)),
                ast.Alias(
                    alias="tps",
                    expr=self._in_window_touchpoints_expr(ast.TupleAccess(tuple=conversion, index=1)),
                ),
                ast.Alias(
                    alias="path_full",
                    expr=ast.Call(
                        name="arrayMap",
                        args=[
                            ast.Lambda(args=["t"], expr=ast.TupleAccess(tuple=ast.Field(chain=["t"]), index=2)),
                            ast.Field(chain=["tps"]),
                        ],
                    ),
                ),
                ast.Alias(alias="orig_len", expr=ast.Call(name="length", args=[ast.Field(chain=["path_full"])])),
                ast.Alias(
                    alias=_PATH,
                    expr=ast.Call(
                        name="arraySlice",
                        args=[ast.Field(chain=["path_full"]), ast.Constant(value=-PATH_MAX_LENGTH)],
                    ),
                ),
                ast.Alias(
                    alias="truncated",
                    expr=ast.CompareOperation(
                        left=ast.Field(chain=["orig_len"]),
                        op=ast.CompareOperationOp.Gt,
                        right=ast.Constant(value=PATH_MAX_LENGTH),
                    ),
                ),
            ],
            select_from=ast.JoinExpr(table=ast.Field(chain=[PERSON_ARRAYS_CTE])),
            array_join_op="ARRAY JOIN",
            array_join_list=[
                ast.Alias(
                    alias=_CONVERSION_INDEX,
                    expr=ast.Call(name="arrayEnumerate", args=[ast.Field(chain=["conversions"])]),
                )
            ],
        )

    def _build_path_rows_select(self) -> ast.SelectQuery:
        """Group identical paths and count their conversions.

        The touchpoint-count filter lives here and only here: the footer reads the unfiltered CTE, so
        switching between "Any" and "exactly 2" re-ranks the rows without moving the share denominator.
        """
        minimum, maximum = self._validated_touchpoint_bounds()

        conditions: list[ast.Expr] = [
            # A conversion with no in-window touchpoint has no journey to show; it is still counted by
            # the footer as unattributed.
            ast.CompareOperation(
                left=ast.Field(chain=["orig_len"]),
                op=ast.CompareOperationOp.Gt,
                right=ast.Constant(value=0),
            )
        ]
        if minimum is not None:
            conditions.append(
                ast.CompareOperation(
                    left=ast.Field(chain=["orig_len"]),
                    op=ast.CompareOperationOp.GtEq,
                    right=ast.Constant(value=minimum),
                )
            )
        if maximum is not None:
            conditions.append(
                ast.CompareOperation(
                    left=ast.Field(chain=["orig_len"]),
                    op=ast.CompareOperationOp.LtEq,
                    right=ast.Constant(value=maximum),
                )
            )

        return ast.SelectQuery(
            select=[
                ast.Field(chain=[_PATH]),
                ast.Alias(alias=_CONVERSIONS, expr=ast.Call(name="count", args=[])),
                ast.Alias(alias=_CONVERSION_VALUE, expr=ast.Call(name="sum", args=[ast.Field(chain=["conv_value"])])),
                # max() rather than any(): one truncated journey in the group is enough to warrant the
                # "starts earlier" marker.
                ast.Alias(alias=_PATH_TRUNCATED, expr=ast.Call(name="max", args=[ast.Field(chain=["truncated"])])),
                ast.Alias(alias=_JOIN_KEY, expr=ast.Constant(value=1)),
            ],
            select_from=ast.JoinExpr(table=ast.Field(chain=[_PER_CONVERSION_PATH_CTE])),
            where=ast.And(exprs=conditions),
            group_by=[ast.Field(chain=[_PATH])],
        )

    def _build_footer_select(self) -> ast.SelectQuery:
        """One row reconciling total against attributed conversions.

        Same shape and reasoning as the attribution table's footer: its own CTE so a filter value that
        matches no paths still reports "you have N conversions" rather than zeros.
        """
        return ast.SelectQuery(
            select=[
                ast.Alias(alias=_TOTAL_CONVERSIONS, expr=ast.Call(name="count", args=[])),
                ast.Alias(
                    alias=_ATTRIBUTED_CONVERSIONS,
                    expr=ast.Call(
                        name="countIf",
                        args=[
                            ast.CompareOperation(
                                left=ast.Field(chain=["orig_len"]),
                                op=ast.CompareOperationOp.Gt,
                                right=ast.Constant(value=0),
                            )
                        ],
                    ),
                ),
                ast.Alias(alias=_JOIN_KEY, expr=ast.Constant(value=1)),
            ],
            select_from=ast.JoinExpr(table=ast.Field(chain=[_PER_CONVERSION_PATH_CTE])),
        )

    def _build_outer_select(self) -> ast.SelectQuery:
        """Attach the footer counts to every row.

        LEFT from the footer, which always has exactly one row, so the reconciliation survives a filter
        that matched nothing. That leaves one placeholder row when there is nothing to show; `_JOIN_KEY`
        is 0 on it, and `_calculate` drops it.
        """
        row_columns = [_PATH, _CONVERSIONS, _CONVERSION_VALUE, _PATH_TRUNCATED]
        select: list[ast.Expr] = [
            ast.Alias(alias=name, expr=ast.Field(chain=[_PATH_ROWS_CTE, name])) for name in row_columns
        ]
        select.extend(
            [
                ast.Alias(alias=_TOTAL_CONVERSIONS, expr=ast.Field(chain=[_FOOTER_CTE, _TOTAL_CONVERSIONS])),
                ast.Alias(alias=_ATTRIBUTED_CONVERSIONS, expr=ast.Field(chain=[_FOOTER_CTE, _ATTRIBUTED_CONVERSIONS])),
                ast.Alias(alias=_JOIN_KEY, expr=ast.Field(chain=[_PATH_ROWS_CTE, _JOIN_KEY])),
            ]
        )

        return ast.SelectQuery(
            select=select,
            select_from=ast.JoinExpr(
                table=ast.Field(chain=[_FOOTER_CTE]),
                next_join=ast.JoinExpr(
                    join_type="LEFT JOIN",
                    table=ast.Field(chain=[_PATH_ROWS_CTE]),
                    constraint=ast.JoinConstraint(
                        expr=ast.CompareOperation(
                            left=ast.Field(chain=[_FOOTER_CTE, _JOIN_KEY]),
                            op=ast.CompareOperationOp.Eq,
                            right=ast.Field(chain=[_PATH_ROWS_CTE, _JOIN_KEY]),
                        ),
                        constraint_type="ON",
                    ),
                ),
            ),
            # The path tie-break makes equal-count rows return in a stable order across refetches, so
            # rows don't shuffle when the user toggles the touchpoint filter back and forth.
            order_by=[
                ast.OrderExpr(expr=ast.Field(chain=[_CONVERSIONS]), order="DESC"),
                ast.OrderExpr(expr=ast.Field(chain=[_PATH]), order="ASC"),
            ],
            limit=ast.Constant(value=(self.query.limit or PATHS_DEFAULT_LIMIT) + PAGINATION_EXTRA),
            offset=ast.Constant(value=self.query.offset or 0),
        )

    # ------------------------------------------------------------------ main query

    def to_query(self) -> ast.SelectQuery:
        date_range = self.query_date_range

        ctes: dict[str, ast.CTE] = {}
        with self.timings.measure("attribution_paths_person_arrays_cte"):
            ctes[PERSON_ARRAYS_CTE] = ast.CTE(
                name=PERSON_ARRAYS_CTE,
                expr=self._build_person_arrays_select(date_range),
                cte_type="subquery",
            )
        # Materialized because two CTEs read it, and ClickHouse otherwise re-evaluates a CTE at each
        # reference: without this the events scan underneath it happens twice.
        ctes[_PER_CONVERSION_PATH_CTE] = ast.CTE(
            name=_PER_CONVERSION_PATH_CTE,
            expr=self._build_per_conversion_path_select(),
            cte_type="subquery",
            materialized=True,
        )
        ctes[_PATH_ROWS_CTE] = ast.CTE(name=_PATH_ROWS_CTE, expr=self._build_path_rows_select(), cte_type="subquery")
        ctes[_FOOTER_CTE] = ast.CTE(name=_FOOTER_CTE, expr=self._build_footer_select(), cte_type="subquery")

        query = self._build_outer_select()
        query.ctes = ctes
        return query

    # ------------------------------------------------------------------ execution

    def _calculate(self) -> MarketingAnalyticsAttributionPathsQueryResponse:
        query = self.to_query()

        response = execute_hogql_query(
            query_type="marketing_analytics_attribution_paths_query",
            query=query,
            team=self.team,
            user=self.user,
            timings=self.timings,
            modifiers=self.modifiers,
            limit_context=self.limit_context or LimitContext.QUERY,
            context=self._shared_hogql_context,
        )

        # Mapped by column name, not tuple position, so adding a column can't shift every later one.
        columns = response.columns or []
        named_results = [dict(zip(columns, row)) for row in response.results or []]

        # Every row carries the same reconciliation totals, so read them off the first one. Read before
        # the placeholder row is dropped, since that row exists precisely to carry them when there are
        # no path rows.
        first = named_results[0] if named_results else {}
        total_conversions = int(first.get(_TOTAL_CONVERSIONS) or 0)
        attributed_conversions = int(first.get(_ATTRIBUTED_CONVERSIONS) or 0)

        named_results = [row for row in named_results if row.get(_JOIN_KEY)]

        requested_limit = self.query.limit or PATHS_DEFAULT_LIMIT
        has_more = len(named_results) > requested_limit
        if has_more:
            named_results = named_results[:requested_limit]

        has_value = bool(self.goal.counts_as_revenue)
        rows = [self._build_row(row, has_value=has_value) for row in named_results]

        return MarketingAnalyticsAttributionPathsQueryResponse(
            results=rows,
            totalConversions=total_conversions,
            attributedConversions=attributed_conversions,
            attributionWindowDays=self.lookback_window_days,
            hasValue=has_value,
            hogql=response.hogql,
            timings=response.timings,
            modifiers=self.modifiers,
            hasMore=has_more,
            limit=requested_limit,
            offset=self.query.offset or 0,
        )

    @staticmethod
    def _build_row(row: dict[str, Any], *, has_value: bool) -> MarketingAnalyticsAttributionPathRow:
        return MarketingAnalyticsAttributionPathRow(
            path=[str(step) for step in (row.get(_PATH) or [])],
            conversions=int(row.get(_CONVERSIONS) or 0),
            conversionValue=float(row.get(_CONVERSION_VALUE) or 0.0) if has_value else None,
            pathTruncated=bool(row.get(_PATH_TRUNCATED)),
        )
