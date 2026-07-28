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

from typing import cast

import structlog

from posthog.schema import (
    AttributionMode,
    CachedMarketingAnalyticsAttributionQueryResponse,
    ConversionGoalFilter1,
    ConversionGoalFilter2,
    ConversionGoalFilter3,
    MarketingAnalyticsAttributionBreakdown,
    MarketingAnalyticsAttributionModelCell,
    MarketingAnalyticsAttributionQuery,
    MarketingAnalyticsAttributionQueryResponse,
    MarketingAnalyticsAttributionRow,
    PropertyMathType,
)

from posthog.hogql import ast
from posthog.hogql.constants import LimitContext
from posthog.hogql.property import action_to_expr
from posthog.hogql.query import execute_hogql_query

from posthog.hogql_queries.utils.query_date_range import QueryDateRange

from products.actions.backend.models.action import Action

from .attribution_weights import (
    DAY_IN_SECONDS,
    build_first_touch_weights,
    build_last_touch_weights,
    build_linear_weights,
    build_position_based_weights,
    build_time_decay_weights,
)
from .constants import DEFAULT_LIMIT, PAGINATION_EXTRA, UNKNOWN_CHANNEL
from .marketing_analytics_base_query_runner import MarketingAnalyticsBaseQueryRunner

logger = structlog.get_logger(__name__)

ConversionGoal = ConversionGoalFilter1 | ConversionGoalFilter2 | ConversionGoalFilter3

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

# Session field backing each breakdown. Read through the events->sessions lazy join, so a team on
# sessions v2 or v3 gets whichever version its modifiers select.
_BREAKDOWN_SESSION_FIELDS: dict[MarketingAnalyticsAttributionBreakdown, str] = {
    MarketingAnalyticsAttributionBreakdown.CHANNEL: "$channel_type",
    MarketingAnalyticsAttributionBreakdown.SOURCE: "$entry_utm_source",
    MarketingAnalyticsAttributionBreakdown.CAMPAIGN: "$entry_utm_campaign",
    MarketingAnalyticsAttributionBreakdown.MEDIUM: "$entry_utm_medium",
    MarketingAnalyticsAttributionBreakdown.CONTENT: "$entry_utm_content",
    MarketingAnalyticsAttributionBreakdown.TERM: "$entry_utm_term",
    MarketingAnalyticsAttributionBreakdown.REFERRING_DOMAIN: "$entry_referring_domain",
    MarketingAnalyticsAttributionBreakdown.LANDING_PAGE: "$entry_pathname",
}

# CTE names.
_REACH_CTE = "influenced_reach"
_PERSON_ARRAYS_CTE = "person_arrays"
_PER_CONVERSION_CTE = "per_conversion"
_PER_TOUCHPOINT_CTE = "per_touchpoint"
_PER_CONVERSION_DIM_CTE = "per_conversion_dim"
_TOTALS_CTE = "attribution_totals"

# A single person with pathological session counts (crawlers, shared devices) would otherwise build an
# unbounded touchpoint array and dominate the query's memory. Truncating costs that person's tail
# touchpoints, which is preferable to failing the whole query.
MAX_TOUCHPOINTS_PER_PERSON = 500

_BREAKDOWN_VALUE = "breakdown_value"
_VISITORS = "visitors"
_INFLUENCED_CONVERSIONS = "influenced_conversions"
_INFLUENCED_VALUE = "influenced_value"
_TOTAL_CONVERSIONS = "total_conversions"
_ATTRIBUTED_CONVERSIONS = "attributed_conversions"

# Result tuple layout: breakdown value, visitors, influenced conversions, influenced value, then a
# (conversions, value) pair per model, then the two reconciliation counts.
_FIXED_COLUMNS = 4
_TOTAL_CONVERSIONS_INDEX = _FIXED_COLUMNS + len(MODEL_ORDER) * 2
_ATTRIBUTED_CONVERSIONS_INDEX = _TOTAL_CONVERSIONS_INDEX + 1


class MarketingAnalyticsAttributionQueryRunner(
    MarketingAnalyticsBaseQueryRunner[MarketingAnalyticsAttributionQueryResponse]
):
    query: MarketingAnalyticsAttributionQuery
    response: MarketingAnalyticsAttributionQueryResponse
    cached_response: CachedMarketingAnalyticsAttributionQueryResponse

    @property
    def breakdown(self) -> MarketingAnalyticsAttributionBreakdown:
        return self.query.breakdownBy or MarketingAnalyticsAttributionBreakdown.CHANNEL

    @property
    def attribution_window_seconds(self) -> int:
        return self.config.attribution_window_days * DAY_IN_SECONDS

    def _resolve_goal(self) -> ConversionGoal:
        """Find the requested goal among the team's configured goals.

        Data warehouse goals are rejected rather than silently mis-attributed: their conversions live in
        a warehouse table keyed by distinct_id, but this query collects conversions and touchpoints from
        one `events` scan grouped by person_id, so there is nothing to join them on here.
        """
        goals, warnings = self._filter_invalid_conversion_goals(self._get_team_conversion_goals())
        self._conversion_goal_warnings = warnings
        self._valid_conversion_goals_count = len(goals)

        for goal in goals:
            if goal.conversion_goal_id == self.query.conversionGoalId:
                if goal.kind == "DataWarehouseNode":
                    raise ValueError(
                        f"Conversion goal '{goal.conversion_goal_name}' is backed by a data warehouse table, "
                        "which attribution doesn't support yet. Pick an event or action goal."
                    )
                return goal

        raise ValueError(f"Conversion goal '{self.query.conversionGoalId}' not found for this team")

    def _conversion_condition(self, goal: ConversionGoal) -> ast.Expr:
        """True for an event row that counts as a conversion for this goal."""
        if goal.kind == "EventsNode":
            return ast.CompareOperation(
                left=ast.Field(chain=["events", "event"]),
                op=ast.CompareOperationOp.Eq,
                right=ast.Constant(value=goal.event),
            )
        # ActionsNode — reuse the shared action->HogQL translation so the definition can't drift from
        # the rest of PostHog.
        action = Action.objects.get(pk=int(cast(str, goal.id)), team__project_id=self.team.project_id)
        return action_to_expr(action)

    def _conversion_value_expr(self, goal: ConversionGoal) -> ast.Expr:
        """Value of one conversion: the goal's math property under SUM math, otherwise 1.

        Mirrors `ConversionGoalProcessor._get_conversion_value_expr` — these must stay in lockstep, or
        the same goal would report different revenue on the Dashboard and here.
        """
        math_type = goal.math
        if math_type in ["sum", PropertyMathType.SUM] or str(math_type).endswith("_sum"):
            if goal.math_property:
                return ast.Call(
                    name="coalesce",
                    args=[
                        ast.Call(name="toFloat", args=[ast.Field(chain=["events", "properties", goal.math_property])]),
                        ast.Constant(value=0.0),
                    ],
                )
        return ast.Call(name="toFloat", args=[ast.Constant(value=1)])

    def _breakdown_expr(self) -> ast.Expr:
        """The row dimension, read off the session a touchpoint belongs to.

        Channel and source fall back to the same sentinels the rest of marketing analytics uses, so rows
        line up with the cost side; the remaining dimensions keep an empty string, which the frontend
        renders as "(none)".
        """
        field = ast.Field(chain=["events", "session", _BREAKDOWN_SESSION_FIELDS[self.breakdown]])

        if self.breakdown == MarketingAnalyticsAttributionBreakdown.CHANNEL:
            return self._non_empty_or(field, UNKNOWN_CHANNEL)
        if self.breakdown == MarketingAnalyticsAttributionBreakdown.SOURCE:
            return self._normalized_source_expr(field)
        return ast.Call(name="toString", args=[ast.Call(name="ifNull", args=[field, ast.Constant(value="")])])

    def _normalized_source_expr(self, field: ast.Expr) -> ast.Expr:
        """Collapse the team's custom UTM source aliases onto each adapter's canonical source name.

        Without this the events side and the cost side disagree on the row key and every cost cell reads
        null. Same treatment as `_build_sessions_select`.
        """
        from .adapters.factory import MarketingSourceFactory  # noqa: PLC0415 — avoids an import cycle
        from .utils import build_source_normalization_expr  # noqa: PLC0415 — avoids an import cycle

        source_mappings = MarketingSourceFactory.get_all_source_identifier_mappings(
            team_config=self.team.marketing_analytics_config
        )
        return build_source_normalization_expr(
            self._non_empty_or(field, self.config.organic_source),
            source_mappings,
        )

    @staticmethod
    def _non_empty_or(field: ast.Expr, fallback: str) -> ast.Expr:
        return ast.Call(
            name="if",
            args=[
                ast.Call(name="notEmpty", args=[ast.Call(name="ifNull", args=[field, ast.Constant(value="")])]),
                field,
                ast.Constant(value=fallback),
            ],
        )

    # ------------------------------------------------------------------ CTEs

    def _build_reach_select(self, date_range: QueryDateRange) -> ast.SelectQuery:
        """(A) Unique visitors per dimension over the display window — everyone, converters or not.

        Uses the same touchpoint definition as the credit side, so "visitors" means exactly the people
        who arrived via a touchpoint that could earn credit. That keeps conversions/visitors an honest
        rate, and means excluding direct removes its row entirely instead of leaving one showing traffic
        with zero credit, which would read as "direct influenced nothing".
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
                    *self._get_where_conditions(date_range, date_field="events.timestamp"),
                ]
            ),
            group_by=[ast.Field(chain=[_BREAKDOWN_VALUE])],
        )

    def _build_converters_select(self, date_range: QueryDateRange, goal: ConversionGoal) -> ast.SelectQuery:
        """(B) Persons who converted in the window.

        This is not an optimization — it is what makes the query affordable. Widening touchpoints from
        "UTM-tagged pageviews" to "every session" multiplies the pageview side by roughly 10x; restricting
        it to converters (typically low single-digit percent of persons) more than pays that back. Removing
        this semi-join changes no results and costs one to two orders of magnitude more.
        """
        return ast.SelectQuery(
            select=[ast.Field(chain=["events", "person_id"])],
            select_from=ast.JoinExpr(table=ast.Field(chain=["events"])),
            where=ast.And(
                exprs=[
                    self._conversion_condition(goal),
                    *self._get_where_conditions(date_range, date_field="events.timestamp"),
                ]
            ),
            group_by=[ast.Field(chain=["events", "person_id"])],
        )

    def _build_person_arrays_select(self, date_range: QueryDateRange, goal: ConversionGoal) -> ast.SelectQuery:
        """(C) One row per converting person: its conversions, plus a deduped touchpoint set.

        Conversions are collected as (timestamp, value) tuples in one array rather than two parallel
        arrays indexed together — `groupArray` gives no ordering guarantee, so two separate arrays could
        in principle pair a conversion's timestamp with another's value.

        `groupUniqArray` over (session start, dimension) collapses every pageview in a session to a
        single touchpoint during aggregation, so there is never a large intermediate array to hold.
        """
        is_conversion = self._conversion_condition(goal)
        breakdown = self._breakdown_expr()

        conversions = ast.Call(
            name="arrayFilter",
            args=[
                ast.Lambda(
                    args=["c"],
                    expr=ast.CompareOperation(
                        left=ast.TupleAccess(tuple=ast.Field(chain=["c"]), index=1),
                        op=ast.CompareOperationOp.Gt,
                        right=ast.Constant(value=0),
                    ),
                ),
                ast.Call(
                    name="groupArray",
                    args=[
                        ast.Call(
                            name="if",
                            args=[
                                is_conversion,
                                ast.Tuple(
                                    exprs=[
                                        ast.Call(
                                            name="toUnixTimestamp", args=[ast.Field(chain=["events", "timestamp"])]
                                        ),
                                        self._conversion_value_expr(goal),
                                    ]
                                ),
                                ast.Tuple(exprs=[ast.Constant(value=0), ast.Constant(value=0.0)]),
                            ],
                        )
                    ],
                ),
            ],
        )

        touchpoints = ast.Call(
            name="arraySlice",
            args=[
                ast.Call(
                    name="arrayFilter",
                    args=[
                        ast.Lambda(
                            args=["t"],
                            expr=ast.CompareOperation(
                                left=ast.TupleAccess(tuple=ast.Field(chain=["t"]), index=1),
                                op=ast.CompareOperationOp.Gt,
                                right=ast.Constant(value=0),
                            ),
                        ),
                        ast.Call(
                            name="groupUniqArray",
                            args=[
                                ast.Call(
                                    name="if",
                                    args=[
                                        self._touchpoint_condition(),
                                        ast.Tuple(
                                            exprs=[
                                                ast.Call(
                                                    name="toUnixTimestamp",
                                                    args=[ast.Field(chain=["events", "session", "$start_timestamp"])],
                                                ),
                                                breakdown,
                                            ]
                                        ),
                                        ast.Tuple(exprs=[ast.Constant(value=0), ast.Constant(value="")]),
                                    ],
                                )
                            ],
                        ),
                    ],
                ),
                ast.Constant(value=1),
                ast.Constant(value=MAX_TOUCHPOINTS_PER_PERSON),
            ],
        )

        return ast.SelectQuery(
            select=[
                ast.Field(chain=["events", "person_id"]),
                ast.Alias(alias="conversions", expr=conversions),
                ast.Alias(alias="touchpoints", expr=touchpoints),
            ],
            select_from=ast.JoinExpr(table=ast.Field(chain=["events"])),
            where=ast.And(
                exprs=[
                    ast.CompareOperation(
                        left=ast.Field(chain=["events", "person_id"]),
                        op=ast.CompareOperationOp.In,
                        right=self._build_converters_select(date_range, goal),
                    ),
                    ast.Or(
                        exprs=[
                            ast.And(
                                exprs=[
                                    self._conversion_condition(goal),
                                    *self._get_where_conditions(date_range, date_field="events.timestamp"),
                                ]
                            ),
                            ast.And(
                                exprs=[
                                    self._pageview_condition(),
                                    *self._lookback_date_conditions(date_range),
                                ]
                            ),
                        ]
                    ),
                ]
            ),
            group_by=[ast.Field(chain=["events", "person_id"])],
            having=ast.CompareOperation(
                left=ast.Call(name="length", args=[ast.Field(chain=["conversions"])]),
                op=ast.CompareOperationOp.Gt,
                right=ast.Constant(value=0),
            ),
        )

    def _pageview_condition(self) -> ast.Expr:
        return ast.CompareOperation(
            left=ast.Field(chain=["events", "event"]),
            op=ast.CompareOperationOp.Eq,
            right=ast.Constant(value="$pageview"),
        )

    def _touchpoint_condition(self) -> ast.Expr:
        """A pageview inside a real session counts as a touchpoint.

        When direct traffic is excluded, drop it here — before the weights are computed — so the
        remaining touchpoints renormalize to full credit instead of quietly losing direct's share.
        """
        conditions: list[ast.Expr] = [
            self._pageview_condition(),
            ast.Call(name="notEmpty", args=[ast.Field(chain=["events", "$session_id"])]),
        ]
        if self.query.excludeDirectTraffic:
            conditions.append(
                ast.CompareOperation(
                    left=ast.Field(chain=["events", "session", "$channel_type"]),
                    op=ast.CompareOperationOp.NotEq,
                    right=ast.Constant(value="Direct"),
                )
            )
        return ast.And(exprs=conditions)

    def _lookback_date_conditions(self, date_range: QueryDateRange) -> list[ast.Expr]:
        """Pageview bounds extended back by the attribution window, so touches that predate the
        display range can still be credited for a conversion inside it."""
        return [
            ast.CompareOperation(
                left=ast.Field(chain=["events", "timestamp"]),
                op=ast.CompareOperationOp.GtEq,
                right=ast.ArithmeticOperation(
                    left=ast.Call(name="toDateTime", args=[ast.Constant(value=date_range.date_from_str)]),
                    op=ast.ArithmeticOperationOp.Sub,
                    right=ast.Call(name="toIntervalSecond", args=[ast.Constant(value=self.attribution_window_seconds)]),
                ),
            ),
            ast.CompareOperation(
                left=ast.Field(chain=["events", "timestamp"]),
                op=ast.CompareOperationOp.LtEq,
                right=ast.Call(name="toDateTime", args=[ast.Constant(value=date_range.date_to_str)]),
            ),
        ]

    def _build_per_conversion_select(self) -> ast.SelectQuery:
        """(D) One row per conversion, carrying all five weight arrays.

        Every builder maps over the same `ts`, so all five arrays have identical length — that is what
        lets (E) explode them with a single shared ARRAY JOIN instead of five.
        """
        conversion_time = ast.Field(chain=["conversion_time"])
        ts = ast.Field(chain=["touch_ts"])

        in_window = ast.Call(
            name="arrayFilter",
            args=[
                ast.Lambda(
                    args=["t"],
                    expr=ast.And(
                        exprs=[
                            ast.CompareOperation(
                                left=ast.TupleAccess(tuple=ast.Field(chain=["t"]), index=1),
                                op=ast.CompareOperationOp.LtEq,
                                right=conversion_time,
                            ),
                            ast.CompareOperation(
                                left=ast.TupleAccess(tuple=ast.Field(chain=["t"]), index=1),
                                op=ast.CompareOperationOp.GtEq,
                                right=ast.ArithmeticOperation(
                                    left=conversion_time,
                                    op=ast.ArithmeticOperationOp.Sub,
                                    right=ast.Constant(value=self.attribution_window_seconds),
                                ),
                            ),
                        ]
                    ),
                ),
                ast.Field(chain=["touchpoints"]),
            ],
        )

        select: list[ast.Expr] = [
            ast.Field(chain=["person_id"]),
            ast.Alias(
                alias="conversion_time",
                expr=ast.TupleAccess(
                    tuple=ast.ArrayAccess(array=ast.Field(chain=["conversions"]), property=ast.Field(chain=["i"])),
                    index=1,
                ),
            ),
            ast.Alias(
                alias="conversion_value",
                expr=ast.TupleAccess(
                    tuple=ast.ArrayAccess(array=ast.Field(chain=["conversions"]), property=ast.Field(chain=["i"])),
                    index=2,
                ),
            ),
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
            select_from=ast.JoinExpr(table=ast.Field(chain=[_PERSON_ARRAYS_CTE])),
            array_join_op="ARRAY JOIN",
            array_join_list=[
                ast.Alias(
                    alias="i",
                    expr=ast.Call(name="arrayEnumerate", args=[ast.Field(chain=["conversions"])]),
                )
            ],
        )

    def _build_per_touchpoint_select(self) -> ast.SelectQuery:
        """(E) One row per touchpoint, indexing all five weight arrays off one ARRAY JOIN."""
        k = ast.Field(chain=["k"])
        select: list[ast.Expr] = [
            ast.Field(chain=["person_id"]),
            ast.Field(chain=["conversion_time"]),
            ast.Field(chain=["conversion_value"]),
            ast.Alias(
                alias=_BREAKDOWN_VALUE,
                expr=ast.ArrayAccess(array=ast.Field(chain=["dims"]), property=k),
            ),
        ]
        for alias in _WEIGHT_ALIASES.values():
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

        Does double duty. It gives "influenced" its once-per-conversion semantics, and it rolls the
        weights up correctly: a channel touched on 3 of 5 sessions earns 0.6 of the linear credit as one
        row, not three rows of 0.2.
        """
        select: list[ast.Expr] = [
            ast.Field(chain=[_BREAKDOWN_VALUE]),
            ast.Field(chain=["person_id"]),
            ast.Field(chain=["conversion_time"]),
            ast.Alias(alias="conv_value", expr=ast.Call(name="any", args=[ast.Field(chain=["conversion_value"])])),
        ]
        for alias in _WEIGHT_ALIASES.values():
            select.append(ast.Alias(alias=alias, expr=ast.Call(name="sum", args=[ast.Field(chain=[alias])])))

        return ast.SelectQuery(
            select=select,
            select_from=ast.JoinExpr(table=ast.Field(chain=[_PER_TOUCHPOINT_CTE])),
            group_by=[
                ast.Field(chain=[_BREAKDOWN_VALUE]),
                ast.Field(chain=["person_id"]),
                ast.Field(chain=["conversion_time"]),
            ],
        )

    def _build_totals_select(self) -> ast.SelectQuery:
        """(G) One row per dimension: influenced counts plus each model's weighted credit."""
        select: list[ast.Expr] = [
            ast.Field(chain=[_BREAKDOWN_VALUE]),
            ast.Alias(alias=_INFLUENCED_CONVERSIONS, expr=ast.Call(name="count", args=[])),
            ast.Alias(alias=_INFLUENCED_VALUE, expr=ast.Call(name="sum", args=[ast.Field(chain=["conv_value"])])),
        ]
        for alias in _WEIGHT_ALIASES.values():
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
        goal = self._resolve_goal()
        date_range = self.query_date_range

        ctes: dict[str, ast.CTE] = {}
        with self.timings.measure("attribution_reach_cte"):
            ctes[_REACH_CTE] = ast.CTE(name=_REACH_CTE, expr=self._build_reach_select(date_range), cte_type="subquery")
        with self.timings.measure("attribution_person_arrays_cte"):
            ctes[_PERSON_ARRAYS_CTE] = ast.CTE(
                name=_PERSON_ARRAYS_CTE,
                expr=self._build_person_arrays_select(date_range, goal),
                cte_type="subquery",
            )
        ctes[_PER_CONVERSION_CTE] = ast.CTE(
            name=_PER_CONVERSION_CTE, expr=self._build_per_conversion_select(), cte_type="subquery"
        )
        ctes[_PER_TOUCHPOINT_CTE] = ast.CTE(
            name=_PER_TOUCHPOINT_CTE, expr=self._build_per_touchpoint_select(), cte_type="subquery"
        )
        ctes[_PER_CONVERSION_DIM_CTE] = ast.CTE(
            name=_PER_CONVERSION_DIM_CTE, expr=self._build_per_conversion_dim_select(), cte_type="subquery"
        )
        ctes[_TOTALS_CTE] = ast.CTE(name=_TOTALS_CTE, expr=self._build_totals_select(), cte_type="subquery")

        query = self._build_outer_select()
        query.ctes = ctes
        return query

    @staticmethod
    def _scalar_over_per_conversion(aggregate: ast.Expr) -> ast.SelectQuery:
        return ast.SelectQuery(
            select=[aggregate],
            select_from=ast.JoinExpr(table=ast.Field(chain=[_PER_CONVERSION_CTE])),
        )

    def _build_outer_select(self) -> ast.SelectQuery:
        """(H) Join credit onto reach.

        FULL OUTER so a dimension keeps its row whether or not it has both sides: traffic that never
        converted still shows visitors, and a touchpoint older than the display window still shows the
        credit it earned even though nobody "arrived" via it in range.
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
        for alias in _WEIGHT_ALIASES.values():
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

        # Reconciliation counts for the footer, as scalar subqueries over the already-materialized
        # per_conversion CTE. Repeated identically on every row, which is the cheap way round: running
        # them as a second query would rebuild the touchpoint scan, the most expensive part of all this.
        select.append(
            ast.Alias(alias=_TOTAL_CONVERSIONS, expr=self._scalar_over_per_conversion(ast.Call(name="count", args=[])))
        )
        select.append(
            ast.Alias(
                alias=_ATTRIBUTED_CONVERSIONS,
                expr=self._scalar_over_per_conversion(
                    ast.Call(
                        name="countIf",
                        args=[
                            ast.CompareOperation(
                                left=ast.Call(name="length", args=[ast.Field(chain=["tps"])]),
                                op=ast.CompareOperationOp.Gt,
                                right=ast.Constant(value=0),
                            )
                        ],
                    )
                ),
            )
        )

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

        limit = self.query.limit or DEFAULT_LIMIT
        return ast.SelectQuery(
            select=select,
            select_from=join,
            # Server ordering only decides which rows make the page; the table re-sorts client side.
            order_by=[
                ast.OrderExpr(expr=ast.Field(chain=[_INFLUENCED_CONVERSIONS]), order="DESC"),
                ast.OrderExpr(expr=ast.Field(chain=[_VISITORS]), order="DESC"),
            ],
            limit=ast.Constant(value=limit + PAGINATION_EXTRA),
            offset=ast.Constant(value=self.query.offset or 0),
        )

    # ------------------------------------------------------------------ execution

    def _calculate(self) -> MarketingAnalyticsAttributionQueryResponse:
        goal = self._resolve_goal()
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

        requested_limit = self.query.limit or DEFAULT_LIMIT
        raw_results = response.results or []
        has_more = len(raw_results) > requested_limit
        if has_more:
            raw_results = raw_results[:requested_limit]

        has_value = bool(goal.counts_as_revenue)
        rows = [self._build_row(row, has_value=has_value) for row in raw_results]

        # Every row carries the same reconciliation totals, so read them off the first one. With no rows
        # there is nothing to reconcile against either.
        total_conversions = int(raw_results[0][_TOTAL_CONVERSIONS_INDEX] or 0) if raw_results else 0
        attributed_conversions = int(raw_results[0][_ATTRIBUTED_CONVERSIONS_INDEX] or 0) if raw_results else 0

        return MarketingAnalyticsAttributionQueryResponse(
            results=rows,
            models=MODEL_ORDER,
            hasValue=has_value,
            attributionWindowDays=self.config.attribution_window_days,
            unattributedConversions=max(total_conversions - attributed_conversions, 0),
            totalConversions=total_conversions,
            hogql=response.hogql,
            timings=response.timings,
            modifiers=self.modifiers,
            hasMore=has_more,
            limit=requested_limit,
            offset=self.query.offset or 0,
            error="; ".join(self._conversion_goal_warnings) if self._conversion_goal_warnings else None,
        )

    def _build_row(self, row: tuple, *, has_value: bool) -> MarketingAnalyticsAttributionRow:
        """Map one result tuple onto the typed row, deriving conversion rate in Python.

        The rate is computed here rather than in SQL so the divide-by-zero case stays readable and the
        frontend keeps the raw numerator and denominator for its tooltips.
        """
        breakdown_value, visitors, influenced_conversions, influenced_value = row[0], row[1], row[2], row[3]

        models: list[MarketingAnalyticsAttributionModelCell] = []
        for index, model in enumerate(MODEL_ORDER):
            conversions = float(row[4 + index * 2] or 0.0)
            value = float(row[5 + index * 2] or 0.0)
            models.append(
                MarketingAnalyticsAttributionModelCell(
                    model=model,
                    conversions=conversions,
                    conversionRate=(conversions / visitors) if visitors else None,
                    conversionValue=value if has_value else None,
                )
            )

        return MarketingAnalyticsAttributionRow(
            breakdownValue=str(breakdown_value or ""),
            visitors=int(visitors or 0),
            influencedConversions=int(influenced_conversions or 0),
            influencedValue=float(influenced_value or 0.0) if has_value else None,
            models=models,
        )

    def _build_main_select_query(self, conversion_aggregator) -> ast.SelectQuery:
        """Not part of this runner's shape.

        The base hook exists to slot a SELECT into its ad-cost-joined table query; this runner overrides
        `to_query` wholesale and builds its own CTE chain, so there is nothing to hook.
        """
        raise NotImplementedError("MarketingAnalyticsAttributionQueryRunner builds its query in to_query")
