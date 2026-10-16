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
    HogQLQuery,
    MarketingAnalyticsAttributionPathsQuery,
    MarketingAnalyticsAttributionQuery,
    PropertyMathType,
)

from posthog.hogql import ast
from posthog.hogql.constants import HogQLGlobalSettings
from posthog.hogql.parser import parse_select

from posthog.hogql_queries.access_controlled_resources import queried_access_controlled_resources
from posthog.hogql_queries.utils.query_date_range import QueryDateRange
from posthog.models.team.team_marketing_analytics_config import MAX_ATTRIBUTION_WINDOW_DAYS, MIN_ATTRIBUTION_WINDOW_DAYS

from .attribution_weights import DAY_IN_SECONDS
from .constants import MARKETING_SPILL_AFTER_BYTES
from .conversion_goal_conditions import conversion_goal_condition
from .conversion_goal_value import conversion_goal_value_in_base_currency
from .marketing_analytics_base_query_runner import ResponseType
from .session_breakdown_base import MarketingSessionBreakdownQueryRunnerBase
from .warehouse_conversion_source import WarehouseConversionSource

ConversionGoal = ConversionGoalFilter1 | ConversionGoalFilter2 | ConversionGoalFilter3

# Both runners collect per-person arrays under this name before diverging.
PERSON_ARRAYS_CTE = "person_arrays"

# The person's conversion total, carried alongside the arrays because MAX_CONVERSIONS_PER_PERSON can
# make the array shorter than it.
PERSON_CONVERSION_COUNT = "conversion_count"

# Ceiling on how many sessions of one person can earn credit. Bots and shared devices would otherwise
# fan out touchpoints x conversions far enough to dominate the query. Touchpoints are sorted before
# truncating and the *most recent* are kept, because only touches within a lookback window of a
# conversion can be credited and conversions sit at the end of the range. Keeping the oldest instead
# would strand a heavy person's conversions with no eligible touchpoint at all, dropping them from the
# table; this way they keep their credit, and only first touch becomes approximate for such a person.
MAX_TOUCHPOINTS_PER_PERSON = 500

# The same ceiling for the other side of the fan-out. Without it, a person with many conversions
# multiplies the two downstream ARRAY JOINs by an unbounded factor, which is the shape that makes the
# query run out of memory. The most recent are kept for the mirror of the reason above: a conversion
# is credited by touchpoints that precede it, and the recent ones are those with touchpoints still in
# the collected window.
MAX_CONVERSIONS_PER_PERSON = 500


class AttributionQueryRunnerBase(MarketingSessionBreakdownQueryRunnerBase[ResponseType], Generic[ResponseType]):
    # Narrower than the session-breakdown base's union: everything below reads attribution-only fields.
    query: MarketingAnalyticsAttributionQuery | MarketingAnalyticsAttributionPathsQuery

    def additional_session_columns(self) -> set[str]:
        return set()

    def resolved_breakdown_expr(self) -> ast.Expr | None:
        return None

    def get_query_settings(self) -> HogQLGlobalSettings:
        # Extra aggregation threads create more partial states and spill files for the same sessions.
        return HogQLGlobalSettings(
            max_bytes_before_external_group_by=MARKETING_SPILL_AFTER_BYTES,
            max_threads=16 if self._live_session_resolution_used else None,
            optimize_aggregation_in_order=True if self._live_session_resolution_used else None,
        )

    def get_cache_key_variant(self) -> str:
        variant = super().get_cache_key_variant()
        if self.config.live_session_resolution_enabled:
            return f"{variant}_live_session_resolution"
        return variant

    @cached_property
    def goal(self) -> ConversionGoal:
        """The requested goal, found among the team's configured goals."""
        all_goals = self._get_team_conversion_goals()
        goals, skipped_goals = self._filter_invalid_conversion_goals(all_goals, require_utm_columns=False)
        self._valid_conversion_goals_count = len(goals)

        for goal in goals:
            if goal.conversion_goal_id == self.query.conversionGoalId:
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

    def get_cache_payload(self) -> dict[str, object]:
        payload = super().get_cache_payload()
        payload["conversion_goal"] = self.goal.model_dump(mode="json", exclude_none=True)
        return payload

    def get_access_controlled_resources(self) -> set[str] | None:
        if not isinstance(self.goal, ConversionGoalFilter3):
            return super().get_access_controlled_resources()
        # The public query carries a goal ID, so discover permissions from its resolved source,
        # including tables and system resources referenced through saved views.
        source = ast.SelectQuery(
            select=[ast.Constant(value=1)],
            select_from=ast.JoinExpr(table=ast.Field(chain=[*self.goal.table_name.split(".")])),
        )
        return queried_access_controlled_resources(
            HogQLQuery(query=source.to_hogql()), self.team, bypassed_scopes=self._bypassed_access_scopes
        )

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
                        conversion_goal_value_in_base_currency(
                            goal,
                            self.team,
                            ast.Field(chain=["events", "properties", goal.math_property]),
                            ast.Field(chain=["events", "timestamp"]),
                        ),
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

    def _event_date_conditions(self, date_range: QueryDateRange, *, lookback_seconds: int = 0) -> list[ast.Expr]:
        start: ast.Expr = ast.Call(name="toDateTime", args=[ast.Constant(value=date_range.date_from_str)])
        if lookback_seconds:
            start = ast.ArithmeticOperation(
                left=start,
                op=ast.ArithmeticOperationOp.Sub,
                right=ast.Call(name="toIntervalSecond", args=[ast.Constant(value=lookback_seconds)]),
            )
        # A cast on the event field propagates to raw sessions, where HogQL treats the timestamp as untyped.
        # A microsecond-precision end includes the full final second without casting the indexed column.
        return [
            ast.CompareOperation(
                left=ast.Field(chain=["events", "timestamp"]),
                op=ast.CompareOperationOp.GtEq,
                right=start,
            ),
            ast.CompareOperation(
                left=ast.Field(chain=["events", "timestamp"]),
                op=ast.CompareOperationOp.LtEq,
                right=ast.Call(name="toDateTime", args=[ast.Constant(value=f"{date_range.date_to_str}.999999")]),
            ),
        ]

    def _lookback_date_conditions(self, date_range: QueryDateRange) -> list[ast.Expr]:
        """Pageview bounds extended back by the attribution window, so touches that predate the
        display range can still be credited for a conversion inside it.
        The inclusive final second matches the conversion date filters.
        """
        return self._event_date_conditions(date_range, lookback_seconds=self.attribution_window_seconds)

    def _build_converters_select(self, date_range: QueryDateRange, *, with_bounds: bool = False) -> ast.SelectQuery:
        """Persons who converted in the window.

        This is not an optimization — it is what makes the query affordable. Widening touchpoints from
        "UTM-tagged pageviews" to "every session" multiplies the pageview side by roughly 10x; restricting
        it to converters (typically low single-digit percent of persons) more than pays that back. Removing
        this semi-join changes no results and costs one to two orders of magnitude more.
        """
        select: list[ast.Expr] = [ast.Field(chain=["events", "person_id"])]
        if with_bounds:
            # The window of conversions this person can credit. A touchpoint outside it earns nothing,
            # so carrying the bounds lets the caller drop it before it reaches the arrays.
            select.append(
                ast.Alias(
                    alias="first_conversion",
                    expr=ast.Call(
                        name="min",
                        args=[ast.Call(name="toUnixTimestamp", args=[ast.Field(chain=["events", "timestamp"])])],
                    ),
                )
            )
            # Only the repeat-conversion mode needs an upper end of its own; see the caller.
            if self.allows_multiple_conversions_per_visitor:
                select.append(
                    ast.Alias(
                        alias="last_conversion",
                        expr=ast.Call(
                            name="max",
                            args=[ast.Call(name="toUnixTimestamp", args=[ast.Field(chain=["events", "timestamp"])])],
                        ),
                    )
                )
        return ast.SelectQuery(
            select=select,
            select_from=ast.JoinExpr(table=ast.Field(chain=["events"])),
            where=ast.And(
                exprs=[
                    self.conversion_condition,
                    *self._event_date_conditions(date_range),
                    *self._test_account_conditions(),
                ]
            ),
            group_by=[ast.Field(chain=["events", "person_id"])],
        )

    def _build_warehouse_person_arrays_select(
        self, date_range: QueryDateRange, goal: ConversionGoalFilter3
    ) -> ast.SelectQuery:
        if self._test_account_conditions():
            raise ValueError(
                "Warehouse attribution cannot apply event or person test-account filters yet. "
                "Filter test accounts in the conversion source and turn off test-account filtering for this query."
            )
        if self.query.properties:
            raise ValueError(
                "Warehouse attribution does not support query property filters yet. Add filters to the goal."
            )
        source = WarehouseConversionSource(goal=goal, team=self.team, database=self._shared_hogql_database)
        people = parse_select(
            """
            SELECT
                if(notEmpty(coalesce(identity.distinct_id, '')), toString(identity.person_id),
                    if(empty(conversions.distinct_id), concat('unmatched_conversion:', conversions.conversion_id),
                        concat('unmatched_person:', conversions.distinct_id))) AS person_id,
                arraySlice(arraySort(groupArray((conversions.timestamp, conversions.value))),
                    {conversion_offset}, {conversion_limit}) AS conversions,
                {conversion_count} AS conversion_count,
                min(conversions.timestamp) AS first_conversion,
                max(conversions.timestamp) AS last_conversion
            FROM warehouse_conversions AS conversions
            LEFT JOIN (
                SELECT distinct_id, person_id FROM person_distinct_ids
                WHERE distinct_id IN (SELECT distinct_id FROM warehouse_conversions)
            ) AS identity ON conversions.distinct_id = identity.distinct_id
            GROUP BY person_id
            """,
            placeholders={
                "conversion_offset": ast.Constant(
                    value=-MAX_CONVERSIONS_PER_PERSON if self.allows_multiple_conversions_per_visitor else 1
                ),
                "conversion_limit": ast.Constant(
                    value=MAX_CONVERSIONS_PER_PERSON if self.allows_multiple_conversions_per_visitor else 1
                ),
                "conversion_count": ast.Call(name="count", args=[])
                if self.allows_multiple_conversions_per_visitor
                else ast.Constant(value=1),
            },
        )
        touchpoints = parse_select(
            """
            SELECT toString(events.person_id) AS person_id,
                arraySlice(arraySort(groupUniqArray(({session_start}, {breakdown}))), {touchpoint_offset}) AS touchpoints
            FROM events
            INNER JOIN warehouse_people AS bounds ON toString(events.person_id) = bounds.person_id
            WHERE {touchpoint_condition} AND {lookback_conditions}
                AND {session_start} >= bounds.first_conversion - {window}
                AND {session_start} <= {last_conversion}
            GROUP BY events.person_id
            """,
            placeholders={
                "session_start": ast.Call(
                    name="toUnixTimestamp", args=[ast.Field(chain=["events", "session", "$start_timestamp"])]
                ),
                "breakdown": self._breakdown_expr(),
                "touchpoint_offset": ast.Constant(value=-MAX_TOUCHPOINTS_PER_PERSON),
                "touchpoint_condition": self._touchpoint_condition(),
                "lookback_conditions": ast.And(exprs=self._lookback_date_conditions(date_range)),
                "window": ast.Constant(value=self.attribution_window_seconds),
                "last_conversion": ast.Field(
                    chain=[
                        "bounds",
                        "last_conversion" if self.allows_multiple_conversions_per_visitor else "first_conversion",
                    ]
                ),
            },
        )
        assert isinstance(touchpoints, ast.SelectQuery)
        assert touchpoints.select_from and touchpoints.select_from.next_join
        # Broadcast the materialized converter set to each events shard.
        touchpoints.select_from.next_join.join_type = "GLOBAL INNER JOIN"
        query = parse_select(
            """
            SELECT people.person_id, people.conversions, people.conversion_count,
                coalesce(touches.touchpoints, []) AS touchpoints
            FROM warehouse_people AS people
            LEFT JOIN {touchpoints} AS touches ON people.person_id = touches.person_id
            """,
            placeholders={"touchpoints": touchpoints},
        )
        assert isinstance(query, ast.SelectQuery)
        query.ctes = {
            "warehouse_conversions": ast.CTE(
                name="warehouse_conversions",
                expr=source.build_query(date_range),
                cte_type="subquery",
                materialized=True,
            ),
            "warehouse_people": ast.CTE(name="warehouse_people", expr=people, cte_type="subquery", materialized=True),
        }
        return query

    def _person_arrays_select(self, date_range: QueryDateRange) -> ast.SelectQuery:
        """The credit side, using shared session resolution when eligible."""
        if self.config.live_session_resolution_enabled:
            from .attribution_sessions_read import build_person_arrays  # noqa: PLC0415 (import cycle)

            with self.timings.measure("attribution_live_session_resolution"):
                resolved = build_person_arrays(self, date_range)
            if resolved is not None:
                self._live_session_resolution_used = True
                return resolved
        return self._build_person_arrays_select(date_range)

    def _build_person_arrays_select(self, date_range: QueryDateRange) -> ast.SelectQuery:
        """One row per converting person: its conversions, plus a deduped touchpoint set.

        Both arrays hold (timestamp, payload) tuples rather than parallel arrays indexed together, since
        `groupArray` gives no ordering guarantee and separate arrays could pair one conversion's timestamp
        with another's value.

        The `-If` combinators only append when the row qualifies, so neither array grows with the
        person's unrelated events. `groupUniqArray` additionally collapses every pageview in a session to
        one touchpoint during aggregation.
        """
        if isinstance(self.goal, ConversionGoalFilter3):
            return self._build_warehouse_person_arrays_select(date_range, self.goal)

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
                        *self._event_date_conditions(date_range),
                    ]
                ),
            ],
        )

        # Only the repeat-conversion mode can credit anything after the person's first conversion; the
        # other mode keeps that conversion alone, so `first_conversion` closes the window on both sides.
        upper_bound_field = "last_conversion" if self.allows_multiple_conversions_per_visitor else "first_conversion"
        session_start = ast.Call(
            name="toUnixTimestamp", args=[ast.Field(chain=["events", "session", "$start_timestamp"])]
        )
        window_opens = ast.ArithmeticOperation(
            left=ast.Field(chain=["conv_bounds", "first_conversion"]),
            op=ast.ArithmeticOperationOp.Sub,
            right=ast.Constant(value=self.attribution_window_seconds),
        )

        # A session that starts before this person's window opens, or after their last creditable
        # conversion, earns credit from none of them, so it never has to enter the array. Bounds the
        # session start rather than the event timestamp because that is the value stored as the
        # touchpoint: a session starting before the last conversion is creditable even when its only
        # pageview lands after it.
        creditable_touchpoint = ast.And(
            exprs=[
                self._touchpoint_condition(),
                ast.CompareOperation(left=session_start, op=ast.CompareOperationOp.GtEq, right=window_opens),
                ast.CompareOperation(
                    left=session_start,
                    op=ast.CompareOperationOp.LtEq,
                    right=ast.Field(chain=["conv_bounds", upper_bound_field]),
                ),
            ]
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
                                creditable_touchpoint,
                            ],
                        )
                    ],
                ),
                ast.Constant(value=-MAX_TOUCHPOINTS_PER_PERSON),
            ],
        )

        # The person's conversion total before MAX_CONVERSIONS_PER_PERSON truncates the array. The
        # footers report "N of M" as an exact count, so M has to be counted here rather than off the
        # capped array; a conversion the cap removed is reported as unattributed, not as absent.
        conversion_count: ast.Expr = ast.Call(name="length", args=[ast.Field(chain=["conversions"])])

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
        else:
            conversion_count = ast.Call(
                name="countIf",
                args=[
                    ast.And(
                        exprs=[
                            self.conversion_condition,
                            *self._event_date_conditions(date_range),
                        ]
                    )
                ],
            )
            conversions = ast.Call(
                name="arraySlice",
                args=[
                    ast.Call(name="arraySort", args=[conversions]),
                    ast.Constant(value=-MAX_CONVERSIONS_PER_PERSON),
                ],
            )

        return ast.SelectQuery(
            select=[
                ast.Field(chain=["events", "person_id"]),
                ast.Alias(alias="conversions", expr=conversions),
                ast.Alias(alias=PERSON_CONVERSION_COUNT, expr=conversion_count),
                ast.Alias(alias="touchpoints", expr=touchpoints),
            ],
            select_from=ast.JoinExpr(
                table=ast.Field(chain=["events"]),
                next_join=ast.JoinExpr(
                    join_type="INNER JOIN",
                    table=self._build_converters_select(date_range, with_bounds=True),
                    alias="conv_bounds",
                    constraint=ast.JoinConstraint(
                        expr=ast.CompareOperation(
                            left=ast.Field(chain=["events", "person_id"]),
                            op=ast.CompareOperationOp.Eq,
                            right=ast.Field(chain=["conv_bounds", "person_id"]),
                        ),
                        constraint_type="ON",
                    ),
                ),
            ),
            where=ast.And(
                exprs=[
                    ast.Or(
                        exprs=[
                            ast.And(
                                exprs=[
                                    self.conversion_condition,
                                    *self._event_date_conditions(date_range),
                                ]
                            ),
                            ast.And(
                                exprs=[
                                    self._pageview_condition(),
                                    *self._lookback_date_conditions(date_range),
                                    # Narrower than the lookback bound above, and per person: an event
                                    # before this person's window opens belongs to a session that
                                    # started before it too, so no conversion of theirs can credit it.
                                    #
                                    # Reads the event timestamp, not the session start the touchpoint
                                    # is keyed on, so the scan drops these rows without the session
                                    # join having to resolve them first. The upper end has no such
                                    # cheap form and is applied on the collected array instead.
                                    ast.CompareOperation(
                                        left=ast.Call(
                                            name="toUnixTimestamp", args=[ast.Field(chain=["events", "timestamp"])]
                                        ),
                                        op=ast.CompareOperationOp.GtEq,
                                        right=window_opens,
                                    ),
                                ]
                            ),
                        ]
                    ),
                    # Outside the OR on purpose. Internal traffic is internal on both arms, and putting
                    # this inside each branch would say the same thing twice.
                    *self._test_account_conditions(),
                ]
            ),
            group_by=[ast.Field(chain=["events", "person_id"])],
            having=ast.CompareOperation(
                left=ast.Call(name="length", args=[ast.Field(chain=["conversions"])]),
                op=ast.CompareOperationOp.Gt,
                right=ast.Constant(value=0),
            ),
        )

    def _total_conversions_expr(self, conversion_index: str) -> ast.Expr:
        """The exact conversion total, for a footer reading a CTE exploded by conversion.

        Counting the exploded rows would report the capped total. Every row of one person carries that
        person's true count instead, so summing it on the first index alone counts each person once.
        """
        return ast.Call(
            name="sumIf",
            args=[
                ast.Field(chain=[PERSON_CONVERSION_COUNT]),
                ast.CompareOperation(
                    left=ast.Field(chain=[conversion_index]),
                    op=ast.CompareOperationOp.Eq,
                    right=ast.Constant(value=1),
                ),
            ],
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
