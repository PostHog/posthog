from collections import defaultdict
from datetime import datetime, timedelta
from typing import Any

from django.db.models import OuterRef, Subquery
from django.db.models.functions import Greatest
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
from products.product_analytics.backend.logic import with_last_viewed_at
from products.product_analytics.backend.models.insight import Insight

STOPPED_AFTER_DAYS = 7
STOPPED_WITHIN_DAYS = 21
PREVIOUS_STEP_SEEN_WITHIN_DAYS = 1
ACTIVE_WINDOW_DAYS = 30
MIN_ACTIVE_DAYS = 20
MAX_FUNNELS_IN_PAYLOAD = 5

# A step counts as stopped when it arrived on most days of the month before its last sighting. This keeps weekly and
# monthly events, which are quiet for days by design, out of the results.
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


def _funnel_steps(query: dict[str, Any] | None) -> list[str | None]:
    source = (query or {}).get("source") if (query or {}).get("kind") == "InsightVizNode" else query
    if not isinstance(source, dict) or source.get("kind") != "FunnelsQuery":
        return []
    return [step.get("event") if step.get("kind") == "EventsNode" else None for step in source.get("series") or []]


def _recently_used_funnels(team_ids: list[int], since: datetime) -> list[tuple[int, str, str, datetime, list]]:
    last_dashboard_access = (
        DashboardTile.objects.filter(insight_id=OuterRef("pk"))
        .order_by("-dashboard__last_accessed_at")
        .values("dashboard__last_accessed_at")[:1]
    )
    funnels = (
        with_last_viewed_at(
            Insight.objects.filter(team_id__in=team_ids, saved=True, query__source__kind="FunnelsQuery")
        )
        .annotate(last_used_at=Greatest("last_viewed_at", Subquery(last_dashboard_access)))
        .filter(last_used_at__gte=since)
    )
    return [
        (team_id, short_id, name or derived_name or "", last_used_at, _funnel_steps(query))
        for team_id, short_id, name, derived_name, last_used_at, query in funnels.values_list(
            "team_id", "short_id", "name", "derived_name", "last_used_at", "query"
        )
    ]


class StoppedFunnelStepsCheck(HealthCheck):
    name = "stopped_funnel_steps"
    kind = "stopped_funnel_steps"
    owner = JobOwners.TEAM_ANALYTICS_PLATFORM
    product = Product.PRODUCT_ANALYTICS
    policy = CLICKHOUSE_BATCH_EXECUTION_POLICY
    schedule = "45 5 * * *"
    active_since_days = 30
    dry_run = True
    remediation = Remediation(
        human="""
            A funnel step stopped arriving while the step before it still arrives, so the funnel converts at 0% after
            that step. If you removed or renamed the event on purpose, update or archive the funnel and dismiss this
            issue. If not, find the code that sends the event and check whether a recent release removed it.
        """,
        agent="""
            Confirm the stop and look for a replacement with `execute-sql` (`SELECT event, min(timestamp), count()
            FROM events WHERE timestamp > now() - INTERVAL 30 DAY GROUP BY event ORDER BY 2 DESC`). An event that
            first appears near the last sighting is a likely rename. Search the user's codebase for the event name and
            read the history around the last-seen date to find the change that removed it. If the change was on
            purpose, tell the user which funnels to update. If not, restore the capture call. The issue resolves when
            the event arrives again or no recently used funnel reads it.
        """,
    )

    @classmethod
    def render_alert(cls, issue: HealthIssue) -> AlertContent:
        funnels = issue.payload.get("funnels") or []
        return AlertContent(
            title=f"Funnel step {issue.payload.get('event')} stopped arriving",
            summary=(
                f"{issue.payload.get('previous_step')} still arrives, but this step was last seen "
                f"{issue.payload.get('last_seen')}. {issue.payload.get('funnel_count', len(funnels))} funnels "
                "now convert at 0% after it."
            ),
            link=f"/insights/{funnels[0]['short_id']}" if funnels else "/insights",
        )

    def detect(self, team_ids: list[int]) -> dict[int, list[HealthCheckResult]]:
        now = timezone.now()
        funnels = _recently_used_funnels(team_ids, since=now - timedelta(days=STOPPED_WITHIN_DAYS))
        if not funnels:
            return {}

        step_events = {(team_id, event) for team_id, *_, steps in funnels for event in steps if event}
        last_seen = {
            (team_id, name): seen_at
            for team_id, name, seen_at in EventDefinition.objects.filter(
                team_id__in={team_id for team_id, _ in step_events}, name__in={event for _, event in step_events}
            ).values_list("team_id", "name", "last_seen_at")
            if seen_at is not None
        }

        def stopped(team_id: int, event: str) -> bool:
            seen_at = last_seen.get((team_id, event))
            return seen_at is not None and now - timedelta(days=STOPPED_WITHIN_DAYS) <= seen_at < now - timedelta(
                days=STOPPED_AFTER_DAYS
            )

        def alive(team_id: int, event: str) -> bool:
            seen_at = last_seen.get((team_id, event))
            return seen_at is not None and seen_at >= now - timedelta(days=PREVIOUS_STEP_SEEN_WITHIN_DAYS)

        # A step that stops while the step before it keeps arriving takes conversion to zero. When the whole flow
        # stops together, the team most likely retired it, so it is not a candidate.
        candidates: dict[tuple[int, str], list[tuple[str, dict[str, str], datetime]]] = defaultdict(list)
        for team_id, short_id, name, last_used_at, steps in funnels:
            for previous, step in zip(steps, steps[1:]):
                if previous and step and alive(team_id, previous) and stopped(team_id, step):
                    candidates[(team_id, step)].append((previous, {"short_id": short_id, "name": name}, last_used_at))
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
            # Only a funnel someone opened after the stop shows a broken number to a person.
            seen_after_stop = [
                (previous, funnel)
                for previous, funnel, used_at in candidates.get((team_id, event), [])
                if used_at.date() > last_day
            ]
            if not seen_after_stop:
                continue
            issues[team_id].append(
                HealthCheckResult(
                    severity=HealthIssue.Severity.INFO,
                    payload={
                        "event": event,
                        "previous_step": seen_after_stop[0][0],
                        "last_seen": last_day.isoformat(),
                        "funnel_count": len(seen_after_stop),
                        "funnels": [funnel for _, funnel in seen_after_stop[:MAX_FUNNELS_IN_PAYLOAD]],
                    },
                    hash_keys=["event"],
                )
            )
        return dict(issues)
