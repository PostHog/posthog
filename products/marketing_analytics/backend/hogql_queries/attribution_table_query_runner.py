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

from functools import cached_property
from typing import Any

from posthog.schema import (
    AttributionMode,
    BaseMathType,
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
from posthog.hogql.query import execute_hogql_query

from posthog.hogql_queries.utils.query_date_range import QueryDateRange
from posthog.models.team.team_marketing_analytics_config import MAX_ATTRIBUTION_WINDOW_DAYS, MIN_ATTRIBUTION_WINDOW_DAYS

from .attribution_weights import (
    DAY_IN_SECONDS,
    build_first_touch_weights,
    build_last_touch_weights,
    build_linear_weights,
    build_position_based_weights,
    build_time_decay_weights,
)
from .constants import DEFAULT_LIMIT, PAGINATION_EXTRA, UNKNOWN_CHANNEL
from .conversion_goal_conditions import conversion_goal_condition
from .marketing_analytics_base_query_runner import MarketingAnalyticsBaseQueryRunner

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
_ROWS_CTE = "attribution_rows"
_FOOTER_CTE = "attribution_footer"

# Ceiling on how many sessions of one person can earn credit. Bots and shared devices would otherwise
# fan out touchpoints x conversions in (D) and (E) far enough to dominate the query. Touchpoints are
# sorted before truncating and the *most recent* are kept, because only touches within a lookback window
# of a conversion can be credited and conversions sit at the end of the range. Keeping the oldest instead
# would strand a heavy person's conversions with no eligible touchpoint at all, dropping them from the
# table; this way they keep their credit, and only first touch becomes approximate for such a person.
MAX_TOUCHPOINTS_PER_PERSON = 500

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
    def lookback_window_days(self) -> int:
        """The window this query attributes over, bounded the same way the team setting is.

        The override widens the events scan, and the schema types it as a plain integer, so an
        out-of-range value from a hand-built query would scan the team's whole event history.
        """
        override = self.query.lookbackWindowDays
        if override is None:
            return self.config.attribution_window_days
        if override < MIN_ATTRIBUTION_WINDOW_DAYS or override > MAX_ATTRIBUTION_WINDOW_DAYS:
            raise ValueError(
                f"The attribution window must be between {MIN_ATTRIBUTION_WINDOW_DAYS} and "
                f"{MAX_ATTRIBUTION_WINDOW_DAYS} days."
            )
        return override

    @property
    def attribution_window_seconds(self) -> int:
        return self.lookback_window_days * DAY_IN_SECONDS

    @cached_property
    def goal(self) -> ConversionGoal:
        """The requested goal, found among the team's configured goals.

        Data warehouse goals are rejected rather than silently mis-attributed: their conversions live in
        a warehouse table keyed by distinct_id, but this query collects conversions and touchpoints from
        one `events` scan grouped by person_id, so there is nothing to join them on here.
        """
        all_goals = self._get_team_conversion_goals()
        goals, skipped_goals = self._filter_invalid_conversion_goals(all_goals)
        self._valid_conversion_goals_count = len(goals)

        for goal in goals:
            if goal.conversion_goal_id == self.query.conversionGoalId:
                if goal.kind == "DataWarehouseNode":
                    raise ValueError(
                        f"Conversion goal '{goal.conversion_goal_name}' is backed by a data warehouse table, "
                        "which attribution doesn't support yet. Pick an event or action goal."
                    )
                return goal

        # The table shows one goal at a time, so another goal being unusable is not this query's problem.
        # Only report it when it's the goal that was actually asked for.
        skipped = next((g for g in all_goals if g.conversion_goal_id == self.query.conversionGoalId), None)
        if skipped is not None:
            reason = next(
                (s.message for s in skipped_goals if s.conversion_goal_id == self.query.conversionGoalId), None
            )
            raise ValueError(reason or f"Conversion goal '{skipped.conversion_goal_name}' can't be attributed")

        raise ValueError(f"Conversion goal '{self.query.conversionGoalId}' not found for this team")

    @cached_property
    def conversion_condition(self) -> ast.Expr:
        """True for an event row that counts as a conversion for this goal.

        Shared with the Dashboard's pipeline so the two can't drift on what a conversion is, which
        includes the goal's own property filters: a goal scoped to purchases over $100 has to mean that
        here too, or this table reports a different number than the Dashboard for the same goal.

        Cached because the query references it three times, and the action branch hits Postgres.
        """
        goal = self.goal
        condition = conversion_goal_condition(goal, self.team)
        if condition is None:
            # Validation already rejected the goals with nothing to match on, so what's left is an
            # action-based goal whose action was deleted.
            raise ValueError(
                f"Conversion goal '{goal.conversion_goal_name}' points to an action that no longer exists. "
                "Update the goal in marketing analytics settings, or pick another goal."
            )
        return condition

    @cached_property
    def allows_multiple_conversions_per_visitor(self) -> bool:
        """Whether a repeat converter contributes every conversion, or just one.

        Unset follows the goal's own math: unique-users math already means one conversion per person
        (mirroring `ConversionGoalProcessor`'s DAU branch, which counts persons rather than events), so
        counting every event here would contradict the number the Dashboard reports for the same goal.
        Count-based goals credit every conversion, which is why their rate columns can exceed 100% — a
        person can convert more often than they visited.
        """
        if self.query.allowMultipleConversionsPerVisitor is not None:
            return self.query.allowMultipleConversionsPerVisitor
        return self.goal.math not in [BaseMathType.DAU, "dau"]

    def _conversion_value_expr(self) -> ast.Expr:
        """Value of one conversion: the goal's math property under SUM math, otherwise 1.

        Mirrors `ConversionGoalProcessor._get_conversion_value_expr` — these must stay in lockstep, or
        the same goal would report different revenue on the Dashboard and here.
        """
        goal = self.goal
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
        line up with the cost side.
        """
        field = ast.Field(chain=["events", "session", _BREAKDOWN_SESSION_FIELDS[self.breakdown]])

        if self.breakdown == MarketingAnalyticsAttributionBreakdown.CHANNEL:
            return self._non_empty_or(field, UNKNOWN_CHANNEL)
        if self.breakdown == MarketingAnalyticsAttributionBreakdown.SOURCE:
            return self._normalized_source_expr(field)
        return ast.Call(name="toString", args=[ast.Call(name="ifNull", args=[field, ast.Constant(value="")])])

    def _normalized_source_expr(self, field: ast.Expr) -> ast.Expr:
        """Collapse the team's custom UTM source aliases onto each adapter's canonical source name, or
        the events side and the cost side disagree on the row key. Same treatment as `_build_sessions_select`.
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

    def _build_converters_select(self, date_range: QueryDateRange) -> ast.SelectQuery:
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
                    self.conversion_condition,
                    *self._get_where_conditions(date_range, date_field="events.timestamp"),
                ]
            ),
            group_by=[ast.Field(chain=["events", "person_id"])],
        )

    def _build_person_arrays_select(self, date_range: QueryDateRange) -> ast.SelectQuery:
        """(C) One row per converting person: its conversions, plus a deduped touchpoint set.

        Both arrays hold (timestamp, payload) tuples rather than parallel arrays indexed together, since
        `groupArray` gives no ordering guarantee and separate arrays could pair one conversion's timestamp
        with another's value.

        The `-If` combinators only append when the row qualifies, so neither array grows with the
        person's unrelated events. `groupUniqArray` additionally collapses every pageview in a session to
        one touchpoint during aggregation.
        """
        # Bounded to the display range, not the lookback-extended range the outer WHERE allows. The
        # pageview branch of that WHERE reaches back a further lookback window to collect touchpoints, and
        # without this bound every conversion in that older stretch would be credited too: the table would
        # silently report a range far longer than the one asked for, and the extra conversions would mostly
        # land as unattributed because touchpoint collection doesn't reach back a window before *them*.
        conversions: ast.Expr = ast.Call(
            name="groupArrayIf",
            args=[
                ast.Tuple(
                    exprs=[
                        ast.Call(name="toUnixTimestamp", args=[ast.Field(chain=["events", "timestamp"])]),
                        self._conversion_value_expr(),
                    ]
                ),
                ast.And(
                    exprs=[
                        self.conversion_condition,
                        *self._get_where_conditions(date_range, date_field="events.timestamp"),
                    ]
                ),
            ],
        )

        # Sorted before truncating: `groupUniqArray` is hash-backed, so its order is unrelated to time and
        # slicing it raw would keep an arbitrary subset. The negative offset takes the tail of the sorted
        # array, i.e. the most recent sessions — see MAX_TOUCHPOINTS_PER_PERSON for why that direction.
        touchpoints = ast.Call(
            name="arraySlice",
            args=[
                ast.Call(
                    name="arraySort",
                    args=[
                        ast.Call(
                            name="groupUniqArrayIf",
                            args=[
                                ast.Tuple(
                                    exprs=[
                                        ast.Call(
                                            name="toUnixTimestamp",
                                            args=[ast.Field(chain=["events", "session", "$start_timestamp"])],
                                        ),
                                        self._breakdown_expr(),
                                    ]
                                ),
                                self._touchpoint_condition(),
                            ],
                        )
                    ],
                ),
                ast.Constant(value=-MAX_TOUCHPOINTS_PER_PERSON),
            ],
        )

        if not self.allows_multiple_conversions_per_visitor:
            # One conversion per person: keep the earliest in the window, so the models attribute the
            # journey that led to them first converting rather than an arbitrary later repeat.
            conversions = ast.Call(
                name="arraySlice",
                args=[
                    ast.Call(name="arraySort", args=[conversions]),
                    ast.Constant(value=1),
                    ast.Constant(value=1),
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
                        right=self._build_converters_select(date_range),
                    ),
                    ast.Or(
                        exprs=[
                            ast.And(
                                exprs=[
                                    self.conversion_condition,
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
            # A session id that resolves to no session row yields epoch zero rather than null, because the
            # join fills a non-nullable column with its default. Test for a real timestamp rather than for
            # null: 1970 can never satisfy the attribution window, so such a touchpoint earns nothing, and
            # left in place it would sort to the very front and consume truncation slots. When a
            # conversion's own session is one of these, dropping it here is what keeps the conversion out
            # of the attributed count instead of silently crediting nobody.
            ast.CompareOperation(
                left=ast.Call(
                    name="toUnixTimestamp", args=[ast.Field(chain=["events", "session", "$start_timestamp"])]
                ),
                op=ast.CompareOperationOp.Gt,
                right=ast.Constant(value=0),
            ),
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
            select_from=ast.JoinExpr(table=ast.Field(chain=[_PERSON_ARRAYS_CTE])),
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
            ctes[_PERSON_ARRAYS_CTE] = ast.CTE(
                name=_PERSON_ARRAYS_CTE,
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

    def _build_main_select_query(self, conversion_aggregator) -> ast.SelectQuery:
        """Not part of this runner's shape.

        The base hook exists to slot a SELECT into its ad-cost-joined table query; this runner overrides
        `to_query` wholesale and builds its own CTE chain, so there is nothing to hook.
        """
        raise NotImplementedError("MarketingAnalyticsAttributionQueryRunner builds its query in to_query")
