import re
import gzip
import json
import time
import threading
import statistics
from concurrent.futures import ThreadPoolExecutor
from typing import TYPE_CHECKING, Optional

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
from posthog.exceptions_capture import capture_exception
from posthog.hogql_queries.query_cache import DjangoCacheQueryCacheManager
from posthog.hogql_queries.query_runner import get_query_runner_or_none
from posthog.models import Team
from posthog.models.instance_setting import get_instance_setting
from posthog.settings import CLICKHOUSE_CLUSTER
from posthog.storage import object_storage

from products.analytics_platform.backend.lazy_computation.stale_policy import SHARED_BACKGROUND_WARMING_TRIGGERS
from products.web_analytics.backend.hogql_queries.web_goals_lazy_precompute import (
    can_use_lazy_precompute as can_use_goals_lazy_precompute,
)
from products.web_analytics.backend.hogql_queries.web_lazy_precompute_common import BACKGROUND_WARMING_TRIGGERS
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
    ["outcome"],  # warmed | skipped_fresh | skipped_duplicate | skipped_raw_low_demand | failed | unsupported
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

# Relative date_from presets that are always narrower than 30 days. -Nh/-Nd/-Nw
# forms are matched by pattern and compared in days; absolute dates and wider
# presets (mStart, all, yStart, -90d, …) are left untouched. Months/years are
# deliberately unmatched: -1m can span 31 days, so expanding it would narrow it.
_SUB_30D_DATE_FROM_PRESETS = frozenset({"dStart", "-1dStart", "wStart", "-1wStart"})
_SUB_30D_DATE_FROM_RE = re.compile(r"^-(\d+)([hdw])$")
_HOURS_PER_DAY = 24
_DAYS_PER_WEEK = 7


def _is_within_30_days(date_from: str | None) -> bool:
    if not date_from:
        return True  # unset falls back to the -7d default
    if date_from in _SUB_30D_DATE_FROM_PRESETS:
        return True
    match = _SUB_30D_DATE_FROM_RE.match(date_from)
    if not match:
        return False
    value, unit = int(match.group(1)), match.group(2)
    if unit == "h":
        return value < 30 * _HOURS_PER_DAY
    if unit == "w":
        return value * _DAYS_PER_WEEK < 30
    return value < 30


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


def build_replay_runner(team: Team, query_json: dict) -> tuple[Optional["QueryRunner"], dict, bool]:
    """Build the runner for a warming replay, widening the date range only for
    shapes the lazy path will actually serve. Returns (runner, replay json,
    lazy-eligible) — the caller holds raw-path replays to a higher demand bar.

    The per-query opt-in does not guarantee the lazy path: shapes the gates
    reject (conversion goals, sampling, unsupported breakdowns/metrics like
    bounce rate, …) execute on the raw path, where a widened replay would be a
    30-day scan the tenant never ran — background load outside their request
    throttles, mintable up to MAX_SHAPES_PER_TEAM per hour. Those shapes replay
    with their faithful original range instead. Eligibility is decided by the
    same per-family `can_use_lazy_precompute` dispatch the runner uses, so this
    check and execution can't disagree. Under the warming tag the enrollment
    gate is bypassed by design — building buckets for not-yet-enrolled teams is
    the warmer's purpose — so the decision rests on the shape itself.
    """
    expanded_json = maybe_expand_warming_date_range(query_json)
    if expanded_json is query_json:
        runner = get_query_runner_or_none(query=query_json, team=team, limit_context=LimitContext.QUERY_ASYNC)
        if runner is None:
            return None, query_json, False
        return runner, query_json, _is_lazy_eligible(runner, query_json)

    runner = get_query_runner_or_none(query=expanded_json, team=team, limit_context=LimitContext.QUERY_ASYNC)
    if runner is None:
        return None, expanded_json, False
    if _is_lazy_eligible(runner, expanded_json):
        return runner, expanded_json, True
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
    # exist in production.) Grouping by the query JSON alone collapses strategy
    # variants of one shape into one replay, and demand is counted as distinct
    # query_ids so duplicated log rows for one request can't inflate it. The
    # per-shape hash is derived from the JSON we already read out of log_comment
    # (cityHash64 of the group key) rather than normalizedQueryHash(query): the
    # latter reads the full `query` SQL-text column — the largest column in
    # query_log — across the whole window purely for a logging id, which over a
    # multi-day scan dominates the read cost.
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
            query_json_raw,
            uniqExact(query_id) AS query_count,
            cityHash64(query_json_raw) AS normalized_query_hash
        FROM (
            SELECT
                JSONExtractInt(log_comment, 'team_id') AS team_id,
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
            query_json_raw
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
            "query_json": json.loads(result[1]),
            "query_count": result[2],
            "normalized_query_hash": result[3],
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
_WARMABLE_QUERIES_STORAGE_KEY = "web_analytics/warmable_queries/v2.json.gz"


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
# reads/inserts), so a small pool cuts wall time ~8x at the widened selection
# size; kept well under the OFFLINE per-user query-slot budget so a build wave
# can't starve other traffic (the same slot pool the inline-build saturation
# incidents exhausted).
WARMING_SHAPE_CONCURRENCY = 8


@dagster.op(retry_policy=cache_warming_retry_policy)
def warm_queries_op(context: dagster.OpExecutionContext, queries: list[dict]) -> None:
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
            runner, query_json, lazy_eligible = build_replay_runner(team, query_json)
            if runner is None:
                WARMING_QUERIES_COUNTER.labels(outcome="unsupported").inc()
                return "unsupported"

            # Raw-path replays keep the pre-widening demand bar: a lazy-eligible
            # shape amortizes into shared immutable buckets (steady-state cost is
            # one cheap today-bucket refresh), but an ineligible shape replays as
            # a full live query every stale hour — with the min-2 floor a tenant
            # could mint MAX_SHAPES_PER_TEAM such shapes from two runs each and
            # have the warmer amplify them outside request throttles.
            if not lazy_eligible and query_info.get("query_count", 0) < RAW_REPLAY_MIN_QUERY_COUNT:
                WARMING_QUERIES_COUNTER.labels(outcome="skipped_raw_low_demand").inc()
                return "skipped_raw_low_demand"

            cache_key = runner.get_cache_key()
            with seen_lock:
                if (team.pk, cache_key) in seen_cache_keys:
                    WARMING_QUERIES_COUNTER.labels(outcome="skipped_duplicate").inc()
                    return "skipped_duplicate"
                seen_cache_keys.add((team.pk, cache_key))

            cache_manager = DjangoCacheQueryCacheManager(team_id=team.pk, cache_key=cache_key)
            cached_data = cache_manager.get_cache_data()

            if cached_data is not None:
                last_refresh = parse_datetime(cached_data["last_refresh"])
                if not runner._is_stale(last_refresh):
                    WARMING_QUERIES_COUNTER.labels(outcome="skipped_fresh").inc()
                    return "skipped_fresh"

            # TODO: We shouldn't try to run a query if it failed last run
            runner.run(analytics_props={"source": EventSource.CACHE_WARMING})
            WARMING_QUERIES_COUNTER.labels(outcome="warmed").inc()
            return "warmed"
        except Exception as e:
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

    outcomes: dict[str, int] = {}
    with ThreadPoolExecutor(max_workers=WARMING_SHAPE_CONCURRENCY) as pool:
        for outcome in pool.map(_warm_one, queries):
            outcomes[outcome] = outcomes.get(outcome, 0) + 1

    queries_warmed = outcomes.get("warmed", 0)
    queries_skipped = outcomes.get("skipped_fresh", 0)
    queries_failed = outcomes.get("failed", 0)
    queries_unsupported = outcomes.get("unsupported", 0)

    context.log.info(
        f"Warmed {queries_warmed} queries ({queries_skipped} already fresh, "
        f"{queries_failed} failed, {queries_unsupported} unsupported kinds)"
    )
    context.add_output_metadata(
        {
            "queries_warmed": queries_warmed,
            "queries_skipped": queries_skipped,
            "queries_failed": queries_failed,
            "queries_unsupported": queries_unsupported,
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
    },
)
def web_analytics_cache_warming_job():
    queries = get_warmable_queries_op()
    warm_queries_op(queries)


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
