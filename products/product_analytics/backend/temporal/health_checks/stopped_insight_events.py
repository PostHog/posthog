from collections import defaultdict
from datetime import timedelta

from django.db.models import Exists, OuterRef
from django.utils import timezone

from posthog.clickhouse.query_tagging import Product
from posthog.job_owners import JobOwners
from posthog.models.health_issue import HealthIssue
from posthog.temporal.health_checks.detectors import CLICKHOUSE_BATCH_EXECUTION_POLICY
from posthog.temporal.health_checks.framework import AlertContent, HealthCheck, Remediation
from posthog.temporal.health_checks.models import HealthCheckResult
from posthog.temporal.health_checks.query import execute_clickhouse_health_team_query

from products.dashboards.backend.models.dashboard_tile import DashboardTile
from products.event_definitions.backend.models.event_definition import EventDefinition
from products.product_analytics.backend.models.insight import Insight, InsightViewed

IN_USE_DAYS = 30
STOPPED_AFTER_DAYS = 7
STOPPED_WITHIN_DAYS = 60
ACTIVE_WINDOW_DAYS = 30
MIN_ACTIVE_DAYS = 20
MAX_INSIGHTS_IN_PAYLOAD = 5

# An event counts as stopped when it arrived on most days of the month before its last sighting. This keeps
# weekly and monthly events, which are quiet for days by design, out of the results.
STOPPED_EVENTS_SQL = """
SELECT team_id, event, last_day
FROM (
    SELECT team_id, event, max(day) AS last_day, arrayCount(d -> d > last_day - %(active_window_days)s, groupArray(day)) AS active_days
    FROM (
        SELECT DISTINCT team_id, event, toDate(timestamp) AS day
        FROM events
        WHERE team_id IN %(team_ids)s
          AND event IN %(events)s
          AND timestamp >= now() - INTERVAL %(lookback_days)s DAY
    )
    GROUP BY team_id, event
)
WHERE last_day < today() - %(stopped_after_days)s
  AND active_days >= %(min_active_days)s
"""


def _insights_by_event_in_use(team_ids: list[int]) -> dict[tuple[int, str], list[dict[str, str]]]:
    cutoff = timezone.now() - timedelta(days=IN_USE_DAYS)
    insights = (
        Insight.objects.filter(team_id__in=team_ids, saved=True, query_metadata__isnull=False)
        .filter(
            Exists(InsightViewed.objects.filter(insight_id=OuterRef("pk"), last_viewed_at__gte=cutoff))
            | Exists(DashboardTile.objects.filter(insight_id=OuterRef("pk"), dashboard__last_accessed_at__gte=cutoff))
        )
        .values_list("team_id", "short_id", "name", "derived_name", "query_metadata")
    )

    insights_by_event: dict[tuple[int, str], list[dict[str, str]]] = defaultdict(list)
    for team_id, short_id, name, derived_name, query_metadata in insights:
        for event in set((query_metadata or {}).get("events") or []):
            insights_by_event[(team_id, event)].append({"short_id": short_id, "name": name or derived_name or ""})
    return insights_by_event


class StoppedInsightEventsCheck(HealthCheck):
    name = "stopped_insight_events"
    kind = "stopped_insight_events"
    owner = JobOwners.TEAM_ANALYTICS_PLATFORM
    product = Product.PRODUCT_ANALYTICS
    policy = CLICKHOUSE_BATCH_EXECUTION_POLICY
    schedule = "45 5 * * *"
    active_since_days = 30
    dry_run = True
    remediation = Remediation(
        human="""
            An event that your insights read stopped arriving, so those insights show a drop to zero. Find the
            code that sends the event and check whether a recent release removed or renamed it. If you renamed
            it on purpose, update the insights to use the new name. If you retired it, remove it from the
            insights.
        """,
        agent="""
            Confirm the stop and look for a replacement with `execute-sql` (`SELECT event, min(timestamp),
            count() FROM events WHERE timestamp > now() - INTERVAL 30 DAY GROUP BY event ORDER BY 2 DESC`). An
            event that first appears near the last sighting is a likely rename. Search the user's codebase for the
            event name and read the history around the last-seen date to find the change that removed it. Restore
            the capture call, or, after the user confirms a rename, point the listed insights at the new event
            with `insight-update`. The issue resolves when the event arrives again or no insight in use reads it.
        """,
    )

    @classmethod
    def render_alert(cls, issue: HealthIssue) -> AlertContent:
        insights = issue.payload.get("insights") or []
        return AlertContent(
            title=f"Event {issue.payload.get('event')} stopped arriving",
            summary=(
                f"Last seen {issue.payload.get('last_seen')}. "
                f"{issue.payload.get('insight_count', len(insights))} insights in use read it."
            ),
            link=f"/insights/{insights[0]['short_id']}" if insights else "/insights",
        )

    def detect(self, team_ids: list[int]) -> dict[int, list[HealthCheckResult]]:
        insights_by_event = _insights_by_event_in_use(team_ids)
        if not insights_by_event:
            return {}

        # last_seen_at is a cheap filter, so ClickHouse only scans the few events that look stopped.
        now = timezone.now()
        candidates = (
            set(
                EventDefinition.objects.filter(
                    team_id__in={team_id for team_id, _ in insights_by_event},
                    name__in={event for _, event in insights_by_event},
                    last_seen_at__lt=now - timedelta(days=STOPPED_AFTER_DAYS),
                    last_seen_at__gte=now - timedelta(days=STOPPED_WITHIN_DAYS),
                ).values_list("team_id", "name")
            )
            & insights_by_event.keys()
        )
        if not candidates:
            return {}

        rows = execute_clickhouse_health_team_query(
            STOPPED_EVENTS_SQL,
            team_ids=sorted({team_id for team_id, _ in candidates}),
            lookback_days=STOPPED_WITHIN_DAYS + ACTIVE_WINDOW_DAYS,
            params={
                "events": sorted({event for _, event in candidates}),
                "active_window_days": ACTIVE_WINDOW_DAYS,
                "stopped_after_days": STOPPED_AFTER_DAYS,
                "min_active_days": MIN_ACTIVE_DAYS,
            },
        )

        issues: dict[int, list[HealthCheckResult]] = defaultdict(list)
        for team_id, event, last_day in rows:
            insights = insights_by_event.get((team_id, event))
            if not insights:
                continue
            issues[team_id].append(
                HealthCheckResult(
                    severity=HealthIssue.Severity.WARNING,
                    payload={
                        "event": event,
                        "last_seen": last_day.isoformat(),
                        "insight_count": len(insights),
                        "insights": insights[:MAX_INSIGHTS_IN_PAYLOAD],
                    },
                    hash_keys=["event"],
                )
            )
        return dict(issues)
