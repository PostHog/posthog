import os
import re
import gzip
import json
import time
import zlib
import random
import threading
import statistics
from concurrent.futures import FIRST_COMPLETED, ThreadPoolExecutor, wait
from datetime import datetime, timedelta
from typing import TYPE_CHECKING, Optional

from django.core.exceptions import ObjectDoesNotExist
from django.db import close_old_connections
from django.utils.dateparse import parse_datetime

import dagster
import structlog
from dagster import Backoff, Jitter, RetryPolicy
from prometheus_client import Counter, Gauge

from posthog.hogql.constants import LimitContext

from posthog.clickhouse.client import sync_execute
from posthog.clickhouse.query_tagging import Feature, reset_query_tags, tag_queries
from posthog.dags.common import JobOwners
from posthog.event_usage import EventSource
from posthog.exceptions import ClickHouseAtCapacity
from posthog.exceptions_capture import capture_exception
from posthog.hogql_queries.query_runner import ExecutionMode, get_query_runner_or_none
from posthog.models import Team
from posthog.models.instance_setting import get_instance_setting
from posthog.query_cache import QueryCache
from posthog.settings import CLICKHOUSE_CLUSTER
from posthog.storage import object_storage

from products.analytics_platform.backend.lazy_computation.stale_policy import SHARED_BACKGROUND_WARMING_TRIGGERS
from products.web_analytics.backend.hogql_queries.web_goals_lazy_precompute import (
    can_use_lazy_precompute as can_use_goals_lazy_precompute,
)
from products.web_analytics.backend.hogql_queries.web_lazy_precompute_common import (
    BACKGROUND_WARMING_TRIGGERS,
    MAX_PRECOMPUTE_DAYS,
    SHAPE_CAP_KEY_IGNORED_QUERY_FIELDS,
)
from products.web_analytics.backend.hogql_queries.web_overview_lazy_precompute import (
    can_use_lazy_precompute as can_use_overview_lazy_precompute,
)
from products.web_analytics.backend.hogql_queries.web_stats_frustration_lazy_precompute import (
    can_use_lazy_precompute as can_use_frustration_lazy_precompute,
)
from products.web_analytics.backend.hogql_queries.web_stats_lazy_precompute import (
    can_use_lazy_precompute as can_use_stats_lazy_precompute,
)
from products.web_analytics.backend.hogql_queries.web_stats_paths_lazy_precompute import (
    can_use_lazy_precompute as can_use_paths_lazy_precompute,
)
from products.web_analytics.backend.hogql_queries.web_vitals_paths_lazy_precompute import (
    can_use_lazy_precompute as can_use_vitals_paths_lazy_precompute,
)
from products.web_analytics.dags.web_preaggregated_utils import check_for_concurrent_runs

if TYPE_CHECKING:
    from posthog.hogql_queries.query_runner import QueryRunner

WARMING_SHAPES_SELECTED_GAUGE = Gauge(
    "posthog_web_analytics_warming_shapes_selected",
    "Number of hot query shapes selected for web analytics warming in the last run",
)
WARMING_QUERIES_COUNTER = Counter(
    "posthog_web_analytics_warming_queries_total",
    "Web analytics warming outcomes per query shape",
    # warmed | skipped_fresh | skipped_duplicate | skipped_raw_low_demand |
    # skipped_cold | skipped_already_warmed | failed | unsupported
    ["outcome"],
)

logger = structlog.get_logger(__name__)

cache_warming_retry_policy = RetryPolicy(
    max_retries=3,
    delay=2,
    backoff=Backoff.EXPONENTIAL,
    jitter=Jitter.FULL,
)


# Query kinds that carry the `useWebAnalyticsPrecompute` per-query toggle.
LAZY_PRECOMPUTE_QUERY_KINDS = frozenset(
    {"WebStatsTableQuery", "WebOverviewQuery", "WebGoalsQuery", "WebVitalsPathBreakdownQuery"}
)

# Per-team ceiling on selected shapes. Bounds how much hourly background compute a
# single tenant can claim by running many distinct shapes past the demand threshold
# (the queries replay outside the tenant's own request throttles).
MAX_SHAPES_PER_TEAM = 100

# Demand is selected by API query kind, not by query_type tag: the tag
# vocabulary is a growing zoo of strategy variants (no_join, session_id_set,
# lazy reads, per-breakdown inserts, …) and enumerating it would silently drop
# new variants from warming. Every kind in the web analytics family starts with
# "Web" (WebOverviewQuery, WebStatsTableQuery, WebVitalsQuery, …).
WARMABLE_QUERY_KIND_PREFIX = "Web"

# Web-family kinds with no get_query_runner branch (they execute through other
# paths). Excluded in the selection so they don't consume the capped slots or
# inflate dry-run counts; warm_queries_op's `unsupported` outcome remains the
# backstop for any future runnerless kind not yet listed here.
UNWARMABLE_QUERY_KINDS = ("WebVitalsQuery",)

# Internal helper rows of a single API call (bucket builds, id-set preflights);
# counting them would double-count demand for teams on those strategies.
INTERNAL_QUERY_TYPE_SUFFIXES = ("_lazy_insert", "_preflight")
_INTERNAL_QUERY_TYPE_FILTER = " OR ".join(f"endsWith(query_type, '{s}')" for s in INTERNAL_QUERY_TYPE_SUFFIXES)

# Request kind (top-level log_comment `kind`) excluded from demand selection.
# Temporal-kind requests are batch/scheduled workflows that run web queries
# across nearly every team; counting them made the selection reflect background
# traffic rather than real dashboard usage. UI and personal-API-key requests are
# kept — those are the reads warming is meant to keep fast.
EXCLUDED_REQUEST_KIND = "temporal"

# Read-bytes ceiling for the demand-selection scan. The 14-day fleet-wide
# query_log scan reads ~40 TiB, over the default cap, so it's raised — but to a
# finite value (~150 TiB, generous headroom for fleet growth) rather than 0, so
# the ClickHouse kill switch's overload cap still clamps it during an overload.
_SELECTION_MAX_BYTES_TO_READ = 150 * 1024**4


def maybe_opt_into_lazy_precompute(query_json: dict) -> dict:
    """Opt a replayed query into the lazy precompute path.

    Replayed production shapes carry no per-query toggle (users only send one via
    the UI). Injecting an explicit `True` makes the warmer build precompute
    buckets regardless of the opt-in default in the runner's eligibility gate,
    while an explicit user `False` in the replayed shape is preserved. Whether a
    team may build buckets at all is decided by the runner's own gate — warming
    requests bypass the rollout flag there, so this injection needs no
    enablement check (flag evaluation is unreliable in Dagster anyway).
    """
    if query_json.get("kind") not in LAZY_PRECOMPUTE_QUERY_KINDS:
        return query_json
    if query_json.get("useWebAnalyticsPrecompute") is not None:
        return query_json
    return {**query_json, "useWebAnalyticsPrecompute": True}


# Warmed bucket depth. ~88% of web analytics requests fit inside 7 days but 93%
# fit inside 30 (-14d/-28d/-30d/month-start make up the difference); since
# per-day buckets are immutable and shared across date ranges, building 30 days
# once covers every narrower request at no recurring cost.
WARMING_EXPANDED_DATE_FROM = "-30d"

# Sub-30d presets that widen to WARMING_EXPANDED_DATE_FROM. Absolute dates and
# wider or point-in-time presets (mStart, all, yStart, -90d, …) are left
# untouched. Months/years are deliberately excluded: -1m can span 31 days, so
# expanding it would narrow it.
_SUB_30D_DATE_FROM_PRESETS = frozenset({"dStart", "-1dStart", "wStart", "-1wStart"})
_HOURS_PER_DAY = 24
_DAYS_PER_WEEK = 7

# Only -Nh/-Nd/-Nw have an exact, monotonic lookback (deeper strictly covers
# shallower), so only these are safe to rank when choosing how deep to warm a
# shape. mStart/-1m/absolute have variable or point-in-time spans — mStart is a
# single day early in the month — so ranking them as "deep" could shrink coverage.
_EXACT_LOOKBACK_DATE_FROM_RE = re.compile(r"^-(\d+)([hdw])$")


def _exact_lookback_days(date_from: str | None) -> int | None:
    """Days a -Nh/-Nd/-Nw range reaches back, or None for any other form."""
    match = _EXACT_LOOKBACK_DATE_FROM_RE.match(date_from or "")
    if not match:
        return None
    value, unit = int(match.group(1)), match.group(2)
    if unit == "h":
        return value // _HOURS_PER_DAY
    if unit == "w":
        return value * _DAYS_PER_WEEK
    return value


def _is_within_30_days(date_from: str | None) -> bool:
    if not date_from:
        return True  # unset falls back to the -7d default
    if date_from in _SUB_30D_DATE_FROM_PRESETS:
        return True
    days = _exact_lookback_days(date_from)
    return days is not None and days < 30


def deepen_to_widest_warmable_range(query_json: dict, observed_date_froms: list[str], max_days: int) -> dict:
    """Point a lazy-path replay at the deepest -Nd/-Nw/-Nh range its own demand
    covers, capped at max_days.

    Fragmentation grouping collapses every date-range variant of a shape into one
    replay, and the representative's own range is arbitrary. Since per-day buckets
    are immutable and shared, warming the deepest observed range once builds the
    buckets every narrower variant reuses — otherwise a shape whose deepest demand
    is -90d but whose representative is -7d only warms 30 days, and each -90d
    request cold-builds the 31-90d tail inline. Ranges past max_days can't be
    precomputed, so they're excluded.

    Deepening is confined to shapes the lazy path will serve, and only to
    open-ended ("to now") ranges. A raw-path shape must replay its faithful range
    — a deeper raw scan is background load the tenant never ran, and its demand
    was only counted at the shallow variant. And a fixed date_to can't be paired
    with another variant's date_from (normalization dropped which endpoints went
    together), so splicing one in could reverse or balloon the span. This mirrors
    maybe_expand_warming_date_range's gate; build_replay_runner applies both before
    the eligibility check and falls back to the untouched range for the raw path.
    """
    if query_json.get("kind") not in LAZY_PRECOMPUTE_QUERY_KINDS:
        return query_json
    if query_json.get("useWebAnalyticsPrecompute") is not True:
        return query_json
    date_range = query_json.get("dateRange") or {}
    if date_range.get("date_to"):
        return query_json
    depths = [
        (days, date_from)
        for date_from in observed_date_froms
        if (days := _exact_lookback_days(date_from)) is not None and days <= max_days
    ]
    if not depths:
        return query_json
    _, deepest = max(depths)
    return {**query_json, "dateRange": {**date_range, "date_from": deepest}}


def maybe_expand_warming_date_range(query_json: dict) -> dict:
    """Deepen a bucket-building replay's date range to WARMING_EXPANDED_DATE_FROM.

    Only date_from moves (earlier), so the built buckets are a strict superset of
    the requested range. Applies only to shapes on the precompute path: for an
    opted-out shape the replay's exact result-cache row is the whole value of
    warming it, so its range must stay faithful.
    """
    if query_json.get("kind") not in LAZY_PRECOMPUTE_QUERY_KINDS:
        return query_json
    if query_json.get("useWebAnalyticsPrecompute") is not True:
        return query_json
    date_range = query_json.get("dateRange") or {}
    if not _is_within_30_days(date_range.get("date_from")):
        return query_json
    return {**query_json, "dateRange": {**date_range, "date_from": WARMING_EXPANDED_DATE_FROM}}


# Family-level eligibility dispatch, mirroring each runner's own lazy-path
# entry points (stats_table tries three families; a shape is lazy-served iff
# any accepts). Keyed by query kind — only LAZY_PRECOMPUTE_QUERY_KINDS appear.
_LAZY_FAMILY_CHECKS: dict[str, tuple] = {
    "WebOverviewQuery": (can_use_overview_lazy_precompute,),
    "WebStatsTableQuery": (
        can_use_paths_lazy_precompute,
        can_use_frustration_lazy_precompute,
        can_use_stats_lazy_precompute,
    ),
    "WebGoalsQuery": (can_use_goals_lazy_precompute,),
    "WebVitalsPathBreakdownQuery": (can_use_vitals_paths_lazy_precompute,),
}


def _is_lazy_eligible(runner: "QueryRunner", query_json: dict) -> bool:
    family_checks = _LAZY_FAMILY_CHECKS.get(query_json.get("kind", ""), ())
    return any(check(runner) for check in family_checks)


def build_replay_runner(
    team: Team, query_json: dict, observed_date_froms: list[str]
) -> tuple[Optional["QueryRunner"], dict, bool]:
    """Build the runner for a warming replay, deepening and widening the date
    range only for shapes the lazy path will actually serve. Returns (runner,
    replay json, lazy-eligible) — the caller holds raw-path replays to a higher
    demand bar.

    The per-query opt-in does not guarantee the lazy path: shapes the gates
    reject (conversion goals, sampling, unsupported breakdowns/metrics like
    bounce rate, …) execute on the raw path, where a deepened or widened replay
    would be a scan the tenant never ran — up to MAX_PRECOMPUTE_DAYS wide,
    background load outside their request throttles, mintable up to
    MAX_SHAPES_PER_TEAM per hour, and its demand was only ever counted at the
    shallow variant. Those shapes replay with their faithful original range
    instead. Eligibility is decided by the same per-family
    `can_use_lazy_precompute` dispatch the runner uses, so this
    check and execution can't disagree. Under the warming tag the enrollment
    gate is bypassed by design — building buckets for not-yet-enrolled teams is
    the warmer's purpose — so the decision rests on the shape itself.
    """
    # The lazy candidate: deepen to the widest range the shape's demand covers,
    # then widen a sub-30d range up to the standard warm depth. Both are no-ops
    # off the lazy path, so an unchanged result means nothing to try there.
    lazy_json = maybe_expand_warming_date_range(
        deepen_to_widest_warmable_range(query_json, observed_date_froms, MAX_PRECOMPUTE_DAYS)
    )
    if lazy_json is query_json:
        runner = get_query_runner_or_none(query=query_json, team=team, limit_context=LimitContext.QUERY_ASYNC)
        if runner is None:
            return None, query_json, False
        return runner, query_json, _is_lazy_eligible(runner, query_json)

    runner = get_query_runner_or_none(query=lazy_json, team=team, limit_context=LimitContext.QUERY_ASYNC)
    if runner is None:
        return None, lazy_json, False
    if _is_lazy_eligible(runner, lazy_json):
        return runner, lazy_json, True
    # Raw path: replay the faithful original range, never the deepened/widened one.
    return (
        get_query_runner_or_none(query=query_json, team=team, limit_context=LimitContext.QUERY_ASYNC),
        query_json,
        False,
    )


def queries_to_keep_fresh(
    context: dagster.OpExecutionContext, days: int = 2, minimum_query_count: int = 2, max_shapes: int = 40000
) -> list[dict]:
    """Fleet-wide demand selection: every (team, query shape) with at least
    `minimum_query_count` runs in the window, hottest first, capped at
    `max_shapes`.

    The audience is implicit — any team with a hot shape is active on web
    analytics and benefits from warming. One batched query replaces the previous
    per-team loop, which could not scale past a handful of teams.
    """
    context.log.info(
        f"Selecting fleet-wide web analytics queries with >= {minimum_query_count} runs "
        f"in the last {days} days (cap {max_shapes} shapes)."
    )

    # Selection reads system.query_log across the whole cluster: Dagster connects
    # to offline nodes, while the user traffic we want to replay lands on other
    # replicas. (metrics_query_log_mv only looks usable — its DDL in
    # posthog/models/query_metrics/sql.py was never migrated, the table does not
    # exist in production.) Demand is grouped by the NORMALIZED shape — the query
    # JSON with the range-varying and non-shape fields stripped
    # (SHAPE_CAP_KEY_IGNORED_QUERY_FIELDS: dateRange, compareFilter, limit, …) —
    # which is the same set the precompute bucket namespace collapses to, so one
    # warmed bucket serves every date-range variant of a shape. Grouping by
    # the raw JSON instead fragmented a shape queried across many date ranges into
    # many sub-threshold entries that never cleared min-count, even though warming
    # it once would serve them all; the largest, most date-varied teams were the
    # worst hit. The representative to replay is the most-demanded variant (argMax
    # below); its range is then deepened to the widest the shape actually needs
    # (its distinct ranges come back in observed_date_froms). Demand is counted as
    # distinct query_ids so duplicated log rows for one request can't inflate it.
    # The per-shape hash is
    # cityHash64 of the group key rather than normalizedQueryHash(query), which
    # would read the full `query` SQL-text column — the largest in query_log —
    # across the whole window purely for a logging id.
    #
    # The scan spans the whole WEB_ANALYTICS_WARMING_DAYS window fleet-wide, which
    # exceeds the default max_bytes_to_read, so the cap is raised to
    # _SELECTION_MAX_BYTES_TO_READ — a finite value, not 0, so the ClickHouse
    # kill switch's overload byte cap still clamps it (min(kill_switch_cap, ours))
    # and the giant scan is refused rather than piled on during an overload. The
    # run is also bounded by max_execution_time and by the demand-selection cache
    # upstream, so this heavy scan happens on the cache TTL cadence, not every run.
    #
    # trigger/feature exclusions keep the warmer's own replays — and every other
    # background warmer — out of the demand counts, otherwise a once-warmed shape
    # would keep itself hot forever. LIKE literals are %%-escaped because
    # clickhouse_driver %-formats the query when params are passed.
    # nosemgrep: clickhouse-fstring-param-audit (interpolations are module-level constants from hardcoded tuples, not user input; everything dynamic is parameterized)
    results = sync_execute(
        f"""
        SELECT
            team_id,
            -- Representative = the shape's most-requested exact variant (its real
            -- date range, modifiers, …). Picking the mode rather than an arbitrary
            -- any() keeps a rare ineligible variant — an all-time range, a UUID
            -- join mode requested once — from being the one that gets replayed.
            argMax(query_json_raw, variant_count) AS representative_query_json,
            -- Summed across variants so date/compare variants of one lazy shape
            -- combine to clear the selection floor: one shared bucket serves them.
            sum(variant_count) AS query_count,
            -- The representative variant's OWN demand. The raw (ineligible) replay
            -- path gates on this, not the sum, so an expensive variant can't
            -- inherit a popular sibling's demand — raw replays aren't shared, so
            -- each stale hour re-runs a full live query.
            max(variant_count) AS representative_query_count,
            cityHash64(normalized_shape) AS normalized_query_hash,
            -- The distinct date ranges this shape was queried at, read from each
            -- variant's own JSON. The representative's range is arbitrary after
            -- normalization, so the warmer deepens it to the widest of these
            -- (see deepen_to_widest_warmable_range).
            groupUniqArray(JSONExtractString(query_json_raw, 'dateRange', 'date_from')) AS observed_date_froms
        FROM (
            SELECT
                team_id,
                normalized_shape,
                query_json_raw,
                uniqExact(query_id) AS variant_count
            FROM (
            SELECT
                JSONExtractInt(log_comment, 'team_id') AS team_id,
                -- The shape key: every top-level query field except the range-
                -- varying / non-shape ones the precompute namespace ignores, so
                -- date-range and compare variants of one shape group together
                -- (char(31)/char(30) are control-char separators that can't occur
                -- in JSON keys). Sorted so field order in the payload is irrelevant.
                arrayStringConcat(
                    arraySort(arrayMap(
                        kv -> concat(kv.1, char(31), kv.2),
                        arrayFilter(
                            kv -> NOT has(%(shape_ignored_fields)s, kv.1),
                            JSONExtractKeysAndValuesRaw(JSONExtractRaw(log_comment, 'query'))
                        )
                    )),
                    char(30)
                ) AS normalized_shape,
                -- aliased away from the native `query_kind` column so the PREWHERE
                -- below binds to the column (Select/Insert/…), not this JSON kind
                -- (WebOverviewQuery/…); with prefer_column_name_to_alias=0 a name
                -- collision would resolve `query_kind = 'Select'` against the alias
                -- and silently select nothing.
                JSONExtractString(log_comment, 'query', 'kind') AS web_query_kind,
                JSONExtractString(log_comment, 'query_type') AS query_type,
                JSONExtractString(log_comment, 'trigger') AS trigger,
                JSONExtractString(log_comment, 'feature') AS feature,
                JSONExtractString(log_comment, 'kind') AS request_kind,
                JSONExtractRaw(log_comment, 'query') AS query_json_raw,
                query_id
            FROM clusterAllReplicas(%(cluster)s, system.query_log)
            -- Filter the cheap native columns first so the big log_comment String
            -- is read only for surviving rows. is_initial_query alone drops roughly
            -- nine-tenths of the window (the rest are distributed subqueries), and
            -- query_kind excludes the warmer's own INSERT replays without a JSON
            -- parse — every warmable web query executes as a Select.
            PREWHERE
                type = 'QueryFinish'
                AND is_initial_query
                AND query_kind = 'Select'
            WHERE
                event_date >= toDate(now() - INTERVAL %(days)s DAY)
                AND event_time >= now() - INTERVAL %(days)s DAY
                -- cheap substring prefilter before any JSON extraction; a
                -- superset of the kind filter below, false positives re-checked
                AND log_comment LIKE '%%{WARMABLE_QUERY_KIND_PREFIX}%%'
        ) AS sub
        WHERE
            team_id != 0
            AND query_json_raw != ''
            AND startsWith(web_query_kind, %(kind_prefix)s)
            AND web_query_kind NOT IN %(unwarmable_kinds)s
            AND NOT ({_INTERNAL_QUERY_TYPE_FILTER})
            AND trigger NOT IN %(background_triggers)s
            AND feature != %(cache_warmup_feature)s
            -- Demand should reflect real product usage, not background query
            -- traffic. Temporal-kind requests (batch/scheduled workflows) run
            -- web queries across nearly every team — left in, they dominated the
            -- selection and filled the cap with shapes no dashboard reader ever
            -- loads. UI and personal-API-key traffic are kept.
            AND request_kind != %(excluded_request_kind)s
            GROUP BY
                team_id,
                normalized_shape,
                query_json_raw
        ) AS variants
        GROUP BY
            team_id,
            normalized_shape
        HAVING query_count >= %(minimum_query_count)s
        ORDER BY
            query_count DESC
        LIMIT %(max_shapes_per_team)s BY team_id
        LIMIT %(max_shapes)s
        """,
        {
            "cluster": CLICKHOUSE_CLUSTER,
            "days": days,
            "minimum_query_count": minimum_query_count,
            "max_shapes": max_shapes,
            "max_shapes_per_team": MAX_SHAPES_PER_TEAM,
            "shape_ignored_fields": sorted(SHAPE_CAP_KEY_IGNORED_QUERY_FIELDS),
            "kind_prefix": WARMABLE_QUERY_KIND_PREFIX,
            "unwarmable_kinds": UNWARMABLE_QUERY_KINDS,
            "background_triggers": tuple(BACKGROUND_WARMING_TRIGGERS | SHARED_BACKGROUND_WARMING_TRIGGERS),
            "cache_warmup_feature": Feature.CACHE_WARMUP.value,
            "excluded_request_kind": EXCLUDED_REQUEST_KIND,
        },
        settings={"max_bytes_to_read": _SELECTION_MAX_BYTES_TO_READ, "max_execution_time": 600},
    )

    return [
        {
            "team_id": result[0],
            # Faithful representative range — deepening happens in
            # build_replay_runner, gated on lazy eligibility, off the raw path.
            "query_json": json.loads(result[1]),
            "query_count": result[2],
            "representative_query_count": result[3],
            "normalized_query_hash": result[4],
            "observed_date_froms": result[5],
        }
        for result in results
    ]


# The demand selection scans terabytes of query_log fleet-wide, so its result is
# cached in Redis and shared across warming runs: the hourly warmer replays the
# cached shape list and the scan only re-runs once the cache expires
# (WEB_ANALYTICS_WARMING_SELECTION_TTL_SECONDS). This is what lets the lookback
# window grow to weeks without multiplying the scan by the warming cadence.
#
# The payload is stored in object storage rather than Redis: at the default cap
# it is already ~34 MiB uncompressed (~890 bytes per shape × max_shapes) and
# grows linearly as max_shapes is raised for coverage, which is a poor fit for a
# single Redis value. The cached blob embeds the selection parameters and a
# timestamp so a settings change or an entry older than the TTL is treated as a
# miss — object storage has no per-key expiry of its own.
#
# The vN suffix versions the selection *logic*: the cache only validates the
# settings params (days/min/max), not the query itself, so a change to the
# selection query (new filter, different grouping) would otherwise keep replaying
# a stale blob written by the old logic until its TTL expired. Bump the version
# whenever the selection query changes so the new logic takes effect on deploy.
_WARMABLE_QUERIES_STORAGE_KEY = "web_analytics/warmable_queries/v5.json.gz"


def _read_cached_warmable_queries(
    days: int, minimum_query_count: int, max_shapes: int, ttl_seconds: int
) -> Optional[list[dict]]:
    # Fail open: any storage, decode, or unexpected-payload problem is treated as
    # a miss so warming falls back to a fresh scan rather than erroring. The field
    # access stays inside the try so a decodable-but-malformed blob (wrong shape,
    # bad field type) misses rather than crashing the hourly run.
    try:
        raw = object_storage.read_bytes(_WARMABLE_QUERIES_STORAGE_KEY, missing_ok=True)
        if raw is None:
            return None
        payload = json.loads(gzip.decompress(raw))
        params_match = (payload["days"], payload["minimum_query_count"], payload["max_shapes"]) == (
            days,
            minimum_query_count,
            max_shapes,
        )
        is_fresh = time.time() - payload["generated_at"] < ttl_seconds
        if not params_match or not is_fresh:
            return None
        return payload["queries"]
    except Exception:
        logger.warning("web_analytics_warming_cache_read_failed", exc_info=True)
        return None


def _write_cached_warmable_queries(days: int, minimum_query_count: int, max_shapes: int, queries: list[dict]) -> None:
    payload = {
        "days": days,
        "minimum_query_count": minimum_query_count,
        "max_shapes": max_shapes,
        "generated_at": time.time(),
        "queries": queries,
    }
    try:
        object_storage.write(_WARMABLE_QUERIES_STORAGE_KEY, gzip.compress(json.dumps(payload).encode()))
    except Exception:
        logger.warning("web_analytics_warming_cache_write_failed", exc_info=True)


@dagster.op
def get_warmable_queries_op(context: dagster.OpExecutionContext) -> list[dict]:
    days = get_instance_setting("WEB_ANALYTICS_WARMING_DAYS")
    minimum_query_count = get_instance_setting("WEB_ANALYTICS_WARMING_MIN_QUERY_COUNT")
    max_shapes = get_instance_setting("WEB_ANALYTICS_WARMING_MAX_SHAPES")
    ttl_seconds = get_instance_setting("WEB_ANALYTICS_WARMING_SELECTION_TTL_SECONDS")

    queries = _read_cached_warmable_queries(days, minimum_query_count, max_shapes, ttl_seconds)
    from_cache = queries is not None
    if queries is None:
        queries = queries_to_keep_fresh(
            context, days=days, minimum_query_count=minimum_query_count, max_shapes=max_shapes
        )
        _write_cached_warmable_queries(days, minimum_query_count, max_shapes, queries)

    team_count = len({q["team_id"] for q in queries})

    WARMING_SHAPES_SELECTED_GAUGE.set(len(queries))
    source = "cached" if from_cache else "freshly selected"
    context.log.info(f"Warming {len(queries)} {source} hot query shapes across {team_count} teams")
    context.add_output_metadata(
        {
            "query_count": len(queries),
            "team_count": team_count,
            "cap_reached": len(queries) >= max_shapes,
            "from_cache": from_cache,
        }
    )
    return queries


# Demand bar for shapes that replay on the raw path (not lazy-eligible). The
# min-2 selection floor is safe for bucket-backed shapes but would let raw
# replays amplify a tenant's two runs into hourly background scans.
RAW_REPLAY_MIN_QUERY_COUNT = 10

# Worker threads for the warm pass. The pass is IO-bound (cache checks, CH
# reads/inserts), so a pool cuts wall time at the widened selection size. A cold
# first run is dominated by per-day bucket builds — hundreds of thousands of them
# — so this is the main throughput lever, but raising it adds load to the offline
# ClickHouse pool. Overridable via WEB_ANALYTICS_WARMING_SHARD_THREADS without
# a redeploy; the pool is fixed for the life of a pass, so a change applies when
# the next run starts. This is the fallback when the setting is unset.
WARMING_SHARD_THREADS = 6

# Fallback shard count for the sharded warm pass (see split_warmable_queries_op);
# overridable live via WEB_ANALYTICS_WARMING_SHARDS. Total ClickHouse-side
# concurrency is shards x per-shard threads.
WARMING_SHARDS = 8

# Heartbeat cadence for the warm pass. Cold bucket builds run ~1s each, so a full
# selection can take hours; without a heartbeat the op is silent start to finish
# and a long run is indistinguishable from a hung one.
WARMING_PROGRESS_LOG_INTERVAL_SECONDS = 120

# Full per-shape wall-clock (runner construction, cache lookups, and the warm
# itself) above which the shape's log line escalates to WARNING.
# Aggregate counters say a run is slow but not WHICH shapes made it slow — the
# forensic gap when diagnosing why passes overrun (deep ranges rebuilding, bucket
# identity churn re-warming old days, one team's pathological filters).
WARMING_SLOW_SHAPE_SECONDS = 15

# A ClickHouse node dying mid-pass can leave every worker thread blocked in a
# socket read that never returns: no futures complete, the heartbeat (which
# lives in the consumption loop) goes silent, and because pool threads are
# non-daemon the process cannot even exit — the run wedges indefinitely,
# mutual exclusion then blocks every subsequent scheduled tick, and the fleet
# goes stale until a human terminates the run. If nothing has completed for
# this long WHILE there is still queued work beyond the in-flight set (threads
# should be turning over constantly), the pass is presumed wedged and the
# process hard-exits so Dagster records a step failure and the next tick runs.
# A quiet tail (pending <= concurrency, e.g. one slow deep-range straggler) is
# legitimate and only logs.
WARMING_STALL_TIMEOUT_SECONDS = 1800

# A quiet tail (pending <= concurrency) gets this many consecutive stall
# windows before it is also presumed wedged: a legitimately slow straggler is
# bounded by ClickHouse-side execution timeouts at minutes, so zero completions
# among only in-flight shapes for this long has no innocent explanation.
WARMING_TAIL_STALL_WINDOWS = 3

# After cancellation/crash, how long healthy in-flight shapes get to finish
# before the process exits hard rather than hanging on a blocked thread join.
WARMING_CANCEL_GRACE_SECONDS = 60


# The warmer shares its per-user ClickHouse query budget with every other
# Dagster job (the `dagster` CH user has a hard simultaneous-query cap on the
# sessions cluster), so a co-tenant burst surfaces here as 202/AtCapacity even
# when the warmer itself is within budget. Those bursts are seconds-long;
# failing the shape defers it a whole hour. A couple of jittered retries ride
# them out, and sleeping in the worker thread throttles the pool exactly while
# the cluster is saturated. Persistent saturation still fails fast: with the
# cap sustained, each shape costs at most ~2 sleeps before reporting "failed".
WARMING_CAPACITY_RETRIES = 2
WARMING_CAPACITY_BACKOFF_RANGE_SECONDS = (5.0, 15.0)

# The shape-level staleness threshold is a fixed wall-clock delta, so shapes
# warmed together go stale together: any bulk pass (a cold drain, a deploy
# rotating cache hashes) synchronizes the fleet and every later run inherits a
# multi-hour expiry storm that monopolizes the hourly cadence until phases
# drift apart on their own. Evaluating staleness with the entry aged by a
# bounded offset warms each shape a little early — never late, so served
# freshness is untouched.
#
# The offset is seeded with (shape, last_refresh), not the shape alone: the
# warmer only samples staleness at run ticks, and with a threshold that is a
# whole number of ticks, every fixed offset below one tick collapses onto the
# same tick — a synchronized cohort would march in formation forever. Seeding
# with last_refresh keeps the offset stable between runs within a cycle (no
# flapping) but re-draws it each time the shape warms, so every cycle each
# shape independently lands one tick earlier or not — a synchronized cohort
# decays geometrically instead of persisting. Mean cost is ~30min early on a
# multi-hour cycle (~+10-15% warms), well inside the sharded pass's headroom.
WARMING_STALENESS_JITTER_MAX_SECONDS = 3600


def _staleness_jitter(normalized_query_hash: object, last_refresh: datetime) -> timedelta:
    # crc32, not hash(): str hashing is salted per process, and the offset must
    # be reproducible across runs or it re-randomizes each hour and shapes flap.
    seed = f"{normalized_query_hash}:{last_refresh.isoformat()}".encode()
    return timedelta(seconds=zlib.crc32(seed) % WARMING_STALENESS_JITTER_MAX_SECONDS)


def _team_still_exists(team_id: int) -> bool:
    # Thin DB boundary so tests can pin the answer: pool worker threads hold their
    # own connections, which can't see a TestCase's uncommitted rows.
    return Team.objects.filter(pk=team_id).exists()


class WarmQueriesConfig(dagster.Config):
    """Launchpad knobs for targeted warming runs. The hourly schedule passes no
    config, so it keeps the defaults; a manual launch can scope a run.

    The concurrent-run guard makes launches of this job mutually exclusive with
    the hourly schedule, so bound a manual backfill with `limit` — an unbounded
    cold backfill can run for hours and starve the hourly refresh the whole time.
    """

    # full: warm everything selected (schedule default). refresh: only shapes
    # already warmed once (cache entry exists) — cheap freshness pass, no cold
    # builds. backfill: only never-warmed shapes (no cache entry) — coverage
    # expansion without re-touching the warm set.
    mode: str = "full"
    # Restrict to specific teams (empty = all selected teams).
    team_ids: list[int] = []
    # Process at most this many shapes, hottest first (0 = no limit).
    limit: int = 0


def _scope_queries(config: WarmQueriesConfig, queries: list[dict]) -> tuple[str, list[dict]]:
    if config.mode not in ("full", "refresh", "backfill"):
        raise ValueError(f"Unknown warming mode {config.mode!r} (expected full, refresh, or backfill)")
    if config.team_ids:
        wanted = set(config.team_ids)
        queries = [q for q in queries if q["team_id"] in wanted]
    if config.limit > 0:
        queries = queries[: config.limit]
    return config.mode, queries


@dagster.op(retry_policy=cache_warming_retry_policy)
def warm_queries_op(context: dagster.OpExecutionContext, config: WarmQueriesConfig, queries: list[dict]) -> None:
    mode, queries = _scope_queries(config, queries)
    _warm_queries(context, mode, queries)


@dagster.op(out=dagster.DynamicOut(dict), retry_policy=cache_warming_retry_policy)
def split_warmable_queries_op(context: dagster.OpExecutionContext, config: WarmQueriesConfig, queries: list[dict]):
    """Scope the selection and fan it out into team-disjoint shards.

    Each shard becomes its own mapped op — a separate subprocess under the
    multiprocess executor, with its own GIL. HogQL compilation is CPU-bound
    Python, so threads inside one process serialize on the interpreter; real
    parallelism needs processes. Sharding by team keeps every potential
    duplicate cache key inside one shard (the dedupe set is keyed on
    (team_id, cache_key)), so no cross-process coordination is needed.
    """
    mode, queries = _scope_queries(config, queries)
    shards_setting = get_instance_setting("WEB_ANALYTICS_WARMING_SHARDS")
    # `if None` rather than `or`: an explicit 0 must clamp to the documented
    # minimum of one shard, not silently fall back to the default of eight.
    shards = min(16, max(1, WARMING_SHARDS if shards_setting is None else shards_setting))
    buckets: dict[int, list[dict]] = {}
    for query_info in queries:
        buckets.setdefault(query_info["team_id"] % shards, []).append(query_info)
    context.log.info(f"Split {len(queries)} shapes into {len(buckets)} shards (mode={mode})")
    for shard_index in sorted(buckets):
        yield dagster.DynamicOutput({"mode": mode, "queries": buckets[shard_index]}, mapping_key=f"shard_{shard_index}")


@dagster.op(retry_policy=cache_warming_retry_policy)
def warm_queries_shard_op(context: dagster.OpExecutionContext, shard: dict) -> None:
    _warm_queries(context, shard["mode"], shard["queries"])


def _warm_queries(context: dagster.OpExecutionContext, mode: str, queries: list[dict]) -> None:
    team_ids = {q["team_id"] for q in queries}
    teams: dict[int, Team] = {t.pk: t for t in Team.objects.filter(pk__in=team_ids)}
    missing_teams = team_ids - teams.keys()
    if missing_teams:
        context.log.warning(f"{len(missing_teams)} teams not found, skipping their shapes")

    # Selection groups by raw JSON text, so differently-encoded rows can
    # normalize to one cache key; first worker to claim it warms, the rest skip.
    seen_cache_keys: set[tuple[int, str]] = set()
    seen_lock = threading.Lock()

    def _warm_one(query_info: dict) -> str:
        # One line per shape, every outcome — deliberately verbose (~a line per
        # selected shape per run). Warm passes have repeatedly been slow for
        # reasons aggregate counters couldn't attribute (bucket identity churn,
        # deep-range rebuilds); per-shape logs make the composition greppable.
        started = time.monotonic()
        outcome = _warm_one_inner(query_info)
        seconds = round(time.monotonic() - started, 2)
        try:
            query_json = query_info.get("query_json") or {}
            date_range = query_json.get("dateRange") if isinstance(query_json, dict) else None
            log = logger.warning if seconds >= WARMING_SLOW_SHAPE_SECONDS else logger.info
            log(
                "web_analytics_warming_shape",
                outcome=outcome,
                seconds=seconds,
                team_id=query_info.get("team_id"),
                kind=query_json.get("kind") if isinstance(query_json, dict) else None,
                breakdown_by=query_json.get("breakdownBy") if isinstance(query_json, dict) else None,
                date_from=date_range.get("date_from") if isinstance(date_range, dict) else None,
                replay_date_from=query_info.get("_replay_date_from"),
                was_cold=query_info.get("_was_cold"),
                capacity_retries=query_info.get("_capacity_retries"),
                normalized_query_hash=query_info.get("normalized_query_hash"),
            )
        except Exception:
            # Observability must never abort the pass: a malformed shape already
            # produced its outcome above; a logging error is not a warm failure.
            logger.exception("web_analytics_warming_shape_log_failed")
        return outcome

    def _warm_one_inner(query_info: dict) -> str:
        team = teams.get(query_info["team_id"])
        if team is None:
            return "team_missing"
        query_json = query_info["query_json"]

        try:
            # Query tags are thread-local, so they must be set here in the worker
            # — not in the op thread — or the replay loses its background-warming
            # identity, which both the lazy gate's rollout bypass and the
            # selection's self-feedback exclusion key on (the eager warmer's
            # missing-tags warnings came from exactly this). Reset first: pool
            # threads are reused, and tags a previous shape's runner added
            # (client_query_id, cache key, …) would otherwise leak into this one.
            reset_query_tags()
            tag_queries(team_id=team.pk, trigger="webAnalyticsQueryWarming", feature=Feature.CACHE_WARMUP)

            query_json = maybe_opt_into_lazy_precompute(query_json)

            # None only for kinds without a get_query_runner branch — the backstop
            # for runnerless kinds the selection doesn't know to exclude yet.
            # Validation errors on supported kinds still raise into the failure path.
            runner, query_json, lazy_eligible = build_replay_runner(
                team, query_json, query_info.get("observed_date_froms", [])
            )
            # Stashed for the wrapper's per-shape log: the REPLAYED range (after
            # widening/deepening) is what actually executes, and it differs from
            # the selected shape's range in exactly the cases worth debugging.
            query_info["_replay_date_from"] = (query_json.get("dateRange") or {}).get("date_from")
            if runner is None:
                WARMING_QUERIES_COUNTER.labels(outcome="unsupported").inc()
                return "unsupported"

            # Raw-path replays keep the pre-widening demand bar: a lazy-eligible
            # shape amortizes into shared immutable buckets (steady-state cost is
            # one cheap today-bucket refresh), but an ineligible shape replays as
            # a full live query every stale hour — with the min-2 floor a tenant
            # could mint MAX_SHAPES_PER_TEAM such shapes from two runs each and
            # have the warmer amplify them outside request throttles. Gate on the
            # representative variant's own demand, not the shape-wide sum: raw
            # replays aren't shared across variants, so a rarely-run expensive
            # variant must not inherit a popular sibling's count.
            if not lazy_eligible and query_info.get("representative_query_count", 0) < RAW_REPLAY_MIN_QUERY_COUNT:
                WARMING_QUERIES_COUNTER.labels(outcome="skipped_raw_low_demand").inc()
                return "skipped_raw_low_demand"

            cache_key = runner.get_cache_key()
            with seen_lock:
                if (team.pk, cache_key) in seen_cache_keys:
                    WARMING_QUERIES_COUNTER.labels(outcome="skipped_duplicate").inc()
                    return "skipped_duplicate"
                seen_cache_keys.add((team.pk, cache_key))

            entry = QueryCache(team_id=team.pk, cache_key=cache_key).lookup().entry
            query_info["_was_cold"] = entry is None

            # The cache entry doubles as the warm/cold discriminator: a shape
            # warmed at least once has one (possibly stale); a never-warmed shape
            # doesn't. refresh keeps the warm set fresh without paying for cold
            # builds; backfill expands coverage without re-touching the warm set.
            if mode == "refresh" and entry is None:
                WARMING_QUERIES_COUNTER.labels(outcome="skipped_cold").inc()
                return "skipped_cold"
            if mode == "backfill" and entry is not None:
                WARMING_QUERIES_COUNTER.labels(outcome="skipped_already_warmed").inc()
                return "skipped_already_warmed"

            cached_data = entry.as_full_response() if entry else None

            if cached_data is not None:
                last_refresh = parse_datetime(cached_data["last_refresh"])
                aged_refresh = (
                    last_refresh - _staleness_jitter(query_info["normalized_query_hash"], last_refresh)
                    if last_refresh
                    else None
                )
                if not runner._is_stale(aged_refresh):
                    WARMING_QUERIES_COUNTER.labels(outcome="skipped_fresh").inc()
                    return "skipped_fresh"

            # TODO: We shouldn't try to run a query if it failed last run
            # Blocking-always, not the stale-checking default: run() re-checks
            # staleness internally against the entry's true last_refresh, so a
            # jitter-early warm would silently return the still-fresh cached
            # response and the early refresh — the whole point of the jitter —
            # would never happen. The warmer has already made the staleness
            # decision above; run() must not second-guess it.
            for attempt in range(WARMING_CAPACITY_RETRIES + 1):
                try:
                    runner.run(
                        execution_mode=ExecutionMode.CALCULATE_BLOCKING_ALWAYS,
                        analytics_props={"source": EventSource.CACHE_WARMING},
                    )
                    break
                except ClickHouseAtCapacity:
                    query_info["_capacity_retries"] = attempt + 1
                    if attempt == WARMING_CAPACITY_RETRIES:
                        raise
                    time.sleep(random.uniform(*WARMING_CAPACITY_BACKOFF_RANGE_SECONDS))
            WARMING_QUERIES_COUNTER.labels(outcome="warmed").inc()
            return "warmed"
        except Exception as e:
            # A team deleted after the teams dict was loaded (the 14-day demand
            # window churns teams out) surfaces as a DoesNotExist from
            # get_cache_key: it reads a team extension via get-or-create, whose
            # create hits the team foreign key and leaves the lookup raising the
            # extension's DoesNotExist. That's not a warming failure — skip it
            # quietly rather than logging a traceback and firing error tracking
            # for every churned team. Verified against the DB rather than keyed on
            # the exception type alone: other models raise DoesNotExist too (a
            # cohort filter whose cohort was deleted mid-window), and for a live
            # team those are genuine failures that must still report.
            if isinstance(e, ObjectDoesNotExist) and not _team_still_exists(team.pk):
                return "team_missing"
            # Module logger, not context.log: Dagster's log manager isn't
            # guaranteed thread-safe, and workers fail concurrently.
            logger.exception(
                "web_analytics_warming_shape_failed",
                team_id=team.pk,
                normalized_query_hash=query_info["normalized_query_hash"],
            )
            capture_exception(e)
            WARMING_QUERIES_COUNTER.labels(outcome="failed").inc()
            return "failed"
        finally:
            # Pool threads hold their own Django connections; drop expired ones so
            # a long pass doesn't accumulate stale connections per thread.
            close_old_connections()

    # Clamped: a non-positive value would abort every run at pool construction and
    # an oversized one can exhaust process threads. The pool is fixed for the life
    # of the pass, so a settings change applies when the next run starts.
    concurrency_setting = get_instance_setting("WEB_ANALYTICS_WARMING_SHARD_THREADS")
    concurrency = min(64, max(1, WARMING_SHARD_THREADS if concurrency_setting is None else concurrency_setting))
    outcomes: dict[str, int] = {}
    total = len(queries)
    processed = 0
    started_at = time.monotonic()
    last_log_at = started_at
    context.log.info(f"Warming {total} shapes across {len(teams)} teams (mode={mode}, concurrency={concurrency})")
    # No `with` block: the context manager's exit calls shutdown(wait=True),
    # which joins worker threads — on the exceptional paths below that would
    # re-block on the very wedged threads this code exists to escape.
    pool = ThreadPoolExecutor(max_workers=concurrency)
    pending: set = set()
    try:
        # Futures are consumed by completion, not input order: with pool.map one
        # slow early shape would block this loop — and the heartbeat — while later
        # workers finish thousands of shapes. Consuming on the op thread also keeps
        # context.log here safe, unlike the worker-thread logging inside _warm_one.
        futures = [pool.submit(_warm_one, query_info) for query_info in queries]
        pending = set(futures)
        empty_waits = 0
        while pending:
            done, pending = wait(pending, timeout=WARMING_STALL_TIMEOUT_SECONDS, return_when=FIRST_COMPLETED)
            if not done:
                empty_waits += 1
                # Queued work beyond the in-flight set means threads should be
                # turning over constantly — one silent window is definitive. A
                # quiet tail gets WARMING_TAIL_STALL_WINDOWS before the same
                # verdict, so a single slow straggler isn't killed but a fully
                # wedged tail cannot spin forever.
                if len(pending) > concurrency or empty_waits >= WARMING_TAIL_STALL_WINDOWS:
                    context.log.error(
                        f"No shape completed in {empty_waits * WARMING_STALL_TIMEOUT_SECONDS}s with {len(pending)} "
                        f"shapes pending — presuming worker threads wedged on dead connections; exiting so the "
                        f"step fails and the next scheduled run takes over"
                    )
                    pool.shutdown(wait=False, cancel_futures=True)
                    # Blocked pool threads are non-daemon: a raise would still hang
                    # at interpreter shutdown joining them. Hard exit is the only
                    # way out of a wedged process; Dagster records a step failure.
                    os._exit(1)
                context.log.warning(
                    f"No shape completed in {WARMING_STALL_TIMEOUT_SECONDS}s with only {len(pending)} in flight "
                    f"— slow tail (window {empty_waits}/{WARMING_TAIL_STALL_WINDOWS}), still waiting"
                )
                continue
            empty_waits = 0
            for future in done:
                outcome = future.result()
                outcomes[outcome] = outcomes.get(outcome, 0) + 1
                processed += 1
            now = time.monotonic()
            if now - last_log_at >= WARMING_PROGRESS_LOG_INTERVAL_SECONDS:
                elapsed = now - started_at
                rate = processed / elapsed
                eta_min = (total - processed) / rate / 60 if rate > 0 else 0
                breakdown = ", ".join(f"{k}={v}" for k, v in sorted(outcomes.items()))
                context.log.info(
                    f"Warming progress: {processed}/{total} ({100 * processed // total}%) "
                    f"at {rate:.0f}/s, ETA ~{eta_min:.0f}m — {breakdown}"
                )
                last_log_at = now
        pool.shutdown(wait=False)
    except BaseException:
        # Cancellation or a crash must not drain the queued backlog (observed as
        # a cancelled run that kept warming for hours), and must not block on a
        # wedged in-flight thread either. Cancel the queue, give healthy
        # in-flight shapes a bounded grace to finish, then exit hard if any
        # remain — re-raising with blocked threads alive would just hang again
        # at the interpreter's exit join.
        pool.shutdown(wait=False, cancel_futures=True)
        if pending:
            _, still_pending = wait(pending, timeout=WARMING_CANCEL_GRACE_SECONDS)
            if still_pending:
                # Not log.exception: the interesting fact is the wedged threads,
                # not the (expected) cancellation traceback.
                context.log.error(  # noqa: TRY400
                    f"{len(still_pending)} in-flight shapes still running {WARMING_CANCEL_GRACE_SECONDS}s "
                    f"after cancellation — exiting hard instead of hanging on the thread join"
                )
                os._exit(1)
        raise

    queries_warmed = outcomes.get("warmed", 0)
    queries_skipped = outcomes.get("skipped_fresh", 0)
    queries_failed = outcomes.get("failed", 0)
    queries_unsupported = outcomes.get("unsupported", 0)

    final_breakdown = ", ".join(f"{k}={v}" for k, v in sorted(outcomes.items()))
    context.log.info(
        f"Warmed {queries_warmed} queries in {(time.monotonic() - started_at) / 60:.1f}m "
        f"(mode={mode}: {final_breakdown})"
    )
    context.add_output_metadata(
        {
            "queries_warmed": queries_warmed,
            "queries_skipped": queries_skipped,
            "queries_skipped_duplicate": outcomes.get("skipped_duplicate", 0),
            "queries_skipped_raw_low_demand": outcomes.get("skipped_raw_low_demand", 0),
            "queries_skipped_cold": outcomes.get("skipped_cold", 0),
            "queries_skipped_already_warmed": outcomes.get("skipped_already_warmed", 0),
            "teams_missing": outcomes.get("team_missing", 0),
            "queries_failed": queries_failed,
            "queries_unsupported": queries_unsupported,
            "concurrency": concurrency,
            "mode": mode,
        }
    )


@dagster.op
def report_warming_plan_op(context: dagster.OpExecutionContext, queries: list[dict]) -> None:
    """Dry-run reporter: summarize what the warmer WOULD warm — team count, total
    query shapes, and the per-team distribution — without running (or
    precomputing) anything.

    Reuses the real selection op, so the counts reflect exactly what a live run
    at the current settings would touch.
    """
    shapes_per_team: dict[int, int] = {}
    for q in queries:
        shapes_per_team[q["team_id"]] = shapes_per_team.get(q["team_id"], 0) + 1
    per_team = sorted(shapes_per_team.items(), key=lambda x: -x[1])
    shape_counts = [c for _, c in per_team]
    total_underlying_requests = sum(q["query_count"] for q in queries)
    median_shapes = statistics.median(shape_counts) if shape_counts else 0

    context.log.info(
        f"DRY RUN — would warm {len(queries)} query shapes across {len(per_team)} teams "
        f"(~{total_underlying_requests} underlying requests over the warming window). "
        f"Per-team shapes: max={shape_counts[0] if shape_counts else 0}, median={median_shapes}. "
        f"Top teams by shape count: {per_team[:10]}"
    )
    context.add_output_metadata(
        {
            "dry_run": True,
            "team_count": len(per_team),
            "total_query_shapes_to_warm": len(queries),
            "total_underlying_requests": total_underlying_requests,
            "max_shapes_per_team": shape_counts[0] if shape_counts else 0,
            "median_shapes_per_team": median_shapes,
            "top_10_teams_by_shape_count": str(per_team[:10]),
        }
    )


@dagster.job(
    description="Warms web analytics query cache and precompute buckets for frequently-run queries fleet-wide",
    tags={
        "owner": JobOwners.TEAM_WEB_ANALYTICS.value,
        "dagster/web_analytics_cache_warming": "web_analytics_cache_warming",
        # The agent default is 2 CPUs / 8Gi (charts: argocd/dagster/values). The
        # sharded pass runs one subprocess per shard, each compiling HogQL on its
        # own core, so the run pod needs CPU for the shards and memory for that
        # many Django interpreters. Capped at 6 CPUs: the dagster nodepool runs
        # 8-core nodes with ~7.9 allocatable, so an 8-CPU request never schedules.
        "dagster-k8s/config": {
            "container_config": {
                "resources": {
                    "requests": {"cpu": "6000m", "memory": "12Gi"},
                    "limits": {"memory": "12Gi"},
                }
            }
        },
    },
)
def web_analytics_cache_warming_job():
    queries = get_warmable_queries_op()
    # Aliased so the config path stays ops.warm_queries_op.config — the split op
    # takes the same WarmQueriesConfig, so saved Launchpad configs written for
    # the pre-sharding single op keep binding unchanged.
    split_warmable_queries_op.alias("warm_queries_op")(queries).map(warm_queries_shard_op)


@dagster.job(
    description="Dry run: report how many web analytics query shapes cache warming would warm, without warming",
    tags={
        "owner": JobOwners.TEAM_WEB_ANALYTICS.value,
        "dagster/web_analytics_cache_warming": "web_analytics_cache_warming_dry_run",
    },
)
def web_analytics_cache_warming_dry_run_job():
    queries = get_warmable_queries_op()
    report_warming_plan_op(queries)


@dagster.schedule(
    cron_schedule="0 * * * *",
    job=web_analytics_cache_warming_job,
    execution_timezone="UTC",
    tags={"owner": JobOwners.TEAM_WEB_ANALYTICS.value},
)
def web_analytics_cache_warming_schedule(context: dagster.ScheduleEvaluationContext):
    skip_reason = check_for_concurrent_runs(context)
    if skip_reason:
        return skip_reason

    return dagster.RunRequest()
