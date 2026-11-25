from datetime import timedelta

from django.conf import settings

from temporalio.client import (
    Client,
    Schedule,
    ScheduleActionStartWorkflow,
    ScheduleCalendarSpec,
    ScheduleOverlapPolicy,
    SchedulePolicy,
    ScheduleRange,
    ScheduleSpec,
)

from posthog.temporal.common.schedule import a_create_schedule, a_schedule_exists, a_update_schedule

from products.error_tracking.backend.temporal.tag_rule_sweep.types import TagRuleSweepInputs
from products.error_tracking.backend.temporal.tag_rule_sweep.workflow import WORKFLOW_NAME

SCHEDULE_ID = "error-tracking-tag-rule-sweep-schedule"
SCHEDULE_CATCHUP_WINDOW = timedelta(days=1)


async def create_error_tracking_tag_rule_sweep_schedule(client: Client) -> None:
    tag_rule_sweep_schedule = Schedule(
        action=ScheduleActionStartWorkflow(
            WORKFLOW_NAME,
            TagRuleSweepInputs(),
            id=SCHEDULE_ID,
            task_queue=settings.ERROR_TRACKING_TASK_QUEUE,
        ),
        spec=ScheduleSpec(
            calendars=[
                ScheduleCalendarSpec(
                    comment="Daily at 5 AM UTC",
                    hour=[ScheduleRange(start=5, end=5)],
                )
            ]
        ),
        policy=SchedulePolicy(overlap=ScheduleOverlapPolicy.SKIP, catchup_window=SCHEDULE_CATCHUP_WINDOW),
    )

    if await a_schedule_exists(client, SCHEDULE_ID):
        await a_update_schedule(client, SCHEDULE_ID, tag_rule_sweep_schedule, keep_paused=True)
    else:
        await a_create_schedule(client, SCHEDULE_ID, tag_rule_sweep_schedule, trigger_immediately=False)
