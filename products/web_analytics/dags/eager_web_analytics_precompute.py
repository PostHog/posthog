"""Eager web analytics precompute — hourly baseline warming.

A single Dagster job that pre-warms the lazy precompute cache for the
Web analytics dashboard's main tile matrix over the trailing 28 days,
for every team belonging to an organization rolled out on the
`web-analytics-precompute-toggle` feature flag.

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
Source of truth is the `web-analytics-precompute-toggle` feature flag,
the same flag the runtime lazy read path checks before serving from the
precompute cache. The flag is structured as one group per enrolled
organization (`Match organizations against id equals <uuid>`). The job
extracts those UUIDs from the flag's filter groups and resolves them to
the set of teams belonging to those organizations.

Reusing the runtime flag for the audience guarantees the eager warming
audience never drifts from the audience the read path will actually
serve — there is no second flag to keep in sync.

The job is a no-op on self-hosted instances (`is_cloud()` returns False)
to avoid resolving a same-keyed flag on an unrelated tenant.

Composition with the lazy read path
-----------------------------------
This job and the lazy read path consult the same flag, so an
organization rolled out on the flag is both warmed by this job and
served from the warmed cache at request time. No two-flag coordination
needed.

This job is complementary to `cache_warming.py`, which replays whatever
queries users actually ran. The eager job covers the fixed UI matrix;
the replay covers the long tail (custom hosts, custom filters, etc.).
"""

import time

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
from posthog.models import FeatureFlag, Team

from products.web_analytics.dags.web_preaggregated_utils import check_for_concurrent_runs

logger = structlog.get_logger(__name__)


EAGER_FLAG_KEY = "web-analytics-precompute-toggle"
# Team id of PostHog's internal dogfooding project on PostHog Cloud, where
# this rollout flag lives. Coupled with the `is_cloud()` gate in
# `get_eager_team_ids` so we never accidentally resolve a same-keyed flag
# against a self-hosted tenant's team 2.
EAGER_FLAG_TEAM_ID = 2

# Single warming window: the trailing 28 days. The lazy precompute path
# stores per-day buckets, so a 28-day warm naturally serves any user
# request for a sub-window (today, last 7d, etc.) via the lazy CH cache.
BASELINE_WINDOW_DAYS = 28

# Hard cap on enrolled teams per cycle. A typo in the flag config can
# explode the audience; this cap fails-loudly rather than silently
# overloading ClickHouse.
_MAX_ENROLLED_TEAMS = 200

# Wall-clock budget per cycle. Past this, the loop stops processing more
# teams; in-flight queries finish but the next team is skipped. The
# `check_for_concurrent_runs` guard on the schedule absorbs the next
# tick if we're still here when it fires.
_CYCLE_BUDGET_SECONDS = 45 * 60


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


def _extract_organization_ids_from_flag(flag: FeatureFlag) -> list[str]:
    """Pull `id equals <uuid>` values out of a flag's filter groups.

    Expects org-aggregated flags shaped as one group per enrolled org
    with a `{type: "group", key: "id", operator: "exact", value: <uuid>}`
    property — the shape the product UI produces for "Match organizations
    against id equals <uuid>" conditions.

    Defends against malformed JSON: any group/property/value not shaped
    as expected is silently skipped instead of crashing the parser. The
    flag is user-editable from the product UI.
    """
    org_ids: list[str] = []
    try:
        groups = (flag.filters or {}).get("groups", []) or []
        if not isinstance(groups, list):
            return []
        for group in groups:
            if not isinstance(group, dict):
                continue
            properties = group.get("properties", []) or []
            if not isinstance(properties, list):
                continue
            for prop in properties:
                if not isinstance(prop, dict):
                    continue
                if prop.get("type") != "group" or prop.get("key") != "id":
                    continue
                # `exact` is the default operator when not specified.
                operator = prop.get("operator") or "exact"
                if operator != "exact":
                    continue
                value = prop.get("value")
                if isinstance(value, str) and value:
                    org_ids.append(value)
                elif isinstance(value, list):
                    org_ids.extend(v for v in value if isinstance(v, str) and v)
    except (TypeError, AttributeError):
        return []
    return org_ids


def get_eager_team_ids() -> list[int]:
    """Resolve the audience: teams belonging to organizations rolled out
    on the `web-analytics-precompute-toggle` flag.

    Returns `[]` for any of: not running on PostHog Cloud, flag absent,
    flag inactive/deleted, no organization-id conditions parsed. The
    empty-list result cleanly turns the warming op into a no-op.
    """
    if not is_cloud():
        return []

    try:
        flag = FeatureFlag.objects.get(team_id=EAGER_FLAG_TEAM_ID, key=EAGER_FLAG_KEY, active=True, deleted=False)
    except FeatureFlag.DoesNotExist:
        return []

    org_ids = _extract_organization_ids_from_flag(flag)
    if not org_ids:
        return []

    return list(Team.objects.filter(organization_id__in=org_ids).values_list("pk", flat=True).distinct().order_by("pk"))


def _baseline_queries() -> list[dict]:
    """Return the eager warming queries — one per family/breakdown.

    Each payload is handed to `get_query_runner(...).run(...)`, which
    dispatches into the family's lazy precompute path. That path is
    idempotent: it checks the family's preagg job table and short-
    circuits on jobs that are already READY for the requested time
    range. The runner — not this DAG — is the source of truth for
    freshness; this function only enumerates the surface (which query
    kinds + breakdowns the dashboard renders).

    `useWebAnalyticsPrecompute=True` is required — without it the lazy
    path rejects the query via `PerQueryOptInNotSet` and the warmer
    silently falls back to legacy compute.

    `filterTestAccounts=True` and `limit=10` match the dashboard's
    defaults so the warmed Django response cache hits on default loads.
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
        {"kind": "WebVitalsPathBreakdownQuery", **common},
    ]
    for breakdown in BASELINE_BREAKDOWNS:
        queries.append(
            {
                "kind": "WebStatsTableQuery",
                "breakdownBy": breakdown.value,
                "limit": 10,
                **common,
            }
        )
    return queries


def _warm_baseline_for_team(context: dagster.OpExecutionContext, team: Team) -> tuple[int, int]:
    """Run the full tile matrix for one team. Returns (warmed, failed).

    Failures per query are caught so one broken breakdown doesn't poison
    the rest of the team's matrix or the rest of the run.
    """
    warmed = 0
    failed = 0
    for query in _baseline_queries():
        kind = str(query.get("kind"))
        breakdown = query.get("breakdownBy")
        label = f"{kind}:{breakdown}" if breakdown else kind
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
    """Run the baseline tile matrix against every flag-enrolled team."""
    team_ids = get_eager_team_ids()

    if len(team_ids) > _MAX_ENROLLED_TEAMS:
        context.log.error(f"eager_baseline_warming_audience_capped enrolled={len(team_ids)} cap={_MAX_ENROLLED_TEAMS}")
        return {"teams": len(team_ids), "warmed": 0, "failed": 0, "skipped": len(team_ids)}

    context.log.info(f"eager_baseline_warming_start teams={len(team_ids)}")

    # Bulk-load teams once instead of N+1 per-team get().
    teams_by_id = {t.pk: t for t in Team.objects.filter(pk__in=team_ids).select_related("organization")}

    warmed = 0
    failed = 0
    skipped = 0
    deadline = time.monotonic() + _CYCLE_BUDGET_SECONDS
    for team_id in team_ids:
        if time.monotonic() > deadline:
            context.log.warning(
                f"eager_baseline_warming_budget_exhausted team_id={team_id} budget_seconds={_CYCLE_BUDGET_SECONDS}"
            )
            skipped += 1
            continue
        team = teams_by_id.get(team_id)
        if team is None:
            context.log.warning(f"eager_baseline_warming_team_missing team_id={team_id}")
            skipped += 1
            continue

        team_warmed, team_failed = _warm_baseline_for_team(context, team)
        warmed += team_warmed
        failed += team_failed

    context.log.info(f"eager_baseline_warming_complete warmed={warmed} failed={failed} skipped={skipped}")
    context.add_output_metadata({"teams": len(team_ids), "warmed": warmed, "failed": failed, "skipped": skipped})
    return {"teams": len(team_ids), "warmed": warmed, "failed": failed, "skipped": skipped}


@dagster.job(
    description=(
        "Hourly pre-warmer for Web analytics: runs the dashboard's main tile matrix over the last "
        f"{BASELINE_WINDOW_DAYS} days for every team belonging to an organization rolled out on the "
        f"`{EAGER_FLAG_KEY}` flag. Each query is dispatched through its standard runner, which routes "
        f"through the family's lazy precompute path — the runner decides what's stale and inserts only "
        f"what's missing."
    ),
    tags={"owner": JobOwners.TEAM_WEB_ANALYTICS.value},
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
