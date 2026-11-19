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

from products.error_tracking.backend.temporal.issue_change_cleanup.types import IssueChangeCleanupInputs
from products.error_tracking.backend.temporal.issue_change_cleanup.workflow import WORKFLOW_NAME

SCHEDULE_ID = "error-tracking-issue-change-cleanup-schedule"
SCHEDULE_CATCHUP_WINDOW = timedelta(days=1)


async def create_error_tracking_issue_change_cleanup_schedule(client: Client) -> None:
    schedule = Schedule(
        action=ScheduleActionStartWorkflow(
            WORKFLOW_NAME,
            IssueChangeCleanupInputs(),
            id=SCHEDULE_ID,
            task_queue=settings.ERROR_TRACKING_TASK_QUEUE,
        ),
        spec=ScheduleSpec(
            calendars=[
                ScheduleCalendarSpec(
                    # An hour after the spike event cleanup, so the two do not run together.
                    comment="Daily at 5 AM UTC",
                    hour=[ScheduleRange(start=5, end=5)],
                )
            ]
        ),
        policy=SchedulePolicy(overlap=ScheduleOverlapPolicy.SKIP, catchup_window=SCHEDULE_CATCHUP_WINDOW),
    )

    if await a_schedule_exists(client, SCHEDULE_ID):
        await a_update_schedule(client, SCHEDULE_ID, schedule)
    else:
        await a_create_schedule(client, SCHEDULE_ID, schedule, trigger_immediately=False)
