from collections import defaultdict
from dataclasses import dataclass
from datetime import date, datetime, timedelta
from typing import Any
from uuid import UUID

from django.utils import timezone

import structlog

from posthog.clickhouse.client.connection import Workload
from posthog.clickhouse.query_tagging import Product
from posthog.exceptions_capture import capture_exception
from posthog.job_owners import JobOwners
from posthog.models.health_issue import HealthIssue
from posthog.models.team import Team
from posthog.temporal.health_checks.detectors import CLICKHOUSE_BATCH_EXECUTION_POLICY
from posthog.temporal.health_checks.framework import AlertContent, HealthCheck, Remediation
from posthog.temporal.health_checks.models import HealthCheckResult
from posthog.temporal.health_checks.query import execute_clickhouse_health_team_query

from products.annotations.backend.facade import api as annotations_api
from products.annotations.backend.facade.enums import AnnotationScope
from products.event_definitions.backend.models import EventDefinition, effective_project_id_expr
from products.notifications.backend.facade.api import (
    NotificationData,
    NotificationType,
    TargetType,
    create_notification,
)
from products.product_analytics.backend.models.insight import Insight

logger = structlog.get_logger(__name__)

EVENT_STOPPED_KIND = "event_stopped"

# An event counts as stopped when it was last seen between these two ages. Events that went quiet
# more than LOOKBACK ago are left alone, because the customer has lived without them for a month.
STOPPED_AFTER = timedelta(days=3)
LOOKBACK = timedelta(days=30)
# A definition this young has no history to compare against, so a quiet week is not a signal yet.
MIN_DEFINITION_AGE = timedelta(days=14)

# An annotation this close to the last event is shown as a possible cause, such as a release.
ANNOTATION_WINDOW = timedelta(days=1)
# Insight and dashboard annotations describe one chart, not a change to the product.
PROJECT_WIDE_ANNOTATION_SCOPES = frozenset({AnnotationScope.PROJECT, AnnotationScope.ORGANIZATION})

# The week before the last event is the baseline for "how many a day did this event get".
BASELINE = timedelta(days=7)
# The SDK and page of the last captures are read from this window before the last event, which keeps
# the properties read small for an event that used to arrive in high volume.
LAST_CAPTURE_WINDOW = timedelta(hours=1)

DAILY_COUNTS_SQL = """
SELECT event, toDate(timestamp) AS day, count()
FROM events
WHERE team_id IN %(team_ids)s
  AND event IN %(events)s
  AND timestamp >= now() - INTERVAL %(lookback_days)s DAY
GROUP BY event, day
"""

LAST_CAPTURE_SQL = """
SELECT
    event,
    argMax(JSONExtractString(properties, '$lib'), timestamp),
    argMax(path(JSONExtractString(properties, '$current_url')), timestamp)
FROM events
WHERE team_id IN %(team_ids)s
  AND ({windows})
GROUP BY event
"""

# Bounds the Postgres work per project and the number of issues a team can hold for this kind.
MAX_CANDIDATES_PER_PROJECT = 50
MAX_ISSUES_PER_TEAM = 10


@dataclass(frozen=True)
class _LastActivity:
    daily_average_before: int | None = None
    lib: str | None = None
    path: str | None = None


@dataclass(frozen=True)
class _Candidate:
    definition_id: str
    name: str
    last_seen_at: datetime


class EventStoppedCheck(HealthCheck):
    name = "event_stopped"
    kind = EVENT_STOPPED_KIND
    owner = JobOwners.TEAM_PRODUCT_ANALYTICS
    product = Product.PRODUCT_ANALYTICS
    # Flagged events cost two ClickHouse reads per project, so batches run one at a time like other ClickHouse checks.
    policy = CLICKHOUSE_BATCH_EXECUTION_POLICY
    schedule = "40 3 * * *"
    rollout_percentage = 0.01
    dry_run = True
    # A team can hold one issue per event. The stock health-alert destination sends one message per
    # issue, so the check sends one grouped in-app notification per team instead (`on_issues_fired`).
    emits_alerts = False
    remediation = Remediation(
        human="""
            Find where your code captures this event and confirm the call still runs. Look for a removed
            or renamed `posthog.capture` call, a changed event name, or a code path that no longer
            executes. If you stopped sending the event on purpose, dismiss the issue, and update the
            insights that use it.
        """,
        agent="""
            Confirm the event is silent with `execute-sql` (`SELECT max(timestamp) FROM events WHERE event =
            '<name>'`). Look for a similar event name that started arriving at the same time, which points
            to a rename, and check the insights that use the event with `system.insights`. Then search the
            user's codebase for the event name to find the `capture` call that was removed or changed. If the
            event was renamed, offer to update the insights to the new name.
        """,
    )

    @classmethod
    def render_alert(cls, issue: HealthIssue) -> AlertContent:
        event = issue.payload.get("event", "An event")
        return AlertContent(
            title=f"{event} stopped arriving",
            summary=_summary(issue.payload),
            link=_event_link(issue.payload),
        )

    def detect(self, team_ids: list[int]) -> dict[int, list[HealthCheckResult]]:
        now = timezone.now()
        teams_by_project: dict[int, list[int]] = defaultdict(list)
        organization_by_project: dict[int, UUID] = {}
        for team_id, project_id, organization_id in Team.objects.filter(id__in=team_ids).values_list(
            "id", "project_id", "organization_id"
        ):
            teams_by_project[project_id].append(team_id)
            organization_by_project[project_id] = organization_id
        if not teams_by_project:
            return {}

        definitions = EventDefinition.objects.annotate(effective_project_id=effective_project_id_expr()).filter(
            effective_project_id__in=list(teams_by_project)
        )
        # A project with no event at all since the cutoff went silent as a whole. That is an install or
        # quota problem, which other checks report, and flagging every event would bury it.
        live_project_ids = set(
            definitions.filter(last_seen_at__gte=now - STOPPED_AFTER)
            .values_list("effective_project_id", flat=True)
            .distinct()
        )

        candidates_by_project: dict[int, list[_Candidate]] = defaultdict(list)
        rows = (
            definitions.filter(
                effective_project_id__in=live_project_ids,
                last_seen_at__lt=now - STOPPED_AFTER,
                last_seen_at__gte=now - LOOKBACK,
                created_at__lte=now - MIN_DEFINITION_AGE,
                # Set when the customer stopped ingestion for this event, so the silence is deliberate.
                ingestion_stopped_at__isnull=True,
            )
            # PostHog's own events have their own checks, such as `no_live_events` for pageviews.
            .exclude(name__startswith="$")
            .order_by("-last_seen_at")
            .values_list("effective_project_id", "id", "name", "last_seen_at")
        )
        for project_id, definition_id, name, last_seen_at in rows:
            if last_seen_at is not None and len(candidates_by_project[project_id]) < MAX_CANDIDATES_PER_PROJECT:
                candidates_by_project[project_id].append(_Candidate(str(definition_id), name, last_seen_at))

        issues: dict[int, list[HealthCheckResult]] = {}
        for project_id, candidates in candidates_by_project.items():
            insight_counts = _insight_counts(project_id, [c.name for c in candidates])
            used = [c for c in candidates if insight_counts.get(c.name)]
            # Most-used first, so the cap keeps the events the customer relies on most.
            used.sort(key=lambda c: insight_counts[c.name], reverse=True)
            flagged = used[:MAX_ISSUES_PER_TEAM]
            activity = _last_activity(teams_by_project[project_id], flagged)
            results = []
            for c in flagged:
                payload: dict[str, Any] = {
                    "event": c.name,
                    "event_definition_id": c.definition_id,
                    "last_seen_at": c.last_seen_at.isoformat(),
                    "insight_count": insight_counts[c.name],
                }
                context = activity.get(c.name, _LastActivity())
                if context.daily_average_before is not None:
                    payload["daily_average_before"] = context.daily_average_before
                if context.lib:
                    payload["last_lib"] = context.lib
                if context.path:
                    payload["last_path"] = context.path
                annotation = _nearby_annotation(
                    teams_by_project[project_id][0], organization_by_project[project_id], c.last_seen_at
                )
                if annotation:
                    payload["annotation"] = annotation
                results.append(
                    HealthCheckResult(severity=HealthIssue.Severity.WARNING, payload=payload, hash_keys=["event"])
                )
            if results:
                for team_id in teams_by_project[project_id]:
                    issues[team_id] = results
        return issues

    @classmethod
    def on_issues_fired(cls, issues: list[HealthIssue]) -> None:
        issues_by_team: dict[int, list[HealthIssue]] = defaultdict(list)
        for issue in issues:
            issues_by_team[issue.team_id].append(issue)
        for team_id, team_issues in issues_by_team.items():
            try:
                create_notification(_notification_for(team_id, team_issues))
            except Exception as e:
                logger.exception("Failed to send event stopped notification", team_id=team_id)
                capture_exception(e, additional_properties={"team_id": team_id, "kind": EVENT_STOPPED_KIND})


def _insight_counts(project_id: int, event_names: list[str]) -> dict[str, int]:
    """Count the saved insights in a project that read each event, from the events list in `query_metadata`."""
    wanted = set(event_names)
    counts: dict[str, int] = defaultdict(int)
    metadata_rows = Insight.objects.filter(
        team__project_id=project_id,
        deleted=False,
        saved=True,
        query_metadata__events__has_any_keys=event_names,
    ).values_list("query_metadata", flat=True)
    for metadata in metadata_rows:
        for name in set(metadata.get("events") or []) & wanted:
            counts[name] += 1
    return counts


def daily_average_before(day_counts: dict[date, int], last_seen_at: datetime) -> int:
    """Average events per day over the full days of the baseline week before the last event's day."""
    last_day = last_seen_at.date()
    days = [last_day - timedelta(days=offset) for offset in range(1, BASELINE.days + 1)]
    return round(sum(day_counts.get(day, 0) for day in days) / BASELINE.days)


def _last_activity(team_ids: list[int], candidates: list[_Candidate]) -> dict[str, _LastActivity]:
    """Read how much each event used to arrive, and where it was last captured.

    The issue is still worth showing without this context, so a failed read leaves it out.
    """
    if not candidates:
        return {}
    try:
        counts: dict[str, dict[date, int]] = defaultdict(dict)
        for event, day, count in execute_clickhouse_health_team_query(
            DAILY_COUNTS_SQL,
            team_ids=team_ids,
            lookback_days=(LOOKBACK + BASELINE).days + 1,
            params={"events": [c.name for c in candidates]},
            workload=Workload.OFFLINE,
        ):
            counts[event][day] = count

        # One window per event, built from parameter names only, so no event name reaches the SQL text.
        windows = " OR ".join(
            f"(event = %(event_{i})s AND timestamp >= %(since_{i})s AND timestamp <= %(until_{i})s)"
            for i in range(len(candidates))
        )
        params: dict[str, Any] = {}
        for i, c in enumerate(candidates):
            params[f"event_{i}"] = c.name
            params[f"since_{i}"] = c.last_seen_at - LAST_CAPTURE_WINDOW
            params[f"until_{i}"] = c.last_seen_at
        last_captures = {
            event: (lib or None, path or None)
            for event, lib, path in execute_clickhouse_health_team_query(
                LAST_CAPTURE_SQL.format(windows=windows),
                team_ids=team_ids,
                params=params,
                workload=Workload.OFFLINE,
            )
        }
    except Exception as e:
        logger.exception("Failed to read stopped event activity", team_ids=team_ids)
        capture_exception(e, additional_properties={"team_ids": team_ids, "kind": EVENT_STOPPED_KIND})
        return {}

    return {
        c.name: _LastActivity(
            daily_average_before=daily_average_before(counts.get(c.name, {}), c.last_seen_at),
            lib=last_captures.get(c.name, (None, None))[0],
            path=last_captures.get(c.name, (None, None))[1],
        )
        for c in candidates
    }


def _nearby_annotation(team_id: int, organization_id: UUID, last_seen_at: datetime) -> dict[str, str] | None:
    annotations = annotations_api.list_dated_annotations(
        team_id=team_id,
        organization_id=organization_id,
        start=last_seen_at - ANNOTATION_WINDOW,
        end=last_seen_at + ANNOTATION_WINDOW,
        limit=10,
    )
    for annotation in annotations:
        if annotation.scope in PROJECT_WIDE_ANNOTATION_SCOPES:
            return {"content": annotation.content, "marked_at": annotation.marked_at.isoformat()}
    return None


def _summary(payload: dict) -> str:
    count = payload.get("insight_count", 0)
    insights = "1 insight uses it" if count == 1 else f"{count} insights use it"
    average = payload.get("daily_average_before")
    before = f", down from about {average:,} a day" if average else ""
    return f"No events in the last {STOPPED_AFTER.days} days{before}. {insights}."


def _event_link(payload: dict) -> str:
    definition_id = payload.get("event_definition_id")
    return f"/data-management/events/{definition_id}" if definition_id else "/data-management/events"


def _notification_for(team_id: int, issues: list[HealthIssue]) -> NotificationData:
    if len(issues) == 1:
        payload = issues[0].payload
        title = f"{payload.get('event', 'An event')} stopped arriving"
        body = f"{_summary(payload)} Open the event to check when it last arrived and which insights read it."
        source_url = _event_link(payload)
    else:
        names = ", ".join(issue.payload.get("event", "") for issue in issues[:3])
        more = f" and {len(issues) - 3} more" if len(issues) > 3 else ""
        title = f"{len(issues)} events your insights use stopped arriving"
        body = (
            f"These events haven't arrived in the last {STOPPED_AFTER.days} days: {names}{more}. "
            "Check whether your code still sends them."
        )
        source_url = "/data-management/events"
    return NotificationData(
        team_id=team_id,
        notification_type=NotificationType.EVENT_STOPPED,
        title=title,
        body=body,
        target_type=TargetType.TEAM,
        target_id=str(team_id),
        source_url=source_url,
    )
