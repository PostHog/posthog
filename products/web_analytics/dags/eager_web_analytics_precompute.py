"""Eager web analytics precompute — hourly baseline warming.

A single Dagster job that pre-warms the lazy precompute cache and Django
response cache for the Web analytics dashboard's main tile matrix over
the last 28 days (and the default 7 day window the dashboard requests
on load), for every team whose organization has at least one active
member matching the `web-analytics-pre-aggregated-tables` feature flag's
email conditions.

Why this exists
---------------
The lazy precompute path caches per-day buckets in `web_*_preaggregated`
tables with a 2h TTL. For high-traffic customers, the dashboard's main
tiles are requested constantly — there is no reason to compute them
reactively. Running the same query set ahead of every reasonable visit
keeps the cache perpetually warm, so user requests turn into pure reads.

Audience
--------
Source of truth is the `web-analytics-pre-aggregated-tables` flag on
PostHog's internal dogfooding project. The job parses the flag's
`email icontains "@domain"` conditions, then resolves them to the set of
teams whose org has at least one active user with a matching email
suffix. The job is a no-op on self-hosted instances (`is_cloud()`
returns False) to avoid resolving a same-keyed flag on an unrelated
tenant.

Composition with the lazy read path
-----------------------------------
This job populates the cache the lazy read path consults. It does NOT
flip the lazy read path's rollout flag (`web-analytics-precompute-toggle`).
For an enrolled team to actually be served from the warmed cache, that
team must also be on the rollout flag. The two flags are independent by
design; operators are expected to overlap their audiences.

This job is complementary to `cache_warming.py`, which replays whatever
queries users actually ran. The eager job covers the fixed UI matrix;
the replay covers the long tail (custom hosts, custom filters, etc.).
"""

import time

from django.db.models import Q

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
from posthog.models.feature_flag import FeatureFlag
from posthog.models.user import User

from products.web_analytics.dags.web_preaggregated_utils import check_for_concurrent_runs

logger = structlog.get_logger(__name__)


EAGER_FLAG_KEY = "web-analytics-pre-aggregated-tables"
# Team id of PostHog's internal dogfooding project on PostHog Cloud, where
# this rollout flag lives. Coupled with the `is_cloud()` gate in
# `get_eager_team_ids` so we never accidentally resolve a same-keyed flag
# against a self-hosted tenant's team 2.
EAGER_FLAG_TEAM_ID = 2

# Primary warming window — the "last 28 days" coverage the eager rollout
# targets. We also warm the dashboard's default 7d window so the Django
# response cache is hit on default loads, not just the lazy CH cache.
BASELINE_WINDOW_DAYS = 28
DASHBOARD_DEFAULT_WINDOW_DAYS = 7
BASELINE_WINDOWS: tuple[int, ...] = (DASHBOARD_DEFAULT_WINDOW_DAYS, BASELINE_WINDOW_DAYS)

# Minimum length for a parsed domain value. Short values (e.g. ".com")
# would otherwise pull in any matching email on the instance.
_MIN_DOMAIN_LEN = 5

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


def _extract_email_domains_from_flag(flag: FeatureFlag) -> list[str]:
    """Pull `email icontains <domain>` values out of a flag's filter groups.

    Defends against malformed JSON shapes — any group/property/value that
    isn't shaped as expected is silently skipped instead of crashing the
    parser. The flag is user-editable from the product UI.
    """
    domains: list[str] = []
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
                if prop.get("type") != "person" or prop.get("key") != "email":
                    continue
                if prop.get("operator") != "icontains":
                    continue
                value = prop.get("value")
                if isinstance(value, str) and value:
                    domains.append(value)
                elif isinstance(value, list):
                    domains.extend(v for v in value if isinstance(v, str) and v)
    except (TypeError, AttributeError):
        return []
    return domains


def _validate_domains(domains: list[str]) -> list[str]:
    """Keep only values that look like email domains.

    Requires `@` prefix and a minimum length so a typo (e.g. `.com`)
    can't enroll every email on the instance.
    """
    return [d for d in domains if d.startswith("@") and len(d) >= _MIN_DOMAIN_LEN]


def get_eager_team_ids() -> list[int]:
    """Resolve the audience: teams whose org has at least one active user
    whose email ends with one of the flag's `@<domain>` values.

    Returns `[]` for any of: not running on PostHog Cloud, flag absent,
    flag inactive/deleted, no valid domains parsed. The empty-list result
    cleanly turns the warming op into a no-op.
    """
    if not is_cloud():
        return []

    try:
        flag = FeatureFlag.objects.get(team_id=EAGER_FLAG_TEAM_ID, key=EAGER_FLAG_KEY, active=True, deleted=False)
    except FeatureFlag.DoesNotExist:
        return []

    domains = _validate_domains(_extract_email_domains_from_flag(flag))
    if not domains:
        return []

    # `iendswith` lowers to `LOWER(email) LIKE LOWER('%@foo.com')` which
    # is still a sequential scan against `posthog_user` but cheaper than
    # `iregex` (no regex compile per row) and end-anchored to prevent
    # `@foo.com` matching `@foo.com.attacker.example`.
    email_filter = Q()
    for d in domains:
        email_filter |= Q(email__iendswith=d)
    matching_user_ids = User.objects.filter(email_filter, is_active=True).values("id")

    return list(
        Team.objects.filter(organization__members__in=matching_user_ids)
        .values_list("pk", flat=True)
        .distinct()
        .order_by("pk")
    )


def _baseline_queries() -> list[dict]:
    """Return the dashboard tile matrix across both warming windows.

    `useWebAnalyticsPrecompute=True` is required — without it the lazy
    precompute path rejects the query via `PerQueryOptInNotSet` and the
    warmer silently falls back to the legacy compute path, leaving the
    `web_*_preaggregated` tables cold.

    `filterTestAccounts=True` and `limit=10` match the dashboard's
    defaults so the warmed Django response cache hits on default loads.
    """
    common_base: dict = {
        "properties": [],
        "filterTestAccounts": True,
        "useWebAnalyticsPrecompute": True,
    }
    queries: list[dict] = []
    for window_days in BASELINE_WINDOWS:
        common = {**common_base, "dateRange": {"date_from": f"-{window_days}d"}}
        queries.extend(
            [
                {"kind": "WebOverviewQuery", **common},
                {"kind": "WebGoalsQuery", "limit": 10, **common},
                {"kind": "WebVitalsPathBreakdownQuery", **common},
            ]
        )
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
        "Hourly pre-warmer for Web analytics: populates the lazy precompute and Django response "
        f"caches by running the dashboard's main tile matrix over the last {BASELINE_WINDOW_DAYS} days "
        f"and the default {DASHBOARD_DEFAULT_WINDOW_DAYS}-day window, for every team whose org has "
        f"an active member matching the `{EAGER_FLAG_KEY}` flag."
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
