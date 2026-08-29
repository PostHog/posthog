"""Reads the attribution CTEs from the session-grain precompute instead of the sessions lazy join.

A row in `marketing_sessions_dimensional_preaggregated` is a touchpoint: it carries the person, the
session start and the dimension, all resolved at write time. That removes the channel classifier from
the read path, which is what puts these queries on the sessions nodes at 42 GiB.

Returns None rather than raising, so the caller keeps one fallback path for "not eligible", "not warm
yet" and "blew up".
"""

from datetime import UTC, datetime, timedelta
from typing import TYPE_CHECKING, Optional

import structlog

from posthog.schema import MarketingAnalyticsAttributionBreakdown

from posthog.hogql import ast
from posthog.hogql.transforms.preaggregated_table_transformation import is_integer_timezone

from posthog.dataclasses import frozen
from posthog.hogql_queries.utils.query_date_range import QueryDateRange

from products.access_control.backend.facade.api import team_has_property_access_rules
from products.marketing_analytics.backend.hogql_queries.marketing_sessions_precompute import (
    PRECOMPUTE_WINDOW_DAYS,
    SESSION_FORWARD_PAD_MINUTES,
    ensure_marketing_sessions_precomputed,
)

from .attribution_base import MAX_TOUCHPOINTS_PER_PERSON
from .constants import UNKNOWN_CHANNEL
from .session_breakdown_base import UNATTRIBUTED_SESSION_VALUES

if TYPE_CHECKING:
    from .attribution_base import AttributionQueryRunnerBase

logger = structlog.get_logger(__name__)

TABLE = "marketing_sessions_dimensional_preaggregated"

# The widest lookback-extended window this path will read. Derived from what the scheduled job keeps
# warm, minus the day of session pad the read asks for on top: a query past this can never be ready,
# so it fails the gate instead of falling back on every request.
MAX_WINDOW_DAYS = PRECOMPUTE_WINDOW_DAYS - 1

BREAKDOWN_COLUMNS: dict[MarketingAnalyticsAttributionBreakdown, str] = {
    MarketingAnalyticsAttributionBreakdown.CHANNEL: "channel_type",
    MarketingAnalyticsAttributionBreakdown.SOURCE: "utm_source",
    MarketingAnalyticsAttributionBreakdown.CAMPAIGN: "utm_campaign",
    MarketingAnalyticsAttributionBreakdown.MEDIUM: "utm_medium",
    MarketingAnalyticsAttributionBreakdown.CONTENT: "utm_content",
    MarketingAnalyticsAttributionBreakdown.TERM: "utm_term",
    MarketingAnalyticsAttributionBreakdown.REFERRING_DOMAIN: "referring_domain",
    MarketingAnalyticsAttributionBreakdown.LANDING_PAGE: "entry_pathname",
}


def _field(name: str) -> ast.Expr:
    return ast.Field(chain=[name])


def ineligible_reason(runner: "AttributionQueryRunnerBase", date_range: QueryDateRange) -> Optional[str]:
    """Why this query cannot read from the precompute, or None if it can.

    A reason string rather than a bool, so the caller can label the fallback counter: these carry very
    different weight, and an unlabeled counter would blur permanent and transient apart.
    """
    modifiers = runner.modifiers
    if modifiers is not None and modifiers.customChannelTypeRules:
        # The stored channel is the builtin classification; custom rules can key on the full URL,
        # which no precompute holds.
        return "custom_channel_rules"

    if not is_integer_timezone(runner.team.timezone):
        # `period_bucket` is an hourly UTC bucket, so a half-hour-offset team's midnight lands
        # mid-bucket and moves sessions across each edge.
        return "non_integer_timezone"

    if team_has_property_access_rules(team_id=runner.team.id):
        # The rows are userless and shared, so they cannot honor per-user property restrictions.
        return "property_access_controlled"

    read = window(runner, date_range)
    if (read.end - read.start).total_seconds() > MAX_WINDOW_DAYS * 86400:
        return "window_over_max"

    return None


@frozen
class ReadWindow:
    """The span of session activity a query reads: its display range extended back by the attribution
    window, in UTC. Both edges are datetimes, so they are named rather than positional."""

    start: datetime
    end: datetime


def window(runner: "AttributionQueryRunnerBase", date_range: QueryDateRange) -> ReadWindow:
    """Converted before subtracting: subtracting from a team-local aware datetime is wall-clock
    arithmetic, which lands an hour away from the credit side across a DST transition.
    """
    return ReadWindow(
        start=date_range.date_from().astimezone(UTC) - timedelta(seconds=runner.attribution_window_seconds),
        end=date_range.date_to().astimezone(UTC),
    )


def _ensure(runner: "AttributionQueryRunnerBase", date_range: QueryDateRange) -> Optional[list[str]]:
    """The job set backing this query, or None to fall back. Resolved once and cached on the runner:
    reach and credit both call this, and a pair served from different sources reports rates above
    100%, which is the bug the shared window exists to prevent.
    """
    if runner._sessions_precompute_resolved:
        return runner._sessions_precompute_jobs

    runner._sessions_precompute_jobs = _resolve(runner, date_range)
    runner._sessions_precompute_resolved = True
    return runner._sessions_precompute_jobs


def _resolve(runner: "AttributionQueryRunnerBase", date_range: QueryDateRange) -> Optional[list[str]]:
    try:
        # Inside the try: the gates read team configuration and access rules, so a failure there has
        # to fall back like any other, not surface as a query error.
        reason = ineligible_reason(runner, date_range)
        if reason is not None:
            logger.info("attribution_sessions_precompute_ineligible", team_id=runner.team.pk, reason=reason)
            return None

        read = window(runner, date_range)
        # Materialize from a session's length before the window: the writer files a session under the
        # chunk holding its start, so a session that opened earlier and ran into the window lives in
        # the preceding chunk. Reading the window alone leaves that row unwritten, and bounding by
        # event time cannot recover a row that was never built.
        ensure_start = read.start - timedelta(minutes=SESSION_FORWARD_PAD_MINUTES)
        # Check-only: a read must never materialize a cold window on the request thread. A miss
        # falls through to the live path and the scheduled job warms the window instead.
        result = ensure_marketing_sessions_precomputed(runner.team, ensure_start, read.end, run_inserts=False)
    except Exception:
        logger.exception("attribution_sessions_precompute_failed", team_id=runner.team.pk)
        return None
    if not result.job_ids or not result.ready:
        return None
    return [str(j) for j in result.job_ids]


def _scope(job_ids: list[str], read: ReadWindow) -> list[ast.Expr]:
    """Scope to the job set and the window, bounding by event time.

    The live path keeps a session whose events fall in the window and then reports its start as the
    touchpoint time, so a session that opened before the window still counts. Bounding by
    `start_timestamp` dropped exactly those, which moved first-touch credit and shrank the reach
    denominator.
    """
    return [
        ast.Call(name="in", args=[_field("job_id"), ast.Tuple(exprs=[ast.Constant(value=j) for j in job_ids])]),
        ast.CompareOperation(
            left=_field("max_event_timestamp"), op=ast.CompareOperationOp.GtEq, right=ast.Constant(value=read.start)
        ),
        ast.CompareOperation(
            left=_field("min_event_timestamp"), op=ast.CompareOperationOp.LtEq, right=ast.Constant(value=read.end)
        ),
    ]


def _exclusions(runner: "AttributionQueryRunnerBase") -> list[ast.Expr]:
    """Mirror of the exclusion half of `_touchpoint_condition`, against the precompute columns."""
    conditions: list[ast.Expr] = []
    if runner.query.excludeDirectTraffic:
        conditions.append(
            ast.CompareOperation(
                left=_field("channel_type"), op=ast.CompareOperationOp.NotEq, right=ast.Constant(value="Direct")
            )
        )
    if runner.query.excludeUnattributed:
        # Judged on the raw column rather than the display expression, so a friendly fallback label
        # cannot smuggle an empty value back in.
        field = _field(BREAKDOWN_COLUMNS[runner.breakdown])
        conditions.append(
            ast.Call(name="notEmpty", args=[ast.Call(name="ifNull", args=[field, ast.Constant(value="")])])
        )
        for sentinel in UNATTRIBUTED_SESSION_VALUES.get(runner.breakdown, ()):
            conditions.append(
                ast.CompareOperation(left=field, op=ast.CompareOperationOp.NotEq, right=ast.Constant(value=sentinel))
            )
    return conditions


def _breakdown_expr(runner: "AttributionQueryRunnerBase") -> ast.Expr:
    column = _field(BREAKDOWN_COLUMNS[runner.breakdown])
    if runner.breakdown == MarketingAnalyticsAttributionBreakdown.CHANNEL:
        return runner._non_empty_or(column, UNKNOWN_CHANNEL)
    if runner.breakdown == MarketingAnalyticsAttributionBreakdown.SOURCE:
        return runner._normalized_source_expr(column)
    if runner.breakdown == MarketingAnalyticsAttributionBreakdown.CAMPAIGN:
        return runner._normalized_campaign_expr(column, source_field=_field("utm_source"))
    return ast.Call(name="toString", args=[ast.Call(name="ifNull", args=[column, ast.Constant(value="")])])


def build_reach(runner: "AttributionQueryRunnerBase", date_range: QueryDateRange) -> Optional[ast.SelectQuery]:
    job_ids = _ensure(runner, date_range)
    if job_ids is None:
        return None
    read = window(runner, date_range)
    # Collapsed per session first, for the reason in `build_person_arrays`. `uniq` already keeps a
    # duplicated session from counting its person twice, but two rows can carry different dimensions,
    # which puts one visitor in two breakdown rows.
    per_session = ast.SelectQuery(
        select=[
            ast.Alias(alias="person_id", expr=_field("person_id")),
            ast.Alias(
                alias="breakdown_value",
                expr=ast.Call(name="argMax", args=[_breakdown_expr(runner), _field("computed_at")]),
            ),
        ],
        select_from=ast.JoinExpr(table=ast.Field(chain=["posthog", TABLE])),
        where=ast.And(exprs=[*_scope(job_ids, read), *_exclusions(runner)]),
        group_by=[_field("session_id"), _field("person_id")],
    )
    return ast.SelectQuery(
        select=[
            ast.Field(chain=["s", "breakdown_value"]),
            ast.Alias(alias="visitors", expr=ast.Call(name="uniq", args=[ast.Field(chain=["s", "person_id"])])),
        ],
        select_from=ast.JoinExpr(table=per_session, alias="s"),
        group_by=[ast.Field(chain=["s", "breakdown_value"])],
    )


def _conversions_per_person(runner: "AttributionQueryRunnerBase", date_range: QueryDateRange) -> ast.SelectQuery:
    """Conversions per converting person, straight off events. Conversions are events, not sessions,
    so this side stays on `events`; what the precompute replaces is the touchpoint side."""
    conversions: ast.Expr = ast.Call(
        name="groupArray",
        args=[
            ast.Tuple(
                exprs=[
                    ast.Call(name="toUnixTimestamp", args=[ast.Field(chain=["events", "timestamp"])]),
                    runner._conversion_value_expr(),
                ]
            )
        ],
    )
    if not runner.allows_multiple_conversions_per_visitor:
        conversions = ast.Call(
            name="arraySlice",
            args=[ast.Call(name="arraySort", args=[conversions]), ast.Constant(value=1), ast.Constant(value=1)],
        )

    def bound(fn: str) -> ast.Expr:
        return ast.Call(
            name=fn, args=[ast.Call(name="toUnixTimestamp", args=[ast.Field(chain=["events", "timestamp"])])]
        )

    return ast.SelectQuery(
        select=[
            ast.Alias(alias="conv_person_id", expr=ast.Field(chain=["events", "person_id"])),
            ast.Alias(alias="conversions", expr=conversions),
            ast.Alias(alias="first_conversion", expr=bound("min")),
            ast.Alias(alias="last_conversion", expr=bound("max")),
        ],
        select_from=ast.JoinExpr(table=ast.Field(chain=["events"])),
        where=ast.And(
            exprs=[
                runner.conversion_condition,
                *runner._get_where_conditions(date_range, date_field="events.timestamp"),
            ]
        ),
        group_by=[ast.Field(chain=["events", "person_id"])],
    )


def build_person_arrays(runner: "AttributionQueryRunnerBase", date_range: QueryDateRange) -> Optional[ast.SelectQuery]:
    """One row per converting person: its conversions, plus its touchpoints read from the precompute.

    The touchpoint side joins the session rows to the converters, so it never touches `events` and
    never resolves the channel.
    """
    job_ids = _ensure(runner, date_range)
    if job_ids is None:
        return None
    read = window(runner, date_range)

    conv = _conversions_per_person(runner, date_range)
    session_start = ast.Call(name="toUnixTimestamp", args=[_field("start_timestamp")])
    # A touchpoint outside [first conversion - window, last conversion] cannot be credited by any of
    # this person's conversions. In single-conversion mode only the first one is kept, so nothing
    # after it is creditable either.
    upper = "last_conversion" if runner.allows_multiple_conversions_per_visitor else "first_conversion"

    # One row per session before the array is built. A session can hold rows under two job_ids: its
    # stored start is the earliest event seen so far, and a later event that predates it moves the
    # start, which files the session under a different chunk while the first chunk's row survives.
    # Both job_ids are in the read set, so without this collapse one session becomes two touchpoints
    # and over-credits the person. The sibling conversion precompute deduplicates for the same reason.
    per_session = ast.SelectQuery(
        select=[
            ast.Alias(alias="person_id", expr=ast.Field(chain=["conv", "conv_person_id"])),
            ast.Alias(alias="session_ts", expr=ast.Call(name="argMax", args=[session_start, _field("computed_at")])),
            ast.Alias(
                alias="session_dim",
                expr=ast.Call(name="argMax", args=[_breakdown_expr(runner), _field("computed_at")]),
            ),
            ast.Alias(
                alias="first_conversion",
                expr=ast.Call(name="any", args=[ast.Field(chain=["conv", "first_conversion"])]),
            ),
            ast.Alias(alias="upper_bound", expr=ast.Call(name="any", args=[ast.Field(chain=["conv", upper])])),
        ],
        select_from=ast.JoinExpr(
            table=ast.Field(chain=["posthog", TABLE]),
            next_join=ast.JoinExpr(
                join_type="INNER JOIN",
                table=_conversions_per_person(runner, date_range),
                alias="conv",
                constraint=ast.JoinConstraint(
                    expr=ast.CompareOperation(
                        left=_field("person_id"),
                        op=ast.CompareOperationOp.Eq,
                        right=ast.Field(chain=["conv", "conv_person_id"]),
                    ),
                    constraint_type="ON",
                ),
            ),
        ),
        where=ast.And(exprs=[*_scope(job_ids, read), *_exclusions(runner)]),
        group_by=[ast.Field(chain=["conv", "conv_person_id"]), _field("session_id")],
    )

    # Creditability is judged on the collapsed start, so a superseded row cannot decide it.
    touchpoints = ast.SelectQuery(
        select=[
            ast.Alias(alias="person_id", expr=ast.Field(chain=["d", "person_id"])),
            ast.Alias(
                alias="touchpoints",
                expr=ast.Call(
                    name="arraySlice",
                    args=[
                        ast.Call(
                            name="arraySort",
                            args=[
                                ast.Call(
                                    name="groupUniqArray",
                                    args=[
                                        ast.Tuple(
                                            exprs=[
                                                ast.Field(chain=["d", "session_ts"]),
                                                ast.Field(chain=["d", "session_dim"]),
                                            ]
                                        )
                                    ],
                                )
                            ],
                        ),
                        ast.Constant(value=-MAX_TOUCHPOINTS_PER_PERSON),
                    ],
                ),
            ),
        ],
        select_from=ast.JoinExpr(table=per_session, alias="d"),
        where=ast.And(
            exprs=[
                ast.CompareOperation(
                    left=ast.Field(chain=["d", "session_ts"]),
                    op=ast.CompareOperationOp.GtEq,
                    right=ast.ArithmeticOperation(
                        left=ast.Field(chain=["d", "first_conversion"]),
                        op=ast.ArithmeticOperationOp.Sub,
                        right=ast.Constant(value=runner.attribution_window_seconds),
                    ),
                ),
                ast.CompareOperation(
                    left=ast.Field(chain=["d", "session_ts"]),
                    op=ast.CompareOperationOp.LtEq,
                    right=ast.Field(chain=["d", "upper_bound"]),
                ),
            ]
        ),
        group_by=[ast.Field(chain=["d", "person_id"])],
    )

    return ast.SelectQuery(
        select=[
            ast.Alias(alias="person_id", expr=ast.Field(chain=["c", "conv_person_id"])),
            ast.Field(chain=["c", "conversions"]),
            ast.Alias(alias="touchpoints", expr=ast.Field(chain=["t", "touchpoints"])),
        ],
        select_from=ast.JoinExpr(
            table=conv,
            alias="c",
            next_join=ast.JoinExpr(
                join_type="LEFT JOIN",
                table=touchpoints,
                alias="t",
                constraint=ast.JoinConstraint(
                    expr=ast.CompareOperation(
                        left=ast.Field(chain=["c", "conv_person_id"]),
                        op=ast.CompareOperationOp.Eq,
                        right=ast.Field(chain=["t", "person_id"]),
                    ),
                    constraint_type="ON",
                ),
            ),
        ),
        where=ast.CompareOperation(
            left=ast.Call(name="length", args=[ast.Field(chain=["c", "conversions"])]),
            op=ast.CompareOperationOp.Gt,
            right=ast.Constant(value=0),
        ),
    )
