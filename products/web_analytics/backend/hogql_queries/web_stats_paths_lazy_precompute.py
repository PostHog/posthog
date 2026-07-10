"""Lazy precompute path for the Web Analytics PATHS (page + bounce) tile.

Mirrors `web_overview_lazy_precompute.py` and shares its eligibility gate via
`web_lazy_precompute_common`. The precomputed table stores one row per
(team, job, UTC hour, breakdown_value) where `breakdown_value` is the URL
path (optionally prefixed with `$host`). For each session we emit one row
per pathname it touched; `avg_bounce_state` is set only when the pathname
matched the session's entry pathname, which `avgState` ignores via NULL on
other rows — reproducing the v2 `PATH_BOUNCE_QUERY` join semantic of
attributing bounce to sessions that entered on the path.
"""

import time
from datetime import UTC, datetime
from typing import TYPE_CHECKING, Optional

import structlog
from prometheus_client import Counter, Histogram

from posthog.schema import (
    HogQLQueryModifiers,
    WebAnalyticsOrderByDirection,
    WebAnalyticsOrderByFields,
    WebStatsBreakdown,
)

from posthog.hogql import ast
from posthog.hogql.parser import parse_expr, parse_select
from posthog.hogql.query import execute_hogql_query

from posthog.clickhouse.query_tagging import Feature, Product, tag_queries

from products.analytics_platform.backend.lazy_computation.lazy_computation_executor import (
    LazyComputationResult,
    LazyComputationTable,
)
from products.web_analytics.backend.hogql_queries.web_lazy_precompute_common import (
    LAZY_TTL_SECONDS,
    SESSION_FORWARD_PAD_MINUTES,
    LazyPrecomputeIneligible,
    ceil_utc_day,
    check_common_eligibility,
    floor_utc_day,
    handle_stale_served,
    host_filter_expr,
    is_background_warming_request,
    log_eligibility_outcome,
    test_account_filter_expr,
    web_ensure_precomputed,
)

if TYPE_CHECKING:
    from products.web_analytics.backend.hogql_queries.stats_table import WebStatsTableQueryRunner

logger = structlog.get_logger(__name__)

_FAMILY = "web_stats_paths"


# Allowlist of exception class names we expect on the lazy path. Anything
# outside this set is collapsed to "other" so dependency-leaking dynamic
# exception names can't blow up Prometheus label cardinality.
_KNOWN_FAILED_ERROR_TYPES: set[str] = {
    "ServerException",  # clickhouse_driver
    "NetworkError",  # clickhouse_driver
    "OperationalError",  # Django DB
    "IntegrityError",  # Django DB
    "AssertionError",
    "AttributeError",
    "KeyError",
    "ValueError",
    "TypeError",
    "TimeoutError",
}


def _bucket_error_label(exc: BaseException) -> str:
    name = type(exc).__name__
    return name if name in _KNOWN_FAILED_ERROR_TYPES else "other"


WEB_STATS_PATHS_LAZY_FAILED = Counter(
    "web_stats_paths_lazy_precompute_failed_total",
    "Lazy precompute path (paths tile) failures, by error class",
    ["error_type"],
)

WEB_STATS_PATHS_LAZY_EMPTY = Counter(
    "web_stats_paths_lazy_precompute_empty_total",
    "Lazy precompute reads that returned zero rows (potential silent ingestion drop or fresh team).",
)

WEB_STATS_PATHS_LAZY_ROWS = Histogram(
    "web_stats_paths_lazy_precompute_rows",
    "Distinct `breakdown_value` rows returned by the lazy precompute read (post-LIMIT cap).",
    buckets=(1, 10, 100, 500, 1000, 2500, 5000, 7500, 10000, float("inf")),
)


class WrongBreakdown(LazyPrecomputeIneligible):
    pass


class MissingBounceRate(LazyPrecomputeIneligible):
    pass


class AvgTimeOnPageUnsupported(LazyPrecomputeIneligible):
    pass


class ScrollDepthUnsupported(LazyPrecomputeIneligible):
    pass


class UnsupportedOrderBy(LazyPrecomputeIneligible):
    def __init__(self, field: object):
        self.field = field
        super().__init__(f"field={field!r}")


# Order-by fields the lazy read response can produce. Anything outside this set
# would force the in-Python sort to fall back to visitors, which would silently
# diverge from the raw path's ordering — better to refuse and fall through.
SUPPORTED_ORDER_BY_FIELDS: set = {
    WebAnalyticsOrderByFields.VISITORS,
    WebAnalyticsOrderByFields.VIEWS,
    WebAnalyticsOrderByFields.BOUNCE_RATE,
}


def can_use_lazy_precompute(runner: "WebStatsTableQueryRunner") -> bool:
    """Return True iff the PATHS tile can be served from the precompute table."""
    try:
        _check_eligible(runner)
    except LazyPrecomputeIneligible as exc:
        log_eligibility_outcome(log_prefix="web_stats_paths_lazy_precompute", team_id=runner.team.pk, error=exc)
        return False
    log_eligibility_outcome(log_prefix="web_stats_paths_lazy_precompute", team_id=runner.team.pk, error=None)
    return True


def _check_eligible(runner: "WebStatsTableQueryRunner") -> None:
    query = runner.query

    # Path tile-specific checks first: cheaper than the org flag round-trip and
    # rejecting other tile shapes here means a single team-level flag still
    # allows overview/paths to opt in independently per query.
    if query.breakdownBy not in (WebStatsBreakdown.PAGE, WebStatsBreakdown.INITIAL_PAGE):
        raise WrongBreakdown(f"breakdownBy={query.breakdownBy!r}")
    if not query.includeBounceRate:
        raise MissingBounceRate()
    if query.includeAvgTimeOnPage:
        raise AvgTimeOnPageUnsupported()
    if query.includeScrollDepth:
        raise ScrollDepthUnsupported()
    # Refuse order-by fields the lazy response doesn't produce. The in-Python
    # sort otherwise silently rewrites to `visitors`, producing different rows
    # than the raw path's `_order_by` would for the same query.
    if query.orderBy:
        order_field = query.orderBy[0]
        if order_field not in SUPPORTED_ORDER_BY_FIELDS:
            raise UnsupportedOrderBy(order_field)

    check_common_eligibility(
        team=runner.team,
        use_web_analytics_precompute=query.useWebAnalyticsPrecompute,
        conversion_goal=query.conversionGoal,
        sampling=query.sampling,
        modifiers=query.modifiers,
        properties=query.properties or [],
        resolve_date_range=lambda: (runner.query_date_range.date_from(), runner.query_date_range.date_to()),
    )


def _events_session_id_expr(runner: "WebStatsTableQueryRunner") -> ast.Expr:
    return runner.events_session_property


def _prepend_host_nullif_empty(host_expr: ast.Expr, path_expr: ast.Expr) -> ast.Expr:
    """Match `WebStatsTableQueryRunner._prepend_host` semantics: concat then nullIf empty."""
    return ast.Call(
        name="nullIf",
        args=[
            ast.Call(name="concat", args=[host_expr, path_expr]),
            ast.Constant(value=""),
        ],
    )


def _breakdown_value_expr(runner: "WebStatsTableQueryRunner") -> ast.Expr:
    """The breakdown column for the precompute, per `runner.query.breakdownBy`:

    - `PAGE`: event pathname (one row per touched path per session) — bounce
      contributes only when this path matches the session's entry pathname,
      via `equals(breakdown_value, entry_breakdown_value)` inside the INSERT.
    - `INITIAL_PAGE`: session entry pathname — the inner `GROUP BY
      (session_id, breakdown_value)` collapses to per-session (entry path is
      constant within a session), so the outer aggregate is "sessions that
      entered on this path". Bounce contributes for every row because
      `breakdown_value == entry_breakdown_value` is always true.

    Path cleaning is applied HERE, at INSERT time, via `runner._apply_path_cleaning`
    (a no-op when `doPathCleaning` is off or the team has no rules). Storing
    already-cleaned paths collapses the breakdown to the cleaned cardinality and
    lets the read group the column directly — it avoids running the team's
    cleaning regex chain over every row on every read, which dominates read cost
    on high-path-cardinality teams. The cache key carries the cleaning: the
    regexes are part of this INSERT AST, so `doPathCleaning` on/off (and a rules
    change) produce distinct `query_hash`es / jobs that coexist — a rules edit
    just spawns a fresh job rather than invalidating in place.

    The cache key differentiates PAGE vs INITIAL_PAGE automatically: the AST
    for each branch differs, so the lazy_computation `query_hash` differs and
    the two precomputes coexist as distinct jobs."""
    if runner.query.breakdownBy == WebStatsBreakdown.INITIAL_PAGE:
        return _entry_breakdown_value_expr(runner)
    path: ast.Expr = ast.Field(chain=["events", "properties", "$pathname"])
    if runner.query.includeHost:
        path = _prepend_host_nullif_empty(ast.Field(chain=["events", "properties", "$host"]), path)
    # Clean after the optional host prefix so the stored value matches what the
    # read previously produced via `_apply_path_cleaning(breakdown_value)`.
    return runner._apply_path_cleaning(path)


def _entry_breakdown_value_expr(runner: "WebStatsTableQueryRunner") -> ast.Expr:
    """Entry pathname (optionally `entry_hostname`-prefixed) — must match the
    same shape AND cleaning as `_breakdown_value_expr` so the equality check
    inside the INSERT properly identifies sessions that entered on each path.
    Cleaning is applied identically (after the optional host prefix) so a cleaned
    pathname still matches its cleaned entry path."""
    path: ast.Expr = ast.Field(chain=["session", "$entry_pathname"])
    if runner.query.includeHost:
        path = _prepend_host_nullif_empty(ast.Field(chain=["session", "$entry_hostname"]), path)
    return runner._apply_path_cleaning(path)


# Cap on stored breakdown rows: only the top-K paths PER DAY by the query's sort
# metric. The PATHS tile shows a paginated top-N and the read's `LIMIT` can't prune
# the scan (it must aggregate every path to find the top), so the long tail — paths
# that never reach the display — is pure dead weight. Reads pay for every stored
# row of the covering jobs, so K directly prices read latency: at 100k the two
# highest-cardinality teams' stored sets grew ~8× and their reads regressed from
# ~300ms to multi-second during recompute windows, while ~95% of active teams
# (fewer than 10k distinct cleaned paths per week fleet-wide) never notice K at
# all. 10k per day keeps those teams' full path set, and because the cap is per
# day (see `INSERT_QUERY_TEMPLATE_CAPPED`) a multi-day job stores the union of
# daily top-Ks — strictly more coverage than the original per-job 10k cap, and
# sub-range reads stay correct.
PATHS_TOP_K = 10_000

# The per-(hour, breakdown) state aggregation — shared by the capped and uncapped
# inserts. The lazy_computation framework substitutes the placeholders (incl.
# `time_window_min`/`time_window_max`) and prepends `team_id`/`job_id` + appends
# `expires_at`. `event_type_filter` is a placeholder even though constant today so a
# future event-kind extension rotates the cache key instead of colliding.
_PER_WINDOW_AGG_SQL = """
SELECT
    toStartOfHour(start_timestamp) AS time_window_start,
    breakdown_value AS breakdown_value,
    uniqState(session_person_id) AS uniq_users_state,
    sumState(assumeNotNull(toInt(filtered_pageview_count))) AS sum_pageviews_state,
    -- Bounce only counts for sessions that entered on this pathname; other rows
    -- contribute NULL, which `avg` skips. We pass `toFloat(is_bounce)` directly
    -- without `assumeNotNull`: the column type is `Nullable(Float64)`, and v2's
    -- `avgIf(is_bounce, ...)` natively skips NULL `$is_bounce` — so the lazy
    -- path matches that semantic instead of coercing NULL to 0.
    avgState(
        if(
            equals(breakdown_value, entry_breakdown_value),
            toFloat(is_bounce),
            NULL
        )
    ) AS avg_bounce_state
FROM (
    SELECT
        any(events.person_id) AS session_person_id,
        {events_session_id} AS session_id,
        {breakdown_value_expr} AS breakdown_value,
        any({entry_breakdown_value_expr}) AS entry_breakdown_value,
        countIf({event_type_filter}) AS filtered_pageview_count,
        any(session.$is_bounce) AS is_bounce,
        min(session.$start_timestamp) AS start_timestamp
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
        breakdown_value IS NOT NULL,
        toStartOfHour(min(session.$start_timestamp)) >= {time_window_min},
        toStartOfHour(min(session.$start_timestamp)) < {time_window_max}
    )
)
GROUP BY time_window_start, breakdown_value
"""

# Uncapped insert — current behaviour, used for ASC sorts (see `_top_k_ranking_expr`).
INSERT_QUERY_TEMPLATE = _PER_WINDOW_AGG_SQL

# Capped insert — keep the top-K `breakdown_value`s by `{top_k_metric}` (the query's
# sort metric) computed PER DAY, then store all per-hour rows of any path that reaches
# a day's top-K. Capping per day (not over the whole job window) is what keeps the cap
# correct for sub-range reads: the read path decomposes a request into daily windows and
# can serve any one of them from a wider covering job (`filter_overlapping_jobs` in the
# lazy executor), so a path in a single day's top-K must be stored even if it falls
# outside the job window's overall top-K — a per-window cap silently drops it.
#
# `per_window` is referenced exactly ONCE: the top-K membership is computed inline with
# window functions instead of a re-scanning `breakdown_value IN (SELECT … FROM per_window)`
# subquery. The earlier double-reference let ClickHouse's analyzer inline the CTE twice and
# prune the inner events subquery's projection per reference — which dropped test-account
# filter-only `mat_*` columns (e.g. `$raw_user_agent` bot filters) out from under the filter
# that still referenced them → `Code 47 UNKNOWN_IDENTIFIER`. A single reference can't be
# pruned inconsistently. `{top_k_metric}` is the sort metric merged across the breakdown's
# hourly rows within each day via `… OVER (PARTITION BY breakdown_value, day_bucket)`;
# `dense_rank()` over it, partitioned by day (constant per breakdown within a day, ties
# broken by `breakdown_value ASC`), ranks distinct breakdowns within each day, so
# `<= PATHS_TOP_K` keeps the union of daily top-Ks. (HogQL parses `LIMIT n BY` but the
# printer can't emit it, so the cap ranks with window functions.) The metric stays in the
# AST, so each sort variant gets its own job.
INSERT_QUERY_TEMPLATE_CAPPED = (
    "WITH per_window AS ("
    + _PER_WINDOW_AGG_SQL
    + """)
SELECT
    time_window_start AS time_window_start,
    breakdown_value AS breakdown_value,
    uniq_users_state AS uniq_users_state,
    sum_pageviews_state AS sum_pageviews_state,
    avg_bounce_state AS avg_bounce_state
FROM (
    SELECT
        time_window_start AS time_window_start,
        breakdown_value AS breakdown_value,
        uniq_users_state AS uniq_users_state,
        sum_pageviews_state AS sum_pageviews_state,
        avg_bounce_state AS avg_bounce_state,
        dense_rank() OVER (
            PARTITION BY day_bucket
            ORDER BY breakdown_rank_metric DESC, breakdown_value ASC
        ) AS breakdown_rank
    FROM (
        SELECT
            time_window_start AS time_window_start,
            breakdown_value AS breakdown_value,
            uniq_users_state AS uniq_users_state,
            sum_pageviews_state AS sum_pageviews_state,
            avg_bounce_state AS avg_bounce_state,
            toStartOfDay(time_window_start) AS day_bucket,
            {top_k_metric} AS breakdown_rank_metric
        FROM per_window
    )
)
WHERE breakdown_rank <= """
    + str(PATHS_TOP_K)
)


def _top_k_ranking_expr(runner: "WebStatsTableQueryRunner") -> ast.Expr | None:
    """Ranking expression for the insert top-K cap, mirroring the read's sort.

    Returns the metric to rank by (DESC, top-K kept) for a descending sort — the
    common, displayable case (the eager warmer's default is `visitors DESC`). Returns
    `None` for an ascending sort: there the "top" is a huge tied long tail (e.g. all
    1-visit paths), so a cap would be unstable and shrink nothing — we store the full
    set uncapped instead. Field/direction default to `visitors DESC`, matching
    `WebStatsTableQueryRunner._resolve_sort_field`. Bounce NaN (paths with no entry
    sessions) ranks last via the `-1.0` sentinel, matching the read's NULLS-LAST.

    The metric is merged across the breakdown's per-hour rows within each day via
    `OVER (PARTITION BY breakdown_value, toStartOfDay(time_window_start))` so the capped
    template can rank breakdowns per day in a single pass over `per_window` (see
    `INSERT_QUERY_TEMPLATE_CAPPED`)."""
    order_by = runner.query.orderBy or []
    # A missing direction (single-element or empty orderBy) defaults to DESC, matching
    # `_resolve_sort_field`'s fallback — so we still cap rather than storing the full set.
    direction = order_by[1] if len(order_by) > 1 else WebAnalyticsOrderByDirection.DESC
    if direction != WebAnalyticsOrderByDirection.DESC:
        return None
    # The `OVER (PARTITION BY breakdown_value, toStartOfDay(time_window_start))` window
    # merges the metric across the breakdown's per-hour rows within a day so the capped
    # template can rank per day in one pass. Fully static SQL — no interpolation, no
    # user input.
    field = order_by[0] if order_by else WebAnalyticsOrderByFields.VISITORS
    if field == WebAnalyticsOrderByFields.VIEWS:
        return parse_expr(
            "sumMerge(sum_pageviews_state) OVER (PARTITION BY breakdown_value, toStartOfDay(time_window_start))"
        )
    if field == WebAnalyticsOrderByFields.BOUNCE_RATE:
        return parse_expr(
            "if(isNaN(avgMerge(avg_bounce_state) "
            "OVER (PARTITION BY breakdown_value, toStartOfDay(time_window_start))), -1.0, "
            "avgMerge(avg_bounce_state) "
            "OVER (PARTITION BY breakdown_value, toStartOfDay(time_window_start)))"
        )
    return parse_expr(
        "uniqMerge(uniq_users_state) OVER (PARTITION BY breakdown_value, toStartOfDay(time_window_start))"
    )


# Wall-clock budget for a *user-facing* request's whole ensure phase (current period plus
# the compare period, which shares whatever remains). The executor checks the budget before
# starting each inline INSERT, so completed windows always persist as READY jobs and later
# requests (or the hourly warmer) converge to warm. Timing out here only means this request
# serves the v2/raw fallback instead of blocking on a long rebuild. 10s admits one or two
# typical window inserts (2-8s each on the largest teams), so the common one-stale-window
# case still completes inline; what it bounds is the pile-up case (many stale windows after
# a hash rotation), which previously held requests for 30s+.
PATHS_USER_ENSURE_WAIT_SECONDS = 10


def ensure_web_stats_paths_precomputed(
    runner: "WebStatsTableQueryRunner",
    time_range_start: datetime,
    time_range_end: datetime,
    wait_budget_seconds: float | None = None,
) -> LazyComputationResult:
    placeholders: dict[str, ast.Expr] = {
        "events_session_id": _events_session_id_expr(runner),
        "breakdown_value_expr": _breakdown_value_expr(runner),
        "entry_breakdown_value_expr": _entry_breakdown_value_expr(runner),
        "event_type_filter": runner.event_type_expr,
        "user_filter": host_filter_expr(runner.query.properties or [], team=runner.team),
        "test_account_filter": test_account_filter_expr(
            test_account_filters=runner._test_account_filters, team=runner.team
        ),
        "pad_minutes": ast.Constant(value=SESSION_FORWARD_PAD_MINUTES),
    }

    # Cap to the displayable top-K for descending sorts; store the full set otherwise.
    # The metric goes into the INSERT AST, so the sort dimension joins the job hash.
    ranking_expr = _top_k_ranking_expr(runner)
    if ranking_expr is not None:
        insert_query = INSERT_QUERY_TEMPLATE_CAPPED
        placeholders["top_k_metric"] = ranking_expr
    else:
        insert_query = INSERT_QUERY_TEMPLATE

    # Warmers keep the framework default; user-facing calls get the 10s budget, or the
    # caller-provided remainder of it when this is the second (compare-period) ensure.
    if is_background_warming_request():
        wait_timeout: float | None = None
    elif wait_budget_seconds is not None:
        wait_timeout = wait_budget_seconds
    else:
        wait_timeout = PATHS_USER_ENSURE_WAIT_SECONDS
    return web_ensure_precomputed(
        team=runner.team,
        insert_query=insert_query,
        time_range_start=time_range_start,
        time_range_end=time_range_end,
        ttl_seconds=LAZY_TTL_SECONDS,
        table=LazyComputationTable.WEB_STATS_PATHS_PREAGGREGATED,
        placeholders=placeholders,
        query_type="web_stats_paths_lazy_insert",
        spill_to_disk=True,  # high-cardinality path breakdown GROUP BY; can build a large hash table
        wait_timeout_seconds=wait_timeout,
    )


# Returns one row per breakdown_value with (current, previous) period pairs
# plus a fill-fraction column for the bar visualisation:
#   breakdown_value, visitors, prev_visitors, views, prev_views, bounce_rate,
#   prev_bounce_rate, fill_fraction
#
# Sort, paginate, and fill-fraction are all computed in SQL so we read back
# exactly the page the user is looking at — no in-Python re-sort, no
# defence-in-depth cardinality cap. `_build_response_from_lazy_rows` just
# materialises the page directly. Matches v2's
# `StatsTablePreAggregatedQueryBuilder._fill_fraction` / `_get_order_by`
# pattern (`stats_table_pre_aggregated.py:515,543`).

# Soft budget for the cumulative `ensure_precomputed` time inside a single
# request. The framework's default `wait_timeout_seconds` is 180 s per call; a
# compare-period request makes two back-to-back calls. If the first burns most
# of that budget we skip the second and fall through to v2/raw to keep the
# overall HTTP request from sitting on a worker for >3 minutes.
ENSURE_BUDGET_MS = 120 * 1000

# HogQL read template. `{...}` placeholders are substituted via `parse_select`
# `placeholders`. ORDER BY / LIMIT / OFFSET are NOT in the template — they're
# attached to the parsed AST in `execute_read_query` so we can build them from
# `runner.query.orderBy` / `runner.paginator` without string interpolation.
#
# `top_level_settings` on `WebStatsPathsPreaggregatedTable` applies
# `load_balancing="in_order"` (read-your-writes via Approach E in
# `products/analytics_platform/backend/lazy_computation/CONSISTENCY.md`) and
# `optimize_skip_unused_shards=1` (shard pruning via the `job_id IN (...)`
# filter + `sipHash64(job_id)` sharding key) — they flow through the printer
# automatically, no need to set them per-call.
#
# `convertToProjectTimezone=False` is forced on the modifiers when invoking
# `execute_hogql_query`, so `time_window_start` (stored UTC) is compared
# directly against the UTC bounds we pass in via `{cur_start}` etc. without
# HogQL coercing them to the team's local timezone.
#
# `breakdown_expr` is the stored `breakdown_value` column directly — no read-time
# cleaning. Path cleaning is baked into the precompute at INSERT time (see
# `_breakdown_value_expr`), so the stored column is already cleaned (or raw, for a
# `doPathCleaning=False` job — the two are distinct `query_hash`es). This avoids
# running the team's nested `replaceRegexpAll` chain over every row on every read,
# which dominated read cost on high-path-cardinality teams.
# The SELECT alias is deliberately `breakdown` (not `breakdown_value`) to avoid
# shadowing the underlying column name. With the same name, HogQL resolves
# `breakdown_value` in GROUP BY to the SELECT alias (printing without the
# table qualifier) which then mismatches the SELECT expression's qualified
# form, and ClickHouse rejects the query with "not under aggregate function
# and not in GROUP BY keys". The consumer destructures rows positionally, so
# the alias name does not affect the response shape.
#
# The outer SELECT wraps the inner aggregation so we can:
#   - normalise NaN → NULL on bounce_rate (avgMergeIf returns NaN, not NULL,
#     when no entry sessions contributed; ClickHouse `ORDER BY ... NULLS LAST`
#     only catches NULL)
#   - compute `fill_fraction` via `sum(...) OVER ()` against the inner GROUP
#     BY result (matching v2's `_fill_fraction`)
_READ_SQL_TEMPLATE = """
SELECT
    breakdown,
    visitors,
    previous_visitors,
    views,
    previous_views,
    if(isNaN(raw_bounce), NULL, raw_bounce) AS bounce_rate,
    if(isNaN(raw_prev_bounce), NULL, raw_prev_bounce) AS previous_bounce_rate,
    {fill_fraction_expr} AS fill_fraction
FROM (
    SELECT
        {breakdown_expr} AS breakdown,
        uniqMergeIf(uniq_users_state, and(time_window_start >= {cur_start}, time_window_start < {cur_end})) AS visitors,
        uniqMergeIf(uniq_users_state, and(time_window_start >= {prev_start}, time_window_start < {prev_end})) AS previous_visitors,
        sumMergeIf(sum_pageviews_state, and(time_window_start >= {cur_start}, time_window_start < {cur_end})) AS views,
        sumMergeIf(sum_pageviews_state, and(time_window_start >= {prev_start}, time_window_start < {prev_end})) AS previous_views,
        avgMergeIf(avg_bounce_state, and(time_window_start >= {cur_start}, time_window_start < {cur_end})) AS raw_bounce,
        avgMergeIf(avg_bounce_state, and(time_window_start >= {prev_start}, time_window_start < {prev_end})) AS raw_prev_bounce
    FROM posthog.web_stats_paths_preaggregated
    WHERE and(
        team_id = {team_id},
        job_id IN {job_ids},
        time_window_start >= {window_min},
        time_window_start < {window_max}
    )
    GROUP BY {breakdown_expr}
    HAVING or(visitors > 0, previous_visitors > 0)
)
"""


def _build_order_by(sort_column: str, sort_direction: str) -> list[ast.OrderExpr]:
    """Build the SQL ORDER BY for the lazy read.

    Sort with explicit NULLS LAST behaviour (`isNull(x) ASC` first), then by
    the user's requested field/direction, then by the path string for a stable
    tiebreaker. `bounce_rate` can be NULL (post-`if(isNaN(...), NULL, ...)`
    coercion in the outer SELECT) when no entry sessions touched a path —
    those rows must go to the end regardless of direction so the UI's empty
    cells aren't interleaved with real data.
    """
    return [
        ast.OrderExpr(expr=ast.Call(name="isNull", args=[ast.Field(chain=[sort_column])]), order="ASC"),
        ast.OrderExpr(expr=ast.Field(chain=[sort_column]), order=sort_direction),  # type: ignore[arg-type]
        ast.OrderExpr(expr=ast.Field(chain=["breakdown"]), order="ASC"),
    ]


def _fill_fraction_expr(sort_column: str) -> ast.Expr:
    """SQL expression for the row's bar-fraction. Mirrors v2's `_fill_fraction`:
    visitors/views are ratio-of-sum over the GROUP BY result; bounce_rate is
    already a 0..1 fraction so passthrough."""
    if sort_column == "bounce_rate":
        # `bounce_rate` may be NULL post-NaN-coercion; the UI tolerates a NULL
        # fill (renders as no bar) so we don't `coalesce` here.
        return ast.Field(chain=["bounce_rate"])
    # `visitors` / `views` are non-negative ints, so `sum(x) OVER ()` is safe;
    # the denominator is zero only when every row is zero. The raw v2 path uses
    # the same unguarded `{col}.1 / sum({col}.1) OVER ()` shape — staying lock-
    # step keeps parity (both may NaN under the same conditions).
    return ast.Call(
        name="divide",
        args=[
            ast.Field(chain=[sort_column]),
            ast.WindowFunction(
                name="sum",
                args=[ast.Field(chain=[sort_column])],
                over_expr=ast.WindowExpr(),
            ),
        ],
    )


def execute_read_query(
    *,
    runner: "WebStatsTableQueryRunner",
    job_ids: list[str],
    current_start_utc: datetime,
    current_end_utc: datetime,
    previous_start_utc: Optional[datetime],
    previous_end_utc: Optional[datetime],
    sort_column: str,
    sort_direction: str,
    limit: int,
    offset: int,
) -> list:
    """Read the precomputed PATHS rows via HogQL.

    Returns the raw `response.results` (list of tuples) so the caller can
    materialize without depending on HogQL's response type. Sort, pagination,
    and fill-fraction are computed in SQL — the caller materialises the page
    directly without any in-Python re-sort.
    """
    # Sentinel for the no-compare case: an unsatisfiable window so the *MergeIf
    # aggregates return 0 / NaN for the "previous" columns without changing shape.
    prev_start = previous_start_utc if previous_start_utc is not None else datetime(1970, 1, 1, tzinfo=UTC)
    prev_end = previous_end_utc if previous_end_utc is not None else datetime(1970, 1, 1, tzinfo=UTC)

    # Prune the scan to the union of the two requested windows. Covering jobs can be
    # much wider than the request (a 7d read served by a 31d-warm job set), and without
    # this bound every stored row of every covering job is scanned and state-merged only
    # to be discarded by the *MergeIf conditions. Computed in Python (not `least()` in
    # SQL) because the no-compare sentinel above would otherwise widen the lower bound
    # to 1970 and defeat the pruning.
    window_min = min(current_start_utc, previous_start_utc) if previous_start_utc else current_start_utc
    window_max = max(current_end_utc, previous_end_utc) if previous_end_utc else current_end_utc

    placeholders: dict[str, ast.Expr] = {
        "team_id": ast.Constant(value=runner.team.pk),
        "job_ids": ast.Constant(value=[str(jid) for jid in job_ids]),
        "cur_start": ast.Constant(value=current_start_utc),
        "cur_end": ast.Constant(value=current_end_utc),
        "prev_start": ast.Constant(value=prev_start),
        "prev_end": ast.Constant(value=prev_end),
        "window_min": ast.Constant(value=window_min),
        "window_max": ast.Constant(value=window_max),
        "breakdown_expr": ast.Field(chain=["breakdown_value"]),
        "fill_fraction_expr": _fill_fraction_expr(sort_column),
    }

    parsed = parse_select(_READ_SQL_TEMPLATE, placeholders=placeholders)
    assert isinstance(parsed, ast.SelectQuery), "lazy paths read template must parse to a SelectQuery"
    parsed.order_by = _build_order_by(sort_column, sort_direction)
    parsed.limit = ast.Constant(value=limit)
    parsed.offset = ast.Constant(value=offset)

    # The precomputed `time_window_start` column is UTC; `convertToProjectTimezone`
    # would wrap it in `toTimeZone(..., team_tz)` and break the direct comparison
    # against our UTC `cur_start`/`cur_end` constants.
    modifiers = runner.modifiers.model_copy() if runner.modifiers else HogQLQueryModifiers()
    modifiers.convertToProjectTimezone = False

    tag_queries(product=Product.WEB_ANALYTICS, feature=Feature.QUERY, query_type="web_stats_paths_lazy_query")
    response = execute_hogql_query(
        query_type="web_stats_paths_lazy_query",
        query=parsed,
        team=runner.team,
        timings=runner.timings,
        modifiers=modifiers,
        limit_context=runner.limit_context,
    )
    return list(response.results or [])


def execute_lazy_precomputed_read(
    runner: "WebStatsTableQueryRunner",
    *,
    sort_column: str,
    sort_direction: str,
    limit: int,
    offset: int,
) -> Optional[list[tuple]]:
    """Orchestrate the lazy precompute + read. Returns the list of result rows,
    or None on any failure (caller falls through to the v2/raw path).

    Sort/limit/offset are applied in SQL — `rows` already contains exactly the
    paginated page in the user's requested order. Each row is
    ``(breakdown_value, visitors, prev_visitors, views, prev_views,
    bounce_rate, prev_bounce_rate, fill_fraction)``.

    The caller fetches `limit + 1` to detect `hasMore`.
    """
    tag_queries(product=Product.WEB_ANALYTICS, feature=Feature.QUERY)
    team_id = runner.team.pk
    overall_started = time.perf_counter()
    try:
        date_from = runner.query_date_range.date_from()
        date_to = runner.query_date_range.date_to()
        assert date_from is not None and date_to is not None

        current_start_utc = date_from.astimezone(UTC)
        current_end_utc = date_to.astimezone(UTC)

        time_range_start = floor_utc_day(current_start_utc)
        time_range_end = ceil_utc_day(current_end_utc)

        if time_range_start >= time_range_end:
            logger.info(
                "web_stats_paths_lazy_precompute_empty_range",
                team_id=team_id,
                time_range_start=time_range_start.isoformat(),
                time_range_end=time_range_end.isoformat(),
            )
            return None

        logger.info(
            "web_stats_paths_lazy_precompute_started",
            team_id=team_id,
            time_range_start=time_range_start.isoformat(),
            time_range_end=time_range_end.isoformat(),
            time_range_days=(time_range_end - time_range_start).days,
        )

        ensure_started = time.perf_counter()
        result = ensure_web_stats_paths_precomputed(
            runner=runner,
            time_range_start=time_range_start,
            time_range_end=time_range_end,
        )
        ensure_duration_ms = int((time.perf_counter() - ensure_started) * 1000)

        logger.info(
            "web_stats_paths_lazy_precompute_ensure_done",
            team_id=team_id,
            job_count=len(result.job_ids),
            ensure_duration_ms=ensure_duration_ms,
            stale=result.stale,
        )
        if result.stale:
            handle_stale_served(runner=runner, family=_FAMILY)

        if not result.job_ids:
            return None

        if not result.ready:
            logger.info(
                "web_stats_paths_lazy_precompute_current_not_ready",
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

                prev_range_start = floor_utc_day(previous_start_utc)
                prev_range_end = ceil_utc_day(previous_end_utc)
                if prev_range_start < prev_range_end:
                    # The compare ensure spends whatever the current-period ensure left of
                    # the budget, so a request with both periods stale cannot block for
                    # 2x the intended time. Warmers keep the framework's 180s per call
                    # (their gate is the wider ENSURE_BUDGET_MS); user-facing requests
                    # share the single PATHS_USER_ENSURE_WAIT_SECONDS across both calls.
                    is_background = is_background_warming_request()
                    if ensure_duration_ms >= ENSURE_BUDGET_MS:
                        logger.info(
                            "web_stats_paths_lazy_precompute_compare_budget_exceeded",
                            team_id=team_id,
                            elapsed_ms=ensure_duration_ms,
                            budget_ms=ENSURE_BUDGET_MS,
                        )
                        return None
                    remaining_budget: Optional[float] = None
                    if not is_background:
                        remaining_budget = PATHS_USER_ENSURE_WAIT_SECONDS - ensure_duration_ms / 1000
                        if remaining_budget <= 1:
                            logger.info(
                                "web_stats_paths_lazy_precompute_compare_budget_exceeded",
                                team_id=team_id,
                                elapsed_ms=ensure_duration_ms,
                                budget_ms=PATHS_USER_ENSURE_WAIT_SECONDS * 1000,
                            )
                            return None
                    prev_ensure_started = time.perf_counter()
                    prev_result = ensure_web_stats_paths_precomputed(
                        runner=runner,
                        time_range_start=prev_range_start,
                        time_range_end=prev_range_end,
                        wait_budget_seconds=remaining_budget,
                    )
                    ensure_duration_ms += int((time.perf_counter() - prev_ensure_started) * 1000)

                    if prev_result.stale:
                        # The debounce collapses this with the current-period enqueue; one
                        # revalidation re-runs the whole query, covering both periods.
                        handle_stale_served(runner=runner, family=_FAMILY)

                    if not prev_result.ready:
                        logger.info(
                            "web_stats_paths_lazy_precompute_previous_not_ready",
                            team_id=team_id,
                            prev_job_count=len(prev_result.job_ids),
                        )
                        return None

                    job_ids.extend(str(jid) for jid in prev_result.job_ids)

        read_started = time.perf_counter()
        rows = execute_read_query(
            runner=runner,
            job_ids=job_ids,
            current_start_utc=current_start_utc,
            current_end_utc=current_end_utc,
            previous_start_utc=previous_start_utc,
            previous_end_utc=previous_end_utc,
            sort_column=sort_column,
            sort_direction=sort_direction,
            limit=limit,
            offset=offset,
        )
        read_duration_ms = int((time.perf_counter() - read_started) * 1000)

        total_duration_ms = int((time.perf_counter() - overall_started) * 1000)

        rows_returned = len(rows) if rows else 0
        WEB_STATS_PATHS_LAZY_ROWS.observe(rows_returned)
        if rows_returned == 0:
            WEB_STATS_PATHS_LAZY_EMPTY.inc()
        logger.info(
            "web_stats_paths_lazy_precompute_completed",
            team_id=team_id,
            job_count=len(result.job_ids),
            rows_returned=rows_returned,
            ensure_duration_ms=ensure_duration_ms,
            read_duration_ms=read_duration_ms,
            total_duration_ms=total_duration_ms,
        )
        return list(rows) if rows else []
    except Exception as exc:
        WEB_STATS_PATHS_LAZY_FAILED.labels(error_type=_bucket_error_label(exc)).inc()
        logger.exception(
            "web_stats_paths_lazy_precompute_failed",
            team_id=team_id,
            error_type=type(exc).__name__,
            total_duration_ms=int((time.perf_counter() - overall_started) * 1000),
        )
        return None
