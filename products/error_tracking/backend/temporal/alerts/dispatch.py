"""Starts alert delivery workflows for lifecycle transitions.

Two durable callers: the lifecycle workflows run it as a retried activity
(ingestion-driven transitions), and a Celery task with retries runs it for the
manual transitions Django mutations queue after commit. Failures raise so the
caller's retry policy owns recovery; starts are idempotent on the notification id.
"""

import asyncio
from datetime import timedelta

from django.conf import settings

import structlog
from temporalio.client import Client
from temporalio.common import WorkflowIDReusePolicy
from temporalio.exceptions import WorkflowAlreadyStartedError

from posthog.temporal.common.client import async_connect

from products.error_tracking.backend.logic.alerts import native_alerts_enabled
from products.error_tracking.backend.models import ErrorTrackingAlert
from products.error_tracking.backend.temporal.alerts.types import AlertDeliveryWorkflowInputs
from products.error_tracking.backend.temporal.alerts.workflow import WORKFLOW_NAME, ErrorTrackingAlertDeliveryWorkflow

logger = structlog.get_logger(__name__)

# Bounds the connect handshake and each start individually; the caller retries a
# stalled Temporal instead of holding its worker.
DISPATCH_TIMEOUT = timedelta(seconds=10)
DISPATCH_CONCURRENCY = 8


class AlertDispatchError(Exception):
    """At least one start was not accepted; the batch is safe to retry as a whole."""


def team_has_enabled_alerts(team_id: int) -> bool:
    return ErrorTrackingAlert.objects.for_team(team_id).filter(enabled=True).exists()


def alert_dispatch_enabled(team_id: int) -> bool:
    # Cheap opt-in gates, in cost order: teams without enabled alert rows never
    # evaluate the flag, and teams outside the flag never start a workflow.
    return team_has_enabled_alerts(team_id) and native_alerts_enabled(team_id)


async def _start_one(temporal: Client, inputs: AlertDeliveryWorkflowInputs, limit: asyncio.Semaphore) -> bool:
    async with limit:
        try:
            await asyncio.wait_for(
                temporal.start_workflow(
                    WORKFLOW_NAME,
                    inputs,
                    id=ErrorTrackingAlertDeliveryWorkflow.workflow_id_for(inputs.notification_id),
                    task_queue=settings.ERROR_TRACKING_TASK_QUEUE,
                    # A redelivered start after the first run completed must be a no-op
                    # (the default ALLOW_DUPLICATE would run it again); failed runs stay
                    # retryable by a fresh start.
                    id_reuse_policy=WorkflowIDReusePolicy.ALLOW_DUPLICATE_FAILED_ONLY,
                ),
                timeout=DISPATCH_TIMEOUT.total_seconds(),
            )
        except WorkflowAlreadyStartedError:
            return True
        except Exception:
            logger.exception(
                "error_tracking_alert_delivery_dispatch_failed",
                team_id=inputs.team_id,
                lifecycle_event=inputs.event,
                notification_id=inputs.notification_id,
            )
            return False
    return True


async def _connect_and_start(batch: list[AlertDeliveryWorkflowInputs]) -> None:
    temporal = await asyncio.wait_for(async_connect(), timeout=DISPATCH_TIMEOUT.total_seconds())
    limit = asyncio.Semaphore(DISPATCH_CONCURRENCY)
    accepted = await asyncio.gather(*(_start_one(temporal, inputs, limit) for inputs in batch))
    if not all(accepted):
        raise AlertDispatchError(f"{accepted.count(False)} of {len(batch)} alert delivery starts were not accepted")


def start_alert_delivery_workflows(batch: list[AlertDeliveryWorkflowInputs]) -> None:
    """Start one delivery workflow per transition, all for the same team, over one connection.

    Returns without touching Temporal when the team has no enabled alerts or is
    outside the flag. Raises `AlertDispatchError` (or the connect failure) when any
    start was not accepted, so the caller's retry re-drives the whole batch.
    """
    if not batch:
        return
    team_ids = {inputs.team_id for inputs in batch}
    if len(team_ids) != 1:
        raise ValueError("Alert delivery batches are per team")
    if not alert_dispatch_enabled(batch[0].team_id):
        return
    asyncio.run(_connect_and_start(batch))


def start_alert_delivery_workflow(inputs: AlertDeliveryWorkflowInputs) -> None:
    start_alert_delivery_workflows([inputs])
