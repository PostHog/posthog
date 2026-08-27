"""Pre-aggregated source for the attribution table's `influenced_reach` CTE.

Reach is the denominator: unique visitors per dimension, converters or not. It is the one CTE not
restricted to converters, so it joins every pageview in the window to `sessions`, and that join is
what runs the query out of memory on a high-volume team. Being a plain rollup, it can come from a
pre-aggregated table instead.

The reach rows are FULL OUTER JOINed to the credit rows on `breakdown_value`, so both sides must
render a dimension to the same string or it splits into a visitors-only row and a credit-only row.
That is what `_preagg_breakdown_expr` and `_preagg_exclusion_conditions` below mirror.

Divergences this does NOT gate, in rough order of impact:

- `$screen`-only sessions count as visitors here and not on the credit side, so a team with app
  traffic gets an inflated denominator. The table has no column to filter them out.
- `gad_source` other than `'1'` is Paid on the credit side and Organic here, splitting a CHANNEL row.
  Inherited from web analytics, which never meets both classifications in one result set.
- Person IDs are frozen at insert time, while the credit side applies overrides at query time.
- Window edges are session-start here and event-time on the credit side.
"""

from datetime import UTC, datetime, timedelta
from typing import TYPE_CHECKING, Optional

import structlog

from posthog.schema import MarketingAnalyticsAttributionBreakdown, SessionsV2JoinMode

from posthog.hogql import ast
from posthog.hogql.database.schema.channel_type import create_preaggregated_channel_type_expr
from posthog.hogql.transforms.preaggregated_table_transformation import is_integer_timezone

from posthog.hogql_queries.utils.query_date_range import QueryDateRange

from products.access_control.backend.facade.api import team_has_property_access_rules
from products.analytics_platform.backend.lazy_computation.lazy_computation_executor import (
    LazyComputationTable,
    parse_ttl_schedule,
)
from products.analytics_platform.backend.lazy_computation.web_dimensional_shared import (
    BOUNCES_INSERT_TEMPLATE,
    DIMENSIONAL_TTL_SECONDS,
    base_placeholders,
)

from .constants import UNKNOWN_CHANNEL
from .marketing_lazy_precompute import handle_stale_served, marketing_ensure_precomputed
from .metrics import ATTRIBUTION_REACH_PRECOMPUTE_FALLBACK_COUNTER, ATTRIBUTION_REACH_PRECOMPUTE_SUCCESS_COUNTER

if TYPE_CHECKING:
    from .attribution_base import AttributionQueryRunnerBase

logger = structlog.get_logger(__name__)

REACH_PRECOMPUTE_TABLE = "web_bounces_dimensional_preaggregated"

# Matches web analytics' ceiling for these tables.
REACH_MAX_WINDOW_DAYS = 90

# The framework merges a fully-missing range into one INSERT, so without a cap a cold ensure scans
# the whole span at once.
REACH_PRECOMPUTE_CHUNK_DAYS = 1

# Column on the pre-aggregated table backing each breakdown. CHANNEL is absent on purpose: it has no
# column and is computed from several of the others.
BREAKDOWN_PREAGG_COLUMNS: dict[MarketingAnalyticsAttributionBreakdown, str] = {
    MarketingAnalyticsAttributionBreakdown.SOURCE: "utm_source",
    MarketingAnalyticsAttributionBreakdown.CAMPAIGN: "utm_campaign",
    MarketingAnalyticsAttributionBreakdown.MEDIUM: "utm_medium",
    MarketingAnalyticsAttributionBreakdown.CONTENT: "utm_content",
    MarketingAnalyticsAttributionBreakdown.TERM: "utm_term",
    MarketingAnalyticsAttributionBreakdown.REFERRING_DOMAIN: "referring_domain",
    MarketingAnalyticsAttributionBreakdown.LANDING_PAGE: "entry_pathname",
}


def _table_field(name: str) -> ast.Expr:
    """Unqualified column reference.

    `FROM posthog.<table>` resolves to the alias `posthog__<table>`, so a reference qualified with the
    bare table name would not resolve. Matching `_build_distinct_preagg_rows`, and required anyway by
    `create_preaggregated_channel_type_expr`, which emits unqualified fields.
    """
    return ast.Field(chain=[name])


def reach_precompute_ineligible_reason(
    runner: "AttributionQueryRunnerBase", date_range: Optional[QueryDateRange] = None
) -> Optional[str]:
    """Why this query cannot read reach from the pre-aggregated table, or None if it can.

    Returns a reason string rather than a bool so the caller can label the fallback counter with it.
    The reasons carry very different weight, permanent against transient, and an unlabeled counter
    would blur them together.
    """
    modifiers = runner.modifiers
    if modifiers is not None and modifiers.customChannelTypeRules:
        # Refused on every breakdown, not just CHANNEL: the rules also feed `excludeDirectTraffic`,
        # which compares against the classifier's output whatever the breakdown is.
        return "custom_channel_rules"

    if not is_integer_timezone(runner.team.timezone):
        # `period_bucket` is an hourly UTC bucket, so a half-hour-offset team's midnight lands
        # mid-bucket and moves up to an hour of sessions across each edge.
        return "non_integer_timezone"

    # Raw modifiers: resolution defaults `sessionsV2JoinMode` to UUID for every query, so the
    # resolved value would refuse everything. The custom-rules check above wants the resolved one.
    query_modifiers = runner.query.modifiers
    if query_modifiers is not None and query_modifiers.sessionsV2JoinMode == SessionsV2JoinMode.UUID:
        # Changes what one session is on the credit side; the rows keep what they were built with.
        return "sessions_v2_uuid_mode"

    if team_has_property_access_rules(team_id=runner.team.id):
        # The rows are userless and shared, so they cannot honor per-user property restrictions.
        return "property_access_controlled"

    if date_range is not None and _window_days(runner, date_range) > REACH_MAX_WINDOW_DAYS:
        # Width, not age: bounds what one request can materialize inline. Includes the lookback, so
        # a team on the maximum attribution window never qualifies.
        return "window_over_max"

    return None


def _window_days(runner: "AttributionQueryRunnerBase", date_range: QueryDateRange) -> int:
    window_start, window_end = _reach_window(runner, date_range)
    return (window_end - window_start).days


def _reach_window(runner: "AttributionQueryRunnerBase", date_range: QueryDateRange) -> tuple[datetime, datetime]:
    """The bounds this read asks the pre-aggregated table for, in UTC.

    Same span as `_lookback_date_conditions`: the display range extended back by the attribution
    window, so a visitor who arrived before the range still counts toward the denominator of a
    conversion inside it. Reach and credit must agree here or rates can exceed 100%.

    Converted to UTC *before* subtracting, for two reasons. Subtracting from a team-local aware
    datetime is wall-clock arithmetic, so a lookback crossing a DST transition would land an hour
    away from the credit side's `toDateTime(...) - toIntervalSecond(...)`, which ClickHouse
    evaluates in absolute seconds. And the job grid reinterprets the datetime's date fields as UTC,
    so a team-local bound would leave the day's final |offset| hours with no job while this read
    still asks for them.
    """
    window_start = date_range.date_from().astimezone(UTC) - timedelta(seconds=runner.attribution_window_seconds)
    return window_start, date_range.date_to().astimezone(UTC)


def build_reach_from_precompute(
    runner: "AttributionQueryRunnerBase", date_range: QueryDateRange
) -> Optional[ast.SelectQuery]:
    """Reach read from the pre-aggregated table, or None when the caller should use the live scan.

    Returns None rather than raising so the caller keeps one fallback path for "not eligible", "not
    warmed yet" and "blew up".
    """
    ineligible = reach_precompute_ineligible_reason(runner, date_range)
    if ineligible is not None:
        ATTRIBUTION_REACH_PRECOMPUTE_FALLBACK_COUNTER.labels(reason=ineligible).inc()
        logger.info("attribution_reach_precompute", outcome=f"fallback_{ineligible}", team_id=runner.team.pk)
        return None

    window_start, window_end = _reach_window(runner, date_range)

    try:
        # The marketing wrapper, not web analytics' raw ensure, so this read gets serve-stale
        # instead of blocking the request thread on a rebuild.
        with runner.timings.measure("attribution_reach_precompute_ensure"):
            result = marketing_ensure_precomputed(
                team=runner.team,
                insert_query=BOUNCES_INSERT_TEMPLATE,
                time_range_start=window_start,
                time_range_end=window_end,
                ttl_seconds=parse_ttl_schedule(
                    DIMENSIONAL_TTL_SECONDS,
                    runner.team.timezone,
                    max_window_days=REACH_PRECOMPUTE_CHUNK_DAYS,
                ),
                table=LazyComputationTable.WEB_BOUNCES_DIMENSIONAL_PREAGGREGATED,
                placeholders=base_placeholders(),
                query_type="web_bounces_dimensional_insert",
            )
    except Exception:
        ATTRIBUTION_REACH_PRECOMPUTE_FALLBACK_COUNTER.labels(reason="exception").inc()
        logger.exception("attribution_reach_precompute_failed", team_id=runner.team.pk)
        return None

    if result.stale:
        # Before the guards: a result can be stale and not ready at once, and handling it after
        # would fall back without enqueueing the revalidation.
        handle_stale_served(team=runner.team, query=runner.query)

    if not result.job_ids:
        # `ready=True` with no jobs is reachable, and an empty `job_id IN ()` is a syntax error
        # raised outside the try above, so it would 500 the table instead of falling back.
        ATTRIBUTION_REACH_PRECOMPUTE_FALLBACK_COUNTER.labels(reason="no_jobs").inc()
        logger.info("attribution_reach_precompute", outcome="fallback_no_jobs", team_id=runner.team.pk)
        return None

    if not result.ready:
        reason = "not_ready_oom" if result.memory_exceeded else "not_ready"
        ATTRIBUTION_REACH_PRECOMPUTE_FALLBACK_COUNTER.labels(reason=reason).inc()
        logger.info(
            "attribution_reach_precompute",
            outcome=f"fallback_{reason}",
            team_id=runner.team.pk,
            errors=result.errors or None,
        )
        return None

    runner._reach_precompute_used = True
    ATTRIBUTION_REACH_PRECOMPUTE_SUCCESS_COUNTER.inc()
    logger.info("attribution_reach_precompute", outcome="served", team_id=runner.team.pk)
    breakdown_expr = _preagg_breakdown_expr(runner)
    where: list[ast.Expr] = [
        ast.Call(
            name="in",
            args=[
                _table_field("job_id"),
                ast.Tuple(exprs=[ast.Constant(value=str(jid)) for jid in result.job_ids]),
            ],
        ),
        ast.CompareOperation(
            left=_table_field("period_bucket"),
            op=ast.CompareOperationOp.GtEq,
            right=ast.Constant(value=window_start),
        ),
        ast.CompareOperation(
            left=_table_field("period_bucket"),
            op=ast.CompareOperationOp.LtEq,
            right=ast.Constant(value=window_end),
        ),
        *_preagg_exclusion_conditions(runner),
    ]

    return ast.SelectQuery(
        select=[
            ast.Alias(alias="breakdown_value", expr=breakdown_expr),
            # uniqMerge, not a count: `host` and `device_type` are event-level, so one session can
            # span several rows. Nothing here may group by those two columns.
            ast.Alias(
                alias="visitors",
                expr=ast.Call(name="uniqMerge", args=[_table_field("persons_uniq_state")]),
            ),
        ],
        select_from=ast.JoinExpr(table=ast.Field(chain=["posthog", REACH_PRECOMPUTE_TABLE])),
        where=ast.And(exprs=where),
        group_by=[ast.Field(chain=["breakdown_value"])],
    )


def _raw_breakdown_field(runner: "AttributionQueryRunnerBase") -> ast.Expr:
    """The unformatted column backing the current breakdown, for emptiness tests."""
    if runner.breakdown == MarketingAnalyticsAttributionBreakdown.CHANNEL:
        return create_preaggregated_channel_type_expr(timings=runner.timings)
    return _table_field(BREAKDOWN_PREAGG_COLUMNS[runner.breakdown])


def _preagg_breakdown_expr(runner: "AttributionQueryRunnerBase") -> ast.Expr:
    """Mirror of `AttributionQueryRunnerBase._breakdown_expr` against the pre-aggregated columns.

    The two must produce identical strings for the same underlying traffic. See the module docstring
    on the FULL OUTER JOIN.
    """
    breakdown = runner.breakdown

    if breakdown == MarketingAnalyticsAttributionBreakdown.CHANNEL:
        return runner._non_empty_or(create_preaggregated_channel_type_expr(timings=runner.timings), UNKNOWN_CHANNEL)

    field = _table_field(BREAKDOWN_PREAGG_COLUMNS[breakdown])

    if breakdown == MarketingAnalyticsAttributionBreakdown.SOURCE:
        return runner._normalized_source_expr(field)
    if breakdown == MarketingAnalyticsAttributionBreakdown.CAMPAIGN:
        return runner._normalized_campaign_expr(field, source_field=_table_field("utm_source"))
    return ast.Call(name="toString", args=[ast.Call(name="ifNull", args=[field, ast.Constant(value="")])])


def _preagg_exclusion_conditions(runner: "AttributionQueryRunnerBase") -> list[ast.Expr]:
    """Mirror of the exclusion half of `_touchpoint_condition`.

    The live path also drops pageviews with no resolvable session; here every row *is* a session, so
    that check has no counterpart.
    """
    conditions: list[ast.Expr] = []

    if runner.query.excludeDirectTraffic:
        conditions.append(
            ast.CompareOperation(
                left=create_preaggregated_channel_type_expr(timings=runner.timings),
                op=ast.CompareOperationOp.NotEq,
                right=ast.Constant(value="Direct"),
            )
        )

    if runner.query.excludeUnattributed:
        from .session_breakdown_base import UNATTRIBUTED_SESSION_VALUES  # noqa: PLC0415 (import cycle)

        field = _raw_breakdown_field(runner)
        conditions.append(
            ast.Call(name="notEmpty", args=[ast.Call(name="ifNull", args=[field, ast.Constant(value="")])])
        )
        for sentinel in UNATTRIBUTED_SESSION_VALUES.get(runner.breakdown, ()):
            conditions.append(
                ast.CompareOperation(
                    left=field,
                    op=ast.CompareOperationOp.NotEq,
                    right=ast.Constant(value=sentinel),
                )
            )

    return conditions


__all__ = [
    "build_reach_from_precompute",
]
