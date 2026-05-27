"""Eager web analytics precompute — hourly baseline warming.

A single Dagster job that pre-warms the lazy precompute cache and Django
response cache for the Web Analytics dashboard's main tile matrix over the
last 28 days, for every team whose organization has a member matching the
`web-analytics-pre-aggregated-tables` feature flag's email conditions.

Why this exists
---------------
The lazy precompute path caches per-day buckets in `web_*_preaggregated`
tables with a 2h TTL. For high-traffic customers, the dashboard's main
tiles are requested constantly — there is no reason to compute them
reactively. Running the same query set ahead of every reasonable visit
keeps the cache perpetually warm, so user requests turn into pure reads.

Audience
--------
Source of truth is the `web-analytics-pre-aggregated-tables` flag on the
PostHog dogfooding project (team id 2 in PostHog Cloud). The job parses
the flag's `email icontains` conditions and resolves them to the set of
teams whose organization has at least one matching member.

Scope
-----
- Window: fixed `last 28 days`.
- Query matrix: 1× WebOverviewQuery, 1× WebGoalsQuery, 1× WebVitalsPathBreakdownQuery,
  N× WebStatsTableQuery (one per UI-rendered `WebStatsBreakdown` value).
- Cadence: hourly. The lazy cache's 2h TTL absorbs any single missed cycle.

This job complements `cache_warming.py`, which replays whatever queries
users actually ran. The eager job covers the fixed UI matrix; the replay
covers the long tail (custom hosts, custom filters, etc.).
"""

import re

import dagster
import structlog
from prometheus_client import Counter

from posthog.schema import WebStatsBreakdown

from posthog.hogql.constants import LimitContext

from posthog.clickhouse.query_tagging import Feature, Product, tag_queries
from posthog.dags.common import JobOwners
from posthog.event_usage import EventSource
from posthog.hogql_queries.query_runner import get_query_runner
from posthog.models import Team
from posthog.models.feature_flag import FeatureFlag

logger = structlog.get_logger(__name__)


EAGER_FLAG_KEY = "web-analytics-pre-aggregated-tables"
# Team id 2 = the PostHog dogfooding project in PostHog Cloud, where this
# rollout flag lives. On self-hosted instances the flag will not exist and
# the job becomes a no-op (returns an empty team list).
EAGER_FLAG_TEAM_ID = 2

BASELINE_WINDOW_DAYS = 28


# The full set of `WebStatsBreakdown` values rendered as tiles in the Web
# Analytics dashboard (see `frontend/src/scenes/web-analytics/webAnalyticsLogic.tsx`).
# `FrustrationMetrics` is treated as a regular breakdown — the dashboard renders
# it via the same `WebStatsTableQuery` shape.
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
    "Baseline queries successfully warmed per cycle.",
    ["query_kind"],
)
EAGER_PRECOMPUTE_BASELINE_FAILED = Counter(
    "web_analytics_eager_precompute_baseline_failed_total",
    "Baseline queries that raised during warming.",
    ["query_kind", "error_type"],
)


def _extract_email_domains_from_flag(flag: FeatureFlag) -> list[str]:
    """Pull `email icontains <domain>` values out of a flag's filter groups.

    The `web-analytics-pre-aggregated-tables` flag is structured as one
    group per customer domain, each with a single `person.email icontains
    "@foo.com"` property. Other shapes are ignored — if the flag is
    re-modelled we'd want to revisit this resolver anyway.
    """
    domains: list[str] = []
    for group in (flag.filters or {}).get("groups", []) or []:
        for prop in group.get("properties", []) or []:
            if prop.get("type") != "person" or prop.get("key") != "email":
                continue
            if prop.get("operator") != "icontains":
                continue
            value = prop.get("value")
            if isinstance(value, str) and value:
                domains.append(value)
            elif isinstance(value, list):
                domains.extend(v for v in value if isinstance(v, str) and v)
    return domains


def get_eager_team_ids() -> list[int]:
    """Resolve the audience: teams whose org has any member whose email
    matches one of the flag's `icontains` domain conditions.

    Returns an empty list if the flag is absent, inactive, or has no
    parseable email conditions — in which case the warming job is a no-op.
    """
    try:
        flag = FeatureFlag.objects.get(team_id=EAGER_FLAG_TEAM_ID, key=EAGER_FLAG_KEY, active=True, deleted=False)
    except FeatureFlag.DoesNotExist:
        return []

    domains = _extract_email_domains_from_flag(flag)
    if not domains:
        return []

    pattern = "|".join(re.escape(d) for d in domains)
    team_ids = (
        Team.objects.filter(organization__members__email__iregex=pattern)
        .values_list("pk", flat=True)
        .distinct()
        .order_by("pk")
    )
    return list(team_ids)


def _baseline_queries() -> list[dict]:
    """Return the fixed UI tile matrix for a single team.

    Same `filterTestAccounts=True` default the dashboard sends. `limit=10`
    matches the per-tile pagination so the warmed response cache exactly
    matches what users request.
    """
    date_range = {"date_from": f"-{BASELINE_WINDOW_DAYS}d"}
    common = {
        "dateRange": date_range,
        "properties": [],
        "filterTestAccounts": True,
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

    Failures per query are caught so one broken breakdown does not poison
    the rest of the team's matrix or the rest of the run.
    """
    warmed = 0
    failed = 0
    for query in _baseline_queries():
        kind = str(query.get("kind"))
        breakdown = query.get("breakdownBy")
        label = f"{kind}:{breakdown}" if breakdown else kind
        try:
            runner = get_query_runner(query=query, team=team, limit_context=LimitContext.QUERY_ASYNC)
            tag_queries(
                team_id=team.pk,
                trigger="webAnalyticsEagerBaselineWarming",
                feature=Feature.CACHE_WARMUP,
                product=Product.WEB_ANALYTICS,
            )
            runner.run(analytics_props={"source": EventSource.CACHE_WARMING})
            EAGER_PRECOMPUTE_BASELINE_WARMED.labels(query_kind=label).inc()
            warmed += 1
        except Exception as exc:
            EAGER_PRECOMPUTE_BASELINE_FAILED.labels(query_kind=label, error_type=type(exc).__name__).inc()
            context.log.exception(f"eager baseline warming failed for team={team.pk} query={label}")
            failed += 1
    return warmed, failed


@dagster.op
def warm_eager_baseline_op(context: dagster.OpExecutionContext) -> dict[str, int]:
    """Run the baseline tile matrix against every flag-enrolled team."""
    team_ids = get_eager_team_ids()
    context.log.info(f"Eager baseline warming: {len(team_ids)} teams enrolled")

    warmed = 0
    failed = 0
    for team_id in team_ids:
        try:
            team = Team.objects.get(pk=team_id)
        except Team.DoesNotExist:
            context.log.warning(f"team_id={team_id} not found, skipping")
            continue

        team_warmed, team_failed = _warm_baseline_for_team(context, team)
        warmed += team_warmed
        failed += team_failed

    context.log.info(f"Eager baseline warming complete: warmed={warmed} failed={failed}")
    context.add_output_metadata({"teams": len(team_ids), "warmed": warmed, "failed": failed})
    return {"teams": len(team_ids), "warmed": warmed, "failed": failed}


@dagster.job(
    description=(
        "Hourly pre-warmer for Web Analytics: runs the dashboard's main tile matrix "
        f"over the last {BASELINE_WINDOW_DAYS} days for every team whose org has a member "
        f"matching the `{EAGER_FLAG_KEY}` flag."
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
    return dagster.RunRequest()
