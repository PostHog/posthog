"""Starts the alert delivery workflow for a lifecycle transition.

Called from two places: the Temporal lifecycle activities (ingestion-driven
transitions) and Django mutation paths via `transaction.on_commit` (manual
transitions). Both callers must never fail because of alerting, so this module
swallows and logs every error.
"""

import asyncio

from django.conf import settings

import structlog
from temporalio.common import WorkflowIDReusePolicy
from temporalio.exceptions import WorkflowAlreadyStartedError

from posthog.temporal.common.client import sync_connect

from products.error_tracking.backend.logic.alerts import native_alerts_enabled
from products.error_tracking.backend.models import ErrorTrackingAlert
from products.error_tracking.backend.temporal.alerts.types import AlertDeliveryWorkflowInputs
from products.error_tracking.backend.temporal.alerts.workflow import WORKFLOW_NAME, ErrorTrackingAlertDeliveryWorkflow

logger = structlog.get_logger(__name__)

# Issue names/descriptions are unbounded text; notifications only need a headline,
# and an oversized Temporal payload (~2 MiB cap) would silently skip the alert.
MAX_ISSUE_NAME_LENGTH = 500
MAX_ISSUE_DESCRIPTION_LENGTH = 5000


def _truncate(value: str | None, limit: int) -> str | None:
    if value is None or len(value) <= limit:
        return value
    return value[: limit - 1] + "…"


def start_alert_delivery_workflow(
    *,
    team_id: int,
    event: str,
    issue_id: str,
    notification_id: str,
    issue_name: str | None = None,
    issue_description: str | None = None,
    status: str | None = None,
    assignee: str | None = None,
    actor_email: str | None = None,
    event_uuid: str | None = None,
    event_timestamp: str | None = None,
    extra: dict[str, str] | None = None,
) -> None:
    try:
        # Cheap opt-in gates, in cost order: teams without enabled alert rows never
        # evaluate the flag, and teams outside the flag never start a workflow.
        if not ErrorTrackingAlert.objects.for_team(team_id).filter(enabled=True).exists():
            return
        if not native_alerts_enabled(team_id):
            return

        inputs = AlertDeliveryWorkflowInputs(
            notification_id=notification_id,
            team_id=team_id,
            issue_id=issue_id,
            event=event,
            issue_name=_truncate(issue_name, MAX_ISSUE_NAME_LENGTH),
            issue_description=_truncate(issue_description, MAX_ISSUE_DESCRIPTION_LENGTH),
            status=status,
            assignee=assignee,
            actor_email=actor_email,
            event_uuid=event_uuid,
            event_timestamp=event_timestamp,
            extra=extra,
        )
        temporal = sync_connect()
        asyncio.run(
            temporal.start_workflow(
                WORKFLOW_NAME,
                inputs,
                id=ErrorTrackingAlertDeliveryWorkflow.workflow_id_for(notification_id),
                task_queue=settings.ERROR_TRACKING_LIFECYCLE_TASK_QUEUE,
                # A redelivered start after the first run completed must be a no-op
                # (the default ALLOW_DUPLICATE would run it again); failed runs stay
                # retryable by a fresh start.
                id_reuse_policy=WorkflowIDReusePolicy.ALLOW_DUPLICATE_FAILED_ONLY,
            )
        )
    except WorkflowAlreadyStartedError:
        pass
    except Exception:
        logger.exception(
            "error_tracking_alert_delivery_dispatch_failed",
            team_id=team_id,
            lifecycle_event=event,
            notification_id=notification_id,
        )
