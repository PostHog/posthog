"""Read cached session dimensions with the same event identity resolution as live attribution.

Stored person IDs can outlive a merge, so only session dimensions come from the cache.
"""

from datetime import UTC, datetime, timedelta
from typing import TYPE_CHECKING, Optional

import structlog

from posthog.schema import MarketingAnalyticsAttributionBreakdown, SessionTableVersion

from posthog.hogql import ast
from posthog.hogql.modifiers import create_default_modifiers_for_team
from posthog.hogql.parser import parse_select
from posthog.hogql.transforms.preaggregated_table_transformation import is_integer_timezone

from posthog.clickhouse.query_tagging import get_query_tag_value
from posthog.dataclasses import frozen
from posthog.hogql_queries.utils.query_date_range import QueryDateRange

from products.access_control.backend.facade.api import team_has_property_access_rules
from products.analytics_platform.backend.lazy_computation.stale_policy import resolve_stale_while_revalidate_seconds
from products.marketing_analytics.backend.hogql_queries.marketing_sessions_precompute import (
    SESSION_READ_REACHBACK_DAYS,
    ensure_marketing_sessions_precomputed,
    precompute_window_start,
)

from .attribution_base import MAX_CONVERSIONS_PER_PERSON, MAX_TOUCHPOINTS_PER_PERSON, PERSON_CONVERSION_COUNT
from .attribution_session_dimensions import session_dimensions
from .constants import UNKNOWN_CHANNEL
from .marketing_lazy_precompute import (
    BACKGROUND_WARMING_TRIGGERS,
    PRECOMPUTE_ONLY_MAX_STALE_SECONDS,
    REVALIDATION_TRIGGER,
    handle_stale_served,
)
from .session_breakdown_base import UNATTRIBUTED_SESSION_VALUES

if TYPE_CHECKING:
    from posthog.schema import HogQLQueryModifiers

    from .attribution_base import AttributionQueryRunnerBase

logger = structlog.get_logger(__name__)

_SESSIONS_CTE = "resolved_cached_sessions"
_CONVERSIONS_CTE = "cached_session_conversions"

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


def _session_table_version(modifiers: "HogQLQueryModifiers") -> SessionTableVersion:
    version = modifiers.sessionTableVersion
    return SessionTableVersion.V2 if version is None or version == SessionTableVersion.AUTO else version


def _session_modifiers_reason(runner: "AttributionQueryRunnerBase") -> Optional[str]:
    writer_modifiers = create_default_modifiers_for_team(runner.team)
    modifiers = runner.modifiers or writer_modifiers
    if (modifiers.customChannelTypeRules or []) != (writer_modifiers.customChannelTypeRules or []):
        return "custom_channel_rules_mismatch"
    if modifiers.convertToProjectTimezone is False:
        return "project_timezone_disabled"
    version = _session_table_version(modifiers)
    if version == SessionTableVersion.V1 or version != _session_table_version(writer_modifiers):
        return "session_table_version_mismatch"
    if version == SessionTableVersion.V2 and modifiers.sessionsV2JoinMode != writer_modifiers.sessionsV2JoinMode:
        return "session_join_mode_mismatch"
    return None


def ineligible_reason(runner: "AttributionQueryRunnerBase", date_range: QueryDateRange) -> Optional[str]:
    """Why this query cannot read from the precompute, or None if it can.

    A reason string rather than a bool, so the caller can label the fallback counter: these carry very
    different weight, and an unlabeled counter would blur permanent and transient apart.
    """
    if reason := _session_modifiers_reason(runner):
        return reason

    if not is_integer_timezone(runner.team.timezone):
        # `period_bucket` is an hourly UTC bucket, so a half-hour-offset team's midnight lands
        # mid-bucket and moves sessions across each edge.
        return "non_integer_timezone"

    # Live date filters omit the UTC offset, so repeated local hours can resolve to another instant.
    if any(
        bound.replace(fold=0).utcoffset() != bound.replace(fold=1).utcoffset()
        for bound in (date_range.date_from(), date_range.date_to())
    ):
        return "ambiguous_date_boundary"

    if team_has_property_access_rules(team_id=runner.team.id):
        # The rows are userless and shared, so they cannot honor per-user property restrictions.
        return "property_access_controlled"

    if runner._test_account_conditions():
        # Shared dimensions include test traffic; use the live path to apply the full filter semantics.
        return "test_account_filters"

    read = window(runner, date_range)
    if read.start - timedelta(days=SESSION_READ_REACHBACK_DAYS) < precompute_window_start(runner.team, read.end):
        return "window_over_max"

    return None


@frozen
class ReadWindow:
    """The span of session activity a query reads: its display range extended back by the attribution
    window, in UTC. Bounds include whole seconds to match conversion date filters."""

    start: datetime
    end: datetime


def window(runner: "AttributionQueryRunnerBase", date_range: QueryDateRange) -> ReadWindow:
    """Converted before subtracting: subtracting from a team-local aware datetime is wall-clock
    arithmetic, which lands an hour away from the credit side across a DST transition.
    """
    return ReadWindow(
        start=date_range.date_from().astimezone(UTC).replace(microsecond=0)
        - timedelta(seconds=runner.attribution_window_seconds),
        end=date_range.date_to().astimezone(UTC).replace(microsecond=999999),
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
        ensure_start = read.start - timedelta(days=SESSION_READ_REACHBACK_DAYS)
        revalidating = get_query_tag_value("trigger") == REVALIDATION_TRIGGER
        grace = resolve_stale_while_revalidate_seconds(PRECOMPUTE_ONLY_MAX_STALE_SECONDS, BACKGROUND_WARMING_TRIGGERS)
        # Only the dedicated revalidation task may rebuild; cold user reads keep the live fallback.
        result = ensure_marketing_sessions_precomputed(
            runner.team,
            ensure_start,
            read.end,
            run_inserts=revalidating,
            stale_while_revalidate_seconds=grace,
        )
        if not result.job_ids or not result.ready:
            return None
    except Exception:
        logger.exception("attribution_sessions_precompute_failed", team_id=runner.team.pk)
        return None
    if result.stale:
        handle_stale_served(team=runner.team, query=runner.query)
    return [str(j) for j in result.job_ids]


def _read_sessions(dimensions: ast.SelectQuery, start: datetime, end: datetime) -> ast.SelectQuery:
    query = parse_select(
        """
        WITH dimensions AS (SELECT * FROM {dimensions}), identities AS (
            SELECT events.$session_id_uuid AS session_id_v7, events.person_id AS person_id,
                min(events.timestamp) AS min_event_timestamp,
                max(events.timestamp) AS max_event_timestamp,
                count() AS pageview_count
            FROM events
            WHERE events.event = '$pageview'
                AND events.timestamp >= {start} AND events.timestamp <= {end}
            GROUP BY session_id_v7, person_id
        )
        SELECT i.session_id_v7, i.person_id, i.min_event_timestamp, i.max_event_timestamp, i.pageview_count,
            d.latest.1 AS period_bucket, d.latest.2 AS start_timestamp, d.latest.3 AS channel_type,
            d.latest.4 AS utm_source, d.latest.5 AS utm_medium, d.latest.6 AS utm_campaign,
            d.latest.7 AS utm_term, d.latest.8 AS utm_content, d.latest.9 AS referring_domain,
            d.latest.10 AS entry_pathname, d.computed_at
        FROM identities AS i
        INNER JOIN dimensions AS d ON i.session_id_v7 = d.session_id_v7
        """,
        placeholders={
            "dimensions": dimensions,
            "start": ast.Constant(value=start),
            "end": ast.Constant(value=end),
        },
    )
    assert isinstance(query, ast.SelectQuery)
    return query


def _scope(read: ReadWindow) -> list[ast.Expr]:
    """Scope to the window by event time; cached dimensions already select the ready job set.

    The live path keeps a session whose events fall in the window and then reports its start as the
    touchpoint time, so a session that opened before the window still counts. Bounding by
    `start_timestamp` dropped exactly those, which moved first-touch credit and shrank the reach
    denominator.
    """
    return [
        ast.CompareOperation(
            left=_field("max_event_timestamp"), op=ast.CompareOperationOp.GtEq, right=ast.Constant(value=read.start)
        ),
        ast.CompareOperation(
            left=_field("min_event_timestamp"), op=ast.CompareOperationOp.LtEq, right=ast.Constant(value=read.end)
        ),
    ]


_EXCLUDED_CHANNEL = "excl_channel_type"
_EXCLUDED_BREAKDOWN = "excl_breakdown"


def _exclusion_columns(runner: "AttributionQueryRunnerBase") -> list[ast.Expr]:
    """The columns the exclusions read, collapsed per session by `computed_at`.

    A session can hold rows under two job_ids, and a re-materialized row can carry different
    dimensions. Filtering the raw rows would drop the current version and leave the superseded one
    standing, so the exclusions have to judge what the collapse decided, not what any row says.
    """
    columns: list[ast.Expr] = []
    if runner.query.excludeDirectTraffic:
        columns.append(
            ast.Alias(
                alias=_EXCLUDED_CHANNEL,
                expr=ast.Call(name="argMax", args=[_field("channel_type"), _field("computed_at")]),
            )
        )
    if runner.query.excludeUnattributed:
        columns.append(
            ast.Alias(
                alias=_EXCLUDED_BREAKDOWN,
                expr=ast.Call(name="argMax", args=[_field(BREAKDOWN_COLUMNS[runner.breakdown]), _field("computed_at")]),
            )
        )
    return columns


def _exclusions(runner: "AttributionQueryRunnerBase", table_alias: Optional[str] = None) -> list[ast.Expr]:
    """Mirror of the exclusion half of `_touchpoint_condition`, against the collapsed columns."""

    def resolved(alias: str) -> ast.Field:
        return ast.Field(chain=[table_alias, alias] if table_alias else [alias])

    conditions: list[ast.Expr] = []
    if runner.query.excludeDirectTraffic:
        conditions.append(
            ast.CompareOperation(
                left=resolved(_EXCLUDED_CHANNEL),
                op=ast.CompareOperationOp.NotEq,
                right=ast.Constant(value="Direct"),
            )
        )
    if runner.query.excludeUnattributed:
        # Judged on the raw column rather than the display expression, so a friendly fallback label
        # cannot smuggle an empty value back in.
        field = resolved(_EXCLUDED_BREAKDOWN)
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
            *_exclusion_columns(runner),
        ],
        select_from=ast.JoinExpr(table=ast.Field(chain=[_SESSIONS_CTE]), alias="cached_sessions"),
        where=ast.And(exprs=_scope(read)),
        group_by=[_field("session_id_v7"), _field("person_id")],
    )
    exclusions = _exclusions(runner, table_alias="s")
    return ast.SelectQuery(
        select=[
            ast.Field(chain=["s", "breakdown_value"]),
            ast.Alias(alias="visitors", expr=ast.Call(name="uniq", args=[ast.Field(chain=["s", "person_id"])])),
        ],
        select_from=ast.JoinExpr(table=per_session, alias="s"),
        where=ast.And(exprs=exclusions) if exclusions else None,
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
    # Counted before the array is capped: the footer reports "N of M" exactly, so a conversion the cap
    # drops has to show up as unattributed rather than vanish from M.
    conversion_count: ast.Expr = ast.Call(name="count", args=[])
    if not runner.allows_multiple_conversions_per_visitor:
        conversions = ast.Call(
            name="arraySlice",
            args=[ast.Call(name="arraySort", args=[conversions]), ast.Constant(value=1), ast.Constant(value=1)],
        )
        conversion_count = ast.Constant(value=1)
    else:
        # The same ceiling the live path applies. Without it the two downstream ARRAY JOINs multiply
        # without bound, which is the shape this precompute exists to keep out of memory.
        conversions = ast.Call(
            name="arraySlice",
            args=[
                ast.Call(name="arraySort", args=[conversions]),
                ast.Constant(value=-MAX_CONVERSIONS_PER_PERSON),
            ],
        )

    def bound(fn: str) -> ast.Expr:
        return ast.Call(
            name=fn, args=[ast.Call(name="toUnixTimestamp", args=[ast.Field(chain=["events", "timestamp"])])]
        )

    return ast.SelectQuery(
        select=[
            ast.Alias(alias="conv_person_id", expr=ast.Field(chain=["events", "person_id"])),
            ast.Alias(alias="conversions", expr=conversions),
            ast.Alias(alias=PERSON_CONVERSION_COUNT, expr=conversion_count),
            ast.Alias(alias="first_conversion", expr=bound("min")),
            ast.Alias(alias="last_conversion", expr=bound("max")),
        ],
        select_from=ast.JoinExpr(table=ast.Field(chain=["events"])),
        where=ast.And(
            exprs=[
                runner.conversion_condition,
                *runner._event_date_conditions(date_range),
            ]
        ),
        group_by=[ast.Field(chain=["events", "person_id"])],
    )


def session_ctes(runner: "AttributionQueryRunnerBase", date_range: QueryDateRange) -> dict[str, ast.CTE]:
    if not runner.config.sessions_precomputation_enabled:
        return {}
    job_ids = _ensure(runner, date_range)
    if job_ids is None:
        return {}
    read = window(runner, date_range)
    columns = {BREAKDOWN_COLUMNS[runner.breakdown]}
    if runner.breakdown == MarketingAnalyticsAttributionBreakdown.CAMPAIGN:
        columns.add("utm_source")
    if runner.query.excludeDirectTraffic:
        columns.add("channel_type")
    # Reach and credit share the event scan; conversion bounds share the revenue aggregation.
    return {
        _SESSIONS_CTE: ast.CTE(
            name=_SESSIONS_CTE,
            expr=_read_sessions(
                session_dimensions(
                    runner.modifiers or create_default_modifiers_for_team(runner.team),
                    columns,
                    job_ids,
                    read.start,
                    read.end,
                ),
                read.start,
                read.end,
            ),
            cte_type="subquery",
            materialized=True,
        ),
        _CONVERSIONS_CTE: ast.CTE(
            name=_CONVERSIONS_CTE,
            expr=_conversions_per_person(runner, date_range),
            cte_type="subquery",
            materialized=True,
        ),
    }


def build_person_arrays(runner: "AttributionQueryRunnerBase", date_range: QueryDateRange) -> Optional[ast.SelectQuery]:
    """One row per converting person: its conversions, plus its touchpoints read from the precompute.

    Session dimensions stay cached while both touchpoints and conversions resolve identity from events.
    """
    job_ids = _ensure(runner, date_range)
    if job_ids is None:
        return None
    read = window(runner, date_range)

    conv = parse_select("SELECT * FROM cached_session_conversions")
    converters = parse_select(
        "SELECT conv_person_id, first_conversion, last_conversion FROM cached_session_conversions"
    )
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
            *_exclusion_columns(runner),
        ],
        select_from=ast.JoinExpr(
            table=ast.Field(chain=[_SESSIONS_CTE]),
            alias="cached_sessions",
            next_join=ast.JoinExpr(
                join_type="INNER JOIN",
                table=converters,
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
        where=ast.And(exprs=_scope(read)),
        group_by=[ast.Field(chain=["conv", "conv_person_id"]), _field("session_id_v7")],
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
                *_exclusions(runner, table_alias="d"),
            ]
        ),
        group_by=[ast.Field(chain=["d", "person_id"])],
    )

    return ast.SelectQuery(
        select=[
            ast.Alias(alias="person_id", expr=ast.Field(chain=["c", "conv_person_id"])),
            ast.Field(chain=["c", "conversions"]),
            ast.Field(chain=["c", PERSON_CONVERSION_COUNT]),
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
