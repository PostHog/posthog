"""Alert filter evaluation: does a lifecycle transition match an alert's filters.

Filters gate thread openers only; replies follow the thread without a second
evaluation. The evaluation itself, and the property surface it sees, live in
`filter_evaluation.py`.
"""

import structlog

from posthog.models import Team

from products.error_tracking.backend.facade.contracts import LifecycleFilterOutcome
from products.error_tracking.backend.logic.assignees import resolve_current_assignee
from products.error_tracking.backend.models import ErrorTrackingAlert, ErrorTrackingIssue
from products.error_tracking.backend.temporal.alerts.filter_evaluation import (
    evaluate_lifecycle_filters,
    filters_are_configured,
)
from products.error_tracking.backend.temporal.alerts.types import AlertDeliveryWorkflowInputs
from products.error_tracking.backend.temporal.lifecycle.event_properties import fetch_event_properties

logger = structlog.get_logger(__name__)


def has_configured_filters(alert: ErrorTrackingAlert) -> bool:
    return filters_are_configured(alert.filters or {})


def alert_filters_match(
    alert: ErrorTrackingAlert, inputs: AlertDeliveryWorkflowInputs, exception_properties: dict[str, object] | None
) -> bool:
    """Whether the transition passes the alert's filters. See `evaluate_lifecycle_filters`."""
    outcome = evaluate_lifecycle_filters(
        alert.filters or {}, inputs, exception_properties, log_context={"alert_id": str(alert.id)}
    )
    return outcome == LifecycleFilterOutcome.MATCH


def stored_issue_created_filter_outcome(
    team_id: int, issue_id: str, fingerprint: str | None, filters: object
) -> LifecycleFilterOutcome:
    """The filter outcome for an issue_created transition rebuilt from the stored issue.

    For callers with no triggering exception, such as the Inbox backfill. The issue row gives
    the lifecycle properties, so a filter on any exception property reads as data unavailable.
    """
    if not isinstance(filters, dict):
        return LifecycleFilterOutcome.FILTER_ERROR
    if not filters_are_configured(filters):
        return LifecycleFilterOutcome.MATCH
    issue = (
        ErrorTrackingIssue.objects.filter(team_id=team_id, id=issue_id)
        .only("name", "description", "status", "severity", "created_at")
        .first()
    )
    if issue is None:
        return LifecycleFilterOutcome.DATA_UNAVAILABLE
    assignee = resolve_current_assignee(issue.id)
    inputs = AlertDeliveryWorkflowInputs.build(
        notification_id="",
        team_id=team_id,
        issue_id=issue_id,
        event="$error_tracking_issue_created",
        issue_name=issue.name,
        issue_description=issue.description,
        # Raw, as the issue-created producers emit it.
        status=issue.status,
        assignee=assignee.property_value if assignee is not None else None,
        severity=issue.severity,
        fingerprint=fingerprint or None,
        first_seen=issue.created_at.isoformat(),
    )
    return evaluate_lifecycle_filters(filters, inputs, None, log_context={"issue_id": issue_id})


class _EventPropertiesInputs:
    """Adapter for the lifecycle event-properties protocol."""

    class _Snapshot:
        def __init__(self, created_at: str) -> None:
            self.created_at = created_at

    def __init__(self, inputs: AlertDeliveryWorkflowInputs) -> None:
        self.team_id = inputs.team_id
        self.event_uuid = inputs.event_uuid or ""
        self.event_timestamp = inputs.event_timestamp or ""
        self.issue = self._Snapshot(inputs.first_seen or "")


def fetch_exception_properties(inputs: AlertDeliveryWorkflowInputs) -> dict[str, object] | None:
    """The triggering exception's properties, for openers with configured filters.

    Ingestion transitions carry the event uuid: the Redis handoff (with a
    ClickHouse fallback) that the lifecycle activities already use serves those,
    and a miss raises so the activity retries. Manual transitions (reopen, assign)
    have no triggering event and get no lookup (a bulk action would turn into one
    ClickHouse scan per issue): None tells the filter the data is unavailable.
    """
    if not inputs.event_uuid:
        return None
    team = Team.objects.get(id=inputs.team_id)
    return fetch_event_properties(team, _EventPropertiesInputs(inputs))
