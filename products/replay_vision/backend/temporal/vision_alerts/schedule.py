"""Temporal schedule for the replay vision alert check workflow."""

from django.conf import settings

from temporalio.client import (
    Client,
    Schedule,
    ScheduleActionStartWorkflow,
    ScheduleOverlapPolicy,
    SchedulePolicy,
    ScheduleSpec,
)

from posthog.temporal.common.schedule import a_create_schedule, a_schedule_exists, a_update_schedule

from products.replay_vision.backend.temporal.vision_alerts.activities import CheckVisionAlertsInput
from products.replay_vision.backend.temporal.vision_alerts.constants import SCHEDULE_CRON, SCHEDULE_ID, WORKFLOW_NAME


async def create_vision_alert_check_schedule(client: Client) -> None:
    schedule = Schedule(
        action=ScheduleActionStartWorkflow(
            WORKFLOW_NAME,
            CheckVisionAlertsInput().model_dump(),
            id=SCHEDULE_ID,
            task_queue=settings.REPLAY_VISION_TASK_QUEUE,
        ),
        spec=ScheduleSpec(cron_expressions=[SCHEDULE_CRON]),
        policy=SchedulePolicy(overlap=ScheduleOverlapPolicy.SKIP),
    )

    if await a_schedule_exists(client, SCHEDULE_ID):
        await a_update_schedule(client, SCHEDULE_ID, schedule)
    else:
        await a_create_schedule(client, SCHEDULE_ID, schedule, trigger_immediately=False)
