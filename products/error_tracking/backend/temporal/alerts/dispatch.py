"""Starts the alert delivery workflow for a lifecycle transition.

Called from two places: the Temporal lifecycle activities (ingestion-driven
transitions) and Django mutation paths via `transaction.on_commit` (manual
transitions). Both callers must never fail because of alerting, so this module
swallows and logs every error.
"""

import asyncio

from django.conf import settings

import structlog
import temporalio.client

from posthog.temporal.common.client import sync_connect

from products.error_tracking.backend.models import ErrorTrackingAlert
from products.error_tracking.backend.temporal.alerts.types import AlertDeliveryWorkflowInputs

logger = structlog.get_logger(__name__)

WORKFLOW_NAME = "error-tracking-alert-delivery"


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
    extra: dict[str, str] | None = None,
) -> None:
    try:
        # Cheap opt-in gate: teams without alert rows never pay for a Temporal call.
        if not ErrorTrackingAlert.objects.for_team(team_id).filter(enabled=True).exists():
            return

        inputs = AlertDeliveryWorkflowInputs(
            notification_id=notification_id,
            team_id=team_id,
            issue_id=issue_id,
            event=event,
            issue_name=issue_name,
            issue_description=issue_description,
            status=status,
            assignee=assignee,
            actor_email=actor_email,
            extra=extra,
        )
        temporal = sync_connect()
        asyncio.run(
            temporal.start_workflow(
                WORKFLOW_NAME,
                inputs,
                id=f"{WORKFLOW_NAME}-{notification_id}",
                task_queue=settings.ERROR_TRACKING_LIFECYCLE_TASK_QUEUE,
            )
        )
    except temporalio.client.WorkflowAlreadyStartedError:
        pass
    except Exception:
        logger.exception(
            "error_tracking_alert_delivery_dispatch_failed",
            team_id=team_id,
            event=event,
            notification_id=notification_id,
        )
