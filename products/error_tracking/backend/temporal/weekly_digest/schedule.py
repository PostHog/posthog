from datetime import timedelta

from django.conf import settings

from temporalio import common
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

from products.error_tracking.backend.temporal.weekly_digest.types import WeeklyDigestInputs
from products.error_tracking.backend.temporal.weekly_digest.workflow import WORKFLOW_NAME

SCHEDULE_ID = "error-tracking-weekly-digest-schedule"
# Fire late if Temporal was down over the Monday-morning slot, but never roll a
# missed week into the next: digest queries anchor on now(), so a day-late run
# would report a shifted window.
SCHEDULE_CATCHUP_WINDOW = timedelta(hours=6)


async def create_error_tracking_weekly_digest_schedule(client: Client) -> None:
    weekly_digest_schedule = Schedule(
        action=ScheduleActionStartWorkflow(
            WORKFLOW_NAME,
            # dry_run defaults to True as a manual-run fail-safe; the schedule is the
            # one caller that must send for real.
            WeeklyDigestInputs(dry_run=False),
            id=SCHEDULE_ID,
            task_queue=settings.ERROR_TRACKING_TASK_QUEUE,
            retry_policy=common.RetryPolicy(maximum_attempts=1),
        ),
        spec=ScheduleSpec(
            calendars=[
                ScheduleCalendarSpec(
                    comment="Mondays at 08:30 UTC",
                    day_of_week=[ScheduleRange(start=1, end=1)],
                    hour=[ScheduleRange(start=8, end=8)],
                    minute=[ScheduleRange(start=30, end=30)],
                )
            ]
        ),
        policy=SchedulePolicy(overlap=ScheduleOverlapPolicy.SKIP, catchup_window=SCHEDULE_CATCHUP_WINDOW),
    )

    if await a_schedule_exists(client, SCHEDULE_ID):
        await a_update_schedule(client, SCHEDULE_ID, weekly_digest_schedule)
    else:
        await a_create_schedule(client, SCHEDULE_ID, weekly_digest_schedule, trigger_immediately=False)
