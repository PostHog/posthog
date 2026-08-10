"""Pre-aggregated source for the attribution table's `influenced_reach` CTE.

Reach is the denominator: unique visitors per dimension, converters or not. It is the one CTE in the
attribution query that is *not* restricted to converters, so it scans every pageview in the
lookback-extended window and joins each to `sessions` — measured, that join is what makes the query
run out of memory on a high-volume team at a 60-day span while the converter-restricted CTEs return
instantly.

Reach is also a plain rollup (`uniq(person_id)` grouped by one dimension, no per-person ordering), so
unlike the credit side it can be served from a pre-aggregated table. `web_bounces_dimensional_preaggregated`
is session-grain with the session's *entry* attribution already resolved, which is exactly the shape
`_build_reach_select` computes the slow way.

Two things this deliberately keeps in lockstep with `AttributionQueryRunnerBase`:

- the display expression per breakdown, including the team's source/campaign normalization. The reach
  rows are FULL OUTER JOINed to the credit rows on `breakdown_value`; if the two sides normalize
  differently, a dimension splits into two rows — one with visitors and no credit, one with credit and
  no visitors.
- the exclusion options, applied before aggregation.

Known divergences, and how each is handled:

- **Custom channel rules.** The pre-aggregated channel type ignores them (they can key on the full URL,
  which no pre-aggregated table stores) while the credit side reads `sessions.$channel_type`, which
  applies them. Gated out.
- **Non-integer timezones.** `period_bucket` is an hourly UTC bucket, so a half-hour-offset team's
  midnight lands mid-bucket. Gated out, same as web analytics does for its own reads.
- **`$screen`-only sessions — NOT gated, and this one is a real known gap.** `BOUNCES_INSERT_TEMPLATE`
  feeds on `$pageview` OR `$screen`, but `_touchpoint_condition` counts only `$pageview`. A mobile
  session that never fires a pageview is therefore a visitor here and not one on the credit side, so a
  team with app traffic gets a denominator inflated by those sessions (they carry no UTMs, so they land
  under Direct) and correspondingly deflated conversion rates. The table cannot express the difference:
  its `pageviews_count_state` counts both event types, so there is no column to filter on. Closing this
  needs either a `$pageview`-only count column on the table or an accepted change to what the live path
  counts as a touchpoint — neither belongs in this change. Until then the flag should stay off for teams
  with meaningful `$screen` volume.
"""

from datetime import timedelta
from typing import TYPE_CHECKING, Optional

import structlog

from posthog.schema import MarketingAnalyticsAttributionBreakdown

from posthog.hogql import ast
from posthog.hogql.database.schema.channel_type import create_preaggregated_channel_type_expr
from posthog.hogql.transforms.preaggregated_table_transformation import is_integer_timezone

from posthog.hogql_queries.utils.query_date_range import QueryDateRange

from products.analytics_platform.backend.lazy_computation.lazy_computation_executor import LazyComputationTable
from products.web_analytics.backend.hogql_queries.web_dimensional_precompute import (
    BOUNCES_INSERT_TEMPLATE,
    DIMENSIONAL_TTL_SECONDS,
    base_placeholders,
)

from .constants import UNKNOWN_CHANNEL
from .marketing_lazy_precompute import marketing_ensure_precomputed
from .metrics import ATTRIBUTION_REACH_PRECOMPUTE_FALLBACK_COUNTER, ATTRIBUTION_REACH_PRECOMPUTE_SUCCESS_COUNTER

if TYPE_CHECKING:
    from .attribution_base import AttributionQueryRunnerBase

logger = structlog.get_logger(__name__)

REACH_PRECOMPUTE_TABLE = "web_bounces_dimensional_preaggregated"

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


def reach_precompute_ineligible_reason(runner: "AttributionQueryRunnerBase") -> Optional[str]:
    """Why this query cannot read reach from the pre-aggregated table, or None if it can.

    Returns a reason string rather than a bool so the caller can label the fallback counter with it —
    these reasons carry very different weight (permanent vs transient) and an unlabeled counter would
    blur them together.
    """
    modifiers = runner.modifiers
    if modifiers is not None and modifiers.customChannelTypeRules:
        # Refused on every breakdown, not just CHANNEL: the rules also feed `excludeDirectTraffic`,
        # which compares against the classifier's output whatever the breakdown is.
        return "custom_channel_rules"

    if not is_integer_timezone(runner.team.timezone):
        # `period_bucket` is an hourly UTC bucket, so a window boundary can only be expressed to the
        # hour. An integer-offset team's midnight lands exactly on a bucket edge and the comparison is
        # exact; a half-hour-offset team's (Asia/Kolkata, Asia/Kathmandu, Australia/Adelaide) lands
        # mid-bucket, silently moving up to an hour of sessions across each edge. Same gate web
        # analytics applies to its own reads of these tables (`NonIntegerTimezone`).
        return "non_integer_timezone"

    return None


def can_use_reach_precompute(runner: "AttributionQueryRunnerBase") -> bool:
    return reach_precompute_ineligible_reason(runner) is None


def build_reach_from_precompute(
    runner: "AttributionQueryRunnerBase", date_range: QueryDateRange
) -> Optional[ast.SelectQuery]:
    """Reach read from the pre-aggregated table, or None when the caller should use the live scan.

    Returns None rather than raising so the caller keeps one fallback path for "not eligible", "not
    warmed yet" and "blew up".
    """
    ineligible = reach_precompute_ineligible_reason(runner)
    if ineligible is not None:
        ATTRIBUTION_REACH_PRECOMPUTE_FALLBACK_COUNTER.labels(reason=ineligible).inc()
        logger.info("attribution_reach_precompute", outcome=f"fallback_{ineligible}", team_id=runner.team.pk)
        return None

    # Same bounds as `_lookback_date_conditions`: the display range extended back by the attribution
    # window, so a visitor who arrived before the range still counts toward the denominator of a
    # conversion inside it. Reach and credit must agree here or rates can exceed 100%.
    window_start = date_range.date_from() - timedelta(seconds=runner.attribution_window_seconds)
    window_end = date_range.date_to()

    try:
        # Goes through the marketing wrapper, not web analytics' own `ensure_web_bounces_dimensional_precomputed`,
        # so this read inherits marketing's serve-stale policy. Calling the raw ensure would block the
        # request thread rebuilding a stale window.
        with runner.timings.measure("attribution_reach_precompute_ensure"):
            result = marketing_ensure_precomputed(
                team=runner.team,
                insert_query=BOUNCES_INSERT_TEMPLATE,
                time_range_start=window_start,
                time_range_end=window_end,
                ttl_seconds=DIMENSIONAL_TTL_SECONDS,
                table=LazyComputationTable.WEB_BOUNCES_DIMENSIONAL_PREAGGREGATED,
                placeholders=base_placeholders(),
                query_type="web_bounces_dimensional_insert",
            )
    except Exception:
        ATTRIBUTION_REACH_PRECOMPUTE_FALLBACK_COUNTER.labels(reason="exception").inc()
        logger.exception("attribution_reach_precompute_failed", team_id=runner.team.pk)
        return None

    if not result.ready:
        ATTRIBUTION_REACH_PRECOMPUTE_FALLBACK_COUNTER.labels(reason="not_ready").inc()
        logger.info("attribution_reach_precompute", outcome="fallback_not_ready", team_id=runner.team.pk)
        return None
    if result.stale:
        runner._precompute_stale = True

    ATTRIBUTION_REACH_PRECOMPUTE_SUCCESS_COUNTER.inc()
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
            # uniqMerge, not a count: `host` and `device_type` are event-level, so one session can be
            # split across several rows. Merging the states collapses it back to one person. This is
            # also why nothing here may group by those two columns.
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

    The two must produce identical strings for the same underlying traffic — see the module docstring
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
        from .attribution_base import UNATTRIBUTED_SESSION_VALUES  # noqa: PLC0415 — avoids an import cycle

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
    "can_use_reach_precompute",
]
