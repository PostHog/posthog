"""Eager web analytics precompute — hourly baseline warming.

A single Dagster job that pre-warms the lazy precompute cache for the
Web analytics dashboard's main tile matrix over the trailing 28 days,
for every team in the hardcoded `EAGER_BASELINE_TEAM_IDS` list.

The job is intentionally thin: it enumerates the dashboard's query
families and dispatches each through `get_query_runner(...).run(...)`.
The runner routes through its family's lazy precompute path, which
already knows what's stale and INSERTs only what's missing. This DAG is
the *trigger*; the runner is the source of truth for freshness.

Why this exists
---------------
The lazy precompute path caches per-day buckets in `web_*_preaggregated`
tables with a 2h TTL. For high-traffic teams the dashboard's main tiles
are requested constantly — there is no reason to compute them reactively.
Running the same query set ahead of every reasonable visit keeps the
cache perpetually warm, so user requests turn into pure reads.

Audience
--------
The audience is a hardcoded `EAGER_BASELINE_TEAM_IDS` tuple kept in
source. To enroll or remove a team, open a PR editing the constant.
The list intentionally mirrors `WEB_ANALYTICS_LAZY_PRECOMPUTE_TEAM_IDS`
on the runtime read path so warmer and reader stay in sync; do not
silently let them drift.

The job is a no-op on self-hosted instances (`is_cloud()` returns False)
since the lazy precompute infrastructure is Cloud-only.

This job is complementary to `cache_warming.py`, which replays whatever
queries users actually ran. The eager job covers the fixed UI matrix;
the replay covers the long tail (custom hosts, custom filters, etc.).
"""

import dagster
import structlog
from prometheus_client import Counter

from posthog.schema import WebStatsBreakdown

from posthog.hogql.constants import LimitContext

from posthog.clickhouse.query_tagging import Feature, Product, tag_queries
from posthog.cloud_utils import is_cloud
from posthog.dags.common import JobOwners
from posthog.event_usage import EventSource
from posthog.hogql_queries.query_runner import get_query_runner
from posthog.models import Team

from products.web_analytics.dags.web_preaggregated_utils import check_for_concurrent_runs

logger = structlog.get_logger(__name__)


# Audience: teams that should have the dashboard's main tile matrix
# perpetually warmed. Keep this in sync with the runtime read-path
# `WEB_ANALYTICS_LAZY_PRECOMPUTE_TEAM_IDS` env var on Django pods —
# warming a team here that the reader doesn't serve is wasted compute.
EAGER_BASELINE_TEAM_IDS: tuple[int, ...] = (2,)

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
    WebStatsBreakdown.SCREEN_NAME,
    WebStatsBreakdown.INITIAL_CHANNEL_TYPE,
    WebStatsBreakdown.INITIAL_REFERRING_DOMAIN,
    WebStatsBreakdown.INITIAL_REFERRING_URL,
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


def _resolve_eager_audience() -> tuple[list[int], str, dict]:
    """Resolve the audience and return a structured trace of which gate
    fired. Returns `(team_ids, gate_reason, diagnostics)`.

    `gate_reason` is one of: `not_cloud`, `no_teams_configured`, `ok`.
    """
    if not is_cloud():
        return [], "not_cloud", {}

    team_ids = list(EAGER_BASELINE_TEAM_IDS)
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
        queries.append(query)

    warmed = 0
    failed = 0
    for query in queries:
        kind = str(query.get("kind"))
        breakdown_value = query.get("breakdownBy")
        label = f"{kind}:{breakdown_value}" if breakdown_value else kind
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
            runner.run(analytics_props={"source": EventSource.CACHE_WARMING})
            EAGER_PRECOMPUTE_BASELINE_WARMED.labels(query_kind=label).inc()
            warmed += 1
        except Exception as exc:
            EAGER_PRECOMPUTE_BASELINE_FAILED.labels(query_kind=label, error_type=type(exc).__name__).inc()
            context.log.exception(f"eager_baseline_warming_query_failed team={team.pk} query={label}")
            failed += 1
    return warmed, failed


@dagster.op
def warm_eager_baseline_op(context: dagster.OpExecutionContext) -> dict[str, int]:
    """Run the baseline tile matrix against every team in `EAGER_BASELINE_TEAM_IDS`."""
    team_ids, gate_reason, diagnostics = _resolve_eager_audience()
    diag_str = " ".join(f"{k}={v}" for k, v in diagnostics.items())
    context.log.info(
        f"eager_baseline_warming_start teams={len(team_ids)} gate_reason={gate_reason} {diag_str}".rstrip()
    )

    # Bulk-load teams once instead of N+1 per-team get().
    teams_by_id = {t.pk: t for t in Team.objects.filter(pk__in=team_ids).select_related("organization")}

    warmed = 0
    failed = 0
    skipped = 0
    for team_id in team_ids:
        team = teams_by_id.get(team_id)
        if team is None:
            context.log.warning(f"eager_baseline_warming_team_missing team_id={team_id}")
            skipped += 1
            continue

        team_warmed, team_failed = _warm_baseline_for_team(context, team)
        warmed += team_warmed
        failed += team_failed

    context.log.info(
        f"eager_baseline_warming_complete teams={len(team_ids)} warmed={warmed} failed={failed} "
        f"skipped={skipped} gate_reason={gate_reason}"
    )
    result = {"teams": len(team_ids), "warmed": warmed, "failed": failed, "skipped": skipped}
    context.add_output_metadata({**result, "gate_reason": gate_reason, **diagnostics})
    return result


@dagster.job(
    description=(
        "Hourly pre-warmer for Web analytics: runs the dashboard's main tile matrix over the last "
        f"{BASELINE_WINDOW_DAYS} days for every team in `EAGER_BASELINE_TEAM_IDS`. Each query is "
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
