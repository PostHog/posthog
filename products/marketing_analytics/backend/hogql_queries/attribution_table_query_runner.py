"""Attribution table: every attribution model's credit for one conversion goal, side by side.

The Dashboard applies the team's single configured `attribution_mode`. This runner instead computes all
five models in one pass, so a marketer can see how differently each channel gets paid depending on how
credit is split — a channel that looks great under last touch and poor under first touch is a channel
whose spend is being misjudged.

Two things differ deliberately from the Dashboard's attribution pipeline in `conversion_goal_processor`:

1. A touchpoint here is a **session**, identified through the `events.session` lazy join, not a
   UTM-tagged pageview. That means Direct / Organic search / Referral appear as rows (the whole point of
   comparing models is seeing what unpaid touches contribute), and a visitor who lands with a UTM and
   browses ten pages counts once rather than ten times.
2. Only one dimension is tracked instead of nine, because the table breaks down by one at a time.

Consequence worth knowing: the Last touch column will not equal the Dashboard's conversion count for the
same goal and window, because the Dashboard only ever sees UTM-tagged pageviews.
"""

from typing import Any

from posthog.schema import (
    AttributionMode,
    CachedMarketingAnalyticsAttributionQueryResponse,
    MarketingAnalyticsAttributionModelCell,
    MarketingAnalyticsAttributionQuery,
    MarketingAnalyticsAttributionQueryResponse,
    MarketingAnalyticsAttributionRow,
)

from posthog.hogql import ast
from posthog.hogql.constants import LimitContext
from posthog.hogql.query import execute_hogql_query

from posthog.hogql_queries.utils.query_date_range import QueryDateRange

from .attribution_base import PERSON_ARRAYS_CTE, AttributionQueryRunnerBase
from .attribution_weights import (
    build_first_touch_weights,
    build_last_touch_weights,
    build_linear_weights,
    build_position_based_weights,
    build_time_decay_weights,
)
from .constants import DEFAULT_LIMIT, PAGINATION_EXTRA

# Column order for the table's model groups: single-touch first, then multi-touch, so the columns read
# left to right from the crudest split to the most nuanced.
MODEL_ORDER: list[AttributionMode] = [
    AttributionMode.FIRST_TOUCH,
    AttributionMode.LAST_TOUCH,
    AttributionMode.LINEAR,
    AttributionMode.TIME_DECAY,
    AttributionMode.POSITION_BASED,
]

# Per-model weight column aliases, parallel to MODEL_ORDER.
_WEIGHT_ALIASES: dict[AttributionMode, str] = {
    AttributionMode.FIRST_TOUCH: "w_first",
    AttributionMode.LAST_TOUCH: "w_last",
    AttributionMode.LINEAR: "w_linear",
    AttributionMode.TIME_DECAY: "w_decay",
    AttributionMode.POSITION_BASED: "w_position",
}

# CTE names.
_REACH_CTE = "influenced_reach"
_PER_CONVERSION_CTE = "per_conversion"
_PER_TOUCHPOINT_CTE = "per_touchpoint"
_PER_CONVERSION_DIM_CTE = "per_conversion_dim"
_TOTALS_CTE = "attribution_totals"
_ROWS_CTE = "attribution_rows"
_FOOTER_CTE = "attribution_footer"

_BREAKDOWN_VALUE = "breakdown_value"
_VISITORS = "visitors"
_INFLUENCED_CONVERSIONS = "influenced_conversions"
_INFLUENCED_VALUE = "influenced_value"
_TOTAL_CONVERSIONS = "total_conversions"
_ATTRIBUTED_CONVERSIONS = "attributed_conversions"
_JOIN_KEY = "footer_key"
# ARRAY JOIN index identifying a conversion within its person.
_CONVERSION_INDEX = "i"


def _ordered_weight_aliases() -> list[str]:
    """Producers and consumers of the per-model columns iterate this rather than `_WEIGHT_ALIASES.values()`,
    so reordering that dict literal can't pair one model's numbers with another's column."""
    return [_WEIGHT_ALIASES[model] for model in MODEL_ORDER]


class MarketingAnalyticsAttributionQueryRunner(AttributionQueryRunnerBase[MarketingAnalyticsAttributionQueryResponse]):
    query: MarketingAnalyticsAttributionQuery
    response: MarketingAnalyticsAttributionQueryResponse
    cached_response: CachedMarketingAnalyticsAttributionQueryResponse

    # ------------------------------------------------------------------ CTEs

    def _build_reach_select(self, date_range: QueryDateRange) -> ast.SelectQuery:
        """(A) Unique visitors per dimension, converters or not.

        Shares the touchpoint definition and the lookback-extended window with the credit side. Bounding
        visitors to the display window instead let a conversion be credited to a touch from before the
        range while its person was missing from the denominator, reporting rates above 100%.
        """
        breakdown = self._breakdown_expr()
        return ast.SelectQuery(
            select=[
                ast.Alias(alias=_BREAKDOWN_VALUE, expr=breakdown),
                ast.Alias(
                    alias=_VISITORS,
                    expr=ast.Call(name="uniq", args=[ast.Field(chain=["events", "person_id"])]),
                ),
            ],
            select_from=ast.JoinExpr(table=ast.Field(chain=["events"])),
            where=ast.And(
                exprs=[
                    self._touchpoint_condition(),
                    *self._lookback_date_conditions(date_range),
                ]
            ),
            group_by=[ast.Field(chain=[_BREAKDOWN_VALUE])],
        )

    def _build_per_conversion_select(self) -> ast.SelectQuery:
        """(D) One row per conversion, carrying all five weight arrays.

        Every builder maps over the same `ts`, so all five arrays have identical length — that is what
        lets (E) explode them with a single shared ARRAY JOIN instead of five.
        """
        conversion_time = ast.Field(chain=["conversion_time"])
        ts = ast.Field(chain=["touch_ts"])

        in_window = self._in_window_touchpoints_expr(conversion_time)

        conversion = ast.ArrayAccess(
            array=ast.Field(chain=["conversions"]), property=ast.Field(chain=[_CONVERSION_INDEX])
        )

        select: list[ast.Expr] = [
            ast.Field(chain=["person_id"]),
            # The ARRAY JOIN index identifies this conversion within the person. Carried downstream
            # because timestamps don't: they're truncated to whole seconds, so two conversions in the
            # same second would otherwise group together as one.
            ast.Field(chain=[_CONVERSION_INDEX]),
            ast.Alias(alias="conversion_time", expr=ast.TupleAccess(tuple=conversion, index=1)),
            ast.Alias(alias="conversion_value", expr=ast.TupleAccess(tuple=conversion, index=2)),
            ast.Alias(alias="tps", expr=in_window),
            ast.Alias(
                # Deliberately not named `ts`: attribution_weights substitutes this reference inside
                # arrayMap lambdas whose parameter is `ts`, and the shadowed name would resolve to the
                # scalar argument instead of the array.
                alias="touch_ts",
                expr=ast.Call(
                    name="arrayMap",
                    args=[
                        ast.Lambda(args=["t"], expr=ast.TupleAccess(tuple=ast.Field(chain=["t"]), index=1)),
                        ast.Field(chain=["tps"]),
                    ],
                ),
            ),
            ast.Alias(
                alias="dims",
                expr=ast.Call(
                    name="arrayMap",
                    args=[
                        ast.Lambda(args=["t"], expr=ast.TupleAccess(tuple=ast.Field(chain=["t"]), index=2)),
                        ast.Field(chain=["tps"]),
                    ],
                ),
            ),
            ast.Alias(alias=_WEIGHT_ALIASES[AttributionMode.FIRST_TOUCH], expr=build_first_touch_weights(ts)),
            ast.Alias(alias=_WEIGHT_ALIASES[AttributionMode.LAST_TOUCH], expr=build_last_touch_weights(ts)),
            ast.Alias(alias=_WEIGHT_ALIASES[AttributionMode.LINEAR], expr=build_linear_weights(ts)),
            ast.Alias(
                alias=_WEIGHT_ALIASES[AttributionMode.TIME_DECAY],
                expr=build_time_decay_weights(ts, conversion_time, self.attribution_window_seconds),
            ),
            ast.Alias(alias=_WEIGHT_ALIASES[AttributionMode.POSITION_BASED], expr=build_position_based_weights(ts)),
        ]

        return ast.SelectQuery(
            select=select,
            select_from=ast.JoinExpr(table=ast.Field(chain=[PERSON_ARRAYS_CTE])),
            array_join_op="ARRAY JOIN",
            array_join_list=[
                ast.Alias(
                    alias=_CONVERSION_INDEX,
                    expr=ast.Call(name="arrayEnumerate", args=[ast.Field(chain=["conversions"])]),
                )
            ],
        )

    def _build_per_touchpoint_select(self) -> ast.SelectQuery:
        """(E) One row per touchpoint, indexing all five weight arrays off one ARRAY JOIN."""
        k = ast.Field(chain=["k"])
        select: list[ast.Expr] = [
            ast.Field(chain=["person_id"]),
            ast.Field(chain=[_CONVERSION_INDEX]),
            ast.Field(chain=["conversion_value"]),
            ast.Alias(
                alias=_BREAKDOWN_VALUE,
                expr=ast.ArrayAccess(array=ast.Field(chain=["dims"]), property=k),
            ),
        ]
        for alias in _ordered_weight_aliases():
            select.append(ast.Alias(alias=alias, expr=ast.ArrayAccess(array=ast.Field(chain=[alias]), property=k)))

        return ast.SelectQuery(
            select=select,
            select_from=ast.JoinExpr(table=ast.Field(chain=[_PER_CONVERSION_CTE])),
            array_join_op="ARRAY JOIN",
            array_join_list=[
                ast.Alias(alias="k", expr=ast.Call(name="arrayEnumerate", args=[ast.Field(chain=["touch_ts"])]))
            ],
        )

    def _build_per_conversion_dim_select(self) -> ast.SelectQuery:
        """(F) Collapse repeat touches on the same dimension within one conversion.

        Gives "influenced" its once-per-conversion semantics, and rolls the weights up: a channel touched
        on 3 of 5 sessions earns 0.6 of the linear credit as one row, not three rows of 0.2.

        Keyed on the conversion's index within its person, not its timestamp: timestamps are truncated to
        whole seconds, so two conversions in the same second would merge into one.
        """
        select: list[ast.Expr] = [
            ast.Field(chain=[_BREAKDOWN_VALUE]),
            ast.Field(chain=["person_id"]),
            ast.Field(chain=[_CONVERSION_INDEX]),
            ast.Alias(alias="conv_value", expr=ast.Call(name="any", args=[ast.Field(chain=["conversion_value"])])),
        ]
        for alias in _ordered_weight_aliases():
            select.append(ast.Alias(alias=alias, expr=ast.Call(name="sum", args=[ast.Field(chain=[alias])])))

        return ast.SelectQuery(
            select=select,
            select_from=ast.JoinExpr(table=ast.Field(chain=[_PER_TOUCHPOINT_CTE])),
            group_by=[
                ast.Field(chain=[_BREAKDOWN_VALUE]),
                ast.Field(chain=["person_id"]),
                ast.Field(chain=[_CONVERSION_INDEX]),
            ],
        )

    def _build_totals_select(self) -> ast.SelectQuery:
        """(G) One row per dimension: influenced counts plus each model's weighted credit."""
        select: list[ast.Expr] = [
            ast.Field(chain=[_BREAKDOWN_VALUE]),
            ast.Alias(alias=_INFLUENCED_CONVERSIONS, expr=ast.Call(name="count", args=[])),
            ast.Alias(alias=_INFLUENCED_VALUE, expr=ast.Call(name="sum", args=[ast.Field(chain=["conv_value"])])),
        ]
        for alias in _ordered_weight_aliases():
            select.append(
                ast.Alias(alias=f"{alias}_conversions", expr=ast.Call(name="sum", args=[ast.Field(chain=[alias])]))
            )
            select.append(
                ast.Alias(
                    alias=f"{alias}_value",
                    expr=ast.Call(
                        name="sum",
                        args=[
                            ast.ArithmeticOperation(
                                left=ast.Field(chain=["conv_value"]),
                                op=ast.ArithmeticOperationOp.Mult,
                                right=ast.Field(chain=[alias]),
                            )
                        ],
                    ),
                )
            )

        return ast.SelectQuery(
            select=select,
            select_from=ast.JoinExpr(table=ast.Field(chain=[_PER_CONVERSION_DIM_CTE])),
            group_by=[ast.Field(chain=[_BREAKDOWN_VALUE])],
        )

    # ------------------------------------------------------------------ main query

    def to_query(self) -> ast.SelectQuery:
        date_range = self.query_date_range

        ctes: dict[str, ast.CTE] = {}
        with self.timings.measure("attribution_reach_cte"):
            ctes[_REACH_CTE] = ast.CTE(name=_REACH_CTE, expr=self._build_reach_select(date_range), cte_type="subquery")
        with self.timings.measure("attribution_person_arrays_cte"):
            ctes[PERSON_ARRAYS_CTE] = ast.CTE(
                name=PERSON_ARRAYS_CTE,
                expr=self._build_person_arrays_select(date_range),
                cte_type="subquery",
            )
        # Materialized because two CTEs read it, and ClickHouse otherwise re-evaluates a CTE at each
        # reference: without this the events scan underneath it happens twice.
        ctes[_PER_CONVERSION_CTE] = ast.CTE(
            name=_PER_CONVERSION_CTE,
            expr=self._build_per_conversion_select(),
            cte_type="subquery",
            materialized=True,
        )
        ctes[_PER_TOUCHPOINT_CTE] = ast.CTE(
            name=_PER_TOUCHPOINT_CTE, expr=self._build_per_touchpoint_select(), cte_type="subquery"
        )
        ctes[_PER_CONVERSION_DIM_CTE] = ast.CTE(
            name=_PER_CONVERSION_DIM_CTE, expr=self._build_per_conversion_dim_select(), cte_type="subquery"
        )
        ctes[_TOTALS_CTE] = ast.CTE(name=_TOTALS_CTE, expr=self._build_totals_select(), cte_type="subquery")
        ctes[_ROWS_CTE] = ast.CTE(name=_ROWS_CTE, expr=self._build_rows_select(), cte_type="subquery")
        ctes[_FOOTER_CTE] = ast.CTE(name=_FOOTER_CTE, expr=self._build_footer_select(), cte_type="subquery")

        query = self._build_outer_select()
        query.ctes = ctes
        return query

    def _build_footer_select(self) -> ast.SelectQuery:
        """(I) One row reconciling what the models could and couldn't credit.

        Its own CTE rather than two scalar subqueries hanging off the outer SELECT, for two reasons.
        `per_conversion` is read once here instead of twice. And a SELECT-list scalar is evaluated per
        output row, so a query that returns no dimension rows would report zero conversions rather than
        "you have conversions and none of them could be credited", which is the more useful of the two.
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
                                left=ast.Call(name="length", args=[ast.Field(chain=["tps"])]),
                                op=ast.CompareOperationOp.Gt,
                                right=ast.Constant(value=0),
                            )
                        ],
                    ),
                ),
                ast.Alias(alias=_JOIN_KEY, expr=ast.Constant(value=1)),
            ],
            select_from=ast.JoinExpr(table=ast.Field(chain=[_PER_CONVERSION_CTE])),
        )

    def _build_outer_select(self) -> ast.SelectQuery:
        """(J) Attach the footer counts to every row.

        LEFT from the footer, which always has exactly one row, so the reconciliation survives a goal
        whose conversions produced no dimension rows at all. That leaves one placeholder row when there
        is nothing to show; `_JOIN_KEY` is 0 on it, and `_calculate` drops it.
        """
        select: list[ast.Expr] = [
            ast.Alias(alias=name, expr=ast.Field(chain=[_ROWS_CTE, name])) for name in self._row_column_names()
        ]
        select.extend(
            [
                ast.Alias(alias=_TOTAL_CONVERSIONS, expr=ast.Field(chain=[_FOOTER_CTE, _TOTAL_CONVERSIONS])),
                ast.Alias(alias=_ATTRIBUTED_CONVERSIONS, expr=ast.Field(chain=[_FOOTER_CTE, _ATTRIBUTED_CONVERSIONS])),
                ast.Alias(alias=_JOIN_KEY, expr=ast.Field(chain=[_ROWS_CTE, _JOIN_KEY])),
            ]
        )

        return ast.SelectQuery(
            select=select,
            select_from=ast.JoinExpr(
                table=ast.Field(chain=[_FOOTER_CTE]),
                next_join=ast.JoinExpr(
                    join_type="LEFT JOIN",
                    table=ast.Field(chain=[_ROWS_CTE]),
                    constraint=ast.JoinConstraint(
                        expr=ast.CompareOperation(
                            left=ast.Field(chain=[_FOOTER_CTE, _JOIN_KEY]),
                            op=ast.CompareOperationOp.Eq,
                            right=ast.Field(chain=[_ROWS_CTE, _JOIN_KEY]),
                        ),
                        constraint_type="ON",
                    ),
                ),
            ),
            # Server ordering only decides which rows make the page; the table re-sorts client side.
            order_by=[
                ast.OrderExpr(expr=ast.Field(chain=[_INFLUENCED_CONVERSIONS]), order="DESC"),
                ast.OrderExpr(expr=ast.Field(chain=[_VISITORS]), order="DESC"),
            ],
            limit=ast.Constant(value=(self.query.limit or DEFAULT_LIMIT) + PAGINATION_EXTRA),
            offset=ast.Constant(value=self.query.offset or 0),
        )

    def _row_column_names(self) -> list[str]:
        """The dimension columns, in the order `_build_rows_select` produces them."""
        names = [_BREAKDOWN_VALUE, _VISITORS, _INFLUENCED_CONVERSIONS, _INFLUENCED_VALUE]
        for alias in _ordered_weight_aliases():
            names.extend([f"{alias}_conversions", f"{alias}_value"])
        return names

    def _build_rows_select(self) -> ast.SelectQuery:
        """(H) Join credit onto reach.

        FULL OUTER so a dimension keeps its row whether or not it has both sides: traffic that never
        converted still shows visitors, and a credited row can't silently vanish if reach drops it.
        """
        totals = ast.Field(chain=[_TOTALS_CTE, _BREAKDOWN_VALUE])
        reach = ast.Field(chain=[_REACH_CTE, _BREAKDOWN_VALUE])

        select: list[ast.Expr] = [
            ast.Alias(
                alias=_BREAKDOWN_VALUE,
                expr=ast.Call(
                    name="coalesce",
                    args=[ast.Call(name="nullIf", args=[totals, ast.Constant(value="")]), reach],
                ),
            ),
            ast.Alias(
                alias=_VISITORS,
                expr=ast.Call(
                    name="ifNull",
                    args=[ast.Field(chain=[_REACH_CTE, _VISITORS]), ast.Constant(value=0)],
                ),
            ),
            ast.Alias(
                alias=_INFLUENCED_CONVERSIONS,
                expr=ast.Call(
                    name="ifNull",
                    args=[ast.Field(chain=[_TOTALS_CTE, _INFLUENCED_CONVERSIONS]), ast.Constant(value=0)],
                ),
            ),
            ast.Alias(
                alias=_INFLUENCED_VALUE,
                expr=ast.Call(
                    name="ifNull",
                    args=[ast.Field(chain=[_TOTALS_CTE, _INFLUENCED_VALUE]), ast.Constant(value=0.0)],
                ),
            ),
        ]
        for alias in _ordered_weight_aliases():
            for suffix in ("conversions", "value"):
                col = f"{alias}_{suffix}"
                select.append(
                    ast.Alias(
                        alias=col,
                        expr=ast.Call(
                            name="ifNull",
                            args=[ast.Field(chain=[_TOTALS_CTE, col]), ast.Constant(value=0.0)],
                        ),
                    )
                )

        # Constant key the footer joins on, and the marker that tells a real row from the placeholder
        # the outer LEFT JOIN emits when there are no rows at all.
        select.append(ast.Alias(alias=_JOIN_KEY, expr=ast.Constant(value=1)))

        join = ast.JoinExpr(
            table=ast.Field(chain=[_TOTALS_CTE]),
            next_join=ast.JoinExpr(
                join_type="FULL OUTER JOIN",
                table=ast.Field(chain=[_REACH_CTE]),
                constraint=ast.JoinConstraint(
                    expr=ast.CompareOperation(left=totals, op=ast.CompareOperationOp.Eq, right=reach),
                    constraint_type="ON",
                ),
            ),
        )

        return ast.SelectQuery(select=select, select_from=join)

    # ------------------------------------------------------------------ execution

    def _calculate(self) -> MarketingAnalyticsAttributionQueryResponse:
        query = self.to_query()

        response = execute_hogql_query(
            query_type="marketing_analytics_attribution_query",
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
        # no dimension rows.
        first = named_results[0] if named_results else {}
        total_conversions = int(first.get(_TOTAL_CONVERSIONS) or 0)
        attributed_conversions = int(first.get(_ATTRIBUTED_CONVERSIONS) or 0)

        named_results = [row for row in named_results if row.get(_JOIN_KEY)]

        requested_limit = self.query.limit or DEFAULT_LIMIT
        has_more = len(named_results) > requested_limit
        if has_more:
            named_results = named_results[:requested_limit]

        has_value = bool(self.goal.counts_as_revenue)
        rows = [self._build_row(row, has_value=has_value) for row in named_results]

        return MarketingAnalyticsAttributionQueryResponse(
            results=rows,
            models=MODEL_ORDER,
            hasValue=has_value,
            attributionWindowDays=self.lookback_window_days,
            allowsMultipleConversionsPerVisitor=self.allows_multiple_conversions_per_visitor,
            unattributedConversions=max(total_conversions - attributed_conversions, 0),
            totalConversions=total_conversions,
            hogql=response.hogql,
            timings=response.timings,
            modifiers=self.modifiers,
            hasMore=has_more,
            limit=requested_limit,
            offset=self.query.offset or 0,
        )

    def _build_row(self, row: dict[str, Any], *, has_value: bool) -> MarketingAnalyticsAttributionRow:
        """The rate is derived here rather than in SQL so the frontend keeps the raw numerator and
        denominator for its tooltips."""
        visitors = int(row.get(_VISITORS) or 0)

        models: list[MarketingAnalyticsAttributionModelCell] = []
        for model in MODEL_ORDER:
            alias = _WEIGHT_ALIASES[model]
            conversions = float(row.get(f"{alias}_conversions") or 0.0)
            value = float(row.get(f"{alias}_value") or 0.0)
            models.append(
                MarketingAnalyticsAttributionModelCell(
                    model=model,
                    conversions=conversions,
                    conversionRate=(conversions / visitors) if visitors else None,
                    conversionValue=value if has_value else None,
                )
            )

        return MarketingAnalyticsAttributionRow(
            breakdownValue=str(row.get(_BREAKDOWN_VALUE) or ""),
            visitors=visitors,
            influencedConversions=int(row.get(_INFLUENCED_CONVERSIONS) or 0),
            influencedValue=float(row.get(_INFLUENCED_VALUE) or 0.0) if has_value else None,
            models=models,
        )
