"""Retention explorer: how well the users each channel brings in stick around.

The attribution table answers "which channel produces conversions". This answers the half that table
can't: whether those users come back. A channel can lead on last-touch conversions and trail every other
channel four weeks later, and nothing in marketing analytics surfaces that today.

Cohorting is by acquisition, not by activity: a person is bucketed once, by the dimension of their
**first** session, and then followed forward. That is what makes a row mean "the users this channel
brought me", rather than "the events that happened to carry this channel's tag" — which is what a plain
`RetentionQuery` with a session-property breakdown would give, and which mixes several channels into one
person's history.

One question, deliberately: do the users this channel brings come back? Cohorts open on arrival, the
columns count return visits, and every cell is a share of the cohort — `retentionReference: 'total'`,
which is the default in core retention and hardcoded on the web analytics tile, so the same percentage
means the same thing wherever a marketer reads it.

Conversion goals are not an axis here yet, and that is a decision rather than an omission. Cohorting on
a goal, or counting conversions in the columns, makes the table a distribution of when people converted
instead of a retention curve: the first column stops being the cohort, the columns stop being a
shrinking group, and for a goal completed once each person lands in exactly one of them. Different chart,
different reading rules — its own iteration, not a dropdown on this one.

Two things this deliberately does that core retention does not:

1. `onlyNewUsers` excludes anyone who was already here before the range. Without it, a channel's cohorts
   are inflated by its own returning traffic, and every channel's week 0 looks larger than its true
   intake.
2. The breakdown value goes through the team's source and campaign normalization (see
   `session_breakdown_base`), so a channel row here keys the same way it does on the cost side.
"""

from datetime import datetime, timedelta
from functools import cached_property
from typing import Any

from posthog.schema import (
    CachedMarketingAnalyticsRetentionQueryResponse,
    IntervalType,
    MarketingAnalyticsRetentionCell,
    MarketingAnalyticsRetentionInterval,
    MarketingAnalyticsRetentionQuery,
    MarketingAnalyticsRetentionQueryResponse,
    MarketingAnalyticsRetentionRow,
)

from posthog.hogql import ast
from posthog.hogql.constants import MAX_BYTES_BEFORE_EXTERNAL_GROUP_BY, HogQLGlobalSettings, LimitContext
from posthog.hogql.property import property_to_expr
from posthog.hogql.query import execute_hogql_query

from posthog.hogql_queries.insights.utils.breakdowns import BREAKDOWN_OTHER_STRING_LABEL
from posthog.hogql_queries.insights.utils.utils import get_start_of_interval_hogql
from posthog.hogql_queries.utils.query_date_range import QueryDateRange, date_to_start_of_interval

from .session_breakdown_base import MarketingSessionBreakdownQueryRunnerBase

# Weekly by default. A daily grain over a 90-day range is 90 cohort rows per breakdown value before
# anyone has misconfigured anything, and marketing questions are asked in weeks anyway.
DEFAULT_INTERVAL = MarketingAnalyticsRetentionInterval.WEEK
DEFAULT_TOTAL_INTERVALS = 8
DEFAULT_BREAKDOWN_LIMIT = 20
DEFAULT_NEW_USER_LOOKBACK_DAYS = 90

# Clamped rather than rejected: these come from a query the frontend builds, so an out-of-range value is
# a bug to contain, not a message to show a marketer. The ceilings bound the matrix at
# MAX_COHORTS x MAX_TOTAL_INTERVALS cells per breakdown value.
MAX_TOTAL_INTERVALS = 40
MAX_COHORTS = 60
# Chosen so the widest matrix still fits under `MAX_SELECT_RETENTION_LIMIT`: the outer select emits one
# row per cell plus the folded row, and 41 x 60 x 40 + 1 is under 100k. Raising any of these three
# without checking that product would put the printer's row cap back in play, and the rows it drops are
# whole breakdown values off the end of the alphabet — exactly what folding exists to prevent.
MAX_BREAKDOWN_LIMIT = 40
MAX_NEW_USER_LOOKBACK_DAYS = 365

# Label the long tail of breakdown values roll up under, shared with core retention so the two surfaces
# print the same thing.
_OTHER = BREAKDOWN_OTHER_STRING_LABEL

_INTERVAL_TO_TYPE: dict[MarketingAnalyticsRetentionInterval, IntervalType] = {
    MarketingAnalyticsRetentionInterval.DAY: IntervalType.DAY,
    MarketingAnalyticsRetentionInterval.WEEK: IntervalType.WEEK,
    MarketingAnalyticsRetentionInterval.MONTH: IntervalType.MONTH,
}

_INTERVAL_LABEL: dict[MarketingAnalyticsRetentionInterval, str] = {
    MarketingAnalyticsRetentionInterval.DAY: "Day",
    MarketingAnalyticsRetentionInterval.WEEK: "Week",
    MarketingAnalyticsRetentionInterval.MONTH: "Month",
}


# CTE names.
_ACQUISITION_CTE = "acquisition"
_ACTIVITY_CTE = "activity"
_COHORT_SIZES_CTE = "cohort_sizes"
_MATRIX_CTE = "matrix"
_FOLDED_SIZES_CTE = "folded_sizes"
_FOLDED_MATRIX_CTE = "folded_matrix"
_SUMMARY_CTE = "summary"

# Column names, shared between the SQL builders and `_calculate`.
_ACTOR_ID = "actor_id"
_BREAKDOWN_VALUE = "breakdown_value"
_FIRST_SESSION_AT = "first_session_at"
# What decides a person's row. The first session under an arrival start, their first conversion under a
# goal start — kept separate from `first_session_at`, which always means the session the breakdown reads.
_COHORT_AT = "cohort_at"
_ACTIVITY_INDEX = "activity_index"
_COHORT_INDEX = "cohort_index"
_COHORT_SIZE = "cohort_size"
_INTERVALS_FROM_BASE = "intervals_from_base"
_COUNT = "count"
_DISTINCT_BREAKDOWNS = "distinct_breakdowns"


class MarketingAnalyticsRetentionQueryRunner(
    MarketingSessionBreakdownQueryRunnerBase[MarketingAnalyticsRetentionQueryResponse]
):
    query: MarketingAnalyticsRetentionQuery
    response: MarketingAnalyticsRetentionQueryResponse
    cached_response: CachedMarketingAnalyticsRetentionQueryResponse

    def __init__(self, *args: Any, **kwargs: Any) -> None:
        super().__init__(*args, **kwargs)
        # A cohorts x columns matrix per breakdown value blows past the default row cap long before the
        # result is unreasonable, so escalate the same way `RetentionQueryRunner` does.
        if self.limit_context in (LimitContext.QUERY, LimitContext.QUERY_ASYNC):
            self.limit_context = LimitContext.RETENTION

    # ------------------------------------------------------------------ options

    @property
    def retention_interval(self) -> MarketingAnalyticsRetentionInterval:
        return self.query.retentionInterval or DEFAULT_INTERVAL

    @property
    def only_new_users(self) -> bool:
        return True if self.query.onlyNewUsers is None else self.query.onlyNewUsers

    @property
    def new_user_lookback_days(self) -> int:
        requested = self.query.newUserLookbackDays or DEFAULT_NEW_USER_LOOKBACK_DAYS
        return max(1, min(requested, MAX_NEW_USER_LOOKBACK_DAYS))

    @property
    def breakdown_limit(self) -> int:
        requested = self.query.breakdownLimit or DEFAULT_BREAKDOWN_LIMIT
        return max(1, min(requested, MAX_BREAKDOWN_LIMIT))

    @cached_property
    def query_date_range(self) -> QueryDateRange:
        """Overrides the base runner's interval-less range: every expression here buckets by period, and
        the cohort rows are one per period, so the range has to know which interval it is counting in."""
        return QueryDateRange(
            date_range=self.query.dateRange,
            team=self.team,
            interval=_INTERVAL_TO_TYPE[self.retention_interval],
            now=datetime.now(),
        )

    @cached_property
    def _period_count(self) -> int:
        """Aligned periods the requested range spans, before the cohort clamp.

        Computed arithmetically rather than by enumerating the range, because `dateRange` is
        caller-controlled: a daily grain over years 0001-9999 would materialize millions of datetimes
        just to slice off the last MAX_COHORTS. Zero or negative when the range is inverted, which
        `cohort_starts` floors at one.
        """
        start = self._aligned(self.query_date_range.date_from())
        end = self._aligned(self.query_date_range.date_to())
        if self.retention_interval == MarketingAnalyticsRetentionInterval.MONTH:
            spans = (end.year - start.year) * 12 + end.month - start.month
        elif self.retention_interval == MarketingAnalyticsRetentionInterval.WEEK:
            spans = (end - start).days // 7
        else:
            spans = (end - start).days
        return spans + 1

    def _aligned(self, moment: datetime) -> datetime:
        interval = _INTERVAL_TO_TYPE[self.retention_interval]
        return date_to_start_of_interval(moment, interval, self.team)

    @cached_property
    def cohort_starts(self) -> list[datetime]:
        """One entry per cohort row: the aligned start of each acquisition period in the range.

        Truncated to the most recent MAX_COHORTS, because an old cohort with few columns left to show is
        the least interesting part of a range someone widened by accident.

        Always at least one entry. An inverted range spans no periods, and every expression below reads
        `cohort_starts[0]` as the window's anchor, so an empty list would fail the query on an index
        error rather than return the empty table the range actually describes.
        """
        kept = max(1, min(self._period_count, MAX_COHORTS))
        end = self._aligned(self.query_date_range.date_to())
        step = self.query_date_range.interval_relativedelta()
        return [end - step * offset for offset in reversed(range(kept))]

    @property
    def truncated_cohorts(self) -> int:
        """Older cohorts the clamp dropped. Reported, because the clamp also pulls the whole scan's
        lower bound forward — the table then covers less than the date range the filter bar shows."""
        return max(self._period_count - len(self.cohort_starts), 0)

    @property
    def interval_count(self) -> int:
        """Column count. Never more than the number of cohorts, since a wider matrix would be all
        greyed-out cells the range can't fill."""
        requested = self.query.totalIntervals or DEFAULT_TOTAL_INTERVALS
        clamped = max(1, min(requested, MAX_TOTAL_INTERVALS))
        return min(clamped, len(self.cohort_starts))

    # ------------------------------------------------------------------ expressions

    def _interval_index_expr(self, source: ast.Expr) -> ast.Expr:
        """How many periods `source` sits after the first cohort's start.

        Both ends go through `get_start_of_interval_hogql`, which is what core retention uses, so a
        team whose week starts on Sunday gets the same week boundaries on both surfaces.
        """
        interval = _INTERVAL_TO_TYPE[self.retention_interval].value
        return ast.Call(
            name="dateDiff",
            args=[
                ast.Constant(value=interval),
                get_start_of_interval_hogql(
                    interval,
                    team=self.team,
                    source=ast.Call(name="toDateTime", args=[ast.Constant(value=self._cohort_window_start_str)]),
                ),
                get_start_of_interval_hogql(interval, team=self.team, source=source),
            ],
        )

    @property
    def _cohort_window_start_str(self) -> str:
        return self.query_date_range.format_date(self.cohort_starts[0])

    @property
    def _cohort_window_end_str(self) -> str:
        return self.query_date_range.date_to_str

    def _range_conditions(self, field: ast.Expr) -> list[ast.Expr]:
        return [
            ast.CompareOperation(
                left=field,
                op=ast.CompareOperationOp.GtEq,
                right=ast.Call(name="toDateTime", args=[ast.Constant(value=self._cohort_window_start_str)]),
            ),
            ast.CompareOperation(
                left=field,
                op=ast.CompareOperationOp.LtEq,
                right=ast.Call(name="toDateTime", args=[ast.Constant(value=self._cohort_window_end_str)]),
            ),
        ]

    def _event_filters(self) -> list[ast.Expr]:
        """The query's own property filters plus the team's test-account filters, applied to every arm
        so the cohort side and the activity side select the same population."""
        exprs: list[ast.Expr] = []
        if self.query.properties:
            exprs.append(property_to_expr(self.query.properties, self.team))
        if self.query.filterTestAccounts and self.team.test_account_filters:
            exprs.extend(property_to_expr(prop, self.team) for prop in self.team.test_account_filters)
        return exprs

    # ------------------------------------------------------------------ CTEs

    def _build_pre_existing_select(self) -> ast.SelectQuery:
        """(A) Persons who were already here before the range started.

        Deliberately a bare pageview rather than `_touchpoint_condition()`: "has this person been here
        before" must not depend on `excludeDirectTraffic`, or excluding direct would make every
        direct-acquired returning visitor look brand new and inflate the paid channels' cohorts.

        `_event_filters()` is applied, though, and that is the deliberate other half: a property filter
        narrows the whole question to a segment, so "new" means new to that segment. Dropping it here
        would let someone who has been around for a year outside the filter count as newly acquired
        inside it — the reverse of what the switch is for.
        """
        return ast.SelectQuery(
            select=[ast.Field(chain=["events", "person_id"])],
            distinct=True,
            select_from=ast.JoinExpr(table=ast.Field(chain=["events"])),
            where=ast.And(
                exprs=[
                    self._pageview_condition(),
                    ast.Call(name="notEmpty", args=[ast.Field(chain=["events", "$session_id"])]),
                    ast.CompareOperation(
                        left=ast.Field(chain=["events", "timestamp"]),
                        op=ast.CompareOperationOp.GtEq,
                        right=ast.ArithmeticOperation(
                            left=ast.Call(name="toDateTime", args=[ast.Constant(value=self._cohort_window_start_str)]),
                            op=ast.ArithmeticOperationOp.Sub,
                            right=ast.Call(
                                name="toIntervalDay", args=[ast.Constant(value=self.new_user_lookback_days)]
                            ),
                        ),
                    ),
                    ast.CompareOperation(
                        left=ast.Field(chain=["events", "timestamp"]),
                        op=ast.CompareOperationOp.Lt,
                        right=ast.Call(name="toDateTime", args=[ast.Constant(value=self._cohort_window_start_str)]),
                    ),
                    *self._event_filters(),
                ]
            ),
        )

    def _build_first_session_select(self) -> ast.SelectQuery:
        """(B) One row per acquired person: when they first arrived, and what brought them.

        `argMin` over the session start is the whole first-touch semantic. Note it is deliberately not
        the attribution runners' person-array collection, which is scoped to converters and keeps the
        *most recent* sessions after truncation — both wrong ends for this question.

        Both timestamp bounds are needed. The `events.timestamp` pair prunes parts on the table's order
        key; the `session.$start_timestamp` pair is what actually defines "acquired in this window", and
        without it a person's first session could sit before the range while one of its later pageviews
        pulls them in.
        """
        session_start = ast.Field(chain=["events", "session", "$start_timestamp"])

        conditions: list[ast.Expr] = [
            self._touchpoint_condition(),
            *self._range_conditions(ast.Field(chain=["events", "timestamp"])),
            *self._range_conditions(session_start),
            *self._event_filters(),
        ]
        if self.only_new_users:
            conditions.append(
                ast.CompareOperation(
                    left=ast.Field(chain=["events", "person_id"]),
                    op=ast.CompareOperationOp.NotIn,
                    right=self._build_pre_existing_select(),
                )
            )

        return ast.SelectQuery(
            select=[
                ast.Alias(alias=_ACTOR_ID, expr=ast.Field(chain=["events", "person_id"])),
                ast.Alias(alias=_FIRST_SESSION_AT, expr=ast.Call(name="min", args=[session_start])),
                ast.Alias(
                    alias=_BREAKDOWN_VALUE,
                    expr=ast.Call(name="argMin", args=[self._breakdown_expr(), session_start]),
                ),
            ],
            select_from=ast.JoinExpr(table=ast.Field(chain=["events"])),
            where=ast.And(exprs=conditions),
            group_by=[ast.Field(chain=[_ACTOR_ID])],
        )

    def _build_acquisition_select(self) -> ast.SelectQuery:
        """(C) One row per person in the table: the period they arrived in, and under which value.

        The first session relabelled: arriving *is* the acquisition, so the period a person belongs to
        and the value they are credited to both come from it.
        """
        first_session = self._build_first_session_select()
        for column in first_session.select:
            if isinstance(column, ast.Alias) and column.alias == _FIRST_SESSION_AT:
                column.alias = _COHORT_AT
        return first_session

    def _build_activity_select(self) -> ast.SelectQuery:
        """(C) One row per person per period they came back in.

        Collapsed to (person, period) here rather than at the join, so the join below fans out by
        periods a person was active in rather than by their every event.

        Restricted to the acquired persons, which the matrix join would discard anyway. It matters
        because this is the join's build side: without the restriction it is every active person in the
        range, and under `onlyNewUsers` the cohort can be a small fraction of that.
        """
        return ast.SelectQuery(
            select=[
                ast.Alias(alias=_ACTOR_ID, expr=ast.Field(chain=["events", "person_id"])),
                ast.Alias(
                    alias=_ACTIVITY_INDEX,
                    expr=self._interval_index_expr(ast.Field(chain=["events", "timestamp"])),
                ),
            ],
            select_from=ast.JoinExpr(table=ast.Field(chain=["events"])),
            where=ast.And(
                exprs=[
                    self._pageview_condition(),
                    *self._range_conditions(ast.Field(chain=["events", "timestamp"])),
                    ast.CompareOperation(
                        left=ast.Field(chain=["events", "person_id"]),
                        op=ast.CompareOperationOp.In,
                        right=ast.SelectQuery(
                            select=[ast.Field(chain=[_ACTOR_ID])],
                            select_from=ast.JoinExpr(table=ast.Field(chain=[_ACQUISITION_CTE])),
                        ),
                    ),
                    *self._event_filters(),
                ]
            ),
            group_by=[ast.Field(chain=[_ACTOR_ID]), ast.Field(chain=[_ACTIVITY_INDEX])],
        )

    def _build_cohort_sizes_select(self) -> ast.SelectQuery:
        """(D) How many people each channel brought in, per acquisition period.

        Also the period-0 cell of every row, which the matrix no longer emits: the cohort is exactly the
        people who did the starting event, so its own size is what that column counts.
        """
        return ast.SelectQuery(
            select=[
                ast.Field(chain=[_BREAKDOWN_VALUE]),
                ast.Alias(alias=_COHORT_INDEX, expr=self._interval_index_expr(ast.Field(chain=[_COHORT_AT]))),
                ast.Alias(
                    alias=_COHORT_SIZE,
                    expr=ast.Call(name="count", args=[ast.Field(chain=[_ACTOR_ID])], distinct=True),
                ),
            ],
            select_from=ast.JoinExpr(table=ast.Field(chain=[_ACQUISITION_CTE])),
            group_by=[ast.Field(chain=[_BREAKDOWN_VALUE]), ast.Field(chain=[_COHORT_INDEX])],
        )

    def _build_matrix_select(self) -> ast.SelectQuery:
        """(E) The cells: people from one cohort seen again N periods later."""
        cohort_index = self._interval_index_expr(ast.Field(chain=[_ACQUISITION_CTE, _COHORT_AT]))
        intervals_from_base = ast.ArithmeticOperation(
            left=ast.Field(chain=[_ACTIVITY_CTE, _ACTIVITY_INDEX]),
            op=ast.ArithmeticOperationOp.Sub,
            right=cohort_index,
        )

        return ast.SelectQuery(
            select=[
                ast.Field(chain=[_ACQUISITION_CTE, _BREAKDOWN_VALUE]),
                ast.Alias(alias=_COHORT_INDEX, expr=cohort_index),
                ast.Alias(alias=_INTERVALS_FROM_BASE, expr=intervals_from_base),
                ast.Alias(
                    alias=_COUNT,
                    expr=ast.Call(name="count", args=[ast.Field(chain=[_ACQUISITION_CTE, _ACTOR_ID])], distinct=True),
                ),
            ],
            select_from=ast.JoinExpr(
                table=ast.Field(chain=[_ACQUISITION_CTE]),
                next_join=ast.JoinExpr(
                    join_type="INNER JOIN",
                    table=ast.Field(chain=[_ACTIVITY_CTE]),
                    constraint=ast.JoinConstraint(
                        expr=ast.CompareOperation(
                            left=ast.Field(chain=[_ACTIVITY_CTE, _ACTOR_ID]),
                            op=ast.CompareOperationOp.Eq,
                            right=ast.Field(chain=[_ACQUISITION_CTE, _ACTOR_ID]),
                        ),
                        constraint_type="ON",
                    ),
                ),
            ),
            group_by=[
                ast.Field(chain=[_ACQUISITION_CTE, _BREAKDOWN_VALUE]),
                ast.Field(chain=[_COHORT_INDEX]),
                ast.Field(chain=[_INTERVALS_FROM_BASE]),
            ],
            having=ast.And(
                exprs=[
                    ast.CompareOperation(
                        left=ast.Field(chain=[_INTERVALS_FROM_BASE]),
                        op=ast.CompareOperationOp.GtEq,
                        right=ast.Constant(value=0),
                    ),
                    ast.CompareOperation(
                        left=ast.Field(chain=[_INTERVALS_FROM_BASE]),
                        op=ast.CompareOperationOp.Lt,
                        right=ast.Constant(value=self.interval_count),
                    ),
                ]
            ),
        )

    def _build_top_breakdowns_select(self) -> ast.SelectQuery:
        """(F) The breakdown values big enough to get their own rows.

        Ranked by people acquired across the whole range, not by any single cell. Ranking on period 0 —
        the obvious alternative — breaks under a conversion-goal return event, where a channel with a
        large intake can legitimately have near-zero conversions in the acquisition period itself.
        """
        return ast.SelectQuery(
            select=[ast.Field(chain=[_BREAKDOWN_VALUE])],
            select_from=ast.JoinExpr(table=ast.Field(chain=[_COHORT_SIZES_CTE])),
            group_by=[ast.Field(chain=[_BREAKDOWN_VALUE])],
            order_by=[
                ast.OrderExpr(expr=ast.Call(name="sum", args=[ast.Field(chain=[_COHORT_SIZE])]), order="DESC"),
                # Ties broken by name so the same data always folds the same way.
                ast.OrderExpr(expr=ast.Field(chain=[_BREAKDOWN_VALUE]), order="ASC"),
            ],
            limit=ast.Constant(value=self.breakdown_limit),
        )

    def _display_value_expr(self, field: ast.Expr) -> ast.Expr:
        """The label a breakdown value renders under: itself, or 'Other'.

        Folding happens here, in SQL, rather than over whatever rows a row cap happened to return. A
        high-cardinality breakdown — landing page especially — produces far more rows than any cap would
        keep, and truncating them by the outer ORDER BY drops whole values alphabetically: they would be
        neither shown nor counted as folded.
        """
        return ast.Call(
            name="if",
            args=[
                ast.CompareOperation(
                    left=field, op=ast.CompareOperationOp.In, right=self._build_top_breakdowns_select()
                ),
                field,
                ast.Constant(value=_OTHER),
            ],
        )

    def _build_folded_sizes_select(self) -> ast.SelectQuery:
        """(G) Cohort sizes after folding. Summed, because several values can share the 'Other' label."""
        return ast.SelectQuery(
            select=[
                ast.Alias(alias=_BREAKDOWN_VALUE, expr=self._display_value_expr(ast.Field(chain=[_BREAKDOWN_VALUE]))),
                ast.Field(chain=[_COHORT_INDEX]),
                ast.Alias(alias=_COHORT_SIZE, expr=ast.Call(name="sum", args=[ast.Field(chain=[_COHORT_SIZE])])),
            ],
            select_from=ast.JoinExpr(table=ast.Field(chain=[_COHORT_SIZES_CTE])),
            group_by=[ast.Field(chain=[_BREAKDOWN_VALUE]), ast.Field(chain=[_COHORT_INDEX])],
        )

    def _build_folded_matrix_select(self) -> ast.SelectQuery:
        """(H) Cells after folding.

        Summing counts across folded values is exact rather than approximate: a person has one
        acquisition breakdown value, so no one can be counted under two of the values being merged.
        """
        return ast.SelectQuery(
            select=[
                ast.Alias(alias=_BREAKDOWN_VALUE, expr=self._display_value_expr(ast.Field(chain=[_BREAKDOWN_VALUE]))),
                ast.Field(chain=[_COHORT_INDEX]),
                ast.Field(chain=[_INTERVALS_FROM_BASE]),
                ast.Alias(alias=_COUNT, expr=ast.Call(name="sum", args=[ast.Field(chain=[_COUNT])])),
            ],
            select_from=ast.JoinExpr(table=ast.Field(chain=[_MATRIX_CTE])),
            group_by=[
                ast.Field(chain=[_BREAKDOWN_VALUE]),
                ast.Field(chain=[_COHORT_INDEX]),
                ast.Field(chain=[_INTERVALS_FROM_BASE]),
            ],
        )

    def _build_summary_select(self) -> ast.SelectQuery:
        """(I) One row saying how many breakdown values existed before folding.

        Its own CTE rather than a SELECT-list scalar, which would be evaluated per output row and would
        report nothing at all when there are no rows to attach it to.
        """
        return ast.SelectQuery(
            select=[
                ast.Alias(
                    alias=_DISTINCT_BREAKDOWNS,
                    expr=ast.Call(name="uniqExact", args=[ast.Field(chain=[_BREAKDOWN_VALUE])]),
                ),
            ],
            select_from=ast.JoinExpr(table=ast.Field(chain=[_COHORT_SIZES_CTE])),
        )

    def _build_outer_select(self) -> ast.SelectQuery:
        """(J) Cohort sizes with their cells attached.

        LEFT from the sizes, so a cohort nobody came back to still emits one row carrying its size —
        otherwise a channel with terrible retention would simply vanish from the table, which reads as
        "no data" rather than as the finding it is.
        """
        return ast.SelectQuery(
            select=[
                ast.Alias(alias=_BREAKDOWN_VALUE, expr=ast.Field(chain=[_FOLDED_SIZES_CTE, _BREAKDOWN_VALUE])),
                ast.Alias(alias=_COHORT_INDEX, expr=ast.Field(chain=[_FOLDED_SIZES_CTE, _COHORT_INDEX])),
                ast.Alias(alias=_COHORT_SIZE, expr=ast.Field(chain=[_FOLDED_SIZES_CTE, _COHORT_SIZE])),
                ast.Alias(alias=_INTERVALS_FROM_BASE, expr=ast.Field(chain=[_FOLDED_MATRIX_CTE, _INTERVALS_FROM_BASE])),
                ast.Alias(alias=_COUNT, expr=ast.Field(chain=[_FOLDED_MATRIX_CTE, _COUNT])),
                ast.Alias(alias=_DISTINCT_BREAKDOWNS, expr=ast.Field(chain=[_SUMMARY_CTE, _DISTINCT_BREAKDOWNS])),
            ],
            select_from=ast.JoinExpr(
                table=ast.Field(chain=[_FOLDED_SIZES_CTE]),
                next_join=ast.JoinExpr(
                    join_type="LEFT JOIN",
                    table=ast.Field(chain=[_FOLDED_MATRIX_CTE]),
                    constraint=ast.JoinConstraint(
                        expr=ast.And(
                            exprs=[
                                ast.CompareOperation(
                                    left=ast.Field(chain=[_FOLDED_MATRIX_CTE, _BREAKDOWN_VALUE]),
                                    op=ast.CompareOperationOp.Eq,
                                    right=ast.Field(chain=[_FOLDED_SIZES_CTE, _BREAKDOWN_VALUE]),
                                ),
                                ast.CompareOperation(
                                    left=ast.Field(chain=[_FOLDED_MATRIX_CTE, _COHORT_INDEX]),
                                    op=ast.CompareOperationOp.Eq,
                                    right=ast.Field(chain=[_FOLDED_SIZES_CTE, _COHORT_INDEX]),
                                ),
                            ]
                        ),
                        constraint_type="ON",
                    ),
                    next_join=ast.JoinExpr(
                        join_type="CROSS JOIN",
                        table=ast.Field(chain=[_SUMMARY_CTE]),
                    ),
                ),
            ),
            order_by=[
                ast.OrderExpr(expr=ast.Field(chain=[_BREAKDOWN_VALUE]), order="ASC"),
                ast.OrderExpr(expr=ast.Field(chain=[_COHORT_INDEX]), order="ASC"),
                ast.OrderExpr(expr=ast.Field(chain=[_INTERVALS_FROM_BASE]), order="ASC"),
            ],
            # Folding caps the rows at (breakdown_limit + 1) x cohorts x columns, so this can only bite
            # if one of those clamps is raised without the other. A pure backstop, never a truncation.
            limit=ast.Constant(value=(self.breakdown_limit + 1) * len(self.cohort_starts) * self.interval_count + 1),
        )

    # ------------------------------------------------------------------ main query

    def to_query(self) -> ast.SelectQuery:
        ctes: dict[str, ast.CTE] = {}

        # Materialized because both `cohort_sizes` and `matrix` read it, and ClickHouse re-evaluates an
        # unmaterialized CTE at each reference — the events scan underneath would run twice.
        with self.timings.measure("retention_acquisition_cte"):
            ctes[_ACQUISITION_CTE] = ast.CTE(
                name=_ACQUISITION_CTE,
                expr=self._build_acquisition_select(),
                cte_type="subquery",
                materialized=True,
            )
        with self.timings.measure("retention_activity_cte"):
            ctes[_ACTIVITY_CTE] = ast.CTE(name=_ACTIVITY_CTE, expr=self._build_activity_select(), cte_type="subquery")
        # Materialized for the same reason: four references read it — `summary`, `folded_sizes`, and the
        # `top_breakdowns` subquery that both folding CTEs inline.
        ctes[_COHORT_SIZES_CTE] = ast.CTE(
            name=_COHORT_SIZES_CTE,
            expr=self._build_cohort_sizes_select(),
            cte_type="subquery",
            materialized=True,
        )
        ctes[_MATRIX_CTE] = ast.CTE(name=_MATRIX_CTE, expr=self._build_matrix_select(), cte_type="subquery")
        ctes[_FOLDED_SIZES_CTE] = ast.CTE(
            name=_FOLDED_SIZES_CTE, expr=self._build_folded_sizes_select(), cte_type="subquery"
        )
        ctes[_FOLDED_MATRIX_CTE] = ast.CTE(
            name=_FOLDED_MATRIX_CTE, expr=self._build_folded_matrix_select(), cte_type="subquery"
        )
        ctes[_SUMMARY_CTE] = ast.CTE(name=_SUMMARY_CTE, expr=self._build_summary_select(), cte_type="subquery")

        query = self._build_outer_select()
        query.ctes = ctes
        return query

    # ------------------------------------------------------------------ execution

    def _calculate(self) -> MarketingAnalyticsRetentionQueryResponse:
        query = self.to_query()

        response = execute_hogql_query(
            query_type="marketing_analytics_retention_query",
            query=query,
            team=self.team,
            user=self.user,
            timings=self.timings,
            modifiers=self.modifiers,
            limit_context=self.limit_context or LimitContext.RETENTION,
            context=self._shared_hogql_context,
            settings=HogQLGlobalSettings(max_bytes_before_external_group_by=MAX_BYTES_BEFORE_EXTERNAL_GROUP_BY),
        )

        # Mapped by column name, not tuple position, so adding a column can't shift every later one.
        columns = response.columns or []
        named_results = [dict(zip(columns, row)) for row in response.results or []]

        # Every row carries the same pre-folding breakdown count, so read it off the first one.
        distinct_breakdowns = int(named_results[0].get(_DISTINCT_BREAKDOWNS) or 0) if named_results else 0
        rows = self._build_rows(named_results)

        return MarketingAnalyticsRetentionQueryResponse(
            results=rows,
            intervalCount=self.interval_count,
            interval=self.retention_interval,
            labels=[f"{_INTERVAL_LABEL[self.retention_interval]} {i}" for i in range(self.interval_count)],
            otherBreakdownCount=max(distinct_breakdowns - self.breakdown_limit, 0),
            truncatedCohorts=self.truncated_cohorts,
            totalCohortSize=sum(row.cohortSize for row in rows),
            hogql=response.hogql,
            timings=response.timings,
            modifiers=self.modifiers,
        )

    def _build_rows(self, rows: list[dict[str, Any]]) -> list[MarketingAnalyticsRetentionRow]:
        """Collapse the flat cell list into one dense row per (breakdown value, cohort).

        Period 0 is filled from the cohort size rather than from a cell, because it is not a
        measurement: the cohort is the people who did the starting event, so the column is 100% of
        itself. Every column after it is measured against the one before, which is what makes a row read
        as period-over-period churn instead of as a share of an increasingly distant cohort.

        Dense on purpose: every row gets exactly `interval_count` cells, zero-filled, so the table never
        has to check whether a column exists before rendering it. The zero-fill is also what keeps the
        step rates honest — a period nobody reached is a real zero, and the column after it goes null.
        """
        cohort_starts = self.cohort_starts
        step = self.query_date_range.interval_relativedelta()
        # `date_to()` is the last instant of the range rather than its exclusive end, so an interval
        # ending exactly there would otherwise read as unfinished — greying out the final column of every
        # fully historical range. On an open-ended range `date_to()` is the end of today, which is in the
        # future, so the wall clock is what bounds a period that is still being lived through.
        range_end = min(
            self.query_date_range.date_to() + timedelta(microseconds=1),
            self.query_date_range.now_with_timezone,
        )

        sizes: dict[tuple[str, int], int] = {}
        counts: dict[tuple[str, int], dict[int, int]] = {}
        for row in rows:
            cohort_index = int(row.get(_COHORT_INDEX) or 0)
            if not 0 <= cohort_index < len(cohort_starts):
                # Defensive: `cohort_index` is derived from a session start the WHERE clause already
                # bounds to the cohort window, so this should be unreachable. It guards a list index.
                continue
            key = (str(row.get(_BREAKDOWN_VALUE) or ""), cohort_index)
            # Folded in SQL already, so the size repeats identically across a cohort's cells.
            sizes[key] = int(row.get(_COHORT_SIZE) or 0)
            offset = row.get(_INTERVALS_FROM_BASE)
            if offset is not None:
                counts.setdefault(key, {})[int(offset)] = int(row.get(_COUNT) or 0)

        results: list[MarketingAnalyticsRetentionRow] = []
        for value, cohort_index in sorted(sizes):
            cohort_size = sizes[(value, cohort_index)]
            bucket = counts.get((value, cohort_index), {})
            values: list[MarketingAnalyticsRetentionCell] = []
            for offset in range(self.interval_count):
                count = bucket.get(offset, 0)
                absolute = cohort_index + offset
                # Complete once the period it covers has fully elapsed inside the queried range. Without
                # this the newest cohorts show a real-looking 0%, which reads as churn rather than as a
                # week that hasn't happened yet.
                complete = absolute < len(cohort_starts) and cohort_starts[absolute] + step <= range_end
                values.append(
                    MarketingAnalyticsRetentionCell(
                        count=count,
                        rate=(count / cohort_size) if cohort_size else None,
                        complete=complete,
                    )
                )
            results.append(
                MarketingAnalyticsRetentionRow(
                    breakdownValue=value,
                    cohortDate=cohort_starts[cohort_index].isoformat(),
                    cohortIndex=cohort_index,
                    cohortSize=cohort_size,
                    values=values,
                )
            )
        return results

    def _build_main_select_query(self, conversion_aggregator: Any) -> ast.SelectQuery:
        """Not part of this runner's shape.

        The base hook exists to slot a SELECT into its ad-cost-joined table query; this runner overrides
        `to_query` wholesale and builds its own CTE chain, so there is nothing to hook.
        """
        raise NotImplementedError(f"{type(self).__name__} builds its query in to_query")
