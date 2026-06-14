"""Eager web analytics precompute — hourly baseline warming.

A single Dagster job that pre-warms the lazy precompute cache for the
Web analytics dashboard's main tile matrix over the trailing 28 days,
for every team in the `WEB_ANALYTICS_LAZY_PRECOMPUTE_TEAM_IDS` setting.

The job is intentionally thin: it enumerates the dashboard's query families
and dispatches each through `get_query_runner(...).run(...)` in force-refresh
mode (`ExecutionMode.CALCULATE_BLOCKING_ALWAYS`). The runner routes through
its family's lazy precompute path, which already knows what's stale and
INSERTs only what's missing. This DAG is the *trigger*; the runner is the
source of truth for freshness.

Force-refresh is used deliberately. The DEFAULT execution mode gates on the
HogQL query result cache (6h staleness), which is the wrong clock for a
precompute warmer whose buckets expire on a much shorter TTL (15min for
today's bucket) — it would skip tiles whose Redis result is still "fresh"
while the precompute they feed has gone cold. Force-refresh always recomputes,
so every tick re-enters the precompute path. Crucially it goes through `run()`
(not a bare `calculate()`), so the warm stays inside the same rate-limit and
concurrency wrappers (`_call_with_rate_limits`) as user traffic — the warmer
must not pile unthrottled ClickHouse work on top of a saturated cluster. It
also refreshes the (no-user) result-cache entry as a side effect, which is
harmless; the user-facing replay warming is `cache_warming.py`'s job.

Why this exists
---------------
The lazy precompute path caches per-day buckets in `web_*_preaggregated`
tables with a 2h TTL. For high-traffic teams the dashboard's main tiles
are requested constantly — there is no reason to compute them reactively.
Running the same query set ahead of every reasonable visit keeps the
cache perpetually warm, so user requests turn into pure reads.

Audience
--------
The audience is the `WEB_ANALYTICS_LAZY_PRECOMPUTE_TEAM_IDS` env-var
setting (defaults to the Cloud dogfooding team on Cloud, empty elsewhere).
The runtime read-path gate (`is_precompute_enabled_for_team`) consults the
*same* setting to bypass the org rollout flag, so warmer and reader read
one source of truth and cannot drift. Enrolling or removing a team is a
deploy-time change to the env var (Django + Dagster pods), not
runtime-overridable.

The job is a no-op on self-hosted instances (`is_cloud()` returns False)
since the lazy precompute infrastructure is Cloud-only.

This job is complementary to `cache_warming.py`, which replays whatever
queries users actually ran. The eager job covers the fixed UI matrix;
the replay covers the long tail (custom hosts, custom filters, etc.).
"""

import time

from django.conf import settings

import dagster
import structlog
from prometheus_client import Counter

from posthog.schema import WebStatsBreakdown

from posthog.hogql.constants import LimitContext

from posthog.clickhouse.query_tagging import Feature, Product, tag_queries
from posthog.cloud_utils import is_cloud
from posthog.dags.common import JobOwners
from posthog.event_usage import EventSource
from posthog.hogql_queries.query_runner import ExecutionMode, get_query_runner
from posthog.models import Team

from products.web_analytics.backend.hogql_queries.web_lazy_precompute_common import is_precompute_enabled_for_team
from products.web_analytics.dags.web_preaggregated_utils import check_for_concurrent_runs

logger = structlog.get_logger(__name__)


# Single warming window: the trailing 28 days. The lazy precompute path
# stores per-day buckets, so a 28-day warm naturally serves any user
# request for a sub-window (today, last 7d, etc.) via the lazy CH cache.
BASELINE_WINDOW_DAYS = 28


# The set of `WebStatsBreakdown` values rendered as tiles in the Web
# analytics dashboard (see `frontend/src/scenes/web-analytics/webAnalyticsLogic.tsx`).
# `FrustrationMetrics` is treated as a regular breakdown — the dashboard
# renders it via the same `WebStatsTableQuery` shape.
BASELINE_BREAKDOWNS: tuple[WebStatsBreakdown, ...] = (
    WebStatsBreakdown.PAGE,
    WebStatsBreakdown.INITIAL_PAGE,
    WebStatsBreakdown.EXIT_PAGE,
    # SCREEN_NAME is deliberately excluded. It reads `$screen_name`, a
    # mobile-only ($screen) property that is empty for web teams, and there is
    # no precompute family for it — warming it only ever ran a raw query that
    # populated nothing. It stays available as an on-demand breakdown.
    WebStatsBreakdown.INITIAL_CHANNEL_TYPE,
    WebStatsBreakdown.INITIAL_REFERRING_DOMAIN,
    # INITIAL_REFERRING_URL is deliberately excluded. Unlike its domain
    # sibling (which reads the aggregated `session.$entry_referring_domain`
    # column), the full-URL breakdown reads the un-materialized event
    # property `$session_entry_referrer` — there is no sessions-table column
    # for the full referrer URL. On high-volume teams that JSONExtract scans
    # the whole `properties` blob and OOMs the per-day insert, then falls
    # back to a raw query that times out at 60s. The breakdown sees
    # negligible real usage, so warming it is pure wasted compute. It stays
    # available as an on-demand breakdown.
    WebStatsBreakdown.INITIAL_UTM_SOURCE,
    WebStatsBreakdown.INITIAL_UTM_MEDIUM,
    WebStatsBreakdown.INITIAL_UTM_CAMPAIGN,
    WebStatsBreakdown.INITIAL_UTM_CONTENT,
    WebStatsBreakdown.INITIAL_UTM_TERM,
    WebStatsBreakdown.INITIAL_UTM_SOURCE_MEDIUM_CAMPAIGN,
    WebStatsBreakdown.BROWSER,
    WebStatsBreakdown.OS,
    WebStatsBreakdown.VIEWPORT,
    WebStatsBreakdown.DEVICE_TYPE,
    WebStatsBreakdown.COUNTRY,
    WebStatsBreakdown.REGION,
    WebStatsBreakdown.CITY,
    WebStatsBreakdown.LANGUAGE,
    WebStatsBreakdown.TIMEZONE,
    WebStatsBreakdown.FRUSTRATION_METRICS,
)


EAGER_PRECOMPUTE_BASELINE_WARMED = Counter(
    "web_analytics_eager_precompute_baseline_warmed_total",
    "Total baseline queries warmed by the eager web analytics precompute job, labeled by query kind.",
    ["query_kind"],
)
EAGER_PRECOMPUTE_BASELINE_FAILED = Counter(
    "web_analytics_eager_precompute_baseline_failed_total",
    "Total baseline queries that failed during eager web analytics warming, labeled by query kind and exception type.",
    ["query_kind", "error_type"],
)
EAGER_PRECOMPUTE_NOT_LAZY_ELIGIBLE = Counter(
    "web_analytics_eager_precompute_not_lazy_eligible_total",
    "Teams skipped by the eager warmer because they are not lazy-precompute eligible "
    "(the gate would route every tile through the raw path).",
)
EAGER_PRECOMPUTE_BASELINE_NOT_PRECOMPUTED = Counter(
    "web_analytics_eager_precompute_baseline_not_precomputed_total",
    "Baseline queries that ran but did NOT resolve to a precompute read (fell through "
    "to raw) — the precompute the warmer should keep fresh is stale, missing, or the "
    "breakdown isn't precomputable. Labeled by query kind.",
    ["query_kind"],
)


def _resolve_eager_audience() -> tuple[list[int], str, dict]:
    """Resolve the audience and return a structured trace of which gate
    fired. Returns `(team_ids, gate_reason, diagnostics)`.

    `gate_reason` is one of: `not_cloud`, `no_teams_configured`, `ok`.
    """
    if not is_cloud():
        return [], "not_cloud", {}

    team_ids = list(settings.WEB_ANALYTICS_LAZY_PRECOMPUTE_TEAM_IDS)
    diag = {"teams_configured": len(team_ids)}
    if not team_ids:
        return [], "no_teams_configured", diag
    return team_ids, "ok", diag


def _warm_baseline_for_team(context: dagster.OpExecutionContext, team: Team) -> tuple[int, int]:
    """Run the full tile matrix for one team. Returns (warmed, failed).

    The matrix mirrors the Web analytics dashboard's main tiles — overview,
    goals, vitals path breakdown, and one `WebStatsTableQuery` per
    breakdown in `BASELINE_BREAKDOWNS`. Each payload is handed to
    `get_query_runner(...).run(...)`, which dispatches into the family's
    lazy precompute path; the runner — not this DAG — decides what's
    stale and inserts only what's missing.

    `useWebAnalyticsPrecompute=True` is required — without it the lazy
    path rejects the query via `PerQueryOptInNotSet` and the warmer
    silently falls back to legacy compute.

    Failures per query are caught so one broken breakdown doesn't poison
    the rest of the team's matrix or the rest of the run.
    """
    common = {
        "dateRange": {"date_from": f"-{BASELINE_WINDOW_DAYS}d"},
        "properties": [],
        "filterTestAccounts": True,
        "useWebAnalyticsPrecompute": True,
    }
    queries: list[dict] = [
        {"kind": "WebOverviewQuery", **common},
        {"kind": "WebGoalsQuery", "limit": 10, **common},
        # Vitals path-breakdown lazy precompute keys its cache on `doPathCleaning`
        # (see `web_vitals_paths_lazy_precompute._build_placeholders`). The
        # dashboard defaults this to True (the team's `isPathCleaningEnabled`
        # selector). Warming with True matches the dashboard's request.
        {"kind": "WebVitalsPathBreakdownQuery", "doPathCleaning": True, **common},
    ]
    for breakdown in BASELINE_BREAKDOWNS:
        query: dict = {"kind": "WebStatsTableQuery", "breakdownBy": breakdown.value, "limit": 10, **common}
        # PAGE and INITIAL_PAGE route through `web_stats_paths_lazy_precompute`,
        # which gates on `includeBounceRate=True` (the dashboard's Paths and
        # Entry-paths tiles enable it). Without this flag the warmer falls
        # through to the raw stats query and the paths preagg table stays cold.
        if breakdown in (WebStatsBreakdown.PAGE, WebStatsBreakdown.INITIAL_PAGE):
            query["includeBounceRate"] = True
        # EXIT_PAGE is served by the simple precompute, which bakes the cleaned-or-raw
        # path into the stored breakdown value and the job hash (unlike PAGE/INITIAL_PAGE,
        # whose paths precompute stores raw paths and cleans at read time). The End-paths
        # tile sends `doPathCleaning=isPathCleaningEnabled` (true for teams with cleaning
        # rules), so without this the warmer fills the raw variant while the dashboard
        # reads the cleaned one and misses. True is a no-op for teams without cleaning
        # rules (`apply_path_cleaning` returns the bare expression → identical hash).
        if breakdown == WebStatsBreakdown.EXIT_PAGE:
            query["doPathCleaning"] = True
        queries.append(query)

    warmed = 0
    failed = 0
    total = len(queries)
    for idx, query in enumerate(queries, start=1):
        kind = str(query.get("kind"))
        breakdown_value = query.get("breakdownBy")
        label = f"{kind}:{breakdown_value}" if breakdown_value else kind
        # Per-tile start line so the run is followable live in the Dagster UI —
        # each tile can take up to the query timeout, so seeing which one is in
        # flight (and how far through the matrix) matters when a run drags.
        context.log.info(f"eager_baseline_warming_tile_start [{idx}/{total}] team={team.pk} query={label}")
        logger.info("eager_baseline_warming_tile_start", team_id=team.pk, query=label, tile=idx, total=total)
        tile_started = time.monotonic()
        try:
            # Tag BEFORE constructing the runner. `tag_queries` writes to
            # a contextvar; any I/O the runner does at construction time
            # inherits these tags, so attribution stays consistent.
            tag_queries(
                team_id=team.pk,
                trigger="webAnalyticsEagerBaselineWarming",
                feature=Feature.CACHE_WARMUP,
                product=Product.WEB_ANALYTICS,
            )
            runner = get_query_runner(query=query, team=team, limit_context=LimitContext.QUERY_ASYNC)
            # Force-refresh via run() — see module docstring (recomputes every tick
            # while staying inside run()'s rate-limit/concurrency wrappers).
            response = runner.run(
                execution_mode=ExecutionMode.CALCULATE_BLOCKING_ALWAYS,
                analytics_props={"source": EventSource.CACHE_WARMING},
            )
            EAGER_PRECOMPUTE_BASELINE_WARMED.labels(query_kind=label).inc()
            warmed += 1
            # Self-check the warm actually did its job: the tile must resolve to a
            # precompute read, not fall through to raw. `usedLazyPrecompute` is only
            # True when the read passed the lazy executor's TTL freshness filter
            # (`created_at + TTL >= now`, TTL = 15min today … 7d old), so True is a
            # guarantee the precomputed value is well within the 2h threshold. A tile
            # that comes back `not True` warmed nothing useful — surface it loudly so a
            # stale/missing precompute or a non-precomputable breakdown can't hide.
            if getattr(response, "usedLazyPrecompute", None) is not True:
                EAGER_PRECOMPUTE_BASELINE_NOT_PRECOMPUTED.labels(query_kind=label).inc()
                context.log.warning(
                    f"eager_baseline_warming_tile_not_precomputed [{idx}/{total}] team={team.pk} query={label}"
                )
                logger.warning(
                    "eager_baseline_warming_tile_not_precomputed",
                    team_id=team.pk,
                    query=label,
                    tile=idx,
                    total=total,
                )
            tile_ms = round((time.monotonic() - tile_started) * 1000)
            context.log.info(
                f"eager_baseline_warming_tile_done [{idx}/{total}] team={team.pk} query={label} "
                f"status=warmed duration_ms={tile_ms}"
            )
            logger.info(
                "eager_baseline_warming_tile_done",
                team_id=team.pk,
                query=label,
                tile=idx,
                total=total,
                status="warmed",
                duration_ms=tile_ms,
            )
        except Exception as exc:
            tile_ms = round((time.monotonic() - tile_started) * 1000)
            EAGER_PRECOMPUTE_BASELINE_FAILED.labels(query_kind=label, error_type=type(exc).__name__).inc()
            context.log.exception(
                f"eager_baseline_warming_query_failed [{idx}/{total}] team={team.pk} query={label} "
                f"duration_ms={tile_ms}"
            )
            logger.exception(
                "eager_baseline_warming_query_failed",
                team_id=team.pk,
                query=label,
                query_kind=label,
                tile=idx,
                total=total,
                status="failed",
                duration_ms=tile_ms,
                error_type=type(exc).__name__,
            )
            failed += 1
    return warmed, failed


@dagster.op
def warm_eager_baseline_op(context: dagster.OpExecutionContext) -> dict[str, int]:
    """Run the baseline tile matrix against every team in the `WEB_ANALYTICS_LAZY_PRECOMPUTE_TEAM_IDS` setting."""
    started = time.monotonic()
    team_ids, gate_reason, diagnostics = _resolve_eager_audience()
    diag_str = " ".join(f"{k}={v}" for k, v in diagnostics.items())
    context.log.info(
        f"eager_baseline_warming_start teams={len(team_ids)} gate_reason={gate_reason} {diag_str}".rstrip()
    )
    # Mirror lifecycle events to structlog so the run is queryable in Loki /
    # PostHog. `context.log` only reaches the Dagster UI — PostHog's Dagster
    # has no python_logs sink wiring it to stdout.
    logger.info("eager_baseline_warming_start", teams=len(team_ids), gate_reason=gate_reason, **diagnostics)

    # Bulk-load teams once instead of N+1 per-team get().
    teams_by_id = {t.pk: t for t in Team.objects.filter(pk__in=team_ids).select_related("organization")}

    warmed = 0
    failed = 0
    skipped = 0
    for team_id in team_ids:
        team = teams_by_id.get(team_id)
        if team is None:
            context.log.warning(f"eager_baseline_warming_team_missing team_id={team_id}")
            logger.warning("eager_baseline_warming_team_missing", team_id=team_id)
            skipped += 1
            continue

        # Eligibility pre-check. The audience IS the precompute team list, so a
        # team reaching here should always be eligible. If it isn't, the gate
        # and the warmer audience have drifted and every tile would silently
        # warm via the raw path — skip loudly rather than burn compute on it.
        if not is_precompute_enabled_for_team(team):
            EAGER_PRECOMPUTE_NOT_LAZY_ELIGIBLE.inc()
            context.log.error(
                f"eager_baseline_warming_not_lazy_eligible team={team_id} — "
                f"skipping; the lazy gate would route every tile through the raw path"
            )
            logger.error("eager_baseline_warming_not_lazy_eligible", team_id=team_id)
            skipped += 1
            continue

        team_started = time.monotonic()
        team_warmed, team_failed = _warm_baseline_for_team(context, team)
        logger.info(
            "eager_baseline_warming_team",
            team_id=team_id,
            warmed=team_warmed,
            failed=team_failed,
            duration_ms=round((time.monotonic() - team_started) * 1000),
        )
        warmed += team_warmed
        failed += team_failed

    duration_ms = round((time.monotonic() - started) * 1000)
    context.log.info(
        f"eager_baseline_warming_complete teams={len(team_ids)} warmed={warmed} failed={failed} "
        f"skipped={skipped} gate_reason={gate_reason} duration_ms={duration_ms}"
    )
    logger.info(
        "eager_baseline_warming_complete",
        teams=len(team_ids),
        warmed=warmed,
        failed=failed,
        skipped=skipped,
        gate_reason=gate_reason,
        duration_ms=duration_ms,
    )
    result = {"teams": len(team_ids), "warmed": warmed, "failed": failed, "skipped": skipped}
    context.add_output_metadata({**result, "gate_reason": gate_reason, "duration_ms": duration_ms, **diagnostics})
    return result


@dagster.job(
    description=(
        "Hourly pre-warmer for Web analytics: runs the dashboard's main tile matrix over the last "
        f"{BASELINE_WINDOW_DAYS} days for every team in `WEB_ANALYTICS_LAZY_PRECOMPUTE_TEAM_IDS`. Each query is "
        "dispatched through its standard runner, which routes through the family's lazy precompute "
        "path — the runner decides what's stale and inserts only what's missing."
    ),
    tags={
        "owner": JobOwners.TEAM_WEB_ANALYTICS.value,
        # Dagster terminates the run if it exceeds this; the next scheduled
        # tick (5 min later) starts fresh.
        "dagster/max_runtime": str(45 * 60),
    },
)
def web_analytics_eager_baseline_warming_job():
    warm_eager_baseline_op()


@dagster.schedule(
    # Hourly. The lazy cache's 2h TTL absorbs a single missed cycle, so
    # there's no need to align with shorter cadences. Offset by 5 min from
    # the top of the hour to avoid colliding with the existing
    # `web_analytics_cache_warming_schedule` (`0 * * * *`).
    cron_schedule="5 * * * *",
    job=web_analytics_eager_baseline_warming_job,
    execution_timezone="UTC",
    tags={"owner": JobOwners.TEAM_WEB_ANALYTICS.value},
)
def web_analytics_eager_baseline_warming_schedule(
    context: dagster.ScheduleEvaluationContext,
) -> "dagster.RunRequest | dagster.SkipReason":
    skip_reason = check_for_concurrent_runs(context)
    if skip_reason:
        return skip_reason
    return dagster.RunRequest()
