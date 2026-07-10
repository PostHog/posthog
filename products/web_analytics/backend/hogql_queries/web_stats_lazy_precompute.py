import json
import time
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import TYPE_CHECKING, Literal, Optional

import structlog
from prometheus_client import Counter

from posthog.schema import (
    HogQLQueryModifiers,
    WebAnalyticsOrderByDirection,
    WebAnalyticsOrderByFields,
    WebStatsBreakdown,
    WebStatsTableQuery,
)

from posthog.hogql import ast
from posthog.hogql.parser import parse_expr, parse_select

from posthog.clickhouse.query_tagging import Feature, Product, tag_queries

from products.analytics_platform.backend.lazy_computation.lazy_computation_executor import (
    LazyComputationResult,
    LazyComputationTable,
)
from products.web_analytics.backend.hogql_queries.web_analytics_lazy_precompute import (
    LAZY_TTL_SECONDS,
    SESSION_FORWARD_PAD_MINUTES,
    WEB_ANALYTICS_LAZY_PRECOMPUTE_FALLBACK,
    WEB_ANALYTICS_LAZY_PRECOMPUTE_SUCCESS,
    LazyPrecomputeIneligible,
    LazyPrecomputeRunner,
    can_use_lazy_precompute as _can_use_lazy_precompute_shared,
    ceil_utc_day,
    events_session_id_expr,
    floor_utc_day,
    test_account_filter_expr,
    user_filter_expr,
)
from products.web_analytics.backend.hogql_queries.web_lazy_precompute_common import (
    handle_stale_served,
    web_ensure_precomputed,
)

_FAMILY = "web_stats"

if TYPE_CHECKING:
    from products.web_analytics.backend.hogql_queries.stats_table import WebStatsTableQueryRunner

logger = structlog.get_logger(__name__)


WEB_STATS_LAZY_FAILED = Counter(
    "web_stats_lazy_precompute_failed_total",
    "Web stats lazy precompute path failures, by error class",
    ["error_type"],
)

# Breakdowns served by `SimpleBreakdownStrategy` / `ChannelTypeStrategy` that we
# expect to behave well under precompute. UTM/browser/OS/region/city values are
# user-controlled at ingestion so cardinality is not strictly bounded, but in
# practice they sit several orders of magnitude below the per-page breakdowns we
# deliberately route to the raw path (page/path, FRUSTRATION_METRICS).
# The failure mode for a pathological team is a slow precompute INSERT, not an
# incorrect result — sort, pagination and HAVING all run in SQL so the read
# returns exactly the page the user asked for regardless of total distinct
# values. If a team's INSERT becomes a hotspot we can carve them out via the
# rollout gate; we are not adding a defensive SQL-side cardinality cap because
# it would silently truncate results vs. the raw path.
#
# INITIAL_REFERRING_URL is the one high-cardinality URL breakdown we precompute:
# the lazy INSERT runs per daily bucket, which stays tractable where the 28-day
# raw query times out, so precompute is strictly better than the raw fallback.
#
# Tuple/float breakdowns (REGION, CITY, VIEWPORT, TIMEZONE) are supported: the
# breakdown value is JSON-encoded into the `breakdown_value` String column and
# decoded back to its native shape on read.
#
# LANGUAGE is supported but special: the raw query groups by the language prefix
# ("en" from "en-US") and labels each group with its most-common region via
# topK(1). The INSERT stores the full `$browser_language` ("en-US") as the
# breakdown_value; the read derives the prefix + most-common-region deterministically
# via a two-level aggregation (see `_LANGUAGE_READ_SQL_TEMPLATE`). The region label
# is window-dependent, so it must be computed on read, not baked into the per-hour
# INSERT. The raw `topK(1)` picks the region with the most sessions; the precompute
# stores no session-count state, so the read approximates it with `argMax` over
# pageviews — the closest stored signal (the dominant region almost always leads on
# both). Matching session-topK exactly would need a new stored state and is deferred
# since it only changes the displayed region (not any count) in rare ties. Missing
# `$browser_language` is kept (not filtered) to match the raw query's
# `outer_where_breakdown() is None` for LANGUAGE, so the tile total stays consistent
# with the overview.
SUPPORTED_BREAKDOWNS: set[WebStatsBreakdown] = {
    WebStatsBreakdown.INITIAL_CHANNEL_TYPE,
    WebStatsBreakdown.INITIAL_REFERRING_DOMAIN,
    WebStatsBreakdown.INITIAL_REFERRING_URL,
    WebStatsBreakdown.INITIAL_UTM_SOURCE,
    WebStatsBreakdown.INITIAL_UTM_CAMPAIGN,
    WebStatsBreakdown.INITIAL_UTM_MEDIUM,
    WebStatsBreakdown.INITIAL_UTM_TERM,
    WebStatsBreakdown.INITIAL_UTM_CONTENT,
    WebStatsBreakdown.INITIAL_UTM_SOURCE_MEDIUM_CAMPAIGN,
    WebStatsBreakdown.BROWSER,
    WebStatsBreakdown.OS,
    WebStatsBreakdown.VIEWPORT,
    WebStatsBreakdown.DEVICE_TYPE,
    WebStatsBreakdown.COUNTRY,
    WebStatsBreakdown.REGION,
    WebStatsBreakdown.CITY,
    WebStatsBreakdown.TIMEZONE,
    WebStatsBreakdown.LANGUAGE,
    # EXIT_PAGE is a session-scoped path (`session.$end_pathname`) served as a simple
    # breakdown — no bounce-rate join, unlike PAGE/INITIAL_PAGE which route to the
    # paths precompute family. It reads a materialized sessions column, so it carries
    # none of the unmaterialized-property OOM risk that keeps INITIAL_REFERRING_URL
    # out of the eager warmer.
    WebStatsBreakdown.EXIT_PAGE,
}

# Breakdowns whose value is a tuple — JSON-decoded as a list and converted back
# to a tuple so the response matches the raw query exactly.
TUPLE_BREAKDOWNS: set[WebStatsBreakdown] = {
    WebStatsBreakdown.REGION,
    WebStatsBreakdown.CITY,
    WebStatsBreakdown.VIEWPORT,
}


class BounceRateUnsupported(LazyPrecomputeIneligible):
    pass


class AvgTimeOnPageUnsupported(LazyPrecomputeIneligible):
    pass


class ScrollDepthUnsupported(LazyPrecomputeIneligible):
    pass


class UnsupportedBreakdown(LazyPrecomputeIneligible):
    def __init__(self, breakdown: object):
        self.breakdown = breakdown
        super().__init__(f"breakdown={breakdown!r}")


class UnsupportedOrderBy(LazyPrecomputeIneligible):
    def __init__(self, field: object):
        self.field = field
        super().__init__(f"field={field!r}")


# orderBy fields the lazy read can serve directly. Anything outside this set
# (bounce rate, scroll depth, conversion-rate, …) must fall through to the raw
# path — the precompute table doesn't store those columns.
SUPPORTED_ORDER_BY_FIELDS: set[WebAnalyticsOrderByFields] = {
    WebAnalyticsOrderByFields.VISITORS,
    WebAnalyticsOrderByFields.VIEWS,
}


def _check_stats_eligible(runner: LazyPrecomputeRunner) -> None:
    """Raise a `LazyPrecomputeIneligible` subclass for stats-table-specific
    reasons the lazy path can't serve the query.

    Typed to the shared `LazyPrecomputeRunner` protocol so it satisfies
    `can_use_lazy_precompute`'s `extra_check` parameter (Callable argument
    types are contravariant). The isinstance narrows `query` from the
    `Union[WebOverviewQuery, WebStatsTableQuery]` shape to the stats-table
    fields we actually need."""
    query = runner.query
    assert isinstance(query, WebStatsTableQuery), "_check_stats_eligible called on non-stats runner"

    # Bounce rate / avg time / scroll depth are extra metrics the precompute
    # table does not store. `includeScrollDepth` implicitly turns on bounce rate.
    if query.includeBounceRate:
        raise BounceRateUnsupported()
    if query.includeAvgTimeOnPage:
        raise AvgTimeOnPageUnsupported()
    if query.includeScrollDepth:
        raise ScrollDepthUnsupported()

    if query.breakdownBy not in SUPPORTED_BREAKDOWNS:
        raise UnsupportedBreakdown(query.breakdownBy)

    # Reject orderBy fields we can't compute from the precompute schema. Falling
    # back to visitors would silently change row ordering vs. the raw path; let
    # the raw query handle these instead.
    if query.orderBy:
        field = query.orderBy[0]
        if field not in SUPPORTED_ORDER_BY_FIELDS:
            raise UnsupportedOrderBy(field)


def can_use_lazy_precompute(runner: "WebStatsTableQueryRunner") -> bool:
    """Return True iff the lazy precompute path is eligible for this web stats
    table query — the shared web analytics gate plus stats-specific checks."""
    return _can_use_lazy_precompute_shared(runner, log_prefix="web_stats", extra_check=_check_stats_eligible)


# HogQL template for the precompute INSERT. The lazy_computation framework
# substitutes the listed placeholders (including `time_window_min`/`time_window_max`),
# parses the result, and INSERTs into `web_stats_preaggregated`. The framework
# automatically prepends `team_id`, `job_id` and appends `expires_at` to the SELECT.
#
# Mirrors the web overview precompute: events are grouped into sessions, each
# session is attributed to the hour of `min(session.$start_timestamp)`, and the
# `HAVING` keeps only sessions whose start hour falls in the job window. This
# matches the raw stats query's compare path, which attributes a session's
# metrics by session start. The forward pad (`SESSION_FORWARD_PAD_MINUTES`) lets
# a session starting near the trailing edge of a daily job still see the events
# that spill past midnight, so its pageview count is complete.
INSERT_QUERY_TEMPLATE = """
SELECT
    toStartOfHour(start_timestamp) AS time_window_start,
    {breakdown_by} AS breakdown_by,
    breakdown_value AS breakdown_value,
    uniqState(session_person_id) AS uniq_users_state,
    sumState(assumeNotNull(toInt(filtered_pageview_count))) AS sum_pageviews_state
FROM (
    SELECT
        any(events.person_id) AS session_person_id,
        {events_session_id} AS session_id,
        {breakdown_value} AS breakdown_value,
        min(session.$start_timestamp) AS start_timestamp,
        countIf(or(equals(event, '$pageview'), equals(event, '$screen'))) AS filtered_pageview_count
    FROM events
    WHERE and(
        {events_session_id} IS NOT NULL,
        {event_type_filter},
        timestamp >= {time_window_min},
        timestamp < ({time_window_max} + toIntervalMinute({pad_minutes})),
        {user_filter},
        {test_account_filter}
    )
    GROUP BY session_id, breakdown_value
    HAVING and(
        toStartOfHour(min(session.$start_timestamp)) >= {time_window_min},
        toStartOfHour(min(session.$start_timestamp)) < {time_window_max}
    )
)
GROUP BY time_window_start, breakdown_by, breakdown_value
"""


def _breakdown_value_expr(runner: "WebStatsTableQueryRunner") -> ast.Expr:
    """JSON-encode the breakdown value so tuple/float/null breakdowns round-trip
    through the `breakdown_value String` column. The wrapped expression is what
    `ensure_precomputed` hashes into the cache key, so different breakdowns
    (including path-cleaning / host-prepend variants) get distinct jobs.

    `toJSONString` of a NULL scalar returns NULL, which the non-nullable column
    would coerce to an unparseable empty string — `coalesce(..., 'null')` keeps
    a genuine NULL breakdown as the JSON literal `null` instead."""
    return ast.Call(
        name="coalesce",
        args=[
            ast.Call(name="toJSONString", args=[runner._counts_breakdown_value()]),
            ast.Constant(value="null"),
        ],
    )


def ensure_web_stats_precomputed(
    runner: "WebStatsTableQueryRunner",
    time_range_start: datetime,
    time_range_end: datetime,
) -> LazyComputationResult:
    placeholders: dict[str, ast.Expr] = {
        "breakdown_by": ast.Constant(value=runner.query.breakdownBy.value),
        "breakdown_value": _breakdown_value_expr(runner),
        "events_session_id": events_session_id_expr(runner),
        "event_type_filter": runner.event_type_expr,
        "user_filter": user_filter_expr(runner),
        "test_account_filter": test_account_filter_expr(runner),
        "pad_minutes": ast.Constant(value=SESSION_FORWARD_PAD_MINUTES),
    }

    return web_ensure_precomputed(
        team=runner.team,
        insert_query=INSERT_QUERY_TEMPLATE,
        time_range_start=time_range_start,
        time_range_end=time_range_end,
        ttl_seconds=LAZY_TTL_SECONDS,
        table=LazyComputationTable.WEB_STATS_PREAGGREGATED,
        placeholders=placeholders,
        query_type=f"web_stats_{runner.query.breakdownBy.value}_lazy_insert",
        spill_to_disk=True,  # high-cardinality breakdown GROUP BY; can build a large hash table
    )


# HogQL read template — substituted via `parse_select(..., placeholders=...)` so
# arguments flow through the printer with proper escaping rather than driver-side
# string formatting. Read-your-writes load balancing and shard pruning are
# attached automatically via `WebStatsPreaggregatedTable.top_level_settings`.
#
# `convertToProjectTimezone=False` is forced on the modifiers in
# `execute_read_query` so `time_window_start` (stored UTC) is compared directly
# against the UTC bounds in `{cur_start}` / `{cur_end}` without the printer
# wrapping them in `toTimeZone(..., team_tz)`.
#
# `sum({sort_metric}) OVER ()` runs after `GROUP BY` + `HAVING` and before the
# `ORDER BY` + LIMIT/OFFSET injected via AST mutation in `execute_read_query`,
# so the same denominator the raw query computes with `sum(...) OVER ()` makes
# it onto every paginated row.
_READ_SQL_TEMPLATE = """
SELECT
    breakdown_value,
    uniqMergeIf(uniq_users_state, and(time_window_start >= {cur_start}, time_window_start < {cur_end})) AS visitors,
    uniqMergeIf(uniq_users_state, and(time_window_start >= {prev_start}, time_window_start < {prev_end})) AS previous_visitors,
    sumMergeIf(sum_pageviews_state, and(time_window_start >= {cur_start}, time_window_start < {cur_end})) AS views,
    sumMergeIf(sum_pageviews_state, and(time_window_start >= {prev_start}, time_window_start < {prev_end})) AS previous_views,
    sum({sort_metric}) OVER () AS fill_total
FROM posthog.web_stats_preaggregated
WHERE and(team_id = {team_id}, job_id IN {job_ids}, breakdown_by = {breakdown_by})
GROUP BY breakdown_value
"""


# LANGUAGE read. The INSERT stores the full `$browser_language` ("en-US") as the
# JSON-encoded `breakdown_value`; here we reproduce the raw query's behaviour —
# group by the language prefix ("en") and label each group with its most-common
# region — entirely on read.
#
# `m` computes the prefix-level visitor/view metrics: `uniqMergeIf` over a GROUP BY
# prefix dedups users across regions exactly (no double-count), matching the raw
# query's prefix-level `uniq`. `r` derives the displayed region per prefix via
# `argMax(region, region_views)` — a best-effort *approximation* of the raw query's
# `topK(1)` over the region part, NOT an exact equivalent: `topK(1)` weights by session
# count, which the precompute does not store, so the region *suffix* on a multi-region
# language (e.g. `cs-CZ` vs `cs-`) can differ from raw. Counts are unaffected; see the
# module-level LANGUAGE note above for why this is accepted. The `splitByChar('-', ..., 2)` limit mirrors the raw
# query's exact split signature so the prefix/region split stays identical to the raw
# path for multi-part BCP-47 tags (e.g. `zh-Hans-CN`) regardless of the cluster's
# `splitby_max_substrings_includes_remaining_string` setting. Empty/null languages are
# kept (not filtered), matching the raw query's `outer_where_breakdown() is None` for
# LANGUAGE.
_LANGUAGE_READ_SQL_TEMPLATE = """
SELECT
    concat(m.lang_prefix, '-', r.top_region) AS breakdown_value,
    m.visitors AS visitors,
    m.previous_visitors AS previous_visitors,
    m.views AS views,
    m.previous_views AS previous_views,
    sum({sort_metric}) OVER () AS fill_total
FROM (
    SELECT
        arrayElement(splitByChar('-', JSONExtractString(breakdown_value), 2), 1) AS lang_prefix,
        uniqMergeIf(uniq_users_state, and(time_window_start >= {cur_start}, time_window_start < {cur_end})) AS visitors,
        uniqMergeIf(uniq_users_state, and(time_window_start >= {prev_start}, time_window_start < {prev_end})) AS previous_visitors,
        sumMergeIf(sum_pageviews_state, and(time_window_start >= {cur_start}, time_window_start < {cur_end})) AS views,
        sumMergeIf(sum_pageviews_state, and(time_window_start >= {prev_start}, time_window_start < {prev_end})) AS previous_views
    FROM posthog.web_stats_preaggregated
    WHERE and(team_id = {team_id}, job_id IN {job_ids}, breakdown_by = {breakdown_by})
    GROUP BY lang_prefix
) AS m
LEFT JOIN (
    SELECT lang_prefix, argMax(region, region_views) AS top_region
    FROM (
        SELECT
            arrayElement(splitByChar('-', JSONExtractString(breakdown_value), 2), 1) AS lang_prefix,
            arrayElement(splitByChar('-', JSONExtractString(breakdown_value), 2), 2) AS region,
            sumMergeIf(sum_pageviews_state, and(time_window_start >= {cur_start}, time_window_start < {cur_end})) AS region_views
        FROM posthog.web_stats_preaggregated
        WHERE and(team_id = {team_id}, job_id IN {job_ids}, breakdown_by = {breakdown_by})
        GROUP BY lang_prefix, region
    )
    GROUP BY lang_prefix
) AS r ON m.lang_prefix = r.lang_prefix
"""


@dataclass
class LazyStatsRow:
    """One breakdown value with its decoded value and current/previous metrics.

    `breakdown_value` is decoded back to its native shape (str, tuple, float or
    None). `*_previous` are read from the precompute table unconditionally; the
    response builder discards them when the query has no compare period.

    `fill_total` is the SQL-side `sum({sort_metric}) OVER ()` denominator for
    `ui_fill_fraction`; identical across every row in a single page.
    """

    breakdown_value: object
    visitors_current: int
    visitors_previous: int
    views_current: int
    views_previous: int
    fill_total: int


@dataclass
class LazyStatsResult:
    rows: list[LazyStatsRow]
    has_more: bool
    sort_metric: str


def _resolve_sort_metric(query: WebStatsTableQuery) -> tuple[str, bool]:
    """Pick the SQL column to ORDER BY plus direction. Mirrors what the raw path
    would do; eligibility guarantees the field is `VISITORS` or `VIEWS`."""
    sort_metric = "visitors"
    descending = True
    if query.orderBy:
        field = query.orderBy[0]
        direction = query.orderBy[1]
        if field == WebAnalyticsOrderByFields.VIEWS:
            sort_metric = "views"
        descending = direction != WebAnalyticsOrderByDirection.ASC
    return sort_metric, descending


# Breakdowns where the raw query keeps NULL rows (surfaced as a "(none)" row) instead
# of dropping them — must stay in lockstep with the `outer_where_breakdown() is None`
# cases in `WebStatsTableQueryRunner`. `test_breakdown_having_matches_live_null_handling`
# enforces the parity so the two can't drift.
_KEEP_NULL_BREAKDOWNS = {
    WebStatsBreakdown.COUNTRY,
    WebStatsBreakdown.BROWSER,
    WebStatsBreakdown.OS,
    WebStatsBreakdown.DEVICE_TYPE,
    WebStatsBreakdown.LANGUAGE,
    WebStatsBreakdown.TIMEZONE,
    WebStatsBreakdown.INITIAL_REFERRING_DOMAIN,
    WebStatsBreakdown.INITIAL_UTM_SOURCE,
    WebStatsBreakdown.INITIAL_UTM_CAMPAIGN,
    WebStatsBreakdown.INITIAL_UTM_MEDIUM,
    WebStatsBreakdown.INITIAL_UTM_TERM,
    WebStatsBreakdown.INITIAL_UTM_CONTENT,
}


def _breakdown_having_expr(breakdown_by: WebStatsBreakdown) -> ast.Expr:
    """HAVING-clause equivalent of the raw query's `outer_where_breakdown()` —
    operates on the JSON-encoded `breakdown_value` column produced by the INSERT.

    Index 2 / index 1 here are 1-based JSON array positions (`JSONExtractRaw`
    follows ClickHouse's 1-based indexing). For VIEWPORT specifically, the raw
    query rejects rows whose width/height are null or zero.

    REGION/CITY *look* like they should drop `(country, null)` rows, but the
    raw query's `tupleElement(..., 2) IS NOT NULL` runs on a non-nullable
    `Tuple(String, String, String)` and never matches in practice — so the
    lazy path keeps null subdivisions too, matching what ships from raw.
    """
    if breakdown_by == WebStatsBreakdown.VIEWPORT:
        return parse_expr(
            "JSONExtractRaw(breakdown_value, 1) NOT IN ('null', '0') "
            "AND JSONExtractRaw(breakdown_value, 2) NOT IN ('null', '0')"
        )
    if breakdown_by in _KEEP_NULL_BREAKDOWNS:
        # Mirror the raw query's `outer_where_breakdown() is None` set: missing data is
        # real for these dimensions and surfaces as a "(none)" row, so it must not be
        # dropped. Source of truth is `WebStatsTableQueryRunner.outer_where_breakdown`.
        return ast.Constant(value=True)
    if breakdown_by == WebStatsBreakdown.INITIAL_CHANNEL_TYPE:
        # JSON scalars: 'null' is genuine null, '""' is empty string.
        return parse_expr("breakdown_value NOT IN ('null', '\"\"')")
    # Default: reject only genuine null.
    return parse_expr("breakdown_value != 'null'")


def _decode_breakdown_value(breakdown_by: WebStatsBreakdown, raw: str) -> object:
    """Reverse the INSERT's `toJSONString` wrapping. Tuple breakdowns come back
    as lists and are converted to tuples; timezone comes back as a number and is
    coerced to float to match the raw query's `toFloat` output."""
    if not raw:
        # A non-nullable String column can surface a genuine NULL breakdown as
        # an empty string; treat it as the null breakdown value.
        return None
    if breakdown_by == WebStatsBreakdown.LANGUAGE:
        # The LANGUAGE read emits the final "lang-region" string directly
        # (concat of prefix + most-common region), not a JSON-wrapped value.
        return raw
    value = json.loads(raw)
    if breakdown_by in TUPLE_BREAKDOWNS and isinstance(value, list):
        return tuple(value)
    if breakdown_by == WebStatsBreakdown.TIMEZONE and value is not None:
        return float(value)
    return value


def execute_read_query(
    *,
    runner: "WebStatsTableQueryRunner",
    job_ids: list[str],
    current_start_utc: datetime,
    current_end_utc: datetime,
    previous_start_utc: Optional[datetime],
    previous_end_utc: Optional[datetime],
) -> tuple[list[LazyStatsRow], bool, str]:
    """Read the precomputed rows via HogQL with SQL-side filtering, ordering and
    pagination. Returns `(rows, has_more, sort_metric)`.

    `parse_select` + placeholders build the column expressions; HAVING/ORDER BY
    are attached via direct AST mutation so the user's `orderBy` flows into the
    SQL (rather than a Python re-sort of an arbitrary slice). LIMIT/OFFSET come
    from `runner.paginator` using the +1 trick to derive `has_more` accurately.
    """
    # Sentinel for the no-compare case: an unsatisfiable window so the *MergeIf
    # aggregates return 0 for the "previous" columns without changing shape.
    prev_start = previous_start_utc if previous_start_utc is not None else datetime(1970, 1, 1, tzinfo=UTC)
    prev_end = previous_end_utc if previous_end_utc is not None else datetime(1970, 1, 1, tzinfo=UTC)

    sort_metric, descending = _resolve_sort_metric(runner.query)

    placeholders: dict[str, ast.Expr] = {
        "team_id": ast.Constant(value=runner.team.pk),
        "job_ids": ast.Constant(value=[str(jid) for jid in job_ids]),
        "breakdown_by": ast.Constant(value=runner.query.breakdownBy.value),
        "cur_start": ast.Constant(value=current_start_utc),
        "cur_end": ast.Constant(value=current_end_utc),
        "prev_start": ast.Constant(value=prev_start),
        "prev_end": ast.Constant(value=prev_end),
        "sort_metric": ast.Field(chain=[sort_metric]),
    }

    read_template = (
        _LANGUAGE_READ_SQL_TEMPLATE if runner.query.breakdownBy == WebStatsBreakdown.LANGUAGE else _READ_SQL_TEMPLATE
    )
    parsed = parse_select(read_template, placeholders=placeholders)
    assert isinstance(parsed, ast.SelectQuery)

    # Filter equivalent to the raw query's `outer_where_breakdown()`. Pushing
    # this to HAVING means ORDER BY + LIMIT downstream see the same row set the
    # raw path's pagination operates on. LANGUAGE applies its breakdown filter in
    # the subquery WHERE instead — its outer SELECT has no GROUP BY, so a HAVING
    # there would be invalid.
    if runner.query.breakdownBy != WebStatsBreakdown.LANGUAGE:
        parsed.having = _breakdown_having_expr(runner.query.breakdownBy)

    direction: Literal["ASC", "DESC"] = "DESC" if descending else "ASC"
    secondary = "views" if sort_metric == "visitors" else "visitors"
    parsed.order_by = [
        ast.OrderExpr(expr=ast.Field(chain=[sort_metric]), order=direction),
        ast.OrderExpr(expr=ast.Field(chain=[secondary]), order=direction),
        # Stable tiebreaker so consecutive pages don't overlap on equal-metric ties.
        ast.OrderExpr(expr=ast.Field(chain=["breakdown_value"]), order="ASC"),
    ]

    # The precomputed `time_window_start` column is UTC; `convertToProjectTimezone`
    # would wrap it in `toTimeZone(..., team_tz)` and break the direct comparison
    # against our UTC `cur_start` / `cur_end` constants.
    modifiers = runner.modifiers.model_copy() if runner.modifiers else HogQLQueryModifiers()
    modifiers.convertToProjectTimezone = False

    tag_queries(product=Product.WEB_ANALYTICS, feature=Feature.QUERY, query_type="web_stats_lazy_query")
    runner.paginator.execute_hogql_query(
        parsed,
        query_type="web_stats_lazy_query",
        team=runner.team,
        timings=runner.timings,
        modifiers=modifiers,
    )

    rows = [
        LazyStatsRow(
            breakdown_value=_decode_breakdown_value(runner.query.breakdownBy, row[0]),
            visitors_current=row[1],
            visitors_previous=row[2],
            views_current=row[3],
            views_previous=row[4],
            fill_total=row[5],
        )
        for row in runner.paginator.results
    ]
    return rows, runner.paginator.has_more(), sort_metric


def execute_lazy_precomputed_read(
    runner: "WebStatsTableQueryRunner",
) -> Optional[LazyStatsResult]:
    """Orchestrate the lazy precompute + read. Returns the decoded rows, or None
    on any failure (caller falls through to the raw path)."""
    # Tag the whole lazy path (INSERT + read) with product/feature so the INSERT
    # `sync_execute` inside `ensure_web_stats_precomputed` doesn't trip
    # DEBUG-mode `UntaggedQueryError`. The read query overrides `query_type`
    # later via `tag_queries(...)` inside `execute_read_query`.
    tag_queries(product=Product.WEB_ANALYTICS, feature=Feature.QUERY)
    team_id = runner.team.pk
    overall_started = time.perf_counter()
    try:
        date_from = runner.query_date_range.date_from()
        date_to = runner.query_date_range.date_to()
        assert date_from is not None and date_to is not None

        # Convert team-tz bounds to tz-aware UTC. We keep `tzinfo` so the HogQL
        # printer doesn't fall back to host-local timezone interpretation.
        current_start_utc = date_from.astimezone(UTC)
        current_end_utc = date_to.astimezone(UTC)

        # Expand the precompute span to UTC day boundaries so the framework's
        # daily-window jobs fully cover the team-tz request.
        time_range_start = floor_utc_day(current_start_utc)
        time_range_end = ceil_utc_day(current_end_utc)

        if time_range_start >= time_range_end:
            WEB_ANALYTICS_LAZY_PRECOMPUTE_FALLBACK.labels(family=_FAMILY, reason="empty_range").inc()
            logger.info(
                "web_stats_lazy_precompute_empty_range",
                team_id=team_id,
                time_range_start=time_range_start.isoformat(),
                time_range_end=time_range_end.isoformat(),
            )
            return None

        logger.info(
            "web_stats_lazy_precompute_started",
            team_id=team_id,
            breakdown_by=runner.query.breakdownBy.value,
            time_range_start=time_range_start.isoformat(),
            time_range_end=time_range_end.isoformat(),
            time_range_days=(time_range_end - time_range_start).days,
        )

        result = ensure_web_stats_precomputed(
            runner=runner,
            time_range_start=time_range_start,
            time_range_end=time_range_end,
        )
        if result.stale:
            handle_stale_served(runner=runner, family=_FAMILY)

        if not result.job_ids:
            WEB_ANALYTICS_LAZY_PRECOMPUTE_FALLBACK.labels(family=_FAMILY, reason="no_job_ids").inc()
            logger.info(
                "web_stats_lazy_precompute_no_job_ids",
                team_id=team_id,
                breakdown_by=runner.query.breakdownBy.value,
            )
            return None

        if not result.ready:
            WEB_ANALYTICS_LAZY_PRECOMPUTE_FALLBACK.labels(family=_FAMILY, reason="current_not_ready").inc()
            logger.info(
                "web_stats_lazy_precompute_current_not_ready",
                team_id=team_id,
                job_count=len(result.job_ids),
            )
            return None

        job_ids: list[str] = [str(jid) for jid in result.job_ids]

        previous_start_utc: Optional[datetime] = None
        previous_end_utc: Optional[datetime] = None
        if runner.query_compare_to_date_range is not None:
            prev_from = runner.query_compare_to_date_range.date_from()
            prev_to = runner.query_compare_to_date_range.date_to()
            if prev_from is not None and prev_to is not None:
                previous_start_utc = prev_from.astimezone(UTC)
                previous_end_utc = prev_to.astimezone(UTC)

                # Precompute the previous period too — without this the read's
                # `job_id IN` filter has no rows covering the previous window and
                # every `*MergeIf(..., prev_*)` returns 0.
                prev_range_start = floor_utc_day(previous_start_utc)
                prev_range_end = ceil_utc_day(previous_end_utc)

                # Cap the previous period's UTC range at the start of the current
                # period's so a non-UTC-timezone boundary day does not produce a
                # job_id shared by both ensure calls (see web overview for the
                # full rationale).
                prev_range_end = min(prev_range_end, time_range_start)

                if prev_range_start < prev_range_end:
                    prev_result = ensure_web_stats_precomputed(
                        runner=runner,
                        time_range_start=prev_range_start,
                        time_range_end=prev_range_end,
                    )
                    if prev_result.stale:
                        # Debounced with the current-period enqueue; one revalidation
                        # re-runs the whole query, covering both periods.
                        handle_stale_served(runner=runner, family=_FAMILY)

                    if not prev_result.ready:
                        WEB_ANALYTICS_LAZY_PRECOMPUTE_FALLBACK.labels(family=_FAMILY, reason="previous_not_ready").inc()
                        logger.info(
                            "web_stats_lazy_precompute_previous_not_ready",
                            team_id=team_id,
                            prev_job_count=len(prev_result.job_ids),
                        )
                        return None

                    job_ids.extend(str(jid) for jid in prev_result.job_ids)
                else:
                    # Cap collapsed the previous-period window to nothing (e.g. a
                    # non-UTC boundary day shared the same job_id as the current
                    # period). Clear the previous bounds so the read does not
                    # filter for a window with no backing job_ids — otherwise
                    # every `*MergeIf(..., prev_*)` would silently return 0.
                    previous_start_utc = None
                    previous_end_utc = None

        rows, has_more, sort_metric = execute_read_query(
            runner=runner,
            job_ids=job_ids,
            current_start_utc=current_start_utc,
            current_end_utc=current_end_utc,
            previous_start_utc=previous_start_utc,
            previous_end_utc=previous_end_utc,
        )

        WEB_ANALYTICS_LAZY_PRECOMPUTE_SUCCESS.labels(family=_FAMILY).inc()
        logger.info(
            "web_stats_lazy_precompute_completed",
            team_id=team_id,
            breakdown_by=runner.query.breakdownBy.value,
            job_count=len(result.job_ids),
            rows_returned=len(rows),
            has_more=has_more,
            total_duration_ms=int((time.perf_counter() - overall_started) * 1000),
        )
        return LazyStatsResult(rows=rows, has_more=has_more, sort_metric=sort_metric)
    except Exception as exc:
        WEB_STATS_LAZY_FAILED.labels(error_type=type(exc).__name__).inc()
        logger.exception(
            "web_stats_lazy_precompute_failed",
            team_id=team_id,
            error_type=type(exc).__name__,
            total_duration_ms=int((time.perf_counter() - overall_started) * 1000),
        )
        return None
