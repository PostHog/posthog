"""Shared machinery for the attribution runners: the table (all five models side by side) and the
conversion paths (most common touchpoint sequences). Both read a touchpoint's dimension the same way as
every other marketing surface (see `session_breakdown_base`), and both collect per-converting-person
arrays of conversions and touchpoints before diverging in how they aggregate them. Keeping the attribution
window, the exclusion options and the person-array collection here is what stops the two surfaces from
drifting on what a journey is.
"""

from functools import cached_property
from typing import Generic

from posthog.schema import (
    BaseMathType,
    ConversionGoalFilter1,
    ConversionGoalFilter2,
    ConversionGoalFilter3,
    MarketingAnalyticsAttributionPathsQuery,
    MarketingAnalyticsAttributionQuery,
    PropertyMathType,
)

from posthog.hogql import ast

from posthog.hogql_queries.utils.query_date_range import QueryDateRange
from posthog.models.team.team_marketing_analytics_config import MAX_ATTRIBUTION_WINDOW_DAYS, MIN_ATTRIBUTION_WINDOW_DAYS

from .attribution_weights import DAY_IN_SECONDS
from .conversion_goal_conditions import conversion_goal_condition
from .marketing_analytics_base_query_runner import ResponseType
from .session_breakdown_base import MarketingSessionBreakdownQueryRunnerBase

ConversionGoal = ConversionGoalFilter1 | ConversionGoalFilter2 | ConversionGoalFilter3

# Both runners collect per-person arrays under this name before diverging.
PERSON_ARRAYS_CTE = "person_arrays"

# Ceiling on how many sessions of one person can earn credit. Bots and shared devices would otherwise
# fan out touchpoints x conversions far enough to dominate the query. Touchpoints are sorted before
# truncating and the *most recent* are kept, because only touches within a lookback window of a
# conversion can be credited and conversions sit at the end of the range. Keeping the oldest instead
# would strand a heavy person's conversions with no eligible touchpoint at all, dropping them from the
# table; this way they keep their credit, and only first touch becomes approximate for such a person.
MAX_TOUCHPOINTS_PER_PERSON = 500


class AttributionQueryRunnerBase(MarketingSessionBreakdownQueryRunnerBase[ResponseType], Generic[ResponseType]):
    # Narrower than the session-breakdown base's union: everything below reads attribution-only fields.
    query: MarketingAnalyticsAttributionQuery | MarketingAnalyticsAttributionPathsQuery

    @cached_property
    def goal(self) -> ConversionGoal:
        """The requested goal, found among the team's configured goals.

        Data warehouse goals are rejected rather than silently mis-attributed: their conversions live in
        a warehouse table keyed by distinct_id, but these queries collect conversions from one `events`
        scan grouped by person_id, so there is nothing to join them on here.
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

        # Only one goal is queried at a time, so another goal being unusable is not this query's problem.
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

    def _build_converters_select(self, date_range: QueryDateRange) -> ast.SelectQuery:
        """Persons who converted in the window.

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
        """One row per converting person: its conversions, plus a deduped touchpoint set.

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

    def _in_window_touchpoints_expr(self, conversion_time: ast.Expr) -> ast.Expr:
        """The person's touchpoints that fall inside one conversion's attribution window.

        Expects to be evaluated where `touchpoints` (from the person-arrays CTE) is in scope.
        """
        return ast.Call(
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

    def _build_main_select_query(self, conversion_aggregator) -> ast.SelectQuery:
        """Not part of the attribution runners' shape.

        The base hook exists to slot a SELECT into its ad-cost-joined table query; these runners override
        `to_query` wholesale and build their own CTE chains, so there is nothing to hook.
        """
        raise NotImplementedError(f"{type(self).__name__} builds its query in to_query")
